"""Ensemble tests for B-6 / B-8 (lint + CI), written from the feature's exit criterion.

Injections are made in temporary copies; the working tree is never touched.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
RUFF = [sys.executable, "-m", "ruff"]


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)


def test_ruff_check_is_silent_on_the_repository():
    r = _run([*RUFF, "check", "."], ROOT)
    assert r.returncode == 0, r.stdout + r.stderr


def test_rule_set_keeps_the_six_families():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert set(cfg["tool"]["ruff"]["lint"]["select"]) >= {"E", "F", "I", "UP", "B", "SIM"}


def test_release_version_is_still_the_same_in_both_places():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text())
    version = cfg["project"]["version"]
    assert f'app_version: str = "{version}"' in (ROOT / "app" / "config.py").read_text()


@pytest.mark.parametrize(
    ("family", "source"),
    [
        ("F401", "import os\n"),
        ("E711", "x = 1\nif x == None:\n    pass\n"),
        ("I001", "import sys\nimport os\n\nprint(os, sys)\n"),
        ("UP006", "import typing\n\n\ndef f(a: typing.List[int]) -> None:\n    pass\n"),
        ("B006", "def f(a=[]):\n    return a\n"),
        ("SIM108", "if True:\n    y = 1\nelse:\n    y = 2\nprint(y)\n"),
    ],
)
def test_ruff_with_project_config_fails_on_injected_error(tmp_path, family, source):
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    (tmp_path / "inj.py").write_text(source)
    r = _run([*RUFF, "check", "."], tmp_path)
    assert r.returncode != 0
    assert family in r.stdout


def test_ruff_with_project_config_passes_on_clean_file(tmp_path):
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    (tmp_path / "ok.py").write_text('"""ok."""\n\nVALUE = 1\n')
    assert _run([*RUFF, "check", "."], tmp_path).returncode == 0


def test_pytest_exits_nonzero_on_altered_assertion(tmp_path):
    (tmp_path / "test_altered.py").write_text("def test_x():\n    assert 1 + 1 == 3\n")
    r = _run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q"], tmp_path)
    assert r.returncode != 0
    assert "1 failed" in r.stdout


def test_pytest_exits_zero_on_intact_assertion(tmp_path):
    (tmp_path / "test_intact.py").write_text("def test_x():\n    assert 1 + 1 == 2\n")
    r = _run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q"], tmp_path)
    assert r.returncode == 0


def test_ci_workflow_fires_on_pull_request_to_main_and_runs_both_checks():
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    trigger = ci.get("on", ci.get(True))
    assert trigger == {"pull_request": {"branches": ["main"]}}
    runs = [s["run"].strip() for j in ci["jobs"].values() for s in j["steps"] if "run" in s]
    assert "ruff check ." in runs and "pytest" in runs


def test_ci_checks_cannot_be_bypassed_even_as_raw_text():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "continue-on-error" not in text
    assert "|| true" not in text and "||true" not in text


def test_image_publish_workflow_still_triggers_on_main_and_tags():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "docker-publish.yml").read_text())
    trigger = wf.get("on", wf.get(True))
    assert trigger["push"]["branches"] == ["main"]
