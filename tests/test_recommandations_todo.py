"""Versement de TODO.md aux recommandations (AD-reco-2, B-7) : écrit depuis le critère."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECO = (ROOT / "docs" / "quality" / "recommendations.md").read_text(encoding="utf-8")
TODO = (ROOT / "TODO.md").read_text(encoding="utf-8")


def test_todo_has_no_open_entry_and_points_to_recommendations():
    assert not re.search(r"^###\s", TODO, re.M)
    assert "## En attente" not in TODO or not re.search(r"## En attente\s*\n+\S", TODO.split("## Livré")[0].split("## En attente")[-1]) 
    assert TODO.startswith("# TODO")
    assert "## Livré" in TODO
    m = re.search(r"\]\((docs/quality/recommendations\.md)\)", TODO)
    assert m and (ROOT / m.group(1)).is_file()


def test_numbering_continuous_and_summary_complete():
    ids = [int(i) for i in re.findall(r"^### R-(\d+) —", RECO, re.M)]
    assert sorted(ids) == list(range(1, len(ids) + 1))
    rows = [int(i) for i in re.findall(r"^\| R-(\d+) \|", RECO, re.M)]
    assert sorted(rows) == sorted(ids)
