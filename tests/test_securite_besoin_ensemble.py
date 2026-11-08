"""Tests d'ensemble de la relecture de securite (B-4, AD-6), ecrits depuis le besoin.

Attendus litteraux. Music Assistant est derriere un bouchon ; la base est jetable ; l'API est
appelee par HTTP, comme le fait un navigateur, un lecteur RFID ou Home Assistant.
"""

from __future__ import annotations

import base64
import json
import re
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

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "docs" / "quality" / "security-review.md"
UID_ZOE = "04-A1-B2-C3"
UID_PAPA = "04-D4-E5-F6"
UID_FREE = "04-00-00-01"


class FailingMA:
    """Music Assistant injoignable."""

    connected = False
    _server_info = None


@pytest.fixture
async def client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's.db'}")
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
        app.dependency_overrides[get_ma_client] = lambda: FailingMA()
        esp_app.dependency_overrides[get_ma_client] = lambda: FailingMA()
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


def _new(title: str, owner: str | None = None, media_type: str = "playlist",
         source_uri: str | None = None) -> dict:
    body = {"title": title, "media_type": media_type,
            "source_uri": source_uri or f"spotify://x/{title}", "provider": "spotify"}
    if owner:
        body["tags_inline"] = [{"category": "owner", "value": owner}]
    return body


async def _world(client) -> dict:
    """Un parent cree : une fiche de Zoe, une fiche de papa, deux cartes assignees, une libre."""
    _login(client, "papa", "parent")
    zoe = (await client.post("/api/v1/media", json=_new("Pour Zoe", "Zoé"))).json()["id"]
    papa = (await client.post("/api/v1/media", json=_new("Secret de papa", "papa"))).json()["id"]
    for uid in (UID_ZOE, UID_PAPA, UID_FREE):
        assert (await client.put(f"/api/v1/rfid/{uid}", json={"uid": uid, "name": uid})).status_code == 200
    for mid, uid in ((zoe, UID_ZOE), (papa, UID_PAPA)):
        r = await client.post(f"/media/{mid}/rfid", data={"rfid_uids": uid})
        assert r.status_code < 400, r.text
    return {"zoe": zoe, "papa": papa}


# ---- Critique 1 : un enfant lit le media d'un autre par les routes RFID (S-1) -------------


async def test_enfant_liste_rfid_sans_la_carte_du_media_d_un_autre(client, oidc_on):
    await _world(client)
    _login(client, "zoe", "child")
    r = await client.get("/api/v1/rfid")
    assert r.status_code == 200
    uids = sorted(t["uid"] for t in r.json())
    assert uids == [UID_FREE, UID_ZOE]
    assert "Secret de papa" not in r.text


async def test_enfant_resout_sa_carte_et_ne_resout_pas_celle_d_un_autre(client, oidc_on):
    await _world(client)
    _login(client, "zoe", "child")
    mine = await client.get(f"/api/v1/rfid/{UID_ZOE}/media")
    assert mine.status_code == 200 and mine.json()["title"] == "Pour Zoe"
    other = await client.get(f"/api/v1/rfid/{UID_PAPA}/media")
    assert other.status_code == 404
    assert "Secret de papa" not in other.text and "spotify://x/Secret" not in other.text


async def test_enfant_a_la_meme_reponse_pour_carte_d_autrui_et_carte_inconnue(client, oidc_on):
    await _world(client)
    _login(client, "zoe", "child")
    hidden = await client.get(f"/api/v1/rfid/{UID_PAPA}/media")
    unknown = await client.get("/api/v1/rfid/04-FF-FF-FF/media")
    assert (hidden.status_code, hidden.json()) == (unknown.status_code, unknown.json())


async def test_parent_voit_toutes_les_cartes_et_resout_celle_de_l_enfant(client, oidc_on):
    await _world(client)
    _login(client, "papa", "parent")
    assert sorted(t["uid"] for t in (await client.get("/api/v1/rfid")).json()) == sorted(
        [UID_FREE, UID_PAPA, UID_ZOE])
    assert (await client.get(f"/api/v1/rfid/{UID_ZOE}/media")).json()["title"] == "Pour Zoe"


