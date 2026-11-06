"""Settings page, RFID upsert and tag management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.views.shared import (
    TAG_COLOR_ALLOWED,
    TAG_COLOR_CHOICES,
    _base_ctx,
    _ma_status,
    templates,
)
from app.config import settings
from app.database import get_db
from app.services import rfid_service
from app.services.auth_service import get_current_user
from app.services.permissions import (
    ensure_parent,
)
from app.services.tag_service import (
    create_tag,
    list_tag_categories,
    list_tags,
)

router = APIRouter(tags=["frontend"])


@router.post("/rfid")
async def rfid_upsert(
    request: Request,
    uid: str = Form(...),
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    ensure_parent(get_current_user(request))
    await rfid_service.upsert_rfid_tag(db, uid=uid, name=name)
    await db.commit()
    return RedirectResponse("/settings?tab=rfid", status_code=303)



@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    tab: str = Query("tags", pattern="^(tags|rfid|system)$"),
    db: AsyncSession = Depends(get_db),
):
    """Parent-only administration: tags, RFID cards and system health, as tabs.

    v1 spent two top-level nav entries on surfaces opened a few times a year.
    """
    ensure_parent(get_current_user(request))

    all_tags = await list_tags(db)
    categories = await list_tag_categories(db)
    cat_labels = {c.slug: c.label for c in categories}
    cat_colors = {c.slug: c.color for c in categories if getattr(c, "color", None)}

    rfid_tags = await rfid_service.list_rfid_tags(db)
    rfid_view = [
        {
            "uid": t.uid,
            "name": t.name,
            "media_id": t.media_id,
            "media_title": t.media.title if getattr(t, "media", None) else None,
        }
        for t in rfid_tags
    ]

    return templates.TemplateResponse(request, "settings.html", _base_ctx(
        request,
        active_nav="settings",
        tab=tab,
        tags=all_tags,
        categories=categories,
        cat_labels=cat_labels,
        cat_colors=cat_colors,
        tag_color_choices=TAG_COLOR_CHOICES,
        rfid_tags=rfid_view,
        ma_status=await _ma_status(),
        app_version=settings.app_version,
    ))


@router.get("/tags")
async def tags_redirect():
    """Merged into /settings in v2."""
    return RedirectResponse("/settings?tab=tags", status_code=302)


@router.get("/rfid")
async def rfid_redirect():
    """Merged into /settings in v2."""
    return RedirectResponse("/settings?tab=rfid", status_code=302)


@router.post("/tags")
async def tags_create(
    request: Request,
    category: str = Form(...),
    value: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    ensure_parent(get_current_user(request))
    await create_tag(db, category, value)
    await db.commit()
    return RedirectResponse("/settings?tab=tags", status_code=303)


@router.post("/tags/categories")
async def tags_category_create(
    request: Request,
    slug: str = Form(...),
    label: str = Form(...),
    color: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    ensure_parent(get_current_user(request))
    normalized_color = (color or "").strip().lower()
    if normalized_color and normalized_color not in TAG_COLOR_ALLOWED:
        raise HTTPException(400, detail="Couleur invalide (hors palette prédéfinie)")

    from app.services.tag_service import upsert_tag_category
    try:
        await upsert_tag_category(db, slug, label, color=normalized_color)
    except ValueError as exc:
        raise HTTPException(400, detail="Couleur invalide") from exc
    await db.commit()
    return RedirectResponse("/settings?tab=tags", status_code=303)


@router.delete("/tags/categories/{slug}")
async def tags_category_delete(
    request: Request,
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    ensure_parent(get_current_user(request))
    from app.services.tag_service import delete_tag_category
    ok = await delete_tag_category(db, slug)
    if not ok:
        raise HTTPException(404, detail="Cat\u00e9gorie introuvable")
    await db.commit()
    return HTMLResponse("")


