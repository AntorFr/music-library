"""``/api/v1/health`` and ``/api/v1/health/ma``: the probe's keys and its auth exemption.

Pins what v0.26.0 answers. Music Assistant is always a stub (AD-filet-1).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from app.services.music_assistant import get_ma_client


class StubMA:
    """Just what ``health_ma`` reads from the client."""

    def __init__(self, connected: bool, server_info: dict | None = None):
        self.connected = connected
        self._server_info = server_info


@pytest.fixture
def stub_ma():
    holder = {"ma": StubMA(False)}
    app.dependency_overrides[get_ma_client] = lambda: holder["ma"]
    yield holder
    app.dependency_overrides.clear()


@pytest.fixture
async def client(stub_ma):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def oidc_on(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.test")
    monkeypatch.setattr(settings, "oidc_client_id", "music-library")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "https://ml.test/auth/callback")


async def test_health_answers_status_app_and_version(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
    }


async def test_health_has_no_unprefixed_alias(client):
    """The probe lives under /api/v1 only; the bare path is not routed."""
    r = await client.get("/health")
    assert r.status_code == 404


async def test_health_ma_disconnected(client, stub_ma):
    stub_ma["ma"] = StubMA(False)
    r = await client.get("/api/v1/health/ma")
    assert r.status_code == 200
    assert r.json() == {
        "status": "disconnected",
        "music_assistant_url": settings.music_assistant_url,
        "server_version": None,
        "schema_version": None,
    }


async def test_health_ma_connected_reports_server_info(client, stub_ma):
    stub_ma["ma"] = StubMA(True, {"server_version": "2.7.1", "schema_version": 28})
    r = await client.get("/api/v1/health/ma")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "music_assistant_url": settings.music_assistant_url,
        "server_version": "2.7.1",
        "schema_version": 28,
    }


async def test_health_ma_connected_without_those_keys_gives_none(client, stub_ma):
    stub_ma["ma"] = StubMA(True, {})
    body = (await client.get("/api/v1/health/ma")).json()
    assert body["status"] == "ok"
    assert body["server_version"] is None
    assert body["schema_version"] is None


async def test_health_is_open_when_auth_is_enforced(client, oidc_on):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_health_ma_requires_authentication(client, oidc_on):
    """Only /api/v1/health is exempt: the MA probe answers 401 JSON without a session."""
    r = await client.get("/api/v1/health/ma")
    assert r.status_code == 401
    assert r.json() == {"detail": "Not authenticated"}
