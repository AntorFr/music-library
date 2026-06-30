"""Compact quick-launch API for embedded screens (e.g. ESPHome dashboards).

Returns an owner's favourites in a minimal, parse-friendly shape so a
microcontroller can render a cover grid and trigger playback via
``POST /api/v1/ma/play`` without carrying the full media schema.

This mirrors the ``/quick`` web launcher but is JSON-only and trimmed for
constrained clients.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.media import MediaType
from app.schemas.media import QuickLaunchItem, QuickLaunchResponse
from app.services import media_service

router = APIRouter(prefix="/api/v1/quick", tags=["quick"])

# Media types that require drilling into episodes/chapters before playback.
_CHILD_TYPES = {MediaType.podcast, MediaType.audiobook}


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
