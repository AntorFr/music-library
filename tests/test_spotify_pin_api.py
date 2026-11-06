"""Pinning a list to a Spotify account: the route, its HTML fragment, and its effects
as the REST API sees them.

test_spotify_account.py pins the happy path and the refusals of the service. Here:
the route's own edges (404, validation, Music Assistant failing), what the fragment
contains for the HTMX swap, and that after a pin the REST contract
(``/api/v1/media``, ``/api/v1/quick``) shows the instance URI. Music Assistant is a
stub (AD-filet-1).
"""

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

HOME = "spotify--Home1234"
DEAD = "spotify--Dead5678"
SPOTIFY_ID = "7dyYwRgXnghudj7gWYGXdB"


class StubMA:
    """One live account, one dead; every list returns ``counts[account]`` items."""

    def __init__(self):
        self.counts = {HOME: 5, DEAD: 0}
        self.fail_configs: Exception | None = None
        self.fail_listing: Exception | None = None

    async def get_provider_configs(self):
        if self.fail_configs:
            raise self.fail_configs
        return [
            {"domain": "spotify", "instance_id": HOME, "name": "Spotify Maison",
             "enabled": True, "status": "loaded", "last_error": None},
            {"domain": "spotify", "instance_id": DEAD, "name": "Spotify Zoé",
             "enabled": False, "status": "disabled", "last_error": None},
        ]

    async def get_item(self, media_type, item_id, provider):
        class _Item:
            provider_mappings = [
                {"provider_domain": "spotify", "provider_instance": HOME, "item_id": SPOTIFY_ID}
            ]
        return _Item()

    async def _items(self, provider):
        if self.fail_listing:
            raise self.fail_listing
        return [object()] * self.counts.get(provider, 0)

    async def get_podcast_episodes(self, item_id, provider):
        return await self._items(provider)

    async def get_playlist_tracks(self, item_id, provider):
        return await self._items(provider)

    async def get_album_tracks(self, item_id, provider):
        return await self._items(provider)

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
def ma(monkeypatch):
    stub = StubMA()

    async def _get():
        return stub

    monkeypatch.setattr("app.services.music_assistant.get_ma_client", _get)
    return stub


@pytest.fixture
async def client(db, ma):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _uri(db, media_id):
    db.expire_all()
    return (await media_service.get_media(db, media_id)).source_uri


async def _create(db, *, uri="library://podcast/88", media_type=MediaType.podcast,
                  provider="spotify", owner="lea", title="Laylo"):
    item, _ = await media_service.create_media(
        db,
        MediaCreate(
            title=title, media_type=media_type, source_uri=uri, provider=provider,
            cover_url=None, duration_min=None, description=None, metadata_extra=None,
            tag_ids=[], tags_inline=[{"category": "owner", "value": owner}],
        ),
    )
    await db.commit()
    return item


# --- The route's edges -------------------------------------------------------

async def test_get_of_an_unknown_media_is_404(client):
    r = await client.get("/media/nope/spotify-account")
    assert r.status_code == 404
    assert r.json() == {"detail": "Média introuvable"}


async def test_post_to_an_unknown_media_is_404(client):
    r = await client.post("/media/nope/spotify-account", data={"account": HOME})
    assert r.status_code == 404
    assert r.json() == {"detail": "Média introuvable"}


async def test_post_without_an_account_field_is_422_and_changes_nothing(client, db):
    item = await _create(db)
    item_id = item.id
    r = await client.post(f"/media/{item.id}/spotify-account", data={})
    assert r.status_code == 422
    assert await _uri(db, item_id) == "library://podcast/88"


async def test_an_account_unknown_to_music_assistant_is_refused_in_the_fragment(client, db):
    item = await _create(db)
    r = await client.post(f"/media/{item.id}/spotify-account", data={"account": "spotify--Ghost"})
    assert r.status_code == 200
    assert "HX-Refresh" not in r.headers
    assert "Compte Spotify inconnu de Music Assistant" in r.text
    assert 'id="spotify-account"' in r.text


async def test_get_when_music_assistant_is_down_still_answers_200_with_the_error(client, db, ma):
    ma.fail_configs = RuntimeError("MA injoignable")
    item = await _create(db)

    r = await client.get(f"/media/{item.id}/spotify-account")
    assert r.status_code == 200
    assert "MA injoignable" in r.text
    assert "<select" not in r.text  # no accounts, so no picker


async def test_post_when_music_assistant_fails_mid_probe_is_reported_not_raised(client, db, ma):
    ma.fail_listing = RuntimeError("timeout")
    item = await _create(db)
    item_id = item.id

    r = await client.post(f"/media/{item.id}/spotify-account", data={"account": HOME})
    assert r.status_code == 200
    assert "HX-Refresh" not in r.headers
    assert "Music Assistant : timeout" in r.text
    assert await _uri(db, item_id) == "library://podcast/88"


