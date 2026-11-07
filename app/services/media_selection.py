"""
Media selection by tags / boolean query (with fallback and tiebreak).
Split out of ``media_service``.
"""

from __future__ import annotations

import random
from collections.abc import Collection

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.media import Media, MediaTag, Tag
from app.schemas.media import (
    MediaSelectParams,
    MediaSelectQueryOptions,
    SelectionFallback,
    TagQueryGroup,
)
from app.services.media_tags import _apply_owner_scope
from app.services.select_engine import apply_fallback, evaluate_group, normalize_select_token


async def select_media(db: AsyncSession, params: MediaSelectParams) -> list[Media]:
    """
    Select media items matching tag criteria.

    Filters are AND across tag categories:
    owner=papa AND mood=calm → items that have BOTH tags.
    """
    tag_filters: dict[str, str] = {}
    if params.owner:
        tag_filters["owner"] = params.owner
    if params.mood:
        tag_filters["mood"] = params.mood
    if params.context:
        tag_filters["context"] = params.context
    if params.genre:
        tag_filters["genre"] = params.genre
    if params.time_of_day:
        tag_filters["time_of_day"] = params.time_of_day
    if params.age_group:
        tag_filters["age_group"] = params.age_group

    stmt = select(Media).options(selectinload(Media.tags)).where(Media.is_active == True)  # noqa: E712

    if params.media_type:
        stmt = stmt.where(Media.media_type == params.media_type)
    if params.provider:
        stmt = stmt.where(Media.provider == params.provider)

    for category, value in tag_filters.items():
        stmt = stmt.where(
            Media.id.in_(
                select(MediaTag.media_id)
                .join(Tag)
                .where(Tag.category == category, Tag.value == value)
            )
        )

    if params.random:
        stmt = stmt.order_by(func.random())

    stmt = stmt.limit(params.limit)

    result = await db.execute(stmt)
    return list(result.scalars().all())


def _media_tag_index(media: Media) -> dict[str, set[str]]:
    idx: dict[str, set[str]] = {}
    for t in getattr(media, "tags", []) or []:
        category = (t.category or "").strip().casefold()
        value = normalize_select_token(t.value or "")
        if not category or not value:
            continue
        idx.setdefault(category, set()).add(value)
    return idx


async def select_media_by_query(
    db: AsyncSession,
    *,
    group: TagQueryGroup,
    options: MediaSelectQueryOptions,
    include_order: list[str] | None = None,
    owner_scope: Collection[str] | None = None,
) -> list[Media]:
    """Select media items using a boolean tag query group + HA-friendly options.

    Strict constraints (never relaxed):
    - options.media_type
    - options.provider
    - options.exclude_ids
    - group.none_of
    - owner_scope (child sessions — applied in SQL, out of the fallback's reach)
    """

    stmt = select(Media).options(selectinload(Media.tags)).where(Media.is_active == True)  # noqa: E712
    stmt = await _apply_owner_scope(db, stmt, owner_scope)

    if options.search:
        stmt = stmt.where(Media.title.ilike(f"%{options.search}%"))
    if options.media_type:
        stmt = stmt.where(Media.media_type == options.media_type)
    if options.provider:
        stmt = stmt.where(Media.provider == options.provider)

    exclude_ids = {s for s in (options.exclude_ids or []) if s}
    if exclude_ids:
        stmt = stmt.where(~Media.id.in_(exclude_ids))

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    tags = [_media_tag_index(m) for m in items]

    # Strict match first
    strict_indices = [i for i in range(len(items)) if evaluate_group(tags[i], group)]
    
    # For "force" fallback, we always try to reach limit even if we have some strict matches
    if options.fallback == SelectionFallback.force:
        if options.random:
            random.shuffle(strict_indices)
        else:
            strict_indices.sort(
                key=lambda i: (items[i].updated_at.timestamp() if items[i].updated_at else 0.0),
                reverse=True,
            )
        
        # If we already have enough strict matches, return them
        if len(strict_indices) >= options.limit:
            return [items[i] for i in strict_indices[: options.limit]]
        
        # Otherwise, use force fallback to complete
        order = include_order or [f.category for f in group.all_of]

        def tiebreak_force(m: Media) -> tuple:
            ts = m.updated_at.timestamp() if m.updated_at else 0.0
            return (-ts, m.title, m.id)

        idx = apply_fallback(
            items=items,
            item_tags=tags,
            group=group,
            limit=options.limit,
            fallback=options.fallback,
            include_order=order,
            passes_strict=lambda _i: True,
            tiebreak=tiebreak_force,
        )
        return [items[i] for i in idx]

    if strict_indices:
        if options.random:
            random.shuffle(strict_indices)
        else:
            strict_indices.sort(
                key=lambda i: (items[i].updated_at.timestamp() if items[i].updated_at else 0.0),
                reverse=True,
            )
        return [items[i] for i in strict_indices[: options.limit]]

    # Fallback
    if options.fallback == SelectionFallback.none:
        return []

    order = include_order or [f.category for f in group.all_of]

    def tiebreak(m: Media) -> tuple:
        ts = m.updated_at.timestamp() if m.updated_at else 0.0
        # Prefer recent updates, stable by title/id.
        return (-ts, m.title, m.id)

    idx = apply_fallback(
        items=items,
        item_tags=tags,
        group=group,
        limit=options.limit,
        fallback=options.fallback,
        include_order=order,
        passes_strict=lambda _i: True,
        tiebreak=tiebreak,
    )
    return [items[i] for i in idx]
