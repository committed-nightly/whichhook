# whichhook

For every git hook event, say what will actually run in this repository — and
name the hook files that are installed and never will. For anyone who has
wondered whether the pre-commit check they set up months ago is still firing,
and found that the only way to know was to try it.

Git resolves hooks with one rule that surprises people: `core.hooksPath` is not
a search path. It names a single directory, and that directory is the only one
git reads. Everything installed anywhere else is dead, and git does not say so.

## The case it was built for

You install a secret scan in `.git/hooks/pre-commit`. Months later somebody adds
husky, which sets `core.hooksPath` to `.husky/_`. Your scan is still there, still
executable, and no longer runs.

```sh
git init myproject && cd myproject

# A secret scan, installed the way people actually install one.
cat > .git/hooks/pre-commit <<'HOOK'
#!/bin/sh
if git diff --cached | grep -q AKIA; then
  echo "refusing: looks like an AWS key" >&2
  exit 1
fi
HOOK
chmod +x .git/hooks/pre-commit

# Six months later, somebody adds husky. This is the part of `npx husky init`
# that matters -- a hooks directory, and core.hooksPath pointed at it.
mkdir -p .husky/_
git config core.hooksPath .husky/_
printf '#!/bin/sh\necho "husky: lint-staged"\n' > .husky/_/pre-commit
chmod +x .husky/_/pre-commit
```

Git's view of the situation:

```console
$ echo 'AKIAIOSFODNN7EXAMPLE' > creds.txt && git add creds.txt
$ git commit -m "add creds"
husky: lint-staged
[master (root-commit) ea2db13] add creds
 1 file changed, 1 insertion(+)
```

The key went in. Nothing was said about the hook that was meant to stop it.

```console
$ whichhook
repo    /tmp/demo3/myproject
hooks   .husky/_
        core.hooksPath, set in file:.git/config (local)

runs on commit
  pre-commit           .husky/_/pre-commit
  prepare-commit-msg   --
  commit-msg           --
  post-commit          --

runs on push
  pre-push             --

  (8 more groups have nothing installed: merge, checkout, rebase, applying patches, sending email, housekeeping, receiving a push (server side), perforce -- see --all)

1 finding, and git will never mention it.

  shadowed   [silent]
    .git/hooks/pre-commit is executable and will never run.

    core.hooksPath is '.husky/_', set in file:.git/config (local), and
    core.hooksPath is not a search path: the one directory it names is the
    only one git reads. This file is not consulted, not reported, and not
    mentioned -- the event fires, the hook in the winning directory runs
    instead, and the operation succeeds. If it is meant to run, the winning
    hook has to call it.
```

## Install

Python 3.10 or newer, no dependencies.

```sh
git clone https://github.com/committed-nightly/whichhook && cd whichhook
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
```

It is not on PyPI. `pip install git+https://github.com/committed-nightly/whichhook`
works if you would rather not keep the checkout.

## Usage

```sh
whichhook                       # the repository you are standing in
whichhook /path/to/repo
whichhook --event pre-push      # ask about one hook
whichhook --all                 # all 28, including server-side and perforce
whichhook --json
whichhook --list-hooks          # the names git looks for, and nothing else
```

`--strict` additionally reports every file in the hooks directory whose name is
not a hook, rather than only the ones that look like a hook name typed wrong.

### Another real one

A fresh clone of a repository that uses the `pre-commit` framework — including
`pre-commit`'s own:

```console
$ git clone --depth 1 https://github.com/pre-commit/pre-commit
$ whichhook pre-commit
...
1 finding, and git will never mention it.

  manager-not-installed   [silent]
    .pre-commit-config.yaml is committed, but no pre-commit hook in this clone
    mentions pre-commit.
```

This is not a bug in that repository. It is how the framework works: the config
is committed, the hook that runs it is a per-clone step, and nothing enforces
it. Which means the checks are configured, reviewed, and inert for anyone who
did not read the contributing guide.

## What it looks for

Git mentions exactly one of these. The rest it does silently, exits 0, and
leaves for you to discover later — so each finding says which it is.

| kind | does git say anything? |
| --- | --- |
| `shadowed` — a hook in a directory `core.hooksPath` overrode | no |
| `never-read` — a hook in `.githooks/` or similar that nothing points at | no |
| `hooks-dir-missing` — `core.hooksPath` names a directory that isn't there | no |
| `unknown-name` — `pre-commit.sh`, `precommit`, and friends | no |
| `no-op` — installed, executable, runs, contains only comments | no |
| `manager-not-installed` — a manager's config committed, its hook absent | no |
| `not-executable` | **yes**, via `advice.ignoredHook` |
| `crlf-shebang` | yes, but it blames the hook file rather than the line endings |
| `interpreter-missing` | yes, on whichever machine is missing it |

`--silent-only` keeps just the ones git will never mention, which is the useful
setting for CI: the cases git reports are already on somebody's screen.

## Exit codes

| code | meaning |
| --- | --- |
| 0 | nothing installed here is dead |
| 1 | findings |
| 2 | not a git repository, or bad usage |

Use `--exit-zero` to report without failing, and `--ignore KIND` (repeatable) to
suppress a kind for good.

## In CI

Worth a step if your repository *commits* a hooks directory and wires it up with
a setup script, because that wiring is what rots:

```yaml
- run: pip install git+https://github.com/committed-nightly/whichhook
- run: whichhook --silent-only --ignore manager-not-installed
```

Be clear about what this can and cannot see from inside CI. A CI checkout has no
hooks installed — nobody ran the setup script, and `.git/hooks` is not something
you can commit — so `shadowed` and `not-executable` will not appear there even
when they are happening on every developer's laptop. What CI *can* check is the
committed side: a `.githooks/` directory that nothing points at, and hook files
named wrong. `manager-not-installed` is true in CI and uninteresting there,
hence the `--ignore`.

For the rest, run it on your own machine. That is where the answer differs from
one clone to the next, which is the whole problem.

## What it deliberately doesn't do

- **It does not run your hooks.** It reads the repository and reports what git
  would resolve. Whether your hook works when it runs is your test suite's job.
- **It does not detect `--no-verify`.** Nothing can, statically; a hook that
  resolves correctly can still be skipped from the command line.
- **It does not understand hook managers**, beyond noticing that a manager's
  config is committed and its hook is not. If you dispatch hooks some way it
  cannot see, `--ignore manager-not-installed` and it will stop guessing.
- **It ignores directories named after a hook.** The `.githooks/pre-commit/`
  convention, where the hook is a directory of scripts run by a third-party
  dispatcher, is intentional and not something git resolves at all.
- **The hook name list is pinned** to the 28 in `man githooks` at git 2.55.0. A
  newer git adding a name would make `whichhook` call a live hook dead;
  `--list-hooks` prints the list and the version it came from so you can check.

## How the claims were checked

Every statement above about git's behaviour was measured against git 2.55.0
before it was written down, and the test suite re-measures it: each scenario
installs a hook that refuses the commit, attempts a real commit, and asserts
both what git did and that `whichhook` predicted it.

Two of those tests exist because the obvious guess was wrong. A hook with **no
shebang still runs** — git falls back to a shell — so a missing shebang is not a
finding here. And a non-executable hook turned out to be the *one* broken case
git reports itself, which is why the output distinguishes silent findings from
loud ones at all.

```sh
pip install -e ".[dev]" && python -m pytest
```

## Licence

MIT.
