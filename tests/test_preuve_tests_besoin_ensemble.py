"""Ensemble tests for the feature music-library-preuve-tests, written from its "Livre" message.

Expected values come from the need: the suite is declared in .sdlc.yaml and run by its
scripts (red suite -> non-zero exit), no workflow plays it, and the image build waits for
an attestation tests-complets on the tagged content (or a parent with the same tree).
Everything runs offline: gh and the Python venv are stubbed in a temporary directory.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
PUBLISH = ROOT / ".github" / "workflows" / "docker-publish.yml"

PYTHON3_STUB = """#!__PY__
import os, sys
a = sys.argv[1:]
if a[:2] == ["-m", "venv"]:
    b = os.path.join(a[2], "bin")
    os.makedirs(b)
    open(os.path.join(b, "pip"), "w").write("#!/bin/sh\\nexit 0\\n")
    open(os.path.join(b, "python"), "w").write(
        "#!__PY__\\nimport os, sys\\n"
        "open(os.environ['CALLS'], 'w').write(' '.join(sys.argv[1:]) + '\\\\n' + os.getcwd() + '\\\\n')\\n"
        "sys.exit(int(os.environ['FAKE_RC']))\\n"
    )
    os.chmod(os.path.join(b, "pip"), 0o755)
    os.chmod(os.path.join(b, "python"), 0o755)
    sys.exit(0)
sys.exit(99)
"""

GH_STUB = """#!__PY__
import os, sys
if os.environ.get("GH_BROKEN"):
    sys.stderr.write("gh: network down\\n")
    sys.exit(1)
# gh api repos/X/commits/<sha>/status --jq ... -> prints the pre-filtered line of <sha>
sha = sys.argv[2].split("/")[-2]
p = os.path.join(os.environ["STATUSES"], sha)
if os.path.exists(p):
    sys.stdout.write(open(p).read())
