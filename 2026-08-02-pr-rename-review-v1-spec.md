# pr-rename-review v1 — implementation spec

- Date: 2026-08-02
- Status: approved
- Supersedes parts of `2026-08-02-pr-rename-review-tool-design.md`; see
  "Revisions to the proposal" below. That document remains the record of the
  problem and the prior-art survey, and is not restated here.
- Worked example throughout: PR #252 (`refactor/german-to-english-rename` →
  `main`), measured against base `main@52efff3`.

## What v1 is

The proposal describes a general tool for any rename PR. v1 is narrower on
purpose: get PR #252 reviewable by the team now, shaped so the general tool
remains buildable later.

**In scope:**

1. The four existing passes, generalized to read their vocabulary from
   `.pr-rename-review.toml` instead of hardcoded Python.
2. A localhost server, so the page can reach GitHub through the user's own
   `gh` login.
3. Viewed state read from and written to GitHub, so a tick in this tool is a
   tick in GitHub's PR UI and vice versa.

**Out of scope, deliberately:**

- **Glossary inference** (pass 2 of the proposal). The glossary for #252 is
  already written down. Inference is the proposal's stated design risk and
  buys nothing for the PR in front of us. The config file is the seam it
  plugs into later.
- **Lazy loading.** 63 files inline to ~745 KB, which is fine. Revisit at
  the scale where it is not.
- **Comments.** See "Commenting" below.

### Commenting

The proposal's non-goal — "not a review platform" — stands. Line comments
are reached by deep-linking into GitHub's own diff, not by writing through
the GitHub API.

This was considered and rejected for v1 rather than overlooked. Writing
comments means draft state, a submit flow, an indicator for what is unsent,
and a second write path to get wrong. Deep-linking costs one context switch
per comment and no implementation. If the switching proves to be the thing
that hurts across 63 files, that is the evidence that justifies building it,
and the finding will be real rather than assumed.

## Revisions to the proposal

| Proposal | v1 |
|---|---|
| Non-goal: "Not a service. No server." | No *hosted* service. A localhost server, user-started, stateless, bound to `127.0.0.1`. |
| Decision: "Output: static HTML from a CLI" | Page served from localhost so it can reach GitHub through the local process. Still one generated page, still no build step. |
| Decision: "Viewed state under the user's own OAuth token" | Same GraphQL API, authenticated by shelling out to `gh`. The tool never handles a token. |
| Hazard 4: OAuth scope | Deleted. There is no OAuth app and no scope grant. |
| Hazard 5: payload size | Accepted, not mitigated. Out of scope at 63 files. |

Unchanged: pairing by name first, disagreements always reported,
one-sided normalization with phantom marking, token-level diff, Python 3
stdlib only.

## Configuration

`.pr-rename-review.toml`, read from the repo root via `tomllib`. It holds
**data only**. The normalization logic — camelCase splitting, case-preserving
replacement, the ordered regex pass — stays in Python, because it is logic
and not vocabulary.

Ordering matters in one of the two sections, and differently in each:

- **`[pairing].words` is an ordered list** and stays one. `pairup.py` applies
  it as a sequence of `str.replace` calls, so `Ausschreibungen → Tenders` must
  precede `Ausschreibung → Tender` or the plural never matches.
- **`[glossary]` tables are unordered** and may be written in any order.
  `glossary.py` sorts them longest-source-first when it compiles them, which
  is what stops `Ausschreibung → Tender` firing inside
  `AusschreibungDuplikatRepository`. Two properties of that sort must survive
  extraction: it is longest-first, and it is **stable**, so equal-length keys
  keep table precedence — `classes` before `words` before `columns`.

```toml
[repo]
base = "main"
head = "origin/refactor/german-to-english-rename"
pr   = 252              # optional; falls back to `gh pr view --json number`

[pairing]               # was pairup.py OVERRIDE / WORDS / DIRS
path_rules   = [["/ausschreibung", "/tender"]]
basenames    = { "Auslastung.java" = "UtilizationRate.java" }
words        = [["Ausschreibungen", "Tenders"], ["Ausschreibung", "Tender"]]

[pairing.dir_segments]  # scoped: applies only under a matching path prefix
scope    = "/evals/"
segments = { Projekt = "ProjectData", Ausschreibung = "Tender" }

[glossary]              # was glossary.py CLASSES / WORDS / COLUMNS
classes = { AusschreibungRepository = "TenderRepository" }
words   = { Ausschreibung = "Tender" }
columns = { ausschreibung_id = "tender_id" }

[glossary.parts]        # component-only: fires inside compounds, never alone
haupt = "Main"

[glossary.rules]        # ordered regex pass, applied before identifier mapping
patterns = [["\\bausschreibungen\\b", "tenders"]]
```

