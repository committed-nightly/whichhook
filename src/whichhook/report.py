"""Rendering. Two formats: one for a person, one for a script."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

from .analyse import Analysis, Finding
from .gitrepo import Repo
from .hooks import ALWAYS_SHOWN, GROUPS

WIDTH = 78
_INDENT = "    "


def _wrap(text: str, indent: str = _INDENT) -> list[str]:
    return textwrap.wrap(
        text,
        width=WIDTH,
        initial_indent=indent,
        subsequent_indent=indent,
        break_long_words=False,
        break_on_hyphens=False,
    )


def _origin(repo: Repo) -> list[str]:
    setting = repo.effective_setting
    if setting is None:
        return ["the repository's own hooks directory -- core.hooksPath is not set"]
    lines = [f"core.hooksPath, set in {setting.origin} ({setting.scope})"]
    losers = repo.hooks_path_settings[:-1]
    for entry in losers:
        lines.append(
            f"overriding core.hooksPath={entry.value!r} from {entry.origin} ({entry.scope})"
        )
    return lines


def _group_lines(analysis: Analysis, groups: list[str]) -> list[str]:
    repo = analysis.repo
    shown = [(group, names) for group, names in GROUPS if group in groups]
    # One column width across every group, so the hook names line up down the
    # whole report rather than per-block.
    pad = max((len(n) for _, names in shown for n in names), default=0)

    out: list[str] = []
    for group, names in shown:
        out.append("")
        out.append(f"runs on {group}")
        for name in names:
            hook = analysis.runnable.get(name)
            target = repo.display(hook.path) if hook else "--"
            out.append(f"  {name.ljust(pad)}   {target}")
    return out


def _which_groups(analysis: Analysis, show_all: bool, event: str | None) -> list[str]:
    if event is not None:
        from .hooks import GROUP_OF

        return [GROUP_OF[event]]
    if show_all:
        return [group for group, _ in GROUPS]
    groups = list(ALWAYS_SHOWN)
    for group, names in GROUPS:
        if group in groups:
            continue
        if any(name in analysis.runnable for name in names):
            groups.append(group)
    return [group for group, _ in GROUPS if group in groups]


def _headline(findings: list[Finding]) -> str:
    silent = sum(1 for f in findings if f.silent)
    total = len(findings)
    if total == 0:
        return "Nothing installed here is dead. Every hook in that directory will run."
    if total == 1:
        if silent:
            return "1 finding, and git will never mention it."
        return "1 finding, which git reports itself."
    if silent == total:
        return f"{total} findings, and git will mention none of them."
    if silent == 0:
        return f"{total} findings, all of which git reports itself."
    return f"{total} findings, {silent} of which git will never mention."


def render_text(
    analysis: Analysis,
    show_all: bool = False,
    event: str | None = None,
    findings: list[Finding] | None = None,
) -> str:
    repo = analysis.repo
    findings = analysis.findings if findings is None else findings
    lines: list[str] = []

    lines.append(f"repo    {repo.root}")
    origin = _origin(repo)
    missing = "" if analysis.hooks_dir_exists else "   (does not exist)"
    lines.append(f"hooks   {repo.display(repo.hooks_dir)}{missing}")
    for extra in origin:
        lines.append(f"        {extra}")
    if repo.bare:
        lines.append("        bare repository")

    lines.extend(_group_lines(analysis, _which_groups(analysis, show_all, event)))

    if not show_all and event is None:
        hidden = [
            group
            for group, names in GROUPS
            if group not in _which_groups(analysis, False, None)
        ]
        if hidden:
            lines.append("")
            lines.append(
                f"  ({len(hidden)} more groups have nothing installed: "
                f"{', '.join(hidden)} -- see --all)"
            )

    lines.append("")
    lines.append(_headline(findings))

    for finding in findings:
        label = "silent" if finding.silent else "git reports it"
        lines.append("")
        lines.append(f"  {finding.kind}   [{label}]")
        lines.extend(_wrap(finding.summary + "."))
        lines.append("")
        lines.extend(_wrap(finding.detail))

    return "\n".join(lines) + "\n"


def render_json(
    analysis: Analysis, findings: list[Finding] | None = None
) -> str:
    repo = analysis.repo
    findings = analysis.findings if findings is None else findings
    payload = {
        "repo": os.fspath(repo.root),
        "git_version": repo.git_version,
        "hooks_dir": os.fspath(repo.hooks_dir),
        "hooks_dir_exists": analysis.hooks_dir_exists,
        "hooks_dir_is_default": repo.hooks_dir_is_default,
        "bare": repo.bare,
        "advice_ignored_hook": repo.advice_ignored_hook,
        "hooks_path_settings": [
            {"scope": e.scope, "origin": e.origin, "value": e.value}
            for e in repo.hooks_path_settings
        ],
        "runs": {
            name: os.fspath(hook.path)
            for name, hook in sorted(analysis.runnable.items())
        },
        "findings": [
            {
                "kind": f.kind,
                "silent": f.silent,
                "path": os.fspath(f.path),
                "hook": f.hook,
                "summary": f.summary,
                "detail": f.detail,
            }
            for f in findings
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"
