"""Auth & permission tests: OIDC session roles, child scoping, machine bearer token."""

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
from app.services.auth_service import user_from_claims
from app.services.tag_service import seed_default_tags


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

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


@pytest.fixture
def oidc_on(monkeypatch):
    """Enable auth enforcement (the four OIDC settings go together)."""
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.test")
    monkeypatch.setattr(settings, "oidc_client_id", "music-library")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "https://ml.test/auth/callback")


def _session_cookie(user: dict) -> str:
    """Forge a signed session cookie the way SessionMiddleware writes it."""
    from itsdangerous import TimestampSigner

    secret = next(
        m.kwargs["secret_key"] for m in app.user_middleware if m.cls is SessionMiddleware
    )
    payload = base64.b64encode(json.dumps({"user": user}).encode())
    return TimestampSigner(str(secret)).sign(payload).decode()


def _login_child(client: AsyncClient, username: str = "lea", groups: list[str] | None = None) -> None:
    client.cookies.set("session", _session_cookie(
        {"username": username, "display_name": username.capitalize(), "role": "child",
         "groups": groups or []}
    ))


def _login_parent(client: AsyncClient) -> None:
    client.cookies.set("session", _session_cookie(
        {"username": "papa", "display_name": "Papa", "role": "parent"}
    ))


async def _create_media(db: AsyncSession, *, title: str, owner: str, uri: str):
    item, _ = await media_service.create_media(
        db,
        MediaCreate(
            title=title,
            media_type=MediaType.playlist,
            source_uri=uri,
            provider="spotify",
            cover_url=None,
            duration_min=None,
            description=None,
            metadata_extra=None,
            tag_ids=[],
            tags_inline=[{"category": "owner", "value": owner}],
        ),
    )
    await db.commit()
    return item


# ---------------------------------------------------------------------------
# Role derivation
# ---------------------------------------------------------------------------

def test_admin_group_grants_parent_role():
    claims = {"preferred_username": "papa", "name": "Papa", "groups": ["admins", "parents"]}
    assert user_from_claims(claims).role == "parent"


def test_other_users_are_children():
    user = user_from_claims({"preferred_username": "Lea", "groups": ["enfants"]})
    assert user.role == "child"
    assert user.owner_value == "lea"  # casefolded


# ---------------------------------------------------------------------------
# Middleware gating
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dev_mode_is_open(client: AsyncClient):
    # No OIDC settings → everything acts as parent, no login.
    response = await client.get("/tags")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_anonymous_html_redirects_to_login(client: AsyncClient, oidc_on):
    response = await client.get("/")
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login"


