"""Compact quick-launch API for embedded screens (e.g. ESPHome dashboards).

Returns an owner's favourites in a minimal, parse-friendly shape so a
microcontroller can render a cover grid and trigger playback via
``POST /api/v1/ma/play`` without carrying the full media schema.

This mirrors the ``/quick`` web launcher but is JSON-only and trimmed for
constrained clients.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
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
from app.services.music_assistant import MusicAssistantClient, get_ma_client

router = APIRouter(prefix="/api/v1/quick", tags=["quick"])

# Media types that require drilling into episodes/chapters before playback.
_CHILD_TYPES = {MediaType.podcast, MediaType.audiobook}

# Default square size (px) for episode thumbnails served through our proxy cache.
EPISODE_THUMB_PX = 96


def _resolve_ma_provider_and_id(item) -> tuple[str | None, str | None]:
    """(provider, item_id) to re-query Music Assistant for an item's children.

    Prefer the ``source_uri``: it is the canonical MA URI (e.g. ``library://audiobook/29``),
    so its scheme is the MA provider and the trailing segment is the item id — a
    self-consistent pair. The stored ``provider`` column can be the *origin* provider
    (audible/spotify) while ``ma_item_id`` is the *library* id; combining those two is wrong
    and makes MA look up a non-existent item. Fall back to provider + ma_item_id only when the
    source_uri can't be parsed.
    """
    uri = item.source_uri or ""
    if "://" in uri:
        scheme, rest = uri.split("://", 1)
        parts = rest.split("/", 1)
        if len(parts) == 2 and parts[1]:
            return scheme, parts[1]
    provider = (item.provider or "").strip() or None
    extra = getattr(item, "metadata_extra", None) or {}
    item_id = str(extra["ma_item_id"]) if isinstance(extra, dict) and extra.get("ma_item_id") else None
    return provider, item_id


@router.get("/thumb")
async def quick_thumb(
    src: str = Query(..., description="Source image URL to proxy (must carry a valid `sig`)."),
    size: int = Query(EPISODE_THUMB_PX, ge=16, le=512, description="Square size in px."),
    sig: str = Query(..., description="HMAC signature issued by this server for (src, size)."),
):
    """Proxy + cache artwork from the music provider's CDN (or the MA imageproxy).

    Embedded clients hit this on our own host instead of the original source: the fetch +
    resize happens here once, and the cached NxN JPEG is served fast on every subsequent
    request. We resize the image ourselves (no third-party resizer). The `sig` ensures only
    URLs this server generated are honoured — so `src` may be any host without becoming an
    open proxy (SSRF).

    Declared before `/{owner}` so the literal path wins over the catch-all segment.
    """
    if not cover_service.verify_thumb(src, size, sig):
        raise HTTPException(403, detail="Invalid or missing signature")

    path = await cover_service.get_or_make_thumb(src, size)
    if path is None:
        return FileResponse(settings.default_cover, media_type="image/jpeg")
    return FileResponse(
        path,
        media_type="image/jpeg",
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
):
    """List a profile's favourites, ready for an embedded cover grid.

    Filtered by the ``owner`` tag. Covers are returned as stable resolved URLs
    (``/covers/<id>.jpg``, 300×300). Unknown owners simply yield an empty list.
    """
    items, _total = await media_service.list_media(
        db,
        media_type=media_type,
        tag_filters={"owner": owner},
        page=1,
        page_size=limit,
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
    provider, item_id = _resolve_ma_provider_and_id(item)
    if not provider or not item_id:
        ma_item = await ma.get_item_by_uri(item.source_uri or "")
        provider, item_id = ma_item.provider, ma_item.item_id
    episodes = await ma.get_podcast_episodes(item_id, provider)
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
    provider, item_id = _resolve_ma_provider_and_id(item)
    if provider and item_id:
        ma_item = await ma.get_item("audiobook", item_id, provider)
    else:
        ma_item = await ma.get_item_by_uri(item.source_uri or "")
    book_uri = ma_item.uri or item.source_uri or ""
    out: list[QuickChildItem] = []
    for ch in sorted(ma_item.chapters, key=lambda c: c.get("position", 0) or 0):
        start = float(ch.get("start", 0) or 0)
        end = ch.get("end")
        end_f = float(end) if end is not None else None
        out.append(
            QuickChildItem(
                title=ch.get("name") or f"Chapitre {ch.get('position', 0)}",
                uri=book_uri,           # chapters share the book uri; seek selects the chapter
                seek=int(start),
                position=int(ch.get("position", 0) or 0),
                duration_s=int(end_f - start) if end_f else None,
            )
        )
    return out


@router.get("/item/{media_id}/children", response_model=QuickChildrenResponse)
async def quick_children(
    request: Request,
    media_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """One page of a podcast's episodes / an audiobook's chapters (drill-down on scroll).

    Episodes carry their own `uri` (+ optional thumbnail, served via our `/thumb` proxy);
    chapters share the book `uri` and carry a `seek` offset (and no thumbnail).
    """
    item = await media_service.get_media(db, media_id)
    if not item:
        raise HTTPException(404, detail="Média introuvable")
    if item.media_type not in _CHILD_TYPES:
        raise HTTPException(400, detail="Ce média n'a pas d'épisodes/chapitres")

    base = str(request.base_url).rstrip("/")
    try:
        if item.media_type == MediaType.podcast:
            all_items = await _podcast_children(ma, item, base)
        else:
            all_items = await _audiobook_children(ma, item)
    except Exception as exc:
        raise HTTPException(502, detail=f"Music Assistant: {exc}") from exc

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
