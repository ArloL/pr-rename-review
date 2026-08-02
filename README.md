# pr-rename-review (prototype)

Throwaway prototype behind
`docs/superpowers/specs/2026-08-02-pr-rename-review-tool-design.md`. It is
committed so that work on the proposal starts from running code, **not**
because it is production tooling. Nothing in the build depends on it.

## What it does

Reviews a rename-heavy PR that GitHub's diff cannot pair. Four passes:

| Script | Pass | Does |
|---|---|---|
| `pairup.py` | 1 | Pairs old→new **by name**, falls back to git similarity, reports every disagreement |
| `scope.py` | 1b | Works out which pairs GitHub actually fails to show, and which have identical blobs |
| `gen2.py` | 3 | Word-diffs each pair with the glossary applied to the old side; marks frozen text; counts residual tokens |
| `render2.py` | 4 | Emits a single self-contained HTML page, files ranked by residual |
| `renamediff.sh` | — | Terminal equivalent for one pair |

Pass 2 of the design — inferring the glossary from the PR — **does not
exist**. `glossary.py` is a hand transcription of the German-to-English
rename tables and is the file that inference is meant to replace.

## Running it

```sh
./run.sh                                                    # main...HEAD
BASE=52efff3 HEAD_REF=origin/refactor/german-to-english-rename ./run.sh
```

Environment: `REPO` (default: git toplevel), `BASE` (default `main`),
`HEAD_REF` (default `HEAD`), `OUT` (default `./build`, gitignored).

Output is `build/hidden-renames.html` plus a log per pass. The pairing
disagreements — the most useful single output — are in `build/pair.log`.

## Known baseline

Against `BASE=52efff3 HEAD_REF=origin/refactor/german-to-english-rename`
(PR #252): 242 renames, 24 pairing disagreements, 63 reviewable pairs,
5,189 → 1,489 residual tokens, 181 frozen, 23 files cancelling to zero,
745 KB page. Treat these as the regression baseline.

## What is hardcoded

- `glossary.py` — the entire vocabulary, German→English only.
- `pairup.py` — `OVERRIDE` and `DIRS` name maps, and the
  `/ausschreibung` → `/tender` package path rule.
- Viewed state is browser `localStorage`. It does not sync with GitHub,
  because `viewerViewedState` resolves against the token holder and an app
  token sees nothing. The design doc covers the fix.

## Caveats worth keeping

- Never pass a pathspec to the rename-detecting diff. Filtering by the new
  path switches rename detection off silently, because the old path stops
  matching, and you get add/delete back with no warning.
- `-l50000` is load-bearing; git's default rename limit is well below the
  size of a repo-wide rename.
- Do not pipe these scripts into `head`. They die on SIGPIPE partway through
  and leave a truncated output file — which cost a wrong intermediate answer
  during the prototype work.
