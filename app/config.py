"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with sensible defaults for local development."""

    # --- Application ---
    app_name: str = "Music Library"
    app_version: str = "0.16.0"
    debug: bool = False

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///data/library.db"

    # --- Covers ---
    covers_dir: Path = Path("data/covers")
    cover_max_size: int = 300  # px, square
    default_cover: str = "static/img/default_cover.jpg"

    # --- Thumbnails (episode/now-playing artwork proxy cache) ---
    # Embedded clients pull artwork from us, not from the original CDN: we fetch the source
    # image once, resize it ourselves (no third-party resizer), cache it, and serve it fast.
    #
    # Requests carry an HMAC signature so only URLs WE generated are honoured — this lets the
    # source be any host (Spotify CDN, podcast host, the MA imageproxy…) without an open-proxy
    # / SSRF risk and without a host allow-list to maintain. Set `thumb_signing_key` to a
    # stable secret in production; if left empty a random per-process key is used (fine, since
    # the cache is ephemeral and links are regenerated each session).
    thumb_signing_key: str = ""
    #
    # Deliberately a NON-persisted path (outside the data volume): the cache rebuilds itself
    # on demand, so wiping it on restart is free and a quick way to purge. A rolling size cap
    # evicts the oldest files (LRU by mtime) as the directory approaches the limit.
    thumbs_dir: Path = Path("/tmp/ml-thumbs")
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


settings = Settings()
