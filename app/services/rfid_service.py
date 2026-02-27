"""RFID tag service.

Rules:
- A RFID tag can be associated to at most one media item.
- A media item can have multiple RFID tags.
- Upsert endpoints must not change association.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.media import Media
from app.models.rfid import RFIDTag


class RFIDAlreadyAssignedError(RuntimeError):
    def __init__(self, uid: str, media_id: str):
        super().__init__(f"RFID tag {uid} already assigned to media {media_id}")
        self.uid = uid
        self.media_id = media_id


async def list_rfid_tags(
    db: AsyncSession,
    *,
    assigned: bool | None = None,
) -> list[RFIDTag]:
    stmt = select(RFIDTag).options(selectinload(RFIDTag.media))
    if assigned is True:
        stmt = stmt.where(RFIDTag.media_id.is_not(None))
    elif assigned is False:
        stmt = stmt.where(RFIDTag.media_id.is_(None))

    stmt = stmt.order_by(RFIDTag.uid.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_rfid_tag(db: AsyncSession, uid: str) -> RFIDTag | None:
    stmt = select(RFIDTag).options(selectinload(RFIDTag.media)).where(RFIDTag.uid == uid)
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def upsert_rfid_tag(db: AsyncSession, uid: str, name: str) -> RFIDTag:
    existing = await get_rfid_tag(db, uid)
    if existing:
        existing.name = name
        await db.flush()
        return existing

    tag = RFIDTag(uid=uid, name=name, media_id=None)
    db.add(tag)
    await db.flush()
    return tag


async def assign_rfid_tags_to_media(
    db: AsyncSession,
    *,
    media_id: str,
    uids: list[str],
) -> list[RFIDTag]:
    """Assign unassigned RFID tags to a media.

    Raises RFIDAlreadyAssignedError if any uid is assigned to another media.
    Unknown uids are ignored (simple UX).
    """

    if not uids:
        return []

    media = await db.get(Media, media_id)
    if not media:
        return []

    stmt = select(RFIDTag).where(RFIDTag.uid.in_(uids)).options(selectinload(RFIDTag.media))
    res = await db.execute(stmt)
    tags = list(res.scalars().all())

    out: list[RFIDTag] = []
    for t in tags:
        if t.media_id and t.media_id != media_id:
            raise RFIDAlreadyAssignedError(t.uid, t.media_id)
        t.media_id = media_id
        out.append(t)

    await db.flush()
    return out


async def unassign_rfid_tag(db: AsyncSession, *, uid: str) -> bool:
    tag = await get_rfid_tag(db, uid)
    if not tag:
        return False
    tag.media_id = None
    await db.flush()
    return True


async def resolve_media_for_rfid(db: AsyncSession, *, uid: str) -> Media | None:
    tag = await get_rfid_tag(db, uid)
    if not tag or not tag.media_id:
        return None
    return await db.get(Media, tag.media_id)
