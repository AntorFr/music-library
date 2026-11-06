"""REST contract of ``/api/v1/tags``: shapes, status codes, write rules."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import media as _media_models  # noqa: F401
from app.models import rfid as _rfid_models  # noqa: F401
from app.services.tag_service import seed_default_tags

TAG_KEYS = {"id", "category", "value", "display", "category_label"}


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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_categories_list_has_the_seeded_defaults_with_shape(client):
    r = await client.get("/api/v1/tags/categories")
    assert r.status_code == 200
    cats = r.json()
    assert cats, "seed_default_tags must provide categories"
    for c in cats:
        assert set(c) == {"slug", "label", "color", "tag_count"}
    assert {"owner", "mood", "genre"} <= {c["slug"] for c in cats}


@pytest.mark.asyncio
async def test_create_category_answers_201_then_409_on_duplicate(client):
    r = await client.post(
        "/api/v1/tags/categories", json={"slug": "ambiance", "label": "Ambiance", "color": "#FF8800"}
    )
    assert r.status_code == 201
    assert r.json() == {"slug": "ambiance", "label": "Ambiance", "color": "#ff8800", "tag_count": 0}
    dup = await client.post("/api/v1/tags/categories", json={"slug": "ambiance", "label": "X"})
    assert dup.status_code == 409
    assert dup.json() == {"detail": "La catégorie 'ambiance' existe déjà"}
    slugs = [c["slug"] for c in (await client.get("/api/v1/tags/categories")).json()]
    assert slugs.count("ambiance") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"slug": "Bad Slug", "label": "x"},
        {"slug": "1abc", "label": "x"},
        {"slug": "ok", "label": ""},
        {"slug": "ok", "label": "x", "color": "red"},
        {"slug": "ok", "label": "x", "color": "#12345"},
    ],
)
async def test_create_category_validates_payload(client, bad):
    assert (await client.post("/api/v1/tags/categories", json=bad)).status_code == 422


@pytest.mark.asyncio
async def test_category_without_color_reads_back_null(client):
    r = await client.post("/api/v1/tags/categories", json={"slug": "nocolor", "label": "Sans"})
    assert r.status_code == 201
    assert r.json()["color"] is None


@pytest.mark.asyncio
async def test_delete_empty_category_204_then_404(client):
    await client.post("/api/v1/tags/categories", json={"slug": "tmp", "label": "Tmp"})
    assert (await client.delete("/api/v1/tags/categories/tmp")).status_code == 204
    gone = await client.delete("/api/v1/tags/categories/tmp")
    assert gone.status_code == 404
    assert gone.json() == {"detail": "Catégorie introuvable"}
    slugs = {c["slug"] for c in (await client.get("/api/v1/tags/categories")).json()}
    assert "tmp" not in slugs


@pytest.mark.asyncio
async def test_delete_category_that_still_has_tags_fails_with_500(db):
    """Doubtful, pinned as is: the docstring says the tags go with the category, but the
    relationship has no cascade, so the ORM nulls ``tags.category`` and SQLite refuses."""

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            await ac.post("/api/v1/tags/categories", json={"slug": "tmp", "label": "Tmp"})
            await ac.post("/api/v1/tags", json={"category": "tmp", "value": "a"})
            r = await ac.delete("/api/v1/tags/categories/tmp")
            assert r.status_code == 500
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_tag_answers_201_with_read_shape_and_category_label(client):
    r = await client.post("/api/v1/tags", json={"category": "mood", "value": "zen"})
    assert r.status_code == 201
    body = r.json()
    assert set(body) == TAG_KEYS
    assert (body["category"], body["value"]) == ("mood", "zen")
    assert isinstance(body["id"], int)
    labels = {c["slug"]: c["label"] for c in (await client.get("/api/v1/tags/categories")).json()}
    assert body["category_label"] == labels["mood"]


@pytest.mark.asyncio
async def test_create_tag_is_get_or_create(client):
    a = (await client.post("/api/v1/tags", json={"category": "mood", "value": "zen"})).json()
    b = await client.post("/api/v1/tags", json={"category": "mood", "value": "zen"})
    assert b.status_code == 201
    assert b.json()["id"] == a["id"]


@pytest.mark.asyncio
async def test_create_tag_in_unknown_category_is_400(client):
    r = await client.post("/api/v1/tags", json={"category": "nope", "value": "x"})
    assert r.status_code == 400
    assert r.json() == {"detail": "Catégorie 'nope' inconnue"}


@pytest.mark.asyncio
async def test_create_tag_validates_payload(client):
    assert (await client.post("/api/v1/tags", json={"category": "mood", "value": ""})).status_code == 422
    assert (await client.post("/api/v1/tags", json={"category": "mood"})).status_code == 422


@pytest.mark.asyncio
async def test_list_tags_filters_by_category_and_shapes_rows(client):
    await client.post("/api/v1/tags", json={"category": "mood", "value": "zen"})
    await client.post("/api/v1/tags", json={"category": "genre", "value": "jazz"})
    allt = (await client.get("/api/v1/tags")).json()
    assert {"mood", "genre"} <= {t["category"] for t in allt}
    only = (await client.get("/api/v1/tags?category=genre")).json()
    assert only and {t["category"] for t in only} == {"genre"}
    assert "jazz" in {t["value"] for t in only}
    assert all(set(t) == TAG_KEYS for t in only)


@pytest.mark.asyncio
async def test_category_tag_count_follows_tags(client):
    def counts(r):
        return {c["slug"]: c["tag_count"] for c in r.json()}

    before = counts(await client.get("/api/v1/tags/categories"))
    await client.post("/api/v1/tags", json={"category": "mood", "value": "zen-count"})
    after = counts(await client.get("/api/v1/tags/categories"))
    assert after["mood"] == before["mood"] + 1


@pytest.mark.asyncio
async def test_delete_tag_204_then_404(client):
    tag = (await client.post("/api/v1/tags", json={"category": "mood", "value": "zen"})).json()
    assert (await client.delete(f"/api/v1/tags/{tag['id']}")).status_code == 204
    gone = await client.delete(f"/api/v1/tags/{tag['id']}")
    assert gone.status_code == 404
    assert gone.json() == {"detail": "Tag introuvable"}


@pytest.mark.asyncio
async def test_delete_tag_with_non_integer_id_is_422(client):
    assert (await client.delete("/api/v1/tags/abc")).status_code == 422
