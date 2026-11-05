"""Security surfaces pass: S-12 (non-ASCII thumbnail signature) and S-13 (stored XSS through
media text reaching JavaScript contexts). No network; Music Assistant is not involved."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import media as _media_models  # noqa: F401
from app.models import rfid as _rfid_models  # noqa: F401
from app.models.media import MediaType
from app.schemas.media import MediaCreate
from app.services import cover_service, media_service
from app.services.tag_service import seed_default_tags

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
EVIL = "a');alert(1);//"


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))


def _render(name: str, **ctx) -> str:
    return _env().get_template(name).render(**ctx)


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
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# --- S-12: a crafted signature answers 403, never 500 ------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("sig", ["é", "%E2%82%AC%E2%82%AC", "deadbeé"])
async def test_thumb_non_ascii_signature_is_403_not_500(client, sig):
    r = await client.get(f"/api/v1/quick/thumb?src=http://x/y.jpg&size=96&sig={sig}")
    assert r.status_code == 403


def test_verify_thumb_accepts_its_own_signature_and_refuses_non_ascii():
    good = cover_service.sign_thumb("http://x/y.jpg", 96)
    assert cover_service.verify_thumb("http://x/y.jpg", 96, good) is True
    assert cover_service.verify_thumb("http://x/y.jpg", 96, "é" * len(good)) is False
    assert cover_service.verify_thumb("http://x/y.jpg", 96, "") is False


# --- S-13: author text never lands inside an inline JS string ----------------


def test_audiobook_chapters_uri_is_data_attribute_not_js_literal():
    html = _render(
        "components/audiobook_chapters.html",
        audiobook_uri=EVIL, chapters=[{"name": "c1", "start": 12.4}], resume_pct=30,
        fully_played=False, error=None,
    )
    assert "playChapter('" not in html
    assert 'onclick="playChapter(this.dataset.uri' in html
    assert html.count('data-uri="a&#39;);alert(1);//"') == 2  # resume button + chapter row


def test_podcast_episode_uri_is_data_attribute_not_js_literal():
    html = _render(
        "components/podcast_episodes.html",
        episodes=[{"name": "ep", "uri": EVIL, "duration": 60}], error=None,
    )
    assert "playEpisode('" not in html
    assert 'data-uri="a&#39;);alert(1);//"' in html
    assert 'onclick="playEpisode(this.dataset.uri)"' in html


def test_ma_items_uri_is_data_attribute_not_js_literal():
    html = _render(
        "components/ma_items.html",
        items=[{"name": "n", "uri": EVIL, "thumb_url_resolved": "", "media_type": "album"}],
    )
    assert "importItem('" not in html
    assert 'data-uri="a&#39;);alert(1);//"' in html
    assert "importItem(this.dataset.uri, this)" in html


def test_toast_message_is_never_parsed_as_html():
    base = (TEMPLATES / "base.html").read_text()
    start = base.index("function showToast")
    body = base[start: base.index("// --- HTMX event listeners", start)]
    assert "innerHTML" not in body
    assert "createTextNode" in body


@pytest.mark.asyncio
async def test_detail_page_source_uri_is_a_json_literal(client, db):
    uri = "spotify://x');alert(1);//"
    item, _ = await media_service.create_media(
        db,
        MediaCreate(title="T", media_type=MediaType.playlist, source_uri=uri, provider="spotify"),
    )
    await db.commit()
    r = await client.get(f"/media/{item.id}")
    assert r.status_code == 200
    assert "const uri = '" not in r.text
    # tojson escapes the quote as ' so the literal cannot be closed early
    assert f"const uri = {json.dumps(uri)}".replace("'", "\\u0027") in r.text
    assert "');alert(1)" not in r.text


def test_ma_search_results_uri_is_data_attribute_not_js_literal():
    html = _render(
        "components/ma_search_results.html",
        has_results=True,
        groups=[("album", "Albums", [
            {"name": "n", "uri": EVIL, "thumb_url_resolved": "", "media_type": "album"},
        ])],
    )
    assert "importItem('" not in html
    assert 'data-uri="a&#39;);alert(1);//"' in html
    assert "importItem(this.dataset.uri, this)" in html
