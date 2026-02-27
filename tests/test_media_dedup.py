from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import media as _media_models  # noqa: F401
from app.schemas.media import MediaCreate
from app.services import media_service
from app.models.media import MediaType


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
async def test_create_media_is_idempotent_on_provider_source_uri(db: AsyncSession):
    data = MediaCreate(
        title="Test",
        media_type=MediaType.track,
        source_uri="spotify://track/123",
        provider="spotify",
        cover_url=None,
        duration_min=None,
        description=None,
        metadata_extra=None,
        tag_ids=[],
        tags_inline=[],
    )

    item1, created1 = await media_service.create_media(db, data)
    await db.commit()

    item2, created2 = await media_service.create_media(db, data)
    await db.commit()

    assert created1 is True
    assert created2 is False
    assert item1.id == item2.id

    # Ensure only one row exists
    items, total = await media_service.list_media(db, page=1, page_size=50)
    assert total == 1
    assert items[0].id == item1.id
