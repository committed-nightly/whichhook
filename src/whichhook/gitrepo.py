"""Everything this tool knows about a repository, asked of git rather than guessed.

The resolution rule for hooks is not complicated, but it is easy to
reimplement slightly wrong, and git will happily answer the question itself:

    git rev-parse --git-path hooks

That honours ``core.hooksPath``, and in a linked worktree it returns the *common*
directory's hooks -- which is the right answer and not the one you get by
looking next to the worktree's ``.git`` file. So it is the only resolver here.

One wrinkle, measured rather than assumed: ``--git-path`` returns a path
relative to the current directory, so from two levels down it answers
``../../.husky/_``. Every call below runs with ``-C`` at the top level and joins
the result there.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class GitUnavailable(RuntimeError):
    """git is not on PATH."""


class NotARepository(RuntimeError):
    """The path given is not inside a git repository."""


def _run(args: list[str], cwd: str | os.PathLike[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=os.fspath(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - depends on the box
        raise GitUnavailable("git is not on PATH") from exc


def _line(args: list[str], cwd: str | os.PathLike[str]) -> str | None:
    proc = _run(args, cwd)
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out or None


@dataclass(frozen=True)
class ConfigEntry:
    """One ``core.hooksPath`` setting, and where it was set."""

    scope: str  # "local", "global", "system", "worktree", "command"
    origin: str  # e.g. "file:.git/config"
    value: str


@dataclass(frozen=True)
class Repo:
    """A repository, and the facts about it that decide which hooks run."""

    root: Path  # worktree top level, or the git dir for a bare repo
    git_dir: Path
    common_dir: Path
    bare: bool
    hooks_dir: Path  # the one directory git will read hooks from
    hooks_path_settings: tuple[ConfigEntry, ...] = ()
    advice_ignored_hook: bool = True
    git_version: str | None = None

    @property
    def effective_setting(self) -> ConfigEntry | None:
        """The ``core.hooksPath`` that won, or None if nothing set one."""
        return self.hooks_path_settings[-1] if self.hooks_path_settings else None

    @property
    def default_hooks_dir(self) -> Path:
        """Where hooks live when nobody sets ``core.hooksPath``."""
        return self.common_dir / "hooks"

    @property
    def hooks_dir_is_default(self) -> bool:
        return _same(self.hooks_dir, self.default_hooks_dir)

    def display(self, path: Path) -> str:
        """A path as a person would write it: relative to the repo when it is inside."""
        try:
            return os.fspath(path.relative_to(self.root))
        except ValueError:
            return os.fspath(path)


def _same(a: Path, b: Path) -> bool:
    """Whether two paths name the same directory, existing or not."""
    try:
        if a.exists() and b.exists():
            return a.resolve() == b.resolve()
    except OSError:  # pragma: no cover - permissions on a parent
        pass
    return os.path.normpath(a) == os.path.normpath(b)


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def _hooks_path_settings(cwd: Path) -> tuple[ConfigEntry, ...]:
    """Every ``core.hooksPath`` in play, lowest precedence first.

    ``--get-all`` lists system, then global, then local, which is git's own
    precedence order, so the last one is the one that wins and the others are
    places somebody put hooks that will not be read.
    """
    proc = _run(
        ["config", "--show-scope", "--show-origin", "--get-all", "core.hooksPath"],
        cwd,
    )
    if proc.returncode != 0:
        return ()

    entries: list[ConfigEntry] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        scope, origin, value = parts
        if value:
            entries.append(ConfigEntry(scope=scope, origin=origin, value=value))
    return tuple(entries)


def discover(start: str | os.PathLike[str] = ".") -> Repo:
    """Build a :class:`Repo` for the repository containing *start*."""
    start_path = Path(start)
    if not start_path.exists():
        raise NotARepository(f"{start_path}: no such file or directory")
    probe = start_path if start_path.is_dir() else start_path.parent

    inside = _line(["rev-parse", "--is-inside-work-tree"], probe)
    bare_answer = _line(["rev-parse", "--is-bare-repository"], probe)
    if inside is None and bare_answer is None:
        raise NotARepository(f"{start_path}: not a git repository")

    bare = bare_answer == "true"

    git_dir_raw = _line(["rev-parse", "--absolute-git-dir"], probe)
    if git_dir_raw is None:
        raise NotARepository(f"{start_path}: not a git repository")
    git_dir = Path(git_dir_raw)

    top = None if bare else _line(["rev-parse", "--show-toplevel"], probe)
    root = Path(top) if top else git_dir

    common_raw = _line(["rev-parse", "--git-common-dir"], root)
    common_dir = _resolve(root, common_raw) if common_raw else git_dir

    # The authoritative answer. Asked from the top level so the relative path
    # git hands back is relative to somewhere we know.
    hooks_raw = _line(["rev-parse", "--git-path", "hooks"], root)
    hooks_dir = _resolve(root, hooks_raw) if hooks_raw else common_dir / "hooks"

    advice = _line(["config", "--get", "advice.ignoredHook"], root)
    advice_on = advice is None or advice.strip().lower() not in {
        "false",
        "0",
        "no",
        "off",
    }

    version = _line(["--version"], probe)
    if version and version.startswith("git version "):
        version = version[len("git version ") :].strip()

    return Repo(
        root=root,
        git_dir=git_dir,
        common_dir=common_dir,
        bare=bare,
        hooks_dir=hooks_dir,
        hooks_path_settings=_hooks_path_settings(root),
        advice_ignored_hook=advice_on,
        git_version=version,
    )
