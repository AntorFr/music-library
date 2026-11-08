"""Home launcher, PWA manifest and the legacy /quick redirect."""

from __future__ import annotations

import logging
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.views.shared import (
    OWNER_COOKIE,
    _base_ctx,
    templates,
)
from app.database import get_db
from app.services import media_service
from app.services.auth_service import get_current_user, normalize_owner
from app.services.tag_service import (
    list_tags,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["frontend"])


@router.get("/manifest.webmanifest")
async def web_manifest():
    """Minimal PWA manifest for the quick launcher."""
    return JSONResponse(
        {
            "name": "Music Library",
            "short_name": "Music",
            "description": "Lanceur rapide familial pour Music Library",
            # Le lanceur est la racine depuis la v2.
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#181818",
            "theme_color": "#03a9f4",
            # PNGs first: SVG manifest icons are ignored by iOS and by older Android.
            # They are square on purpose — both platforms apply their own corner mask.
            "icons": [
                {
                    "src": "/static/img/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
                {
                    "src": "/static/img/icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
                {
                    "src": "/static/img/favicon.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any",
                },
            ],
        },
        media_type="application/manifest+json",
    )


@router.get("/", response_class=HTMLResponse)
async def listen_page(
    request: Request,
    owner: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Home: the launcher. Pick a profile and a speaker, tap a cover, it plays.

    The profile comes from the URL, then from the ``ml_owner`` cookie the page
    writes. Reading it here is what lets the first response already be the right
    page: no redirect round-trip, and no flash of the setup card on every launch.
    """
    # The page writes the cookie with encodeURIComponent, and Starlette hands it
    # back still percent-encoded: without unquote, "S%C3%A9bastien" never matches
    # "Sébastien", and every accented profile reads as "n'existe plus".
    owner = owner or unquote(request.cookies.get(OWNER_COOKIE) or "") or None
    user = get_current_user(request)
    owner_tags = await list_tags(db, category="owner")
    owners = sorted({t.value for t in owner_tags}, key=str.casefold)
    if user.view_owner_keys is not None:
        # A child's picker only offers their own tag + their group tags.
        owners = [o for o in owners if normalize_owner(o) in user.view_owner_keys]
        if owner not in owners:
            own = [o for o in owners if normalize_owner(o) == user.owner_value]
            owner = own[0] if own else (owners[0] if owners else None)
    selected_owner = owner if owner in owners else None

    items = []
    if selected_owner:
        items, _ = await media_service.list_media(
            db,
            tag_filters={"owner": selected_owner},
            page=1,
            page_size=500,
        )

    players = []
    try:
        from app.services.music_assistant import get_ma_client
        ma = await get_ma_client()
        players = [p.to_dict() for p in await ma.get_players()]
    except Exception as exc:
        logger.info("Quick launcher: Music Assistant players unavailable: %s", exc)

    quick_data = {
        "owners": owners,
        "players": [p.get("player_id") for p in players if p.get("player_id")],
        "selected_owner": selected_owner,
    }

    return templates.TemplateResponse(request, "listen/index.html", _base_ctx(
        request,
        active_nav="listen",
        items=items,
        owners=owners,
        selected_owner=selected_owner,
        invalid_owner=owner if owner and not selected_owner else None,
        players=players,
        quick_data=quick_data,
    ))


@router.get("/quick")
async def quick_redirect(owner: str | None = None):
    """The launcher moved to the root in v2 — keep old links and shortcuts working."""
    target = f"/?owner={quote(owner)}" if owner else "/"
    return RedirectResponse(target, status_code=302)