`[glossary.parts]` exists because the prototype seeds its component table with
one entry that is in none of the three data tables. `Hauptausschreibung →
mainTender` is a glossary row, so `haupt` must fire inside
`hauptAusschreibungId`; but a bare `haupt` in German prompt prose is not a
rename, so it must not become a whole-word rule. Words and classes outrank
this table, and simple columns fill in behind it.

`dir_segments` is scoped rather than global because it is not general
vocabulary: `Projekt → ProjectData` is correct for an eval fixture directory
and wrong everywhere else. Applying it globally would produce confident
nonsense of exactly the kind the proposal warns about.

### Load-time assertions

Both are cheap, and both catch a failure that is otherwise silent.

- **Idempotence** (proposal hazard 2). Refuse a config where
  `normalize(normalize(x)) != normalize(x)` over the config's own values. A
  glossary entry that rewrites its own output breaks phantom detection, and
  frozen text reappears as noise with no error.
- **Collisions** (proposal §1). Two old paths deriving one new path is an
  error at load, not a silent overwrite.

## CLI and server

### Packaging

A `pyproject.toml` with a console script. Teammates run:

```sh
uv run pr-rename-review serve     # run the passes, serve, open browser
uv run pr-rename-review serve --no-build   # serve the existing build/
uv run pr-rename-review build     # passes only, no server
uv run pr-rename-review pairs     # disagreement report to stdout, exit
```

`serve` rebuilds every time unless told not to. There is no staleness
heuristic: the passes take seconds, and a heuristic that guesses wrong serves
a stale page that looks current, which is the failure this whole tool exists
to avoid.

`pairs` stands alone because it is stage 1 of the proposal's staging — the
output that found the 24 mispairings — and it is useful in a terminal with no
page and no browser. `run.sh` stays as a thin shim over `build`.

### Server

`http.server.ThreadingHTTPServer`, bound to `127.0.0.1` on an ephemeral port,
printing its URL on start. Three routes:

| Route | Does |
|---|---|
| `GET /` | the generated page |
| `GET /api/viewed` | `{path: state}` for every file in the PR |
| `POST /api/viewed` | `{path, viewed}` → marks or unmarks, returns new state |

The process holds no state. GitHub is the store. The server exists only
because a browser cannot hold `gh` credentials.

### Authentication

`gh api graphql`, inheriting whoever is logged in. The tool never sees,
stores, or transmits a token. Reads `viewerViewedState` on
`PullRequestChangedFile`; writes `markFileAsViewed` / `unmarkFileAsViewed`.

The token identity that blocked the prototype is resolved by construction:
`viewerViewedState` resolves against the token holder, and `gh` holds the
user's own login, so each teammate sees and writes their own ticks.

### Path mapping

`markFileAsViewed` takes a path, and GitHub only knows the paths in its own
file list. This works out for every file we display:

| Our view | GitHub's view | Markable as |
|---|---|---|
| paired, GitHub agrees (168) | rename | new path |
| paired, GitHub shows delete + add (62) | the new file is a pure addition | new path |
| mispaired (1) and empty fixtures (11) | wrong rename, but the new path is present | new path |

So the page keys viewed state on the **new path** throughout, and a tick here
is the same tick a teammate sees in GitHub.

### Failure modes

All degrade; none break the page.

| Condition | Behaviour |
|---|---|
| `gh` missing or logged out | page loads, viewed state falls back to `localStorage`, banner names the cause and the fix |
| a mark/unmark call fails | that row's tick reverts, error shown on the row, nothing else affected |
| path GitHub does not recognise | row marked local-only and listed in a page footer, never silently dropped |

The `localStorage` path is the proposal's read-only fallback, kept as the
offline mode rather than deleted.

## The page

