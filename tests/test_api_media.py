"""REST contract of ``/api/v1/media``: response shapes, status codes, selection (dev mode = parent)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import media as _media_models  # noqa: F401
from app.models import rfid as _rfid_models  # noqa: F401
from app.services.tag_service import seed_default_tags

MEDIA_KEYS = {
    "id", "title", "media_type", "source_uri", "provider", "cover_url", "duration_min",
    "description", "metadata_extra", "cover_local", "is_active", "created_at", "updated_at", "tags",
}


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


def _payload(n: int = 1, **over) -> dict:
    p = {
        "title": f"Titre {n}", "media_type": "playlist", "source_uri": f"spotify://playlist/{n}",
        "provider": "spotify",
    }
    p.update(over)
    return p


async def _make(client, n=1, tags=(), **over) -> dict:
    r = await client.post(
        "/api/v1/media",
        json=_payload(n, tags_inline=[{"category": c, "value": v} for c, v in tags], **over),
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.mark.asyncio
async def test_create_answers_201_with_the_full_media_shape(client):
    r = await client.post("/api/v1/media", json=_payload(description="d", duration_min=12))
    assert r.status_code == 201
    body = r.json()
    assert set(body) == MEDIA_KEYS
    assert body["title"] == "Titre 1"
    assert body["media_type"] == "playlist"
    assert body["is_active"] is True
    assert body["duration_min"] == 12
    assert body["tags"] == []


@pytest.mark.asyncio
async def test_create_twice_is_idempotent_and_answers_200(client):
    first = await _make(client, 1)
    r = await client.post("/api/v1/media", json=_payload(1))
    assert r.status_code == 200
    assert r.json()["id"] == first["id"]
    listing = (await client.get("/api/v1/media")).json()
    assert listing["total"] == 1


@pytest.mark.asyncio
async def test_create_with_inline_tags_returns_brief_tags(client):
    body = await _make(client, 1, tags=[("mood", "calm")])
    assert body["tags"] == [{"category": "mood", "value": "calm"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"title": ""},
        {"media_type": "vinyl"},
        {"duration_min": -1},
        {"source_uri": ""},
    ],
)
async def test_create_rejects_invalid_payload_with_422(client, bad):
    r = await client.post("/api/v1/media", json=_payload(1, **bad))
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


@pytest.mark.asyncio
async def test_create_without_required_field_is_422(client):
    r = await client.post("/api/v1/media", json={"title": "x"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_returns_the_item_and_404_when_unknown(client):
    item = await _make(client, 1)
    ok = await client.get(f"/api/v1/media/{item['id']}")
    assert ok.status_code == 200
    assert set(ok.json()) == MEDIA_KEYS
    assert ok.json()["id"] == item["id"]
    missing = await client.get("/api/v1/media/does-not-exist")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Média introuvable"}


@pytest.mark.asyncio
async def test_list_pagination_envelope(client):
    for n in range(3):
        await _make(client, n)
    r = await client.get("/api/v1/media?page=1&page_size=2")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "page_size", "pages"}
    assert (body["total"], body["page"], body["page_size"], body["pages"]) == (3, 1, 2, 2)
    assert len(body["items"]) == 2
    second = (await client.get("/api/v1/media?page=2&page_size=2")).json()
    assert len(second["items"]) == 1
    assert {i["id"] for i in body["items"]}.isdisjoint({i["id"] for i in second["items"]})


@pytest.mark.asyncio
async def test_list_empty_has_zero_pages(client):
    body = (await client.get("/api/v1/media")).json()
    assert body == {"items": [], "total": 0, "page": 1, "page_size": 50, "pages": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["page=0", "page_size=0", "page_size=201", "media_type=vinyl"])
async def test_list_rejects_bad_query_with_422(client, q):
    assert (await client.get(f"/api/v1/media?{q}")).status_code == 422


@pytest.mark.asyncio
async def test_list_filters_by_search_type_provider_and_tag(client):
    await _make(client, 1, tags=[("mood", "calm")], title="Alpha")
    await _make(client, 2, tags=[("mood", "fun")], title="Beta", media_type="album")
    await _make(client, 3, title="Gamma", provider="local")

    def titles(r):
        return sorted(i["title"] for i in r.json()["items"])

    assert titles(await client.get("/api/v1/media?search=alph")) == ["Alpha"]
    assert titles(await client.get("/api/v1/media?media_type=album")) == ["Beta"]
    assert titles(await client.get("/api/v1/media?provider=local")) == ["Gamma"]
    assert titles(await client.get("/api/v1/media?mood=calm")) == ["Alpha"]


@pytest.mark.asyncio
async def test_update_is_partial_and_keeps_other_fields(client):
    item = await _make(client, 1, description="keep")
    r = await client.put(f"/api/v1/media/{item['id']}", json={"title": "Nouveau"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Nouveau"
    assert body["description"] == "keep"
    assert body["source_uri"] == item["source_uri"]


@pytest.mark.asyncio
async def test_update_unknown_is_404_and_invalid_is_422(client):
    assert (await client.put("/api/v1/media/nope", json={"title": "x"})).status_code == 404
    item = await _make(client, 1)
    assert (await client.put(f"/api/v1/media/{item['id']}", json={"title": ""})).status_code == 422


@pytest.mark.asyncio
async def test_update_replaces_tags_with_inline_list(client):
    item = await _make(client, 1, tags=[("mood", "calm")])
    r = await client.put(
        f"/api/v1/media/{item['id']}", json={"tags_inline": [{"category": "genre", "value": "rock"}]}
    )
    assert r.status_code == 200
    assert r.json()["tags"] == [{"category": "genre", "value": "rock"}]


@pytest.mark.asyncio
async def test_soft_delete_answers_204_and_hides_from_default_list(client):
    item = await _make(client, 1)
    r = await client.delete(f"/api/v1/media/{item['id']}")
    assert r.status_code == 204
    assert r.content == b""
    got = await client.get(f"/api/v1/media/{item['id']}")
    assert got.status_code == 200
    assert got.json()["is_active"] is False
    assert (await client.get("/api/v1/media")).json()["total"] == 0


@pytest.mark.asyncio
async def test_hard_delete_removes_the_row(client):
    item = await _make(client, 1)
    assert (await client.delete(f"/api/v1/media/{item['id']}?hard=true")).status_code == 204
    assert (await client.get(f"/api/v1/media/{item['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_delete_unknown_is_404(client):
    r = await client.delete("/api/v1/media/nope")
    assert r.status_code == 404
    assert r.json() == {"detail": "Média introuvable"}


@pytest.mark.asyncio
async def test_recreating_a_soft_deleted_item_reactivates_it(client):
    item = await _make(client, 1)
    await client.delete(f"/api/v1/media/{item['id']}")
    r = await client.post("/api/v1/media", json=_payload(1))
    assert r.status_code == 200
    assert r.json()["id"] == item["id"]
    assert r.json()["is_active"] is True


# --- selection -------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_returns_resolved_cover_urls_and_honours_limit(client):
    ids = [(await _make(client, n, tags=[("mood", "calm")]))["id"] for n in range(3)]
    r = await client.get("/api/v1/media/select?mood=calm&limit=2")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    for m in body:
        assert set(m) == MEDIA_KEYS | {"cover_url_resolved"}
        assert m["cover_url_resolved"] == f"http://test/covers/{m['id']}.jpg"
        assert m["id"] in ids


@pytest.mark.asyncio
async def test_select_and_between_categories_or_within_one(client):
    a = await _make(client, 1, tags=[("mood", "calm"), ("genre", "rock")])
    b = await _make(client, 2, tags=[("mood", "fun"), ("genre", "rock")])
    await _make(client, 3, tags=[("mood", "calm"), ("genre", "pop")])

    both = (await client.get("/api/v1/media/select?mood=calm&genre=rock")).json()
    assert [m["id"] for m in both] == [a["id"]]
    either = (await client.get("/api/v1/media/select?mood=calm,fun&genre=rock")).json()
    assert {m["id"] for m in either} == {a["id"], b["id"]}


@pytest.mark.asyncio
async def test_select_exclusions_and_exclude_ids(client):
    a = await _make(client, 1, tags=[("genre", "rock")])
    b = await _make(client, 2, tags=[("genre", "metal")])
    c = await _make(client, 3, tags=[("genre", "rock")])
    r = (await client.get("/api/v1/media/select?not_genre=metal")).json()
    assert {m["id"] for m in r} == {a["id"], c["id"]}
    r = (await client.get(f"/api/v1/media/select?exclude_ids={a['id']},{b['id']}")).json()
    assert [m["id"] for m in r] == [c["id"]]


@pytest.mark.asyncio
async def test_select_without_match_is_an_empty_list(client):
    await _make(client, 1, tags=[("mood", "calm")])
    r = await client.get("/api/v1/media/select?mood=nope")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["limit=0", "limit=101", "fallback=weird", "media_type=vinyl"])
async def test_select_rejects_bad_query_with_422(client, q):
    assert (await client.get(f"/api/v1/media/select?{q}")).status_code == 422


@pytest.mark.asyncio
async def test_select_fallback_relaxes_only_when_nothing_matches(client):
    a = await _make(client, 1, tags=[("owner", "papa"), ("mood", "calm")])
    strict = (await client.get("/api/v1/media/select?owner=papa&mood=fun")).json()
    assert strict == []
    soft = (await client.get("/api/v1/media/select?owner=papa&mood=fun&fallback=soft")).json()
    assert [m["id"] for m in soft] == [a["id"]]


@pytest.mark.asyncio
async def test_select_query_post_boolean_groups(client):
    a = await _make(client, 1, tags=[("owner", "papa"), ("mood", "calm")])
    b = await _make(client, 2, tags=[("owner", "papa"), ("context", "evening")])
    await _make(client, 3, tags=[("owner", "papa"), ("genre", "metal")])
    await _make(client, 4, tags=[("owner", "maman"), ("mood", "calm")])
    body = {
        "query": {
            "all_of": [{"category": "owner", "values": ["papa"]}],
            "any_of": [
                {"all_of": [{"category": "mood", "values": ["calm"]}]},
                {"all_of": [{"category": "context", "values": ["evening"]}]},
            ],
            "none_of": [{"category": "genre", "values": ["metal"]}],
        },
        "options": {"limit": 10},
    }
    r = await client.post("/api/v1/media/select/query", json=body)
    assert r.status_code == 200
    out = r.json()
    assert {m["id"] for m in out} == {a["id"], b["id"]}
    assert all("cover_url_resolved" in m for m in out)


@pytest.mark.asyncio
async def test_select_query_rejects_missing_query_with_422(client):
    assert (await client.post("/api/v1/media/select/query", json={})).status_code == 422
    r = await client.post(
        "/api/v1/media/select/query", json={"query": {}, "options": {"limit": 0}}
    )
    assert r.status_code == 422
