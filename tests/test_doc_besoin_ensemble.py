"""Tests d'ensemble de la feature music-library-qualite-doc (B-3, B-8, AD-3, P-1).

Ecrits depuis le besoin (fiche, critere de sortie, docs/parcours.md), pas depuis le diff.
Attendus litteraux. Aucun test ne s'appuie sur git (la CI n'a que le checkout du commit).

Plan (besoin -> cas -> preuve)
- B-3 liens      : tout lien relatif des fichiers livres se resout (nominal) ; le lien
                   vers un fichier absent est detecte (le detecteur lui-meme, bord).
- B-3 variables  : chaque champ de Settings (ML_*) figure dans le tableau du README, avec
                   son defaut ; aucune lecture d'environnement cachee dans app/ ;
                   aucune variable du tableau n'est inconnue du code (exclusion).
- B-3/P-1 CI     : chaque commande `run` de ci.yml est nommee dans le README ; le README
                   lie ci.yml.
- B-8 version    : README lie CLAUDE.md et nomme pyproject.toml et app/config.py ;
                   pyproject.version == app_version == defaut documente == status.md.
- AD-3 decisions: section « Durable decisions » ; un ADR par entree et pas d'ADR hors
                   liste ; numerotation 0001.. continue ; 4 sections non vides ; les
                   chemins app/ cites existent.
- AD-3 pointeurs : copilot-instructions ne copie aucun autre fichier ; AGENTS.md = lien
                   vers CLAUDE.md ; status.md = etat courant ; PLAN/REQUIREMENTS marques
                   historiques ; AUTH.md ne contredit pas le code (variables, exemptions).
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest
import yaml

from app.config import Settings
from app.services.auth_service import is_exempt_path

ROOT = Path(__file__).resolve().parents[1]

DELIVERED = [
    "README.md",
    "ARCHITECTURE.md",
    "CLAUDE.md",
    "AGENTS.md",
    ".agent/status.md",
    ".github/copilot-instructions.md",
    "docs/PLAN.md",
    "docs/REQUIREMENTS.md",
    "docs/AUTH.md",
]

LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _delivered_files() -> list[str]:
    return DELIVERED + sorted(
        f"docs/adr/{p.name}" for p in (ROOT / "docs" / "adr").glob("*.md")
    )


def _broken_links(rel: str, text: str | None = None) -> list[str]:
    base = (ROOT / rel).parent
    text = _read(rel) if text is None else text
    broken = []
    for target in LINK.findall(text):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        path = target.split("#", 1)[0]
        if path and not (base / path).exists():
            broken.append(target)
    return broken


# --------------------------------------------------------------------------- B-3 liens


@pytest.mark.parametrize("rel", DELIVERED + ["docs/adr/0001-oidc-parent-child-roles-and-open-dev-mode.md"])
def test_fichier_livre_existe(rel):
    # Panne : un fichier de la liste « Livre » manque (README absent avant la feature).
    assert (ROOT / rel).is_file()


def test_tout_lien_relatif_des_fichiers_livres_se_resout():
    # Panne : un lien renomme/supprime (ex. [docs/adr/](docs/adr/) vers un dossier absent).
    broken = {rel: _broken_links(rel) for rel in _delivered_files()}
    assert {k: v for k, v in broken.items() if v} == {}


def test_le_detecteur_de_liens_voit_un_lien_casse():
    # Panne : le detecteur laisse tout passer (test miroir).
    assert _broken_links("README.md", "[x](docs/nexiste-pas.md) [y](README.md#a) [z](https://e.org)") == [
        "docs/nexiste-pas.md"
    ]


def test_le_readme_a_des_liens_vers_l_architecture_et_les_adr():
    # Panne : README isole, un pod ne trouve pas la suite (P-1).
    links = LINK.findall(_read("README.md"))
    assert "ARCHITECTURE.md" in links
    assert any(t.startswith("docs/adr") for t in links)


# --------------------------------------------------------------------------- B-3 variables


def _readme_env_rows() -> dict[str, str]:
    rows = {}
    for line in _read("README.md").splitlines():
        m = re.match(r"^\|\s*`(ML_[A-Z0-9_]+)`\s*\|(.*)\|\s*$", line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def test_chaque_champ_de_settings_figure_dans_le_tableau_du_readme():
    # Panne : une variable ajoutee a Settings (ou oubliee) sans ligne README.
    fields = {"ML_" + name.upper() for name in Settings.model_fields}
    assert fields - set(_readme_env_rows()) == set()


def test_le_tableau_du_readme_ne_cite_aucune_variable_inconnue_du_code():
    # Exclusion : pas de variable fantome documentee.
    fields = {"ML_" + name.upper() for name in Settings.model_fields}
    assert set(_readme_env_rows()) - fields == set()


def test_variables_litterales_attendues_dans_le_readme():
    # Attendu en dur, independant de Settings : les variables que le canon et AUTH.md nomment.
    rows = _readme_env_rows()
    for var in (
        "ML_DATABASE_URL",
        "ML_API_TOKEN",
        "ML_SESSION_SECRET",
        "ML_OIDC_ISSUER",
        "ML_OIDC_CLIENT_ID",
        "ML_OIDC_CLIENT_SECRET",
        "ML_OIDC_REDIRECT_URI",
        "ML_OIDC_ADMIN_GROUP",
        "ML_MUSIC_ASSISTANT_URL",
        "ML_MUSIC_ASSISTANT_TOKEN",
        "ML_HOME_ASSISTANT_URL",
        "ML_HOME_ASSISTANT_TOKEN",
        "ML_THUMB_SIGNING_KEY",
        "ML_ESP_PORT",
        "ML_PORT",
        "ML_HOST",
    ):
        assert var in rows, var


def test_aucune_lecture_d_environnement_hors_settings_dans_app():
    # Panne : une variable lue par os.environ / os.getenv / "ML_..." en dehors de Settings,
    # donc absente du tableau sans que le test des champs le voie.
    offenders = []
    for py in sorted((ROOT / "app").rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}:
                offenders.append(f"{py.relative_to(ROOT)}:{node.lineno}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.fullmatch(
                r"ML_[A-Z0-9_]+", node.value
            ):
                offenders.append(f"{py.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


@pytest.mark.parametrize(
    ("var", "literal"),
    [
        ("ML_PORT", "`8000`"),
        ("ML_ESP_PORT", "`8001`"),
        ("ML_COVER_MAX_SIZE", "`300`"),
        ("ML_OIDC_ADMIN_GROUP", "`parents`"),
        ("ML_DATABASE_URL", "`sqlite+aiosqlite:///data/library.db`"),
        ("ML_THUMBS_DIR", "`/tmp/ml-thumbs`"),
        ("ML_MUSIC_ASSISTANT_URL", "`http://localhost:8095`"),
        ("ML_HOME_ASSISTANT_URL", "`http://localhost:8123`"),
        ("ML_DEBUG", "`false`"),
    ],
)
def test_le_defaut_documente_est_le_defaut_du_code(var, literal):
    # Panne : defaut du README qui contredit app/config.py (« aucun enonce ne contredit le code »).
    assert literal in _readme_env_rows()[var]
    field = Settings.model_fields[var.removeprefix("ML_").lower()]
    default = {False: "false"}.get(field.default, str(field.default))
    assert literal.strip("`") == default


# --------------------------------------------------------------------------- B-3 / P-1 CI


def test_le_readme_nomme_chaque_commande_que_ci_yml_execute():
    # Panne : ci.yml change ou le README derive ; ici les commandes litterales de la CI.
    ci = yaml.safe_load(_read(".github/workflows/ci.yml"))
    runs = [
        step["run"].strip()
        for job in ci["jobs"].values()
        for step in job["steps"]
        if "run" in step
    ]
    assert runs == ["pip install -e '.[dev]'", "ruff check .", "pytest"]
    readme = _read("README.md")
    for cmd in runs:
        assert cmd in readme, cmd


def test_le_readme_lie_ci_yml():
    assert ".github/workflows/ci.yml" in LINK.findall(_read("README.md"))


def test_le_readme_nomme_les_commandes_dans_l_ordre_de_la_ci():
    readme = _read("README.md")
    i = readme.index("ruff check .")
    assert readme.index("pip install -e '.[dev]'", readme.index("## Lint")) < i < readme.index("pytest", i)


# --------------------------------------------------------------------------- B-8 versionnage


def test_le_readme_lie_la_regle_de_versionnage():
    readme = _read("README.md")
    assert "CLAUDE.md" in LINK.findall(readme)
    assert "pyproject.toml" in readme and "app/config.py" in readme
    assert re.search(r"^#+ .*[Vv]ersion", readme, re.M)


def test_les_deux_versions_sont_alignees_et_le_readme_les_reprend():
    # Panne : un slice bumpe un seul emplacement, ou la doc cite une autre version (P-3).
    py = tomllib.loads(_read("pyproject.toml"))["project"]["version"]
    cfg = Settings.model_fields["app_version"].default
    assert py == cfg
    assert f"`{py}`" in _readme_env_rows()["ML_APP_VERSION"]


def test_claude_md_garde_la_regle_de_versionnage():
    text = _read("CLAUDE.md")
    assert "pyproject.toml" in text and "app/config.py" in text and "tag" in text


# --------------------------------------------------------------------------- AD-3 decisions


def _durable_section() -> str:
    text = _read("ARCHITECTURE.md")
    m = re.search(r"^(#+)\s*Durable decisions\s*$", text, re.M)
    assert m, "section « Durable decisions » absente"
    rest = text[m.end():]
    nxt = re.search(rf"^#{{1,{len(m.group(1))}}}\s", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _adr_files() -> list[str]:
    return sorted(p.name for p in (ROOT / "docs" / "adr").glob("*.md"))


def test_architecture_a_une_section_durable_decisions_non_vide():
    assert len(_adr_links()) >= 1


def _adr_links() -> list[str]:
    return [
        t.rsplit("/", 1)[1]
        for t in LINK.findall(_durable_section())
        if t.startswith("docs/adr/") and t.endswith(".md")
    ]


def test_un_adr_par_entree_de_la_liste_et_aucun_adr_hors_liste():
    # Panne : un ADR sans entree (ou une entree sans fichier).
    assert sorted(_adr_links()) == _adr_files()
    assert len(set(_adr_links())) == len(_adr_links())


def test_les_adr_sont_numerotes_de_0001_sans_trou_et_nommes_nnnn_titre():
    names = _adr_files()
    assert all(re.fullmatch(r"\d{4}-[a-z0-9]+(-[a-z0-9]+)*\.md", n) for n in names), names
    assert [int(n[:4]) for n in names] == list(range(1, len(names) + 1))


def test_chaque_adr_a_les_quatre_sections_dans_l_ordre_et_non_vides():
    # Panne : ADR sans « Rejected » (ou section vide).
    for name in _adr_files():
        text = (ROOT / "docs" / "adr" / name).read_text(encoding="utf-8")
        heads = re.findall(r"^## (.+?)\s*$", text, re.M)
        assert heads == ["Context", "Decision", "Rejected", "Consequences"], (name, heads)
        parts = re.split(r"^## .+$", text, flags=re.M)[1:]
        assert all(len(p.strip()) > 40 for p in parts), name
        assert text.startswith(f"# ADR-{name[:4]}"), name


def test_les_chemins_app_cites_par_les_adr_et_le_readme_existent():
    # Panne : « aucun enonce ne contredit le code » : un module cite qui n'existe plus.
    missing = []
    for rel in [f"docs/adr/{n}" for n in _adr_files()] + ["README.md"]:
        for path in re.findall(r"`(app/[A-Za-z0-9_./-]+)`", _read(rel)):
            if not (ROOT / path.rstrip("/")).exists():
                missing.append((rel, path))
    assert missing == []


def test_le_code_final_a_un_paquet_views_que_la_doc_ne_nie_pas():
    # Le refactoring a fait de app/api/views.py un paquet : la doc livree le dit.
    assert (ROOT / "app" / "api" / "views").is_dir()
    assert not (ROOT / "app" / "api" / "views.py").exists()
    assert "app/api/views/" in _read("ARCHITECTURE.md")


# --------------------------------------------------------------------------- AD-3 pointeurs


def test_copilot_instructions_est_un_pointeur_qui_ne_copie_aucun_autre_fichier():
    # Panne : le fichier redevient une copie de CLAUDE.md / README.
    cop = _read(".github/copilot-instructions.md")
    assert len(cop.splitlines()) <= 15
    links = LINK.findall(cop)
    assert "../CLAUDE.md" in links and "../README.md" in links
    others = ""
    for rel in ["CLAUDE.md", "README.md", "ARCHITECTURE.md", ".agent/status.md"] + [
        f"docs/{n}" for n in ("AUTH.md", "PLAN.md", "REQUIREMENTS.md")
    ]:
        others += _read(rel) + "\n"
    copied = [
        ln.strip()
        for ln in cop.splitlines()
        if len(ln.strip()) >= 25 and ln.strip() in others
    ]
    assert copied == []


def test_agents_md_reste_le_lien_vers_claude_md():
    agents = ROOT / "AGENTS.md"
    assert agents.is_symlink() or "CLAUDE.md" in agents.read_text(encoding="utf-8")
    assert agents.resolve() == (ROOT / "CLAUDE.md").resolve() or "(CLAUDE.md)" in _read("AGENTS.md")


def test_status_md_est_un_etat_courant_pas_un_historique():
    # Panne : l'historique version par version revient (seule la version courante est citee).
    text = _read(".agent/status.md")
    versions = set(re.findall(r"\d+\.\d+\.\d+", text))
    current = tomllib.loads(_read("pyproject.toml"))["project"]["version"]
    assert versions == {current}
    assert "docs/quality/recommendations.md" in text
    assert not re.search(r"^#+ .*\bv?\d+\.\d+", text, re.M)


@pytest.mark.parametrize("rel", ["docs/PLAN.md", "docs/REQUIREMENTS.md"])
def test_plan_et_requirements_sont_marques_historiques_en_tete(rel):
    # Panne : un document ecrit avant le code presente comme actuel.
    head = "\n".join(_read(rel).splitlines()[:4]).lower()
    assert "histor" in head


def test_auth_md_cite_seulement_des_variables_du_code():
    fields = {"ML_" + name.upper() for name in Settings.model_fields}
    cited = set(re.findall(r"ML_[A-Z0-9_]+", _read("docs/AUTH.md")))
    assert cited - fields == set()
    assert {"ML_OIDC_ISSUER", "ML_API_TOKEN", "ML_SESSION_SECRET"} <= cited


@pytest.mark.parametrize(
    "path",
    ["/auth/login", "/auth/callback", "/static/app.css", "/covers/1.jpg",
     "/manifest.webmanifest", "/favicon.ico", "/api/v1/health"],
)
def test_les_exemptions_decrites_par_auth_md_sont_exemptees_par_le_code(path):
    assert is_exempt_path(path) is True


@pytest.mark.parametrize("path", ["/", "/api/v1/media", "/api/v1/healthz-not", "/authx"])
def test_les_autres_chemins_ne_sont_pas_exemptes(path):
    # Exclusion : AUTH.md liste les exemptions ; rien d'autre n'est ouvert.
    assert is_exempt_path(path) is False
