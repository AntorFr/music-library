"""Application start-up: ``init_db`` and the lifespan, on an empty base and on a
sample base in the previous schema.

The schema is not migrated by Alembic (there is none): it is created by ``create_all``
and upgraded by the one hand-written step of ``init_db`` — ``tag_categories.color``
(AD-filet-2). The sample base is a SQLite file whose ``tag_categories`` has no
``color`` column. ``init_db`` works on the module-global engine, so every test swaps
``engine`` / ``async_session`` of ``app.database`` for ones on a tmp file
(AD-filet-1); nothing else is patched but the covers directories and the
Music Assistant client, which never touches the network.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.database as database
import app.services.music_assistant as ma_module
from app.config import settings
from app.main import app
from app.models import media as _media_models  # noqa: F401
from app.models import rfid as _rfid_models  # noqa: F401
from app.services.tag_service import DEFAULT_TAG_CATEGORIES

EXPECTED_TABLES = {"media", "media_tags", "tag_categories", "tags", "rfid_tags"}

#: The previous schema: ``tag_categories`` without ``color``; the rest as it was.
OLD_SCHEMA = [
    "CREATE TABLE tag_categories (slug VARCHAR(50) NOT NULL PRIMARY KEY, "
    "label VARCHAR(100) NOT NULL)",
    "CREATE TABLE tags (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
    "category VARCHAR(50) NOT NULL REFERENCES tag_categories (slug) ON DELETE CASCADE, "
    "value VARCHAR(100) NOT NULL, CONSTRAINT uq_tag_category_value UNIQUE (category, value))",
]
OLD_ROWS = [
    "INSERT INTO tag_categories (slug, label) VALUES ('owner', 'Propriétaire')",
    "INSERT INTO tag_categories (slug, label) VALUES ('saga', 'Sagas')",
    "INSERT INTO tags (category, value) VALUES ('owner', 'lea')",
    "INSERT INTO tags (category, value) VALUES ('saga', 'Mickey')",
]


def _url(tmp_path, name="t.db"):
    return f"sqlite+aiosqlite:///{tmp_path/name}"


@pytest.fixture
def swap_engine(tmp_path, monkeypatch):
    """Point ``app.database`` at a tmp file; returns the engine."""
    def _swap(name="t.db"):
        eng = create_async_engine(_url(tmp_path, name), echo=False)
        monkeypatch.setattr(database, "engine", eng)
        monkeypatch.setattr(
            database, "async_session",
            async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False),
        )
        return eng

    return _swap


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "covers_dir", tmp_path / "data" / "covers")
    monkeypatch.setattr(settings, "thumbs_dir", tmp_path / "thumbs")


class FakeMA:
    def __init__(self):
        self.disconnected = False

    async def disconnect(self):
        self.disconnected = True


@pytest.fixture
def fake_ma(monkeypatch):
    fake = FakeMA()
    monkeypatch.setattr(ma_module, "_client", fake)
    return fake


async def _tables(eng):
    async with eng.connect() as conn:
        res = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        return {r[0] for r in res.fetchall()}


async def _columns(eng, table):
    async with eng.connect() as conn:
        res = await conn.execute(text(f"PRAGMA table_info({table})"))
        return [r[1] for r in res.fetchall()]


async def _make_sample(eng):
    async with eng.begin() as conn:
        for stmt in OLD_SCHEMA + OLD_ROWS:
            await conn.exec_driver_sql(stmt)


# --- init_db on an empty base -----------------------------------------------

async def test_init_db_creates_every_table_on_an_empty_base(swap_engine):
    eng = swap_engine()
    assert await _tables(eng) == set()

    await database.init_db()

    assert await _tables(eng) >= EXPECTED_TABLES
    assert "color" in await _columns(eng, "tag_categories")


async def test_init_db_on_an_empty_base_creates_no_rows(swap_engine):
    eng = swap_engine()
    await database.init_db()
    async with eng.connect() as conn:
        for table in EXPECTED_TABLES:
            n = (await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()
            assert n == 0, table


async def test_init_db_twice_is_harmless(swap_engine):
    eng = swap_engine()
    await database.init_db()
    cols = await _columns(eng, "tag_categories")
    await database.init_db()
    assert await _columns(eng, "tag_categories") == cols
    assert cols.count("color") == 1


# --- init_db on the previous schema -------------------------------------------

async def test_the_sample_base_really_lacks_the_color_column(swap_engine):
    """Guards the fixture: without it the migration tests below would prove nothing."""
    eng = swap_engine()
    await _make_sample(eng)
    assert "color" not in await _columns(eng, "tag_categories")
    assert await _tables(eng) == {"tag_categories", "tags", "sqlite_sequence"}


async def test_init_db_adds_the_color_column_to_the_sample_base(swap_engine):
    eng = swap_engine()
    await _make_sample(eng)

    await database.init_db()

    assert "color" in await _columns(eng, "tag_categories")


async def test_init_db_keeps_every_row_of_the_sample_base(swap_engine):
    eng = swap_engine()
    await _make_sample(eng)

    await database.init_db()

    async with eng.connect() as conn:
        cats = (await conn.execute(
            text("SELECT slug, label, color FROM tag_categories ORDER BY slug")
        )).fetchall()
        tags = (await conn.execute(
            text("SELECT category, value FROM tags ORDER BY category")
        )).fetchall()
    assert [tuple(r) for r in cats] == [
        ("owner", "Propriétaire", None),
        ("saga", "Sagas", None),
    ]
    assert [tuple(r) for r in tags] == [("owner", "lea"), ("saga", "Mickey")]


async def test_init_db_creates_the_tables_missing_from_the_sample_base(swap_engine):
    eng = swap_engine()
    await _make_sample(eng)
    await database.init_db()
    assert await _tables(eng) >= EXPECTED_TABLES


async def test_the_added_column_is_nullable_and_writable(swap_engine):
    eng = swap_engine()
    await _make_sample(eng)
    await database.init_db()
    async with eng.begin() as conn:
        await conn.exec_driver_sql("UPDATE tag_categories SET color='#112233' WHERE slug='saga'")
    async with eng.connect() as conn:
        got = (await conn.execute(
            text("SELECT slug, color FROM tag_categories ORDER BY slug")
        )).fetchall()
    assert [tuple(r) for r in got] == [("owner", None), ("saga", "#112233")]


async def test_init_db_twice_on_the_sample_base_keeps_one_color_column(swap_engine):
    eng = swap_engine()
    await _make_sample(eng)
    await database.init_db()
    await database.init_db()
    assert (await _columns(eng, "tag_categories")).count("color") == 1
    async with eng.connect() as conn:
        n = (await conn.execute(text("SELECT COUNT(*) FROM tag_categories"))).scalar_one()
    assert n == 2


async def test_no_alembic_version_table_is_ever_created(swap_engine):
    """AD-filet-2: the schema evolves in init_db; there is no Alembic bookkeeping."""
    eng = swap_engine()
    await _make_sample(eng)
    await database.init_db()
    assert "alembic_version" not in await _tables(eng)


# --- Lifespan -----------------------------------------------------------------

async def test_lifespan_on_an_empty_base_builds_schema_and_seeds_default_tags(
    swap_engine, fake_ma, tmp_path
):
    eng = swap_engine()

    async with app.router.lifespan_context(app):
        assert await _tables(eng) >= EXPECTED_TABLES
        async with eng.connect() as conn:
            slugs = {r[0] for r in (await conn.execute(
                text("SELECT slug FROM tag_categories")
            )).fetchall()}
            n_tags = (await conn.execute(text("SELECT COUNT(*) FROM tags"))).scalar_one()
        assert slugs == set(DEFAULT_TAG_CATEGORIES)
        assert n_tags == 4 + 6 + 7 + 4 + 4 + 7  # owner, mood, context, time, age, genre
    assert (tmp_path / "data" / "covers").is_dir()
    assert (tmp_path / "thumbs").is_dir()


async def test_lifespan_shutdown_disconnects_music_assistant(swap_engine, fake_ma):
    swap_engine()
    async with app.router.lifespan_context(app):
        assert fake_ma.disconnected is False
    assert fake_ma.disconnected is True
    assert ma_module._client is None


async def test_lifespan_upgrades_the_sample_base_and_does_not_reseed(swap_engine, fake_ma):
    eng = swap_engine()
    await _make_sample(eng)

    async with app.router.lifespan_context(app):
        assert "color" in await _columns(eng, "tag_categories")
        async with eng.connect() as conn:
            rows = (await conn.execute(
                text("SELECT slug, label FROM tag_categories ORDER BY slug")
            )).fetchall()
            tags = (await conn.execute(
                text("SELECT category, value FROM tags ORDER BY category")
            )).fetchall()

    # Categories already present => seeding is skipped entirely, nothing is added.
    assert [tuple(r) for r in rows] == [("owner", "Propriétaire"), ("saga", "Sagas")]
    assert [tuple(r) for r in tags] == [("owner", "lea"), ("saga", "Mickey")]


async def test_lifespan_restart_does_not_duplicate_the_seed(swap_engine, fake_ma):
    eng = swap_engine()
    async with app.router.lifespan_context(app):
        pass
    async with eng.connect() as conn:
        before = (await conn.execute(text("SELECT COUNT(*) FROM tags"))).scalar_one()
    ma_module._client = FakeMA()
    async with app.router.lifespan_context(app):
        pass
    async with eng.connect() as conn:
        after = (await conn.execute(text("SELECT COUNT(*) FROM tags"))).scalar_one()
    assert before == after > 0


async def test_the_upgraded_sample_base_serves_the_app(swap_engine, fake_ma):
    """After start-up the real routes read the migrated base (color is selectable)."""
    swap_engine()
    eng = database.engine
    await _make_sample(eng)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/api/v1/tags/categories")
    assert r.status_code == 200
    got = {c["slug"]: c for c in r.json()}
    assert set(got) == {"owner", "saga"}
    assert got["saga"]["label"] == "Sagas"
