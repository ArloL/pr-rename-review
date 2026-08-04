# A review tool for renames GitHub cannot pair

- Date: 2026-08-02
- Status: proposal. Partly superseded — see
  `2026-08-02-pr-rename-review-v1-spec.md`, which is the approved v1 and
  narrows this document: no glossary inference, a localhost server, and `gh`
  instead of OAuth. This document remains the record of the problem, the
  measurements, and the prior-art survey.
- Scope: a standalone developer tool. No production code, no runtime
  dependency, nothing shipped to customers.
- Worked example throughout: PR #252 (`refactor/german-to-english-rename`
  → `main`), measured against base `main@52efff3`.

## Problem

A rename-only PR is the case code review is worst at, and PR #252 is a clean
specimen: 242 files move, almost every line in them changes, and none of the
behaviour does. Three distinct failures stack up.

**GitHub does not pair most of the files.** Rename detection matches a
deleted file to an added one by content similarity at a 50% threshold. A
rename that rewrites the domain vocabulary drops far below that. Of the 242
renames on PR #252, GitHub pairs 168 and fails on 74:

| What GitHub renders | Files | Why |
|---|---|---|
| Correct rename, side by side | 168 | above 50% similarity |
| Unrelated delete + add | 62 | below 50% similarity |
| Rename to the **wrong** file | 1 | similarity picked the partner, not the name |
| Rename to the wrong file, but both sides empty | 11 | zero-byte eval fixtures, arbitrary matching |

Lowering the threshold locally is not a fix, and this is the finding that
motivates the whole tool: **below 50%, content similarity starts pairing
files that merely have the same shape.** At `-M01%` git cross-links all
three single-line event records into a cycle (`AusschreibungErstelltEvent`
→ `TenderClassifiedEvent`, `AusschreibungKlassifiziertEvent` →
`TenderExtractedEvent`, `AusschreibungExtrahiertEvent` →
`TenderCreatedEvent`), swaps `Auslastung` and `RemoteAnteil` into each
other's targets, and swaps the `domain/` and `rest/` `package-info.java`
files. Twenty-four pairings disagree with what the names plainly say — 14
eval fixtures, 5 `package-info.java`, 3 events, 2 value objects. A reviewer
who lowers the threshold trades "no pairing" for "confidently wrong
pairing", which is worse.

There is a second, quieter trap: filtering by the new path silently disables
rename detection, because the old path no longer matches the pathspec. The
same command reports `A` or `R` depending on whether you remembered to name
both sides.

**Once paired, the diff is all noise.** A word diff of a renamed file lights
up every renamed token. Across the 63 reviewable pairs that is 5,189
highlighted tokens, of which roughly 3,500 are the mechanical glossary
already fixed by the design doc and 181 are German the rename deliberately
froze. About 1,489 are actual naming decisions. The signal is under 30% of
what is drawn, and it is not clustered — it is scattered one token at a time
through the noise.

**There is no way to hold your place.** Sixty-three files is more than one
sitting. GitHub's per-file *Viewed* ticks live in the GitHub diff, which is
the view that is failing; they do not follow you into whatever you are
actually reading the change in.

## Why not an existing tool

Surveyed before proposing to build. Nothing covers the combination, and one
product is close enough that it should be tried first.

