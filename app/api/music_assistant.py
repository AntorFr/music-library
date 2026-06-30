"""
API routes for Music Assistant integration.

Allows browsing MA library, getting item details + thumbnail URLs,
and playing media on MA players.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.media import NowPlaying
from app.services import cover_service, media_service
from app.services.music_assistant import MusicAssistantClient, get_ma_client

router = APIRouter(prefix="/api/v1/ma", tags=["music-assistant"])


# ---------------------------------------------------------------------------
# Search & browse
# ---------------------------------------------------------------------------

@router.get("/search")
async def ma_search(
    q: str = Query(..., min_length=1, description="Requête de recherche"),
    types: str | None = Query(
        None, description="Types séparés par virgule: track,album,playlist,radio,audiobook,podcast"
    ),
    limit: int = Query(25, ge=1, le=100),
    library_only: bool = False,
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """
    Rechercher dans Music Assistant.

    Retourne les résultats groupés par type avec les URLs de miniatures.
    """
    media_types = types.split(",") if types else None

    results = await ma.search(q, media_types=media_types, limit=limit, library_only=library_only)

    def serialize_items(items):
        out = []
        for item in items:
            d = item.to_dict()
            d["thumb_url_resolved"] = ma.get_item_image_url(item, size=300)
            out.append(d)
        return out

    return {
        "tracks": serialize_items(results.tracks),
        "albums": serialize_items(results.albums),
        "playlists": serialize_items(results.playlists),
        "artists": serialize_items(results.artists),
        "radio": serialize_items(results.radio),
        "audiobooks": serialize_items(results.audiobooks),
        "podcasts": serialize_items(results.podcasts),
    }


@router.get("/item")
async def ma_get_item(
    uri: str = Query(..., description="URI Music Assistant (ex: spotify://playlist/xxx)"),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """
    Récupérer les infos détaillées d'un élément Music Assistant par URI.

    Retourne le titre, artistes, album, durée, et l'URL de la miniature.
    """
    try:
        item = await ma.get_item_by_uri(uri)
    except Exception as exc:
        raise HTTPException(400, detail=f"Impossible de récupérer l'élément: {exc}")

    data = item.to_dict()
    data["thumb_url_resolved"] = ma.get_item_image_url(item, size=300)
    data["thumb_url_full"] = ma.get_item_image_url(item, size=0)
    data["all_images"] = [
        {
            "type": img.type,
            "path": img.path,
            "provider": img.provider,
            "remotely_accessible": img.remotely_accessible,
            "url_300": ma.get_image_url(img, size=300),
            "url_original": ma.get_image_url(img, size=0),
        }
        for img in item.images
    ]
    return data


# ---------------------------------------------------------------------------
# Library listings
# ---------------------------------------------------------------------------

@router.get("/library/playlists")
async def ma_playlists(
    search: str | None = None,
    limit: int | None = None,
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Lister les playlists de la bibliothèque MA."""
    items = await ma.get_library_playlists(search=search, limit=limit)
    return [
        {**item.to_dict(), "thumb_url_resolved": ma.get_item_image_url(item, size=300)}
        for item in items
    ]


