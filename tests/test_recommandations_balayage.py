"""Balayage de docs/quality/recommendations.md (AD-reco-1, B-7) : écrit depuis le critère."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
Q = ROOT / "docs" / "quality"
RECO = (Q / "recommendations.md").read_text(encoding="utf-8")
THEMES = ["Security", "Behaviour kept as found", "Tooling and CI",
          "Documentation gaps", "New functions", "Applied"]


def _entries():
    parts = re.split(r"^### (R-\d+) — (.+)$", RECO, flags=re.M)
    out = {}
    for i in range(1, len(parts), 3):
        out[parts[i]] = (parts[i + 1], parts[i + 2])
    return out


def _origins():
    return {k: (re.search(r"\*\*Origin\*\*:(.*)", b).group(1) if re.search(r"\*\*Origin\*\*:(.*)", b) else "")
            for k, (_, b) in _entries().items()}


def _all_origin_text():
    return "\n".join(_origins().values())


def test_themes_in_ad_reco_1_order():
    pos = [RECO.index(f"\n## {t}\n") for t in THEMES]
    assert pos == sorted(pos)
    assert "## How to read" in RECO and "## Summary" in RECO


def test_every_entry_has_five_fields_and_two_options():
    ents = _entries()
    assert len(ents) >= 30
    for rid, (_, body) in ents.items():
        for f in ("Origin", "Today", "Options", "Recommendation", "Status"):
            assert re.search(rf"^- \*\*{f}\*\*:", body, re.M), (rid, f)
        status = re.search(r"\*\*Status\*\*:\s*(\w+)", body).group(1)
        assert status in ("open", "applied"), rid
        opts = re.search(r"\*\*Options\*\*:(.*)", body).group(1)
        if status == "open":
            assert len(re.findall(r"\(\d\)", opts)) >= 2, rid
            assert "eave as is" in opts, rid


def test_ids_unique_and_summary_lists_each():
    ids = re.findall(r"^### (R-\d+) —", RECO, re.M)
    assert len(ids) == len(set(ids))
    for rid in ids:
        assert re.search(rf"^\| {rid} \|", RECO, re.M), rid


def test_every_coverage_test_is_in_an_origin():
    cov = (Q / "coverage.md").read_text(encoding="utf-8")
    sec = cov.split("## Comportements douteux conservés")[1]
    tests = re.findall(r"^\| `(tests/[^`]+)` \|", sec, re.M)
    assert len(tests) == 14
    origins = _all_origin_text()
    assert [t for t in tests if t not in origins] == []


def test_every_security_finding_noncritical_is_in_an_origin():
    sec = (Q / "security-review.md").read_text(encoding="utf-8")
    ids = re.findall(r"^\*\*(S-\d+) — ", sec, re.M)
    assert len(ids) == 21
    origins = _all_origin_text()
    assert [s for s in ids if not re.search(rf"\b{s}\b", origins)] == []


def test_applied_fixes_are_applied_with_commit():
    ents = _entries()
    for sid in ("S-1", "S-13"):
        hits = [k for k, o in _origins().items() if re.search(rf"\b{sid}\b", o)]
        assert hits, sid
        for k in hits:
            st = re.search(r"\*\*Status\*\*:(.*)", ents[k][1]).group(1)
            assert "applied" in st and re.search(r"`[0-9a-f]{7,}`", st), k
            sha = re.search(r"`([0-9a-f]{7,})`", st).group(1)
            r = subprocess.run(["git", "cat-file", "-t", sha], cwd=ROOT, capture_output=True, text=True)
            assert r.stdout.strip() == "commit", (k, sha)


def test_banner_gaps_in_origin():
    origins = _all_origin_text()
    for doc in ("PLAN.md", "REQUIREMENTS.md"):
        txt = (ROOT / "docs" / doc).read_text(encoding="utf-8")
        banner = [ln for ln in txt.splitlines() if ln.startswith(">")]
        bullets = [ln[1:].strip()[2:].strip() for ln in banner if ln[1:].strip().startswith("- ")]
        assert bullets
        for b in bullets:
            key = b[:40]
            assert key in origins, (doc, b)


def test_actions_and_mypy_entries_exist():
    titles = " ".join(t for t, _ in _entries().values()).lower()
    assert "sha" in titles and "mypy" in titles
