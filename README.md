# pr-rename-review

Reviews a rename-heavy PR that GitHub's diff cannot pair.

GitHub matches a deleted file to an added one by content similarity at a 50%
threshold. A rename that rewrites the domain vocabulary drops far below that,
so the files that changed most are exactly the ones GitHub stops showing side
by side. This tool pairs them **by name** instead, cancels the mechanical part
of the rename, and ranks what is left.

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
| `pairup.py` | 1 | Pairs old→new **by name**, falls back to git similarity, reports every disagreement |
| `scope.py` | 1b | Works out which pairs GitHub actually fails to show, and which have identical blobs |
| `gen2.py` | 3 | Word-diffs each pair with the glossary applied to the old side; marks frozen text; counts residual tokens |
| `render2.py` | 4 | Emits the page, files ranked by residual |
| `renamediff.sh` | — | Terminal equivalent for one pair |

Pass 2 of the design — inferring the glossary from the PR — **is deliberately
not built**. The glossary for PR #252 is already written down, and inference is
where the design risk lives. `.pr-rename-review.toml` is the seam it would plug
into. See the spec's "What v1 is" for the reasoning.

## Configuration

`.pr-rename-review.toml` holds the vocabulary. Data only — the normalization
and pairing logic stays in Python.

Two ordering rules matter, and they differ:

- **`[pairing].words` is an ordered list.** It is applied as a sequence of
  `str.replace` calls, so the plural must precede the singular. Do not sort it.
- **`[glossary]` tables are unordered.** They are sorted longest-source-first
  at compile time, stably, so equal-length keys keep table precedence:
  classes, then words, then columns.

`[glossary.parts]` is component-only vocabulary: it fires inside compound
identifiers but never as a whole word. `haupt` lives there because
`Hauptausschreibung` is a glossary row but a bare `haupt` in German prose is
not a rename.

Two things are asserted at load time, because both fail silently otherwise:
the glossary must be idempotent (`normalize(normalize(x)) == normalize(x)`),
and no two old paths may derive the same new path.

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

## Baseline

Against the **pinned** `BASE=52efff3 HEAD_REF=1ce7bfa` (PR #252): 242 renames,
21 pairing disagreements, 62 reviewable pairs plus 11 identical-blob shuffles,
5,187 → 1,489 residual tokens, 181 frozen, 22 files cancelling to zero.

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
