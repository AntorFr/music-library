"""Media detail sub-resources: Spotify account, episodes, chapters, RFID, tags."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.views.shared import (
    _base_ctx,
    _build_available_tag_options,
    _parse_tag_input,
    templates,
)
from app.database import get_db
from app.models.media import MediaType
from app.services import media_service, rfid_service, spotify_accounts
from app.services.auth_service import get_current_user
from app.services.permissions import (
    OWNER_CATEGORY,
    ensure_media_access,
    ensure_media_edit,
    ensure_parent,
    is_protected_owner_tag,
)
from app.services.tag_service import (
    list_tag_categories,
    list_tags,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["frontend"])


async def _spotify_account_block(
    request: Request, item: Any, *, error: str | None = None
) -> HTMLResponse:
    """The "Compte Spotify" card: MA's Spotify accounts, the current one selected."""
    accounts: list[dict] = []
    load_error: str | None = None
    try:
        from app.services.music_assistant import get_ma_client
        accounts = await spotify_accounts.list_accounts(await get_ma_client())
    except Exception as exc:
        logger.warning("Spotify accounts unavailable: %s", exc)
        load_error = str(exc)
    return templates.TemplateResponse(request, "components/spotify_account.html", _base_ctx(
        request,
        item=item,
        accounts=accounts,
        current=spotify_accounts.current_account(item),
        error=error or load_error,
    ))


@router.get("/media/{media_id}/spotify-account", response_class=HTMLResponse)
async def media_spotify_account(
    request: Request, media_id: str, db: AsyncSession = Depends(get_db)
):
    """HTMX partial: the account picker, loaded after the page (it asks MA)."""
    ensure_parent(get_current_user(request))
    item = await media_service.get_media(db, media_id)
    if not item:
        raise HTTPException(404, detail="Média introuvable")
    return await _spotify_account_block(request, item)


