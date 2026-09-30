"""Pinning a media to one Spotify account from its detail page."""

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

HOME = "spotify--Home1234"
DEAD = "spotify--Dead5678"
SPOTIFY_ID = "7dyYwRgXnghudj7gWYGXdB"


class FakeLibraryItem:
    def __init__(self, mappings):
        self.provider_mappings = mappings


class FakeMA:
    """Two accounts: one loaded, one whose login failed and that MA disabled."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.counts: dict[str, int] = {HOME: 12, DEAD: 0}
        self.library_item = FakeLibraryItem([
            {"provider_domain": "spotify", "provider_instance": DEAD, "item_id": SPOTIFY_ID},
            {"provider_domain": "spotify", "provider_instance": HOME, "item_id": SPOTIFY_ID},
        ])

    async def get_provider_configs(self):
        return [
            {"domain": "spotify", "instance_id": DEAD, "name": "Spotify Zoé",
             "enabled": False, "status": "disabled",
             "last_error": {"error_code": 6, "message": "Login failed"}},
            {"domain": "spotify", "instance_id": HOME, "name": None,
             "default_name": "Spotify [Maison]", "enabled": True, "status": "loaded",
             "last_error": None},
            {"domain": "audible", "instance_id": "audible--x", "status": "loaded"},
        ]

    async def get_item(self, media_type, item_id, provider):
        self.calls.append(("get_item", media_type, item_id, provider))
        return self.library_item

    async def get_podcast_episodes(self, item_id, provider):
        self.calls.append(("episodes", item_id, provider))
        return [object()] * self.counts.get(provider, 0)

    async def get_playlist_tracks(self, item_id, provider):
        self.calls.append(("playlist_tracks", item_id, provider))
        return [object()] * self.counts.get(provider, 0)

    async def get_album_tracks(self, item_id, provider):
        self.calls.append(("album_tracks", item_id, provider))
        return [object()] * self.counts.get(provider, 0)

    async def get_players(self):
        return []


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

    async def _get():
        return ma

    monkeypatch.setattr("app.services.music_assistant.get_ma_client", _get)
    return ma


@pytest.fixture
async def client(db: AsyncSession, fake_ma: FakeMA):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _create(db, *, uri, media_type=MediaType.podcast, provider="spotify"):
    item, _ = await media_service.create_media(
        db,
        MediaCreate(
            title="Laylo", media_type=media_type, source_uri=uri, provider=provider,
            cover_url=None, duration_min=None, description=None,
            metadata_extra={"ma_item_id": uri.rsplit("/", 1)[1]},
            tag_ids=[], tags_inline=[],
        ),
    )
    await db.commit()
    return item


async def _reload(db, item_id):
    db.expire_all()
    return await media_service.get_media(db, item_id)


# --- Listing ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_picker_lists_spotify_accounts_dead_one_disabled(client, db):
    item = await _create(db, uri="library://podcast/88")

    r = await client.get(f"/media/{item.id}/spotify-account")
    assert r.status_code == 200
    html = r.text
    assert "Automatique (bibliothèque Music Assistant)" in html
    assert "Spotify [Maison]" in html          # default_name when MA has no custom name
    assert "audible" not in html
    # The failed account is shown with its reason, and cannot be picked.
    dead = html[html.index(f'value="{DEAD}"'):].split("</option>")[0]
    assert "disabled" in dead
    assert "Login failed" in dead


@pytest.mark.asyncio
async def test_picker_preselects_the_pinned_account(client, db):
    item = await _create(db, uri=f"{HOME}://podcast/{SPOTIFY_ID}")

    html = (await client.get(f"/media/{item.id}/spotify-account")).text
    home = html[html.index(f'value="{HOME}"'):].split(">")[0]
    assert "selected" in home
    assert "Automatique" not in html


@pytest.mark.asyncio
async def test_detail_page_offers_picker_only_for_spotify_lists(client, db):
    podcast = await _create(db, uri="library://podcast/88")
    book = await _create(db, uri="library://audiobook/26", media_type=MediaType.audiobook,
                         provider="audible")

    assert f"/media/{podcast.id}/spotify-account" in (await client.get(f"/media/{podcast.id}")).text
    assert "spotify-account" not in (await client.get(f"/media/{book.id}")).text


# --- Switching ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_switch_from_library_pins_the_account(client, db, fake_ma):
    item = await _create(db, uri="library://podcast/88")

    r = await client.post(f"/media/{item.id}/spotify-account", data={"account": HOME})
    assert r.status_code == 200
    assert r.headers.get("HX-Refresh") == "true"
    # The Spotify id comes from the library item, and is probed through the target.
    assert ("get_item", "podcast", "88", "library") in fake_ma.calls
    assert ("episodes", SPOTIFY_ID, HOME) in fake_ma.calls

    saved = await _reload(db, item.id)
    assert saved.source_uri == f"{HOME}://podcast/{SPOTIFY_ID}"
    assert saved.metadata_extra["ma_item_id"] == SPOTIFY_ID
    assert saved.provider == "spotify"


@pytest.mark.asyncio
async def test_switch_between_accounts_keeps_the_spotify_id(client, db, fake_ma):
    other = "spotify--Other999"
    fake_ma.counts[other] = 3
    configs = await fake_ma.get_provider_configs()
    configs.append({"domain": "spotify", "instance_id": other, "name": "Spotify Léo",
                    "enabled": True, "status": "loaded"})

    async def _configs():
        return configs

    fake_ma.get_provider_configs = _configs
    item = await _create(db, uri=f"{HOME}://playlist/{SPOTIFY_ID}", media_type=MediaType.playlist)

    r = await client.post(f"/media/{item.id}/spotify-account", data={"account": other})
    assert r.headers.get("HX-Refresh") == "true"
    assert not any(c[0] == "get_item" for c in fake_ma.calls)
    assert ("playlist_tracks", SPOTIFY_ID, other) in fake_ma.calls
    assert (await _reload(db, item.id)).source_uri == f"{other}://playlist/{SPOTIFY_ID}"


@pytest.mark.asyncio
async def test_switch_refused_when_account_returns_nothing(client, db, fake_ma):
    fake_ma.counts[HOME] = 0
    item = await _create(db, uri="library://podcast/88")

    r = await client.post(f"/media/{item.id}/spotify-account", data={"account": HOME})
    assert "HX-Refresh" not in r.headers
    assert "ne renvoie rien" in r.text
    assert (await _reload(db, item.id)).source_uri == "library://podcast/88"


@pytest.mark.asyncio
async def test_switch_refused_to_a_dead_account(client, db, fake_ma):
    item = await _create(db, uri="library://podcast/88")

    r = await client.post(f"/media/{item.id}/spotify-account", data={"account": DEAD})
    assert "ne fonctionne pas" in r.text
    assert not any(c[0] == "episodes" for c in fake_ma.calls)
    assert (await _reload(db, item.id)).source_uri == "library://podcast/88"


@pytest.mark.asyncio
async def test_switch_refused_for_a_non_spotify_media(client, db):
    item = await _create(db, uri="library://audiobook/26", media_type=MediaType.audiobook,
                         provider="audible")

    r = await client.post(f"/media/{item.id}/spotify-account", data={"account": HOME})
    assert "ne passe pas par un compte Spotify" in r.text
    assert (await _reload(db, item.id)).source_uri == "library://audiobook/26"


# --- Permissions -------------------------------------------------------------

def _login_child(client: AsyncClient) -> None:
    from itsdangerous import TimestampSigner

    secret = next(
        m.kwargs["secret_key"] for m in app.user_middleware if m.cls is SessionMiddleware
    )
    user = {"username": "lea", "display_name": "Lea", "role": "child", "groups": []}
    payload = base64.b64encode(json.dumps({"user": user}).encode())
    client.cookies.set("session", TimestampSigner(str(secret)).sign(payload).decode())


@pytest.mark.asyncio
async def test_children_cannot_switch_account(client, db, monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.test")
    monkeypatch.setattr(settings, "oidc_client_id", "music-library")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "https://ml.test/auth/callback")
    item = await _create(db, uri="library://podcast/88")
    _login_child(client)

    assert (await client.get(f"/media/{item.id}/spotify-account")).status_code == 403
    r = await client.post(f"/media/{item.id}/spotify-account", data={"account": HOME})
    assert r.status_code == 403
    assert (await _reload(db, item.id)).source_uri == "library://podcast/88"
