"""Owner-tag permissions seen through the REST API: parent / child / machine, case and accent
normalisation, group tags. Completes test_auth_permissions (not repeated here): the surfaces it
leaves out — select/query, quick, tag routes, ma/import, hard delete of others', bearer edges."""

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
from app.services.auth_service import (
    CurrentUser,
    normalize_owner,
    user_from_session,
    user_to_session,
)
from app.services.music_assistant import get_ma_client
from app.services.permissions import can_view_media, is_protected_owner_tag
from app.services.tag_service import seed_default_tags


class ImportableItem:
    name = "Importé"
    media_type = "playlist"
    uri = "library://playlist/9"
    provider = "library"
    provider_mappings = []
    duration = 0
    description = ""
    artist_str = ""
    album_name = ""
    item_id = "9"


class FakeMA:
    async def get_item_by_uri(self, uri):
        if uri != ImportableItem.uri:
            raise RuntimeError("not found")
        return ImportableItem()

    def get_item_image_url(self, item, size=0):
        return f"https://cdn.test/{item.item_id}?s={size}"

    async def get_podcast_episodes(self, item_id, provider):
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
async def client(db: AsyncSession, monkeypatch):
    async def override_get_db():
        yield db

    async def no_cover(*_a, **_k):
        return None

    monkeypatch.setattr("app.services.cover_service.download_and_save_cover", no_cover)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_ma_client] = lambda: FakeMA()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def oidc_on(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.test")
    monkeypatch.setattr(settings, "oidc_client_id", "music-library")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "https://ml.test/auth/callback")


def _login(client: AsyncClient, username: str, role: str = "child", groups=()) -> None:
    from itsdangerous import TimestampSigner

    secret = next(m.kwargs["secret_key"] for m in app.user_middleware if m.cls is SessionMiddleware)
    user = {"username": username, "display_name": username, "role": role, "groups": list(groups)}
    payload = base64.b64encode(json.dumps({"user": user}).encode())
    client.cookies.set("session", TimestampSigner(str(secret)).sign(payload).decode())


async def _media(db, title, owners=(), uri=None, media_type=MediaType.playlist):
    item, _ = await media_service.create_media(
        db,
        MediaCreate(
            title=title, media_type=media_type, source_uri=uri or f"spotify://x/{title}",
            provider="spotify",
            tags_inline=[{"category": "owner", "value": o} for o in owners],
        ),
    )
    await db.commit()
    return item


def _titles(r) -> set[str]:
    body = r.json()
    items = body["items"] if isinstance(body, dict) else body
    return {i["title"] for i in items}


# --- normalisation: case and accents ----------------------------------------------


@pytest.mark.parametrize(
    "raw,key",
    [("Zoé", "zoe"), ("ZOE", "zoe"), ("zoé", "zoe"), ("Sébastien", "sebastien"), ("Éloïse", "eloise")],
)
def test_normalize_owner_folds_case_and_accents(raw, key):
    assert normalize_owner(raw) == key


@pytest.mark.asyncio
@pytest.mark.parametrize("tag,username", [("LEA", "lea"), ("lea", "LEA"), ("Zoé", "zoe"), ("zoe", "Zoé"), ("ÉLOÏSE", "eloise")])
async def test_owner_matching_ignores_case_and_accents_both_ways(client, db, oidc_on, tag, username):
    _login(client, username)
    mine = await _media(db, "Mien", [tag])
    await _media(db, "Autre", ["papa"])
    r = await client.get("/api/v1/media")
    assert _titles(r) == {"Mien"}
    assert (await client.get(f"/api/v1/media/{mine.id}")).status_code == 200


@pytest.mark.asyncio
async def test_group_name_matches_owner_tag_ignoring_case_and_accents(client, db, oidc_on):
    _login(client, "lea", groups=["Famille", "Éveil"])
    await _media(db, "Partagé", ["famille"])
    await _media(db, "Éveil", ["eveil"])
    await _media(db, "Papa", ["papa"])
    assert _titles(await client.get("/api/v1/media")) == {"Partagé", "Éveil"}


