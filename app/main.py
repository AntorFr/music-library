"""Music Library — FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import covers, media, music_assistant, system, tags, views
from app.config import settings
from app.database import init_db
from app.services.music_assistant import close_ma_client
from app.services.tag_service import seed_default_tags

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # --- Startup ---
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)

    # Ensure data directories exist
    settings.covers_dir.mkdir(parents=True, exist_ok=True)

    # Init database tables
    await init_db()

    # Seed default tags
    from app.database import async_session
    async with async_session() as db:
        await seed_default_tags(db)
        await db.commit()

    logger.info("Database initialized, default tags seeded")

    yield

    # --- Shutdown ---
    await close_ma_client()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

# --- Static files ---
app.mount("/static", StaticFiles(directory="app/static", check_dir=False), name="static")

# --- API routes ---
app.include_router(system.router)
app.include_router(media.router)
app.include_router(tags.router)
app.include_router(covers.router)
app.include_router(music_assistant.router)

# --- Frontend (HTML) routes ---
app.include_router(views.router)
