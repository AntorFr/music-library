"""The ESP surface (``app.esp_app``) seen from the device: what it serves, what it
refuses, and that it asks for no identity.

test_esp_api.py pins the route table and the two blocked writes; this file pins the
answers at the boundary — status, payload, the 404 of the guard, absence of auth.
Music Assistant is a stub, the covers directory a tmp dir (AD-filet-1).
"""

from __future__ import annotations

from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.esp_app import esp_app
from app.main import app
from app.models import media as _media_models  # noqa: F401
from app.models import rfid as _rfid_models  # noqa: F401
from app.models.media import MediaType
from app.schemas.media import MediaCreate
from app.services import media_service
from app.services.music_assistant import get_ma_client
from app.services.tag_service import seed_default_tags


class StubMA:
    """Just what the transport routes read; records the calls (no network)."""

    connected = True

    def __init__(self):
        self.calls: list[tuple] = []

    async def get_players(self):
        return []

    async def get_podcast_episodes(self, item_id, provider):
        return []

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
def covers(tmp_path, monkeypatch):
    d = tmp_path / "covers"
    d.mkdir()
    monkeypatch.setattr(settings, "covers_dir", d)
    return d


@pytest.fixture
async def esp(db, covers):
    async def override_get_db():
        yield db

    esp_app.dependency_overrides[get_db] = override_get_db
    esp_app.dependency_overrides[get_ma_client] = lambda: StubMA()
    transport = ASGITransport(app=esp_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://esp") as c:
        yield c
    esp_app.dependency_overrides.clear()


@pytest.fixture
def oidc_on(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.test")
    monkeypatch.setattr(settings, "oidc_client_id", "music-library")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "https://ml.test/auth/callback")


async def _media(db, *, title="Comptines", owner="lea", uri="spotify://playlist/c",
                 media_type=MediaType.playlist):
    item, _ = await media_service.create_media(
        db,
        MediaCreate(
            title=title, media_type=media_type, source_uri=uri, provider="spotify",
            cover_url=None, duration_min=None, description=None, metadata_extra=None,
            tag_ids=[], tags_inline=[{"category": "owner", "value": owner}],
        ),
    )
    await db.commit()
    return item


def _jpeg() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (64, 64), (10, 120, 200)).save(buf, "JPEG")
    return buf.getvalue()


# --- Served ------------------------------------------------------------------

async def test_health_answers_the_probe_keys(esp):
    r = await esp.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok", "app": settings.app_name, "version": settings.app_version,
    }


async def test_the_openapi_title_names_the_esp_surface():
    assert esp_app.title == f"{settings.app_name} — ESP API"
    assert esp_app.version == settings.app_version


async def test_quick_grid_is_served_with_urls_resolved_on_the_esp_host(esp, db):
    item = await _media(db)
    await _media(db, title="Rock Papa", owner="papa", uri="spotify://playlist/r")

    r = await esp.get("/api/v1/quick/lea")
    assert r.status_code == 200
    assert r.json() == {
        "owner": "lea",
        "count": 1,
        "items": [{
            "id": item.id, "title": "Comptines", "media_type": "playlist",
            "uri": "spotify://playlist/c",
            "cover_url": f"http://esp/covers/{item.id}.jpg",
            "has_children": False,
        }],
    }


async def test_quick_grid_of_an_unknown_owner_is_empty_not_an_error(esp):
    r = await esp.get("/api/v1/quick/nobody")
    assert r.status_code == 200
    assert r.json()["count"] == 0
    assert r.json()["items"] == []


async def test_quick_children_of_a_missing_media_is_404(esp):
    r = await esp.get("/api/v1/quick/item/nope/children")
    assert r.status_code == 404


async def test_cover_is_served_from_the_covers_directory(esp, db, covers):
    item = await _media(db)
    (covers / f"{item.id}.jpg").write_bytes(_jpeg())

    r = await esp.get(f"/covers/{item.id}.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "public, max-age=86400"
    assert r.content == _jpeg()


async def test_cover_resize_is_validated_at_the_boundary(esp):
    assert (await esp.get("/covers/x.jpg", params={"size": 8})).status_code == 422
    assert (await esp.get("/covers/x.jpg", params={"fmt": "png"})).status_code == 422


async def test_ma_players_is_reachable_on_the_esp_port(esp):
    r = await esp.get("/api/v1/ma/players")
    assert r.status_code == 200
    assert r.json() == []


# --- Refused -----------------------------------------------------------------

@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/ma/import"),
        ("POST", "/api/v1/media/abc/cover"),
        ("POST", "/api/v1/media/abc/def/cover"),
    ],
)
async def test_blocked_writes_answer_the_guards_404_body(esp, method, path):
    r = await esp.request(method, path)
    assert r.status_code == 404
    assert r.json() == {"detail": "Not found"}


async def test_only_post_is_guarded_a_get_on_the_import_path_is_a_plain_405(esp):
    """The guard's 404 is for POST only; other verbs reach the router's own answer."""
    r = await esp.get("/api/v1/ma/import")
    assert r.status_code == 405


async def test_a_media_path_ending_in_cover_is_guarded_whatever_its_middle(esp):
    """The guard is a prefix + suffix test, not a route match (doubtful: it also
    swallows ``/api/v1/media/cover``, which is not a route)."""
    r = await esp.post("/api/v1/media/cover")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not found"}  # the guard's body, not FastAPI's "Not Found"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/rfid"),
        ("PUT", "/api/v1/rfid/04-70-D7-DA"),
        ("GET", "/api/v1/media"),
        ("GET", "/api/v1/tags"),
        ("GET", "/"),
        ("GET", "/settings"),
        ("GET", "/auth/login"),
    ],
)
async def test_management_surfaces_are_not_routed_here(esp, method, path):
    r = await esp.request(method, path)
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


async def test_the_same_rfid_route_exists_on_the_main_app(db):
    """The contrast that gives the previous test its meaning."""
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/api/v1/rfid")).status_code == 200
    finally:
        app.dependency_overrides.clear()


# --- No identity -------------------------------------------------------------

async def test_no_identity_is_asked_even_when_oidc_is_on(esp, db, oidc_on):
    await _media(db)
    for path in ("/api/v1/health", "/api/v1/quick/lea"):
        r = await esp.get(path)
        assert r.status_code == 200, path


async def test_the_main_app_does_refuse_the_same_call_when_oidc_is_on(db, oidc_on):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/quick/lea")
    assert r.status_code == 401
    assert r.json() == {"detail": "Not authenticated"}


async def test_the_esp_app_has_no_session_cookie(esp):
    r = await esp.get("/api/v1/health")
    assert "set-cookie" not in r.headers
