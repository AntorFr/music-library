from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import media as _media_models  # noqa: F401
from app.models import rfid as _rfid_models  # noqa: F401
from app.models.media import MediaType
from app.schemas.media import MediaCreate
from app.services import media_service
from app.services.tag_service import seed_default_tags


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        await seed_default_tags(session)
        await session.commit()
        yield session

    await engine.dispose()


@pytest.fixture
async def client(db: AsyncSession):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _create_media(
    db: AsyncSession,
    *,
    title: str,
    owner: str,
    uri: str,
    media_type: MediaType = MediaType.playlist,
):
    item, _ = await media_service.create_media(
        db,
        MediaCreate(
            title=title,
            media_type=media_type,
            source_uri=uri,
            provider="spotify",
            cover_url=None,
            duration_min=None,
            description=None,
            metadata_extra=None,
            tag_ids=[],
            tags_inline=[{"category": "owner", "value": owner}],
        ),
    )
    await db.commit()
    return item


@pytest.mark.asyncio
async def test_quick_api_returns_owner_favourites(client: AsyncClient, db: AsyncSession):
    item = await _create_media(
        db, title="Comptines", owner="lea", uri="spotify://playlist/comptines"
    )
    await _create_media(db, title="Rock Papa", owner="papa", uri="spotify://playlist/rock")

    response = await client.get("/api/v1/quick/lea")

    assert response.status_code == 200
    data = response.json()
    assert data["owner"] == "lea"
    assert data["count"] == 1
    assert len(data["items"]) == 1

    entry = data["items"][0]
    assert entry["id"] == item.id
    assert entry["title"] == "Comptines"
    assert entry["media_type"] == "playlist"
    assert entry["uri"] == "spotify://playlist/comptines"
    assert entry["cover_url"] == f"http://test/covers/{item.id}.jpg"
    assert entry["has_children"] is False


@pytest.mark.asyncio
async def test_quick_api_flags_children_for_podcast(client: AsyncClient, db: AsyncSession):
    await _create_media(
        db,
        title="Henri le Lapin",
        owner="lea",
        uri="spotify://podcast/henri",
        media_type=MediaType.podcast,
    )

    response = await client.get("/api/v1/quick/lea")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["media_type"] == "podcast"
    assert items[0]["has_children"] is True


@pytest.mark.asyncio
async def test_quick_api_media_type_filter(client: AsyncClient, db: AsyncSession):
    await _create_media(db, title="Comptines", owner="lea", uri="spotify://playlist/comptines")
    await _create_media(
        db,
        title="Le Petit Prince",
        owner="lea",
        uri="spotify://audiobook/prince",
        media_type=MediaType.audiobook,
    )

    response = await client.get("/api/v1/quick/lea?media_type=audiobook")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Le Petit Prince"


@pytest.mark.asyncio
async def test_quick_api_unknown_owner_is_empty(client: AsyncClient):
    response = await client.get("/api/v1/quick/nobody")

    assert response.status_code == 200
    data = response.json()
    assert data == {"owner": "nobody", "count": 0, "items": []}
