"""Import a Music Assistant item into the local catalogue.

Shared by the two surfaces that offer it — the JSON API (``/api/v1/ma/import``) and the
browse page's JS fetch (``/browse/import``). They used to carry a copy each of the same
forty lines, which is how the two copies of the MA resolver managed to drift apart for
three months (see :func:`~app.services.music_assistant.resolve_ma_provider_and_id`).
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import Media, MediaType
from app.schemas.media import MediaCreate
from app.services import cover_service, media_service
from app.services.music_assistant import MusicAssistantClient

#: MA media_type string -> our enum. Anything unknown lands on ``track``.
MA_TYPE_TO_MEDIA_TYPE: dict[str, MediaType] = {
    "track": MediaType.track,
    "album": MediaType.album,
    "playlist": MediaType.playlist,
    "radio": MediaType.radio,
    "audiobook": MediaType.audiobook,
    "podcast": MediaType.podcast,
}

#: Square size (px) of the cover we cache locally at import time.
COVER_PX = 300


async def import_ma_item(
    db: AsyncSession,
    ma: MusicAssistantClient,
    uri: str,
    *,
    owner_value: str | None,
) -> Media:
    """Create (or return) the local row for the MA item at ``uri``, cover included.

    Raises ``HTTPException(400)`` when MA cannot resolve the URI. The caller shapes the
    response; the session is committed by the ``get_db`` dependency.
    """
    try:
        item = await ma.get_item_by_uri(uri)
    except Exception as exc:
        raise HTTPException(400, detail=f"Impossible de récupérer l'élément: {exc}") from exc

    # The *origin* provider, for display and bookkeeping only. It is NOT a valid pair with
    # the library item id — addressing MA again goes through source_uri, see
    # resolve_ma_provider_and_id().
    provider = item.provider
    if item.provider_mappings:
        provider = item.provider_mappings[0].get("provider_domain", provider)

    media, _created = await media_service.create_media(
        db,
        MediaCreate(
            title=item.name,
            media_type=MA_TYPE_TO_MEDIA_TYPE.get(item.media_type, MediaType.track),
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
        ),
        force_owner_value=owner_value,
    )

    thumb_url = ma.get_item_image_url(item, size=COVER_PX)
    if thumb_url:
        local_path = await cover_service.download_and_save_cover(media.id, thumb_url)
        if local_path:
            media.cover_local = local_path

    return media
