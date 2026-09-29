"""The names git looks for, and the events that reach them.

The list is the whole reason this package exists. Git consults these names and
nothing else: a file called ``precommit`` or ``pre-commit.sh`` can sit in the
hooks directory, executable, forever, and git will never read it or mention it.
"""

from __future__ import annotations

# Every hook documented in `man githooks` as of git 2.55.0, in the order the
# man page lists them.
#
# A newer git could add a name that is missing here, and whichhook would then
# call a live hook dead. That direction of error is the one worth knowing
# about, so `--list-hooks` prints the list and the version it came from rather
# than hiding it.
KNOWN_GIT_VERSION = "2.55.0"

HOOK_NAMES: tuple[str, ...] = (
    "applypatch-msg",
    "pre-applypatch",
    "post-applypatch",
    "pre-commit",
    "pre-merge-commit",
    "prepare-commit-msg",
    "commit-msg",
    "post-commit",
    "pre-rebase",
    "post-checkout",
    "post-merge",
    "pre-push",
    "pre-receive",
    "update",
    "proc-receive",
    "post-receive",
    "post-update",
    "reference-transaction",
    "push-to-checkout",
    "pre-auto-gc",
    "post-rewrite",
    "sendemail-validate",
    "fsmonitor-watchman",
    "p4-changelist",
    "p4-prepare-changelist",
    "p4-post-changelist",
    "p4-pre-submit",
    "post-index-change",
)

HOOK_NAME_SET = frozenset(HOOK_NAMES)

# Hooks grouped by the thing you were doing when they fired, because "what runs
# when I commit" is the question people actually have. Every name in HOOK_NAMES
# appears in exactly one group; the test suite enforces that.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("commit", ("pre-commit", "prepare-commit-msg", "commit-msg", "post-commit")),
    ("push", ("pre-push",)),
    ("merge", ("pre-merge-commit", "post-merge")),
    ("checkout", ("post-checkout",)),
    ("rebase", ("pre-rebase", "post-rewrite")),
    (
        "applying patches",
        ("applypatch-msg", "pre-applypatch", "post-applypatch"),
    ),
    ("sending email", ("sendemail-validate",)),
    (
        "housekeeping",
        (
            "pre-auto-gc",
            "post-index-change",
            "reference-transaction",
            "fsmonitor-watchman",
        ),
    ),
    (
        "receiving a push (server side)",
        (
            "pre-receive",
            "update",
            "proc-receive",
            "post-receive",
            "post-update",
            "push-to-checkout",
        ),
    ),
    (
        "perforce",
        (
            "p4-changelist",
            "p4-prepare-changelist",
            "p4-post-changelist",
            "p4-pre-submit",
        ),
    ),
)

# Shown even when nothing is installed for them, because "nothing runs on
# commit" is an answer somebody came here for. The rest of the groups only
# appear when they have something to say, or under --all.
ALWAYS_SHOWN = ("commit", "push")

GROUP_OF = {name: group for group, names in GROUPS for name in names}

# Suffixes people add to a hook and then wonder why nothing happens. Used only
# to decide whether a stray file was *trying* to be a hook -- see
# `near_miss` below.
_SCRIPT_SUFFIXES = (
    ".sh",
    ".bash",
    ".zsh",
    ".py",
    ".rb",
    ".pl",
    ".js",
    ".ts",
    ".ps1",
    ".bat",
    ".cmd",
    ".exe",
)

# Files that legitimately live in a hooks directory without being hooks. Hook
# managers keep their plumbing next to the hooks they install, and reporting
# husky's own wrapper as a mistake would make this tool useless on any repo
# that uses husky.
SUPPORT_FILENAMES = frozenset(
    {
        "husky.sh",  # husky v8's shared prologue
        "h",  # husky v9's, renamed
        "common.sh",
        "README",
        "README.md",
        "LICENSE",
        "Makefile",
    }
)


def _squash(name: str) -> str:
    """Drop the separators and case, so `Pre_Commit` meets `pre-commit`."""
    return "".join(c for c in name.lower() if c.isalnum())


_SQUASHED = {_squash(name): name for name in HOOK_NAMES}


def near_miss(filename: str) -> str | None:
    """The hook this filename was probably meant to be, if any.

    Deliberately narrow. A file called ``helpers.sh`` in a hooks directory is
    not claiming to be a hook and is nobody's bug; ``pre-commit.sh`` and
    ``precommit`` are claiming exactly that and are silently doing nothing.
    Reporting the first kind is how a linter earns its way into somebody's
    ignore list.
    """
    if filename in HOOK_NAME_SET:
        return None

    candidates = [filename]
    lowered = filename.lower()
    for suffix in _SCRIPT_SUFFIXES:
        if lowered.endswith(suffix):
            candidates.append(filename[: -len(suffix)])
            break

    for candidate in candidates:
        hit = _SQUASHED.get(_squash(candidate))
        if hit:
            return hit
    return None