@pytest.mark.asyncio
async def test_anonymous_api_gets_401(client: AsyncClient, oidc_on):
    response = await client.get("/api/v1/media")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_stays_open(client: AsyncClient, oidc_on):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_bearer_token_grants_machine_access(
    client: AsyncClient, db: AsyncSession, oidc_on, monkeypatch
):
    monkeypatch.setattr(settings, "api_token", "ha-token")
    await _create_media(db, title="Rock", owner="papa", uri="spotify://playlist/rock")

    response = await client.get(
        "/api/v1/media", headers={"Authorization": "Bearer ha-token"}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1

    bad = await client.get("/api/v1/media", headers={"Authorization": "Bearer wrong"})
    assert bad.status_code == 401


# ---------------------------------------------------------------------------
# Child scoping — reads
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_child_only_sees_own_media(client: AsyncClient, db: AsyncSession, oidc_on):
    _login_child(client, "lea")
    mine = await _create_media(db, title="Comptines", owner="Lea", uri="spotify://playlist/c")
    await _create_media(db, title="Rock", owner="papa", uri="spotify://playlist/r")

    response = await client.get("/api/v1/media")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == mine.id


@pytest.mark.asyncio
async def test_child_cannot_fetch_others_media(client: AsyncClient, db: AsyncSession, oidc_on):
    _login_child(client, "lea")
    other = await _create_media(db, title="Rock", owner="papa", uri="spotify://playlist/r")

    response = await client.get(f"/api/v1/media/{other.id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_child_select_cannot_reach_others(client: AsyncClient, db: AsyncSession, oidc_on):
    _login_child(client, "lea")
    await _create_media(db, title="Rock", owner="papa", uri="spotify://playlist/r")

    # Even asking explicitly for papa's media (with aggressive fallback) yields nothing.
    response = await client.get(
        "/api/v1/media/select?owner=papa&fallback=aggressive",
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_parent_sees_everything(client: AsyncClient, db: AsyncSession, oidc_on):
    _login_parent(client)
    await _create_media(db, title="Comptines", owner="lea", uri="spotify://playlist/c")
    await _create_media(db, title="Rock", owner="papa", uri="spotify://playlist/r")

    response = await client.get("/api/v1/media")
    assert response.status_code == 200
    assert response.json()["total"] == 2


# ---------------------------------------------------------------------------
# Child scoping — writes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_child_create_gets_owner_tag(client: AsyncClient, db: AsyncSession, oidc_on):
    _login_child(client, "lea")
    response = await client.post(
        "/api/v1/media",
        json={
            "title": "Mes chansons",
            "media_type": "playlist",
            "source_uri": "spotify://playlist/mine",
            "provider": "spotify",
        },
    )
    assert response.status_code == 201
    tags = response.json()["tags"]
    assert {"category": "owner", "value": "lea"} in [
        {"category": t["category"], "value": t["value"]} for t in tags
    ]


@pytest.mark.asyncio
async def test_child_update_keeps_owner_tag(client: AsyncClient, db: AsyncSession, oidc_on):
    _login_child(client, "lea")
    mine = await _create_media(db, title="Comptines", owner="lea", uri="spotify://playlist/c")

    # Try to strip every tag — the owner tag must be re-applied.
    response = await client.put(
        f"/api/v1/media/{mine.id}",
        json={"tag_ids": []},
    )
    assert response.status_code == 200
    tags = response.json()["tags"]
    assert [t for t in tags if t["category"] == "owner" and t["value"].lower() == "lea"]


@pytest.mark.asyncio
async def test_child_cannot_update_others_media(client: AsyncClient, db: AsyncSession, oidc_on):
    _login_child(client, "lea")
    other = await _create_media(db, title="Rock", owner="papa", uri="spotify://playlist/r")

    response = await client.put(
        f"/api/v1/media/{other.id}",
        json={"title": "Pwned"},
    )
    assert response.status_code == 404

    response = await client.delete(f"/api/v1/media/{other.id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_child_cannot_remove_own_owner_tag(client: AsyncClient, db: AsyncSession, oidc_on):
    _login_child(client, "lea")
    mine = await _create_media(db, title="Comptines", owner="lea", uri="spotify://playlist/c")
    owner_tag = next(t for t in mine.tags if t.category == "owner")

    response = await client.delete(
        f"/media/{mine.id}/tags/{owner_tag.id}"
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_child_cannot_manage_tags(client: AsyncClient, db: AsyncSession, oidc_on):
    _login_child(client, "lea")
    page = await client.get("/tags")
    assert page.status_code == 403

    api = await client.post(
        "/api/v1/tags",
        json={"category": "mood", "value": "calm"},
    )
    assert api.status_code == 403


@pytest.mark.asyncio
async def test_child_can_edit_own_media(client: AsyncClient, db: AsyncSession, oidc_on):
    _login_child(client, "lea")
    mine = await _create_media(db, title="Comptines", owner="lea", uri="spotify://playlist/c")

    response = await client.put(
        f"/api/v1/media/{mine.id}",
        json={"title": "Comptines 2"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Comptines 2"


# ---------------------------------------------------------------------------
# Accent-insensitive owner matching (username "zoe" ↔ tag "Zoé")
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_child_matches_accented_owner_tag(client: AsyncClient, db: AsyncSession, oidc_on):
    _login_child(client, "zoe")
    mine = await _create_media(db, title="Comptines", owner="Zoé", uri="spotify://playlist/c")
    await _create_media(db, title="Rock", owner="papa", uri="spotify://playlist/r")

    response = await client.get("/api/v1/media")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == mine.id


@pytest.mark.asyncio
async def test_child_create_reuses_accented_owner_tag(
    client: AsyncClient, db: AsyncSession, oidc_on
):
    _login_child(client, "zoe")
    await _create_media(db, title="Comptines", owner="Zoé", uri="spotify://playlist/c")

    response = await client.post(
        "/api/v1/media",
        json={
            "title": "Nouveau",
            "media_type": "playlist",
            "source_uri": "spotify://playlist/new",
            "provider": "spotify",
        },
    )
    assert response.status_code == 201
    owner_tags = [t["value"] for t in response.json()["tags"] if t["category"] == "owner"]
    # The existing accented tag is reused — no lowercase twin created.
    assert owner_tags == ["Zoé"]


# ---------------------------------------------------------------------------
# Group tags: a child also sees media shared through their IdP groups
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_child_sees_group_shared_media(client: AsyncClient, db: AsyncSession, oidc_on):
    _login_child(client, "Léo", groups=["enfants", "famille"])
    await _create_media(db, title="Le sien", owner="Léo", uri="spotify://playlist/t")
    await _create_media(db, title="Partagé", owner="famille", uri="spotify://playlist/f")
    await _create_media(db, title="Des petits", owner="enfants", uri="spotify://playlist/e")
    await _create_media(db, title="Rock papa", owner="papa", uri="spotify://playlist/p")

    response = await client.get("/api/v1/media")
    assert response.status_code == 200
    titles = {i["title"] for i in response.json()["items"]}
    assert titles == {"Le sien", "Partagé", "Des petits"}


@pytest.mark.asyncio
async def test_child_edits_group_shared_media_without_touching_ownership(
    client: AsyncClient, db: AsyncSession, oidc_on
):
    _login_child(client, "Léo", groups=["famille"])
    shared = await _create_media(db, title="Partagé", owner="famille", uri="spotify://playlist/f")

    # Editable directly (no need to duplicate it under their own tag)…
    response = await client.put(
        f"/api/v1/media/{shared.id}", json={"title": "Partagé 2", "tag_ids": []}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Partagé 2"
    # …but the owner tags are preserved as-is: famille kept, no own tag added.
    owners = sorted(t["value"] for t in body["tags"] if t["category"] == "owner")
    assert owners == ["famille"]

    # Soft delete allowed, hard delete stays parent-only.
    assert (await client.delete(f"/api/v1/media/{shared.id}?hard=true")).status_code == 403
    assert (await client.delete(f"/api/v1/media/{shared.id}")).status_code == 204


@pytest.mark.asyncio
async def test_child_cannot_hand_out_owner_tags(client: AsyncClient, db: AsyncSession, oidc_on):
    _login_child(client, "lea")
    mine = await _create_media(db, title="Comptines", owner="lea", uri="spotify://playlist/c")

    response = await client.post(
        f"/media/{mine.id}/tags", data={"category": "owner", "value": "famille"}
    )
    assert response.status_code == 403
