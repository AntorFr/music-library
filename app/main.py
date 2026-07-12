"""Music Library — FastAPI application entry point."""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from app.api import auth, covers, media, music_assistant, quick, rfid, system, tags, views
from app.config import settings
from app.database import init_db
from app.services.auth_service import is_exempt_path, oidc_enabled, resolve_request_user
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
    settings.thumbs_dir.mkdir(parents=True, exist_ok=True)

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

# --- Authentication ---
# Everything on this app (UI + /api/v1) requires an identity: an OIDC session for
# browsers, or the static bearer token for machines (Home Assistant). The trimmed ESP
# app (app.esp_app, port 8001) deliberately has none of this — a 302 to the IdP would
# break embedded clients. Registered before SessionMiddleware so the session (outermost
# middleware) is already resolved when this one runs.
@app.middleware("http")
async def _require_auth(request: Request, call_next):
    if is_exempt_path(request.url.path):
        return await call_next(request)
    user = resolve_request_user(request)
    if user is None:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return RedirectResponse("/auth/login", status_code=302)
    request.state.user = user
    return await call_next(request)


# Signed session cookie carrying the identity between requests. Without a configured
# secret, sessions reset on every restart (fine for dev — dev mode needs no session).
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret or secrets.token_hex(32),
    same_site="lax",
    https_only=oidc_enabled(),
    max_age=30 * 24 * 3600,
)

# --- Static files ---
app.mount("/static", StaticFiles(directory="app/static", check_dir=False), name="static")

# --- API routes ---
app.include_router(auth.router)
app.include_router(system.router)
app.include_router(media.router)
app.include_router(tags.router)
app.include_router(covers.router)
app.include_router(music_assistant.router)
app.include_router(quick.router)
app.include_router(rfid.router)

# --- Frontend (HTML) routes ---
app.include_router(views.router)