async def test_jeton_machine_voit_toutes_les_cartes(client, oidc_on, monkeypatch):
    await _world(client)
    client.cookies.clear()
    monkeypatch.setattr(settings, "api_token", "ha-token")
    h = {"Authorization": "Bearer ha-token"}
    r = await client.get("/api/v1/rfid", headers=h)
    assert r.status_code == 200 and len(r.json()) == 3
    assert (await client.get(f"/api/v1/rfid/{UID_PAPA}/media", headers=h)).status_code == 200


async def test_sans_session_les_routes_rfid_refusent(client, oidc_on):
    await _world(client)
    client.cookies.clear()
    assert (await client.get("/api/v1/rfid")).status_code == 401
    assert (await client.get(f"/api/v1/rfid/{UID_ZOE}/media")).status_code == 401


# ---- Critique 2 : acces sans session ; enfant ecrit le media d'un autre -------------------


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/media"), ("POST", "/api/v1/media"), ("GET", "/api/v1/tags"),
    ("GET", "/api/v1/ma/players"), ("GET", "/media"), ("GET", "/settings"),
])
async def test_sans_session_rien_ne_repond_hors_exemptions(client, oidc_on, method, path):
    r = await client.request(method, path, follow_redirects=False)
    assert r.status_code in (401, 302, 307), (path, r.status_code)


async def test_enfant_ne_modifie_ni_ne_supprime_le_media_d_un_autre(client, oidc_on):
    w = await _world(client)
    _login(client, "zoe", "child")
    put = await client.put(f"/api/v1/media/{w['papa']}", json={"title": "Pirate"})
    assert put.status_code == 404
    assert (await client.delete(f"/api/v1/media/{w['papa']}")).status_code == 404
    assert (await client.delete(f"/api/v1/media/{w['papa']}?hard=true")).status_code in (403, 404)
    _login(client, "papa", "parent")
    assert (await client.get(f"/api/v1/media/{w['papa']}")).json()["title"] == "Secret de papa"


async def test_enfant_ne_prend_pas_le_role_parent_en_retirant_un_tag_owner(client, oidc_on):
    w = await _world(client)
    _login(client, "zoe", "child")
    r = await client.put(f"/api/v1/media/{w['zoe']}", json={"title": "Renomme", "tags_inline": []})
    assert r.status_code == 200
    tags = [t["value"] for t in (await client.get(f"/api/v1/media/{w['zoe']}")).json()["tags"]]
    assert "Zoé" in tags


# ---- Critique 3 : identifiant Spotify ------------------------------------------------------


async def test_enfant_ne_peut_ni_lire_ni_changer_le_compte_spotify(client, oidc_on):
    w = await _world(client)
    _login(client, "zoe", "child")
    assert (await client.get(f"/media/{w['zoe']}/spotify-account")).status_code == 403
    r = await client.post(f"/media/{w['zoe']}/spotify-account", data={"account": "spotify--abc"})
    assert r.status_code == 403
    assert (await client.get(f"/media/{w['papa']}/spotify-account")).status_code in (403, 404)


async def test_la_fiche_ne_rend_aucun_secret_de_configuration(client, oidc_on, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "tok-confidentiel")
    monkeypatch.setattr(settings, "session_secret", "sess-confidentiel")
    w = await _world(client)
    for path in ("/api/v1/media", f"/api/v1/media/{w['zoe']}", "/api/v1/rfid", "/",
                 f"/media/{w['zoe']}"):
        text = (await client.get(path)).text
        for secret in ("tok-confidentiel", "sess-confidentiel", "secret"):
            assert secret not in text.replace("Secret de papa", ""), (path, secret)


# ---- Corriges sans changement de comportement (S-2, S-12) ---------------------------------


async def test_bearer_non_ascii_donne_401_et_non_500(client, oidc_on, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "ha-token")
    r = await client.get("/api/v1/media", headers={"Authorization": "Bearer hé-token".encode()})
    assert r.status_code == 401
    ok = await client.get("/api/v1/media", headers={"Authorization": "Bearer ha-token"})
    assert ok.status_code == 200


