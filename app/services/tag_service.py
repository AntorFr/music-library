"""
Tag & TagCategory CRUD service.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import DEFAULT_TAG_CATEGORIES, Tag, TagCategoryModel


# ---------------------------------------------------------------------------
# Tag Category CRUD
# ---------------------------------------------------------------------------

async def list_tag_categories(db: AsyncSession) -> list[TagCategoryModel]:
    """Return all tag categories ordered by label."""
    stmt = select(TagCategoryModel).order_by(TagCategoryModel.label)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_tag_category(db: AsyncSession, slug: str) -> TagCategoryModel | None:
    stmt = select(TagCategoryModel).where(TagCategoryModel.slug == slug)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_tag_category(db: AsyncSession, slug: str, label: str) -> TagCategoryModel:
    """Create a new tag category."""
    cat = TagCategoryModel(slug=slug, label=label)
    db.add(cat)
    await db.flush()
    return cat


async def get_or_create_tag_category(db: AsyncSession, slug: str, label: str) -> TagCategoryModel:
    """Get existing or create new tag category."""
    existing = await get_tag_category(db, slug)
    if existing:
        return existing
    return await create_tag_category(db, slug, label)


async def delete_tag_category(db: AsyncSession, slug: str) -> bool:
    """Delete a tag category (cascades to tags)."""
    cat = await get_tag_category(db, slug)
    if not cat:
        return False
    await db.delete(cat)
    await db.flush()
    return True


async def get_cat_labels(db: AsyncSession) -> dict[str, str]:
    """Return a slug→label mapping for all categories."""
    cats = await list_tag_categories(db)
    return {c.slug: c.label for c in cats}


# ---------------------------------------------------------------------------
# Tag CRUD
# ---------------------------------------------------------------------------

async def list_tags(
    db: AsyncSession,
    category: str | None = None,
) -> list[Tag]:
    """List all tags, optionally filtered by category."""
    stmt = select(Tag).order_by(Tag.category, Tag.value)
    if category:
        stmt = stmt.where(Tag.category == category)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_tag(db: AsyncSession, tag_id: int) -> Tag | None:
    stmt = select(Tag).where(Tag.id == tag_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_tag(db: AsyncSession, category: str, value: str) -> Tag:
    """Create a new tag (raises on duplicate)."""
    tag = Tag(category=category, value=value)
    db.add(tag)
    await db.flush()
    return tag


async def get_or_create_tag(db: AsyncSession, category: str, value: str) -> Tag:
    """Get existing or create new tag."""
    stmt = select(Tag).where(Tag.category == category, Tag.value == value)
    result = await db.execute(stmt)
    tag = result.scalar_one_or_none()
    if tag:
        return tag
    return await create_tag(db, category, value)


async def delete_tag(db: AsyncSession, tag_id: int) -> bool:
    tag = await get_tag(db, tag_id)
    if not tag:
        return False
    await db.delete(tag)
    await db.flush()
    return True


async def list_categories(db: AsyncSession) -> dict[str, list[str]]:
    """Return all categories with their values."""
    tags = await list_tags(db)
    categories: dict[str, list[str]] = {}
    for tag in tags:
        cat = tag.category
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(tag.value)
    return categories


async def seed_default_tags(db: AsyncSession) -> None:
    """Seed default tag categories and tags for first run."""
    # Seed categories
    for slug, label in DEFAULT_TAG_CATEGORIES.items():
        await get_or_create_tag_category(db, slug, label)

    # Seed default tags
    defaults: dict[str, list[str]] = {
        "owner": ["papa", "maman", "enfants", "famille"],
        "mood": ["calm", "energetic", "focus", "happy", "chill", "sleep"],
        "context": ["morning", "cooking", "work", "party", "bath", "car", "sport"],
        "time_of_day": ["morning", "afternoon", "evening", "night"],
        "age_group": ["kids", "teens", "adults", "all"],
        "genre": ["pop", "rock", "classical", "jazz", "electronic", "hip-hop", "ambient"],
    }
    for category, values in defaults.items():
        for value in values:
            await get_or_create_tag(db, category, value)
