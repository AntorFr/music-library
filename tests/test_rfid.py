from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import media as _media_models  # noqa: F401
from app.models import rfid as _rfid_models  # noqa: F401
from app.models.media import Media, MediaType
from app.services import rfid_service


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_does_not_change_association(db: AsyncSession):
    t = await rfid_service.upsert_rfid_tag(db, uid="04-70-D7-DA", name="Carte A")
    assert t.media_id is None
    await db.commit()

    t2 = await rfid_service.upsert_rfid_tag(db, uid="04-70-D7-DA", name="Carte A2")
    await db.commit()

    assert t2.uid == "04-70-D7-DA"
    assert t2.name == "Carte A2"
    assert t2.media_id is None


@pytest.mark.asyncio
async def test_assign_unassigned_only(db: AsyncSession):
    media1 = Media(
        title="Track 1",
        media_type=MediaType.track,
        source_uri="spotify://track/1",
        provider="spotify",
        cover_url=None,
        cover_local=None,
        duration_min=None,
        description=None,
        metadata_extra=None,
        is_active=True,
    )
    media2 = Media(
        title="Track 2",
        media_type=MediaType.track,
        source_uri="spotify://track/2",
        provider="spotify",
        cover_url=None,
        cover_local=None,
        duration_min=None,
        description=None,
        metadata_extra=None,
        is_active=True,
    )
    db.add_all([media1, media2])
    await db.flush()

    await rfid_service.upsert_rfid_tag(db, uid="04-70-D7-DA", name="Carte A")
    await rfid_service.upsert_rfid_tag(db, uid="04-75-D7-DA", name="Carte B")
    await db.commit()

    await rfid_service.assign_rfid_tags_to_media(db, media_id=media1.id, uids=["04-70-D7-DA"])
    await db.commit()

    # Assigning the same UID to a different media must fail
    with pytest.raises(rfid_service.RFIDAlreadyAssignedError):
        await rfid_service.assign_rfid_tags_to_media(db, media_id=media2.id, uids=["04-70-D7-DA"])


@pytest.mark.asyncio
async def test_list_unassigned_and_resolve(db: AsyncSession):
    media = Media(
        title="Track X",
        media_type=MediaType.track,
        source_uri="spotify://track/x",
        provider="spotify",
        cover_url=None,
        cover_local=None,
        duration_min=None,
        description=None,
        metadata_extra=None,
        is_active=True,
    )
    db.add(media)
    await db.flush()

    await rfid_service.upsert_rfid_tag(db, uid="04-70-D7-DA", name="Carte A")
    await rfid_service.upsert_rfid_tag(db, uid="04-75-D7-DA", name="Carte B")
    await db.commit()

    await rfid_service.assign_rfid_tags_to_media(db, media_id=media.id, uids=["04-70-D7-DA"])
    await db.commit()

    unassigned = await rfid_service.list_rfid_tags(db, assigned=False)
    assert [t.uid for t in unassigned] == ["04-75-D7-DA"]

    resolved = await rfid_service.resolve_media_for_rfid(db, uid="04-70-D7-DA")
    assert resolved is not None
    assert resolved.title == "Track X"
