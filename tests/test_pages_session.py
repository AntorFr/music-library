"""Main HTML pages once auth is enforced: no session, parent session, child session.

Pins the redirect-or-render decision of v0.26.0 per page. Sessions are forged the way
``SessionMiddleware`` writes them; Music Assistant is a stub that is down (AD-filet-1).
"""

from __future__ import annotations

import base64
import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
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
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'t.db'}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        await seed_default_tags(session)
        await session.commit()
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def oidc_on(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.test")
    monkeypatch.setattr(settings, "oidc_client_id", "music-library")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "https://ml.test/auth/callback")

    async def down():
        raise ConnectionError("stub: Music Assistant is down")

    monkeypatch.setattr("app.services.music_assistant.get_ma_client", down)


@pytest.fixture
async def client(db: AsyncSession):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _cookie(user: dict) -> str:
    from itsdangerous import TimestampSigner

    secret = next(
        m.kwargs["secret_key"] for m in app.user_middleware if m.cls is SessionMiddleware
    )
    payload = base64.b64encode(json.dumps({"user": user}).encode())
    return TimestampSigner(str(secret)).sign(payload).decode()


def _parent(client):
    client.cookies.set("session", _cookie({"username": "papa", "display_name": "Papa", "role": "parent"}))


def _child(client, username="lea"):
    client.cookies.set("session", _cookie(
        {"username": username, "display_name": username.capitalize(), "role": "child", "groups": []}
    ))


async def _media(db, *, title, owner, uri):
    item, _ = await media_service.create_media(
        db,
        MediaCreate(
            title=title, media_type=MediaType.playlist, source_uri=uri, provider="spotify",
            cover_url=None, duration_min=None, description=None, metadata_extra=None,
            tag_ids=[], tags_inline=[{"category": "owner", "value": owner}],
        ),
    )
    await db.commit()
    return item


PAGES = ["/", "/quick", "/media", "/media/x", "/media/x/edit", "/browse", "/settings",
         "/settings?tab=system", "/tags", "/rfid"]


# --- Without a session -------------------------------------------------------

@pytest.mark.parametrize("path", PAGES)
async def test_anonymous_page_requests_redirect_to_login(client, path):
    r = await client.get(path)
    assert r.status_code == 302
    assert r.headers["location"] == "/auth/login"


async def test_anonymous_fragment_routes_redirect_to_login(client):
    for path in ("/browse/search?maSearch=beatles", "/browse/library/playlists"):
        r = await client.get(path)
        assert (r.status_code, r.headers["location"]) == (302, "/auth/login")


async def test_anonymous_api_requests_get_401_json_not_a_redirect(client):
    r = await client.get("/api/v1/media")
    assert r.status_code == 401
    assert r.json() == {"detail": "Not authenticated"}


async def test_the_manifest_is_open_without_a_session(client):
    r = await client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.json()["name"] == "Music Library"


async def test_a_tampered_session_cookie_counts_as_anonymous(client):
    client.cookies.set("session", "garbage.value.here")
    r = await client.get("/")
    assert (r.status_code, r.headers["location"]) == (302, "/auth/login")


# --- Parent ------------------------------------------------------------------

@pytest.mark.parametrize(
    ("path", "marker"),
    [("/", "Écouter"), ("/media", "Catalogue"), ("/browse", "Ajouter"),
     ("/settings", "Réglages"), ("/settings?tab=rfid", "Réglages"),
     ("/settings?tab=system", "Réglages")],
)
async def test_parent_sees_every_main_page(client, path, marker):
    _parent(client)
    r = await client.get(path)
    assert r.status_code == 200
    assert marker in r.text


async def test_parent_opens_anyones_media(client, db):
    item = await _media(db, title="Rock de Papa", owner="Papa", uri="spotify://playlist/rock")
    _parent(client)
    assert (await client.get(f"/media/{item.id}")).status_code == 200
    assert (await client.get(f"/media/{item.id}/edit")).status_code == 200


# --- Child -------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/settings", "/settings?tab=rfid", "/settings?tab=system"])
async def test_child_is_refused_the_settings_page(client, path):
    _child(client)
    r = await client.get(path)
    assert r.status_code == 403
    assert r.json() == {"detail": "Réservé aux parents"}


async def test_child_posting_an_rfid_card_is_refused(client):
    _child(client)
    r = await client.post("/rfid", data={"uid": "AA", "name": "Carte"})
    assert r.status_code == 403


@pytest.mark.parametrize(
    ("path", "marker"), [("/", "Écouter"), ("/media", "Catalogue"), ("/browse", "Ajouter")]
)
async def test_child_still_gets_the_other_main_pages(client, path, marker):
    _child(client)
    r = await client.get(path)
    assert r.status_code == 200
    assert marker in r.text


async def test_child_opens_their_own_media(client, db):
    item = await _media(db, title="Histoires du soir", owner="Lea", uri="spotify://playlist/h")
    _child(client)
    r = await client.get(f"/media/{item.id}")
    assert r.status_code == 200
    assert "Histoires du soir" in r.text
    assert (await client.get(f"/media/{item.id}/edit")).status_code == 200


async def test_child_gets_404_not_403_on_someone_elses_media(client, db):
    item = await _media(db, title="Rock de Papa", owner="Papa", uri="spotify://playlist/rock")
    _child(client)
    for path in (f"/media/{item.id}", f"/media/{item.id}/edit"):
        r = await client.get(path)
        assert r.status_code == 404
        assert r.json() == {"detail": "Média introuvable"}


async def test_child_catalogue_lists_only_their_media(client, db):
    await _media(db, title="Histoires du soir", owner="Lea", uri="spotify://playlist/h")
    await _media(db, title="Zebulon de Papa", owner="Papa", uri="spotify://playlist/z")
    _child(client)
    r = await client.get("/media")
    assert "Histoires du soir" in r.text
    assert "Zebulon de Papa" not in r.text


async def test_child_launcher_is_pinned_to_their_own_profile(client, db):
    await _media(db, title="Histoires du soir", owner="Lea", uri="spotify://playlist/h")
    await _media(db, title="Zebulon de Papa", owner="Papa", uri="spotify://playlist/z")
    _child(client)
    r = await client.get("/?owner=Papa")
    assert r.status_code == 200
    assert "Histoires du soir" in r.text
    assert "Zebulon de Papa" not in r.text