async def test_signature_miniature_non_ascii_donne_403_et_non_500(client):
    r = await client.get("/api/v1/quick/thumb?src=http://x/y.jpg&size=96&sig=%C3%A9")
    assert r.status_code == 403
    async with AsyncClient(transport=ASGITransport(app=esp_app), base_url="http://e") as e:
        assert (await e.get("/api/v1/quick/thumb?src=http://x/y.jpg&size=96&sig=%C3%A9")).status_code == 403


# ---- Critique 4 : script d'un enfant dans le navigateur d'un parent (S-13) ----------------

EVIL = "a');alert(1);//"


class _Item:
    uri = ""
    resume_position_ms = None
    fully_played = None
    duration = 0
    chapters = [{"name": "Chap 1", "start": 0, "position": 1}]


class _ChaptersMA:
    async def get_item(self, *a, **k):
        return _Item()

    async def get_item_by_uri(self, *a, **k):
        return _Item()


async def test_chapitres_source_uri_a_guillemet_n_ouvre_pas_de_script(client, oidc_on, monkeypatch):
    import app.services.music_assistant as ma_mod

    async def _get():
        return _ChaptersMA()

    monkeypatch.setattr(ma_mod, "get_ma_client", _get)
    _login(client, "zoe", "child")
    mid = (await client.post("/api/v1/media", json=_new(
        "Livre", "Zoé", media_type="audiobook", source_uri=EVIL))).json()["id"]
    _login(client, "papa", "parent")
    r = await client.get(f"/media/{mid}/chapters")
    assert r.status_code == 200
    assert "Chap 1" in r.text
    assert "alert(1)" not in re.sub(r'data-uri="[^"]*"', "", r.text)
    assert "playChapter('a" not in r.text


async def test_toast_n_interprete_pas_le_html(client, oidc_on):
    _login(client, "papa", "parent")
    page = (await client.get("/")).text
    assert "toast.innerHTML" not in page


async def test_detail_ne_met_pas_source_uri_entre_apostrophes_js(client, oidc_on):
    _login(client, "zoe", "child")
    mid = (await client.post("/api/v1/media", json=_new("Piege", "Zoé", source_uri=EVIL))).json()["id"]
    text = (await client.get(f"/media/{mid}")).text
    assert "const uri = 'a" not in text


# ---- Le rapport -----------------------------------------------------------------------------


def _report() -> str:
    assert REPORT.is_file(), "docs/quality/security-review.md absent"
    return REPORT.read_text()


@pytest.mark.parametrize("menace", [
    r"owner|account", r"spotify", r"esp|rfid", r"upload|cover|template", r"music assistant", r"log",
])
def test_le_rapport_couvre_chaque_menace_listee(menace):
    text = _report().lower()
    rows = [ln for ln in text.splitlines() if ln.startswith("## ") and "row" in ln]
    assert any(re.search(menace, ln) for ln in rows), (menace, rows)


def test_chaque_constat_porte_une_classe():
    findings = re.findall(r"^\*\*(S-\d+) — ([^—]+?) —", _report(), re.M)
    assert len(findings) >= 10
    assert {c for _, c in findings} <= {"critical", "recommendation", "fixed"}
    ids = [i for i, _ in findings]
    assert len(set(ids)) == len(ids)


def test_chaque_critique_porte_la_reponse_du_proprietaire_et_son_etat():
    text = _report()
    blocs = re.split(r"(?m)^(?=\*\*S-\d+ — )", text)
    critiques = [b for b in blocs if re.match(r"\*\*S-\d+ — critical", b)]
    assert len(critiques) >= 1
    for b in critiques:
        assert "Owner's answer" in b, b[:60]
        assert "**Applied:**" in b, b[:60]


def test_le_rapport_ne_contient_aucun_secret_ni_uid_reel():
    text = _report()
    assert not re.search(r"\b04-[0-9A-F]{2}-[0-9A-F]{2}-[0-9A-F]{2}\b", text)
    assert not re.search(r"Bearer [A-Za-z0-9_\-]{16,}", text)
    assert not re.search(r"spotify--[0-9a-f]{8,}", text)


# ---- P-3 : aucune version changee ------------------------------------------------------------


def test_version_inchangee_0_27_0_dans_les_deux_emplacements():
    assert tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"] == "0.27.0"
    assert settings.app_version == "0.27.0"
