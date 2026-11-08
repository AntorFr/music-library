"""B-7 / P-2 : docs/quality/recommendations.md, vérifié depuis le besoin (niveau ensemble).

Les attendus sont écrits en dur depuis le critère de sortie de la feature et depuis les
documents d'entrée (coverage.md, security-review.md, TODO.md d'origine) : aucun n'est tiré
du document testé.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECO = (ROOT / "docs" / "quality" / "recommendations.md").read_text(encoding="utf-8")
TODO = (ROOT / "TODO.md").read_text(encoding="utf-8")

# Les 14 « comportements douteux conservés » de coverage.md (fichier, test).
DOUBTFUL = [
    ("test_covers_api.py", "test_missing_cover_with_a_relative_default_path_is_a_500"),
    ("test_pages_views.py", "test_media_list_with_an_unknown_media_type_is_a_500"),
    ("test_pages_views.py", "test_browse_library_unknown_type_with_ma_down_is_a_200"),
    ("test_pages_views.py", "test_browse_search_with_ma_down_reports_the_error_inline"),
    ("test_health.py", "test_health_has_no_unprefixed_alias"),
    ("test_api_tags.py", "test_delete_category_that_still_has_tags_fails_with_500"),
    ("test_api_tags.py", "test_create_category_answers_201_then_409_on_duplicate"),
    ("test_api_ma.py", "test_search_ma_failure_is_not_caught"),
    ("test_api_quick.py", "test_thumb_download_failure_falls_back_to_the_default_cover"),
    ("test_api_permissions.py", "test_child_delete_of_others_media_is_404_even_when_hard"),
    ("test_rfid_api.py", "test_put_with_a_malformed_uid_answers_500_and_stores_nothing"),
    ("test_esp_boundary.py", "test_a_media_path_ending_in_cover_is_guarded_whatever_its_middle"),
    ("test_spotify_pin_api.py", "test_fragment_for_a_non_spotify_media_still_renders"),
    ("test_startup.py", "test_no_alembic_version_table_is_ever_created"),
]
SECURITY_IDS = [f"S-{n}" for n in range(1, 22)]
TODO_TITLES = [
    "API de recherche floue en langage naturel",
    "Interface mobile « lanceur rapide » (iPad / iPhone)",
]


def _entries():
    parts = re.split(r"^### (R-\d+) — (.+)$", RECO, flags=re.M)
    return {parts[i]: (parts[i + 1], parts[i + 2]) for i in range(1, len(parts), 3)}


def _field(body, name):
    m = re.search(rf"^- \*\*{name}\*\*:[ \t]*(.*)$", body, re.M)
    return m.group(1).strip() if m else None


def _entries_citing(token):
    return [k for k, (_, b) in _entries().items() if token in (_field(b, "Origin") or "")]


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


# --- nominal -----------------------------------------------------------------

def test_document_exists_with_many_entries():
    assert (ROOT / "docs" / "quality" / "recommendations.md").is_file()
    assert len(_entries()) >= 40


def test_every_entry_has_non_empty_origin_options_recommendation():
    for rid, (_, body) in _entries().items():
        for f in ("Origin", "Options", "Recommendation"):
            assert _field(body, f), (rid, f)


def test_every_open_entry_offers_at_least_two_options():
    for rid, (_, body) in _entries().items():
        if (_field(body, "Status") or "").startswith("open"):
            assert len(re.findall(r"\(\d\)", _field(body, "Options"))) >= 2, rid


# --- coverage.md : comportements douteux conservés ----------------------------

def test_each_of_the_14_doubtful_behaviours_has_an_entry_citing_its_test():
    for fichier, nom in DOUBTFUL:
        assert _entries_citing(f"tests/{fichier}::{nom}"), (fichier, nom)


def test_doubtful_behaviours_cited_tests_really_exist():
    for fichier, nom in DOUBTFUL:
        src = (ROOT / "tests" / fichier).read_text(encoding="utf-8")
        assert re.search(rf"def {nom}\(", src), (fichier, nom)


# --- security-review.md ---------------------------------------------------------

def test_each_of_the_21_security_findings_is_cited_by_an_entry():
    for sid in SECURITY_IDS:
        assert any(re.search(rf"\b{sid}\b", _field(b, "Origin") or "") for _, b in _entries().values()), sid


# --- AD-6 : correctifs appliqués ---------------------------------------------------

def test_critical_fixes_s1_and_s13_are_noted_applied_with_a_real_commit():
    for sid in ("S-1", "S-13"):
        hits = [b for _, b in _entries().values() if re.search(rf"\b{sid}\b", _field(b, "Origin") or "")]
        assert len(hits) == 1, sid
        status = _field(hits[0], "Status")
        assert status.startswith("applied"), sid
        sha = re.search(r"`([0-9a-f]{7,40})`", status)
        assert sha, sid
        assert _git("cat-file", "-t", sha.group(1)).stdout.strip() == "commit", sid


def test_exactly_four_entries_are_applied_the_two_critical_and_two_fixed():
    applied = {k: _field(b, "Origin") for k, (_, b) in _entries().items()
               if (_field(b, "Status") or "").startswith("applied")}
    assert len(applied) == 4
    ids = sorted(re.search(r"S-\d+", o).group(0) for o in applied.values())
    assert ids == ["S-1", "S-12", "S-13", "S-2"]


# --- TODO.md --------------------------------------------------------------------

def test_todo_md_no_longer_holds_open_entries():
    assert not re.search(r"^#{2,4}\s*\d+\.", TODO, re.M)
    assert not re.search(r"^###\s", TODO, re.M)
    for title in TODO_TITLES:
        assert title not in TODO
    assert "recommendations.md" in TODO


def test_each_todo_entry_is_in_the_recommendations_with_its_details():
    for title in TODO_TITLES:
        hits = _entries_citing(title)
        assert len(hits) == 1, title
        body = _entries()[hits[0]][1]
        assert _field(body, "Status").startswith("open")
    fuzzy = _entries()[_entries_citing(TODO_TITLES[0])[0]][1]
    mobile = _entries()[_entries_citing(TODO_TITLES[1])[0]][1]
    assert "Ollama" in fuzzy and "embeddings" in fuzzy
    assert "localStorage" in mobile and "PWA" in mobile


# --- bannières PLAN.md / REQUIREMENTS.md ------------------------------------------------

def test_each_banner_gap_of_the_historical_docs_is_in_an_origin():
    gaps = ["aucune migration Alembic", "l'authentification existe", "port 8001",
            "est devenu le paquet", "pas d'auth", "arborescence du §7"]
    origins = "\n".join(_field(b, "Origin") or "" for _, b in _entries().values())
    for g in gaps:
        assert g in origins, g


# --- thèmes cités par la fiche (« etc. ») ------------------------------------------------

def test_actions_sha_pinning_and_mypy_have_their_own_entry():
    titles = [t.lower() for t, _ in _entries().values()]
    assert any("sha" in t and "action" in t for t in titles)
    assert any("mypy" in t for t in titles)


# --- exclusions : rien n'est décidé ni appliqué à la place de Monsieur -------------------

def test_statuses_are_only_open_or_applied():
    for rid, (_, body) in _entries().items():
        assert re.match(r"(open|applied)\b", _field(body, "Status")), rid


def test_new_functions_are_recommendations_never_scope():
    for title in TODO_TITLES:
        rid = _entries_citing(title)[0]
        assert _field(_entries()[rid][1], "Status") == "open", rid
        assert "new function" in _entries()[rid][0].lower()


# --- ordre et cohérence du sommaire --------------------------------------------------

def test_summary_row_matches_each_entry_origin_and_status():
    rows = dict()
    for m in re.finditer(r"^\| (R-\d+) \| (.*?) \| (.*?) \| (.*?) \| (\w+) \|$", RECO, re.M):
        rows[m.group(1)] = (m.group(2), m.group(5))
    ents = _entries()
    assert set(rows) == set(ents)
    for rid, (title, status) in rows.items():
        assert title == ents[rid][0], rid
        assert status == _field(ents[rid][1], "Status").split()[0], rid


def test_entry_ids_are_unique_and_cover_1_to_n():
    ids = re.findall(r"^### R-(\d+) —", RECO, re.M)
    assert len(ids) == len(set(ids))
    assert sorted(map(int, ids)) == list(range(1, len(ids) + 1))
