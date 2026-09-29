"""Fixtures for building throwaway repositories.

The autouse isolation fixture matters more than it looks. Every assertion in
this suite is about how git resolves hooks, and a `core.hooksPath` in the
developer's own global config would change the answer for every test at once
-- quietly, and in the direction of passing. So the global and system config
files are pointed at nothing for the duration.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch, tmp_path_factory):
    """Cut the tests off from whatever git config this machine happens to have."""
    empty = tmp_path_factory.mktemp("gitconfig") / "none"
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(empty))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)
    yield


def git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed:\n{proc.stderr}")
    return proc


class RepoBuilder:
    def __init__(self, root: Path):
        self.root = root
        git("init", "-q", str(root), cwd=root.parent)

    def write(self, relpath: str, content: str, executable: bool = True) -> Path:
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        if executable:
            path.chmod(0o755)
        else:
            path.chmod(0o644)
        return path

    def hook(self, relpath: str, body: str = "exit 0", executable: bool = True) -> Path:
        return self.write(relpath, f"#!/bin/sh\n{body}\n", executable=executable)

    def config(self, key: str, value: str) -> None:
        git("config", key, value, cwd=self.root)

    def commit(self, filename: str = "f") -> subprocess.CompletedProcess[str]:
        """Attempt a real commit, so a test can ask git what it actually did."""
        (self.root / filename).write_text(filename)
        git("add", filename, cwd=self.root)
        return git("commit", "-m", f"add {filename}", cwd=self.root, check=False)


@pytest.fixture
def git_cmd():
    """Raw git, for the handful of tests that need to drive it directly."""
    return git


@pytest.fixture
def make_repo(tmp_path):
    counter = {"n": 0}

    def _make(name: str | None = None) -> RepoBuilder:
        counter["n"] += 1
        root = tmp_path / (name or f"repo{counter['n']}")
        root.mkdir()
        return RepoBuilder(root)

    return _make