Four changes, all local to `render2.py`. The keyboard flow is unchanged: `V`
marks viewed and jumps to the next file, `J`/`K` step. That flow is what makes
63 files survivable and nothing here should disturb it.

1. **`save()` becomes a POST** to `/api/viewed`; the initial set comes from
   `GET /api/viewed`. Optimistic update, revert on failure.
2. **Keys are already new paths.** `render2.py` sets `"id": f["new"]`, so the
   viewed set is keyed correctly for the API boundary and needs no change.
3. **GitHub deep links** per file and per line —
   `.../pull/252/files#diff-<sha256 of new path>`, with an `R<line>` suffix
   where a line is identified. This is the commenting story.
4. **A status banner** — synced with GitHub, or local-only with the reason.
5. **The header prose must be corrected.** It currently states that GitHub's
   ticks "aren't readable from an API token, so this page keeps its own … 
   nothing is written back to PR #252". Under v1 that is the opposite of the
   truth, and a page that misdescribes whether it writes to a shared PR is
   worse than one that does not write at all. The hardcoded `#252`, `63`,
   `242` and `168` in that header come from config and payload instead.

## Verification

The acceptance criterion is a replay. Config extraction is a pure refactor, so
any difference in output is a transcription bug:

> Run against the pinned baseline `BASE=52efff3 HEAD_REF=1ce7bfa` with the
> glossary supplied by `.pr-rename-review.toml` and reproduce the prototype's
> output exactly: 242 renames, 21 pairing disagreements, 62 reviewable pairs
> plus 11 identical-blob shuffles, 5,187 → 1,489 residual tokens, 181 frozen,
> 22 files cancelling to zero.

**The head ref must be pinned to a commit, never to
`origin/refactor/german-to-english-rename`.** That ref moves. The figures
originally recorded in the proposal — 24 disagreements, 63 pairs, 5,189
tokens, 23 clean — were measured against an earlier state of the branch and do
not reproduce at any current commit; the difference is three eval fixtures
whose content changed enough that git's similarity pairing now agrees with the
name-derived pairing. The prototype was never wrong. A moving ref as a
regression baseline was.

Diffing `build/diffdata2.json` before and after the extraction is the
mechanical form of this test and catches a mistranscribed entry precisely.

Beyond the replay:

- **Idempotence** over the loaded config, asserted at load time (hazard 2).
- **Collision check** on derived new paths, asserted at load time.
- **No pathspec** ever reaches the rename-detecting diff. This failure is
  silent — filtering by the new path disables rename detection because the
  old path stops matching — and it produced a wrong answer during the
  prototype work.
- **Viewed round-trip**: mark a file, re-read `GET /api/viewed`, confirm it
  returns marked. Then confirm by hand, once, that the file shows as viewed
  in GitHub's own PR UI. That manual check is the whole justification for the
  server and must actually be performed, not assumed.

## Staging

1. **Config extraction.** Move `pairup.py` and `glossary.py` data into
   `.pr-rename-review.toml`; add the load-time assertions. Gated by the
   replay: identical `diffdata2.json`.
2. **Packaging and `pairs`.** `pyproject.toml`, console script, the three
   subcommands. Useful shipped alone.
3. **Server and viewed sync.** The three routes, the `gh` calls, the page
   changes, the fallback banner.

Each is useful on its own, and 1 is the one with a hard pass/fail gate.

## Cleanups carried along

- `gen2.py:124` reads `build/pairs.tsv`, which no pass writes any more, so
  `PREV` is always empty. Remove it — it will otherwise read as meaningful
  during the extraction.

## Hazards specific to v1

1. **Mistranscribing the glossary during extraction.** The most likely bug,
   and invisible without the replay: a dropped entry means real changed text
   stops being cancelled, or worse, stops being *shown* as residual. The
   `diffdata2.json` diff is the mitigation and is not optional.
2. **Optimistic viewed updates diverging from GitHub.** A failed write that
   silently keeps its tick would mean a file marked reviewed that nobody
   reviewed. Reverting on failure is required behaviour, not polish.
3. **The ordered `words` list losing its order** through a config format that
   does not preserve it. TOML arrays do; TOML tables do in Python's `tomllib`
   because dicts are ordered. Anything keyed and re-sorted would break
   longest-first matching silently.
