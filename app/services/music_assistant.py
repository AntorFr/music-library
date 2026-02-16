"""
Music Assistant WebSocket client.

Lightweight client to interact with Music Assistant server for:
- Searching and retrieving media item info (playlists, albums, tracks, radios…)
- Getting cover/thumbnail image URLs
- Playing media on player queues
- Listing available players

Uses the MA WebSocket API (same protocol as the official client).
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
import uuid
from typing import Any

import httpx
import websockets
from websockets.asyncio.client import ClientConnection

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes for parsed MA responses
# ---------------------------------------------------------------------------

class MAImage:
    """Represents an image attached to a media item."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.type: str = data.get("type", "")  # thumb, fanart, logo…
        self.path: str = data.get("path", "")
        self.provider: str = data.get("provider", "")
        self.remotely_accessible: bool = data.get("remotely_accessible", False)

    def __repr__(self) -> str:
        return f"<MAImage {self.type} provider={self.provider}>"


class MAMediaItem:
    """Parsed media item from Music Assistant."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._raw = data
        self.item_id: str = str(data.get("item_id", ""))
        self.provider: str = data.get("provider", "")
        self.name: str = data.get("name", "")
        self.media_type: str = data.get("media_type", "")
        self.uri: str = data.get("uri", "")
        self.sort_name: str = data.get("sort_name", "")
        self.available: bool = data.get("available", True)

        # Metadata
        metadata = data.get("metadata") or {}
        self.description: str = metadata.get("description", "")
        self.images: list[MAImage] = [
            MAImage(img) for img in (metadata.get("images") or [])
        ]

        # Provider mappings (other providers where this item exists)
        self.provider_mappings: list[dict] = data.get("provider_mappings", [])

        # Type-specific fields
        self.artists: list[dict] = data.get("artists", [])
        self.album: dict | None = data.get("album")
        self.duration: int = data.get("duration", 0)
        self.owner: str = data.get("owner", "")

    @property
    def artist_names(self) -> list[str]:
        """Extract artist names from the artists list."""
        return [a.get("name", "") for a in self.artists if a.get("name")]

    @property
    def artist_str(self) -> str:
        """Comma-separated artist names."""
        return ", ".join(self.artist_names)

    @property
    def album_name(self) -> str:
        """Album name if available."""
        if self.album:
            return self.album.get("name", "")
        return ""

    @property
    def thumb_image(self) -> MAImage | None:
        """Return the first thumbnail image, if any."""
        for img in self.images:
            if img.type == "thumb":
                return img
        return self.images[0] if self.images else None

    def to_dict(self) -> dict[str, Any]:
        """Serializable summary of the item."""
        thumb = self.thumb_image
        return {
            "item_id": self.item_id,
            "provider": self.provider,
            "name": self.name,
            "media_type": self.media_type,
            "uri": self.uri,
            "artists": self.artist_str,
            "album": self.album_name,
            "duration": self.duration,
            "description": self.description,
            "thumb_url": thumb.path if thumb else None,
            "thumb_provider": thumb.provider if thumb else None,
            "thumb_remotely_accessible": thumb.remotely_accessible if thumb else False,
        }

    def __repr__(self) -> str:
        return f"<MAMediaItem '{self.name}' ({self.media_type}) uri={self.uri}>"


class MAPlayer:
    """Parsed player info from Music Assistant."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._raw = data
        self.player_id: str = data.get("player_id", "")
        self.name: str = data.get("display_name", "") or data.get("name", "")
        self.available: bool = data.get("available", False)
        self.powered: bool = data.get("powered", False)
        self.state: str = data.get("state", "")  # playing, paused, idle, off
        self.volume_level: int = data.get("volume_level", 0)
        self.type: str = data.get("type", "")
        self.provider: str = data.get("provider", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "available": self.available,
            "powered": self.powered,
            "state": self.state,
            "volume_level": self.volume_level,
            "type": self.type,
            "provider": self.provider,
        }

    def __repr__(self) -> str:
        return f"<MAPlayer '{self.name}' ({self.state})>"