@router.get("/library/albums")
async def ma_albums(
    search: str | None = None,
    limit: int | None = None,
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Lister les albums de la bibliothèque MA."""
    items = await ma.get_library_albums(search=search, limit=limit)
    return [
        {**item.to_dict(), "thumb_url_resolved": ma.get_item_image_url(item, size=300)}
        for item in items
    ]


@router.get("/library/tracks")
async def ma_tracks(
    search: str | None = None,
    limit: int | None = None,
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Lister les pistes de la bibliothèque MA."""
    items = await ma.get_library_tracks(search=search, limit=limit)
    return [
        {**item.to_dict(), "thumb_url_resolved": ma.get_item_image_url(item, size=300)}
        for item in items
    ]


@router.get("/library/radios")
async def ma_radios(
    search: str | None = None,
    limit: int | None = None,
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Lister les stations radio de la bibliothèque MA."""
    items = await ma.get_library_radios(search=search, limit=limit)
    return [
        {**item.to_dict(), "thumb_url_resolved": ma.get_item_image_url(item, size=300)}
        for item in items
    ]


@router.get("/library/audiobooks")
async def ma_audiobooks(
    search: str | None = None,
    limit: int | None = None,
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Lister les livres audio de la bibliothèque MA."""
    items = await ma.get_library_audiobooks(search=search, limit=limit)
    return [
        {**item.to_dict(), "thumb_url_resolved": ma.get_item_image_url(item, size=300)}
        for item in items
    ]


@router.get("/library/podcasts")
async def ma_podcasts(
    search: str | None = None,
    limit: int | None = None,
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Lister les podcasts de la bibliothèque MA."""
    items = await ma.get_library_podcasts(search=search, limit=limit)
    return [
        {**item.to_dict(), "thumb_url_resolved": ma.get_item_image_url(item, size=300)}
        for item in items
    ]


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------

@router.get("/players")
async def ma_players(ma: MusicAssistantClient = Depends(get_ma_client)):
    """Lister les players Music Assistant disponibles."""
    players = await ma.get_players()
    return [p.to_dict() for p in players]


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

@router.post("/play")
async def ma_play(
    queue_id: str = Query(..., description="ID du player queue cible"),
    uri: str = Query(..., description="URI du média à jouer"),
    option: str | None = Query(None, description="play, replace, next, add"),
    radio_mode: bool = False,
    seek: int | None = Query(
        None,
        description="Position en secondes — saute à cet offset après le démarrage (ex: début de chapitre).",
    ),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Lancer la lecture d'un média sur un player via Music Assistant."""
    try:
        await ma.play_media(queue_id, uri, option=option, radio_mode=radio_mode)
        if seek and seek > 0:
            # Wait for the queue to actually start playing the item before seeking.
            import asyncio
            await asyncio.sleep(1.5)
            try:
                await ma.seek(queue_id, seek)
            except Exception as exc:
                # Non-fatal: playback started, only seek failed
                import logging
                logging.getLogger(__name__).warning("Seek failed: %s", exc)
    except Exception as exc:
        raise HTTPException(500, detail=f"Erreur de lecture: {exc}")
    return {"status": "ok", "queue_id": queue_id, "uri": uri, "seek": seek}


# ---------------------------------------------------------------------------
# Transport & playback controls — the standard HA media_player command set,
# so the embedded UI can mirror it (shuffle, repeat, volume, etc.).
# ---------------------------------------------------------------------------

async def _cmd(awaitable, label: str):
    """Await an MA command, mapping failures to a 500."""
    try:
        await awaitable
    except Exception as exc:
        raise HTTPException(500, detail=f"Erreur {label}: {exc}") from exc
    return {"status": "ok"}


@router.post("/pause")
async def ma_pause(
    queue_id: str = Query(...),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Pause the queue."""
    return await _cmd(ma.pause(queue_id), "pause")


@router.post("/resume")
async def ma_resume(
    queue_id: str = Query(...),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Resume the queue (does not change the current item)."""
    return await _cmd(ma.play(queue_id), "resume")


@router.post("/play_pause")
async def ma_play_pause(
    queue_id: str = Query(...),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Toggle play/pause."""
    return await _cmd(ma.play_pause(queue_id), "play_pause")


@router.post("/stop")
async def ma_stop(
    queue_id: str = Query(...),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Stop the queue."""
    return await _cmd(ma.stop(queue_id), "stop")


@router.post("/next")
async def ma_next(
    queue_id: str = Query(...),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Skip to the next item."""
    return await _cmd(ma.next_track(queue_id), "next")


@router.post("/previous")
async def ma_previous(
    queue_id: str = Query(...),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Go to the previous item."""
    return await _cmd(ma.previous_track(queue_id), "previous")


@router.post("/seek")
async def ma_seek(
    queue_id: str = Query(...),
    position: int = Query(..., ge=0, description="Position en secondes"),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Seek the current item to an absolute position (seconds)."""
    return await _cmd(ma.seek(queue_id, position), "seek")


@router.post("/shuffle")
async def ma_shuffle(
    queue_id: str = Query(...),
    enabled: bool = Query(..., description="Activer/désactiver l'aléatoire"),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Enable/disable shuffle."""
    return await _cmd(ma.set_shuffle(queue_id, enabled), "shuffle")


@router.post("/repeat")
async def ma_repeat(
    queue_id: str = Query(...),
    mode: str = Query(..., description="off | one | all"),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Set repeat mode (off | one | all)."""
    if mode not in ("off", "one", "all"):
        raise HTTPException(422, detail="mode doit être off | one | all")
    return await _cmd(ma.set_repeat(queue_id, mode), "repeat")


@router.post("/volume")
async def ma_volume(
    queue_id: str = Query(...),
    level: int = Query(..., ge=0, le=100, description="Volume absolu 0..100"),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Set absolute volume (0..100). queue_id is used as the player id."""
    return await _cmd(ma.set_volume(queue_id, level), "volume")


@router.post("/volume_step")
async def ma_volume_step(
    queue_id: str = Query(...),
    direction: str = Query(..., description="up | down"),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Step the volume up or down."""
    if direction == "up":
        return await _cmd(ma.volume_up(queue_id), "volume_up")
    if direction == "down":
        return await _cmd(ma.volume_down(queue_id), "volume_down")
    raise HTTPException(422, detail="direction doit être up | down")


@router.post("/mute")
async def ma_mute(
    queue_id: str = Query(...),
    muted: bool = Query(...),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Mute/unmute the player."""
    return await _cmd(ma.set_mute(queue_id, muted), "mute")


@router.post("/power")
async def ma_power(
    queue_id: str = Query(...),
    powered: bool = Query(...),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Power the player on/off."""
    return await _cmd(ma.set_power(queue_id, powered), "power")


@router.get("/now_playing", response_model=NowPlaying)
async def ma_now_playing(
    queue_id: str = Query(...),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """Compact playback state of a queue (for the embedded now-playing widget)."""
    try:
        data = await ma.get_now_playing(queue_id)
    except Exception as exc:
        raise HTTPException(503, detail=f"Music Assistant indisponible: {exc}") from exc
    return NowPlaying(**data)


# ---------------------------------------------------------------------------
# Import from MA → local catalogue
# ---------------------------------------------------------------------------

@router.post("/import")
async def ma_import_item(
    uri: str = Query(..., description="URI Music Assistant de l'élément à importer"),
    db: AsyncSession = Depends(get_db),
    ma: MusicAssistantClient = Depends(get_ma_client),
):
    """
    Importer un élément Music Assistant dans le catalogue local.

    Récupère les infos + miniature depuis MA et crée l'entrée dans la DB locale.
    """
    try:
        item = await ma.get_item_by_uri(uri)
    except Exception as exc:
        raise HTTPException(400, detail=f"Impossible de récupérer l'élément: {exc}")

    # Map MA media_type to our MediaType
    from app.models.media import MediaType
    type_map = {
        "track": MediaType.track,
        "album": MediaType.album,
        "playlist": MediaType.playlist,
        "radio": MediaType.radio,
        "audiobook": MediaType.audiobook,
        "podcast": MediaType.podcast,
    }
    media_type = type_map.get(item.media_type, MediaType.track)

    # Determine provider from provider_mappings or item
    provider = item.provider
    if item.provider_mappings:
        provider = item.provider_mappings[0].get("provider_domain", provider)

    from app.schemas.media import MediaCreate
    create_data = MediaCreate(
        title=item.name,
        media_type=media_type,
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

    media, _created = await media_service.create_media(db, create_data)

    # Also try to download and cache the thumbnail locally
    thumb_url = ma.get_item_image_url(item, size=300)
    if thumb_url:
        local_path = await cover_service.download_and_save_cover(media.id, thumb_url)
        if local_path:
            media.cover_local = local_path

    from app.schemas.media import MediaRead
    return MediaRead.model_validate(media)
