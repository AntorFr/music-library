"""Pins for .github/workflows/ci.yml (B-6, AD-4): ruff + pytest on every PR to main."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


@pytest.fixture(scope="module")
def ci() -> dict:
    return yaml.safe_load((WORKFLOWS / "ci.yml").read_text())


def _steps(ci: dict) -> list[dict]:
    return [s for job in ci["jobs"].values() for s in job["steps"]]


def _runs(ci: dict) -> list[str]:
    return [s["run"].strip() for s in _steps(ci) if "run" in s]


def test_triggers_only_on_pull_request_to_main(ci):
    # PyYAML reads the bare key `on` as boolean True.
    trigger = ci.get("on", ci.get(True))
    assert set(trigger) == {"pull_request"}
    assert trigger["pull_request"]["branches"] == ["main"]


def test_runs_ruff_check_and_pytest_in_order(ci):
    runs = _runs(ci)
    assert "ruff check ." in runs
    assert "pytest" in runs
    assert runs.index("ruff check .") < runs.index("pytest")


def test_installs_dev_extras_before_checks(ci):
    runs = _runs(ci)
    install = next(i for i, r in enumerate(runs) if r.startswith("pip install"))
    assert "-e" in runs[install] and ".[dev]" in runs[install]
    assert install < runs.index("ruff check .")


def test_uses_python_312(ci):
    setups = [s for s in _steps(ci) if str(s.get("uses", "")).startswith("actions/setup-python@")]
    assert [str(s["with"]["python-version"]) for s in setups] == ["3.12"]


def test_checks_cannot_be_bypassed(ci):
    for job in ci["jobs"].values():
        assert "continue-on-error" not in job
        assert "if" not in job
    for step in _steps(ci):
        assert "continue-on-error" not in step
        assert "if" not in step
        run = step.get("run", "")
        assert "|| true" not in run and "||true" not in run
        assert "set +e" not in run


def test_actions_pinned_by_major_tag(ci):
    for step in _steps(ci):
        if "uses" in step:
            _, _, ref = step["uses"].partition("@")
            assert ref.startswith("v") and ref[1:].isdigit(), step["uses"]

