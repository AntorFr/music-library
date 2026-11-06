"""Media catalogue, creation, detail page, edit form and update."""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.views.shared import (
    _base_ctx,
    _build_available_tag_options,
    _filter_url_builder,
    templates,
)
from app.database import get_db
from app.models.media import MediaType
from app.schemas.media import MediaCreate, MediaUpdate
from app.services import cover_service, media_service, rfid_service, spotify_accounts
from app.services.auth_service import get_current_user
from app.services.permissions import (
    ensure_media_access,
    ensure_media_edit,
)
from app.services.tag_service import (
    list_tag_categories,
    list_tags,
)

router = APIRouter(tags=["frontend"])


@router.get("/media", response_class=HTMLResponse)
async def media_list(
    request: Request,
    search: str | None = None,
    media_type: str | None = None,
    provider: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    mt = MediaType(media_type) if media_type else None

    # Extract tag filters from query params (tag_<category>=<value>)
    tag_filters: dict[str, str] = {}
    for key, val in request.query_params.items():
        if key.startswith("tag_") and val:
            tag_filters[key[4:]] = val

    user = get_current_user(request)
    items, total = await media_service.list_media(
        db, search=search, media_type=mt, provider=provider,
        tag_filters=tag_filters or None,
        page=page, page_size=page_size,
        owner_scope=user.view_owner_keys,
    )
    pages = math.ceil(total / page_size) if total else 0

    # Distinct providers for filter dropdown
    all_items_for_providers, _ = await media_service.list_media(
        db, page=1, page_size=500, owner_scope=user.view_owner_keys
    )
    providers = sorted(set(i.provider for i in all_items_for_providers))

    # Tags grouped by category for filter dropdowns
    categories = await list_tag_categories(db)
    all_tags = await list_tags(db)
    tags_by_cat: dict[str, list[str]] = {}
    for t in all_tags:
        tags_by_cat.setdefault(t.category, []).append(t.value)
    if user.owner_value is not None:
        # A child is hard-scoped to their owner tag — the filter would be misleading.
        tags_by_cat.pop("owner", None)
    cat_labels = {c.slug: c.label for c in categories}

    active_params: dict[str, str] = {}
    if search:
        active_params["search"] = search
    if media_type:
        active_params["media_type"] = media_type
    if provider:
        active_params["provider"] = provider
    for cat, value in tag_filters.items():
        active_params[f"tag_{cat}"] = value

    ctx = _base_ctx(
        request,
        items=items,
        total=total,
        page=page,
        pages=pages,
        search=search,
        media_type=media_type or "",
        provider=provider or "",
        providers=providers,
        media_types=list(MediaType),
        tag_filters=tag_filters,
        tags_by_cat=tags_by_cat,
        cat_labels=cat_labels,
        filter_url=_filter_url_builder(active_params),
        has_filters=bool(active_params),
        # The search box keeps the other filters: it sends them as hx-vals rather
        # than hx-include, now that the chips are links instead of form controls.
        active_query={k: v for k, v in active_params.items() if k != "search"},
    )

    # If HTMX request and target is #media-results, return partial
    if request.headers.get("HX-Target") == "media-results":
        return templates.TemplateResponse(request, "components/media_grid.html", ctx)

    return templates.TemplateResponse(request, "media/list.html", ctx)


# ---------------------------------------------------------------------------
# Media — Detail
# ---------------------------------------------------------------------------

@router.post("/media/new")
async def media_create(
    request: Request,
    title: str = Form(...),
    media_type: str = Form(...),
    source_uri: str = Form(...),
    provider: str = Form(...),
    cover_url: str = Form(""),
    duration_min: str = Form(""),
    description: str = Form(""),
    tag_ids: list[str] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
):
    data = MediaCreate(
        title=title,
        media_type=MediaType(media_type),
        source_uri=source_uri,
        provider=provider,
        cover_url=cover_url or None,
        duration_min=int(duration_min) if duration_min else None,
        description=description or None,
        tag_ids=[int(t) for t in tag_ids if t],
    )
    user = get_current_user(request)
    item, _created = await media_service.create_media(
        db, data, force_owner_value=user.owner_value
    )

    # Download cover if URL provided
    if item.cover_url and not item.cover_local:
        local = await cover_service.download_and_save_cover(item.id, item.cover_url)
        if local:
            item.cover_local = local
            await db.commit()

    return RedirectResponse(f"/media/{item.id}", status_code=303)


@router.get("/media/{media_id}", response_class=HTMLResponse)
async def media_detail(request: Request, media_id: str, db: AsyncSession = Depends(get_db)):
    item = await media_service.get_media(db, media_id)
    ensure_media_access(get_current_user(request), item)

    # Get players for play button
    players = []
    try:
        from app.services.music_assistant import get_ma_client
        ma = await get_ma_client()
        players = await ma.get_players()
    except Exception:
        pass

    # Tags for unified add picker
    categories = await list_tag_categories(db)
    all_tags = await list_tags(db)
    cat_labels = {c.slug: c.label for c in categories}
    cat_colors = {c.slug: c.color for c in categories if getattr(c, "color", None)}
    available_tag_options = _build_available_tag_options(
        item=item,
        all_tags=all_tags,
        cat_labels=cat_labels,
    )

    # RFID tags (assigned + available)
    assigned_rfid = [
        {"uid": t.uid, "name": t.name}
        for t in (getattr(item, "rfid_tags", []) or [])
    ]
    available_rfid = [
        {"uid": t.uid, "name": t.name}
        for t in await rfid_service.list_rfid_tags(db, assigned=False)
    ]

    return templates.TemplateResponse(request, "media/detail.html", _base_ctx(
        request,
        item=item,
        players=players,
        cat_labels=cat_labels,
        cat_colors=cat_colors,
        available_tag_options=available_tag_options,
        assigned_rfid=assigned_rfid,
        available_rfid=available_rfid,
        spotify_switchable=spotify_accounts.is_switchable(item),
    ))



@router.get("/media/{media_id}/edit", response_class=HTMLResponse)
async def media_edit_form(request: Request, media_id: str, db: AsyncSession = Depends(get_db)):
    item = await media_service.get_media(db, media_id)
    ensure_media_edit(get_current_user(request), item)
    all_tags = await list_tags(db)
    categories = await list_tag_categories(db)
    cat_labels = {c.slug: c.label for c in categories}
    cat_colors = {c.slug: c.color for c in categories if getattr(c, "color", None)}
    return templates.TemplateResponse(request, "media/form.html", _base_ctx(
        request,
        item=item,
        available_tags=all_tags,
        cat_labels=cat_labels,
        cat_colors=cat_colors,
        media_types=list(MediaType),
    ))


@router.post("/media/{media_id}/edit")
async def media_update(
    request: Request,
    media_id: str,
    title: str = Form(...),
    media_type: str = Form(...),
    source_uri: str = Form(...),
    provider: str = Form(...),
    cover_url: str = Form(""),
    duration_min: str = Form(""),
    description: str = Form(""),
    is_active: str = Form("true"),
    tag_ids: list[str] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
):
    data = MediaUpdate(
        title=title,
        media_type=MediaType(media_type),
        source_uri=source_uri,
        provider=provider,
        cover_url=cover_url or None,
        duration_min=int(duration_min) if duration_min else None,
        description=description or None,
        is_active=is_active == "true",
        tag_ids=[int(t) for t in tag_ids if t],
    )
    user = get_current_user(request)
    existing = await media_service.get_media(db, media_id)
    ensure_media_edit(user, existing)
    item = await media_service.update_media(
        db, media_id, data, preserve_owner_tags=user.owner_value is not None
    )
    if not item:
        raise HTTPException(404, detail="Média introuvable")

    # Download cover if changed
    if item.cover_url and not item.cover_local:
        local = await cover_service.download_and_save_cover(item.id, item.cover_url)
        if local:
            item.cover_local = local
            await db.commit()

    return RedirectResponse(f"/media/{item.id}", status_code=303)


