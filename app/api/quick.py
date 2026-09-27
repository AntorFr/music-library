"""Compact quick-launch API for embedded screens (e.g. ESPHome dashboards).

Returns an owner's favourites in a minimal, parse-friendly shape so a
microcontroller can render a cover grid and trigger playback via
``POST /api/v1/ma/play`` without carrying the full media schema.

This mirrors the ``/quick`` web launcher but is JSON-only and trimmed for
constrained clients.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.media import MediaType
from app.schemas.media import (
    QuickChildItem,
    QuickChildrenResponse,
    QuickLaunchItem,
    QuickLaunchResponse,
)
from app.services import cover_service, media_service
from app.services.auth_service import CurrentUser, get_current_user
from app.services.music_assistant import (
    MusicAssistantClient,
    fetch_audiobook,
    fetch_podcast_episodes,
    get_ma_client,
    normalize_chapters,
)
from app.services.permissions import ensure_media_access

router = APIRouter(prefix="/api/v1/quick", tags=["quick"])

# Media types that require drilling into episodes/chapters before playback.
_CHILD_TYPES = {MediaType.podcast, MediaType.audiobook}

# Default square size (px) for episode thumbnails served through our proxy cache.
EPISODE_THUMB_PX = 96

# `/children?keepalive=1`: how long to wait for a normal JSON answer before switching to a
# streamed one, and the gap between the whitespace bytes sent while MA works. The gap must
# stay well under the ESP's HTTP inactivity timeout (5 s).
KEEPALIVE_FIRST_WAIT_S = 1.0
KEEPALIVE_INTERVAL_S = 2.0


@router.get("/thumb")
async def quick_thumb(
    src: str = Query(..., description="Source image URL to proxy (must carry a valid `sig`)."),
    size: int = Query(EPISODE_THUMB_PX, ge=16, le=512, description="Square size in px."),
    sig: str = Query(..., description="HMAC signature issued by this server for (src, size)."),
    fmt: str = Query(
        "jpg", pattern="^(jpg|bmp)$",
        description="Output encoding: jpg (small) or bmp (no-DCT, cheap to decode on-device).",
    ),
):
    """Proxy + cache artwork from the music provider's CDN (or the MA imageproxy).

    Embedded clients hit this on our own host instead of the original source: the fetch +
    resize happens here once, and the cached NxN variant is served fast on every subsequent
    request. We resize the image ourselves (no third-party resizer). The `sig` ensures only
    URLs this server generated are honoured — so `src` may be any host without becoming an
    open proxy (SSRF).

    `fmt` (jpg|bmp) is deliberately NOT part of the signature: it only selects the output
    encoding of an already-authorised `src`+`size`, so a client can append `&fmt=bmp` to a
    signed URL (to trade transfer size for a cheaper on-device decode) without re-signing.

    Declared before `/{owner}` so the literal path wins over the catch-all segment.
    """
    if not cover_service.verify_thumb(src, size, sig):
        raise HTTPException(403, detail="Invalid or missing signature")

    path = await cover_service.get_or_make_thumb(src, size, fmt)
    if path is None:
        return FileResponse(settings.default_cover, media_type="image/jpeg")
    return FileResponse(
        path,
        media_type=cover_service.media_type_for(fmt),
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/{owner}", response_model=QuickLaunchResponse)
async def quick_favourites(
    request: Request,
    owner: str,
    media_type: MediaType | None = Query(
        None, description="Optional filter, e.g. only playlists."
    ),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """List a profile's favourites, ready for an embedded cover grid.

    Filtered by the ``owner`` tag. Covers are returned as stable resolved URLs
    (``/covers/<id>.jpg``, 300×300). Unknown owners simply yield an empty list.
    A child session only reaches its own grid (other owners yield empty) — on
    the unauthenticated ESP surface every request is unrestricted.
    """
    items, _total = await media_service.list_media(
        db,
        media_type=media_type,
        tag_filters={"owner": owner},
        page=1,
        page_size=limit,
        owner_scope=user.view_owner_keys,
    )

    base = str(request.base_url).rstrip("/")
    out = [
        QuickLaunchItem(
            id=m.id,
            title=m.title,
            media_type=m.media_type,
            uri=m.source_uri,
            cover_url=f"{base}/covers/{m.id}.jpg",
            has_children=m.media_type in _CHILD_TYPES,
        )
        for m in items
    ]
    return QuickLaunchResponse(owner=owner, count=len(out), items=out)


async def _podcast_children(ma: MusicAssistantClient, item, base: str) -> list[QuickChildItem]:
    episodes = await fetch_podcast_episodes(ma, item)
    out: list[QuickChildItem] = []
    for e in episodes:
        # Route the thumbnail through our own cached proxy (see `/thumb`): the device fetches
        # it from us, and we resize the original ourselves (size=0 = original, no third-party
        # resizer) before caching.
        source = ma.get_item_image_url(e, size=0)
        out.append(
            QuickChildItem(
                title=e.name,
                uri=e.uri,
                cover_url=cover_service.thumb_proxy_url(base, source, EPISODE_THUMB_PX),
                position=e.position or None,
                duration_s=e.duration or None,
                resume_s=(e.resume_position_ms // 1000) if e.resume_position_ms else None,
                fully_played=e.fully_played,
            )
        )
    return out


async def _audiobook_children(ma: MusicAssistantClient, item) -> list[QuickChildItem]:
    ma_item = await fetch_audiobook(ma, item)
    book_uri = ma_item.uri or item.source_uri or ""
    return [
        QuickChildItem(
            title=ch["name"] or f"Chapitre {ch['position']}",
            uri=book_uri,           # chapters share the book uri; seek selects the chapter
            seek=int(ch["start"]),
            position=ch["position"],
            duration_s=int(ch["duration"]) if ch["duration"] is not None else None,
        )
        for ch in normalize_chapters(ma_item)
    ]


def _children_page(item, all_items: list[QuickChildItem], offset: int, limit: int) -> QuickChildrenResponse:
    page = all_items[offset : offset + limit]
    return QuickChildrenResponse(
        parent_id=item.id,
        media_type=item.media_type,
        offset=offset,
        limit=limit,
        count=len(page),
        has_more=(offset + limit) < len(all_items),
        items=page,
    )


async def _keepalive_body(fetch: asyncio.Task, item, offset: int, limit: int):
    """Stream the page once `fetch` finishes, sending a space every few seconds meanwhile.

    Leading whitespace is valid JSON, so the client parses the body as usual; the spaces only
    prove the request is still being worked on, which keeps an embedded client's inactivity
    timeout from firing while MA is slow. The status line (200) is already sent by then, so a
    failure is reported in the body as ``{"detail": ...}`` without ``items``.
    """
    while True:
        done, _ = await asyncio.wait({fetch}, timeout=KEEPALIVE_INTERVAL_S)
        if done:
            break
        yield b" "
    exc = fetch.exception()
    if exc is not None:
        yield json.dumps({"detail": f"Music Assistant: {exc}"}).encode()
        return
    yield _children_page(item, fetch.result(), offset, limit).model_dump_json().encode()


@router.get("/item/{media_id}/children", response_model=QuickChildrenResponse)
async def quick_children(
    request: Request,
    media_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    keepalive: bool = Query(
        False,
        description="Stream whitespace while Music Assistant is slow, then the JSON page "
        "(for clients with a short inactivity timeout).",
    ),
    db: AsyncSession = Depends(get_db),
    ma: MusicAssistantClient = Depends(get_ma_client),
    user: CurrentUser = Depends(get_current_user),
):
    """One page of a podcast's episodes / an audiobook's chapters (drill-down on scroll).

    Episodes come newest first, so the first page holds the latest ones; chapters keep
    reading order.

    Episodes carry their own `uri` (+ optional thumbnail, served via our `/thumb` proxy);
    chapters share the book `uri` and carry a `seek` offset (and no thumbnail).

    A provider-backed podcast can take tens of seconds on a cold MA cache. With
    `keepalive=1`, an answer that is not ready within a second is streamed: whitespace every
    few seconds, then the page (or `{"detail": ...}` on failure) — see `_keepalive_body`.
    """
    item = await media_service.get_media(db, media_id)
    ensure_media_access(user, item)
    if item.media_type not in _CHILD_TYPES:
        raise HTTPException(400, detail="Ce média n'a pas d'épisodes/chapitres")

    base = str(request.base_url).rstrip("/")
    if item.media_type == MediaType.podcast:
        fetch = asyncio.ensure_future(_podcast_children(ma, item, base))
    else:
        fetch = asyncio.ensure_future(_audiobook_children(ma, item))
    # A streamed request whose client hung up never reads the outcome: mark it retrieved so
    # a failure isn't logged as "Task exception was never retrieved".
    fetch.add_done_callback(lambda t: t.cancelled() or t.exception())

    if keepalive:
        done, _ = await asyncio.wait({fetch}, timeout=KEEPALIVE_FIRST_WAIT_S)
        if not done:
            return StreamingResponse(
                _keepalive_body(fetch, item, offset, limit), media_type="application/json"
            )
    try:
        all_items = await fetch
    except Exception as exc:
        raise HTTPException(502, detail=f"Music Assistant: {exc}") from exc
    return _children_page(item, all_items, offset, limit)
