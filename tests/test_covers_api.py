"""Cover routes: ``GET /covers/{id}.jpg`` and ``POST /api/v1/media/{id}/cover``.

Pins what v0.26.0 does at the HTTP edge — serving, resized variants, formats, the
self-healing download, upload and its errors. The covers directory is a tmp dir and
no network is touched (AD-filet-1).
"""

from __future__ import annotations

from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import media as _media_models  # noqa: F401
from app.models import rfid as _rfid_models  # noqa: F401
from app.models.media import MediaType
from app.schemas.media import MediaCreate
from app.services import cover_service, media_service
from app.services.tag_service import seed_default_tags


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
def covers(tmp_path, monkeypatch):
    d = tmp_path / "covers"
    d.mkdir()
    monkeypatch.setattr(settings, "covers_dir", d)
    return d


@pytest.fixture
async def client(db, covers):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _media(db, *, title="Album", cover_url=None, owner=None):
    item, _ = await media_service.create_media(
        db,
        MediaCreate(
            title=title, media_type=MediaType.playlist, source_uri=f"spotify://playlist/{title}",
            provider="spotify", cover_url=cover_url, duration_min=None, description=None,
            metadata_extra=None, tag_ids=[],
            tags_inline=[{"category": "owner", "value": owner}] if owner else [],
        ),
    )
    await db.commit()
    return item


