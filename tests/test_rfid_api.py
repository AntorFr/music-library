"""``/api/v1/rfid``: list, create/rename, resolve by UID — and who may write.

Pins what v0.26.0 answers (AD-filet-1). The service is covered by test_rfid.py;
here only the HTTP contract is pinned, through the real ``app.main.app``.
"""

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
from app.services import media_service, rfid_service
from app.services.tag_service import seed_default_tags

UID_A = "04-70-D7-DA"
UID_B = "04-75-D7-DA"


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


@pytest.fixture
def oidc_on(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.test")
    monkeypatch.setattr(settings, "oidc_client_id", "music-library")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "https://ml.test/auth/callback")


def _login(client: AsyncClient, role: str) -> None:
    from itsdangerous import TimestampSigner

    secret = next(
        m.kwargs["secret_key"] for m in app.user_middleware if m.cls is SessionMiddleware
    )
    user = {"username": "lea", "display_name": "Lea", "role": role, "groups": []}
    payload = base64.b64encode(json.dumps({"user": user}).encode())
    client.cookies.set("session", TimestampSigner(str(secret)).sign(payload).decode())


async def _media(db, title="Laylo", uri="spotify://track/1"):
    item, _ = await media_service.create_media(
        db,
        MediaCreate(
            title=title, media_type=MediaType.track, source_uri=uri, provider="spotify",
            cover_url=None, duration_min=None, description=None, metadata_extra=None,
            tag_ids=[], tags_inline=[],
        ),
    )
    await db.commit()
    return item


# --- List ------------------------------------------------------------------

async def test_list_is_empty_on_a_fresh_base(client):
    r = await client.get("/api/v1/rfid")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_is_sorted_by_uid_and_carries_the_media_title(client, db):
    item = await _media(db)
    await rfid_service.upsert_rfid_tag(db, uid=UID_B, name="Carte B")
    await rfid_service.upsert_rfid_tag(db, uid=UID_A, name="Carte A")
    await db.commit()
    await rfid_service.assign_rfid_tags_to_media(db, media_id=item.id, uids=[UID_B])
    await db.commit()

    r = await client.get("/api/v1/rfid")
    assert r.status_code == 200
    assert r.json() == [
        {"uid": UID_A, "name": "Carte A", "media_id": None, "media_title": None},
        {"uid": UID_B, "name": "Carte B", "media_id": item.id, "media_title": "Laylo"},
    ]


async def test_list_filters_on_assigned(client, db):
    item = await _media(db)
    await rfid_service.upsert_rfid_tag(db, uid=UID_A, name="Carte A")
    await rfid_service.upsert_rfid_tag(db, uid=UID_B, name="Carte B")
    await db.commit()
    await rfid_service.assign_rfid_tags_to_media(db, media_id=item.id, uids=[UID_A])
    await db.commit()

    only_assigned = (await client.get("/api/v1/rfid", params={"assigned": "true"})).json()
    only_free = (await client.get("/api/v1/rfid", params={"assigned": "false"})).json()
    assert [t["uid"] for t in only_assigned] == [UID_A]
    assert [t["uid"] for t in only_free] == [UID_B]


async def test_list_rejects_a_non_boolean_filter(client):
    r = await client.get("/api/v1/rfid", params={"assigned": "maybe"})
    assert r.status_code == 422


# --- Create / rename ---------------------------------------------------------

async def test_put_creates_an_unassigned_tag(client, db):
    r = await client.put(f"/api/v1/rfid/{UID_A}", json={"name": "Carte A"})
    assert r.status_code == 200
    assert r.json() == {"uid": UID_A, "name": "Carte A", "media_id": None, "media_title": None}

    listed = (await client.get("/api/v1/rfid")).json()
    assert [(t["uid"], t["name"]) for t in listed] == [(UID_A, "Carte A")]


