"""Music Assistant browse, search and import pages."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.views.shared import (
    _base_ctx,
    _provider_info,
    templates,
)
from app.database import get_db
from app.models.media import MediaType
from app.services.auth_service import get_current_user
from app.services.ma_import import import_ma_item
from app.services.tag_service import (
    list_tag_categories,
    list_tags,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["frontend"])


@router.get("/browse", response_class=HTMLResponse)
async def browse_page(request: Request, db: AsyncSession = Depends(get_db)):
    """The "Ajouter" entry: adding goes through Music Assistant in practice.

    The hand-typed form — an RSS feed, a stream URL — is a modal here rather than
    the page the nav used to point at. Open to children too: their addition is
    auto-tagged to their own profile (see media_service.create_media).
    """
    all_tags = await list_tags(db)
    categories = await list_tag_categories(db)
    return templates.TemplateResponse(request, "ma/browse.html", _base_ctx(
        request,
        active_nav="add",
        available_tags=all_tags,
        cat_labels={c.slug: c.label for c in categories},
        cat_colors={c.slug: c.color for c in categories if getattr(c, "color", None)},
        media_types=list(MediaType),
    ))


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
            d.update(_provider_info(item.provider))
            items.append(d)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("MA browse error: %s", e)
        items = []

    return templates.TemplateResponse(request, "components/ma_items.html", _base_ctx(
        request, items=items,
    ))


@router.get("/browse/search", response_class=HTMLResponse)
async def browse_search(request: Request, q: str = Query("", alias="maSearch")):
    # HTMX sends the input name as param, otherwise use q
    search_q = request.query_params.get("maSearch") or request.query_params.get("q") or q
    category = request.query_params.get("category", "all")

    if not search_q or len(search_q) < 2:
        return HTMLResponse(
            '<div class="empty-state"><i class="mdi mdi-magnify"></i>'
            "<p>Tapez au moins 2 caractères…</p></div>"
        )

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

        def serialize(items):
            # Sort: library items first, then by name
            sorted_items = sorted(
                items,
                key=lambda i: (0 if i.uri.startswith("library://") else 1, i.name.lower()),
            )
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
        return HTMLResponse(
            '<div class="empty-state"><i class="mdi mdi-alert-circle"></i>'
            f"<p>Erreur Music Assistant: {e}</p></div>"
        )

    return templates.TemplateResponse(request, "components/ma_search_results.html", _base_ctx(
        request, groups=groups, has_results=has_results,
    ))


@router.post("/browse/import")
async def browse_import(
    request: Request,
    uri: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Import a MA item into the local catalogue — returns JSON for JS fetch."""
    from app.services.music_assistant import get_ma_client

    media = await import_ma_item(
        db, await get_ma_client(), uri,
        owner_value=get_current_user(request).owner_value,
    )
    return {"id": media.id, "title": media.title}


