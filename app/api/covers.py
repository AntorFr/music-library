"""API routes for covers (static serving + upload)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services import cover_service, media_service

router = APIRouter(tags=["covers"])


@router.get("/covers/{media_id}.jpg")
async def get_cover(media_id: str, db: AsyncSession = Depends(get_db)):
    """
    Serve a cover image as a static file.

    Stable URL for ESPHome: `http://host:8000/covers/{media_id}.jpg`

    If the local file is missing but a cover_url exists in the database,
    re-downloads it automatically (self-healing cache).
    """
    path = cover_service.get_cover_path(media_id)

    # Auto-recover: if local file is gone, try re-downloading from cover_url
    if not path:
        media = await media_service.get_media(db, media_id)
        if media and media.cover_url:
            local = await cover_service.ensure_local_cover(media_id, media.cover_url)
            if local:
                media.cover_local = local
                await db.commit()
                path = cover_service.get_cover_path(media_id)

    if not path:
        default = settings.default_cover
        return FileResponse(default, media_type="image/jpeg")

    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/api/v1/media/{media_id}/cover", tags=["media"])
async def upload_cover(
    media_id: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    """Upload a cover image for a media item."""
    media = await media_service.get_media(db, media_id)
    if not media:
        raise HTTPException(404, detail="Média introuvable")

    content = await file.read()
    local_path = await cover_service.save_cover_from_bytes(media_id, content)
    if not local_path:
        raise HTTPException(500, detail="Erreur lors du traitement de l'image")

    media.cover_local = local_path
    return {"cover_local": local_path, "url": f"/covers/{media_id}.jpg"}
