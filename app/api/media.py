"""API routes for local media catalogue CRUD."""

from __future__ import annotations

import math
from urllib.parse import parse_qsl

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.media import MediaType
from app.schemas.media import (
    MediaCreate,
    MediaRead,
    MediaSelectQueryOptions,
    MediaSelectQueryRequest,
    MediaSelectRead,
    SelectionFallback,
    MediaUpdate,
    PaginatedResponse,
)
from app.services import media_service
from app.services.select_engine import build_simple_group, parse_tag_filters_from_qsl, split_csv

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


@router.get("/select", response_model=list[MediaSelectRead])
async def select_media(
    request: Request,
    owner: str | None = None,
    mood: str | None = None,
    context: str | None = None,
    genre: str | None = None,
    time_of_day: str | None = None,
    age_group: str | None = None,
    not_owner: str | None = None,
    not_mood: str | None = None,
    not_context: str | None = None,
    not_genre: str | None = None,
    not_time_of_day: str | None = None,
    not_age_group: str | None = None,
    media_type: MediaType | None = None,
    provider: str | None = None,
    random: bool = False,
    limit: int = Query(10, ge=1, le=100),
    exclude_ids: str | None = Query(
        None,
        description="CSV UUIDs à exclure (ex: id1,id2)",
    ),
    fallback: SelectionFallback = Query(
        SelectionFallback.none,
        description="none|soft|aggressive (appliqué uniquement si 0 résultat)",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Intelligent media selection — used by Home Assistant automations.

    - AND entre catégories, OR via CSV dans une même catégorie
    - Exclusions strictes via `not_<category>=...` ou `not_tag_<slug>=...`
    - Tags dynamiques: `tag_<slug>=a,b`

    Exemples:
    - Simple: `?owner=papa&mood=calm&random=true&limit=1`
    - Multi-valeurs: `?tag_style=rock,pop&not_tag_style=metal`
    - Exclude IDs: `?owner=papa&exclude_ids=uuid1,uuid2`
    """

    pairs = parse_qsl(request.url.query, keep_blank_values=False)
    parsed = parse_tag_filters_from_qsl(
        pairs,
        reserved_keys={"media_type", "provider", "random", "limit", "fallback", "exclude_ids"},
    )

    # Collect exclude_ids from query (support repeated params) + explicit param
    excluded: set[str] = set(split_csv(exclude_ids))
    for k, v in pairs:
        if k == "exclude_ids":
            excluded.update(split_csv(v))

    group = build_simple_group(parsed.include_values, parsed.exclude_values, parsed.include_order)

    options = MediaSelectQueryOptions(
        limit=limit,
        random=random,
        fallback=fallback,
        exclude_ids=sorted(excluded),
        media_type=media_type,
        provider=provider,
    )

    items = await media_service.select_media_by_query(
        db,
        group=group,
        options=options,
        include_order=parsed.include_order,
    )

    base = str(request.base_url).rstrip("/")
    out: list[MediaSelectRead] = []
    for m in items:
        d = MediaRead.model_validate(m).model_dump()
        d["cover_url_resolved"] = f"{base}/covers/{m.id}.jpg"
        out.append(MediaSelectRead(**d))
    return out


@router.post(
    "/select/query",
    response_model=list[MediaSelectRead],
    summary="Complex selection query (HA)",
)
async def select_media_query(
    request: Request,
    payload: MediaSelectQueryRequest = Body(
        ..., 
        examples={
            "simple": {
                "summary": "AND + exclusions + fallback",
                "value": {
                    "query": {
                        "all_of": [
                            {"category": "owner", "values": ["papa"]},
                            {"category": "mood", "values": ["calm", "focus"]},
                        ],
                        "none_of": [
                            {"category": "genre", "values": ["metal"]}
                        ],
                        "any_of": [],
                    },
                    "options": {
                        "limit": 1,
                        "random": False,
                        "fallback": "soft",
                        "exclude_ids": [],
                        "media_type": "track",
                        "provider": None,
                    },
                },
            },
            "nested": {
                "summary": "Nested OR groups",
                "value": {
                    "query": {
                        "all_of": [{"category": "owner", "values": ["papa"]}],
                        "any_of": [
                            {"all_of": [{"category": "mood", "values": ["calm"]}], "any_of": [], "none_of": []},
                            {"all_of": [{"category": "context", "values": ["evening"]}], "any_of": [], "none_of": []},
                        ],
                        "none_of": [],
                    },
                    "options": {"limit": 3, "fallback": "aggressive", "media_type": "track"},
                },
            },
        },
    ),
    db: AsyncSession = Depends(get_db),
):
    """Complex boolean selection (ET/OU/NOT) for Home Assistant."""

    # Fallback order/weights use top-level all_of category order.
    seen: set[str] = set()
    include_order: list[str] = []
    for f in payload.query.all_of:
        if f.category not in seen:
            seen.add(f.category)
            include_order.append(f.category)

    items = await media_service.select_media_by_query(
        db,
        group=payload.query,
        options=payload.options,
        include_order=include_order,
    )

    base = str(request.base_url).rstrip("/")
    out: list[MediaSelectRead] = []
    for m in items:
        d = MediaRead.model_validate(m).model_dump()
        d["cover_url_resolved"] = f"{base}/covers/{m.id}.jpg"
        out.append(MediaSelectRead(**d))
    return out


@router.get("/{media_id}", response_model=MediaRead)
async def get_media(media_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single media item by ID."""
    item = await media_service.get_media(db, media_id)
    if not item:
        raise HTTPException(404, detail="Média introuvable")
    return MediaRead.model_validate(item)


@router.post("", response_model=MediaRead, status_code=201)
async def create_media(
    data: MediaCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Create a new media item."""
    item, created = await media_service.create_media(db, data)
    if not created:
        response.status_code = 200
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
