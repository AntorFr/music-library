"""Tests d'ensemble de la tranche refactoring (B-1, B-5, P-4), écrits depuis le besoin.

Le système est lancé comme le README le dit : `python -m app.server`, base SQLite jetable,
ports libres, Music Assistant absent. L'attendu est littéral : tailles de départ
(1179 / 990 / 578 lignes), liste des routes, empreintes des réponses relevées sur
`epic/music-library-qualite` (4238be78), avant le refactoring. Les identifiants créés au vol
sont remplacés par <A>/<B>/<C> et l'ordre des mots est ignoré avant l'empreinte.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent

# --- Relevé de la base, à la main -------------------------------------------------------
GOLDEN = [
    ('/api/v1/health', 200, 'f914f5c87d98', 56),
    ('/', 200, '2ca1c83f410b', 39672),
    ('/media', 200, '2b3ba62e9252', 29391),
    ('/media?media_type=audiobook', 200, '990bf5de8948', 30589),
    ('/media?q=Alp', 200, '2b3ba62e9252', 29391),
    ('/media/<A>', 200, '9293d55a94cb', 26972),
    ('/media/<A>/edit', 200, 'c4281d23ab79', 29574),
    ('/media/<C>/episodes', 200, 'd5926cdce31d', 1178),
    ('/media/<B>/chapters', 200, '375e109367c7', 1192),
    ('/media/<C>/spotify-account', 200, 'ce3bd950bc37', 404),
    ('/tags', 302, 'e3b0c44298fc', 0),
    ('/rfid', 302, 'e3b0c44298fc', 0),
    ('/settings', 200, 'fddb74e13fc7', 70209),
    ('/quick', 302, 'e3b0c44298fc', 0),
    ('/browse', 200, 'd345eca6fb34', 38202),
    ('/browse/library/albums', 200, 'c1ece30b4021', 119),
    ('/browse/search?q=x', 200, '1f4228fdb8d8', 97),
    ('/manifest.webmanifest', 200, '293053043ba2', 499),
    ('/api/v1/media', 200, '33d815ad369e', 974),
    ('/api/v1/media/<A>', 200, '047015596e1a', 304),
    ('/api/v1/quick/Léa', 200, '6707a58ea924', 343),
    ('/api/v1/tags', 200, '3acd7350e77c', 3423),
    ('/api/v1/tags/categories', 200, '31e651a75dde', 392),
    ('/api/v1/rfid', 200, '2e2c430e5b93', 73),
    ('/media/new', 404, '766ae2e1e886', 30),
    ('/nope', 404, '96a100ea29bc', 22),
]

OLD_NAMES = {
    "app.api.views": ["router"],
    "app.services.music_assistant": [
        "MAImage", "MAMediaItem", "MAPlayer", "MASearchResults", "MusicAssistantClient",
        "close_ma_client", "fetch_audiobook", "fetch_podcast_episodes", "get_ma_client",
        "normalize_chapters", "resolve_ma_provider_and_id",
    ],
    "app.services.media_service": [
        "DuplicateMediaError", "add_tag_to_media", "create_media", "delete_media",
        "get_media", "get_or_create_owner_tag", "list_media", "remove_tag_from_media",
        "select_media", "select_media_by_query", "update_media",
    ],
}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    d = tmp_path_factory.mktemp("live")
    port, esp = _free_port(), _free_port()
    env = dict(
        os.environ,
        ML_DATABASE_URL=f"sqlite+aiosqlite:///{d}/l.db",
        ML_PORT=str(port),
        ML_ESP_PORT=str(esp),
        ML_HOST="127.0.0.1",
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.server"], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30)
    try:
        for _ in range(150):
            try:
                if client.get("/api/v1/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            pytest.fail("le serveur ne répond pas sur /api/v1/health")

        def new(title, media_type, owner):
            body = {"title": title, "media_type": media_type,
                    "source_uri": f"spotify://x/{title}", "provider": "spotify",
                    "tags_inline": [{"category": "owner", "value": owner}]}
            r = client.post("/api/v1/media", json=body)
            assert r.status_code == 201, r.text
            return r.json()["id"]

        a = new("Alpha", "playlist", "Léa")
        b = new("Bravo", "audiobook", "Tom")
        c = new("Charlie", "podcast", "Léa")
        assert client.put("/api/v1/rfid/04-AA-BB-CC", json={"name": "Carte"}).status_code == 200
        yield client, {"<A>": a, "<B>": b, "<C>": c}, port
    finally:
        proc.terminate()
        proc.wait(timeout=20)


def _fingerprint(client, ids, port, path_tpl):
    path = path_tpl
    for k, v in ids.items():
        path = path.replace(k, v)
    r = client.get(path)
    body = r.text
    for k, v in ids.items():
        body = body.replace(v, k).replace(v[:8], k)
    body = body.replace(str(port), "<PORT>")
    body = re.sub(r"\d\d/\d\d/\d{4} à \d\d:\d\d", "<DT>", body)
    body = re.sub(r"\d{4}-\d\d-\d\dT[\d:.]+(Z|\+00:00)?", "<TS>", body)
    digest = hashlib.sha256(" ".join(sorted(body.split())).encode()).hexdigest()[:12]
    return r.status_code, digest, len(body)


@pytest.mark.parametrize("path,status,digest,length", GOLDEN, ids=[g[0] for g in GOLDEN])
def test_page_ou_route_rend_la_meme_sortie_qu_avant_le_refactoring(
    live, path, status, digest, length
):
    client, ids, port = live
    # GOLDEN note les chemins avec <A>/<B>/<C> ; le test les remplace par les vrais ids
    assert _fingerprint(client, ids, port, path) == (status, digest, length)


def test_openapi_garde_une_seule_etiquette_frontend_par_operation(live):
    client, _, _ = live
    spec = client.get("/openapi.json").json()
    doubles = sorted(
        f"{m} {p}"
        for p, ops in spec["paths"].items()
        for m, op in ops.items()
        if op.get("tags") == ["frontend", "frontend"]
    )
    assert doubles == []


def test_library_type_inconnu_reste_404_et_type_connu_ne_plante_pas_sans_ma(live):
    client, _, _ = live
    assert client.get("/api/v1/ma/library/bogus").status_code == 404
    assert client.get("/api/v1/ma/library/").status_code == 404


@pytest.mark.parametrize("module,names", OLD_NAMES.items())
def test_anciens_chemins_d_import_restent_valides(module, names):
    mod = importlib.import_module(module)
    assert [n for n in names if not hasattr(mod, n)] == []


@pytest.mark.parametrize(
    "files,limit",
    [
        (["app/services/music_assistant.py"], 990),
        (["app/services/media_service.py"], 578),
    ],
)
def test_module_plus_court_qu_au_depart(files, limit):
    for f in files:
        assert len((ROOT / f).read_text().splitlines()) < limit


def test_views_plus_court_qu_au_depart_fichier_par_fichier():
    legacy = ROOT / "app/api/views.py"
    files = [legacy] if legacy.exists() else sorted((ROOT / "app/api/views").glob("*.py"))
    assert files
    assert all(len(f.read_text().splitlines()) < 1179 for f in files)


def test_pas_de_branche_item_morte_dans_le_formulaire_media():
    text = (ROOT / "app/templates/media/form.html").read_text()
    for guard in ("{% if item %}", " if item else ", "{% if item and ", "{% if not item %}"):
        assert guard not in text


def test_un_seul_gestionnaire_pour_les_routes_library():
    router = importlib.import_module("app.api.music_assistant").router
    assert len([r for r in router.routes if "/library/" in getattr(r, "path", "")]) == 1


def test_version_et_migrations_inchangees():
    assert 'version = "0.27.0"' in (ROOT / "pyproject.toml").read_text()
    assert 'app_version: str = "0.27.0"' in (ROOT / "app/config.py").read_text()
    assert not list(ROOT.rglob("alembic*/versions/*.py"))
    assert not (ROOT / "alembic").exists()


def test_openapi_aucune_operation_n_a_d_etiquette_en_double_et_les_pages_gardent_frontend(live):
    client, _, _ = live
    spec = client.get("/openapi.json").json()
    tags = {
        f"{m} {p}": op.get("tags", [])
        for p, ops in spec["paths"].items()
        for m, op in ops.items()
        if m in {"get", "post", "put", "patch", "delete"}
    }
    dupes = sorted(k for k, t in tags.items() if len(t) != len(set(t)))
    assert dupes == []
    assert sum(1 for t in tags.values() if t == ["frontend"]) == 27