| Tool | Pairs what GitHub won't | Cancels the rename | Marks viewed | Notes |
|---|---|---|---|---|
| [SemanticDiff](https://semanticdiff.com/github/) | unverified | yes, AST-inferred | inherits GitHub | Java supported since 0.8.6. Renders inside GitHub's diff, so it probably inherits GitHub's file list — the failure that matters here. Docs blocked automated fetch; verify by hand. |
| [Reviewable](https://docs.reviewable.io/files.html) | yes, own client-side matching | no | yes, plus scriptable completion conditions | Closest on pairing *and* progress tracking. Still similarity-based, so it inherits the cross-linking hazard. |
| [RAID](https://github.com/rodrigo-brito/refactoring-aware-diff) | no | annotates refactorings | no | RefDiff + Actions + Chrome extension, Java supported. ICPC 2021 research artifact; do not expect maintenance. |
| [difftastic](https://difftastic.wilfred.me.uk/) | no | ignores formatting only | no | Local AST diff. Does not pair files or track state. |
| `git` [textconv](https://git-scm.com/docs/gitattributes) | no | yes, with a normalizer you write | no | Built in. A `.gitattributes` diff driver gets the glossary trick into plain `git diff`, keeping `--word-diff` and `git log -p`. The cheapest partial answer. |

The gap none of them fill is pairing **by name rather than by content**, and
accepting a **supplied or inferred vocabulary** rather than inferring
renames structurally. Those two are what make a rename PR legible.

**Recommendation before building:** spend an hour running SemanticDiff
against PR #252. If it repairs the file list, this proposal is not worth
funding. If it inherits GitHub's pairing — the likely case — it cannot help
with the 74 files that are the actual problem.

## Goals

1. Point it at a PR number or two refs and get a usable review with **no
   configuration**.
2. Pair files by name, and report every disagreement with content-similarity
   pairing rather than silently preferring one.
3. Cancel the mechanical part of a rename, and rank files by what is left.
4. Distinguish text a rename deliberately froze from decisions nobody has
   reviewed.
5. Track viewed state, and sync it with the ticks GitHub already stores.

## Non-goals

- **Not a review platform.** No comments, no approvals, no threads, no CI
  integration. Reviewable and GitHub already do that; this is a reading aid
  that runs beside them.
- **Not a refactoring detector.** No AST, no RefactoringMiner, no
  Extract-Method inference. Token level only — see the decision below.
- **Not a service.** No GitHub App, no webhook, no hosted state, no server
  to operate.
- **Not a rename linter.** It does not judge whether a rename was correct,
  only surfaces the ones nobody agreed in advance.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Pairing | Name-derived first, git similarity only as fallback | Content similarity demonstrably mispairs same-shaped files — 19 times on PR #252, including a three-way cycle |
| Disagreements | Always reported, never silently resolved | The mispairings were the most valuable output of the prototype; hiding them would have hidden the finding |
| Glossary | Inferred from the PR itself; config file optional | Zero-config on any repo. A design-doc-supplied glossary is the special case, not the requirement |
| Diff granularity | Token level, not AST | Per-language AST parsing is the entire cost of SemanticDiff. Tokens cancelled 71% of the noise on a Java PR with ~200 lines of Python |
| Normalization | Applied to the old side only, with phantom marking | Two-sided normalization would hide a *missed* rename, which is exactly what review should catch |
| Output | Static HTML from a CLI | No server, no auth surface, no operational story. The page is a file you can send to someone |
| Viewed state | GitHub GraphQL under the user's own OAuth token | The ticks already exist in GitHub; keeping a second private list is the wrong answer |
| Language | Python 3, stdlib only | The prototype already is. `difflib` does the token diff; no build step, no dependency review |

## Design

Four passes and a renderer. Passes 1, 3 and 5 exist in prototype form
(see "What already exists"); pass 2 is the new work and the thing that makes
the tool general.

### 1. Pairing

For every file the diff reports as deleted or renamed, derive the expected
new path from the old one — apply the path glossary to directory segments,
apply the identifier glossary to the basename — and check whether that path
exists on the head side. If it does, that is the pair. If it does not, fall
back to git's own similarity guess. Then emit three lists:

- pairs where name and similarity agree,
- pairs where they **disagree**, with both candidates and the similarity
  score, flagged in the UI,
- old files with no derivable partner, and new files nothing points at.

Collisions (two old files deriving the same new path) are an error, not a
silent overwrite.

This pass needs `-l50000` on the diff to defeat git's default rename limit,
and must never apply a pathspec filter, for the reason in "Problem".

### 2. Glossary inference — the new work

Everything above still needs a vocabulary. Requiring one is what would stop
this being usable on an arbitrary PR, so infer it:

1. Word-diff every confirmed pair with no normalization.
2. Collect every one-to-one token substitution and count how many distinct
   files and distinct call sites each appears in.
3. Rank by support. `Ausschreibung→Tender` appears in 200+ places;
   `praedikate→predicates` in one file. High support means doctrine, low
   support means a local decision.
4. Split camelCase and snake_case components and re-count, so a compound
   that never appears standalone still contributes to its parts.
5. Present the ranked list as a **proposed** glossary, each entry with its
   support count and one example line, each individually revocable.

The user accepts or rejects entries; the file ranking recomputes. A config
file (`.pr-rename-review.yml`) can pin or exclude entries so the decision
survives to the next run, and a project that already has a rename spec can
paste its table in and skip the inference.

The inference must never be silent. An entry that is accepted has hidden
real diff text, and the page has to say which entries did that and what they
covered.

### 3. Residual diff and phantom marking

Apply the accepted glossary to the old side, then diff. A by-the-book rename
produces identical tokens and vanishes. What stays lit is what the glossary
does not explain.

Because normalization is one-sided, text the rename deliberately kept in the
source language would show as a phantom difference — the old side gets
translated, the new side does not. Detect it: a span pair where
`normalize(new) == old` is frozen text, not a change. Mark it in a third
colour and exclude it from the count. On PR #252 this correctly identifies
the `SORT_EXPRESSIONS` keys in `TenderQueryRepository` as frozen wire
contract rather than 181 tokens of unreviewed decision.

Also treat a pair differing only by case convention (`publicationDate` vs
`publication_date`) as equal. A German word that names both a Java field and
a DB column has two right answers and the glossary can only hold one.

### 4. The page

Static HTML, everything inlined. Side-by-side word diff, files ranked by
residual token count, a raw/cancelled toggle, and filters for *unviewed*,
*has residual*, and *pairing disputed*. The ranking is the product: it puts
the files where the rename made the most unlogged decisions at the top.

### 5. Viewed state

Read `viewerViewedState` on `PullRequestChangedFile` and write
`markFileAsViewed` / `unmarkFileAsViewed` via GraphQL, under the user's own
OAuth token. Both have been in the GitHub GraphQL API [since
2020](https://docs.github.com/en/graphql/overview/changelog/2020).

The token identity matters and is the reason the prototype could not do
this: `viewerViewedState` resolves against whoever holds the token. An app
or bot token reports the *app's* ticks, which are always empty. Only a user
token sees the user's.

Read-only fallback: with no token, or a token lacking scope, keep the state
in browser local storage and say so on the page.

## Hazards

Ranked by how easy it is to ship the bug and not notice.

1. **Inferred glossary over-cancels.** A wrong inferred entry hides real
   changed text, and the whole point of the tool is that hidden text is
   assumed reviewed. This is the one failure mode that makes the tool worse
   than no tool. Mitigations: never auto-accept below a support threshold;
   show every accepted entry with its support and an example; make the raw
   view one keystroke away; and state the count of tokens each entry hid.
2. **Phantom detection depends on `normalize` being near-idempotent** on
   English input. If a glossary entry rewrites its own output, frozen text
   stops being detected and reappears as noise. Assert idempotence over the
   accepted glossary at load time and refuse entries that fail it.
3. **Name-derived pairing is not infallible either.** A file genuinely split
   in two, or merged, has no single right partner. The disagreement report
   is the mitigation — it must be prominent, not a footnote.
4. **OAuth scope.** Writing viewed state on a private repo needs `repo`,
   which is a broad grant for a reading aid. Read-only mode must be fully
   functional without any token, and the write path opt-in.
5. **Payload size.** 63 files inline to roughly 740 KB. A 500-file PR will
   not fit in one page. Either lazy-load per file, or cap and say what was
   dropped — silent truncation would read as "reviewed everything".
6. **Identifier splitting assumes camelCase/snake_case.** Fine for Java,
   Python, Go, TypeScript. Meaningless for Lisp-family or heavily
   abbreviated codebases. Detect and degrade to whole-token matching rather
   than producing confident nonsense.

## Verification

The acceptance criterion is a replay, because we have a fully worked case:

> **Run with no configuration against PR #252 and it must independently
> rediscover all 24 pairing disagreements, and rank `TenderQueryRepository`
> and `TenderServiceImpl` in the top two.**

The prototype in `tools/pr-rename-review/` already produces exactly this
against `BASE=52efff3 HEAD_REF=origin/refactor/german-to-english-rename`:
24 disagreements, 5,189 → 1,489 residual tokens, 181 frozen, 23 files
cancelling to zero. Those numbers are the regression baseline — the
generalized tool must reach them *without* being handed the glossary.

That exercises pairing, inference, and ranking at once, against an answer
established by hand.

Beyond that:

- **Inference recall.** Feed only the diff; assert the inferred glossary
  recovers the high-support entries of the design doc's own glossary table
  (`Ausschreibung→Tender`, `Vermittler→Contact`, `Duplikat→Duplicate`, …).
  Recall on the long tail will be poor and that is fine — the tail is what
  the reviewer is supposed to look at.
- **Phantom precision.** Assert the `SORT_EXPRESSIONS` keys in
  `TenderQueryRepository` are classified frozen, not residual.
- **Idempotence.** `normalize(normalize(x)) == normalize(x)` over the
  accepted glossary, as a load-time assertion (hazard 2).
- **No-pathspec regression test.** Assert the tool's own diff invocation
  never carries a pathspec, since that failure is silent and produced a
  wrong answer during the prototype work.

## Staging

Each stage is useful shipped alone, which is the point of splitting them.

1. **Pairing + disagreement report.** A CLI that prints the three lists.
   This alone would have caught the 19 mispairings and is maybe a day.
2. **Inference + ranking.** Adds the glossary, the residual counts, and the
   ordering. This is where the design risk is (hazard 1).
3. **Page + viewed sync.** The renderer largely exists; the GraphQL sync is
   new.

## What already exists

`tools/pr-rename-review/` carries the throwaway prototype this proposal is
generalized from — roughly 900 lines of Python, hardcoded to PR #252 and to
the German-to-English glossary. It is committed so the next session starts
from working code rather than a blank file, and it is **not** production
tooling.

| File | Lines | Maps to | State |
|---|---|---|---|
| `pairup.py` | 134 | Pass 1 | Works. Found all 24 disagreements. Glossary hardcoded |
| `glossary.py` | 198 | Pass 2 input | Hand-transcribed from the rename design doc. This is the file inference replaces |
| `scope.py` | 51 | Pass 1 output | Works out which pairs GitHub actually fails to show |
| `gen2.py` | 151 | Pass 3 | Works, including phantom marking and case-convention equality |
| `render2.py` | 375 | Pass 4 | Works. Ranking, filters, browser-local viewed state |
| `renamediff.sh` | 57 | — | Terminal equivalent, single pair |

The honest reading: passes 1, 3 and 4 are largely done and need
generalizing; pass 2 does not exist; pass 5 does not exist and was the
blocker that forced the browser-local fallback.

## Prior art

- SemanticDiff — <https://semanticdiff.com/github/>, Java support
  <https://semanticdiff.com/blog/semanticdiff-0.8.6/>
- Reviewable file handling — <https://docs.reviewable.io/files.html>
- RAID — <https://github.com/rodrigo-brito/refactoring-aware-diff>
- difftastic — <https://difftastic.wilfred.me.uk/>
- git textconv diff drivers — <https://git-scm.com/docs/gitattributes>
- GitHub GraphQL viewed-state API —
  <https://docs.github.com/en/graphql/overview/changelog/2020>
