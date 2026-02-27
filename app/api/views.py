"""
Frontend (HTML) view routes.

Renders Jinja2 templates for the Music Library web UI.
All JSON API calls are delegated to the existing /api/v1/ routes.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.media import MediaType
from app.schemas.media import MediaCreate, MediaUpdate
from app.services import cover_service, media_service
from app.services import rfid_service
from app.services.tag_service import (
    create_tag,
    get_cat_labels,
    get_tag,
    list_tag_categories,
    list_tags,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["frontend"])
templates = Jinja2Templates(directory="app/templates")

# ---------------------------------------------------------------------------
# Shared template context helpers
# ---------------------------------------------------------------------------

TYPE_LABELS: dict[str, str] = {
    "playlist": "Playlist",
    "audiobook": "Livre audio",
    "radio": "Radio",
    "podcast": "Podcast",
    "album": "Album",
    "track": "Piste",
}

TYPE_ICONS: dict[str, str] = {
    "playlist": "playlist-music",
    "audiobook": "book-music",
    "radio": "radio",
    "podcast": "podcast",
    "album": "album",
    "track": "music-note",
}


def _base_ctx(request: Request, **extra: Any) -> dict:
    """Build base template context."""
    return {
        "request": request,
        "type_labels": TYPE_LABELS,
        "type_icons": TYPE_ICONS,
        **extra,
    }


def _build_available_tag_options(
    *,
    item: Any,
    all_tags: list[Any],
    cat_labels: dict[str, str],
) -> list[str]:
    existing = {(t.category, t.value) for t in (getattr(item, "tags", []) or [])}
    options: list[str] = []
    for t in all_tags:
        if (t.category, t.value) in existing:
            continue
        cat_label = cat_labels.get(t.category, t.category)
        options.append(f"{cat_label}: {t.value}")
    return sorted(set(options), key=str.casefold)


def _parse_tag_input(
    *,
    raw: str,
    cat_labels: dict[str, str],
) -> tuple[str, str]:
    """Parse a single tag input like '<Category>: <value>'.

    Accepts either a category slug or its label (case-insensitive).
    """
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(400, detail="Tag invalide")

    if ":" not in raw:
        raise HTTPException(400, detail="Format attendu: 'Catégorie: valeur'")

    left, right = raw.split(":", 1)
    cat_token = left.strip()
    value = right.strip()
    if not cat_token or not value:
        raise HTTPException(400, detail="Format attendu: 'Catégorie: valeur'")

    label_to_slug = {lbl.casefold(): slug for slug, lbl in cat_labels.items()}
    slug = label_to_slug.get(cat_token.casefold(), cat_token)
    return slug, value


# ---------------------------------------------------------------------------
# RFID tags
# ---------------------------------------------------------------------------


@router.get("/rfid", response_class=HTMLResponse)
async def rfid_page(request: Request, db: AsyncSession = Depends(get_db)):
    tags = await rfid_service.list_rfid_tags(db)
    view = [
        {
            "uid": t.uid,
            "name": t.name,
            "media_id": t.media_id,
            "media_title": t.media.title if getattr(t, "media", None) else None,
        }
        for t in tags
    ]
    return templates.TemplateResponse(
        "rfid/list.html",
        _base_ctx(request, tags=view),
    )


@router.post("/rfid")
async def rfid_upsert(
    uid: str = Form(...),
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    await rfid_service.upsert_rfid_tag(db, uid=uid, name=name)
    await db.commit()
    return RedirectResponse("/rfid", status_code=303)


# ---------------------------------------------------------------------------
# Home / Dashboard
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    # Stats
    all_items, total = await media_service.list_media(db, page=1, page_size=1)
    _, active_count = await media_service.list_media(db, page=1, page_size=1)

    # Count by type
    by_type: dict[str, int] = {}
    for mt in MediaType:
        _, cnt = await media_service.list_media(db, media_type=mt, page=1, page_size=1)
        if cnt > 0:
            by_type[mt.value] = cnt

    # Tags count
    all_tags = await list_tags(db)

    # Players count (best effort)
    players_count = 0
    try:
        from app.services.music_assistant import get_ma_client
        ma = await get_ma_client()
        players = await ma.get_players()
        players_count = len(players)
    except Exception:
        pass

    # Recent items
    recent_items, _ = await media_service.list_media(db, page=1, page_size=12)

    stats = {
        "total": total,
        "active": active_count,  # all are counted for now
        "tags": len(all_tags),
        "players": players_count,
        "by_type": by_type,
    }

    return templates.TemplateResponse("index.html", _base_ctx(
        request,
        stats=stats,
        recent=recent_items,
    ))


# ---------------------------------------------------------------------------
# Media — List
# ---------------------------------------------------------------------------

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

    items, total = await media_service.list_media(
        db, search=search, media_type=mt, provider=provider,
        tag_filters=tag_filters or None,
        page=page, page_size=page_size,
    )
    pages = math.ceil(total / page_size) if total else 0

    # Distinct providers for filter dropdown
    all_items_for_providers, _ = await media_service.list_media(db, page=1, page_size=500)
    providers = sorted(set(i.provider for i in all_items_for_providers))

    # Tags grouped by category for filter dropdowns
    categories = await list_tag_categories(db)
    all_tags = await list_tags(db)
    tags_by_cat: dict[str, list[str]] = {}
    for t in all_tags:
        tags_by_cat.setdefault(t.category, []).append(t.value)
    cat_labels = {c.slug: c.label for c in categories}

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
    )

    # If HTMX request and target is #media-results, return partial
    if request.headers.get("HX-Target") == "media-results":
        return templates.TemplateResponse("components/media_grid.html", ctx)

    return templates.TemplateResponse("media/list.html", ctx)


# ---------------------------------------------------------------------------
# Media — Detail
# ---------------------------------------------------------------------------

@router.get("/media/new", response_class=HTMLResponse)
async def media_new_form(request: Request, db: AsyncSession = Depends(get_db)):
    all_tags = await list_tags(db)
    cat_labels = {c.slug: c.label for c in await list_tag_categories(db)}
    return templates.TemplateResponse("media/form.html", _base_ctx(
        request,
        item=None,
        available_tags=all_tags,
        cat_labels=cat_labels,
        media_types=list(MediaType),
    ))


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
    item, _created = await media_service.create_media(db, data)

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
    if not item:
        raise HTTPException(404, detail="Média introuvable")

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

    return templates.TemplateResponse("media/detail.html", _base_ctx(
        request,
        item=item,
        players=players,
        cat_labels=cat_labels,
        available_tag_options=available_tag_options,
        assigned_rfid=assigned_rfid,
        available_rfid=available_rfid,
    ))


@router.post("/media/{media_id}/rfid")
async def media_assign_rfid(
    media_id: str,
    rfid_uids: list[str] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
):
    try:
        await rfid_service.assign_rfid_tags_to_media(db, media_id=media_id, uids=rfid_uids)
        await db.commit()
    except rfid_service.RFIDAlreadyAssignedError as exc:
        raise HTTPException(409, detail=f"Tag RFID déjà associé: {exc.uid}")
    return RedirectResponse(f"/media/{media_id}", status_code=303)


@router.post("/media/{media_id}/rfid/{uid}/remove")
async def media_unassign_rfid(
    media_id: str,
    uid: str,
    db: AsyncSession = Depends(get_db),
):
    await rfid_service.unassign_rfid_tag(db, uid=uid)
    await db.commit()
    return RedirectResponse(f"/media/{media_id}", status_code=303)


@router.post("/media/{media_id}/tags", response_class=HTMLResponse)
async def media_add_tag(
    request: Request,
    media_id: str,
    tag: str | None = Form(None),
    category: str | None = Form(None),
    value: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Add a tag to a media item and return the updated tags block partial."""
    cat_labels = {c.slug: c.label for c in await list_tag_categories(db)}

    if tag:
        category, value = _parse_tag_input(raw=tag, cat_labels=cat_labels)
    if not category or not value:
        raise HTTPException(400, detail="Tag invalide")

    item = await media_service.add_tag_to_media(db, media_id, category, value)
    if not item:
        raise HTTPException(404, detail="Média introuvable")
    await db.commit()

    all_tags = await list_tags(db)
    available_tag_options = _build_available_tag_options(
        item=item,
        all_tags=all_tags,
        cat_labels=cat_labels,
    )
    return templates.TemplateResponse("components/media_tags_block.html", {
        "request": request,
        "item": item,
        "cat_labels": cat_labels,
        "available_tag_options": available_tag_options,
    })


