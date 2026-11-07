"""Criteria of the task "doc-decisions": ARCHITECTURE.md organs and one ADR per durable decision."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCH = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
ADR_DIR = ROOT / "docs" / "adr"
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SECTIONS = ("Context", "Decision", "Rejected", "Consequences")


def _adrs() -> list[Path]:
    return sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))


def test_every_app_module_is_cited_in_architecture():
    missing = []
    for py in sorted((ROOT / "app").rglob("*.py")):
        rel = py.relative_to(ROOT).as_posix()
        name = py.name
        pkg = py.parent.relative_to(ROOT).as_posix() + "/"
        cited = rel in ARCH or f"`{name}`" in ARCH or f"`{name[:-3]}`" in ARCH or pkg in ARCH
        # a bare module name is only accepted when its package is cited too
        if not (cited and pkg in ARCH):
            missing.append(rel)
    assert missing == []


def test_durable_decisions_section_lists_exactly_the_adrs():
    assert re.search(r"^## Durable decisions", ARCH, re.M)
    section = ARCH.split("## Durable decisions", 1)[1].split("\n## ", 1)[0]
    listed = sorted(re.findall(r"\(docs/adr/([^)]+\.md)\)", section))
    assert listed == [p.name for p in _adrs()]
    assert len(listed) == 7


def test_adrs_numbered_from_0001_without_gap():
    numbers = [int(p.name[:4]) for p in _adrs()]
    assert numbers == list(range(1, len(numbers) + 1))


def test_each_adr_has_four_sections_and_cites_an_app_file():
    for p in _adrs():
        text = p.read_text(encoding="utf-8")
        for s in SECTIONS:
            assert re.search(rf"^## {s}\s*$", text, re.M), f"{p.name}: no {s}"
        cited = [c for c in re.findall(r"`(app/[\w/]+\.py)`", text) if (ROOT / c).is_file()]
        assert cited, f"{p.name}: cites no existing app/ file"


def test_relative_links_resolve():
    for src in [ROOT / "ARCHITECTURE.md", *_adrs()]:
        for target in LINK.findall(src.read_text(encoding="utf-8")):
            if re.match(r"^[a-z]+:|^#", target):
                continue
            path = target.split("#", 1)[0]
            assert (src.parent / path).exists(), f"{src.name}: broken link {target}"


def test_adr_0005_does_not_claim_alembic_migrations():
    text = (ADR_DIR / "0005-sqlite-schema-created-and-upgraded-at-startup.md").read_text()
    assert "init_db" in text
    assert not (ROOT / "alembic").exists() and not (ROOT / "alembic.ini").exists()
