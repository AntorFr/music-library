"""The v2 navigation contract: four entries, and what happened to the other four.

These pin the routing decisions rather than the markup — a redesign should be free
to move pixels, not to silently resurrect a page or break a bookmarked URL.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import media as _media_models  # noqa: F401
from app.models import rfid as _rfid_models  # noqa: F401
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
async def client(db: AsyncSession):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# --- The four entries ------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "marker"),
    [
        ("/", "Écouter"),
        ("/media", "Catalogue"),
        ("/browse", "Ajouter"),
        ("/settings", "Réglages"),
    ],
)
async def test_the_four_nav_entries_render(client, path, marker):
    r = await client.get(path)
    assert r.status_code == 200
    assert marker in r.text


@pytest.mark.asyncio
async def test_nav_offers_exactly_four_entries(client):
    """v1 grew one entry per feature and reached eight. Four is the contract now."""
    r = await client.get("/")
    sidebar = r.text.split('<nav class="sidebar-nav">')[1].split("</nav>")[0]
    assert sidebar.count("<a href=") == 4
    for href in ('href="/"', 'href="/media"', 'href="/browse"', 'href="/settings"'):
        assert href in sidebar


# --- What moved ------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("/quick", "/"),
        ("/tags", "/settings?tab=tags"),
        ("/rfid", "/settings?tab=rfid"),
    ],
)
async def test_old_urls_still_land_somewhere(client, old, new):
    """Home-screen shortcuts and bookmarks outlive a redesign."""
    r = await client.get(old, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == new


@pytest.mark.asyncio
async def test_quick_keeps_its_owner_when_redirected(client):
    r = await client.get("/quick?owner=papa", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/?owner=papa"


# --- What is gone ----------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/players", "/media/new"])
async def test_removed_pages_are_gone(client, path):
    """The speaker list had no controls; the add form is a modal on /browse now."""
    r = await client.get(path, follow_redirects=False)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_manual_add_still_accepts_a_post(client):
    """The page is gone, the endpoint is not — the modal posts to it."""
    r = await client.post(
        "/media/new",
        data={
            "title": "La Grimm Académie",
            "media_type": "podcast",
            "source_uri": "https://feeds.example.test/grimm",
            "provider": "manuel",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/media/")


# --- Settings tabs ---------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tab", "marker"),
    [("tags", "Nouveau tag"), ("rfid", "Créer / renommer"), ("system", "Music Assistant")],
)
async def test_settings_tabs_render(client, tab, marker):
    r = await client.get(f"/settings?tab={tab}")
    assert r.status_code == 200
    assert marker in r.text


@pytest.mark.asyncio
async def test_settings_rejects_an_unknown_tab(client):
    r = await client.get("/settings?tab=nope")
    assert r.status_code == 422


# --- Adding is open to children -------------------------------------------

@pytest.mark.asyncio
async def test_add_page_carries_the_manual_modal(client):
    """Children add too, so the entry stays in the shared nav — modal included."""
    r = await client.get("/browse")
    assert r.status_code == 200
    assert 'id="manualScrim"' in r.text
    assert "Saisie manuelle" in r.text


# --- Catalogue filters are links, not form controls ------------------------

@pytest.mark.asyncio
async def test_filter_chips_compose_and_uncompose(client):
    """Each chip carries the URL with that one filter flipped — combining is the
    whole point, and removing one must keep the others."""
    r = await client.get("/media?media_type=podcast")
    assert r.status_code == 200
    # Picking a tag on top of the type keeps the type.
    assert "/media?media_type=podcast&amp;tag_age_group=kids" in r.text

    r2 = await client.get("/media?media_type=podcast&tag_age_group=kids")
    active = r2.text.split('chip-bar-active')[1].split("</div>")[0]
    # Dropping the type keeps the tag, and vice versa.
    assert 'href="/media?tag_age_group=kids"' in active
    assert 'href="/media?media_type=podcast"' in active
    assert 'href="/media"' in active  # tout effacer


@pytest.mark.asyncio
async def test_search_keeps_the_other_filters(client):
    r = await client.get("/media?media_type=podcast&tag_age_group=kids")
    assert '"media_type": "podcast"' in r.text
    assert '"tag_age_group": "kids"' in r.text


@pytest.mark.asyncio
async def test_catalogue_has_no_select_wall_left(client):
    """v1 stacked one <select> per filter axis. None should remain."""
    r = await client.get("/media")
    filters = r.text.split('<div class="chip-bar">')[1].split('<div id="media-results">')[0]
    assert "<select" not in filters


@pytest.mark.asyncio
async def test_changing_a_filter_returns_to_page_one(client):
    r = await client.get("/media?page=3&media_type=podcast")
    assert "page=3" not in r.text.split('<div class="chip-bar">')[1].split("</div>")[0]