@pytest.mark.asyncio
async def test_media_with_several_owner_tags_is_seen_by_any_of_them(client, db, oidc_on):
    _login(client, "lea")
    await _media(db, "Duo", ["papa", "lea"])
    assert _titles(await client.get("/api/v1/media")) == {"Duo"}


@pytest.mark.asyncio
async def test_non_owner_tag_carrying_the_childs_name_does_not_grant_access(client, db, oidc_on):
    """Only tags of the `owner` category scope a child: a `genre` tag whose value equals the
    child's name (or a group name) must not open the media. Fails if the category test is dropped."""
    item, _ = await media_service.create_media(
        db,
        MediaCreate(
            title="Faux propriétaire", media_type=MediaType.playlist, source_uri="spotify://x/faux",
            provider="spotify",
            tags_inline=[{"category": "genre", "value": "Léa"}, {"category": "genre", "value": "Famille"}],
        ),
    )
    await db.commit()
    _login(client, "lea", groups=["famille"])
    assert _titles(await client.get("/api/v1/media")) == set()
    assert (await client.get(f"/api/v1/media/{item.id}")).status_code == 404


@pytest.mark.asyncio
async def test_untagged_media_is_hidden_from_a_child_and_visible_to_a_parent(client, db, oidc_on):
    orphan = await _media(db, "Orpheline")
    _login(client, "lea")
    assert _titles(await client.get("/api/v1/media")) == set()
    assert (await client.get(f"/api/v1/media/{orphan.id}")).status_code == 404
    _login(client, "papa", role="parent")
    assert _titles(await client.get("/api/v1/media")) == {"Orpheline"}


def test_view_and_write_keys_of_the_user_model():
    child = CurrentUser("Zoé", "Zoé", "child", ("Famille",))
    assert child.owner_value == "zoe"
    assert child.view_owner_keys == frozenset({"zoe", "famille"})
    parent = CurrentUser("papa", "Papa", "parent")
    assert parent.owner_value is None
    assert parent.view_owner_keys is None


def test_session_round_trip_and_rejects_forged_roles():
    child = CurrentUser("lea", "Léa", "child", ("enfants",))
    assert user_from_session(user_to_session(child)) == child
    assert user_from_session({"username": "x", "role": "root"}) is None
    assert user_from_session({"username": "", "role": "parent"}) is None
    assert user_from_session("nope") is None


# --- reads: the API surfaces a child can reach ------------------------------------


@pytest.mark.asyncio
async def test_child_cannot_reach_others_through_the_owner_filter(client, db, oidc_on):
    _login(client, "lea")
    await _media(db, "Mien", ["lea"])
    await _media(db, "Rock", ["papa"])
    assert _titles(await client.get("/api/v1/media?owner=papa")) == set()
    assert _titles(await client.get("/api/v1/media/select?owner=papa")) == set()
    assert _titles(await client.get("/api/v1/media/select?not_owner=lea")) == set()


@pytest.mark.asyncio
async def test_select_query_post_is_scoped_for_a_child(client, db, oidc_on):
    _login(client, "lea")
    await _media(db, "Mien", ["lea"])
    await _media(db, "Rock", ["papa"])
    body = {"query": {"all_of": [{"category": "owner", "values": ["papa", "lea"]}]}}
    assert _titles(await client.post("/api/v1/media/select/query", json=body)) == {"Mien"}
    _login(client, "papa", role="parent")
    assert _titles(await client.post("/api/v1/media/select/query", json=body)) == {"Mien", "Rock"}


@pytest.mark.asyncio
async def test_quick_favourites_only_reach_the_childs_own_grid(client, db, oidc_on):
    _login(client, "lea")
    await _media(db, "Mien", ["lea"])
    await _media(db, "Rock", ["papa"])
    assert (await client.get("/api/v1/quick/lea")).json()["count"] == 1
    assert (await client.get("/api/v1/quick/papa")).json() == {"owner": "papa", "count": 0, "items": []}


@pytest.mark.asyncio
async def test_quick_children_of_someone_elses_media_is_404(client, db, oidc_on):
    other = await _media(db, "Podcast", ["papa"], media_type=MediaType.podcast)
    _login(client, "lea")
    assert (await client.get(f"/api/v1/quick/item/{other.id}/children")).status_code == 404
    _login(client, "papa", role="parent")
    assert (await client.get(f"/api/v1/quick/item/{other.id}/children")).status_code == 200


