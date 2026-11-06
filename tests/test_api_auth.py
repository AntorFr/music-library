"""``/auth`` routes (OIDC login/callback/logout) behind a stub IdP client, and what the
session they open then allows through the API."""

from __future__ import annotations

import pytest
from fastapi.responses import RedirectResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import auth as auth_routes
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import media as _media_models  # noqa: F401
from app.models import rfid as _rfid_models  # noqa: F401
from app.services.tag_service import seed_default_tags


class StubIdP:
    """Stands for the authlib client: no discovery, no network."""

    def __init__(self, token=None, userinfo=None, error=None):
        self.token = token if token is not None else {"userinfo": {}}
        self._userinfo = userinfo or {}
        self.error = error
        self.userinfo_calls = 0

    async def authorize_redirect(self, request, redirect_uri):
        return RedirectResponse(f"https://idp.test/authorize?redirect_uri={redirect_uri}", status_code=302)

    async def authorize_access_token(self, request):
        if self.error:
            raise self.error
        return self.token

    async def userinfo(self, token):
        self.userinfo_calls += 1
        return self._userinfo


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


@pytest.fixture
def oidc_on(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.test")
    monkeypatch.setattr(settings, "oidc_client_id", "music-library")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "https://ml.test/auth/callback")
    monkeypatch.setattr(settings, "oidc_admin_group", "admins")


def _idp(monkeypatch, idp: StubIdP) -> StubIdP:
    monkeypatch.setattr(auth_routes, "get_oidc_client", lambda: idp)
    return idp


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/auth/login", "/auth/callback"])
async def test_without_oidc_login_and_callback_bounce_to_home(client, path):
    r = await client.get(path)
    assert r.status_code == 303
    assert r.headers["location"] == "/"


@pytest.mark.asyncio
async def test_logout_always_redirects_home(client):
    r = await client.get("/auth/logout")
    assert r.status_code == 303
    assert r.headers["location"] == "/"


@pytest.mark.asyncio
async def test_login_hands_over_to_the_idp_with_the_configured_redirect_uri(
    client, oidc_on, monkeypatch
):
    _idp(monkeypatch, StubIdP())
    r = await client.get("/auth/login")
    assert r.status_code == 302
    assert r.headers["location"] == "https://idp.test/authorize?redirect_uri=https://ml.test/auth/callback"


@pytest.mark.asyncio
async def test_callback_with_oauth_error_is_401_naming_the_error(client, oidc_on, monkeypatch):
    from authlib.integrations.base_client.errors import OAuthError

    _idp(monkeypatch, StubIdP(error=OAuthError(error="invalid_grant", description="expired")))
    r = await client.get("/auth/callback")
    assert r.status_code == 401
    assert r.json() == {"detail": "Authentication failed: invalid_grant"}


@pytest.mark.asyncio
async def test_callback_without_username_claim_is_401(client, oidc_on, monkeypatch):
    _idp(monkeypatch, StubIdP(token={"userinfo": {"groups": ["x"]}}))
    r = await client.get("/auth/callback")
    assert r.status_code == 401
    assert r.json() == {"detail": "Authentication failed: no username claim"}


@pytest.mark.asyncio
async def test_callback_opens_a_child_session_that_scopes_the_api(client, oidc_on, monkeypatch):
    _idp(monkeypatch, StubIdP(token={"userinfo": {
        "preferred_username": "lea", "name": "Léa", "groups": ["enfants"]}}))
    r = await client.get("/auth/callback")
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert "session" in r.cookies or "session" in client.cookies

    # the session is live: the API answers (not 401) but tag management is refused
    assert (await client.get("/api/v1/media")).status_code == 200
    denied = await client.post("/api/v1/tags", json={"category": "mood", "value": "x"})
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Réservé aux parents"}


@pytest.mark.asyncio
async def test_callback_admin_group_opens_a_parent_session(client, oidc_on, monkeypatch):
    _idp(monkeypatch, StubIdP(token={"userinfo": {
        "preferred_username": "papa", "groups": ["admins"]}}))
    assert (await client.get("/auth/callback")).status_code == 303
    ok = await client.post("/api/v1/tags", json={"category": "mood", "value": "x"})
    assert ok.status_code == 201


@pytest.mark.asyncio
async def test_callback_falls_back_to_userinfo_endpoint_when_groups_are_missing(
    client, oidc_on, monkeypatch
):
    idp = _idp(monkeypatch, StubIdP(
        token={"userinfo": {"preferred_username": "papa"}},
        userinfo={"preferred_username": "papa", "groups": ["admins"]},
    ))
    assert (await client.get("/auth/callback")).status_code == 303
    assert idp.userinfo_calls == 1
    assert (await client.post("/api/v1/tags", json={"category": "mood", "value": "y"})).status_code == 201


@pytest.mark.asyncio
async def test_logout_drops_the_session(client, oidc_on, monkeypatch):
    _idp(monkeypatch, StubIdP(token={"userinfo": {
        "preferred_username": "papa", "groups": ["admins"]}}))
    await client.get("/auth/callback")
    assert (await client.get("/api/v1/media")).status_code == 200
    assert (await client.get("/auth/logout")).status_code == 303
    assert (await client.get("/api/v1/media")).status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_api_401_body_and_html_redirect(client, oidc_on):
    r = await client.get("/api/v1/tags")
    assert r.status_code == 401
    assert r.json() == {"detail": "Not authenticated"}
    page = await client.get("/")
    assert page.status_code == 302
    assert page.headers["location"] == "/auth/login"