async def test_put_renames_and_keeps_the_association(client, db):
    item = await _media(db)
    await rfid_service.upsert_rfid_tag(db, uid=UID_A, name="Carte A")
    await db.commit()
    await rfid_service.assign_rfid_tags_to_media(db, media_id=item.id, uids=[UID_A])
    await db.commit()

    r = await client.put(f"/api/v1/rfid/{UID_A}", json={"name": "Renommée"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Renommée"
    assert body["media_id"] == item.id
    assert body["media_title"] == "Laylo"
    assert len((await client.get("/api/v1/rfid")).json()) == 1


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": "x" * 121}])
async def test_put_validates_the_name(client, payload):
    r = await client.put(f"/api/v1/rfid/{UID_A}", json=payload)
    assert r.status_code == 422
    assert (await client.get("/api/v1/rfid")).json() == []


async def test_put_with_a_malformed_uid_answers_500_and_stores_nothing(client, db):
    """The UID pattern is only checked on the *response* model: the request is
    accepted, the response fails validation, nothing is committed (doubtful)."""
    r = await client.put("/api/v1/rfid/not-a-uid", json={"name": "Carte"})
    assert r.status_code == 500
    await db.rollback()  # the test's shared session stands in for get_db's rollback
    assert await rfid_service.get_rfid_tag(db, "not-a-uid") is None


# --- Resolve -----------------------------------------------------------------

async def test_resolve_returns_the_media_behind_the_uid(client, db):
    item = await _media(db, uri="spotify://track/42")
    await rfid_service.upsert_rfid_tag(db, uid=UID_A, name="Carte A")
    await db.commit()
    await rfid_service.assign_rfid_tags_to_media(db, media_id=item.id, uids=[UID_A])
    await db.commit()

    r = await client.get(f"/api/v1/rfid/{UID_A}/media")
    assert r.status_code == 200
    assert r.json() == {
        "uid": UID_A,
        "media_id": item.id,
        "title": "Laylo",
        "source_uri": "spotify://track/42",
        "provider": "spotify",
        "cover_url_resolved": f"http://test/covers/{item.id}.jpg",
    }


async def test_resolve_unknown_uid_is_404(client):
    r = await client.get(f"/api/v1/rfid/{UID_A}/media")
    assert r.status_code == 404
    assert r.json() == {"detail": "Tag RFID introuvable ou non associé"}


async def test_resolve_known_but_unassigned_uid_is_404_too(client, db):
    await rfid_service.upsert_rfid_tag(db, uid=UID_A, name="Carte A")
    await db.commit()
    r = await client.get(f"/api/v1/rfid/{UID_A}/media")
    assert r.status_code == 404
    assert r.json() == {"detail": "Tag RFID introuvable ou non associé"}


# --- Permissions -------------------------------------------------------------

async def test_a_child_cannot_create_a_tag(client, db, oidc_on):
    _login(client, "child")
    r = await client.put(f"/api/v1/rfid/{UID_A}", json={"name": "Carte A"})
    assert r.status_code == 403
    assert r.json() == {"detail": "Réservé aux parents"}
    assert await rfid_service.get_rfid_tag(db, UID_A) is None


async def test_a_parent_session_can_create_a_tag(client, db, oidc_on):
    _login(client, "parent")
    r = await client.put(f"/api/v1/rfid/{UID_A}", json={"name": "Carte A"})
    assert r.status_code == 200
    assert (await rfid_service.get_rfid_tag(db, UID_A)).name == "Carte A"


async def test_the_bearer_token_can_write(client, db, oidc_on, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "s3cret")
    r = await client.put(
        f"/api/v1/rfid/{UID_A}", json={"name": "Carte A"},
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 200


async def test_anonymous_callers_get_401_once_oidc_is_on(client, oidc_on):
    for method, path in [("GET", "/api/v1/rfid"), ("GET", f"/api/v1/rfid/{UID_A}/media")]:
        r = await client.request(method, path)
        assert r.status_code == 401
        assert r.json() == {"detail": "Not authenticated"}
    r = await client.put(f"/api/v1/rfid/{UID_A}", json={"name": "x"})
    assert r.status_code == 401


async def test_a_child_can_still_read_and_resolve(client, db, oidc_on):
    """List and resolve carry no permission check (doubtful for a child scope)."""
    item = await _media(db)
    await rfid_service.upsert_rfid_tag(db, uid=UID_A, name="Carte A")
    await db.commit()
    await rfid_service.assign_rfid_tags_to_media(db, media_id=item.id, uids=[UID_A])
    await db.commit()
    _login(client, "child")

    assert (await client.get("/api/v1/rfid")).status_code == 200
    assert (await client.get(f"/api/v1/rfid/{UID_A}/media")).status_code == 200
