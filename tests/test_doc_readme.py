"""Criteria of the task "doc-readme": config table, CI commands, versioning link, links."""

import re
from pathlib import Path

import yaml

from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _table_rows() -> dict[str, str]:
    rows = {}
    for line in README.splitlines():
        m = re.match(r"\|\s*`(ML_[A-Z0-9_]+)`\s*\|(.*)\|\s*$", line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def test_every_settings_field_is_in_config_table_with_default():
    rows = _table_rows()
    for name, field in Settings.model_fields.items():
        var = "ML_" + name.upper()
        assert var in rows, var
        cells = [c.strip() for c in rows[var].split("|")]
        assert len(cells) >= 3 and cells[0], f"{var}: missing meaning"
        default = field.default
        if isinstance(default, str) and default:
            assert default in cells[1], f"{var}: default {default!r} not documented"
        if isinstance(default, str) and not default:
            assert "empty" in cells[1].lower(), var


def test_table_documents_no_unknown_variable():
    expected = {"ML_" + n.upper() for n in Settings.model_fields}
    assert set(_table_rows()) == expected


def test_numeric_and_bool_defaults_match():
    rows = _table_rows()
    assert "`8000`" in rows["ML_PORT"] and "`8001`" in rows["ML_ESP_PORT"]
    assert "`300`" in rows["ML_COVER_MAX_SIZE"] and "`false`" in rows["ML_DEBUG"]
    assert "1073741824" in rows["ML_THUMB_CACHE_MAX_BYTES"]


def test_no_environ_read_outside_settings_is_missing_from_table():
    rows = _table_rows()
    found = set()
    for py in (ROOT / "app").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        found |= set(re.findall(r"""(?:environ(?:\.get)?\s*[\[(]|getenv\()\s*["'](\w+)["']""", text))
    assert [v for v in found if v not in rows] == []


def test_ci_run_commands_appear_verbatim_in_readme_in_order():
    wf = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    runs = [s["run"] for j in wf["jobs"].values() for s in j["steps"] if "run" in s]
    assert runs
    pos = -1
    for cmd in runs:
        i = README.find(cmd, pos + 1)
        assert i > pos, f"{cmd!r} missing or out of order"
        pos = i


def test_readme_links_claude_md_for_versioning():
    section = README.split("## Versioning", 1)[1].split("\n## ", 1)[0]
    assert "(CLAUDE.md)" in section
    assert "pyproject.toml" in section and "app/config.py" in section


def test_relative_links_resolve():
    bad = []
    for target in LINK.findall(README):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        if not (ROOT / target.split("#")[0]).exists():
            bad.append(target)
    assert bad == []


def test_readme_is_english_and_mentions_ports():
    assert "8000" in README and "8001" in README
    assert not re.search(r"\b(Lancer|lancement|Démarrer|bibliothèque)\b", README)
