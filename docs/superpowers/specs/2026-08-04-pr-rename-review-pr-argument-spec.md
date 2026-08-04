# Take a pull request, not two configured branches

Design, 2026-08-04. Supersedes the `[repo]` section of
`2026-08-02-pr-rename-review-v1-spec.md`.

## The problem

Reviewing a PR takes three things today: a `REPO` export, a `.pr-rename-review.toml`
edited to name `base` and `head`, and a `pr` number in that same file so viewed
ticks sync. Two of the three are derivable from the third. Worse, they can
disagree: nothing checks that `head` is the branch PR `pr` actually proposes, so
a stale `head` reviews one branch while ticking files on another.

A pull request number already names its own base and head. Ask GitHub.

## The surface

```
pr-rename-review serve [PR]     PR = 259 | #259 | https://github.com/o/r/pull/259
pr-rename-review build [PR]
pr-rename-review pairs [PR]
```

Omit `PR` and the tool asks `gh` for the PR of the branch checked out in the
repo. `--repo` (or `$REPO`, or the working directory) still says *which*
checkout.

`--base`/`--head` and `$BASE`/`$HEAD_REF` remain, and gain a sharper meaning:
they skip GitHub entirely. That is the offline path, and it is the path the
pinned replay baseline in `tests/conftest.py` already drives, which is why the
regression suite survives this change untouched.

## Resolving the PR

`gh pr view <spec> --json url,number,baseRefName`, run inside the checkout —
`gh` resolves the repository from its working directory, so every call is made
in `REPO`, never in this tool. The spec is passed to `gh` verbatim; it already
accepts a number, a URL, or nothing.

Owner and repository come from parsing the `url` field, which names the **base**
repository. Today's `resolve_target` reads `headRepositoryOwner`/`headRepository`
instead. On a cross-repository PR those name the fork, and the viewed-state
GraphQL query then runs against a repository that has no such pull request.
Parsing `url` fixes a bug that no same-repo PR could expose.

## Resolving the refs

Pick the git remote whose URL matches that owner/repository, comparing on the
`owner/name` tail so SSH and HTTPS forms both match, and falling back to
`origin`. Then fetch both endpoints into a private namespace:

```sh
git fetch <remote> +refs/pull/259/head:refs/pr-rename-review/259 \
                   +refs/heads/main:refs/pr-rename-review/base/259
```

`refs/pull/N/head` is what makes this uniform. It exists for every pull request,
fork or not, and it is exactly the commit GitHub is showing — no local branch has
to exist, and no fork has to be configured as a remote. The base branch is
fetched the same way rather than read from a remote-tracking branch, so the
result does not depend on the user's fetch configuration.

The two private ref names become `HEAD_REF` and `BASE`. `refs.resolve` then runs
`git merge-base` over them exactly as it does now. Resolving the base to the
merge base rather than to the base branch's tip is still what makes a moving
base safe: against the tip, every commit `main` gained since the fork would show
up inside the review as if the PR had made it. That reasoning currently lives in
a comment in `.pr-rename-review.toml`; it moves to the README.

Forced refspecs (`+`) so re-runs update in place. The private namespace means
nothing the user cares about is written — no remote-tracking branch is created
or moved.

## What threads through the passes

`cli` resolves once per run and puts `PR`, `PR_OWNER` and `PR_REPO` into the
pass environment beside `REPO`, `BASE` and `HEAD_REF`.

`render2.py` reads those three instead of loading config and making its own
`gh repo view` call. One resolution per run, one source of truth, one fewer
network round trip. `github.pr_url` loses its `cfg` parameter and takes the
number directly.

The passes stay scripts run in sequence, communicating through the environment.
That is unchanged and deliberate — see the module docstring in `cli.py`.

## Errors

Today's posture is kept: a stale review that says which commits it used beats no
review at all.

| Situation | Behaviour |
|---|---|
| Fetch fails, private refs exist from an earlier run | Warning, review the refs on disk |
| Fetch fails, no private refs | Hard error — there is nothing to review |
| No `PR` argument, current branch has no PR | Hard error naming the fix: pass one |
| `gh` missing or logged out | Fatal on the PR path, irrelevant on `--base`/`--head` |
| No git remote matches and no `origin` | Hard error naming the remotes found |

## Deletions

- `config.py`
- `.pr-rename-review.toml`
- `tests/test_config.py`
- `github.resolve_target` and `github.resolve_repo`, superseded by `resolve_pr`

`run.sh` and the README both document the config file and must be updated in the
same change.

## Testing

New, against fake runners so no test touches the network:

- `resolve_pr`: bare number, `#`-prefixed, full URL, no spec at all; a
  cross-repository PR resolving to the base repository rather than the fork;
  `gh` missing; `gh` returning an error.
- Remote selection: URL match over `origin`, SSH and HTTPS forms, fallback to
  `origin`, and the no-candidate error.
- The fetch refspec's exact shape, the fetch-failed-but-refs-exist warning, and
  the fetch-failed-and-no-refs error.

Changed:

- `tests/test_cli.py` gains the positional argument reaching the pass
  environment, and `--base`/`--head` bypassing `gh` entirely. It loses
  `test_refs_default_to_config`.

Untouched:

- `tests/conftest.py` and the golden replay. They pin `BASE` and `HEAD_REF` to
  commits and drive the passes directly. The baseline stays
  `BASE=eb1b00665 HEAD_REF=47c9dc7`, and every number in the README's Baseline
  section must still reproduce after this change. That is the acceptance test:
  the input surface changes, the output does not.
