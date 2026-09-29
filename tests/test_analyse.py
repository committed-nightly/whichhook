"""Resolution, and the cases where speaking up would be wrong.

Half of these tests assert that whichhook says *nothing*. A tool that reports a
correctly configured husky repo as broken gets one run and then an entry in
somebody's ignore list, so the quiet cases are as load-bearing as the loud ones.
"""

from __future__ import annotations

import pytest

from whichhook.analyse import analyse
from whichhook.gitrepo import NotARepository, discover


def kinds(analysis) -> set[str]:
    return {f.kind for f in analysis.findings}


def look(root, **kwargs):
    return analyse(discover(root), **kwargs)


# --- resolution ------------------------------------------------------------


def test_default_hooks_directory(make_repo):
    repo = make_repo()
    a = look(repo.root)
    assert a.repo.hooks_dir == repo.root / ".git" / "hooks"
    assert a.repo.hooks_dir_is_default
    assert a.repo.effective_setting is None


def test_relative_hooks_path_resolves_against_the_worktree_root(make_repo):
    """And not against the current directory, which is what --git-path returns."""
    repo = make_repo()
    repo.hook("hooks/pre-commit")
    repo.config("core.hooksPath", "hooks")
    deep = repo.root / "a" / "b"
    deep.mkdir(parents=True)

    from_root = look(repo.root)
    from_deep = look(deep)
    assert from_root.repo.hooks_dir == repo.root / "hooks"
    assert from_deep.repo.hooks_dir == repo.root / "hooks"