async def test_pinning_onto_an_account_that_already_has_the_media_is_refused(client, db):
    await _create(db, uri=f"{HOME}://podcast/{SPOTIFY_ID}", title="Déjà là")
    item = await _create(db, uri="library://podcast/88", title="Doublon")
    item_id = item.id

    r = await client.post(f"/media/{item.id}/spotify-account", data={"account": HOME})
    assert "HX-Refresh" not in r.headers
    assert "Ce média existe déjà dans le catalogue sur ce compte" in r.text
    assert await _uri(db, item_id) == "library://podcast/88"


# --- The fragment ------------------------------------------------------------

async def test_fragment_is_a_card_posting_back_to_the_same_url(client, db):
    item = await _create(db)
    html = (await client.get(f"/media/{item.id}/spotify-account")).text
    assert 'id="spotify-account"' in html
    assert f'hx-post="/media/{item.id}/spotify-account"' in html
    assert 'name="account"' in html
    assert "Music Assistant choisit le compte lui-même" in html
    assert "Spotify Maison" in html


async def test_fragment_of_a_pinned_media_says_the_account_is_used(client, db):
    item = await _create(db, uri=f"{HOME}://podcast/{SPOTIFY_ID}")
    html = (await client.get(f"/media/{item.id}/spotify-account")).text
    assert "Les épisodes et la lecture passent par ce compte." in html
    assert "Music Assistant choisit" not in html


async def test_fragment_lists_the_usable_account_before_the_disabled_one(client, db):
    item = await _create(db)
    html = (await client.get(f"/media/{item.id}/spotify-account")).text
    assert html.index("Spotify Maison") < html.index("Spotify Zoé")
    assert "désactivé" in html  # the reason shown next to the dead account


async def test_fragment_for_a_non_spotify_media_still_renders(client, db):
    """The GET does not check ``is_switchable``: the card is served for any media
    (the detail page just does not offer it). Doubtful, pinned as is."""
    item = await _create(db, uri="library://audiobook/26", media_type=MediaType.audiobook,
                         provider="audible")
    r = await client.get(f"/media/{item.id}/spotify-account")
    assert r.status_code == 200
    assert 'id="spotify-account"' in r.text


# --- Effects through the REST API -------------------------------------------

async def test_after_a_pin_the_rest_api_shows_the_instance_uri(client, db):
    item = await _create(db)
    before = (await client.get(f"/api/v1/media/{item.id}")).json()
    assert before["source_uri"] == "library://podcast/88"

    r = await client.post(f"/media/{item.id}/spotify-account", data={"account": HOME})
    assert r.headers.get("HX-Refresh") == "true"
    assert r.text == ""

    after = (await client.get(f"/api/v1/media/{item.id}")).json()
    assert after["source_uri"] == f"{HOME}://podcast/{SPOTIFY_ID}"
    assert after["title"] == before["title"]
    assert after["provider"] == "spotify"


async def test_after_a_pin_the_quick_grid_hands_the_instance_uri_to_the_device(client, db):
    item = await _create(db)
    await client.post(f"/media/{item.id}/spotify-account", data={"account": HOME})

    r = await client.get("/api/v1/quick/lea")
    assert r.status_code == 200
    entries = r.json()["items"]
    assert [e["id"] for e in entries] == [item.id]
    assert entries[0]["uri"] == f"{HOME}://podcast/{SPOTIFY_ID}"


async def test_a_refused_pin_leaves_the_rest_api_untouched(client, db):
    item = await _create(db)
    await client.post(f"/media/{item.id}/spotify-account", data={"account": DEAD})

    r = await client.get(f"/api/v1/media/{item.id}")
    assert r.json()["source_uri"] == "library://podcast/88"


async def test_a_pin_keeps_the_other_media_as_they_were(client, db):
    item = await _create(db, title="A")
    other = await _create(db, uri="library://podcast/99", title="B")
    await client.post(f"/media/{item.id}/spotify-account", data={"account": HOME})

    r = await client.get(f"/api/v1/media/{other.id}")
    assert r.json()["source_uri"] == "library://podcast/99"


async def test_pin_is_idempotent_through_the_same_account(client, db):
    item = await _create(db)
    for _ in range(2):
        r = await client.post(f"/media/{item.id}/spotify-account", data={"account": HOME})
        assert r.headers.get("HX-Refresh") == "true"
    got = (await client.get(f"/api/v1/media/{item.id}")).json()
    assert got["source_uri"] == f"{HOME}://podcast/{SPOTIFY_ID}"
