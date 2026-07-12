"""
Media CRUD service — business logic for managing the local catalogue.
"""

from __future__ import annotations

import uuid
import random
from collections.abc import Collection
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.media import Media, MediaTag, MediaType, Tag
from app.schemas.media import (
    MediaCreate,
    MediaSelectParams,
    MediaSelectQueryOptions,
    MediaUpdate,
    SelectionFallback,
    TagQueryGroup,
)
from app.services import cover_service
from app.services.auth_service import normalize_owner
from app.services.permissions import OWNER_CATEGORY
from app.services.select_engine import apply_fallback, evaluate_group
from app.services.select_engine import normalize_select_token


class DuplicateMediaError(RuntimeError):
    """Raised when an operation would create a duplicate media entry."""

    def __init__(self, provider: str, source_uri: str, existing_id: str):
        super().__init__(f"Duplicate media for provider={provider} source_uri={source_uri}")
        self.provider = provider
        self.source_uri = source_uri
        self.existing_id = existing_id


async def _get_by_provider_source(
    db: AsyncSession,
    *,
    provider: str,
    source_uri: str,
    exclude_id: str | None = None,
) -> Media | None:
    stmt = (
        select(Media)
        .options(selectinload(Media.tags))
        .where(Media.provider == provider, Media.source_uri == source_uri)
    )
    if exclude_id:
        stmt = stmt.where(Media.id != exclude_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_create_tag(
    db: AsyncSession, category: str, value: str
) -> Tag:
    """Return existing tag or create new one."""
    stmt = select(Tag).where(Tag.category == category, Tag.value == value)
    result = await db.execute(stmt)
    tag = result.scalar_one_or_none()
    if tag:
        return tag
    tag = Tag(category=category, value=value)
    db.add(tag)
    await db.flush()
    return tag


async def _matching_owner_tag_ids(db: AsyncSession, owner_keys: Collection[str]) -> list[int]:
    """Ids of the owner tags matching a set of normalised owner keys.

    Matching is accent- and case-insensitive ("zoe" ↔ tag "Zoé"), which
    SQLite cannot do natively — so the (small) owner tag list is matched in
    Python.
    """
    keys = {normalize_owner(k) for k in owner_keys}
    result = await db.execute(
        select(Tag.id, Tag.value).where(Tag.category == OWNER_CATEGORY)
    )
    return [
        tag_id for tag_id, value in result.all()
        if normalize_owner(value or "") in keys
    ]


async def get_or_create_owner_tag(db: AsyncSession, owner_value: str) -> Tag:
    """Owner tag for a child session, matched accent/case-insensitively.

    The username is plain ("zoe") while the existing owner tag may be
    accented/capitalised ("Zoé") — reuse the existing tag instead of
    creating a twin.
    """
    tag_ids = await _matching_owner_tag_ids(db, [owner_value])
    if tag_ids:
        result = await db.execute(select(Tag).where(Tag.id == tag_ids[0]))
        return result.scalar_one()
    return await _get_or_create_tag(db, OWNER_CATEGORY, owner_value)


async def _apply_owner_scope(db: AsyncSession, stmt, owner_scope: Collection[str] | None):
    """Restrict a Media select to items carrying one of the owner tags a child
    session may see (their own tag + their group tags).

    This constraint is mandatory — it is applied at the SQL layer and is never
    relaxed by the selection fallback logic. No matching owner tag ⇒ no rows.
    """
    if owner_scope is not None:
        tag_ids = await _matching_owner_tag_ids(db, owner_scope)
        stmt = stmt.where(
            Media.id.in_(
                select(MediaTag.media_id).where(MediaTag.tag_id.in_(tag_ids))
            )
        )
    return stmt


async def _resolve_tags(
    db: AsyncSession,
    tag_ids: list[int] | None = None,
    tags_inline: list[dict[str, str]] | None = None,
) -> list[Tag]:
    """Resolve tag IDs and inline tag definitions into Tag objects."""
    tags: list[Tag] = []

    if tag_ids:
        stmt = select(Tag).where(Tag.id.in_(tag_ids))
        result = await db.execute(stmt)
        tags.extend(result.scalars().all())

    if tags_inline:
        for t in tags_inline:
            tag = await _get_or_create_tag(db, t["category"], t["value"])
            if tag not in tags:
                tags.append(tag)

    return tags


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def create_media(
    db: AsyncSession, data: MediaCreate, *, force_owner_value: str | None = None
) -> tuple[Media, bool]:
    """Create a new media item.

    Duplicate control:
    - Unicity key is (provider, source_uri)
    - If an item already exists, returns it (created=False) instead of creating
      a second row. This keeps the operation idempotent for HA imports.

    ``force_owner_value`` (child sessions): the caller's owner tag is appended
    regardless of the submitted tags, so children cannot create unscoped media.
    """

    existing = await _get_by_provider_source(
        db, provider=data.provider, source_uri=data.source_uri
    )
    if existing:
        # Reactivate if it was soft-deleted
        if not existing.is_active:
            existing.is_active = True

        # Merge tags if provided
        new_tags = await _resolve_tags(
            db,
            tag_ids=data.tag_ids,
            tags_inline=[{"category": t.category, "value": t.value} for t in data.tags_inline],
        )
        if new_tags:
            current = {(t.category, t.value) for t in (existing.tags or [])}
            for t in new_tags:
                if (t.category, t.value) not in current:
                    existing.tags.append(t)

        if force_owner_value:
            owner_tag = await get_or_create_owner_tag(db, force_owner_value)
            if owner_tag not in existing.tags:
                existing.tags.append(owner_tag)

        # Fill cover_url if missing
        if not existing.cover_url and data.cover_url:
            existing.cover_url = data.cover_url

        # Ensure we have a cached cover if we can
        if existing.cover_url and not existing.cover_local:
            local_path = await cover_service.download_and_save_cover(existing.id, existing.cover_url)
            if local_path:
                existing.cover_local = local_path

        await db.flush()
        return existing, False

    media = Media(
        id=str(uuid.uuid4()),
        title=data.title,
        media_type=data.media_type,
        source_uri=data.source_uri,
        provider=data.provider,
        cover_url=data.cover_url,
        duration_min=data.duration_min,
        description=data.description,
        metadata_extra=data.metadata_extra,
    )

    # Resolve tags
    tags = await _resolve_tags(
        db,
        tag_ids=data.tag_ids,
        tags_inline=[{"category": t.category, "value": t.value} for t in data.tags_inline],
    )
    if force_owner_value:
        owner_tag = await get_or_create_owner_tag(db, force_owner_value)
        if owner_tag not in tags:
            tags.append(owner_tag)
    media.tags = tags

    db.add(media)
    await db.flush()

    # Download cover if URL provided
    if data.cover_url:
        local_path = await cover_service.download_and_save_cover(media.id, data.cover_url)
        if local_path:
            media.cover_local = local_path

    await db.flush()
    return media, True


async def get_media(db: AsyncSession, media_id: str) -> Media | None:
    """Get a single media item by ID."""
    stmt = select(Media).options(selectinload(Media.tags)).where(Media.id == media_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_media(
    db: AsyncSession,
    *,
    search: str | None = None,
    media_type: MediaType | None = None,
    provider: str | None = None,
    tag_filters: dict[str, str] | None = None,
    is_active: bool = True,
    page: int = 1,
    page_size: int = 50,
    owner_scope: Collection[str] | None = None,
) -> tuple[list[Media], int]:
    """
    List media with filtering, search, and pagination.

    ``owner_scope`` (child sessions) restricts results to media carrying that
    owner tag, on top of any user-supplied filters.

    Returns (items, total_count).
    """
    stmt = select(Media).options(selectinload(Media.tags)).where(Media.is_active == is_active)
    stmt = await _apply_owner_scope(db, stmt, owner_scope)

    if search:
        stmt = stmt.where(
            or_(
                Media.title.ilike(f"%{search}%"),
                Media.description.ilike(f"%{search}%"),
            )
        )

    if media_type:
        stmt = stmt.where(Media.media_type == media_type)

    if provider:
        stmt = stmt.where(Media.provider == provider)

    # Tag filters: AND across categories
    if tag_filters:
        for category, value in tag_filters.items():
            stmt = stmt.where(
                Media.id.in_(
                    select(MediaTag.media_id)
                    .join(Tag)
                    .where(Tag.category == category, Tag.value == value)
                )
            )

    # Count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    # Paginate
    stmt = stmt.order_by(Media.updated_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return items, total


async def update_media(
    db: AsyncSession,
    media_id: str,
    data: MediaUpdate,
    *,
    preserve_owner_tags: bool = False,
) -> Media | None:
    """Update a media item (partial update).

    ``preserve_owner_tags`` (child sessions): the media's owner tags are kept
    exactly as they were, whatever the submitted tag list says — children edit
    content, parents manage ownership.
    """
    media = await get_media(db, media_id)
    if not media:
        return None

    update_data = data.model_dump(exclude_unset=True)

    # Prevent duplicates if provider/source_uri is being changed
    new_provider = update_data.get("provider", media.provider)
    new_source_uri = update_data.get("source_uri", media.source_uri)
    if new_provider != media.provider or new_source_uri != media.source_uri:
        dup = await _get_by_provider_source(
            db,
            provider=new_provider,
            source_uri=new_source_uri,
            exclude_id=media.id,
        )
        if dup:
            raise DuplicateMediaError(new_provider, new_source_uri, dup.id)

    # Handle tags separately
    tag_ids = update_data.pop("tag_ids", None)
    tags_inline = update_data.pop("tags_inline", None)

    for field, value in update_data.items():
        setattr(media, field, value)

    if tag_ids is not None or tags_inline is not None:
        inline_dicts = None
        if tags_inline:
            inline_dicts = [{"category": t["category"], "value": t["value"]} for t in tags_inline]
        new_tags = await _resolve_tags(db, tag_ids=tag_ids, tags_inline=inline_dicts)
        if preserve_owner_tags:
            previous_owner = [t for t in media.tags if t.category == OWNER_CATEGORY]
            new_tags = [t for t in new_tags if t.category != OWNER_CATEGORY] + previous_owner
        media.tags = new_tags

    # Re-download cover if URL changed
    if "cover_url" in update_data and data.cover_url:
        local_path = await cover_service.download_and_save_cover(media.id, data.cover_url)
        if local_path:
            media.cover_local = local_path

    await db.flush()
    return media


async def delete_media(db: AsyncSession, media_id: str, hard: bool = False) -> bool:
    """Soft-delete (or hard-delete) a media item."""
    media = await get_media(db, media_id)
    if not media:
        return False

    if hard:
        cover_service.delete_cover(media_id)
        await db.delete(media)
    else:
        media.is_active = False

    await db.flush()
    return True


# ---------------------------------------------------------------------------
# Tag management (add/remove on a media item)
# ---------------------------------------------------------------------------

async def add_tag_to_media(db: AsyncSession, media_id: str, category: str, value: str) -> Media | None:
    """Add a tag to a media item. Returns the updated media or None."""
    media = await get_media(db, media_id)
    if not media:
        return None
    tag = await _get_or_create_tag(db, category, value)
    if tag not in media.tags:
        media.tags.append(tag)
        await db.flush()
    return media


async def remove_tag_from_media(db: AsyncSession, media_id: str, tag_id: int) -> Media | None:
    """Remove a tag from a media item. Returns the updated media or None."""
    media = await get_media(db, media_id)
    if not media:
        return None
    media.tags = [t for t in media.tags if t.id != tag_id]
    await db.flush()
    return media


# ---------------------------------------------------------------------------
# Intelligent selection
# ---------------------------------------------------------------------------

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
