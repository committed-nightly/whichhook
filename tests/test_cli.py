"""Exit codes, flags, and the shape of --json.

Exit codes are the contract anything scripting this tool depends on, so they
are asserted rather than assumed: 0 nothing dead, 1 findings, 2 could not look.
"""

from __future__ import annotations

import json

import pytest

from whichhook.cli import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, run


def test_clean_repo_exits_zero(make_repo, capsys):
    assert run([str(make_repo().root)]) == EXIT_OK
    assert "Nothing installed here is dead" in capsys.readouterr().out


def test_findings_exit_one(make_repo, capsys):
    repo = make_repo()
    repo.hook(".git/hooks/precommit")
    assert run([str(repo.root)]) == EXIT_FINDINGS
    assert "unknown-name" in capsys.readouterr().out


def test_not_a_repo_exits_two(tmp_path, capsys):
    assert run([str(tmp_path)]) == EXIT_USAGE
    assert "not a git repository" in capsys.readouterr().err


def test_exit_zero_flag(make_repo, capsys):
    repo = make_repo()
    repo.hook(".git/hooks/precommit")
    assert run([str(repo.root), "--exit-zero"]) == EXIT_OK
    assert "unknown-name" in capsys.readouterr().out, "still reported, just not fatal"


def test_ignore_suppresses_and_clears_the_exit_code(make_repo, capsys):
    repo = make_repo()
    repo.hook(".git/hooks/precommit")
    assert run([str(repo.root), "--ignore", "unknown-name"]) == EXIT_OK
    assert "unknown-name" not in capsys.readouterr().out


def test_ignore_rejects_a_kind_that_does_not_exist(make_repo):
    with pytest.raises(SystemExit) as exc:
        run([str(make_repo().root), "--ignore", "not-a-kind"])
    assert exc.value.code == EXIT_USAGE


def test_silent_only_drops_the_findings_git_reports(make_repo, capsys):
    repo = make_repo()
    repo.hook(".git/hooks/pre-commit", executable=False)  # git warns about this

    assert run([str(repo.root)]) == EXIT_FINDINGS
    capsys.readouterr()
    assert run([str(repo.root), "--silent-only"]) == EXIT_OK
    assert "not-executable" not in capsys.readouterr().out


def test_silent_only_keeps_the_silent_ones(make_repo):
    repo = make_repo()
    repo.hook(".git/hooks/precommit")
    assert run([str(repo.root), "--silent-only"]) == EXIT_FINDINGS


def test_event_filter(make_repo, capsys):
    repo = make_repo()
    repo.hook(".git/hooks/precommit")  # a pre-commit near-miss
    assert run([str(repo.root), "--event", "pre-push"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "runs on push" in out
    assert "runs on commit" not in out


def test_event_rejects_a_name_git_does_not_know(make_repo):
    with pytest.raises(SystemExit) as exc:
        run([str(make_repo().root), "--event", "pre-comit"])
    assert exc.value.code == EXIT_USAGE


def test_all_lists_every_group(make_repo, capsys):
    assert run([str(make_repo().root), "--all"]) == EXIT_OK
    out = capsys.readouterr().out
    for name in ("p4-changelist", "proc-receive", "sendemail-validate"):
        assert name in out


def test_default_output_hides_the_empty_exotic_groups(make_repo, capsys):
    assert run([str(make_repo().root)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "pre-commit" in out
    assert "p4-changelist" not in out
    assert "see --all" in out


def test_list_hooks(capsys):
    assert run(["--list-hooks"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "pre-commit" in out
    assert "28 hook names" in out


def test_json_shape(make_repo, capsys):
    repo = make_repo()
    repo.hook(".husky/_/pre-commit")
    repo.hook(".git/hooks/pre-commit")
    repo.config("core.hooksPath", ".husky/_")

    assert run([str(repo.root), "--json"]) == EXIT_FINDINGS
    payload = json.loads(capsys.readouterr().out)

    assert payload["hooks_dir"].endswith(".husky/_")
    assert payload["hooks_dir_exists"] is True
    assert payload["hooks_dir_is_default"] is False
    assert payload["runs"]["pre-commit"].endswith(".husky/_/pre-commit")
    assert [s["scope"] for s in payload["hooks_path_settings"]] == ["local"]

    finding = payload["findings"][0]
    assert finding["kind"] == "shadowed"
    assert finding["silent"] is True
    assert finding["hook"] == "pre-commit"
    assert finding["path"].endswith(".git/hooks/pre-commit")


def test_json_respects_ignore(make_repo, capsys):
    repo = make_repo()
    repo.hook(".git/hooks/precommit")
    assert run([str(repo.root), "--json", "--ignore", "unknown-name"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["findings"] == []
