"""API routes for tags management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.media import TagCategoryCreate, TagCategoryRead, TagCreate, TagRead
from app.services import tag_service

router = APIRouter(prefix="/api/v1/tags", tags=["tags"])


# ---------------------------------------------------------------------------
# Tag Categories
# ---------------------------------------------------------------------------

@router.get("/categories", response_model=list[TagCategoryRead])
async def list_categories(db: AsyncSession = Depends(get_db)):
    """List all tag categories."""
    cats = await tag_service.list_tag_categories(db)
    out = []
    for c in cats:
        out.append(TagCategoryRead(slug=c.slug, label=c.label, color=getattr(c, "color", None), tag_count=len(c.tags)))
    return out


@router.post("/categories", response_model=TagCategoryRead, status_code=201)
async def create_category(data: TagCategoryCreate, db: AsyncSession = Depends(get_db)):
    """Create a new tag category."""
    existing = await tag_service.get_tag_category(db, data.slug)
    if existing:
        raise HTTPException(409, detail=f"La catégorie '{data.slug}' existe déjà")
    cat = await tag_service.create_tag_category(db, data.slug, data.label, color=data.color)
    return TagCategoryRead(slug=cat.slug, label=cat.label, color=getattr(cat, "color", None), tag_count=0)


@router.delete("/categories/{slug}", status_code=204)
async def delete_category(slug: str, db: AsyncSession = Depends(get_db)):
    """Delete a tag category and all its tags."""
    ok = await tag_service.delete_tag_category(db, slug)
    if not ok:
        raise HTTPException(404, detail="Catégorie introuvable")


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

@router.get("", response_model=list[TagRead])
async def list_tags(
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all tags, optionally filtered by category."""
    tags = await tag_service.list_tags(db, category=category)
    cat_labels = await tag_service.get_cat_labels(db)
    return [
        TagRead(
            id=t.id,
            category=t.category,
            value=t.value,
            display=t.display,
            category_label=cat_labels.get(t.category, t.category),
        )
        for t in tags
    ]


@router.post("", response_model=TagRead, status_code=201)
async def create_tag(data: TagCreate, db: AsyncSession = Depends(get_db)):
    """Create a new tag."""
    # Verify the category exists
    cat = await tag_service.get_tag_category(db, data.category)
    if not cat:
        raise HTTPException(400, detail=f"Catégorie '{data.category}' inconnue")
    tag = await tag_service.get_or_create_tag(db, data.category, data.value)
    return TagRead(
        id=tag.id,
        category=tag.category,
        value=tag.value,
        display=tag.display,
        category_label=cat.label,
    )


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(tag_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a tag."""
    ok = await tag_service.delete_tag(db, tag_id)
    if not ok:
        raise HTTPException(404, detail="Tag introuvable")
