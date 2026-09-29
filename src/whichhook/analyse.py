"""Work out what runs, and what is installed and never will.

Every claim about git's behaviour in here was measured against git 2.55.0
before it was written down, because most of them are not documented and two of
the obvious guesses were wrong:

* A hook with no shebang at all *runs* -- git falls back to a shell. So a
  missing shebang is not a finding.
* A non-executable hook is the one broken case git actually mentions, via
  ``advice.ignoredHook``. Everything else in this module is silent: git does
  the wrong thing, exits 0, and says nothing.

That split is the point of the ``silent`` flag on each finding. "git already
told you" and "you will find out in six weeks" deserve different treatment.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .gitrepo import Repo
from .hooks import (
    HOOK_NAME_SET,
    SUPPORT_FILENAMES,
    near_miss,
)

# Directories people put hooks in expecting something to notice. None of these
# is read by git unless core.hooksPath names it.
CONVENTIONAL_DIRS = (
    ".githooks",
    ".git-hooks",
    "githooks",
    "git-hooks",
    ".husky",
    ".hooks",
)

# Hook managers, by the file that gives them away, and the token their own
# installed shim contains.
MANAGERS = (
    (".pre-commit-config.yaml", "pre-commit", "pre-commit"),
    (".pre-commit-config.yml", "pre-commit", "pre-commit"),
    ("lefthook.yml", "lefthook", "lefthook"),
    ("lefthook.yaml", "lefthook", "lefthook"),
    (".lefthook.yml", "lefthook", "lefthook"),
    (".overcommit.yml", "overcommit", "overcommit"),
)

# The hook each manager is overwhelmingly installed for. Checking every hook a
# manager *could* own produces noise; checking the one it is always used for
# produces the finding people need.
MANAGER_HOOK = {
    "pre-commit": "pre-commit",
    "lefthook": "pre-commit",
    "overcommit": "pre-commit",
}


@dataclass(frozen=True)
class HookFile:
    """A file sitting in a hooks directory, and what is wrong with it."""

    path: Path
    name: str
    executable: bool
    shebang: str | None
    crlf_shebang: bool
    interpreter: str | None
    interpreter_found: bool
    is_noop: bool

    @property
    def runs(self) -> bool:
        """Whether git will execute this file when the event fires."""
        return self.executable


@dataclass(frozen=True)
class Finding:
    """One reason a hook that looks installed is not going to run."""

    kind: str
    silent: bool
    path: Path
    hook: str | None
    summary: str
    detail: str

    def sort_key(self) -> tuple[int, str, str]:
        return (0 if self.silent else 1, self.kind, os.fspath(self.path))


@dataclass
class Analysis:
    repo: Repo
    runnable: dict[str, HookFile] = field(default_factory=dict)
    present: dict[str, HookFile] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    hooks_dir_exists: bool = True
    shadowed_dirs: list[Path] = field(default_factory=list)

    @property
    def silent_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.silent]


def _is_executable(path: Path) -> bool:
    """Whether git will treat this file as executable.

    Deliberately reads the mode bits rather than calling ``os.access``: access()
    answers for whoever is running, and root passes it whatever the bits say.
    A linter that changes its verdict when you run it under sudo is worse than
    no linter, and the mode bits are what the repository actually carries.
    """
    try:
        return bool(path.stat().st_mode & 0o111)
    except OSError:
        return False


def _read_text(path: Path, limit: int = 65536) -> str:
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit)
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


def _body_is_noop(text: str) -> bool:
    """Whether the script does nothing at all once you drop the furniture.

    A hook with a shebang and three comments is installed, executable, exits 0,
    and is indistinguishable at the command line from one that is doing its
    job.
    """
    for index, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if index == 0 and stripped.startswith("#!"):
            continue
        if stripped.startswith("#"):
            continue
        return False
    return True


def inspect_file(path: Path) -> HookFile:
    text = _read_text(path)
    first_line = text.split("\n", 1)[0] if text else ""

    shebang = None
    crlf = False
    interpreter = None
    found = True
    if first_line.startswith("#!"):
        crlf = first_line.endswith("\r")
        shebang = first_line.rstrip("\r")
        words = shebang[2:].strip().split()
        if words:
            interpreter = words[0]
            # `#!/usr/bin/env python3` fails on python3, not on env, so the
            # thing worth checking is the argument.
            if os.path.basename(interpreter) == "env" and len(words) > 1:
                interpreter = words[1]
            found = (
                bool(shutil.which(interpreter))
                if not interpreter.startswith("/")
                else Path(interpreter).exists()
            )

    return HookFile(
        path=path,
        name=path.name,
        executable=_is_executable(path),
        shebang=shebang,
        crlf_shebang=crlf,
        interpreter=interpreter,
        interpreter_found=found,
        is_noop=_body_is_noop(text),
    )


def _hook_files(directory: Path) -> list[Path]:
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return []
    return [p for p in entries if p.is_file() and not p.name.endswith(".sample")]


def _candidate_dirs(repo: Repo) -> list[tuple[Path, str]]:
    """Directories that hold hooks git is not going to read.

    ``shadowed`` means git would have read this directory if something had not
    overridden it. ``never-read`` means it was never in the running: a
    convention that only works if ``core.hooksPath`` names it, and nothing
    does.
    """
    out: list[tuple[Path, str]] = []
    seen: set[str] = {os.path.normpath(repo.hooks_dir)}

    def add(path: Path, kind: str) -> None:
        key = os.path.normpath(path)
        if key in seen:
            return
        seen.add(key)
        if path.is_dir():
            out.append((path, kind))

    # The default location, if core.hooksPath moved off it.
    if not repo.hooks_dir_is_default:
        add(repo.default_hooks_dir, "shadowed")

    # A core.hooksPath at a lower precedence than the one that won: a global
    # hooks path is exactly how people install an org-wide secret scan, and a
    # repo-local setting turns it off without a word.
    for entry in repo.hooks_path_settings[:-1]:
        base = repo.root
        value = Path(entry.value).expanduser()
        add(value if value.is_absolute() else base / value, "shadowed")

    for name in CONVENTIONAL_DIRS:
        add(repo.root / name, "never-read")

    return out


def analyse(repo: Repo, strict: bool = False) -> Analysis:
    result = Analysis(repo=repo)
    hooks_dir = repo.hooks_dir
    result.hooks_dir_exists = hooks_dir.is_dir()

    if not result.hooks_dir_exists:
        setting = repo.effective_setting
        if setting is not None:
            result.findings.append(
                Finding(
                    kind="hooks-dir-missing",
                    silent=True,
                    path=hooks_dir,
                    hook=None,
                    summary=(
                        f"core.hooksPath points at {repo.display(hooks_dir)}, "
                        "which does not exist"
                    ),
                    detail=(
                        f"Set in {setting.origin} ({setting.scope}). Git reads hooks "
                        "from that one directory and nowhere else, so with it absent "
                        "no hook runs for any event -- including any hook still "
                        f"sitting in {repo.display(repo.default_hooks_dir)}. Git does "
                        "not warn about this; the commit simply succeeds. The usual "
                        "cause is a directory that an install step creates and the "
                        "install step not having run, which is what `npm ci "
                        "--ignore-scripts` does to husky."
                    ),
                )
            )

    # What is in the winning directory.
    winning_bodies: list[str] = []
    for path in _hook_files(hooks_dir):
        winning_bodies.append(_read_text(path))
        if path.name in HOOK_NAME_SET:
            hook = inspect_file(path)
            result.present[hook.name] = hook
            if hook.runs:
                result.runnable[hook.name] = hook
            continue

        if path.name in SUPPORT_FILENAMES or path.name.startswith("."):
            continue

        intended = near_miss(path.name)
        if intended is not None:
            result.findings.append(
                Finding(
                    kind="unknown-name",
                    silent=True,
                    path=path,
                    hook=intended,
                    summary=(
                        f"{repo.display(path)} is not a hook name -- git looks for "
                        f"{intended!r}"
                    ),
                    detail=(
                        "Git consults an exact list of names and reads nothing else "
                        "in the directory, so this file is never opened. Nothing "
                        "reports it: the event fires, git finds no hook of that "
                        f"name, and the operation succeeds. Rename it to {intended}."
                    ),
                )
            )
        elif strict:
            result.findings.append(
                Finding(
                    kind="unrecognised",
                    silent=True,
                    path=path,
                    hook=None,
                    summary=f"{repo.display(path)} is not a hook name",
                    detail=(
                        "Reported because --strict was given. This file may well be "
                        "a helper that something else sources, in which case it is "
                        "fine where it is."
                    ),
                )
            )

    _check_present(repo, result)
    _check_shadowed(repo, result, winning_bodies)
    _check_managers(repo, result, winning_bodies)

    result.findings.sort(key=Finding.sort_key)
    return result


def _check_present(repo: Repo, result: Analysis) -> None:
    for hook in sorted(result.present.values(), key=lambda h: h.name):
        if not hook.executable:
            result.findings.append(
                Finding(
                    kind="not-executable",
                    silent=not repo.advice_ignored_hook,
                    path=hook.path,
                    hook=hook.name,
                    summary=f"{repo.display(hook.path)} is not executable, so git skips it",
                    detail=(
                        "Git prints a hint about this one -- this is the single "
                        "broken case it mentions -- unless advice.ignoredHook is "
                        "false, and the hint goes to stderr where a CI log will "
                        "swallow it. `chmod +x` fixes it."
                        if repo.advice_ignored_hook
                        else "advice.ignoredHook is false in this repository, so git "
                        "will not print its usual hint. Nothing at all will be "
                        "said. `chmod +x` fixes it."
                    ),
                )
            )
            continue

        if hook.crlf_shebang:
            result.findings.append(
                Finding(
                    kind="crlf-shebang",
                    silent=False,
                    path=hook.path,
                    hook=hook.name,
                    summary=f"{repo.display(hook.path)} has CRLF line endings",
                    detail=(
                        "The carriage return is part of the interpreter path, so the "
                        f"kernel looks for {hook.interpreter!r}+CR and does not find "
                        "it. Git reports this as `cannot exec "
                        f"'{repo.display(hook.path)}': No such file or directory`, "
                        "about a file that is plainly there, which is why this one "
                        "costs an afternoon. Convert to LF, and consider "
                        "`* text=auto` or an entry in .gitattributes."
                    ),
                )
            )
        elif hook.interpreter and not hook.interpreter_found:
            result.findings.append(
                Finding(
                    kind="interpreter-missing",
                    silent=False,
                    path=hook.path,
                    hook=hook.name,
                    summary=(
                        f"{repo.display(hook.path)} wants {hook.interpreter!r}, "
                        "which is not on this box"
                    ),
                    detail=(
                        "This one is loud: the operation fails with the "
                        "interpreter's own error. It is here because it fails on "
                        "whichever machine is missing the interpreter and not on "
                        "yours, so the person who finds out is not the person who "
                        "wrote it."
                    ),
                )
            )

        if hook.is_noop:
            result.findings.append(
                Finding(
                    kind="no-op",
                    silent=True,
                    path=hook.path,
                    hook=hook.name,
                    summary=f"{repo.display(hook.path)} has no code in it",
                    detail=(
                        "Comments and a shebang only. It is installed, it is "
                        "executable, it runs, and it exits 0 -- so from the outside "
                        "it is indistinguishable from a hook that is doing its job."
                    ),
                )
            )


def _check_shadowed(repo: Repo, result: Analysis, winning_bodies: list[str]) -> None:
    blob = "\n".join(winning_bodies)

    for directory, kind in _candidate_dirs(repo):
        files = [p for p in _hook_files(directory) if p.name in HOOK_NAME_SET]
        if not files:
            continue

        # Something in the winning directory may be deliberately dispatching to
        # this one -- husky's own wrapper in `.husky/_` calls the hook in
        # `.husky`, and hand-rolled dispatchers do the same. If the winning
        # hooks mention the directory, it is wired up and not our business.
        dir_label = repo.display(directory)
        if dir_label in blob or directory.name in blob:
            continue

        recorded = False
        for path in files:
            # For a directory git was never going to read, only speak up when
            # nothing runs for that event at all. If something does run, it is
            # very likely the dispatcher we just failed to spot.
            if kind == "never-read" and path.name in result.runnable:
                continue

            if kind == "shadowed":
                setting = repo.effective_setting
                where = (
                    f"core.hooksPath is {setting.value!r}, set in {setting.origin} "
                    f"({setting.scope})"
                    if setting
                    else "core.hooksPath is set"
                )
                detail = (
                    f"{where}, and core.hooksPath is not a search path: the one "
                    "directory it names is the only one git reads. This file is not "
                    "consulted, not reported, and not mentioned -- the event fires, "
                    "the hook in the winning directory runs instead, and the "
                    "operation succeeds. If it is meant to run, the winning hook has "
                    "to call it."
                )
            else:
                detail = (
                    "Nothing points at this directory. Git only reads the directory "
                    "core.hooksPath names, or the repository's own hooks directory "
                    f"when it names none; {dir_label} is a convention, not something "
                    "git knows about. Committing hooks here is fine, but somebody or "
                    "something still has to run `git config core.hooksPath "
                    f"{dir_label}` in every clone."
                )

            result.findings.append(
                Finding(
                    kind="shadowed" if kind == "shadowed" else "never-read",
                    silent=True,
                    path=path,
                    hook=path.name,
                    summary=(
                        f"{repo.display(path)} is executable and will never run"
                        if _is_executable(path)
                        else f"{repo.display(path)} is in a directory git does not read"
                    ),
                    detail=detail,
                )
            )
            recorded = True

        if recorded:
            result.shadowed_dirs.append(directory)


def _check_managers(repo: Repo, result: Analysis, winning_bodies: list[str]) -> None:
    blob = "\n".join(winning_bodies)
    reported: set[str] = set()

    for filename, manager, token in MANAGERS:
        if manager in reported or not (repo.root / filename).is_file():
            continue
        if token in blob:
            continue
        hook_name = MANAGER_HOOK[manager]
        if hook_name in result.runnable:
            # Something else owns that event. Saying the manager is not
            # installed would be a guess, and a wrong one on any repo that
            # chains them.
            continue

        reported.add(manager)
        result.findings.append(
            Finding(
                kind="manager-not-installed",
                silent=True,
                path=repo.root / filename,
                hook=hook_name,
                summary=(
                    f"{filename} is committed, but no {hook_name} hook in this "
                    f"clone mentions {manager}"
                ),
                detail=(
                    f"The config is in the repository; the hook that runs it is not, "
                    "because installing it is a per-clone step that nothing "
                    "enforces. So the checks are configured, reviewed, and never "
                    "run for anyone who did not read the contributing guide. "
                    f"`{manager} install` writes the hook. This is an inference from "
                    f"the absence of any {hook_name} hook mentioning {manager} -- if "
                    "you dispatch it some other way, ignore it with "
                    "--ignore manager-not-installed."
                ),
            )
        )
