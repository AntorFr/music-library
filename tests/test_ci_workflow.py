"""Pins for AD-preuve-tests-1: the suite is declared and attested, no workflow plays it."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def _triggers(wf: dict) -> dict:
    # PyYAML reads the bare key `on` as boolean True.
    return wf.get("on", wf.get(True))


@pytest.fixture(scope="module")
def publish() -> dict:
    return yaml.safe_load((WORKFLOWS / "docker-publish.yml").read_text())


def _all_runs(wf: dict) -> list[str]:
    return [s["run"] for job in wf["jobs"].values() for s in job["steps"] if "run" in s]


def test_ci_yml_is_gone():
    assert not (WORKFLOWS / "ci.yml").exists()


def test_no_workflow_plays_the_suite_or_fires_on_branches_and_pull_requests():
    for path in WORKFLOWS.glob("*.y*ml"):
        wf = yaml.safe_load(path.read_text())
        trigger = _triggers(wf)
        assert "pull_request" not in trigger, path.name
        assert "branches" not in (trigger.get("push") or {}), path.name
        for run in _all_runs(wf):
            assert "pytest" not in run and "ruff" not in run, path.name


def test_suite_is_declared_with_a_local_level():
    tests = yaml.safe_load((ROOT / ".sdlc.yaml").read_text())["tests"]
    assert tests["commande"] == "scripts/suite-attestee.sh"
    assert tests["rapport"] == "resultats.xml"
    assert tests["format"] == "junit"
    assert tests["delai"]
    assert tests["local"] == "scripts/suite-locale.sh"
    for name in ("suite-attestee.sh", "suite-locale.sh"):
        assert (ROOT / "scripts" / name).is_file()
    assert "resultats.xml" in (ROOT / ".gitignore").read_text().split()


def test_attested_script_installs_dev_extras_and_writes_a_junit_report():
    script = (ROOT / "scripts" / "suite-attestee.sh").read_text()
    assert " install " in script and "-e '.[dev]'" in script
    assert "--junitxml=resultats.xml" in script


def test_image_is_built_on_a_v_tag_only(publish):
    trigger = _triggers(publish)
    assert set(trigger) == {"push", "release"}
    assert trigger["push"] == {"tags": ["v*"]}
    assert trigger["release"] == {"types": ["published"]}


def test_image_build_needs_the_attestation_job(publish):
    jobs = publish["jobs"]
    assert "attestation" in jobs
    assert jobs["build-and-push"]["needs"] == "attestation"
    for job in jobs.values():
        assert "startsWith(github.ref, 'refs/tags/v')" in job["if"]
    att = jobs["attestation"]
    assert att["permissions"]["statuses"] == "read"
    assert any("tests-complets" in run for run in _all_runs({"jobs": {"a": att}}))


def test_claude_md_states_the_rule():
    text = (ROOT / "CLAUDE.md").read_text()
    assert ".sdlc.yaml" in text
    assert "attest" in text
    assert "attester --publier" in text
