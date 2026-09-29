"""Command line entry point."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .analyse import analyse
from .gitrepo import GitUnavailable, NotARepository, discover
from .hooks import HOOK_NAMES, KNOWN_GIT_VERSION
from .report import render_json, render_text

KINDS = (
    "hooks-dir-missing",
    "shadowed",
    "never-read",
    "unknown-name",
    "unrecognised",
    "not-executable",
    "crlf-shebang",
    "interpreter-missing",
    "no-op",
    "manager-not-installed",
)

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="whichhook",
        description=(
            "For every git hook event, say what will actually run in this "
            "repository -- and name the hook files that never will."
        ),
        epilog=(
            "Exit status: 0 nothing dead, 1 findings, 2 could not look. "
            "core.hooksPath is not a search path: the directory it names is "
            "the only one git reads."
        ),
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="a path inside the repository to inspect (default: the current directory)",
    )
    parser.add_argument(
        "--event",
        metavar="HOOK",
        help="ask about one hook only, e.g. --event pre-push",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="list every hook git knows about, including server-side and perforce",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "also report every file in the hooks directory whose name is not a "
            "hook, rather than only the ones that look like a hook name typed "
            "wrong"
        ),
    )
    parser.add_argument(
        "--silent-only",
        action="store_true",
        help=(
            "report only the findings git will never mention, and exit 0 if "
            "those are the only ones missing -- the useful setting for CI, "
            "since the cases git does report are already on somebody's screen"
        ),
    )
    parser.add_argument(
        "--ignore",
        metavar="KIND",
        action="append",
        default=[],
        help=f"suppress a finding kind (repeatable). One of: {', '.join(KINDS)}",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="always exit 0, even with findings",
    )
    parser.add_argument(
        "--list-hooks",
        action="store_true",
        help="print the hook names git looks for, and stop",
    )
    parser.add_argument("--version", action="version", version=f"whichhook {__version__}")
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_hooks:
        print(
            f"{len(HOOK_NAMES)} hook names, from `man githooks` at git "
            f"{KNOWN_GIT_VERSION}."
        )
        print("A file in the hooks directory with any other name is never read.")
        print()
        for name in HOOK_NAMES:
            print(f"  {name}")
        return EXIT_OK

    if args.event is not None and args.event not in HOOK_NAMES:
        parser.error(
            f"{args.event!r} is not a git hook name; `--list-hooks` prints the "
            f"{len(HOOK_NAMES)} that are"
        )

    unknown = [kind for kind in args.ignore if kind not in KINDS]
    if unknown:
        parser.error(f"unknown finding kind to --ignore: {', '.join(unknown)}")

    try:
        repo = discover(args.path)
    except NotARepository as exc:
        print(f"whichhook: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except GitUnavailable as exc:  # pragma: no cover - depends on the box
        print(f"whichhook: {exc}", file=sys.stderr)
        return EXIT_USAGE

    analysis = analyse(repo, strict=args.strict)

    findings = [f for f in analysis.findings if f.kind not in set(args.ignore)]
    if args.event is not None:
        findings = [f for f in findings if f.hook in (args.event, None)]
    if args.silent_only:
        findings = [f for f in findings if f.silent]

    if args.json:
        sys.stdout.write(render_json(analysis, findings=findings))
    else:
        sys.stdout.write(
            render_text(analysis, show_all=args.all, event=args.event, findings=findings)
        )

    if args.exit_zero or not findings:
        return EXIT_OK
    return EXIT_FINDINGS


def main() -> None:  # pragma: no cover - console_scripts shim
    sys.exit(run())