@pytest.mark.asyncio
async def test_hidden_and_missing_media_answer_identically(client, db, oidc_on):
    other = await _media(db, "Rock", ["papa"])
    _login(client, "lea")
    hidden = await client.get(f"/api/v1/media/{other.id}")
    missing = await client.get("/api/v1/media/nope")
    assert (hidden.status_code, hidden.json()) == (missing.status_code, missing.json()) == (
        404, {"detail": "Média introuvable"})


# --- writes -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_child_delete_of_others_media_is_404_even_when_hard(client, db, oidc_on):
    other = await _media(db, "Rock", ["papa"])
    _login(client, "lea")
    assert (await client.delete(f"/api/v1/media/{other.id}")).status_code == 404
    assert (await client.delete(f"/api/v1/media/{other.id}?hard=true")).status_code == 404
    _login(client, "papa", role="parent")
    assert (await client.get(f"/api/v1/media/{other.id}")).json()["is_active"] is True


@pytest.mark.asyncio
async def test_child_hard_delete_of_own_media_is_403_and_keeps_the_row(client, db, oidc_on):
    mine = await _media(db, "Mien", ["lea"])
    _login(client, "lea")
    r = await client.delete(f"/api/v1/media/{mine.id}?hard=true")
    assert r.status_code == 403
    assert r.json() == {"detail": "Réservé aux parents"}
    assert (await client.get(f"/api/v1/media/{mine.id}")).status_code == 200


@pytest.mark.asyncio
async def test_parent_can_hard_delete_anyones_media(client, db, oidc_on):
    other = await _media(db, "Rock", ["papa"])
    _login(client, "mama", role="parent")
    assert (await client.delete(f"/api/v1/media/{other.id}?hard=true")).status_code == 204
    assert (await client.get(f"/api/v1/media/{other.id}")).status_code == 404


@pytest.mark.asyncio
async def test_child_update_of_group_media_keeps_every_owner_tag(client, db, oidc_on):
    _login(client, "lea", groups=["famille"])
    shared = await _media(db, "Partagé", ["famille", "papa"])
    r = await client.put(
        f"/api/v1/media/{shared.id}",
        json={"tags_inline": [{"category": "mood", "value": "calm"}]},
    )
    assert r.status_code == 200
    tags = {(t["category"], t["value"]) for t in r.json()["tags"]}
    assert {("owner", "famille"), ("owner", "papa"), ("mood", "calm")} <= tags


@pytest.mark.asyncio
async def test_child_create_of_existing_item_adds_own_owner_tag_and_answers_200(client, db, oidc_on):
    await _media(db, "Existant", ["papa"], uri="spotify://playlist/shared")
    _login(client, "lea")
    r = await client.post("/api/v1/media", json={
        "title": "Existant", "media_type": "playlist",
        "source_uri": "spotify://playlist/shared", "provider": "spotify"})
    assert r.status_code == 200
    owners = {t["value"].lower() for t in r.json()["tags"] if t["category"] == "owner"}
    assert owners == {"papa", "lea"}


@pytest.mark.asyncio
async def test_parent_create_adds_no_owner_tag(client, db, oidc_on):
    _login(client, "papa", role="parent")
    r = await client.post("/api/v1/media", json={
        "title": "X", "media_type": "playlist", "source_uri": "spotify://playlist/x", "provider": "spotify"})
    assert r.status_code == 201
    assert r.json()["tags"] == []


@pytest.mark.asyncio
async def test_child_import_from_ma_gets_the_owner_tag(client, db, oidc_on):
    _login(client, "Zoé")
    r = await client.post("/api/v1/ma/import?uri=library://playlist/9")
    assert r.status_code == 200
    assert [t["value"] for t in r.json()["tags"] if t["category"] == "owner"] == ["zoe"]


@pytest.mark.asyncio
async def test_parent_import_from_ma_gets_no_owner_tag(client, db, oidc_on):
    _login(client, "papa", role="parent")
    r = await client.post("/api/v1/ma/import?uri=library://playlist/9")
    assert r.status_code == 200
    assert [t for t in r.json()["tags"] if t["category"] == "owner"] == []