class MASearchResults:
    """Parsed search results from Music Assistant."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.artists: list[MAMediaItem] = [
            MAMediaItem(i) for i in (data.get("artists") or [])
        ]
        self.albums: list[MAMediaItem] = [
            MAMediaItem(i) for i in (data.get("albums") or [])
        ]
        self.tracks: list[MAMediaItem] = [
            MAMediaItem(i) for i in (data.get("tracks") or [])
        ]
        self.playlists: list[MAMediaItem] = [
            MAMediaItem(i) for i in (data.get("playlists") or [])
        ]
        self.radio: list[MAMediaItem] = [
            MAMediaItem(i) for i in (data.get("radio") or [])
        ]
        self.audiobooks: list[MAMediaItem] = [
            MAMediaItem(i) for i in (data.get("audiobooks") or [])
        ]
        self.podcasts: list[MAMediaItem] = [
            MAMediaItem(i) for i in (data.get("podcasts") or [])
        ]

    @property
    def all_items(self) -> list[MAMediaItem]:
        """Flatten all results into a single list."""
        return (
            self.tracks + self.albums + self.playlists
            + self.artists + self.radio + self.audiobooks + self.podcasts
        )


# ---------------------------------------------------------------------------
# WebSocket client
# ---------------------------------------------------------------------------

class MusicAssistantClient:
    """
    Lightweight async client for Music Assistant WebSocket API.

    Uses a background reader task so multiple commands can be in-flight
    concurrently (no global lock bottleneck).

    Usage:
        async with MusicAssistantClient() as ma:
            results = await ma.search("Daft Punk")
            for item in results.tracks:
                print(item.name, item.artist_str)
                thumb_url = ma.get_image_url(item.thumb_image, size=300)
    """

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
    ) -> None:
        self._base_url = (url or settings.music_assistant_url).rstrip("/")
        self._token = token or settings.music_assistant_token
        self._ws: ClientConnection | None = None
        self._server_info: dict[str, Any] | None = None
        # Pending futures keyed by message_id — allows concurrent commands
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task | None = None
        self._write_lock = asyncio.Lock()  # protect ws.send only (fast)
        self._connect_lock = asyncio.Lock()  # prevent concurrent reconnect

    @property
    def ws_url(self) -> str:
        """WebSocket endpoint URL."""
        base = self._base_url.replace("http://", "ws://").replace("https://", "wss://")
        return f"{base}/ws"

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def connected(self) -> bool:
        return self._ws is not None and self._reader_task is not None and not self._reader_task.done()

    # --- Background reader ---

    async def _reader_loop(self) -> None:
        """Background task that reads all WS messages and dispatches responses."""
        import json
        try:
            async for raw in self._ws:  # type: ignore[union-attr]
                data = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
                # Skip event / broadcast messages
                if data.get("event"):
                    continue
                msg_id = data.get("message_id")
                if msg_id and msg_id in self._pending:
                    fut = self._pending.pop(msg_id)
                    if not fut.done():
                        fut.set_result(data)
        except websockets.ConnectionClosed as exc:
            logger.warning("MA WebSocket connection closed: %s", exc)
        except Exception as exc:
            logger.error("MA reader loop error: %s", exc)
        finally:
            # Fail all pending futures so callers don't hang
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("MA WebSocket connection lost"))
            self._pending.clear()
            self._ws = None
            logger.info("MA reader loop exited")

    # --- Connection management ---

    async def connect(self) -> None:
        """Open WebSocket connection and authenticate if needed."""
        if self.connected:
            return

        async with self._connect_lock:
            # Double-check after acquiring lock
            if self.connected:
                return

            # Clean up old state
            if self._reader_task and not self._reader_task.done():
                self._reader_task.cancel()
            self._pending.clear()

            logger.info("Connecting to Music Assistant at %s", self.ws_url)
            self._ws = await websockets.connect(self.ws_url)

            # First message from server is ServerInfoMessage
            import json
            raw = await self._ws.recv()
            self._server_info = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
            logger.info(
                "Connected to MA server v%s (schema %s)",
                self._server_info.get("server_version"),
                self._server_info.get("schema_version"),
            )

            # Authenticate BEFORE starting reader loop (sequential handshake)
            schema_version = self._server_info.get("schema_version", 0)
            if schema_version >= 28 and self._token:
                message_id = uuid.uuid4().hex
                msg = {
                    "message_id": message_id,
                    "command": "auth",
                    "args": {"token": self._token},
                }
                await self._ws.send(json.dumps(msg))
                # Read until auth response
                while True:
                    raw_resp = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
                    resp = json.loads(raw_resp) if isinstance(raw_resp, str) else json.loads(raw_resp.decode())
                    if resp.get("event"):
                        continue
                    if resp.get("message_id") == message_id:
                        if "error_code" in resp:
                            await self._ws.close()
                            self._ws = None
                            raise ConnectionError("Music Assistant authentication failed")
                        logger.info("Authenticated with MA server")
                        break

            # Start background reader
            self._reader_task = asyncio.create_task(self._reader_loop())

    async def _ensure_connected(self) -> None:
        """Reconnect if the connection was lost."""
        if not self.connected:
            logger.info("MA connection lost — reconnecting…")
            self._ws = None
            await self.connect()

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        self._reader_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._pending.clear()
        logger.info("Disconnected from Music Assistant")

    async def __aenter__(self) -> MusicAssistantClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()

    # --- Low-level command ---

    async def _send_command(self, command: str, **kwargs: Any) -> Any:
        """Send a command and wait for the matching response (non-blocking)."""
        await self._ensure_connected()
        if not self._ws:
            raise ConnectionError("Not connected to Music Assistant")

        import json

        message_id = uuid.uuid4().hex
        msg = {
            "message_id": message_id,
            "command": command,
            "args": kwargs,
        }

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[message_id] = fut

        async with self._write_lock:
            await self._ws.send(json.dumps(msg))

        try:
            response = await asyncio.wait_for(fut, timeout=60.0)
        except asyncio.TimeoutError:
            self._pending.pop(message_id, None)
            raise TimeoutError(f"MA command '{command}' timed out after 60s")

        if "error_code" in response:
            error_msg = response.get("details", response.get("error_code", "Unknown error"))
            raise RuntimeError(f"MA command '{command}' failed: {error_msg}")

        return response.get("result")

    # --- High-level: Search & Browse ---

    async def search(
        self,
        query: str,
        media_types: list[str] | None = None,
        limit: int = 25,
        library_only: bool = False,
    ) -> MASearchResults:
        """
        Search for media items across all providers.

        Args:
            query: Search text.
            media_types: Filter by types (e.g. ["track", "playlist", "album"]).
                         None = all types.
            limit: Max results per type.
            library_only: Only search in library.

        Returns:
            MASearchResults with categorized results.
        """
        result = await self._send_command(
            "music/search",
            search_query=query,
            media_types=media_types,
            limit=limit,
            library_only=library_only,
        )
        return MASearchResults(result or {})

    async def get_item_by_uri(self, uri: str) -> MAMediaItem:
        """
        Get a single media item by its URI.

        Args:
            uri: MA URI like "spotify://playlist/37i9dQZF1DXcBWIGoYBM5M"
                 or "library://track/123"

        Returns:
            Parsed MAMediaItem with full info.
        """
        result = await self._send_command("music/item_by_uri", uri=uri)
        return MAMediaItem(result)

    async def get_item(
        self,
        media_type: str,
        item_id: str,
        provider: str,
    ) -> MAMediaItem:
        """Get a single media item by type, id, and provider."""
        result = await self._send_command(
            "music/item",
            media_type=media_type,
            item_id=item_id,
            provider_instance_id_or_domain=provider,
        )
        return MAMediaItem(result)

    # --- High-level: Library listings ---

    async def get_library_playlists(
        self, search: str | None = None, limit: int | None = None
    ) -> list[MAMediaItem]:
        """List playlists from the MA library."""
        result = await self._send_command(
            "music/playlists/library_items", search=search, limit=limit
        )
        return [MAMediaItem(i) for i in (result or [])]

    async def get_library_albums(
        self, search: str | None = None, limit: int | None = None
    ) -> list[MAMediaItem]:
        """List albums from the MA library."""
        result = await self._send_command(
            "music/albums/library_items", search=search, limit=limit
        )
        return [MAMediaItem(i) for i in (result or [])]

    async def get_library_tracks(
        self, search: str | None = None, limit: int | None = None
    ) -> list[MAMediaItem]:
        """List tracks from the MA library."""
        result = await self._send_command(
            "music/tracks/library_items", search=search, limit=limit
        )
        return [MAMediaItem(i) for i in (result or [])]

    async def get_library_radios(
        self, search: str | None = None, limit: int | None = None
    ) -> list[MAMediaItem]:
        """List radio stations from the MA library."""
        result = await self._send_command(
            "music/radios/library_items", search=search, limit=limit
        )
        return [MAMediaItem(i) for i in (result or [])]

    async def get_library_audiobooks(
        self, search: str | None = None, limit: int | None = None
    ) -> list[MAMediaItem]:
        """List audiobooks from the MA library."""
        result = await self._send_command(
            "music/audiobooks/library_items", search=search, limit=limit
        )
        return [MAMediaItem(i) for i in (result or [])]

    async def get_library_podcasts(
        self, search: str | None = None, limit: int | None = None
    ) -> list[MAMediaItem]:
        """List podcasts from the MA library."""
        result = await self._send_command(
            "music/podcasts/library_items", search=search, limit=limit
        )
        return [MAMediaItem(i) for i in (result or [])]

    # --- High-level: Players ---

    async def get_players(self) -> list[MAPlayer]:
        """List all available players."""
        result = await self._send_command("players/all")
        return [MAPlayer(p) for p in (result or [])]

    async def get_player_queues(self) -> list[dict]:
        """List all player queues."""
        result = await self._send_command("player_queues/all")
        return result or []

    # --- High-level: Playback ---

    async def play_media(
        self,
        queue_id: str,
        media: str | list[str],
        option: str | None = None,
        radio_mode: bool = False,
    ) -> None:
        """
        Play media on a player queue.

        Args:
            queue_id: Target player queue ID.
            media: URI string or list of URI strings.
            option: Enqueue option (play, replace, next, add, replace_next).
            radio_mode: Enable radio mode.
        """
        await self._send_command(
            "player_queues/play_media",
            queue_id=queue_id,
            media=media,
            option=option,
            radio_mode=radio_mode,
        )

    # --- Image URLs ---

    def get_image_url(self, image: MAImage | None, size: int = 0) -> str | None:
        """
        Build a usable image URL for a MAImage.

        For remotely accessible images without resize: returns direct URL.
        For others or with resize: returns the MA imageproxy URL.

        Args:
            image: MAImage object (from item.thumb_image).
            size: Desired size in px (0 = original).

        Returns:
            URL string or None if no image.
        """
        if not image:
            return None

        # Direct URL if remotely accessible and no resize needed
        if image.remotely_accessible and not size:
            return image.path

        # Resized remote image via weserv
        if image.remotely_accessible and size:
            return (
                f"https://images.weserv.nl/?url={urllib.parse.quote(image.path)}"
                f"&w={size}&h={size}&fit=cover&a=attention"
            )

        # MA image proxy for non-remote images
        encoded_url = urllib.parse.quote(urllib.parse.quote(image.path))
        return (
            f"{self._base_url}/imageproxy"
            f"?path={encoded_url}"
            f"&provider={image.provider}"
            f"&size={size}"
        )

    def get_item_image_url(self, item: MAMediaItem, size: int = 0) -> str | None:
        """Convenience: get the thumbnail URL for a media item."""
        return self.get_image_url(item.thumb_image, size=size)

    # --- Image download ---

    async def download_image(
        self,
        image: MAImage | None,
        size: int = 0,
    ) -> bytes | None:
        """
        Download image bytes for a MAImage.

        Args:
            image: MAImage object.
            size: Desired size.

        Returns:
            Raw image bytes or None.
        """
        url = self.get_image_url(image, size=size)
        if not url:
            return None

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(url, follow_redirects=True)
                resp.raise_for_status()
                return resp.content
            except httpx.HTTPError as exc:
                logger.warning("Failed to download image from %s: %s", url, exc)
                return None

    async def download_item_image(
        self, item: MAMediaItem, size: int = 0
    ) -> bytes | None:
        """Download the thumbnail image for a media item."""
        return await self.download_image(item.thumb_image, size=size)


# ---------------------------------------------------------------------------
# Singleton / FastAPI dependency
# ---------------------------------------------------------------------------

_client: MusicAssistantClient | None = None


async def get_ma_client() -> MusicAssistantClient:
    """
    FastAPI dependency — returns a connected MA client.

    The client is created once and reused. If the connection drops,
    it will reconnect automatically on next command.
    """
    global _client
    if _client is None:
        _client = MusicAssistantClient()
    if not _client.connected:
        try:
            await _client.connect()
        except Exception:
            logger.warning(
                "Could not connect to Music Assistant at %s — "
                "MA features will be unavailable.",
                settings.music_assistant_url,
            )
    return _client


async def close_ma_client() -> None:
    """Shut down the global MA client (call on app shutdown)."""
    global _client
    if _client:
        await _client.disconnect()
        _client = None
