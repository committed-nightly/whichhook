"""Pin every claim whichhook makes to what git actually does.

These are the tests that matter. whichhook's whole output is a prediction --
"this will run", "this never will" -- and a prediction is checkable: put a hook
in place that refuses the commit, try to commit, and see whether git stopped.

Each test below asserts both halves: git's real behaviour, and whichhook
agreeing with it. If a future git changes how hooks resolve, these fail, which
is the point. Two of them exist because the obvious guess was wrong.
"""

from __future__ import annotations

import pytest

from whichhook.analyse import analyse
from whichhook.gitrepo import discover

BLOCK = "exit 1"  # a hook that refuses whatever is happening


def kinds(analysis) -> set[str]:
    return {f.kind for f in analysis.findings}


def look(repo_root):
    return analyse(discover(repo_root))


def test_executable_hook_in_the_default_dir_runs(make_repo):
    repo = make_repo()
    repo.hook(".git/hooks/pre-commit", BLOCK)

    assert repo.commit().returncode != 0, "git should have refused the commit"

    a = look(repo.root)
    assert "pre-commit" in a.runnable
    assert a.findings == []


def test_non_executable_hook_is_skipped_and_git_says_so(make_repo):
    repo = make_repo()
    repo.hook(".git/hooks/pre-commit", BLOCK, executable=False)

    proc = repo.commit()
    assert proc.returncode == 0, "a non-executable hook cannot block anything"
    # The one broken case git mentions itself.
    assert "not set as executable" in proc.stderr

    a = look(repo.root)
    assert "pre-commit" not in a.runnable
    assert kinds(a) == {"not-executable"}
    finding = a.findings[0]
    assert finding.silent is False, "git printed a hint, so this one is not silent"


def test_advice_off_makes_the_non_executable_case_silent(make_repo):
    repo = make_repo()
    repo.hook(".git/hooks/pre-commit", BLOCK, executable=False)
    repo.config("advice.ignoredHook", "false")

    proc = repo.commit()
    assert proc.returncode == 0
    assert "not set as executable" not in proc.stderr

    a = look(repo.root)
    assert a.findings[0].silent is True


def test_hooks_path_shadows_the_default_dir_without_a_word(make_repo):
    """The case the tool exists for: a global check silently switched off."""
    repo = make_repo()
    repo.hook(".git/hooks/pre-commit", BLOCK)  # would refuse the commit
    repo.hook(".husky/_/pre-commit", "exit 0")  # husky's, which allows it
    repo.config("core.hooksPath", ".husky/_")

    proc = repo.commit()
    assert proc.returncode == 0, "the .git/hooks blocker did not run"
    assert "pre-commit" not in proc.stderr, "and git never mentioned it"

    a = look(repo.root)
    assert a.runnable["pre-commit"].path == repo.root / ".husky/_/pre-commit"
    assert kinds(a) == {"shadowed"}
    assert a.findings[0].silent is True
    assert a.findings[0].path == repo.root / ".git/hooks/pre-commit"


def test_hooks_path_at_a_missing_directory_disables_every_hook(make_repo):
    repo = make_repo()
    repo.hook(".git/hooks/pre-commit", BLOCK)
    repo.config("core.hooksPath", ".husky/_")  # never created

    proc = repo.commit()
    assert proc.returncode == 0
    assert proc.stderr.strip() == "" or "hook" not in proc.stderr

    a = look(repo.root)
    assert a.runnable == {}
    assert "hooks-dir-missing" in kinds(a)


@pytest.mark.parametrize("name", ["precommit", "pre-commit.sh", "pre_commit"])
def test_a_misnamed_hook_is_never_read(make_repo, name):
    repo = make_repo()
    repo.hook(f".git/hooks/{name}", BLOCK)

    assert repo.commit().returncode == 0, f"{name} should not be consulted"

    a = look(repo.root)
    assert a.runnable == {}
    assert kinds(a) == {"unknown-name"}
    assert a.findings[0].hook == "pre-commit"


def test_a_hook_with_no_shebang_still_runs(make_repo):
    """Measured, not assumed: git falls back to a shell, so this is no finding.

    This was the first thing this tool got wrong. A missing shebang looks like
    an obvious defect and is not one.
    """
    repo = make_repo()
    repo.write(".git/hooks/pre-commit", "exit 1\n")

    assert repo.commit().returncode != 0, "no shebang, and it still blocked the commit"

    a = look(repo.root)
    assert "pre-commit" in a.runnable
    assert a.findings == []


def test_crlf_line_endings_break_the_hook_confusingly(make_repo):
    repo = make_repo()
    repo.write(".git/hooks/pre-commit", "#!/bin/sh\r\nexit 0\r\n")

    proc = repo.commit()
    assert proc.returncode != 0
    # Git blames the hook file, which exists, rather than the interpreter.
    assert "cannot exec" in proc.stderr
    assert (repo.root / ".git/hooks/pre-commit").exists()

    a = look(repo.root)
    assert kinds(a) == {"crlf-shebang"}


def test_sample_hooks_shipped_by_git_are_not_findings(make_repo):
    """A fresh repo is full of `.sample` files and is not misconfigured."""
    repo = make_repo()
    samples = list((repo.root / ".git/hooks").glob("*.sample"))
    assert samples, "git init should have written sample hooks"

    a = look(repo.root)
    assert a.findings == []
    assert a.runnable == {}


def test_a_worktree_reads_the_common_directory(make_repo, tmp_path, git_cmd):
    repo = make_repo()
    repo.hook(".git/hooks/pre-commit", BLOCK)
    repo.commit("seed")  # blocked, so commit again without the hook
    (repo.root / ".git/hooks/pre-commit").unlink()
    repo.commit("seed")

    linked = tmp_path / "linked"
    git_cmd("worktree", "add", "-q", str(linked), "-b", "wt", cwd=repo.root)

    a = look(linked)
    assert a.repo.hooks_dir == repo.root / ".git" / "hooks"
