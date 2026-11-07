"""Parsed Music Assistant responses (plain data classes, no I/O)."""

from __future__ import annotations

from typing import Any


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
        # Chapters (audiobooks, sometimes podcast episodes) — list of dicts
        # with keys: position, name, start (sec), end (sec | None)
        self.chapters: list[dict] = list(metadata.get("chapters") or [])

        # Provider mappings (other providers where this item exists)
        self.provider_mappings: list[dict] = data.get("provider_mappings", [])

        # Type-specific fields
        self.artists: list[dict] = data.get("artists", [])
        self.album: dict | None = data.get("album")
        self.duration: int = data.get("duration", 0)
        self.owner: str = data.get("owner", "")

        # Podcast episode-specific fields (present only when media_type == podcast_episode)
        self.position: int = data.get("position", 0)
        self.fully_played: bool | None = data.get("fully_played")
        self.resume_position_ms: int | None = data.get("resume_position_ms")

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
            "position": self.position,
            "fully_played": self.fully_played,
            "resume_position_ms": self.resume_position_ms,
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