@router.post("/media/{media_id}/spotify-account", response_class=HTMLResponse)
async def media_set_spotify_account(
    request: Request,
    media_id: str,
    account: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Pin the media to one Spotify account, after checking it returns content.

    On success the whole page reloads: the play button, the episode list and the
    source URI shown below all derive from the URI that just changed.
    """
    ensure_parent(get_current_user(request))
    item = await media_service.get_media(db, media_id)
    if not item:
        raise HTTPException(404, detail="Média introuvable")
    try:
        from app.services.music_assistant import get_ma_client
        await spotify_accounts.switch_account(db, await get_ma_client(), item, account)
    except spotify_accounts.AccountSwitchError as exc:
        return await _spotify_account_block(request, item, error=str(exc))
    except Exception as exc:
        logger.warning("Spotify account switch failed for %s: %s", media_id, exc)
        return await _spotify_account_block(request, item, error=f"Music Assistant : {exc}")
    await db.commit()
    return HTMLResponse("", headers={"HX-Refresh": "true"})


@router.get("/media/{media_id}/episodes", response_class=HTMLResponse)
async def media_podcast_episodes(
    request: Request, media_id: str, db: AsyncSession = Depends(get_db)
):
    """HTMX partial: list of podcast episodes from Music Assistant."""
    item = await media_service.get_media(db, media_id)
    ensure_media_access(get_current_user(request), item)
    if item.media_type != MediaType.podcast:
        return templates.TemplateResponse(request, "components/podcast_episodes.html",
            {"request": request, "episodes": [], "item": item, "error": None},
        )

    error: str | None = None
    episodes: list[dict] = []
    try:
        from app.services.music_assistant import fetch_podcast_episodes, get_ma_client
        ma = await get_ma_client()

        ma_episodes = await fetch_podcast_episodes(ma, item)
        episodes = [
            {
                "uri": e.uri,
                "name": e.name,
                "position": e.position,
                "duration": e.duration,
                "fully_played": e.fully_played,
                "resume_position_ms": e.resume_position_ms,
                "thumb_url": ma.get_image_url(e.thumb_image, size=120),
            }
            for e in ma_episodes
        ]
    except Exception as exc:
        logger.warning("Failed to fetch podcast episodes for %s: %s", media_id, exc)
        error = str(exc)

    return templates.TemplateResponse(request, "components/podcast_episodes.html",
        {"request": request, "episodes": episodes, "item": item, "error": error},
    )


@router.get("/media/{media_id}/chapters", response_class=HTMLResponse)
async def media_audiobook_chapters(
    request: Request, media_id: str, db: AsyncSession = Depends(get_db)
):
    """HTMX partial: list of audiobook chapters from Music Assistant."""
    item = await media_service.get_media(db, media_id)
    ensure_media_access(get_current_user(request), item)
    if item.media_type != MediaType.audiobook:
        return templates.TemplateResponse(request, "components/audiobook_chapters.html",
            {"request": request, "chapters": [], "item": item, "error": None,
             "audiobook_uri": "", "resume_pct": 0, "resume_position_ms": None,
             "fully_played": None},
        )

    error: str | None = None
    chapters: list[dict] = []
    audiobook_uri = item.source_uri or ""
    resume_position_ms: int | None = None
    fully_played: bool | None = None
    duration_s = 0
    try:
        from app.services.music_assistant import (
            fetch_audiobook,
            get_ma_client,
            normalize_chapters,
        )
        ma = await get_ma_client()

        ma_item = await fetch_audiobook(ma, item)
        audiobook_uri = ma_item.uri or audiobook_uri
        resume_position_ms = ma_item.resume_position_ms
        fully_played = ma_item.fully_played
        duration_s = ma_item.duration or 0
        chapters = normalize_chapters(ma_item)
    except Exception as exc:
        logger.warning("Failed to fetch audiobook chapters for %s: %s", media_id, exc)
        error = str(exc)

    resume_pct = 0
    if duration_s and resume_position_ms:
        resume_pct = round((resume_position_ms / 1000) / duration_s * 100)

    return templates.TemplateResponse(request, "components/audiobook_chapters.html",
        {
            "request": request,
            "chapters": chapters,
            "item": item,
            "error": error,
            "audiobook_uri": audiobook_uri,
            "resume_position_ms": resume_position_ms,
            "fully_played": fully_played,
            "resume_pct": resume_pct,
        },
    )


@router.post("/media/{media_id}/rfid")
async def media_assign_rfid(
    request: Request,
    media_id: str,
    rfid_uids: list[str] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
):
    ensure_parent(get_current_user(request))
    try:
        await rfid_service.assign_rfid_tags_to_media(db, media_id=media_id, uids=rfid_uids)
        await db.commit()
    except rfid_service.RFIDAlreadyAssignedError as exc:
        raise HTTPException(409, detail=f"Tag RFID déjà associé: {exc.uid}") from exc

    if request.headers.get("HX-Target") == "rfid-assigned":
        item = await media_service.get_media(db, media_id)
        if not item:
            raise HTTPException(404, detail="Média introuvable")
        assigned_rfid = [
            {"uid": t.uid, "name": t.name}
            for t in (getattr(item, "rfid_tags", []) or [])
        ]
        return templates.TemplateResponse(request, "components/rfid_assigned.html",
            _base_ctx(request, item=item, assigned_rfid=assigned_rfid),
        )

    return RedirectResponse(f"/media/{media_id}", status_code=303)


@router.post("/media/{media_id}/rfid/{uid}/remove")
async def media_unassign_rfid(
    request: Request,
    media_id: str,
    uid: str,
    db: AsyncSession = Depends(get_db),
):
    ensure_parent(get_current_user(request))
    await rfid_service.unassign_rfid_tag(db, uid=uid)
    await db.commit()

    if request.headers.get("HX-Target") == "rfid-assigned":
        item = await media_service.get_media(db, media_id)
        if not item:
            raise HTTPException(404, detail="Média introuvable")
        assigned_rfid = [
            {"uid": t.uid, "name": t.name}
            for t in (getattr(item, "rfid_tags", []) or [])
        ]
        return templates.TemplateResponse(request, "components/rfid_assigned.html",
            _base_ctx(request, item=item, assigned_rfid=assigned_rfid),
        )

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
    categories = await list_tag_categories(db)
    cat_labels = {c.slug: c.label for c in categories}
    cat_colors = {c.slug: c.color for c in categories if getattr(c, "color", None)}

    if tag:
        category, value = _parse_tag_input(raw=tag, cat_labels=cat_labels)
    if not category or not value:
        raise HTTPException(400, detail="Tag invalide")

    user = get_current_user(request)
    existing = await media_service.get_media(db, media_id)
    ensure_media_edit(user, existing)
    if user.owner_value is not None and category == OWNER_CATEGORY:
        raise HTTPException(403, detail="Tags propriétaires gérés par les parents")

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
    if request.headers.get("HX-Target") == "media-tags":
        return templates.TemplateResponse(request, "components/media_tags.html", {
            "request": request,
            "item": item,
            "cat_labels": cat_labels,
            "cat_colors": cat_colors,
            "current_user": user,
        })

    return templates.TemplateResponse(request, "components/media_tags_block.html", {
        "request": request,
        "item": item,
        "cat_labels": cat_labels,
        "cat_colors": cat_colors,
        "available_tag_options": available_tag_options,
        "current_user": user,
    })


@router.delete("/media/{media_id}/tags/{tag_id}", response_class=HTMLResponse)
async def media_remove_tag(
    request: Request,
    media_id: str,
    tag_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Remove a tag from a media item and return the updated tags block partial."""
    user = get_current_user(request)
    existing = await media_service.get_media(db, media_id)
    ensure_media_edit(user, existing)
    target = next((t for t in existing.tags if t.id == tag_id), None)
    if target is not None and is_protected_owner_tag(user, target):
        raise HTTPException(403, detail="Tags propriétaires gérés par les parents")

    item = await media_service.remove_tag_from_media(db, media_id, tag_id)
    if not item:
        raise HTTPException(404, detail="Média introuvable")
    await db.commit()
    categories = await list_tag_categories(db)
    cat_labels = {c.slug: c.label for c in categories}
    cat_colors = {c.slug: c.color for c in categories if getattr(c, "color", None)}
    all_tags = await list_tags(db)
    available_tag_options = _build_available_tag_options(
        item=item,
        all_tags=all_tags,
        cat_labels=cat_labels,
    )
    if request.headers.get("HX-Target") == "media-tags":
        return templates.TemplateResponse(request, "components/media_tags.html", {
            "request": request,
            "item": item,
            "cat_labels": cat_labels,
            "cat_colors": cat_colors,
            "current_user": user,
        })

    return templates.TemplateResponse(request, "components/media_tags_block.html", {
        "request": request,
        "item": item,
        "cat_labels": cat_labels,
        "cat_colors": cat_colors,
        "available_tag_options": available_tag_options,
        "current_user": user,
    })

