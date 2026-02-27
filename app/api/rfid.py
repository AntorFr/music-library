"""API routes for managing RFID tags and resolving media by RFID UID."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.rfid import RFIDResolveResponse, RFIDTagRead, RFIDTagUpsert
from app.services import rfid_service

router = APIRouter(prefix="/api/v1/rfid", tags=["rfid"])


@router.get("", response_model=list[RFIDTagRead])
async def list_rfid(
    assigned: bool | None = Query(
        None, description="true=only assigned, false=only unassigned, null=all"
    ),
    db: AsyncSession = Depends(get_db),
):
    tags = await rfid_service.list_rfid_tags(db, assigned=assigned)
    out: list[RFIDTagRead] = []
    for t in tags:
        out.append(
            RFIDTagRead(
                uid=t.uid,
                name=t.name,
                media_id=t.media_id,
                media_title=t.media.title if getattr(t, "media", None) else None,
            )
        )
    return out


@router.put("/{uid}", response_model=RFIDTagRead, summary="Create or rename a RFID tag")
async def upsert_rfid(
    uid: str,
    payload: RFIDTagUpsert,
    db: AsyncSession = Depends(get_db),
):
    tag = await rfid_service.upsert_rfid_tag(db, uid=uid, name=payload.name)
    return RFIDTagRead(
        uid=tag.uid,
        name=tag.name,
        media_id=tag.media_id,
        media_title=tag.media.title if getattr(tag, "media", None) else None,
    )


@router.get("/{uid}/media", response_model=RFIDResolveResponse)
async def resolve_media(
    request: Request,
    uid: str,
    db: AsyncSession = Depends(get_db),
):
    media = await rfid_service.resolve_media_for_rfid(db, uid=uid)
    if not media:
        raise HTTPException(404, detail="Tag RFID introuvable ou non associé")

    base = str(request.base_url).rstrip("/")
    return RFIDResolveResponse(
        uid=uid,
        media_id=media.id,
        title=media.title,
        source_uri=media.source_uri,
        provider=media.provider,
        cover_url_resolved=f"{base}/covers/{media.id}.jpg",
    )
