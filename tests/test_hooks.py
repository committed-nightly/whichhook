"""The hook name table, and the rule for deciding a file meant to be one."""

from __future__ import annotations

import pytest

from whichhook.analyse import _body_is_noop
from whichhook.hooks import ALWAYS_SHOWN, GROUPS, HOOK_NAMES, near_miss


def test_every_hook_is_in_exactly_one_group():
    grouped = [name for _, names in GROUPS for name in names]
    assert sorted(grouped) == sorted(HOOK_NAMES)
    assert len(grouped) == len(set(grouped)), "a hook is listed in two groups"


def test_no_duplicate_hook_names():
    assert len(HOOK_NAMES) == len(set(HOOK_NAMES))


def test_always_shown_groups_exist():
    names = {group for group, _ in GROUPS}
    assert set(ALWAYS_SHOWN) <= names


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("precommit", "pre-commit"),
        ("pre_commit", "pre-commit"),
        ("PreCommit", "pre-commit"),
        ("pre-commit.sh", "pre-commit"),
        ("pre-commit.py", "pre-commit"),
        ("Pre-Commit.BASH", "pre-commit"),
        ("prepushbash", None),
        ("pre-push.sh", "pre-push"),
        ("commitmsg", "commit-msg"),
        # Any run of separators counts, spaces included -- a file called
        # "p4 pre submit" was aiming at the hook and missed.
        ("p4 pre submit", "p4-pre-submit"),
    ],
)
def test_near_miss_catches_the_names_people_actually_type(filename, expected):
    assert near_miss(filename) == expected


@pytest.mark.parametrize("name", HOOK_NAMES)
def test_a_correct_hook_name_is_not_a_near_miss(name):
    assert near_miss(name) is None


@pytest.mark.parametrize(
    "filename",
    ["helpers.sh", "README.md", "lint.py", "config.yaml", "utils", "run-checks.sh"],
)
def test_ordinary_helper_files_are_left_alone(filename):
    """The rule that keeps this tool out of somebody's ignore list."""
    assert near_miss(filename) is None


@pytest.mark.parametrize(
    "body, expected",
    [
        ("#!/bin/sh\n", True),
        ("#!/bin/sh\n# TODO: write this\n", True),
        ("#!/bin/sh\n\n\n   \n", True),
        ("#!/bin/sh\nexit 0\n", False),
        ("#!/bin/sh\n# comment\nnpm test\n", False),
        ("", True),
        ("exit 0\n", False),
    ],
)
def test_no_op_detection(body, expected):
    assert _body_is_noop(body) is expected