def _png(size=(300, 200), color=(200, 30, 30)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _put_cover(covers, media_id, size=300):
    Image.new("RGB", (size, size), (10, 20, 30)).save(covers / f"{media_id}.jpg", "JPEG")


@pytest.fixture
def oidc_on(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.test")
    monkeypatch.setattr(settings, "oidc_client_id", "music-library")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "https://ml.test/auth/callback")


# --- Reading ---------------------------------------------------------------

async def test_existing_cover_is_served_as_jpeg_with_a_day_of_cache(client, covers):
    _put_cover(covers, "abc")
    r = await client.get("/covers/abc.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "public, max-age=86400"
    assert r.content == (covers / "abc.jpg").read_bytes()


async def test_size_query_serves_a_resized_cached_variant(client, covers):
    _put_cover(covers, "abc")
    r = await client.get("/covers/abc.jpg?size=64")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    with Image.open(BytesIO(r.content)) as im:
        assert im.size == (64, 64)
    assert (covers / "abc_64.jpg").exists()


async def test_bmp_format_is_served_as_bmp(client, covers):
    _put_cover(covers, "abc")
    r = await client.get("/covers/abc.jpg?fmt=bmp&size=32")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/bmp"
    with Image.open(BytesIO(r.content)) as im:
        assert im.format == "BMP"
        assert im.size == (32, 32)


async def test_bmp_without_size_keeps_the_base_resolution(client, covers):
    _put_cover(covers, "abc", size=120)
    r = await client.get("/covers/abc.jpg?fmt=bmp")
    assert r.headers["content-type"] == "image/bmp"
    with Image.open(BytesIO(r.content)) as im:
        assert im.size == (120, 120)
    assert (covers / "abc_orig.bmp").exists()


@pytest.mark.parametrize(
    "query",
    ["size=15", "size=513", "size=abc", "fmt=png"],
)
async def test_invalid_size_or_format_is_a_422(client, covers, query):
    _put_cover(covers, "abc")
    r = await client.get(f"/covers/abc.jpg?{query}")
    assert r.status_code == 422


@pytest.mark.parametrize("size", [16, 512])
async def test_size_bounds_are_inclusive(client, covers, size):
    _put_cover(covers, "abc")
    r = await client.get(f"/covers/abc.jpg?size={size}")
    assert r.status_code == 200


async def test_covers_are_served_without_a_session(client, covers, oidc_on):
    """``/covers/`` is exempt from auth: embedded clients carry no session."""
    _put_cover(covers, "abc")
    r = await client.get("/covers/abc.jpg")
    assert r.status_code == 200


async def test_missing_cover_falls_back_to_the_default_image(client, covers, tmp_path, monkeypatch):
    default = tmp_path / "default.jpg"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(default, "JPEG")
    monkeypatch.setattr(settings, "default_cover", str(default))
    r = await client.get("/covers/unknown.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == default.read_bytes()
    assert "cache-control" not in r.headers


async def test_missing_cover_with_a_relative_default_path_is_a_500(
    client, covers, tmp_path, monkeypatch
):
    """DOUTEUX — ``default_cover`` is ``static/img/default_cover.jpg``, relative to the
    working directory, while the file lives in ``app/static``: from the repository root
    (or ``/app`` in the image) the fallback file is not found and the route answers 500."""
    monkeypatch.chdir(tmp_path)
    r = await client.get("/covers/unknown.jpg")
    assert r.status_code == 500


async def test_missing_cover_is_downloaded_again_from_its_cover_url(
    client, db, covers, monkeypatch
):
    item = await _media(db, cover_url="https://img.test/c.png")
    calls = []

    async def fake_ensure(media_id, url):
        calls.append((media_id, url))
        _put_cover(covers, media_id)
        return f"covers/{media_id}.jpg"

    monkeypatch.setattr(cover_service, "ensure_local_cover", fake_ensure)
    r = await client.get(f"/covers/{item.id}.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert calls == [(item.id, "https://img.test/c.png")]
    await db.refresh(item)
    assert item.cover_local == f"covers/{item.id}.jpg"


async def test_failed_redownload_falls_back_to_the_default(
    client, db, covers, tmp_path, monkeypatch
):
    item = await _media(db, cover_url="https://img.test/c.png")

    async def fail(media_id, url):
        return None

    default = tmp_path / "default.jpg"
    Image.new("RGB", (8, 8)).save(default, "JPEG")
    monkeypatch.setattr(cover_service, "ensure_local_cover", fail)
    monkeypatch.setattr(settings, "default_cover", str(default))
    r = await client.get(f"/covers/{item.id}.jpg")
    assert r.status_code == 200
    assert r.content == default.read_bytes()


async def test_media_without_cover_url_is_not_redownloaded(client, db, covers, tmp_path, monkeypatch):
    item = await _media(db, cover_url=None)

    async def boom(media_id, url):  # pragma: no cover - must not be reached
        raise AssertionError("no download expected")

    default = tmp_path / "default.jpg"
    Image.new("RGB", (8, 8)).save(default, "JPEG")
    monkeypatch.setattr(cover_service, "ensure_local_cover", boom)
    monkeypatch.setattr(settings, "default_cover", str(default))
    r = await client.get(f"/covers/{item.id}.jpg")
    assert r.status_code == 200


# --- Uploading -------------------------------------------------------------

async def test_upload_stores_a_square_jpeg_and_answers_its_url(client, db, covers):
    item = await _media(db)
    r = await client.post(
        f"/api/v1/media/{item.id}/cover",
        files={"file": ("c.png", _png(), "image/png")},
    )
    assert r.status_code == 200
    assert r.json() == {
        "cover_local": f"covers/{item.id}.jpg",
        "url": f"/covers/{item.id}.jpg",
    }
    with Image.open(covers / f"{item.id}.jpg") as im:
        assert im.format == "JPEG"
        assert im.size == (settings.cover_max_size, settings.cover_max_size)
    assert item.cover_local == f"covers/{item.id}.jpg"


async def test_uploaded_cover_is_then_served(client, db, covers):
    item = await _media(db)
    await client.post(
        f"/api/v1/media/{item.id}/cover", files={"file": ("c.png", _png(), "image/png")}
    )
    r = await client.get(f"/covers/{item.id}.jpg")
    assert r.status_code == 200
    assert r.content == (covers / f"{item.id}.jpg").read_bytes()


async def test_upload_drops_stale_resized_variants(client, db, covers):
    item = await _media(db)
    _put_cover(covers, item.id)
    await client.get(f"/covers/{item.id}.jpg?size=64")
    assert (covers / f"{item.id}_64.jpg").exists()
    await client.post(
        f"/api/v1/media/{item.id}/cover", files={"file": ("c.png", _png(), "image/png")}
    )
    assert not (covers / f"{item.id}_64.jpg").exists()


async def test_upload_of_a_non_image_is_a_500_with_a_french_detail(client, db, covers):
    item = await _media(db)
    r = await client.post(
        f"/api/v1/media/{item.id}/cover",
        files={"file": ("c.png", b"not an image", "image/png")},
    )
    assert r.status_code == 500
    assert r.json() == {"detail": "Erreur lors du traitement de l'image"}
    assert not (covers / f"{item.id}.jpg").exists()


async def test_upload_for_an_unknown_media_is_a_404(client, covers):
    r = await client.post(
        "/api/v1/media/nope/cover", files={"file": ("c.png", _png(), "image/png")}
    )
    assert r.status_code == 404
    assert r.json() == {"detail": "Média introuvable"}


async def test_upload_without_a_file_is_a_422(client, db):
    item = await _media(db)
    r = await client.post(f"/api/v1/media/{item.id}/cover")
    assert r.status_code == 422


async def test_upload_requires_authentication(client, db, oidc_on):
    item = await _media(db)
    r = await client.post(
        f"/api/v1/media/{item.id}/cover", files={"file": ("c.png", _png(), "image/png")}
    )
    assert r.status_code == 401
