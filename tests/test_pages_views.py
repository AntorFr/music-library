"""Main HTML pages of ``app/api/views.py`` in open (dev) mode: status and marker text.

Pins what v0.26.0 answers — pages, redirects, 404s and the errors a bad query gives.
Music Assistant is a stub that is down or scripted; no network (AD-filet-1).
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
def ma_down(monkeypatch):
    async def down():
        raise ConnectionError("stub: Music Assistant is down")

    monkeypatch.setattr("app.services.music_assistant.get_ma_client", down)


@pytest.fixture
async def client(db: AsyncSession, ma_down):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _media(db, *, title="Les Contes", owner=None, media_type=MediaType.playlist, uri=None):
    item, _ = await media_service.create_media(
        db,
        MediaCreate(
            title=title, media_type=media_type, source_uri=uri or f"spotify://playlist/{title}",
            provider="spotify", cover_url=None, duration_min=None, description=None,
            metadata_extra=None, tag_ids=[],
            tags_inline=[{"category": "owner", "value": owner}] if owner else [],
        ),
    )
    await db.commit()
    return item


# --- Listen (/) and the legacy launcher URL ---------------------------------

async def test_listen_page_renders_without_music_assistant(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Écouter" in r.text


async def test_listen_page_shows_the_selected_owners_media(client, db):
    await _media(db, title="Histoires du soir", owner="Léa")
    await _media(db, title="Rock de Papa", owner="Papa", uri="spotify://playlist/rock")
    r = await client.get("/?owner=Léa")
    assert r.status_code == 200
    assert "Histoires du soir" in r.text
    assert "Rock de Papa" not in r.text


async def test_listen_page_reads_the_owner_from_the_percent_encoded_cookie(client, db):
    await _media(db, title="Histoires du soir", owner="Léa")
    client.cookies.set("ml_owner", "L%C3%A9a")
    r = await client.get("/")
    assert r.status_code == 200
    assert "Histoires du soir" in r.text


async def test_listen_page_with_an_unknown_owner_is_still_a_200(client, db):
    await _media(db, title="Histoires du soir", owner="Léa")
    r = await client.get("/?owner=Fantome")
    assert r.status_code == 200
    assert "Histoires du soir" not in r.text


async def test_quick_redirects_to_the_root(client):
    r = await client.get("/quick")
    assert r.status_code == 302
    assert r.headers["location"] == "/"


async def test_quick_redirect_keeps_the_owner_quoted(client):
    r = await client.get("/quick?owner=Léa B")
    assert r.status_code == 302
    assert r.headers["location"] == "/?owner=L%C3%A9a%20B"


# --- Catalogue (/media) ------------------------------------------------------

async def test_media_list_renders_the_catalogue(client, db):
    await _media(db, title="Les Contes")
    r = await client.get("/media")
    assert r.status_code == 200
    assert "Catalogue" in r.text
    assert "Les Contes" in r.text


async def test_media_list_search_filters_by_title(client, db):
    await _media(db, title="Les Contes")
    await _media(db, title="Zebulon", uri="spotify://playlist/zeb")
    r = await client.get("/media?search=Contes")
    assert r.status_code == 200
    assert "Les Contes" in r.text
    assert "Zebulon" not in r.text


@pytest.mark.parametrize("query", ["page=0", "page_size=0", "page_size=101", "page=abc"])
async def test_media_list_rejects_bad_paging_with_422(client, query):
    r = await client.get(f"/media?{query}")
    assert r.status_code == 422


async def test_media_list_with_an_unknown_media_type_is_a_500(client):
    """DOUTEUX — ``MediaType(media_type)`` raises ValueError, nothing turns it into a 4xx."""
    r = await client.get("/media?media_type=bogus")
    assert r.status_code == 500


# --- Media detail and edit form ----------------------------------------------

async def test_media_detail_renders_the_item(client, db):
    item = await _media(db, title="Les Contes")
    r = await client.get(f"/media/{item.id}")
    assert r.status_code == 200
    assert "Les Contes" in r.text


async def test_media_detail_unknown_id_is_404(client):
    r = await client.get("/media/nope")
    assert r.status_code == 404
    assert r.json() == {"detail": "Média introuvable"}


async def test_media_edit_form_renders_the_item(client, db):
    item = await _media(db, title="Les Contes")
    r = await client.get(f"/media/{item.id}/edit")
    assert r.status_code == 200
    assert "Les Contes" in r.text
    assert f"/media/{item.id}/edit" in r.text


async def test_media_edit_form_unknown_id_is_404(client):
    r = await client.get("/media/nope/edit")
    assert r.status_code == 404


# --- Settings and its legacy redirects ---------------------------------------

@pytest.mark.parametrize("tab", [None, "tags", "rfid", "system"])
async def test_settings_renders_each_tab(client, tab):
    r = await client.get("/settings" + (f"?tab={tab}" if tab else ""))
    assert r.status_code == 200
    assert "Réglages" in r.text


async def test_settings_unknown_tab_is_422(client):
    r = await client.get("/settings?tab=bogus")
    assert r.status_code == 422


async def test_settings_system_tab_reports_music_assistant_down(client):
    r = await client.get("/settings?tab=system")
    assert r.status_code == 200
    assert "stub: Music Assistant is down" in r.text


@pytest.mark.parametrize(
    ("old", "new"),
    [("/tags", "/settings?tab=tags"), ("/rfid", "/settings?tab=rfid")],
)
async def test_legacy_admin_urls_redirect_with_302(client, old, new):
    r = await client.get(old)
    assert r.status_code == 302
    assert r.headers["location"] == new


# --- Browse ("Ajouter") ----------------------------------------------------

async def test_browse_page_renders(client):
    r = await client.get("/browse")
    assert r.status_code == 200
    assert "Ajouter" in r.text


class _LibraryMA:
    """A reachable Music Assistant with an empty library."""

    def __getattr__(self, name):
        if name.startswith("get_library_"):
            async def empty(limit=50):
                return []
            return empty
        raise AttributeError(name)


async def test_browse_library_unknown_type_is_400_when_ma_answers(client, monkeypatch):
    async def up():
        return _LibraryMA()

    monkeypatch.setattr("app.services.music_assistant.get_ma_client", up)
    r = await client.get("/browse/library/foo")
    assert r.status_code == 400
    assert r.json() == {"detail": "Type inconnu"}


async def test_browse_library_unknown_type_with_ma_down_is_a_200(client):
    """DOUTEUX — the type is only checked once MA answered: with MA down, any type is a 200."""
    r = await client.get("/browse/library/foo")
    assert r.status_code == 200


async def test_browse_library_with_ma_down_renders_an_empty_fragment(client):
    r = await client.get("/browse/library/playlists")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


async def test_browse_search_below_two_characters_asks_for_more(client):
    r = await client.get("/browse/search?maSearch=a")
    assert r.status_code == 200
    assert "Tapez au moins 2 caractères" in r.text


async def test_browse_search_with_ma_down_reports_the_error_inline(client):
    """The failure comes back as a 200 fragment carrying the exception text."""
    r = await client.get("/browse/search?maSearch=beatles")
    assert r.status_code == 200
    assert "Erreur Music Assistant: stub: Music Assistant is down" in r.text


# --- Manifest ----------------------------------------------------------------

async def test_manifest_is_a_pwa_manifest_rooted_at_slash(client):
    r = await client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    body = r.json()
    assert body["name"] == "Music Library"
    assert body["start_url"] == "/"
    assert body["display"] == "standalone"
    assert [i["sizes"] for i in body["icons"]] == ["192x192", "512x512", "any"]
