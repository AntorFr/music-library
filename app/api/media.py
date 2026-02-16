"""API routes for local media catalogue CRUD."""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.media import MediaType
from app.schemas.media import (
    MediaCreate,
    MediaRead,
    MediaSelectParams,
    MediaUpdate,
    PaginatedResponse,
)
from app.services import media_service

router = APIRouter(prefix="/api/v1/media", tags=["media"])


@router.get("", response_model=PaginatedResponse)
async def list_media(
    search: str | None = None,
    media_type: MediaType | None = None,
    provider: str | None = None,
    owner: str | None = None,
    mood: str | None = None,
    context: str | None = None,
    genre: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List media items with filters and pagination."""
    tag_filters: dict[str, str] = {}
    if owner:
        tag_filters["owner"] = owner
    if mood:
        tag_filters["mood"] = mood
    if context:
        tag_filters["context"] = context
    if genre:
        tag_filters["genre"] = genre

    items, total = await media_service.list_media(
        db,
        search=search,
        media_type=media_type,
        provider=provider,
        tag_filters=tag_filters if tag_filters else None,
        page=page,
        page_size=page_size,
    )
    return PaginatedResponse(
        items=[MediaRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/select", response_model=list[MediaRead])
async def select_media(
    owner: str | None = None,
    mood: str | None = None,
    context: str | None = None,
    genre: str | None = None,
    time_of_day: str | None = None,
    age_group: str | None = None,
    media_type: MediaType | None = None,
    provider: str | None = None,
    random: bool = False,
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    Intelligent media selection — used by Home Assistant automations.

    Filters are AND across tag categories.  
    Example: `?owner=papa&mood=calm&context=evening&random=true&limit=1`
    """
    params = MediaSelectParams(
        owner=owner,
        mood=mood,
        context=context,
        genre=genre,
        time_of_day=time_of_day,
        age_group=age_group,
        media_type=media_type,
        provider=provider,
        random=random,
        limit=limit,
    )
    items = await media_service.select_media(db, params)
    return [MediaRead.model_validate(i) for i in items]


@router.get("/{media_id}", response_model=MediaRead)
async def get_media(media_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single media item by ID."""
    item = await media_service.get_media(db, media_id)
    if not item:
        raise HTTPException(404, detail="Média introuvable")
    return MediaRead.model_validate(item)


@router.post("", response_model=MediaRead, status_code=201)
async def create_media(data: MediaCreate, db: AsyncSession = Depends(get_db)):
    """Create a new media item."""
    item = await media_service.create_media(db, data)
    return MediaRead.model_validate(item)


@router.put("/{media_id}", response_model=MediaRead)
async def update_media(
    media_id: str, data: MediaUpdate, db: AsyncSession = Depends(get_db)
):
    """Update a media item (partial update)."""
    item = await media_service.update_media(db, media_id, data)
    if not item:
        raise HTTPException(404, detail="Média introuvable")
    return MediaRead.model_validate(item)


@router.delete("/{media_id}", status_code=204)
async def delete_media(
    media_id: str,
    hard: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Delete a media item (soft delete by default)."""
    ok = await media_service.delete_media(db, media_id, hard=hard)
    if not ok:
        raise HTTPException(404, detail="Média introuvable")
