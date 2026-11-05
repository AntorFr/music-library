"""REST contract of ``/api/v1/quick`` beyond what test_quick_api / test_ma_* already pin:
the signed thumbnail proxy, parameter validation, MA failures, child scoping."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app as app_pkg
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import media as _media_models  # noqa: F401
from app.models import rfid as _rfid_models  # noqa: F401
from app.models.media import MediaType
from app.schemas.media import MediaCreate
from app.services import cover_service, media_service
from app.services.music_assistant import get_ma_client
from app.services.tag_service import seed_default_tags


class BrokenMA:
    """Music Assistant stub whose every browse call fails (no network)."""

    async def get_podcast_episodes(self, item_id, provider):
        raise RuntimeError("MA down")

    async def get_item(self, media_type, item_id, provider):
        raise RuntimeError("MA down")

    async def get_item_by_uri(self, uri):
        raise RuntimeError("MA down")

    def get_item_image_url(self, item, size=0):
        return ""


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
async def client(db: AsyncSession):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_ma_client] = lambda: BrokenMA()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _create(db, *, title, uri, owner=None, media_type=MediaType.playlist):
    item, _ = await media_service.create_media(
        db,
        MediaCreate(
            title=title, media_type=media_type, source_uri=uri, provider="spotify",
            tags_inline=[{"category": "owner", "value": owner}] if owner else [],
        ),
    )
    await db.commit()
    return item


# --- /thumb ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_thumb_without_signature_is_422(client):
    r = await client.get("/api/v1/quick/thumb?src=http://x/y.jpg")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_thumb_with_wrong_signature_is_403(client):
    r = await client.get("/api/v1/quick/thumb?src=http://x/y.jpg&size=96&sig=deadbeefdeadbeef")
    assert r.status_code == 403
    assert r.json() == {"detail": "Invalid or missing signature"}


@pytest.mark.asyncio
async def test_thumb_signature_is_bound_to_the_size(client):
    sig = cover_service.sign_thumb("http://x/y.jpg", 96)
    r = await client.get(f"/api/v1/quick/thumb?src=http://x/y.jpg&size=128&sig={sig}")
    assert r.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["size=15", "size=513", "fmt=png"])
async def test_thumb_rejects_out_of_range_parameters(client, q):
    sig = cover_service.sign_thumb("http://x/y.jpg", 96)
    r = await client.get(f"/api/v1/quick/thumb?src=http://x/y.jpg&sig={sig}&size=96&{q}")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_thumb_download_failure_falls_back_to_the_default_cover(client, monkeypatch):
    # settings.default_cover is relative to the working directory (/app in the image, where
    # it resolves to app/static); the test points it at the file so the cwd does not matter.
    monkeypatch.setattr(settings, "default_cover", str(Path(app_pkg.__file__).parent / "static/img/default_cover.jpg"))
    async def none(*_a, **_k):
        return None

    monkeypatch.setattr(cover_service, "get_or_make_thumb", none)
    sig = cover_service.sign_thumb("http://x/y.jpg", 96)
    r = await client.get(f"/api/v1/quick/thumb?src=http://x/y.jpg&size=96&sig={sig}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content[:2] == b"\xff\xd8"


@pytest.mark.asyncio
async def test_thumb_serves_the_cached_file_with_cache_header(client, monkeypatch, tmp_path):
    f = tmp_path / "t.bmp"
    f.write_bytes(b"BM-fake")
    seen = {}

    async def fake(src, size, fmt):
        seen["args"] = (src, size, fmt)
        return f

    monkeypatch.setattr(cover_service, "get_or_make_thumb", fake)
    sig = cover_service.sign_thumb("http://x/y.jpg", 96)
    r = await client.get(f"/api/v1/quick/thumb?src=http://x/y.jpg&size=96&sig={sig}&fmt=bmp")
    assert r.status_code == 200
    assert r.content == b"BM-fake"
    assert r.headers["cache-control"] == "public, max-age=604800"
    assert r.headers["content-type"] == cover_service.media_type_for("bmp")
    assert seen["args"] == ("http://x/y.jpg", 96, "bmp")


# --- favourites ------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["limit=0", "limit=501", "media_type=vinyl"])
async def test_favourites_reject_bad_query(client, q):
    assert (await client.get(f"/api/v1/quick/lea?{q}")).status_code == 422


@pytest.mark.asyncio
async def test_favourites_honour_limit_and_report_count(client, db):
    for n in range(3):
        await _create(db, title=f"P{n}", uri=f"spotify://playlist/{n}", owner="lea")
    data = (await client.get("/api/v1/quick/lea?limit=2")).json()
    assert data["owner"] == "lea"
    assert data["count"] == 2
    assert len(data["items"]) == 2
    assert set(data["items"][0]) == {
        "id", "title", "media_type", "uri", "cover_url", "has_children"
    }


@pytest.mark.asyncio
async def test_audiobook_is_flagged_with_children(client, db):
    await _create(db, title="Livre", uri="spotify://audiobook/1", owner="lea",
                  media_type=MediaType.audiobook)
    items = (await client.get("/api/v1/quick/lea")).json()["items"]
    assert items[0]["has_children"] is True


# --- children --------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [MediaType.podcast, MediaType.audiobook])
async def test_children_ma_failure_is_a_502_naming_music_assistant(client, db, kind):
    item = await _create(db, title="X", uri=f"spotify://{kind.value}/1", media_type=kind)
    r = await client.get(f"/api/v1/quick/item/{item.id}/children")
    assert r.status_code == 502
    assert r.json() == {"detail": "Music Assistant: MA down"}


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["offset=-1", "limit=0", "limit=201"])
async def test_children_reject_bad_paging(client, db, q):
    item = await _create(db, title="X", uri="spotify://podcast/1", media_type=MediaType.podcast)
    assert (await client.get(f"/api/v1/quick/item/{item.id}/children?{q}")).status_code == 422


@pytest.mark.asyncio
async def test_children_of_a_media_without_episodes_is_a_400(client, db):
    """Fails if the 400 guard on non podcast / audiobook media is removed or its code changed."""
    item = await _create(db, title="Liste", uri="spotify://playlist/1", media_type=MediaType.playlist)
    r = await client.get(f"/api/v1/quick/item/{item.id}/children")
    assert r.status_code == 400
    assert r.json() == {"detail": "Ce média n'a pas d'épisodes/chapitres"}


@pytest.mark.asyncio
async def test_children_of_an_unknown_media_is_404(client):
    r = await client.get("/api/v1/quick/item/999999/children")
    assert r.status_code == 404
    assert r.json() == {"detail": "Média introuvable"}
