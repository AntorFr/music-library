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
import contextlib
import logging
import urllib.parse
import uuid
from typing import Any

import httpx
import websockets
from websockets.asyncio.client import ClientConnection

from app.config import settings
from app.services.ma_helpers import (  # noqa: F401  (re-exported)
    _episode_fetches,
    _single_flight_episodes,
    fetch_audiobook,
    fetch_podcast_episodes,
    normalize_chapters,
    resolve_ma_provider_and_id,
)
from app.services.ma_models import (  # noqa: F401  (re-exported)
    MAImage,
    MAMediaItem,
    MAPlayer,
    MASearchResults,
)

logger = logging.getLogger(__name__)


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
        # Partial result chunks keyed by message_id. MA sends these for async generators.
        self._partial_results: dict[str, list[Any]] = {}
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
        return (
            self._ws is not None
            and self._reader_task is not None
            and not self._reader_task.done()
        )

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
                    if data.get("partial"):
                        result = data.get("result")
                        chunks = self._partial_results.setdefault(msg_id, [])
                        if isinstance(result, list):
                            chunks.extend(result)
                        elif result is not None:
                            chunks.append(result)
                        continue

                    fut = self._pending.pop(msg_id)
                    chunks = self._partial_results.pop(msg_id, None)
                    if chunks is not None:
                        result = data.get("result")
                        if isinstance(result, list):
                            chunks.extend(result)
                        elif result is not None:
                            chunks.append(result)
                        data = {**data, "result": chunks}
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
            self._partial_results.clear()
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
            self._partial_results.clear()

            logger.info("Connecting to Music Assistant at %s", self.ws_url)
            # Default max_size is 1 MiB — MA can send larger single frames (e.g. a
            # podcast_episodes result for a show with many/long episodes), which the
            # client would otherwise reject with close code 1009 "message too big"
            # and silently drop the connection (surfaced to users as a generic
            # "MA WebSocket connection lost"). Disable the cap; MA is a trusted host.
            self._ws = await websockets.connect(self.ws_url, max_size=None)

            # First message from server is ServerInfoMessage
            import json
            raw = await self._ws.recv()
            self._server_info = (
                json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
            )
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
                    resp = (
                        json.loads(raw_resp)
                        if isinstance(raw_resp, str)
                        else json.loads(raw_resp.decode())
                    )
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
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
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
        except TimeoutError as exc:
            self._pending.pop(message_id, None)
            self._partial_results.pop(message_id, None)
            raise TimeoutError(f"MA command '{command}' timed out after 60s") from exc

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

    async def _get_library(
        self, media_type: str, search: str | None, limit: int | None
    ) -> list[MAMediaItem]:
        """List one media type from the MA library (single implementation)."""
        result = await self._send_command(
            f"music/{media_type}/library_items", search=search, limit=limit
        )
        return [MAMediaItem(i) for i in (result or [])]

    async def get_library_playlists(
        self, search: str | None = None, limit: int | None = None
    ) -> list[MAMediaItem]:
        """List playlists from the MA library."""
        return await self._get_library("playlists", search, limit)

    async def get_library_albums(
        self, search: str | None = None, limit: int | None = None
    ) -> list[MAMediaItem]:
        """List albums from the MA library."""
        return await self._get_library("albums", search, limit)

    async def get_library_tracks(
        self, search: str | None = None, limit: int | None = None
    ) -> list[MAMediaItem]:
        """List tracks from the MA library."""
        return await self._get_library("tracks", search, limit)

    async def get_library_radios(
        self, search: str | None = None, limit: int | None = None
    ) -> list[MAMediaItem]:
        """List radio stations from the MA library."""
        return await self._get_library("radios", search, limit)

    async def get_library_audiobooks(
        self, search: str | None = None, limit: int | None = None
    ) -> list[MAMediaItem]:
        """List audiobooks from the MA library."""
        return await self._get_library("audiobooks", search, limit)

    async def get_library_podcasts(
        self, search: str | None = None, limit: int | None = None
    ) -> list[MAMediaItem]:
        """List podcasts from the MA library."""
        return await self._get_library("podcasts", search, limit)

    async def get_podcast_episodes(
        self, item_id: str, provider: str
    ) -> list[MAMediaItem]:
        """List episodes of a podcast, newest first.

        MA always re-fetches episodes from the provider so resume position
        info stays fresh — do not cache the result.

        MA numbers episodes oldest to newest (the latest has the highest
        ``position``), so sorting descending puts the latest episode on the
        first page of every paginated consumer. Audiobook chapters keep reading
        order — see :func:`normalize_chapters`.
        """
        result = await self._send_command(
            "music/podcasts/podcast_episodes",
            item_id=item_id,
            provider_instance_id_or_domain=provider,
        )
        episodes = [MAMediaItem(i) for i in (result or [])]
        episodes.sort(key=lambda e: e.position, reverse=True)
        return episodes

    async def get_playlist_tracks(
        self, item_id: str, provider: str
    ) -> list[MAMediaItem]:
        """List the tracks of a playlist, as seen through one provider instance."""
        result = await self._send_command(
            "music/playlists/playlist_tracks",
            item_id=item_id,
            provider_instance_id_or_domain=provider,
        )
        return [MAMediaItem(i) for i in (result or [])]

    async def get_album_tracks(
        self, item_id: str, provider: str
    ) -> list[MAMediaItem]:
        """List the tracks of an album, as seen through one provider instance."""
        result = await self._send_command(
            "music/albums/album_tracks",
            item_id=item_id,
            provider_instance_id_or_domain=provider,
        )
        return [MAMediaItem(i) for i in (result or [])]

    async def get_provider_configs(self) -> list[dict]:
        """Every configured provider instance, loaded or not (``status``, ``last_error``)."""
        return await self._send_command("config/providers") or []

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

    async def seek(self, queue_id: str, position: int) -> None:
        """Seek to position (in seconds) on the current queue item."""
        await self._send_command(
            "player_queues/seek", queue_id=queue_id, position=int(position)
        )

    # --- High-level: Transport & playback controls (queue-level) ---

    async def play(self, queue_id: str) -> None:
        """Resume playback of the queue."""
        await self._send_command("player_queues/play", queue_id=queue_id)

    async def pause(self, queue_id: str) -> None:
        """Pause the queue."""
        await self._send_command("player_queues/pause", queue_id=queue_id)

    async def play_pause(self, queue_id: str) -> None:
        """Toggle play/pause."""
        await self._send_command("player_queues/play_pause", queue_id=queue_id)

    async def stop(self, queue_id: str) -> None:
        """Stop the queue."""
        await self._send_command("player_queues/stop", queue_id=queue_id)

    async def next_track(self, queue_id: str) -> None:
        """Skip to the next item."""
        await self._send_command("player_queues/next", queue_id=queue_id)

    async def previous_track(self, queue_id: str) -> None:
        """Go to the previous item."""
        await self._send_command("player_queues/previous", queue_id=queue_id)

    async def set_shuffle(self, queue_id: str, enabled: bool) -> None:
        """Enable/disable shuffle on the queue."""
        await self._send_command(
            "player_queues/shuffle", queue_id=queue_id, shuffle_enabled=bool(enabled)
        )

    async def set_repeat(self, queue_id: str, mode: str) -> None:
        """Set repeat mode: off | one | all."""
        await self._send_command(
            "player_queues/repeat", queue_id=queue_id, repeat_mode=mode
        )

    # --- High-level: Player controls (player-level; player_id == queue_id in MA) ---

    async def set_volume(self, player_id: str, level: int) -> None:
        """Set absolute volume (0..100)."""
        level = max(0, min(100, int(level)))
        await self._send_command(
            "players/cmd/volume_set", player_id=player_id, volume_level=level
        )

    async def volume_up(self, player_id: str) -> None:
        """Step the volume up."""
        await self._send_command("players/cmd/volume_up", player_id=player_id)

    async def volume_down(self, player_id: str) -> None:
        """Step the volume down."""
        await self._send_command("players/cmd/volume_down", player_id=player_id)

    async def set_mute(self, player_id: str, muted: bool) -> None:
        """Mute/unmute the player."""
        await self._send_command(
            "players/cmd/volume_mute", player_id=player_id, muted=bool(muted)
        )

    async def set_power(self, player_id: str, powered: bool) -> None:
        """Power the player on/off."""
        await self._send_command(
            "players/cmd/power", player_id=player_id, powered=bool(powered)
        )

    # --- High-level: Now-playing state ---

    async def get_queue(self, queue_id: str) -> dict | None:
        """Return the raw queue dict for queue_id, or None if not found."""
        for q in await self.get_player_queues():
            if q.get("queue_id") == queue_id:
                return q
        return None

    async def get_now_playing(self, queue_id: str) -> dict:
        """Build a compact now-playing snapshot for a queue.

        Combines the queue (current item, state, shuffle, repeat, elapsed) with the
        matching player (volume, mute, power). Best-effort: MA field shapes vary, so every
        lookup is defensive and falls back to None.
        """
        queue = await self.get_queue(queue_id)
        player = None
        for p in await self.get_players():
            if p.player_id == queue_id:
                player = p
                break

        out: dict[str, Any] = {
            "queue_id": queue_id,
            "available": queue is not None,
            "state": "idle",
            "title": None,
            "artist": None,
            "cover_url": None,
            "uri": None,
            "duration_s": None,
            "position_s": None,
            "volume": None,
            "muted": None,
            "shuffle": None,
            "repeat": None,
            "powered": None,
        }

        if queue:
            out["state"] = queue.get("state") or "idle"
            out["shuffle"] = queue.get("shuffle_enabled")
            out["repeat"] = queue.get("repeat_mode")
            elapsed = queue.get("elapsed_time")
            if elapsed is None:
                elapsed = queue.get("corrected_elapsed_time")
            out["position_s"] = int(elapsed) if elapsed is not None else None

            cur = queue.get("current_item") or {}
            media_item = cur.get("media_item") or {}
            out["title"] = cur.get("name") or media_item.get("name")
            out["uri"] = cur.get("uri") or media_item.get("uri")
            dur = cur.get("duration") or media_item.get("duration")
            out["duration_s"] = int(dur) if dur else None
            artists = media_item.get("artists") or []
            out["artist"] = ", ".join(a.get("name", "") for a in artists if a.get("name")) or None
            images = (media_item.get("metadata") or {}).get("images") or []
            if images:
                # Original URL (size=0, no third-party resizer): the now-playing endpoint
                # wraps it in our own signed thumbnail proxy for embedded clients.
                out["cover_url"] = self.get_image_url(MAImage(images[0]), size=0)

        if player:
            out["volume"] = player.volume_level
            out["powered"] = player.powered
            out["muted"] = player._raw.get("volume_muted")

        return out

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
