"""
Tag helpers for the media catalogue: get-or-create, inline resolution and the
owner scope (child sessions). Split out of ``media_service``.
"""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import Media, MediaTag, Tag
from app.services.auth_service import normalize_owner
from app.services.permissions import OWNER_CATEGORY


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