"""


def _sh(cmd, cwd, env=None):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)


def _stub(directory: Path, name: str, body: str) -> None:
    directory.mkdir(exist_ok=True)
    f = directory / name
    f.write_text(body.replace("__PY__", sys.executable))
    f.chmod(f.stat().st_mode | stat.S_IEXEC)


# ---------------------------------------------------------------- declaration


def test_declared_scripts_are_executable_files():
    tests = yaml.safe_load((ROOT / ".sdlc.yaml").read_text())["tests"]
    for key in ("commande", "local"):
        path = ROOT / tests[key]
        assert path.is_file(), key
        assert os.access(path, os.X_OK), f"{tests[key]} must be executable"


def test_declared_delay_leaves_a_wide_margin():
    delai = str(yaml.safe_load((ROOT / ".sdlc.yaml").read_text())["tests"]["delai"])
    assert delai.endswith(("m", "h"))
    minutes = int(delai[:-1]) * (60 if delai.endswith("h") else 1)
    assert minutes >= 10


def test_report_file_is_ignored_and_not_tracked():
    assert _sh(["git", "ls-files", "resultats.xml"], ROOT).stdout.strip() == ""
    assert _sh(["git", "check-ignore", "resultats.xml"], ROOT).returncode == 0


def test_docker_publish_is_the_only_workflow():
    names = sorted(p.name for p in (ROOT / ".github" / "workflows").glob("*.y*ml"))
    assert names == ["docker-publish.yml"]


# ---------------------------------------------------------------- suite script


def _run_script(name, tmp_path, rc, extra=None):
    _stub(tmp_path / "bin", "python3", PYTHON3_STUB)
    calls = tmp_path / "calls.txt"
    env = {
        **os.environ,
        "PATH": str(tmp_path / "bin") + os.pathsep + os.environ["PATH"],
        "FAKE_RC": str(rc),
        "CALLS": str(calls),
        **(extra or {}),
    }
    return _sh([str(ROOT / "scripts" / name)], tmp_path, env=env), calls


@pytest.mark.parametrize("script", ["suite-attestee.sh", "suite-locale.sh"])
def test_red_suite_makes_the_script_exit_non_zero(script, tmp_path):
    r, calls = _run_script(script, tmp_path, 1)
    assert r.returncode == 1, r.stdout + r.stderr
    assert calls.exists(), "pytest was never invoked"


@pytest.mark.parametrize("script", ["suite-attestee.sh", "suite-locale.sh"])
def test_green_suite_exits_zero_and_asks_for_a_junit_report_from_the_repo_root(script, tmp_path):
    r, calls = _run_script(script, tmp_path, 0)
    assert r.returncode == 0, r.stdout + r.stderr
    args, cwd = calls.read_text().splitlines()
    assert "-m pytest" in args
    assert "--junitxml=resultats.xml" in args
    assert cwd == str(ROOT)


def test_script_leaves_no_venv_behind(tmp_path):
    tmp = tmp_path / "tmpdir"
    tmp.mkdir()
    _run_script("suite-attestee.sh", tmp_path, 1, {"TMPDIR": str(tmp)})
    assert list(tmp.iterdir()) == []


# ---------------------------------------------------------------- attestation job


def _attestation_script() -> str:
    wf = yaml.safe_load(PUBLISH.read_text())
    runs = [s["run"] for s in wf["jobs"]["attestation"]["steps"] if "run" in s]
    assert len(runs) == 1
    return runs[0]


def _git(repo, *args):
    ident = dict(os.environ)
    ident.update(
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@t",
    )
    r = subprocess.run(
        ["git", *args], cwd=repo, env=ident, capture_output=True, text=True, check=True
    )
    return r.stdout.strip()


class World:
    """Repo: c1 (file a), c2 (adds file b), c3 (empty commit, same tree as c2); c4 on demand (new tree)."""

    def __init__(self, tmp_path: Path):
        self.repo = tmp_path / "repo"
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q")
        Path.write_text(self.repo / "a", "a")
        _git(self.repo, "add", "a")
        _git(self.repo, "commit", "-q", "-m", "c1")
        self.c1 = _git(self.repo, "rev-parse", "HEAD")
        Path.write_text(self.repo / "b", "b")
        _git(self.repo, "add", "b")
        _git(self.repo, "commit", "-q", "-m", "c2")
        self.c2 = _git(self.repo, "rev-parse", "HEAD")
        _git(self.repo, "commit", "-q", "--allow-empty", "-m", "c3")
        self.c3 = _git(self.repo, "rev-parse", "HEAD")
        self.marks = tmp_path / "marks"
        os.makedirs(self.marks)
        self.bindir = tmp_path / "ghbin"
        _stub(self.bindir, "gh", GH_STUB)

    def commit_new_tree(self):
        Path.write_text(self.repo / "c", "c")
        _git(self.repo, "add", "c")
        _git(self.repo, "commit", "-q", "-m", "c4")
        self.c4 = _git(self.repo, "rev-parse", "HEAD")

    def attest(self, sha, line):
        Path.write_text(self.marks / sha, line + "\n")

    def run(self, broken=False):
        vars_ = dict(os.environ)
        vars_.update(
            PATH=str(self.bindir) + os.pathsep + os.environ["PATH"],
            STATUSES=str(self.marks),
            GITHUB_REPOSITORY="AntorFr/music-library",
            GH_TOKEN="x",
            GH_BROKEN="1" * broken,
        )
        return _sh(["bash", "-e", "-c", _attestation_script()], self.repo, env=vars_)


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def test_tag_on_attested_commit_passes(world):
    world.attest(world.c3, "success 1622 passed")
    assert world.run().returncode == 0


def test_unattested_empty_follow_up_commit_passes_through_parent_with_same_tree(world):
    world.attest(world.c2, "success 1622 passed")
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert world.c2 in r.stdout


def test_attestation_of_a_parent_with_a_different_tree_is_refused(world):
    world.commit_new_tree()
    world.attest(world.c3, "success old content")
    r = world.run()
    assert r.returncode == 1
    assert "tests-complets" in r.stdout + r.stderr


def test_commit_without_any_attestation_is_refused(world):
    assert world.run().returncode == 1


@pytest.mark.parametrize("state", ["failure", "pending", "error"])
def test_non_success_attestation_is_refused(world, state):
    world.attest(world.c3, f"{state} suite not green")
    world.attest(world.c2, f"{state} suite not green")
    assert world.run().returncode == 1


def test_forge_unreachable_refuses_the_release(world):
    world.attest(world.c3, "success 1622 passed")
    assert world.run(broken=True).returncode == 1
