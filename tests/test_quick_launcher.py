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


async def _create_media(db: AsyncSession, *, title: str, owner: str, uri: str):
    item, _ = await media_service.create_media(
        db,
        MediaCreate(
            title=title,
            media_type=MediaType.playlist,
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
async def test_quick_route_contains_owners_and_renders_without_players(client: AsyncClient):
    response = await client.get("/quick")

    assert response.status_code == 200
    assert "Lanceur" in response.text
    assert 'value="papa"' in response.text
    assert "Aucune enceinte Music Assistant" in response.text


@pytest.mark.asyncio
async def test_quick_route_filters_media_by_owner(client: AsyncClient, db: AsyncSession):
    await _create_media(db, title="Playlist Papa", owner="papa", uri="spotify://playlist/papa")
    await _create_media(db, title="Playlist Maman", owner="maman", uri="spotify://playlist/maman")

    response = await client.get("/quick?owner=papa")

    assert response.status_code == 200
    assert "Playlist Papa" in response.text
    assert "Playlist Maman" not in response.text


@pytest.mark.asyncio
async def test_manifest_contract(client: AsyncClient):
    response = await client.get("/manifest.webmanifest")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Music Library"
    assert data["short_name"] == "Music"
    assert data["start_url"] == "/quick"
    assert data["display"] == "standalone"
    assert data["icons"]
