"""Dedicated ESPHome API surface (served on its own port).

A trimmed FastAPI app exposing ONLY the endpoints an embedded dashboard needs:

* ``/api/v1/quick/*`` — favourites grid, episode/chapter drill-down, thumbnail proxy
* ``/covers/*``        — cover images (resized variants)
* ``/api/v1/ma/*``     — Music Assistant transport / now-playing
* ``/api/v1/health``   — health probe

The RFID API, the media CRUD and the HTML frontend are intentionally left out so this
surface can be exposed on a fast, plaintext internal network (no TLS handshake cost on the
device) without also exposing the management UI. The very same endpoints remain mounted on
the main app (:data:`app.main.app`), so they stay reachable over the public HTTPS proxy.

The few library-mutating writes that ride along on the shared routers (cover upload, MA
import) are blocked here by a request guard — FastAPI resolves included routes lazily
against the *shared* router objects, so they can't be pruned per-app without affecting the
main app. Database/table initialisation is owned by the main app's lifespan; both run in
one process (see ``app.server``) and share the same engine, so this app needs none.
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api import covers, music_assistant, quick, system
from app.config import settings

esp_app = FastAPI(
    title=f"{settings.app_name} — ESP API",
    version=settings.app_version,
)

esp_app.include_router(system.router)
esp_app.include_router(covers.router)
esp_app.include_router(music_assistant.router)
esp_app.include_router(quick.router)


def _is_blocked_admin_write(method: str, path: str) -> bool:
    """Library-mutating writes that must not be reachable on the ESP port.

    Music Assistant *transport* POSTs (play/pause/volume/…) are intentionally allowed —
    they are the whole point of the control surface.
    """
    if method != "POST":
        return False
    if path == "/api/v1/ma/import":  # triggers a full library import
        return True
    if path.startswith("/api/v1/media/") and path.endswith("/cover"):  # cover upload
        return True
    return False


@esp_app.middleware("http")
async def _block_admin_writes(request: Request, call_next):
    if _is_blocked_admin_write(request.method, request.url.path):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return await call_next(request)
