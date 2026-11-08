"""Versement de TODO.md aux recommandations (AD-reco-2, B-7) : écrit depuis le critère."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECO = (ROOT / "docs" / "quality" / "recommendations.md").read_text(encoding="utf-8")
TODO = (ROOT / "TODO.md").read_text(encoding="utf-8")


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def _entries():
    parts = re.split(r"^### (R-\d+) — (.+)$", RECO, flags=re.M)
    return {parts[i]: parts[i + 2] for i in range(1, len(parts), 3)}


def test_todo_has_no_open_entry_and_points_to_recommendations():
    assert not re.search(r"^###\s", TODO, re.M)
    assert "## En attente" not in TODO or not re.search(r"## En attente\s*\n+\S", TODO.split("## Livré")[0].split("## En attente")[-1]) 
    assert TODO.startswith("# TODO")
    assert "## Livré" in TODO
    m = re.search(r"\]\((docs/quality/recommendations\.md)\)", TODO)
    assert m and (ROOT / m.group(1)).is_file()


def test_every_todo_title_of_epic_is_in_an_origin():
    r = _git("show", "origin/epic/music-library-qualite:TODO.md")
    if r.returncode != 0:
        return
    titles = re.findall(r"^### (.+)$", r.stdout, re.M)
    assert len(titles) == 2
    origins = {k: re.search(r"\*\*Origin\*\*:(.*)", b).group(1) for k, b in _entries().items()}
    for t in titles:
        title = re.sub(r"^\d+\.\s*", "", t)
        hits = [k for k, o in origins.items() if title in o]
        assert hits, t
        for k in hits:
            body = _entries()[k]
            assert re.search(r"^- \*\*Options\*\*:.*\(2\)", body, re.M), k
            assert re.search(r"^- \*\*Recommendation\*\*:\s*\S", body, re.M), k


def test_numbering_continuous_and_summary_complete():
    ids = [int(i) for i in re.findall(r"^### R-(\d+) —", RECO, re.M)]
    assert sorted(ids) == list(range(1, len(ids) + 1))
    rows = [int(i) for i in re.findall(r"^\| R-(\d+) \|", RECO, re.M)]
    assert sorted(rows) == sorted(ids)
