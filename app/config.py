"""Application configuration loaded from environment variables."""

from pathlib import Path
from urllib.parse import urlparse

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with sensible defaults for local development."""

    # --- Application ---
    app_name: str = "Music Library"
    app_version: str = "0.15.0"
    debug: bool = False

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///data/library.db"

    # --- Covers ---
    covers_dir: Path = Path("data/covers")
    cover_max_size: int = 300  # px, square
    default_cover: str = "static/img/default_cover.jpg"

    # --- Thumbnails (episode artwork proxy cache) ---
    # External episode thumbnails (Music Assistant / weserv) are fetched + resized + cached
    # here once, so embedded clients pull them from us instead of hitting the slow upstream
    # proxy on every request. Sources are restricted to these hosts (anti-SSRF); the Music
    # Assistant host is always allowed in addition (see `thumb_hosts`).
    #
    # Deliberately a NON-persisted path (outside the data volume): the cache rebuilds itself
    # on demand, so wiping it on restart is free and a quick way to purge. A rolling size cap
    # evicts the oldest files (LRU by mtime) as the directory approaches the limit.
    thumbs_dir: Path = Path("/tmp/ml-thumbs")
    thumb_allowed_hosts: str = "images.weserv.nl"  # comma-separated
    thumb_cache_max_bytes: int = 1024 * 1024 * 1024  # 1 GiB; 0 disables the cap

    # --- Music Assistant ---
    music_assistant_url: str = "http://localhost:8095"
    music_assistant_token: str = ""

    # --- Home Assistant ---
    home_assistant_url: str = "http://localhost:8123"
    home_assistant_token: str = ""

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    # Dedicated, trimmed ESPHome API surface served on its own port (HTTP) so it can be
    # exposed on a fast internal network without surfacing the admin CRUD / web frontend.
    esp_port: int = 8001

    model_config = {"env_prefix": "ML_", "env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def thumb_hosts(self) -> set[str]:
        """Hosts allowed as thumbnail proxy sources (allowlist + the Music Assistant host)."""
        hosts = {h.strip().lower() for h in self.thumb_allowed_hosts.split(",") if h.strip()}
        ma_host = urlparse(self.music_assistant_url).hostname
        if ma_host:
            hosts.add(ma_host.lower())
        return hosts


settings = Settings()
