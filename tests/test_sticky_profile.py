"""The launcher must remember the profile and the speaker — across visits, and
across a Music Assistant hiccup.

Two bugs motivated these:

1. Coming back to the launcher through the menu is an hx-boost swap, which does
   not fire DOMContentLoaded — the only trigger the restore was bound to. The
   page stayed in its server-rendered default (setup card, nothing selected), so
   it looked as though the choice had been wiped when it was simply never read.
2. The saved speaker was deleted whenever it was missing from the player list
   the server had just sent — and that list is empty every time MA is
   unreachable, or a speaker is asleep.
"""

from __future__ import annotations

import pathlib

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

LISTEN_TEMPLATE = pathlib.Path("app/templates/listen/index.html").read_text()


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


# --- The server honours the cookie on the very first request ---------------

@pytest.mark.asyncio
async def test_cookie_selects_the_profile_without_a_url_param(client, db):
    await _media(db, title="Playlist Papa", owner="papa", uri="spotify://playlist/p")
    await _media(db, title="Playlist Maman", owner="maman", uri="spotify://playlist/m")

    client.cookies.set("ml_owner", "papa")
    r = await client.get("/")

    assert r.status_code == 200
    assert "Playlist Papa" in r.text
    assert "Playlist Maman" not in r.text


@pytest.mark.asyncio
async def test_url_param_beats_the_cookie(client, db):
    await _media(db, title="Playlist Papa", owner="papa", uri="spotify://playlist/p")
    await _media(db, title="Playlist Maman", owner="maman", uri="spotify://playlist/m")

    client.cookies.set("ml_owner", "papa")
    r = await client.get("/?owner=maman")

    assert "Playlist Maman" in r.text
    assert "Playlist Papa" not in r.text


@pytest.mark.asyncio
async def test_a_stale_cookie_does_not_break_the_page(client, db):
    """A profile that no longer exists must fall back, not 500."""
    client.cookies.set("ml_owner", "quelquun-qui-nexiste-plus")
    r = await client.get("/")
    assert r.status_code == 200


# --- The page restores itself after an hx-boost swap -----------------------

def test_restore_runs_on_htmx_load_too():
    """hx-boost never fires DOMContentLoaded — binding to it alone was the bug."""
    assert "htmx:load" in LISTEN_TEMPLATE
    assert "bootListen" in LISTEN_TEMPLATE


def test_script_survives_being_run_twice():
    """hx-boost re-executes the script on each arrival; a top-level const would
    throw on redeclaration and take the whole block down with it."""
    scripts = LISTEN_TEMPLATE.split("{% block scripts %}")[1]
    assert "(function () {" in scripts
    for name in ("playQuickMedia", "openQuickPanel", "playEpisode", "filterChapters"):
        assert f"window.{name} = {name};" in scripts, f"{name} doit rester global"


# --- A missing speaker is not an invalid speaker ---------------------------

def test_the_saved_speaker_is_never_deleted():
    """MA blinking, or a speaker asleep, must not cost the user their choice."""
    # The keys the old code wiped are gone entirely.
    assert "QUICK_PLAYER_KEY" not in LISTEN_TEMPLATE
    assert "QUICK_OWNER_KEY" not in LISTEN_TEMPLATE
    # The only removal left is the one-off migration of the pre-0.22.1 settings.
    assert LISTEN_TEMPLATE.count("localStorage.removeItem") == 1
    assert "localStorage.removeItem(legacyKey)" in LISTEN_TEMPLATE
    # And the speaker is read back without being checked against the live list.
    assert "readCookie(PLAYER_COOKIE)" in LISTEN_TEMPLATE


def test_an_offline_speaker_is_reported_not_dropped():
    assert 'id="quickPlayerOffline"' in LISTEN_TEMPLATE
    assert "Enceinte hors ligne" in LISTEN_TEMPLATE


def test_settings_persist_for_a_year():
    assert "60 * 60 * 24 * 365" in LISTEN_TEMPLATE
    assert "SameSite=Lax" in LISTEN_TEMPLATE
