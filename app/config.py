"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with sensible defaults for local development."""

    # --- Application ---
    app_name: str = "Music Library"
    app_version: str = "0.8.0-beta"
    debug: bool = False

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///data/library.db"

    # --- Covers ---
    covers_dir: Path = Path("data/covers")
    cover_max_size: int = 300  # px, square
    default_cover: str = "static/img/default_cover.jpg"

    # --- Music Assistant ---
    music_assistant_url: str = "http://localhost:8095"
    music_assistant_token: str = ""

    # --- Home Assistant ---
    home_assistant_url: str = "http://localhost:8123"
    home_assistant_token: str = ""

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_prefix": "ML_", "env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