def test_absolute_hooks_path(make_repo, tmp_path):
    repo = make_repo()
    elsewhere = tmp_path / "shared-hooks"
    elsewhere.mkdir()
    (elsewhere / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
    (elsewhere / "pre-commit").chmod(0o755)
    repo.config("core.hooksPath", str(elsewhere))

    a = look(repo.root)
    assert a.repo.hooks_dir == elsewhere
    assert "pre-commit" in a.runnable
    assert a.findings == []


def test_not_a_repository(tmp_path):
    with pytest.raises(NotARepository):
        discover(tmp_path)


def test_missing_path(tmp_path):
    with pytest.raises(NotARepository):
        discover(tmp_path / "nope")


# --- the quiet cases -------------------------------------------------------


def test_a_husky_v9_layout_is_clean(make_repo):
    """The layout every husky repo has. Nothing here is wrong.

    `.husky/pre-commit` sits in a directory git does not read, but the wrapper
    in `.husky/_` is what calls it, so reporting it would be a false positive
    on every husky project in existence.
    """
    repo = make_repo()
    repo.hook(".husky/_/pre-commit", '. "${0%/*}/h"')
    repo.hook(".husky/pre-commit", "npx lint-staged")
    repo.write(".husky/_/h", "#!/usr/bin/env sh\n# husky prologue\n")
    repo.config("core.hooksPath", ".husky/_")

    a = look(repo.root)
    assert a.findings == []
    assert "pre-commit" in a.runnable


def test_an_explicit_dispatcher_is_not_reported(make_repo):
    """If the winning hook names the other directory, it is wired up."""
    repo = make_repo()
    repo.hook(".githooks/pre-commit", "exit 0")
    repo.hook(".git/hooks/pre-commit", "exec .githooks/pre-commit")

    a = look(repo.root)
    assert a.findings == []


def test_a_clean_repo_with_no_hooks_at_all(make_repo):
    a = look(make_repo().root)
    assert a.findings == []
    assert a.runnable == {}


def test_helper_files_beside_a_hook_are_not_reported(make_repo):
    repo = make_repo()
    repo.hook(".git/hooks/pre-commit", ". $(dirname $0)/lib.sh")
    repo.write(".git/hooks/lib.sh", "#!/bin/sh\necho hi\n")
    repo.write(".git/hooks/.gitignore", "*\n", executable=False)

    a = look(repo.root)
    assert a.findings == []


def test_strict_reports_helper_files(make_repo):
    repo = make_repo()
    repo.hook(".git/hooks/pre-commit", "exit 0")
    repo.write(".git/hooks/lib.sh", "#!/bin/sh\necho hi\n")

    assert look(repo.root).findings == []
    strict = look(repo.root, strict=True)
    assert kinds(strict) == {"unrecognised"}


# --- the loud cases --------------------------------------------------------


def test_a_conventional_directory_nothing_points_at(make_repo):
    repo = make_repo()
    repo.hook(".githooks/pre-commit", "exit 1")

    a = look(repo.root)
    assert kinds(a) == {"never-read"}
    assert a.findings[0].silent is True


def test_a_conventional_directory_is_quiet_when_something_owns_the_event(make_repo):
    """Conservative on purpose: something already runs, so stay out of it."""
    repo = make_repo()
    repo.hook(".githooks/pre-commit", "exit 1")
    repo.hook(".git/hooks/pre-commit", "echo unrelated")

    assert look(repo.root).findings == []


def test_a_lower_precedence_hooks_path_is_shadowed(make_repo, tmp_path, monkeypatch):
    """A global hooks path, switched off by a repo-local one."""
    global_config = tmp_path / "gitconfig-global"
    org_hooks = tmp_path / "org-hooks"
    org_hooks.mkdir()
    (org_hooks / "pre-push").write_text("#!/bin/sh\n# secret scan\nexit 1\n")
    (org_hooks / "pre-push").chmod(0o755)
    global_config.write_text(f"[core]\n\thooksPath = {org_hooks}\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))

    repo = make_repo()
    repo.hook(".husky/_/pre-push", "exit 0")
    repo.config("core.hooksPath", ".husky/_")

    a = look(repo.root)
    assert [e.scope for e in a.repo.hooks_path_settings] == ["global", "local"]
    assert kinds(a) == {"shadowed"}
    assert a.findings[0].path == org_hooks / "pre-push"


def test_a_no_op_hook(make_repo):
    repo = make_repo()
    repo.write(".git/hooks/pre-commit", "#!/bin/sh\n# TODO: add the linter\n")

    a = look(repo.root)
    assert kinds(a) == {"no-op"}
    assert "pre-commit" in a.runnable, "it does run; it just does nothing"


def test_interpreter_missing(make_repo):
    repo = make_repo()
    repo.write(".git/hooks/pre-commit", "#!/usr/bin/env python3.99\nraise SystemExit(1)\n")
    (repo.root / ".git/hooks/pre-commit").chmod(0o755)

    a = look(repo.root)
    assert kinds(a) == {"interpreter-missing"}
    assert a.findings[0].silent is False


def test_a_present_interpreter_is_not_reported(make_repo):
    repo = make_repo()
    repo.write(".git/hooks/pre-commit", "#!/usr/bin/env sh\nexit 0\n")
    (repo.root / ".git/hooks/pre-commit").chmod(0o755)

    assert look(repo.root).findings == []


def test_pre_commit_framework_configured_but_not_installed(make_repo):
    repo = make_repo()
    repo.write(".pre-commit-config.yaml", "repos: []\n", executable=False)

    a = look(repo.root)
    assert kinds(a) == {"manager-not-installed"}


def test_pre_commit_framework_installed_is_quiet(make_repo):
    repo = make_repo()
    repo.write(".pre-commit-config.yaml", "repos: []\n", executable=False)
    repo.hook(".git/hooks/pre-commit", "exec pre-commit run --hook-stage commit")

    assert look(repo.root).findings == []


def test_findings_are_sorted_silent_first(make_repo):
    repo = make_repo()
    repo.hook(".git/hooks/pre-commit", "exit 0", executable=False)  # git reports it
    repo.hook(".git/hooks/precommit", "exit 0")  # silent

    a = look(repo.root)
    assert [f.silent for f in a.findings] == [True, False]
