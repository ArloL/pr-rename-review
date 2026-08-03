# pr-rename-review

Reviews a rename-heavy PR that GitHub's diff cannot pair.

GitHub matches a deleted file to an added one by content similarity at a 50%
threshold. A rename that rewrites the domain vocabulary drops far below that,
so the files that changed most are exactly the ones GitHub stops showing side
by side. This tool pairs them from the branch's **recorded moves** instead —
the exact per-commit renames a dedicated rename commit leaves behind — and
word-diffs every file of the PR in one reviewable, tickable page.

Design: `2026-08-02-pr-rename-review-v1-spec.md`. The original proposal, with
the problem analysis and prior-art survey, is
`2026-08-02-pr-rename-review-tool-design.md`.

## Using it

```sh
export REPO=/path/to/the/checkout          # the repo the PR lives in

uv run pr-rename-review serve              # build, serve, open a browser
uv run pr-rename-review build              # passes only, no server
uv run pr-rename-review pairs              # disagreement report, then exit
```

Flags: `--repo`, `--base`, `--head`, `--out`, `--no-build` (serve the existing
`build/`), `--no-browser`. Refs default to `[repo]` in
`.pr-rename-review.toml`.

`serve` rebuilds every time unless told not to. There is no staleness
heuristic on purpose: the passes take seconds, and a heuristic that guesses
wrong serves a stale page that looks current.

`pairs` is useful on its own. It prints the pairing disagreements — the
output that found the mispairings in the first place — and needs no browser.

## What it does

| Script | Pass | Does |
|---|---|---|
| `pairup.py` | 1 | Pairs old→new from the branch's **recorded moves** (exact per-commit renames), falls back to git's endpoint similarity, reports every disagreement |
| `scope.py` | 1b | Works out how GitHub presents each pair, and which have identical blobs |
| `gen2.py` | 3 | Word-diffs each pair |
| `render2.py` | 4 | Emits the page, files ranked by changed tokens |

Pairing needs no vocabulary: keep the renames in their own commit (`git mv`,
commit, then change content in later commits) and every move is recorded as
an exact per-commit rename that similarity guessing can never degrade. Only
moves the history cannot prove — identical-blob shuffles, renames folded
into content commits — fall back to git's endpoint guess.

## Configuration

`.pr-rename-review.toml` names the refs to review and the PR whose Viewed
ticks to sync. Nothing else.

## Viewed state

Per-file **Viewed** ticks are read from and written to GitHub through your own
`gh` login, so a tick in this tool is a tick on the PR and vice versa. The tool
never sees a token: it shells out to `gh api graphql`, and
`viewerViewedState` resolves against whoever holds the credential. That token
identity is why the prototype could not do this — an app token reports the
app's ticks, which are always empty.

Without `gh`, the page still works: viewed state falls back to `localStorage`
and a banner says so. A write GitHub rejects reverts the tick rather than
leaving a file marked reviewed that nobody reviewed.

**Comments are not written by this tool.** Each row carries a ↗ link into
GitHub's own diff; comment there. This is a deliberate non-goal — see the
spec's "Commenting" section for why, and for what would justify changing it.

## Which commits get reviewed

`[repo].base` and `[repo].head` name **moving** refs — `origin/main` and the PR
branch — because the point is to review the PR as it stands. `build` and
`serve` fetch first, so pushing and running again is enough; there is no
separate fetch to forget. A fetch that fails is reported and the build carries
on against the refs already on disk.

The base is resolved to `git merge-base base head`, never to the base branch's
tip. Against the tip, every commit `main` gained since the fork would show up
inside the review as if the PR had made it. The page prints the commits it
actually built from, so a build made before a fetch looks stale rather than
passing for current.

## Baseline

The regression baseline is pinned separately, in `tests/conftest.py`, which is
what lets the config refs move. Against `BASE=52efff3 HEAD_REF=1ce7bfa`
(PR #252): 242 renames, 21 pairing disagreements, 62 reviewable pairs plus 11
identical-blob shuffles, 5,187 → 1,489 residual tokens, 181 frozen, 22 files
cancelling to zero.

```sh
REPO=/path/to/the/checkout uv run pytest
```

The replay compares a fresh run against `tests/golden/` per file, so a failure
names which file changed. Without `REPO` the replay tests skip rather than
fail.

**Pin the head ref to a commit.** `origin/refactor/german-to-english-rename`
moves. An earlier README recorded 24 disagreements / 63 pairs / 5,189 tokens /
23 clean, measured against a state of the branch that has since advanced;
those numbers do not reproduce at any current commit. Re-baselining is a
deliberate act: point `tests/conftest.py` and `[repo].head` at the new commit
and re-capture `tests/golden/`.

## Caveats worth keeping

- **Never pass a pathspec to a rename-detecting diff.** Filtering by the new
  path switches rename detection off silently, because the old path stops
  matching, and you get add/delete back with no warning.
  `tests/test_no_pathspec.py` enforces this.
- **`-l50000` is required.** Git's default rename limit is well below the size
  of a repo-wide rename.
- **Do not pipe the passes into `head`.** They die on SIGPIPE partway through
  and leave a truncated output file — which cost a wrong intermediate answer
  during the prototype work.
- **`gh` resolves the repository from its working directory.** Every `gh` call
  runs inside `REPO`, not inside this tool.