@router.delete("/media/{media_id}/tags/{tag_id}", response_class=HTMLResponse)
async def media_remove_tag(
    request: Request,
    media_id: str,
    tag_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Remove a tag from a media item and return the updated tags block partial."""
    item = await media_service.remove_tag_from_media(db, media_id, tag_id)
    if not item:
        raise HTTPException(404, detail="Média introuvable")
    await db.commit()
    cat_labels = {c.slug: c.label for c in await list_tag_categories(db)}
    all_tags = await list_tags(db)
    available_tag_options = _build_available_tag_options(
        item=item,
        all_tags=all_tags,
        cat_labels=cat_labels,
    )
    return templates.TemplateResponse("components/media_tags_block.html", {
        "request": request,
        "item": item,
        "cat_labels": cat_labels,
        "available_tag_options": available_tag_options,
    })


@router.get("/media/{media_id}/edit", response_class=HTMLResponse)
async def media_edit_form(request: Request, media_id: str, db: AsyncSession = Depends(get_db)):
    item = await media_service.get_media(db, media_id)
    if not item:
        raise HTTPException(404, detail="Média introuvable")
    all_tags = await list_tags(db)
    cat_labels = {c.slug: c.label for c in await list_tag_categories(db)}
    return templates.TemplateResponse("media/form.html", _base_ctx(
        request,
        item=item,
        available_tags=all_tags,
        cat_labels=cat_labels,
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
    item = await media_service.update_media(db, media_id, data)
    if not item:
        raise HTTPException(404, detail="Média introuvable")

    # Download cover if changed
    if item.cover_url and not item.cover_local:
        local = await cover_service.download_and_save_cover(item.id, item.cover_url)
        if local:
            item.cover_local = local
            await db.commit()

    return RedirectResponse(f"/media/{item.id}", status_code=303)


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

@router.get("/tags", response_class=HTMLResponse)
async def tags_page(request: Request, db: AsyncSession = Depends(get_db)):
    all_tags = await list_tags(db)
    categories = await list_tag_categories(db)
    cat_labels = {c.slug: c.label for c in categories}
    return templates.TemplateResponse("tags/list.html", _base_ctx(
        request,
        tags=all_tags,
        categories=categories,
        cat_labels=cat_labels,
    ))


@router.post("/tags")
async def tags_create(
    request: Request,
    category: str = Form(...),
    value: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    await create_tag(db, category, value)
    await db.commit()
    return RedirectResponse("/tags", status_code=303)


@router.post("/tags/categories")
async def tags_category_create(
    request: Request,
    slug: str = Form(...),
    label: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from app.services.tag_service import get_or_create_tag_category
    await get_or_create_tag_category(db, slug, label)
    await db.commit()
    return RedirectResponse("/tags", status_code=303)


@router.delete("/tags/categories/{slug}")
async def tags_category_delete(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    from app.services.tag_service import delete_tag_category
    ok = await delete_tag_category(db, slug)
    if not ok:
        raise HTTPException(404, detail="Cat\u00e9gorie introuvable")
    await db.commit()
    return HTMLResponse("")


# ---------------------------------------------------------------------------
# Music Assistant — Browse & Import
# ---------------------------------------------------------------------------

@router.get("/browse", response_class=HTMLResponse)
async def browse_page(request: Request):
    return templates.TemplateResponse("ma/browse.html", _base_ctx(request))


@router.get("/browse/library/{media_type}", response_class=HTMLResponse)
async def browse_library(request: Request, media_type: str):
    try:
        from app.services.music_assistant import get_ma_client
        ma = await get_ma_client()

        method_map = {
            "playlists": ma.get_library_playlists,
            "albums": ma.get_library_albums,
            "tracks": ma.get_library_tracks,
            "radios": ma.get_library_radios,
            "audiobooks": ma.get_library_audiobooks,
            "podcasts": ma.get_library_podcasts,
        }

        fetch = method_map.get(media_type)
        if not fetch:
            raise HTTPException(400, detail="Type inconnu")

        raw_items = await fetch(limit=50)
        items = []
        for item in raw_items:
            d = item.to_dict()
            d["thumb_url_resolved"] = ma.get_item_image_url(item, size=300)
            # Provider badge info
            base = item.provider.split("--")[0] if "--" in item.provider else item.provider
            _PROV = {
                "library": ("Bibliothèque", "mdi-bookshelf", "badge-success"),
                "spotify": ("Spotify", "mdi-spotify", "badge-primary"),
                "ytmusic": ("YouTube Music", "mdi-youtube", "badge-danger"),
                "apple_music": ("Apple Music", "mdi-apple", "badge-surface"),
                "tidal": ("Tidal", "mdi-music-box", "badge-primary"),
                "audible": ("Audible", "mdi-headphones", "badge-warning"),
            }
            label, icon, cls = _PROV.get(base, (base.capitalize(), "mdi-cloud", "badge-surface"))
            d["provider_label"] = label
            d["provider_icon"] = icon
            d["provider_badge"] = cls
            d["is_library"] = item.provider == "library"
            items.append(d)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("MA browse error: %s", e)
        items = []

    return templates.TemplateResponse("components/ma_items.html", _base_ctx(
        request, items=items,
    ))


@router.get("/browse/search", response_class=HTMLResponse)
async def browse_search(request: Request, q: str = Query("", alias="maSearch")):
    # HTMX sends the input name as param, otherwise use q
    search_q = request.query_params.get("maSearch") or request.query_params.get("q") or q
    category = request.query_params.get("category", "all")

    if not search_q or len(search_q) < 2:
        return HTMLResponse('<div class="empty-state"><i class="mdi mdi-magnify"></i><p>Tapez au moins 2 caractères…</p></div>')

    # Map tab categories to MA media_types
    CATEGORY_TO_MEDIA_TYPES: dict[str, list[str] | None] = {
        "all": None,  # search all types
        "playlists": ["playlist"],
        "albums": ["album"],
        "tracks": ["track"],
        "radios": ["radio"],
        "audiobooks": ["audiobook"],
        "podcasts": ["podcast"],
    }
    media_types = CATEGORY_TO_MEDIA_TYPES.get(category)

    try:
        from app.services.music_assistant import get_ma_client
        ma = await get_ma_client()
        results = await ma.search(search_q, media_types=media_types, limit=20)

        # Provider display names
        PROVIDER_LABELS = {
            "library": ("Bibliothèque", "mdi-bookshelf", "badge-success"),
            "spotify": ("Spotify", "mdi-spotify", "badge-primary"),
            "ytmusic": ("YouTube Music", "mdi-youtube", "badge-danger"),
            "apple_music": ("Apple Music", "mdi-apple", "badge-surface"),
            "tidal": ("Tidal", "mdi-music-box", "badge-primary"),
            "audible": ("Audible", "mdi-headphones", "badge-warning"),
        }

        def _provider_info(provider: str) -> dict:
            """Return label, icon, badge class for a provider."""
            # Provider can be like "spotify--ThNy9kHW", extract base name
            base = provider.split("--")[0] if "--" in provider else provider
            label, icon, cls = PROVIDER_LABELS.get(base, (base.capitalize(), "mdi-cloud", "badge-surface"))
            return {"provider_label": label, "provider_icon": icon, "provider_badge": cls,
                    "is_library": provider == "library"}

        def serialize(items):
            # Sort: library items first, then by name
            sorted_items = sorted(items, key=lambda i: (0 if i.uri.startswith("library://") else 1, i.name.lower()))
            out = []
            for item in sorted_items:
                d = item.to_dict()
                d["thumb_url_resolved"] = ma.get_item_image_url(item, size=300)
                d.update(_provider_info(item.provider))
                out.append(d)
            return out

        all_groups = [
            ("playlists", "Playlists", serialize(results.playlists)),
            ("albums", "Albums", serialize(results.albums)),
            ("tracks", "Pistes", serialize(results.tracks)),
            ("artists", "Artistes", serialize(results.artists)),
            ("radio", "Radios", serialize(results.radio)),
            ("audiobooks", "Livres audio", serialize(results.audiobooks)),
            ("podcasts", "Podcasts", serialize(results.podcasts)),
        ]

        # Filter to only the selected category (unless "all")
        if category and category != "all":
            CATEGORY_GROUP_KEY = {
                "playlists": "playlists",
                "albums": "albums",
                "tracks": "tracks",
                "radios": "radio",
                "audiobooks": "audiobooks",
                "podcasts": "podcasts",
            }
            group_key = CATEGORY_GROUP_KEY.get(category)
            if group_key:
                groups = [(k, label, items) for k, label, items in all_groups if k == group_key]
            else:
                groups = all_groups
        else:
            groups = all_groups

        has_results = any(items for _, _, items in groups)
    except Exception as e:
        logger.error("MA search error: %s", e)
        return HTMLResponse(f'<div class="empty-state"><i class="mdi mdi-alert-circle"></i><p>Erreur Music Assistant: {e}</p></div>')

    return templates.TemplateResponse("components/ma_search_results.html", _base_ctx(
        request, groups=groups, has_results=has_results,
    ))


@router.post("/browse/import")
async def browse_import(
    uri: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Import a MA item into the local catalogue — returns JSON for JS fetch."""
    from app.services.music_assistant import get_ma_client
    ma = await get_ma_client()

    try:
        item = await ma.get_item_by_uri(uri)
    except Exception as exc:
        raise HTTPException(400, detail=f"Impossible de récupérer l'élément: {exc}")

    type_map = {
        "track": MediaType.track,
        "album": MediaType.album,
        "playlist": MediaType.playlist,
        "radio": MediaType.radio,
        "audiobook": MediaType.audiobook,
        "podcast": MediaType.podcast,
    }
    m_type = type_map.get(item.media_type, MediaType.track)

    provider = item.provider
    if item.provider_mappings:
        provider = item.provider_mappings[0].get("provider_domain", provider)

    data = MediaCreate(
        title=item.name,
        media_type=m_type,
        source_uri=item.uri,
        provider=provider,
        cover_url=ma.get_item_image_url(item, size=0),
        duration_min=item.duration // 60 if item.duration else None,
        description=item.description or None,
        metadata_extra={
            "artists": item.artist_str,
            "album": item.album_name,
            "ma_item_id": item.item_id,
        },
    )

    media, _created = await media_service.create_media(db, data)

    # Download cover
    thumb_url = ma.get_item_image_url(item, size=300)
    if thumb_url:
        local = await cover_service.download_and_save_cover(media.id, thumb_url)
        if local:
            media.cover_local = local
            await db.commit()

    return {"id": media.id, "title": media.title}


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------

@router.get("/players", response_class=HTMLResponse)
async def players_page(request: Request):
    players = []
    try:
        from app.services.music_assistant import get_ma_client
        ma = await get_ma_client()
        raw = await ma.get_players()
        players = [p.to_dict() for p in raw]
    except Exception as e:
        logger.error("Failed to fetch players: %s", e)

    return templates.TemplateResponse("ma/players.html", _base_ctx(
        request, players=players,
    ))
