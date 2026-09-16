"""The two MA import surfaces must create exactly the same local row.

They used to be two copies of the same forty lines (JSON API + browse page), which is
the shape that let the MA resolver rot on one side only. These tests pin the shared
``services/ma_import.import_ma_item`` from both ends.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import media as _media_models  # noqa: F401
from app.models import rfid as _rfid_models  # noqa: F401
from app.models.media import Media, MediaType
from app.services.music_assistant import get_ma_client
from app.services.tag_service import seed_default_tags


class FakeItem:
    """A podcast as MA hands it over: library URI, but a Spotify origin mapping."""

    name = "Wyktaur"
    media_type = "podcast"
    uri = "library://podcast/88"
    provider = "library"
    provider_mappings = [{"provider_domain": "spotify", "item_id": "033xL1jpR7s2LsMLxpnfRl"}]
    duration = 3600
    description = "Podcast officiel."
    artist_str = ""
    album_name = ""
    item_id = "88"


class FakeMA:
    def __init__(self):
        self.item = FakeItem()

    async def get_item_by_uri(self, uri):
        if uri != self.item.uri:
            raise RuntimeError(f"{uri} not found")
        return self.item

    def get_item_image_url(self, item, size=0):
        return f"https://cdn.test/{item.item_id}?s={size}"


@pytest.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'t.db'}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        await seed_default_tags(session)
        await session.commit()
        yield session
    await engine.dispose()


@pytest.fixture
def fake_ma(monkeypatch):
    ma = FakeMA()

    async def _get(*_a, **_k):
        return ma

    # The JSON API injects the client; the HTMX view imports it directly.
    app.dependency_overrides[get_ma_client] = lambda: ma
    monkeypatch.setattr("app.services.music_assistant.get_ma_client", _get)
    # No network: the cover download is exercised elsewhere.
    monkeypatch.setattr(
        "app.services.cover_service.download_and_save_cover",
        lambda *_a, **_k: _none(),
    )
    return ma


async def _none():
    return None


@pytest.fixture
async def client(db: AsyncSession, fake_ma: FakeMA):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _imported_row(db: AsyncSession) -> Media:
    rows = (await db.execute(select(Media))).scalars().all()
    assert len(rows) == 1, f"expected exactly one imported row, got {len(rows)}"
    return rows[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/ma/import", "/browse/import"])
async def test_import_creates_the_same_row(client, db, path):
    r = await client.post(f"{path}?uri=library://podcast/88")
    assert r.status_code in (200, 201), r.text

    row = await _imported_row(db)
    assert row.title == "Wyktaur"
    assert row.media_type == MediaType.podcast
    assert row.source_uri == "library://podcast/88"
    # The *origin* provider wins over item.provider — it is display info, not an address.
    assert row.provider == "spotify"
    assert row.metadata_extra["ma_item_id"] == "88"
    assert row.duration_min == 60


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/ma/import", "/browse/import"])
async def test_import_unknown_uri_is_a_400(client, path):
    r = await client.post(f"{path}?uri=library://podcast/999")
    assert r.status_code == 400
    assert "Impossible de récupérer" in r.text
