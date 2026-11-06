"""Criteria of the task "doc-anciens": status.md, PLAN/REQUIREMENTS, AUTH.md, pointers."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIX = [
    ".agent/status.md",
    "docs/PLAN.md",
    "docs/REQUIREMENTS.md",
    "docs/AUTH.md",
    "AGENTS.md",
    ".github/copilot-instructions.md",
]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_status_names_current_version_without_history():
    version = tomllib.loads(_text("pyproject.toml"))["project"]["version"]
    text = _text(".agent/status.md")
    assert version in text
    # no per-version history: only the current version may appear as vX.Y.Z / X.Y.Z
    others = set(re.findall(r"\bv?\d+\.\d+\.\d+\b", text)) - {version, "v" + version}
    assert others == set()


def test_status_open_boxes_are_production_checks_only():
    text = _text(".agent/status.md")
    assert "TODO.md" not in text
    assert len(re.findall(r"^- \[ \]", text, re.M)) >= 1
    assert "- [x]" not in text.lower()


def test_status_points_to_recommendations_in_code_not_link():
    text = _text(".agent/status.md")
    assert "`docs/quality/recommendations.md`" in text
    assert "](docs/quality/recommendations.md" not in text
    assert "](../docs/quality" not in text


def test_relative_links_resolve_in_the_six_files():
    for rel in SIX:
        path = ROOT / rel
        if path.is_symlink() and not path.exists():
            raise AssertionError(f"{rel} is a dangling symlink")
        for target in LINK.findall(_text(rel)):
            if re.match(r"^[a-z]+:", target) or target.startswith("#"):
                continue
            file_part = target.split("#")[0]
            assert (path.parent / file_part).exists(), f"{rel}: {target}"


def test_plan_and_requirements_marked_historical_at_top():
    for rel in ("docs/PLAN.md", "docs/REQUIREMENTS.md"):
        head = "\n".join(_text(rel).splitlines()[:6])
        assert "historical" in head.lower(), rel


def test_agents_is_still_symlink_to_claude():
    path = ROOT / "AGENTS.md"
    assert path.is_symlink()
    assert path.readlink() == Path("CLAUDE.md")


def test_copilot_instructions_shares_no_line_with_claude():
    claude = {ln.strip() for ln in _text("CLAUDE.md").splitlines() if ln.strip()}
    copilot_path = ROOT / ".github/copilot-instructions.md"
    assert not copilot_path.is_symlink()
    shared = [
        ln.strip()
        for ln in copilot_path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and ln.strip() in claude
    ]
    assert shared == []
    body = copilot_path.read_text(encoding="utf-8")
    assert "CLAUDE.md" in body and "README.md" in body


def test_auth_doc_claims_match_code_constants():
    from app.config import settings
    from app.services import auth_service
    from app.services.auth_service import DEV_USER, MACHINE_USER

    doc = _text("docs/AUTH.md")
    assert settings.oidc_admin_group == "parents" and "`parents`" in doc
    assert MACHINE_USER.username == "api-token" and MACHINE_USER.is_parent
    assert DEV_USER.username == "dev" and DEV_USER.is_parent
    assert "api-token" in doc and "`dev`" in doc
    for path in ("/auth/", "/static/", "/covers/", "/manifest.webmanifest",
                 "/favicon.ico", "/api/v1/health"):
        assert auth_service.is_exempt_path(path + ("x" if path.endswith("/") else ""))
        assert path in doc
    assert not auth_service.is_exempt_path("/api/v1/media")
