"""
Media CRUD service — business logic for managing the local catalogue.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.media import Media, MediaTag, MediaType, Tag
from app.schemas.media import MediaCreate, MediaUpdate
from app.services import cover_service
from app.services.media_selection import (  # noqa: F401  (re-exported)
    _media_tag_index,
    select_media,
    select_media_by_query,
)
from app.services.media_tags import (  # noqa: F401  (re-exported)
    _apply_owner_scope,
    _get_or_create_tag,
    _matching_owner_tag_ids,
    _resolve_tags,
    get_or_create_owner_tag,
)
from app.services.permissions import OWNER_CATEGORY


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
            local_path = await cover_service.download_and_save_cover(
                existing.id, existing.cover_url
            )
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

async def add_tag_to_media(
    db: AsyncSession, media_id: str, category: str, value: str
) -> Media | None:
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