# --- tag management is parent-only, reading is open ----------------------------------


@pytest.mark.asyncio
async def test_child_is_refused_every_tag_write_but_may_read(client, db, oidc_on):
    tag = None
    _login(client, "papa", role="parent")
    tag = (await client.post("/api/v1/tags", json={"category": "mood", "value": "zen"})).json()
    _login(client, "lea")
    denied = {"detail": "Réservé aux parents"}
    for r in (
        await client.post("/api/v1/tags/categories", json={"slug": "x", "label": "X"}),
        await client.delete("/api/v1/tags/categories/mood"),
        await client.post("/api/v1/tags", json={"category": "mood", "value": "a"}),
        await client.delete(f"/api/v1/tags/{tag['id']}"),
    ):
        assert r.status_code == 403
        assert r.json() == denied
    assert (await client.get("/api/v1/tags")).status_code == 200
    assert (await client.get("/api/v1/tags/categories")).status_code == 200
    # nothing was removed
    assert tag["id"] in {t["id"] for t in (await client.get("/api/v1/tags?category=mood")).json()}


@pytest.mark.asyncio
async def test_permission_check_precedes_validation_on_tag_writes(client, oidc_on):
    _login(client, "lea")
    r = await client.post("/api/v1/tags", json={"category": "nope", "value": "x"})
    assert r.status_code == 403


# --- machine bearer token ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_bearer_token_is_parent_level_across_the_api(client, db, oidc_on, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "s3cret")
    await _media(db, "Rock", ["papa"])
    h = {"Authorization": "Bearer s3cret"}
    assert _titles(await client.get("/api/v1/media", headers=h)) == {"Rock"}
    assert (await client.post("/api/v1/tags", json={"category": "mood", "value": "t"}, headers=h)).status_code == 201
    assert (await client.get("/api/v1/quick/papa", headers=h)).json()["count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header",
    ["Bearer wrong", "Bearer ", "Basic s3cret", "s3cret", "bearer"],
)
async def test_bad_bearer_headers_are_401(client, oidc_on, monkeypatch, header):
    monkeypatch.setattr(settings, "api_token", "s3cret")
    r = await client.get("/api/v1/media", headers={"Authorization": header})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_non_ascii_bearer_is_401_not_500(client, oidc_on, monkeypatch):
    """S-2: compare_digest raised TypeError on a non-ASCII str -> unauthenticated 500."""
    monkeypatch.setattr(settings, "api_token", "s3cret")
    r = await client.get(
        "/api/v1/media", headers={"Authorization": "Bearer sécrét".encode()}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_bearer_scheme_is_case_insensitive(client, oidc_on, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "s3cret")
    r = await client.get("/api/v1/media", headers={"Authorization": "bEaReR s3cret"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_bearer_is_ignored_when_no_token_is_configured(client, oidc_on, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "")
    r = await client.get("/api/v1/media", headers={"Authorization": "Bearer "})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_forged_or_unsigned_session_cookie_is_401(client, oidc_on):
    client.cookies.set("session", "not-a-signed-cookie")
    assert (await client.get("/api/v1/media")).status_code == 401


@pytest.mark.asyncio
async def test_api_and_cover_exemptions_with_auth_on(client, oidc_on):
    assert (await client.get("/api/v1/health")).status_code != 401
    assert (await client.get("/api/v1/media")).status_code == 401
    assert (await client.get("/api/v1/ma/players")).status_code == 401
    assert (await client.get("/api/v1/quick/lea")).status_code == 401
    assert (await client.get("/api/v1/tags")).status_code == 401


def test_pure_permission_helpers():
    child = CurrentUser("lea", "Lea", "child", ("famille",))
    tag = type("T", (), {"category": "owner", "value": "x"})
    other = type("T", (), {"category": "mood", "value": "x"})
    assert is_protected_owner_tag(child, tag) is True
    assert is_protected_owner_tag(child, other) is False
    assert is_protected_owner_tag(CurrentUser("p", "P", "parent"), tag) is False
    item = type("M", (), {"tags": [type("T", (), {"category": "owner", "value": "FAMILLE"})]})
    assert can_view_media(child, item) is True
    assert can_view_media(CurrentUser("zed", "Z", "child"), item) is False
