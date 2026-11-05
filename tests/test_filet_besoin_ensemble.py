"""Tests d'ensemble du filet (B-1, B-2), écrits depuis le besoin et non depuis le code.

Attendus littéraux. Music Assistant est toujours derrière un bouchon ; la base est jetable.
"""

from __future__ import annotations

import base64
import json
import tomllib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, get_db
from app.esp_app import esp_app
from app.main import app
from app.models import media as _m  # noqa: F401
from app.models import rfid as _r  # noqa: F401
from app.services.music_assistant import get_ma_client
from app.services.tag_service import seed_default_tags


class StubMA:
    connected = False
    _server_info = None


@pytest.fixture
async def client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'b.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        await seed_default_tags(s)
        await s.commit()

        async def _db():
            yield s

        app.dependency_overrides[get_db] = _db
        esp_app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_ma_client] = lambda: StubMA()
        esp_app.dependency_overrides[get_ma_client] = lambda: StubMA()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            yield ac
        app.dependency_overrides.clear()
        esp_app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
def oidc_on(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.test")
    monkeypatch.setattr(settings, "oidc_client_id", "music-library")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "https://ml.test/auth/callback")


def _login(c: AsyncClient, username: str, role: str) -> None:
    secret = next(m.kwargs["secret_key"] for m in app.user_middleware if m.cls is SessionMiddleware)
    user = {"username": username, "display_name": username, "role": role, "groups": []}
    payload = base64.b64encode(json.dumps({"user": user}).encode())
    c.cookies.set("session", TimestampSigner(str(secret)).sign(payload).decode())


def _new(title: str, owner: str | None = None) -> dict:
    body = {"title": title, "media_type": "playlist", "source_uri": f"spotify://x/{title}",
            "provider": "spotify"}
    if owner:
        body["tags_inline"] = [{"category": "owner", "value": owner}]
    return body


async def test_health_dit_ok_et_la_version_du_paquet(client):
    version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "app": "Music Library", "version": version}


async def test_creation_puis_lecture_d_un_media_formes_de_reponse(client):
    r = await client.post("/api/v1/media", json=_new("Contes"))
    assert r.status_code == 201
    mid = r.json()["id"]
    assert r.json()["title"] == "Contes"
    got = await client.get(f"/api/v1/media/{mid}")
    assert got.status_code == 200 and got.json()["title"] == "Contes"
    lst = (await client.get("/api/v1/media")).json()
    assert set(lst) == {"items", "total", "page", "page_size", "pages"}
    assert lst["total"] == 1


async def test_media_inconnu_donne_404_et_titre_absent_donne_422(client):
    assert (await client.get("/api/v1/media/999999")).status_code == 404
    bad = _new("x")
    del bad["title"]
    assert (await client.post("/api/v1/media", json=bad)).status_code == 422


async def test_un_enfant_ne_voit_que_ses_fiches_et_le_total_ne_trahit_pas_les_autres(client, oidc_on):
    _login(client, "papa", "parent")
    mine = (await client.post("/api/v1/media", json=_new("A moi", "Zoé"))).json()["id"]
    other = (await client.post("/api/v1/media", json=_new("A papa", "papa"))).json()["id"]
    _login(client, "zoe", "child")
    lst = (await client.get("/api/v1/media")).json()
    assert [i["title"] for i in lst["items"]] == ["A moi"]
    assert lst["total"] == 1
    assert (await client.get(f"/api/v1/media/{mine}")).status_code == 200
    assert (await client.get(f"/api/v1/media/{other}")).status_code == 404


async def test_un_enfant_ne_peut_pas_gerer_les_tags_rfid(client, oidc_on):
    _login(client, "zoe", "child")
    r = await client.put("/api/v1/rfid/04-A1-B2-C3", json={"uid": "04-A1-B2-C3", "name": "x"})
    assert r.status_code in (403, 422)
    assert r.status_code != 200


async def test_sans_session_l_api_refuse_quand_l_auth_est_active(client, oidc_on):
    assert (await client.get("/api/v1/media")).status_code == 401
    assert (await client.get("/api/v1/health")).status_code == 200


async def test_rfid_cree_puis_liste(client):
    r = await client.put("/api/v1/rfid/04-A1-B2-C3", json={"uid": "04-A1-B2-C3", "name": "Carte bleue"})
    assert r.status_code == 200
    assert r.json()["uid"] == "04-A1-B2-C3" and r.json()["name"] == "Carte bleue"
    assert r.json()["media_id"] is None
    lst = (await client.get("/api/v1/rfid")).json()
    assert [t["uid"] for t in lst] == ["04-A1-B2-C3"]


async def test_api_esp_expose_la_sante_et_ferme_l_import_et_le_rfid(client):
    async with AsyncClient(transport=ASGITransport(app=esp_app), base_url="http://e") as e:
        assert (await e.get("/api/v1/health")).status_code == 200
        assert (await e.post("/api/v1/ma/import", json={})).status_code == 404
        assert (await e.get("/api/v1/rfid")).status_code == 404
        assert (await e.get("/api/v1/media")).status_code == 404


async def test_page_inconnue_404_et_accueil_repond(client):
    assert (await client.get("/page-qui-n-existe-pas")).status_code == 404
    r = await client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]

