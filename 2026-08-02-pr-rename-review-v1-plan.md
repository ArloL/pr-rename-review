# pr-rename-review v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the PR #252 rename-review prototype into a config-driven tool with a localhost server that syncs per-file viewed state with GitHub.

**Architecture:** Four existing passes keep their file-based handoff (`canonical-pairs.tsv` → `scope.json` → `diffdata2.json` → HTML). Their hardcoded German→English vocabulary moves to `.pr-rename-review.toml`. A stateless `http.server` on `127.0.0.1` serves the generated page and proxies viewed-state reads and writes to `gh api graphql`.

**Tech Stack:** Python 3.13 (stdlib only at runtime), `tomllib`, `http.server`, `uv` for packaging and running, `pytest` as the only dev dependency, `gh` CLI for GitHub access.

## Global Constraints

- **Runtime code is stdlib only.** `pytest` is a dev dependency; nothing else is added. This is a decision from the proposal and is not up for renegotiation mid-plan.
- **Python 3.11+** is required (`tomllib`). Pin `requires-python = ">=3.11"`.
- **The replay is the gate.** Tasks 2–6 must leave `build/diffdata2.json` byte-identical to the golden fixture captured in Task 1. Any difference is a transcription bug, not an improvement.
- **Never pass a pathspec** to a rename-detecting `git diff`. Filtering by the new path silently disables rename detection because the old path stops matching. `tests/test_no_pathspec.py` enforces this.
- **`-l50000` is required** on every rename-detecting `git diff`. Git's default rename limit is far below a repo-wide rename.
- **Do not pipe the passes into `head`.** They die on SIGPIPE mid-write and leave a truncated output file.
- **Prefer CLI long options** (`--silent`, not `-s`) in all shell commands and docs.
- The tool never reads, stores, logs, or transmits a GitHub token. All GitHub access is `gh api graphql`.
- Viewed state is keyed on the **new path** everywhere.

## Prerequisites

The replay needs the real repository. Before Task 1, establish:

```sh
export REPO=/path/to/the/hsp/checkout      # the repo PR #252 lives in
export BASE=52efff3
export HEAD_REF=origin/refactor/german-to-english-rename
git -C "$REPO" fetch origin refactor/german-to-english-rename
```

This directory is **not** currently a git repository. Task 1 initialises it, since the plan commits after every task.

---

### Task 1: Repository, test harness, and the golden baseline

Nothing can be safely refactored until the current output is captured. This task changes no behaviour — it freezes it.

**Files:**
- Create: `pyproject.toml`
- Create: `tests/conftest.py`
- Create: `tests/test_replay.py`
- Create: `tests/golden/diffdata2.json` (generated, committed)
- Create: `tests/golden/pair.log` (generated, committed)
- Create: `tests/test_no_pathspec.py`

- [ ] **Step 1: Initialise the repository**

```bash
cd /Users/arlookeeffe/Developer/pr-rename-review
git init
git add --all
git commit --message "chore: import rename-review prototype and v1 spec"
```

- [ ] **Step 2: Add `pyproject.toml`**

```toml
[project]
name = "pr-rename-review"
version = "0.1.0"
description = "Review a rename-heavy PR that GitHub's diff cannot pair"
requires-python = ">=3.11"
dependencies = []

[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

`pythonpath = ["."]` is required. Without it pytest puts only `tests/` on
`sys.path`, and every `import config` / `import glossary` in this plan fails
with `ModuleNotFoundError`.

- [ ] **Step 3: Capture the golden output from the unmodified prototype**

Run the prototype exactly as it stands, then copy its output in. Do this
before any source file is edited — the fixture is only meaningful if it comes
from code known to produce the published numbers.

```bash
REPO="$REPO" BASE=52efff3 HEAD_REF=origin/refactor/german-to-english-rename ./run.sh
mkdir -p tests/golden
cp build/diffdata2.json tests/golden/diffdata2.json
cp build/pair.log tests/golden/pair.log
```

- [ ] **Step 4: Verify the captured baseline matches the published numbers**

```bash
tail --lines=4 build/residual.log
grep --count "" build/pairs2.tsv
grep --extended-regexp "total disagreements" build/pair.log
```

Expected, from the spec's acceptance criterion — **stop and investigate if any
differ**, because the fixture would then freeze the wrong answer:

| Check | Expected |
|---|---|
| reviewable pairs (`pairs2.tsv` lines) | 63 |
| pairing disagreements | 24 |
| residual tokens | 5,189 → 1,489 |
| frozen | 181 |
| cancel to zero | 23 |

- [ ] **Step 5: Write the replay test**

```python
# tests/conftest.py
import json, os, pathlib, subprocess
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "golden"


@pytest.fixture(scope="session")
def repo_env():
    """Environment for a replay against the real PR #252 checkout."""
    repo = os.environ.get("REPO")
    if not repo:
        pytest.skip("set REPO to the checkout PR #252 lives in")
    return {
        **os.environ,
        "REPO": repo,
        "BASE": os.environ.get("BASE", "52efff3"),
        "HEAD_REF": os.environ.get(
            "HEAD_REF", "origin/refactor/german-to-english-rename"),
    }


@pytest.fixture(scope="session")
def rebuilt(tmp_path_factory, repo_env):
    """Run the full pipeline into a scratch directory and return its payload."""
    out = tmp_path_factory.mktemp("build")
    env = {**repo_env, "OUT": str(out)}
    for script in ("pairup.py", "scope.py", "gen2.py"):
        subprocess.run(["python3", str(ROOT / script)], env=env, cwd=ROOT,
                       check=True, capture_output=True, text=True)
    return json.loads((out / "diffdata2.json").read_text())
```

```python
# tests/test_replay.py
import json, pathlib

GOLDEN = pathlib.Path(__file__).resolve().parent / "golden"


def test_replay_matches_golden(rebuilt):
    golden = json.loads((GOLDEN / "diffdata2.json").read_text())

    got = {f["new"]: f for f in rebuilt["files"]}
    want = {f["new"]: f for f in golden["files"]}
    assert sorted(got) == sorted(want), "the set of reviewable pairs changed"

    for path in sorted(want):
        assert got[path] == want[path], f"payload changed for {path}"

    assert rebuilt["empties"] == golden["empties"]


def test_replay_totals(rebuilt):
    files = rebuilt["files"]
    assert len(files) == 63
    assert sum(f["raw_w"] for f in files) == 5189
    assert sum(f["nrm_w"] for f in files) == 1489
    assert sum(f["nrm_ph"] for f in files) == 181
    assert sum(1 for f in files if f["nrm_w"] == 0) == 23
```

Comparing per path before comparing wholesale is deliberate: a bare
`assert rebuilt == golden` on a megabyte of JSON produces an unreadable
failure, and the whole value of this test is telling you *which* file a
mistranscribed glossary entry broke.

- [ ] **Step 6: Write the no-pathspec regression test**

```python
# tests/test_no_pathspec.py
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = ["pairup.py", "scope.py", "gen2.py"]


def test_rename_diffs_carry_no_pathspec():
    """A pathspec silently disables rename detection: the old path stops
    matching, so renames come back as add+delete with no warning."""
    for name in SOURCES:
        text = (ROOT / name).read_text()
        for call in re.findall(r'\["git", "diff".*?\]', text, re.S):
            assert "-M" in call, f"{name}: rename detection missing in {call}"
            assert "-l50000" in call, f"{name}: rename limit missing in {call}"
            assert "--" not in call, f"{name}: pathspec separator in {call}"
```

- [ ] **Step 7: Run the tests and verify they pass against unmodified code**

Run: `uv run pytest --verbose`
Expected: PASS. If `test_replay_matches_golden` fails here, the fixture and the
code disagree before any change was made — stop and resolve that first.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml tests/
git commit --message "test: freeze PR #252 output as the replay baseline"
```

---

### Task 2: Config loading

**Files:**
- Create: `config.py`
- Create: `.pr-rename-review.toml`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `load_config(path: pathlib.Path | None = None) -> Config`, and the dataclass `Config` with fields `base: str`, `head: str`, `pr: int | None`, `pairing: Pairing`, `glossary: GlossaryTables`. `Pairing` has `path_rules: list[tuple[str, str]]`, `basenames: dict[str, str]`, `words: list[tuple[str, str]]`, `dir_scope: str | None`, `dir_segments: dict[str, str]`. `GlossaryTables` has `classes: dict[str, str]`, `words: dict[str, str]`, `columns: dict[str, str]`, `patterns: list[tuple[str, str]]`. Raises `ConfigError` on a malformed file.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
import pathlib, textwrap
import pytest
from config import Config, ConfigError, load_config


def write(tmp_path, body):
    p = tmp_path / ".pr-rename-review.toml"
    p.write_text(textwrap.dedent(body))
    return p


def test_loads_repo_section(tmp_path):
    cfg = load_config(write(tmp_path, """
        [repo]
        base = "main"
        head = "origin/branch"
        pr = 252
    """))
    assert (cfg.base, cfg.head, cfg.pr) == ("main", "origin/branch", 252)


def test_pr_is_optional(tmp_path):
    cfg = load_config(write(tmp_path, """
        [repo]
        base = "main"
        head = "HEAD"
    """))
    assert cfg.pr is None


def test_pairing_words_keep_file_order(tmp_path):
    """Order is significant: the plural must be tried before the singular,
    because pairup applies these as a sequence of str.replace calls."""
    cfg = load_config(write(tmp_path, """
        [repo]
        base = "main"
        head = "HEAD"
        [pairing]
        words = [["Ausschreibungen", "Tenders"], ["Ausschreibung", "Tender"]]
    """))
    assert cfg.pairing.words == [
        ("Ausschreibungen", "Tenders"), ("Ausschreibung", "Tender")]


def test_dir_segments_carry_their_scope(tmp_path):
    cfg = load_config(write(tmp_path, """
        [repo]
        base = "main"
        head = "HEAD"
        [pairing.dir_segments]
        scope = "/evals/"
        segments = { Projekt = "ProjectData" }
    """))
    assert cfg.pairing.dir_scope == "/evals/"
    assert cfg.pairing.dir_segments == {"Projekt": "ProjectData"}


def test_missing_repo_section_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="repo"):
        load_config(write(tmp_path, "[pairing]\n"))


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.toml")


def test_empty_defaults_are_usable(tmp_path):
    """A config with no vocabulary at all must load. Pairing then falls back
    entirely to git similarity, which is a legitimate way to run the tool."""
    cfg = load_config(write(tmp_path, """
        [repo]
        base = "main"
        head = "HEAD"
    """))
    assert cfg.pairing.words == []
    assert cfg.glossary.classes == {}
    assert cfg.glossary.patterns == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py --verbose`
Expected: FAIL, `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Implement `config.py`**

```python
"""Load `.pr-rename-review.toml`. Data only -- all normalization logic lives
in glossary.py, because vocabulary belongs in config and behaviour does not."""
import pathlib
import tomllib
from dataclasses import dataclass, field

DEFAULT_NAME = ".pr-rename-review.toml"


class ConfigError(Exception):
    pass


@dataclass
class Pairing:
    path_rules: list[tuple[str, str]] = field(default_factory=list)
    basenames: dict[str, str] = field(default_factory=dict)
    words: list[tuple[str, str]] = field(default_factory=list)
    dir_scope: str | None = None
    dir_segments: dict[str, str] = field(default_factory=dict)


@dataclass
class GlossaryTables:
    classes: dict[str, str] = field(default_factory=dict)
    words: dict[str, str] = field(default_factory=dict)
    columns: dict[str, str] = field(default_factory=dict)
    patterns: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Config:
    base: str
    head: str
    pr: int | None
    pairing: Pairing
    glossary: GlossaryTables


def _pairs(rows, where):
    out = []
    for row in rows:
        if not (isinstance(row, list) and len(row) == 2):
            raise ConfigError(f"{where}: expected [from, to] pairs, got {row!r}")
        out.append((row[0], row[1]))
    return out


def load_config(path=None):
    path = pathlib.Path(path) if path else pathlib.Path.cwd() / DEFAULT_NAME
    if not path.exists():
        raise ConfigError(f"config not found: {path}")
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)

    repo = raw.get("repo")
    if not repo or "base" not in repo or "head" not in repo:
        raise ConfigError(f"{path}: [repo] must set both base and head")

    p = raw.get("pairing", {})
    dirs = p.get("dir_segments", {})
    pairing = Pairing(
        path_rules=_pairs(p.get("path_rules", []), "pairing.path_rules"),
        basenames=dict(p.get("basenames", {})),
        words=_pairs(p.get("words", []), "pairing.words"),
        dir_scope=dirs.get("scope"),
        dir_segments=dict(dirs.get("segments", {})),
    )

    g = raw.get("glossary", {})
    glossary = GlossaryTables(
        classes=dict(g.get("classes", {})),
        words=dict(g.get("words", {})),
        columns=dict(g.get("columns", {})),
        patterns=_pairs(g.get("rules", {}).get("patterns", []),
                        "glossary.rules.patterns"),
    )

    return Config(base=repo["base"], head=repo["head"], pr=repo.get("pr"),
                  pairing=pairing, glossary=glossary)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py --verbose`
Expected: PASS (8 tests)

- [ ] **Step 5: Write `.pr-rename-review.toml` by transcribing the hardcoded tables**

Transcribe **verbatim**, changing nothing but the syntax:

| From | To |
|---|---|
| `pairup.py:25-54` `OVERRIDE` | `[pairing].basenames` |
| `pairup.py:55-66` `WORDS` | `[pairing].words` — keep list order exactly |
| `pairup.py:68-74` `DIRS` | `[pairing.dir_segments].segments`, with `scope = "/evals/"` |
| `pairup.py:79` `"/ausschreibung" → "/tender"` | `[pairing].path_rules` |
| `glossary.py:11-59` `CLASSES` | `[glossary].classes` |
| `glossary.py:62-86` `WORDS` | `[glossary].words` |
| `glossary.py:89-124` `COLUMNS` | `[glossary].columns` |

Two entries need care because TOML bare keys will not hold them — quote both
keys and both values:

```toml
"duplikat.threshold" = "duplicate.threshold"
"archivierung.cron" = "archiving-schedule.cron"
```

`[glossary.rules].patterns` is empty for PR #252: the prototype has no regex
pass beyond the word tables. Include the empty table so the shape is documented.

Preserve the comments that record *why* an entry is shaped as it is —
`glossary.py:75-76` on why `Ort` is a column and not a word, and
`glossary.py:158-160` on the decomposed `haupt` entry. Those are the reasoning
that stops someone "tidying" the table later.

- [ ] **Step 6: Verify the transcription is complete and faithful**

This is the highest-risk step in the plan, and eyeballing 150 rows does not
catch a dropped one. Compare the TOML against the still-present Python
literals mechanically. Write this scratch script, run it, then delete it — it
only works while both representations exist, which is the point.

```python
# scratch_check.py  (delete at the end of this step -- do not commit)
import tomllib
import glossary, pairup

raw = tomllib.load(open('.pr-rename-review.toml', 'rb'))


def compare(name, got, want):
    missing = {k: want[k] for k in want.keys() - got.keys()}
    extra = {k: got[k] for k in got.keys() - want.keys()}
    changed = {k: (want[k], got[k]) for k in want.keys() & got.keys()
               if want[k] != got[k]}
    assert not (missing or extra or changed), \
        f"{name}: missing={missing} extra={extra} changed={changed}"
    print(f"{name}: {len(want)} entries match")


g, p = raw['glossary'], raw['pairing']
compare('glossary.classes', g['classes'], glossary.CLASSES)
compare('glossary.words', g['words'], glossary.WORDS)
compare('glossary.columns', g['columns'], glossary.COLUMNS)
compare('pairing.basenames', p['basenames'], pairup.OVERRIDE)
compare('pairing.dir_segments',
        p['dir_segments']['segments'], pairup.DIRS)

# order matters here, so compare as a sequence rather than as a mapping
assert [tuple(x) for x in p['words']] == list(pairup.WORDS), \
    "pairing.words differs in content or order"
print(f"pairing.words: {len(pairup.WORDS)} entries match, in order")
```

Run: `uv run python3 scratch_check.py`
Expected: six lines, all reporting a match. Then `rm scratch_check.py`.

- [ ] **Step 7: Commit**

```bash
git add config.py tests/test_config.py .pr-rename-review.toml
git commit --message "feat: load rename vocabulary from .pr-rename-review.toml"
```

---

### Task 3: Glossary reads from config

**Files:**
- Modify: `glossary.py` (replace the data tables at lines 11–124 and 157–166 with config-driven construction; keep `_recase`, `_map_ident`, `CAMEL`, `IDENT` unchanged)
- Modify: `gen2.py:6` (import site)
- Create: `tests/test_glossary.py`

**Interfaces:**
- Consumes: `config.Config`, `config.GlossaryTables` from Task 2.
- Produces: `build_glossary(tables: GlossaryTables) -> Glossary`, where `Glossary` has one public method `normalize(text: str) -> str`. Raises `GlossaryError` when the compiled glossary is not idempotent.

The three behaviours below are subtle, currently correct, and easy to lose in
this refactor. Each has a test.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_glossary.py
import pytest
from config import GlossaryTables
from glossary import GlossaryError, build_glossary


def test_longest_source_wins():
    """Without longest-first ordering, `Ausschreibung` fires inside
    `AusschreibungDuplikat` and produces `TenderDuplikat`."""
    g = build_glossary(GlossaryTables(
        classes={"AusschreibungDuplikat": "TenderDuplicate"},
        words={"Ausschreibung": "Tender"}))
    assert g.normalize("AusschreibungDuplikat") == "TenderDuplicate"


def test_equal_length_keys_keep_table_precedence():
    """The sort is stable and classes are emitted first, so a class entry
    beats a word entry of the same key length."""
    g = build_glossary(GlossaryTables(
        classes={"Quelle": "SourceRef"}, words={"Quelle": "Source"}))
    assert g.normalize("Quelle") == "SourceRef"


def test_lower_camel_variant_is_derived():
    g = build_glossary(GlossaryTables(words={"Ausschreibung": "Tender"}))
    assert g.normalize("ausschreibung") == "tender"


def test_upper_variant_is_derived_for_words_and_columns():
    g = build_glossary(GlossaryTables(
        words={"Quelle": "Source"}, columns={"ausschreibung_id": "tender_id"}))
    assert g.normalize("QUELLE") == "SOURCE"
    assert g.normalize("AUSSCHREIBUNG_ID") == "TENDER_ID"


def test_compound_identifiers_map_component_wise():
    """`AusschreibungPersistenceTest` is not in any table, but its first
    component is, and that is mechanical rather than a naming decision."""
    g = build_glossary(GlossaryTables(words={"Ausschreibung": "Tender"}))
    assert g.normalize("AusschreibungPersistenceTest") == "TenderPersistenceTest"
    assert g.normalize("duplikatRepository") == "duplikatRepository"


def test_component_pass_preserves_case_of_each_part():
    g = build_glossary(GlossaryTables(words={"Ausschreibung": "Tender"}))
    assert g.normalize("hauptAusschreibungId") == "hauptTenderId"


def test_single_component_identifiers_are_left_alone():
    """The component pass requires >= 2 parts, so a bare word only changes
    if a whole-word rule matched it earlier."""
    g = build_glossary(GlossaryTables(words={"Daten": "Data"}))
    assert g.normalize("unrelated") == "unrelated"


def test_word_boundaries_are_respected():
    g = build_glossary(GlossaryTables(columns={"quelle": "source"}))
    assert g.normalize("quelle_x quelle") == "quelle_x source"


def test_columns_seed_parts_only_when_simple():
    """A column key with `_` or `.` is not a single identifier component,
    so it must not enter the component table."""
    g = build_glossary(GlossaryTables(
        columns={"start_datum": "start_date", "titel": "title"}))
    assert g.normalize("titelFeld") == "titleFeld"
    assert g.normalize("startDatumFeld") == "startDatumFeld"


def test_non_idempotent_glossary_is_rejected():
    """An entry that rewrites its own output breaks phantom detection:
    frozen German stops being recognised and reappears as noise."""
    with pytest.raises(GlossaryError, match="idempotent"):
        build_glossary(GlossaryTables(words={"Alpha": "Beta", "Beta": "Gamma"}))


def test_idempotent_glossary_is_accepted():
    build_glossary(GlossaryTables(words={"Ausschreibung": "Tender"}))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_glossary.py --verbose`
Expected: FAIL, `ImportError: cannot import name 'build_glossary'`

- [ ] **Step 3: Rewrite `glossary.py`**

Delete the `CLASSES`, `WORDS`, `COLUMNS` and `PARTS` literals and the
module-level `RULES = _build()`. Keep `_lower1`, `_recase`, `IDENT` and
`CAMEL` exactly as they are. The construction logic moves into a class:

```python
"""Apply a rename glossary to text. The vocabulary comes from
`.pr-rename-review.toml`; only the logic lives here."""
import re

IDENT = re.compile(r"[A-Za-z0-9_]+")
CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+|_+")


class GlossaryError(Exception):
    pass


def _lower1(s):
    return s[0].lower() + s[1:]


def _recase(part, repl):
    if part.isupper() and len(part) > 1:
        return repl.upper()
    if part[:1].islower():
        return repl[0].lower() + repl[1:]
    return repl


class Glossary:
    def __init__(self, rules, parts):
        self._rules = rules
        self._parts = parts

    def _map_ident(self, m):
        tok = m.group(0)
        parts = CAMEL.findall(tok)
        if len(parts) < 2:
            return tok
        out, hit = [], False
        for p in parts:
            r = self._parts.get(p.lower())
            if r and p != "_":
                out.append(_recase(p, r)); hit = True
            else:
                out.append(p)
        return "".join(out) if hit else tok

    def normalize(self, text):
        for pat, repl in self._rules:
            text = pat.sub(repl, text)
        return IDENT.sub(self._map_ident, text)


def _compile_rules(tables):
    rules = []
    for k, v in tables.classes.items():
        rules.append((k, v))
        rules.append((_lower1(k), _lower1(v)))
    for k, v in tables.words.items():
        rules.append((k, v))
        rules.append((_lower1(k), _lower1(v)))
        rules.append((k.upper(), v.upper()))
    for k, v in tables.columns.items():
        rules.append((k, v))
        rules.append((k.upper(), v.upper()))
    # longest source first, so TenderDuplicateRepository wins over Tender.
    # sorted() is stable, so equal-length keys keep table precedence:
    # classes, then words, then columns.
    rules.sort(key=lambda kv: -len(kv[0]))
    compiled = [(re.compile(p), r) for p, r in tables.patterns]
    return compiled + [(re.compile(r"\b" + re.escape(k) + r"\b"), v)
                       for k, v in rules]


def _compile_parts(tables):
    parts = {}
    for k, v in list(tables.words.items()) + list(tables.classes.items()):
        parts[k.lower()] = v
    for k, v in tables.columns.items():
        if "_" not in k and "." not in k:
            parts.setdefault(k.lower(), v[0].upper() + v[1:])
    return parts


def build_glossary(tables):
    g = Glossary(_compile_rules(tables), _compile_parts(tables))
    _assert_idempotent(g, tables)
    return g


def _assert_idempotent(g, tables):
    """normalize(normalize(x)) must equal normalize(x). An entry that
    rewrites its own output makes phantom detection unreliable, and the
    symptom -- frozen German reappearing as residual noise -- looks like a
    reviewing problem rather than a config bug."""
    probes = set(tables.classes) | set(tables.words) | set(tables.columns)
    probes |= set(tables.classes.values()) | set(tables.words.values())
    probes |= set(tables.columns.values())
    for probe in sorted(probes):
        once = g.normalize(probe)
        twice = g.normalize(once)
        if once != twice:
            raise GlossaryError(
                f"glossary is not idempotent: {probe!r} -> {once!r} -> {twice!r}")
```

Note `patterns` is prepended, matching the spec's "applied before identifier
mapping" and giving the ordered regex pass priority over the word tables.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_glossary.py --verbose`
Expected: PASS (11 tests)

- [ ] **Step 5: Wire `gen2.py` to the config-built glossary**

Replace `gen2.py:6` (`from glossary import normalize`) with construction from
config, and leave every call site reading `normalize(...)` unchanged:

```python
from config import load_config
from glossary import build_glossary

CFG = load_config(S / ".pr-rename-review.toml")
normalize = build_glossary(CFG.glossary).normalize
```

In the same pass, delete the dead `PREV` block at `gen2.py:122-125`. It reads
`build/pairs.tsv`, which no pass has written since the prototype was split, so
`PREV` is always empty and every file's `prev` flag is always `False`. Left in
place it reads as meaningful during this refactor.

Replace `prev=new in PREV` at `gen2.py:143` with `prev=False`, and keep the
key in the payload — `render2.py:29` and its `prev` tag in `drawIndex` still
reference it, and removing the field is churn this task does not need. The
replay proves the flag was already always `False`.

- [ ] **Step 6: Run the replay**

Run: `uv run pytest --verbose`
Expected: PASS, including `test_replay_matches_golden`.

If the replay fails, the failure names the file whose payload changed. Diff
that file's entry between golden and rebuilt — the cause is a dropped or
altered glossary entry from Task 2's transcription, not a logic error here.

- [ ] **Step 7: Commit**

```bash
git add glossary.py gen2.py tests/test_glossary.py
git commit --message "refactor: build the glossary from config, assert idempotence"
```

---

### Task 4: Pairing reads from config

**Files:**
- Modify: `pairup.py` (replace `OVERRIDE`/`WORDS`/`DIRS` at lines 24–74 and `expect` at 77–87; keep the diff invocation and reporting)
- Create: `tests/test_pairing.py`

**Interfaces:**
- Consumes: `config.Pairing` from Task 2.
- Produces: `expected_path(old: str, pairing: Pairing) -> str` and `check_collisions(canon: dict[str, str]) -> None`, which raises `PairingError` listing every new path claimed by more than one old path.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pairing.py
import pytest
from config import Pairing
from pairup import PairingError, check_collisions, expected_path


def test_path_rules_apply_to_directories_only():
    p = Pairing(path_rules=[("/ausschreibung", "/tender")])
    assert expected_path("src/de/ausschreibung/Foo.java", p) == \
        "src/de/tender/Foo.java"


def test_basename_override_beats_word_substitution():
    """A semantic rename is not word-for-word, so the override must win
    outright rather than being applied on top of the word list."""
    p = Pairing(basenames={"Auslastung.java": "UtilizationRate.java"},
                words=[("Auslastung", "Workload")])
    assert expected_path("a/Auslastung.java", p) == "a/UtilizationRate.java"


def test_words_apply_in_file_order():
    p = Pairing(words=[("Ausschreibungen", "Tenders"),
                       ("Ausschreibung", "Tender")])
    assert expected_path("a/AusschreibungenRepo.java", p) == "a/TendersRepo.java"


def test_reversed_word_order_would_break_the_plural():
    """Documents why order is significant, so nobody sorts the table."""
    p = Pairing(words=[("Ausschreibung", "Tender"),
                       ("Ausschreibungen", "Tenders")])
    assert expected_path("a/AusschreibungenRepo.java", p) == "a/TenderenRepo.java"


def test_dir_segments_apply_only_inside_their_scope():
    p = Pairing(dir_scope="/evals/", dir_segments={"Projekt": "ProjectData"})
    assert expected_path("t/evals/Projekt/a.json", p) == "t/evals/ProjectData/a.json"
    assert expected_path("src/Projekt/a.json", p) == "src/Projekt/a.json"


def test_dir_segments_match_whole_segments_only():
    p = Pairing(dir_scope="/evals/", dir_segments={"Projekt": "ProjectData"})
    assert expected_path("t/evals/ProjektAlt/a.json", p) == \
        "t/evals/ProjektAlt/a.json"


def test_file_with_no_directory():
    p = Pairing(words=[("Ausschreibung", "Tender")])
    assert expected_path("Ausschreibung.java", p) == "Tender.java"


def test_collisions_are_an_error():
    with pytest.raises(PairingError, match="new/Tender.java"):
        check_collisions({"a/Alt.java": "new/Tender.java",
                          "b/Alt.java": "new/Tender.java"})


def test_no_collisions_passes():
    check_collisions({"a.java": "b.java", "c.java": "d.java"})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_pairing.py --verbose`
Expected: FAIL, `ImportError: cannot import name 'expected_path'`

- [ ] **Step 3: Rewrite the pairing logic in `pairup.py`**

```python
from config import load_config

CFG = load_config(pathlib.Path(SP) / ".pr-rename-review.toml")


class PairingError(Exception):
    pass


def expected_path(old, pairing):
    """Derive the new path from the old one by name alone. Content
    similarity is never consulted here -- that is the whole point."""
    d, b = os.path.split(old)
    for a, z in pairing.path_rules:
        d = d.replace(a, z)
    if pairing.dir_segments and (
            pairing.dir_scope is None or pairing.dir_scope in f"{d}/"):
        d = "/".join(pairing.dir_segments.get(seg, seg) for seg in d.split("/"))
    if b in pairing.basenames:
        b = pairing.basenames[b]
    else:
        for a, z in pairing.words:
            b = b.replace(a, z)
    return f"{d}/{b}" if d else b


def check_collisions(canon):
    """Two old paths deriving one new path is ambiguous, and silently
    keeping the last one would drop a file from the review entirely."""
    seen = {}
    for old, new in canon.items():
        seen.setdefault(new, []).append(old)
    clashes = {new: olds for new, olds in seen.items() if len(olds) > 1}
    if clashes:
        detail = "; ".join(f"{new} <- {', '.join(sorted(olds))}"
                           for new, olds in sorted(clashes.items()))
        raise PairingError(f"two old paths derive the same new path: {detail}")
```

Replace the call `n = expect(o)` at `pairup.py:107` with
`n = expected_path(o, CFG.pairing)`, and replace the printed `collisions`
line at `pairup.py:128-129` with `check_collisions(canon)`.

Note the scope check tests `d + "/"`, so a scope of `/evals/` matches a
directory that *ends* at `evals` as well as one that contains it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_pairing.py --verbose`
Expected: PASS (9 tests)

- [ ] **Step 5: Run the replay and check the disagreement report is unchanged**

```bash
uv run pytest --verbose
REPO="$REPO" BASE=52efff3 HEAD_REF=origin/refactor/german-to-english-rename ./run.sh
diff tests/golden/pair.log build/pair.log && echo "pairing report unchanged"
```

Expected: tests PASS, `diff` reports no differences, and the report still ends
`total disagreements: 24`.

- [ ] **Step 6: Commit**

```bash
git add pairup.py tests/test_pairing.py
git commit --message "refactor: derive pairing from config, raise on collisions"
```

---

### Task 5: Package and CLI

**Files:**
- Create: `cli.py`
- Modify: `pyproject.toml` (add the console script and module list)
- Modify: `run.sh` (delegate to the CLI)
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_config` (Task 2); the four pass scripts as subprocesses.
- Produces: `main(argv: list[str] | None = None) -> int` and the console script `pr-rename-review`. Subcommands: `build`, `pairs`, `serve`. `serve` is added in Task 7; this task registers it and exits with a clear message.

The passes stay as scripts run in sequence rather than becoming imported
functions. That is deliberate: importing them means restructuring their
module-level bodies, which is exactly the churn the replay gate is protecting
against. The CLI is a driver, not a rewrite.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
import pytest
from cli import main


def test_no_arguments_prints_usage_and_fails(capsys):
    assert main([]) == 2
    assert "build" in capsys.readouterr().err


def test_unknown_subcommand_fails(capsys):
    with pytest.raises(SystemExit):
        main(["frobnicate"])


def test_build_accepts_ref_overrides(monkeypatch):
    seen = {}
    monkeypatch.setattr("cli.run_passes",
                        lambda passes, env: seen.update(env) or 0)
    assert main(["build", "--base", "abc", "--head", "def"]) == 0
    assert seen["BASE"] == "abc"
    assert seen["HEAD_REF"] == "def"


def test_pairs_runs_only_the_pairing_pass(monkeypatch):
    seen = {}
    monkeypatch.setattr("cli.run_passes",
                        lambda passes, env: seen.update(p=passes) or 0)
    assert main(["pairs"]) == 0
    assert seen["p"] == ["pairup.py"]


def test_build_runs_all_four_passes(monkeypatch):
    seen = {}
    monkeypatch.setattr("cli.run_passes",
                        lambda passes, env: seen.update(p=passes) or 0)
    main(["build"])
    assert seen["p"] == ["pairup.py", "scope.py", "gen2.py", "render2.py"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py --verbose`
Expected: FAIL, `ModuleNotFoundError: No module named 'cli'`

- [ ] **Step 3: Implement `cli.py`**

```python
"""Driver for the rename-review passes."""
import argparse, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent
ALL_PASSES = ["pairup.py", "scope.py", "gen2.py", "render2.py"]


def run_passes(passes, env):
    """Run each pass in order, logging full output and echoing the tail.
    Never pipe these into `head`: they die on SIGPIPE mid-write and leave a
    truncated output file."""
    out = pathlib.Path(env["OUT"])
    out.mkdir(parents=True, exist_ok=True)
    for name in passes:
        stem = name.removesuffix(".py")
        print(f"== {stem}", file=sys.stderr)
        proc = subprocess.run([sys.executable, str(ROOT / name)],
                              env=env, cwd=ROOT, capture_output=True, text=True)
        (out / f"{stem}.log").write_text(proc.stdout)
        if proc.returncode:
            sys.stderr.write(proc.stderr)
            return proc.returncode
        print("\n".join(proc.stdout.splitlines()[-4:]), file=sys.stderr)
    return 0


def _env(args):
    from config import load_config
    cfg = load_config(ROOT / ".pr-rename-review.toml")
    return {**os.environ,
            "REPO": args.repo or os.environ.get("REPO", ""),
            "BASE": args.base or cfg.base,
            "HEAD_REF": args.head or cfg.head,
            "OUT": args.out or os.environ.get("OUT", str(ROOT / "build"))}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="pr-rename-review")
    parser.add_argument("--repo"), parser.add_argument("--base")
    parser.add_argument("--head"), parser.add_argument("--out")
    sub = parser.add_subparsers(dest="cmd")
    for name in ("build", "pairs", "serve"):
        sub.add_parser(name, parents=[], add_help=True)
    args = parser.parse_args(argv)

    if not args.cmd:
        parser.print_usage(sys.stderr)
        print("error: pick a subcommand: build, pairs, serve", file=sys.stderr)
        return 2
    if args.cmd == "pairs":
        return run_passes(["pairup.py"], _env(args))
    if args.cmd == "build":
        return run_passes(ALL_PASSES, _env(args))
    print("error: `serve` is not implemented yet", file=sys.stderr)
    return 1
```

The shared `--repo/--base/--head/--out` flags must be declared on the top-level
parser as shown, before the subparsers, so `main(["build", "--base", "abc"])`
parses. If you declare them per-subparser instead, the tests above fail.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py --verbose`
Expected: PASS (5 tests)

- [ ] **Step 5: Register the console script**

Add to `pyproject.toml`:

```toml
[project.scripts]
pr-rename-review = "cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
include = ["cli.py", "config.py", "glossary.py", "pairup.py", "scope.py",
           "gen2.py", "render2.py"]
```

- [ ] **Step 6: Replace `run.sh` with a shim**

```bash
#!/usr/bin/env bash
# Compatibility shim. `uv run pr-rename-review build` is the real entry point.
set -euo pipefail
cd "$(dirname "$0")"
exec uv run pr-rename-review build "$@"
```

- [ ] **Step 7: Verify the CLI end to end and re-run the replay**

```bash
REPO="$REPO" uv run pr-rename-review pairs | tail --lines=3
REPO="$REPO" uv run pr-rename-review build
uv run pytest --verbose
```

Expected: `pairs` ends `total disagreements: 24`; `build` writes
`build/hidden-renames.html`; all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add cli.py pyproject.toml run.sh tests/test_cli.py
git commit --message "feat: add pr-rename-review CLI with build and pairs"
```

---

### Task 6: GitHub client

**Files:**
- Create: `github.py`
- Create: `tests/test_github.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `class GitHubError(Exception)`
  - `class GitHub` with `__init__(self, owner, repo, pr, runner=None)`, `viewed_states() -> dict[str, str]` mapping path to `"VIEWED"`/`"UNVIEWED"`/`"DISMISSED"`, and `set_viewed(path: str, viewed: bool) -> str` returning the new state.
  - `resolve_target(runner=None) -> tuple[str, str, int]` returning `(owner, repo, pr_number)`.
  - `anchor(path: str, line: int | None = None) -> str` returning the GitHub diff fragment for a file, e.g. `#diff-<sha256 hex of path>` with `R<line>` appended when a line is given.

`runner` is a callable `(list[str]) -> str` that runs a command and returns
stdout. It defaults to a `subprocess` implementation and exists so the tests
never invoke `gh`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_github.py
import hashlib, json
import pytest
from github import GitHub, GitHubError, anchor, resolve_target


class FakeRunner:
    """Records the commands it is given and replays canned stdout."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_anchor_is_sha256_of_the_path():
    want = hashlib.sha256(b"src/main/java/Foo.java").hexdigest()
    assert anchor("src/main/java/Foo.java") == f"#diff-{want}"


def test_anchor_with_a_line_targets_the_right_side():
    assert anchor("a.java", 42).endswith("R42")


def test_viewed_states_are_keyed_by_path():
    payload = json.dumps({"data": {"repository": {"pullRequest": {"files": {
        "nodes": [{"path": "a.java", "viewerViewedState": "VIEWED"},
                  {"path": "b.java", "viewerViewedState": "UNVIEWED"}],
        "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}})
    gh = GitHub("o", "r", 252, runner=FakeRunner(payload))
    assert gh.viewed_states() == {"a.java": "VIEWED", "b.java": "UNVIEWED"}


def test_viewed_states_follow_pagination():
    page1 = json.dumps({"data": {"repository": {"pullRequest": {"files": {
        "nodes": [{"path": "a.java", "viewerViewedState": "VIEWED"}],
        "pageInfo": {"hasNextPage": True, "endCursor": "CUR"}}}}}})
    page2 = json.dumps({"data": {"repository": {"pullRequest": {"files": {
        "nodes": [{"path": "b.java", "viewerViewedState": "UNVIEWED"}],
        "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}})
    runner = FakeRunner(page1, page2)
    gh = GitHub("o", "r", 252, runner=runner)
    assert set(gh.viewed_states()) == {"a.java", "b.java"}
    assert len(runner.calls) == 2, "a 242-file PR needs more than one page"


def test_set_viewed_marks_and_returns_the_new_state():
    pr_id = json.dumps({"data": {"repository": {"pullRequest": {"id": "PR_1"}}}})
    mutation = json.dumps({"data": {"markFileAsViewed": {"clientMutationId": None}}})
    runner = FakeRunner(pr_id, mutation)
    gh = GitHub("o", "r", 252, runner=runner)
    assert gh.set_viewed("a.java", True) == "VIEWED"
    assert "markFileAsViewed" in " ".join(runner.calls[1])


def test_set_viewed_unmarks():
    pr_id = json.dumps({"data": {"repository": {"pullRequest": {"id": "PR_1"}}}})
    mutation = json.dumps({"data": {"unmarkFileAsViewed": {"clientMutationId": None}}})
    runner = FakeRunner(pr_id, mutation)
    gh = GitHub("o", "r", 252, runner=runner)
    assert gh.set_viewed("a.java", False) == "UNVIEWED"
    assert "unmarkFileAsViewed" in " ".join(runner.calls[1])


def test_graphql_errors_become_GitHubError():
    payload = json.dumps({"errors": [{"message": "Could not resolve to a User"}]})
    gh = GitHub("o", "r", 252, runner=FakeRunner(payload))
    with pytest.raises(GitHubError, match="Could not resolve"):
        gh.viewed_states()


def test_missing_gh_becomes_GitHubError():
    gh = GitHub("o", "r", 252, runner=FakeRunner(FileNotFoundError("gh")))
    with pytest.raises(GitHubError, match="gh"):
        gh.viewed_states()


def test_resolve_target_reads_owner_repo_and_number():
    payload = json.dumps({"number": 252,
                          "headRepository": {"name": "hsp"},
                          "headRepositoryOwner": {"login": "haeger"}})
    assert resolve_target(runner=FakeRunner(payload)) == ("haeger", "hsp", 252)


def test_no_token_never_appears_in_any_command():
    """The tool must never handle a token. gh holds the credentials."""
    payload = json.dumps({"data": {"repository": {"pullRequest": {"files": {
        "nodes": [], "pageInfo": {"hasNextPage": False}}}}}})
    runner = FakeRunner(payload)
    GitHub("o", "r", 252, runner=runner).viewed_states()
    joined = " ".join(" ".join(c) for c in runner.calls)
    assert "token" not in joined.lower()
    assert "Authorization" not in joined
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_github.py --verbose`
Expected: FAIL, `ModuleNotFoundError: No module named 'github'`

- [ ] **Step 3: Implement `github.py`**

```python
"""GitHub access via the `gh` CLI. The tool never holds a token: `gh` is
already authenticated as the user, and `viewerViewedState` resolves against
whoever holds the credential -- which is why an app token sees nothing and
this has to shell out."""
import hashlib, json, subprocess

FILES_QUERY = """
query($owner:String!,$repo:String!,$pr:Int!,$after:String){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$pr){
      files(first:100,after:$after){
        nodes{ path viewerViewedState }
        pageInfo{ hasNextPage endCursor }
      }}}}
"""

PR_ID_QUERY = """
query($owner:String!,$repo:String!,$pr:Int!){
  repository(owner:$owner,name:$repo){ pullRequest(number:$pr){ id }}}
"""

MARK = """
mutation($id:ID!,$path:String!){
  markFileAsViewed(input:{pullRequestId:$id,path:$path}){ clientMutationId }}
"""

UNMARK = """
mutation($id:ID!,$path:String!){
  unmarkFileAsViewed(input:{pullRequestId:$id,path:$path}){ clientMutationId }}
"""


class GitHubError(Exception):
    pass


def _subprocess_runner(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode:
        raise GitHubError(proc.stderr.strip() or f"{cmd[0]} failed")
    return proc.stdout


def anchor(path, line=None):
    """GitHub keys each file in a PR diff by the sha256 of its path."""
    frag = f"#diff-{hashlib.sha256(path.encode()).hexdigest()}"
    return f"{frag}R{line}" if line else frag


class GitHub:
    def __init__(self, owner, repo, pr, runner=None):
        self.owner, self.repo, self.pr = owner, repo, pr
        self._run = runner or _subprocess_runner
        self._pr_id = None

    def _graphql(self, query, **variables):
        # `gh api graphql` sends --field values as strings and --raw-field
        # values untyped, which is how an Int! variable reaches the API as a
        # number rather than "252".
        cmd = ["gh", "api", "graphql", "--field", f"query={query}"]
        for key, value in variables.items():
            if value is None:
                continue
            if isinstance(value, str):
                cmd += ["--field", f"{key}={value}"]
            else:
                cmd += ["--raw-field", f"{key}={value}"]
        try:
            raw = self._run(cmd)
        except FileNotFoundError as exc:
            raise GitHubError(
                "gh not found -- install it and run `gh auth login`") from exc
        payload = json.loads(raw)
        if payload.get("errors"):
            raise GitHubError("; ".join(e.get("message", "?")
                                        for e in payload["errors"]))
        return payload["data"]

    def viewed_states(self):
        states, cursor = {}, None
        while True:
            files = self._graphql(FILES_QUERY, owner=self.owner, repo=self.repo,
                                  pr=self.pr, after=cursor
                                  )["repository"]["pullRequest"]["files"]
            for node in files["nodes"]:
                states[node["path"]] = node["viewerViewedState"]
            if not files["pageInfo"].get("hasNextPage"):
                return states
            cursor = files["pageInfo"]["endCursor"]

    def _id(self):
        if self._pr_id is None:
            self._pr_id = self._graphql(
                PR_ID_QUERY, owner=self.owner, repo=self.repo, pr=self.pr
            )["repository"]["pullRequest"]["id"]
        return self._pr_id

    def set_viewed(self, path, viewed):
        self._graphql(MARK if viewed else UNMARK, id=self._id(), path=path)
        return "VIEWED" if viewed else "UNVIEWED"


def resolve_target(runner=None):
    run = runner or _subprocess_runner
    raw = run(["gh", "pr", "view", "--json",
               "number,headRepository,headRepositoryOwner"])
    data = json.loads(raw)
    return (data["headRepositoryOwner"]["login"],
            data["headRepository"]["name"], data["number"])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_github.py --verbose`
Expected: PASS (10 tests)

- [ ] **Step 5: Smoke test against the real PR, read-only**

```bash
uv run python3 -c "
from github import GitHub, resolve_target
owner, repo, pr = resolve_target()
print(owner, repo, pr)
s = GitHub(owner, repo, pr).viewed_states()
print(len(s), 'files;', sum(1 for v in s.values() if v == 'VIEWED'), 'viewed')
"
```

Expected: prints the PR's owner/repo/number and a file count in the low
hundreds. This reads only — it marks nothing.

- [ ] **Step 6: Commit**

```bash
git add github.py tests/test_github.py
git commit --message "feat: read and write GitHub viewed state through gh"
```

---

### Task 7: The localhost server

**Files:**
- Create: `server.py`
- Modify: `cli.py` (implement the `serve` subcommand)
- Create: `tests/test_server.py`

**Interfaces:**
- Consumes: `github.GitHub`, `github.GitHubError` (Task 6); `cli.run_passes` (Task 5).
- Produces: `serve(page: pathlib.Path, gh, host="127.0.0.1", port=0, open_browser=True) -> None` and `make_server(page, gh, host, port) -> http.server.ThreadingHTTPServer`, the latter returning without serving so tests can drive it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_server.py
import json, pathlib, threading, urllib.error, urllib.request
import pytest
from github import GitHubError
from server import make_server


class FakeGitHub:
    def __init__(self, states=None, fail=False):
        self.states = states or {}
        self.fail = fail
        self.writes = []

    def viewed_states(self):
        if self.fail:
            raise GitHubError("not authenticated")
        return dict(self.states)

    def set_viewed(self, path, viewed):
        if self.fail:
            raise GitHubError("not authenticated")
        self.writes.append((path, viewed))
        self.states[path] = "VIEWED" if viewed else "UNVIEWED"
        return self.states[path]


@pytest.fixture
def live(tmp_path):
    page = tmp_path / "hidden-renames.html"
    page.write_text("<h1>page</h1>")
    made = {}

    def start(gh):
        srv = make_server(page, gh, "127.0.0.1", 0)
        made["srv"] = srv
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{srv.server_address[1]}"

    yield start
    if "srv" in made:
        made["srv"].shutdown()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read().decode()


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read().decode())


def test_root_serves_the_page(live):
    base = live(FakeGitHub())
    status, body = get(base + "/")
    assert status == 200 and "<h1>page</h1>" in body


def test_get_viewed_returns_states(live):
    base = live(FakeGitHub({"a.java": "VIEWED"}))
    status, body = get(base + "/api/viewed")
    assert status == 200
    assert json.loads(body) == {"synced": True, "states": {"a.java": "VIEWED"}}


def test_get_viewed_reports_unsynced_rather_than_failing(live):
    """No gh login must leave the page usable, not break it."""
    base = live(FakeGitHub(fail=True))
    status, body = get(base + "/api/viewed")
    payload = json.loads(body)
    assert status == 200
    assert payload["synced"] is False
    assert "not authenticated" in payload["reason"]
    assert payload["states"] == {}


def test_post_viewed_marks_the_file(live):
    gh = FakeGitHub()
    base = live(gh)
    status, body = post(base + "/api/viewed", {"path": "a.java", "viewed": True})
    assert status == 200 and body == {"path": "a.java", "state": "VIEWED"}
    assert gh.writes == [("a.java", True)]


def test_post_viewed_unmarks(live):
    gh = FakeGitHub({"a.java": "VIEWED"})
    base = live(gh)
    _, body = post(base + "/api/viewed", {"path": "a.java", "viewed": False})
    assert body["state"] == "UNVIEWED"


def test_post_failure_is_a_502_so_the_page_can_revert(live):
    base = live(FakeGitHub(fail=True))
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base + "/api/viewed", {"path": "a.java", "viewed": True})
    assert exc.value.code == 502


def test_post_without_a_path_is_a_400(live):
    base = live(FakeGitHub())
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base + "/api/viewed", {"viewed": True})
    assert exc.value.code == 400


def test_unknown_route_is_a_404(live):
    base = live(FakeGitHub())
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(base + "/nope")
    assert exc.value.code == 404


def test_binds_loopback_only(live):
    """A review page carrying private source must not be reachable off-box."""
    srv = make_server(pathlib.Path(__file__), FakeGitHub(), "127.0.0.1", 0)
    assert srv.server_address[0] == "127.0.0.1"
    srv.server_close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_server.py --verbose`
Expected: FAIL, `ModuleNotFoundError: No module named 'server'`

- [ ] **Step 3: Implement `server.py`**

```python
"""A stateless localhost proxy between the generated page and GitHub.

It exists for exactly one reason: a browser cannot hold the user's `gh`
credentials. No state is kept here -- GitHub is the store."""
import http.server, json, webbrowser
from github import GitHubError


def make_server(page, gh, host="127.0.0.1", port=0):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, payload, ctype="application/json"):
            body = (payload if isinstance(payload, bytes)
                    else json.dumps(payload).encode())
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            if self.path == "/api/viewed":
                try:
                    return self._send(200, {"synced": True,
                                            "states": gh.viewed_states()})
                except GitHubError as exc:
                    # Degrade, never break: the page falls back to
                    # localStorage and says so in its banner.
                    return self._send(200, {"synced": False, "states": {},
                                            "reason": str(exc)})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/viewed":
                return self._send(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "malformed JSON"})
            path = body.get("path")
            if not path:
                return self._send(400, {"error": "path is required"})
            try:
                state = gh.set_viewed(path, bool(body.get("viewed")))
            except GitHubError as exc:
                # 502 rather than 200: the page must revert the tick, because
                # a tick that did not reach GitHub is a file marked reviewed
                # that nobody reviewed.
                return self._send(502, {"error": str(exc)})
            self._send(200, {"path": path, "state": state})

    return http.server.ThreadingHTTPServer((host, port), Handler)


def serve(page, gh, host="127.0.0.1", port=0, open_browser=True):
    srv = make_server(page, gh, host, port)
    url = f"http://{host}:{srv.server_address[1]}/"
    print(f"serving {page.name} at {url}  (ctrl-c to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        srv.shutdown()
        srv.server_close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_server.py --verbose`
Expected: PASS (9 tests)

- [ ] **Step 5: Implement the `serve` subcommand in `cli.py`**

Replace the `serve` stub with:

```python
    if args.cmd == "serve":
        env = _env(args)
        if not args.no_build:
            code = run_passes(ALL_PASSES, env)
            if code:
                return code
        page = pathlib.Path(env["OUT"]) / "hidden-renames.html"
        if not page.exists():
            print(f"error: {page} does not exist; run without --no-build",
                  file=sys.stderr)
            return 1
        from server import serve
        try:
            owner, repo, pr = resolve_target()
            gh = GitHub(owner, repo, pr)
        except GitHubError as exc:
            print(f"warning: GitHub sync unavailable ({exc}); "
                  "viewed state will be local to your browser", file=sys.stderr)
            gh = _OfflineGitHub(str(exc))
        serve(page, gh, open_browser=not args.no_browser)
        return 0
```

Add `--no-build` and `--no-browser` as `action="store_true"` flags on the
top-level parser, and add `from github import GitHub, GitHubError,
resolve_target` to `cli.py`'s module-level imports — `_OfflineGitHub` below
raises `GitHubError` at module scope, so a function-local import will not do.

Then the offline stand-in, so the page still loads without `gh`:

```python
class _OfflineGitHub:
    """Stands in when gh is unavailable, so the page loads and honestly
    reports that nothing is being written back."""

    def __init__(self, reason):
        self.reason = reason

    def viewed_states(self):
        raise GitHubError(self.reason)

    def set_viewed(self, path, viewed):
        raise GitHubError(self.reason)
```

Add a CLI test for the new flags:

```python
def test_serve_can_skip_the_build(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr("cli.run_passes", lambda p, e: called.append(p) or 0)
    monkeypatch.setattr("cli._env", lambda a: {"OUT": str(tmp_path)})
    main(["serve", "--no-build", "--no-browser"])
    assert called == [], "serve --no-build must not run the passes"
```

`serve` rebuilds by default. There is no staleness heuristic on purpose: the
passes take seconds, and a heuristic that guesses wrong serves a stale page
that looks current — the exact failure this tool exists to prevent.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest --verbose`
Expected: PASS, replay included.

- [ ] **Step 7: Commit**

```bash
git add server.py cli.py tests/test_server.py tests/test_cli.py
git commit --message "feat: serve the review page and proxy viewed state to GitHub"
```

---

### Task 8: The page talks to the server

**Files:**
- Modify: `render2.py:217-220` (header prose), `:205-206` (subtitle), `:222-227` (tally), `:261-267` (viewed state), `:290-294` (index row links), `:345-358` (mark/unmark handlers)
- Create: `tests/test_render.py`

**Interfaces:**
- Consumes: `github.anchor` (Task 6); `config.load_config` (Task 2); `GET/POST /api/viewed` (Task 7).
- Produces: `render2.pr_url(cfg: Config, owner: str, repo: str, path: str, line: int | None = None) -> str | None`, returning `None` when `cfg.pr` is unset.

`render2.py` is one large f-string; literal braces in the JavaScript are
doubled (`{{`, `}}`). Every snippet below is written for insertion into that
f-string and keeps that convention.

- [ ] **Step 1: Write the failing test for the deep-link builder**

```python
# tests/test_render.py
import hashlib
import pytest
from config import Config, GlossaryTables, Pairing
from render2 import pr_url


def cfg(pr=252):
    return Config(base="main", head="HEAD", pr=pr,
                  pairing=Pairing(), glossary=GlossaryTables())


def test_pr_url_points_at_the_file_in_the_github_diff():
    url = pr_url(cfg(), "haeger", "hsp", "src/Foo.java")
    digest = hashlib.sha256(b"src/Foo.java").hexdigest()
    assert url == f"https://github.com/haeger/hsp/pull/252/files#diff-{digest}"


def test_pr_url_can_target_a_line_on_the_new_side():
    url = pr_url(cfg(), "haeger", "hsp", "src/Foo.java", 12)
    assert url.endswith("R12")


def test_pr_url_without_a_pr_number_returns_none():
    """With no PR number there is nothing to link to, and a broken link is
    worse than no link."""
    assert pr_url(cfg(pr=None), "haeger", "hsp", "src/Foo.java") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_render.py --verbose`
Expected: FAIL, `ImportError: cannot import name 'pr_url'`

- [ ] **Step 3: Add `pr_url` to `render2.py`**

```python
from config import load_config
from github import GitHubError, anchor, resolve_target

CFG = load_config(S / ".pr-rename-review.toml")
try:
    OWNER, REPO_NAME, _PR = resolve_target()
except GitHubError:
    # `build` must work with no gh available; the links are simply absent.
    OWNER = REPO_NAME = None


def pr_url(cfg, owner, repo, path, line=None):
    """Deep link into GitHub's own diff. Commenting happens there -- this
    tool does not write comments."""
    if not (cfg.pr and owner and repo):
        return None
    return (f"https://github.com/{owner}/{repo}/pull/{cfg.pr}/files"
            f"{anchor(path, line)}")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_render.py --verbose`
Expected: PASS (3 tests)

- [ ] **Step 5: Replace the browser-local viewed state with server calls**

Replace `render2.py:261-267` with:

```javascript
// Viewed state lives in GitHub, reached through the local server, so a tick
// here is the same tick a teammate sees on the PR. localStorage is the
// fallback for when `gh` is unavailable.
const KEY='hsp-hidden-renames-viewed-v1';
let viewed=new Set(),synced=false;
function saveLocal(){{try{{localStorage.setItem(KEY,JSON.stringify([...viewed]));}}catch(e){{}}}}
function loadLocal(){{try{{viewed=new Set(JSON.parse(localStorage.getItem(KEY)||'[]'));}}catch(e){{}}}}
function isDone(f){{return viewed.has(f.id);}}

function banner(text,warn){{
  const el=document.getElementById('sync');
  el.textContent=text; el.className=warn?'sync warn':'sync';
}}

async function loadViewed(){{
  try{{
    const r=await fetch('/api/viewed');
    const j=await r.json();
    if(j.synced){{
      synced=true;
      viewed=new Set(Object.entries(j.states)
        .filter(([,v])=>v==='VIEWED').map(([k])=>k));
      banner('Viewed state synced with GitHub',false);
    }}else{{
      loadLocal();
      banner('Not synced with GitHub ('+(j.reason||'unknown')+
             ') — ticks stay in this browser',true);
    }}
  }}catch(e){{
    loadLocal();
    banner('Local-only: the review server is not reachable',true);
  }}
  draw();
}}

async function setViewed(id,on){{
  const had=viewed.has(id);
  on?viewed.add(id):viewed.delete(id);
  draw();
  if(!synced){{saveLocal();return true;}}
  try{{
    const r=await fetch('/api/viewed',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{path:id,viewed:on}})}});
    if(!r.ok)throw new Error(await r.text());
    return true;
  }}catch(e){{
    // Revert. A tick that never reached GitHub would mean a file marked
    // reviewed that nobody reviewed.
    had?viewed.add(id):viewed.delete(id);
    banner('GitHub rejected that change — tick reverted',true);
    draw();
    return false;
  }}
}}
```

- [ ] **Step 6: Route the handlers through `setViewed`**

At `render2.py:345-358`, replace each `viewed.add(...)/save()` and
`viewed.delete(...)/save()` pair:

```javascript
if(mv)mv.onclick=async()=>{{await setViewed(D[cur].id,true);nextTodo();}};
if(un)un.onclick=async()=>{{await setViewed(D[cur].id,false);}};
```

and in the keyboard handler:

```javascript
if(isDone(D[cur])){{setViewed(D[cur].id,false);}}
else{{setViewed(D[cur].id,true).then(ok=>{{if(ok)nextTodo();}});}}
```

Replace the `reset` handler so it unmarks through the server rather than
clearing a local set that GitHub still disagrees with:

```javascript
document.getElementById('reset').onclick=async()=>{{
  for(const id of [...viewed]){{await setViewed(id,false);}}
}};
```

Add `await loadViewed();` as the page's entry point in place of the current
initial `draw()` call, and add the banner element next to the progress bar:

```html
<span id="sync" class="sync">Checking GitHub…</span>
```

- [ ] **Step 7: Add the GitHub links to each index row**

The URL is computed in Python, one per file, so the sha256 stays in the code
that Step 1 already tests. Add to the `compact.append({...})` dict at
`render2.py:24-33`:

```python
        "gh": pr_url(CFG, OWNER, REPO_NAME, f["new"]),
```

Then in `drawIndex` at `render2.py:290-294`, render the link beside the
filename. `stopPropagation` is required — without it the link click also
fires the row handler that opens the file:

```javascript
const gh=f.gh?`<a class="ghlink" href="${{f.gh}}" target="_blank" rel="noopener"
  onclick="event.stopPropagation()" title="Open in GitHub to comment">↗</a>`:'';
```

and include `${{gh}}` inside the `<span class="nm">` alongside `${{f.nn}}`.

- [ ] **Step 8: Handle paths GitHub does not recognise**

The spec requires that a file GitHub's list does not contain is marked
local-only and named in the footer, never silently dropped. Our new path is
*derived*, so a pairing bug shows up here first — and a row that silently
accepted ticks it never sent would be the worst possible failure of this tool.

`GET /api/viewed` already returns GitHub's full path map, so the page can
compute the difference on load. In `loadViewed`, after the `synced` branch:

```javascript
      const known=new Set(Object.keys(j.states));
      unknown=D.filter(f=>!known.has(f.id)).map(f=>f.id);
      if(unknown.length){{
        banner('Synced, but '+unknown.length+
               ' file(s) are not in GitHub\\'s list — see the footer',true);
      }}
```

Declare `let unknown=[];` beside `viewed`, treat an unknown path as local-only
in `setViewed`:

```javascript
  if(!synced||unknown.includes(id)){{saveLocal();return true;}}
```

and render the list in the footer next to the existing "11 pairs left out"
table:

```javascript
document.getElementById('unk').innerHTML=unknown.length
  ? '<h2>Not in GitHub\\'s file list</h2><p>These ticks stay in this browser. '+
    'A path here usually means the derived new path is wrong — check the '+
    'pairing report.</p><ul>'+unknown.map(u=>`<li>${{u}}</li>`).join('')+'</ul>'
  : '';
```

Add `<div id="unk"></div>` inside the `.foot` block at `render2.py:249-255`,
and call this from `draw()` so it updates with the rest of the page.

- [ ] **Step 9: Correct the header prose**

The text at `render2.py:217-220` currently states the opposite of the new
behaviour. Replace it:

```html
  <br><br>GitHub's per-file <b>Viewed</b> ticks are read and written through
  your own <code>gh</code> login, so a tick here is a tick on the PR and a tick
  on the PR shows up here. <b>V</b> marks the open file viewed and jumps to the
  next one; <b>J</b> and <b>K</b> step through the list. To comment, follow the
  ↗ link into GitHub's diff — this page does not write comments.
```

Replace the hardcoded counts in the subtitle and note at `:205-210` with
values from config and payload: `CFG.pr` for the PR number, `CFG.base` and
`CFG.head` for the refs, and `len(compact)` for the pair count. The
`242 renames total, 168 of them GitHub shows correctly` figures are not in
`diffdata2.json`; have `scope.py` write `canon_total` and `gh_correct` into
`scope.json` and carry them through `gen2.py` into the payload rather than
leaving stale numbers in the template.

- [ ] **Step 10: Verify the page end to end**

```bash
REPO="$REPO" uv run pr-rename-review serve --no-browser
```

Then in a browser, at the printed URL, confirm:

| Check | Expected |
|---|---|
| banner | "Viewed state synced with GitHub" |
| files already ticked on the PR | show as viewed on load |
| press `V` | row ticks, progress advances |
| reload the page | the tick survives |
| the ↗ link | opens the right file in GitHub's diff |
| `gh auth logout`, then reload | banner warns, page still usable |

Re-run `gh auth login` afterwards.

- [ ] **Step 11: Run the full suite and commit**

```bash
uv run pytest --verbose
git add render2.py scope.py gen2.py tests/test_render.py
git commit --message "feat: sync viewed state from the page, link to GitHub for comments"
```

---

### Task 9: Verify against GitHub and update the docs

The claim that justifies the whole server is "a tick here is a tick in
GitHub's PR UI". Nothing so far proves it in GitHub's own interface.

**Files:**
- Modify: `README.md`
- Modify: `2026-08-02-pr-rename-review-v1-spec.md` (status line only)

- [ ] **Step 1: Perform the manual round-trip against the real PR**

Pick a file you have genuinely reviewed, so the marks left behind are honest.

1. Open PR #252's Files tab in a browser. Note a file that is **not** ticked.
2. Run `REPO="$REPO" uv run pr-rename-review serve` and mark that file viewed.
3. Reload the GitHub Files tab. **The file must now show as viewed.**
4. Untick it in GitHub's UI, reload the tool's page, and confirm it shows as
   unviewed there.

Record the result. If step 3 fails, stop — the localhost server has no
justification without it, and the cause is almost certainly a path mismatch
between our new path and GitHub's file list.

- [ ] **Step 2: Verify a delete+add file specifically**

The 62 files GitHub renders as an unrelated delete plus add are the ones this
tool exists for, and they are the ones whose path mapping was reasoned about
rather than observed. Repeat step 1 using a file with `kind == "split"` from
`build/scope.json`:

```bash
uv run python3 -c "
import json
rows=[r for r in json.load(open('build/scope.json')) if r['kind']=='split']
print(rows[0]['new'])"
```

Expected: marking that file in the tool ticks it on the PR.

- [ ] **Step 3: Rewrite `README.md`**

Replace the prototype README. It must state:

- what the tool is, and that pass 2 (glossary inference) is deliberately not
  built — with a pointer to the v1 spec for why
- `uv run pr-rename-review build | pairs | serve`, and the `--no-build` and
  `--no-browser` flags
- that the vocabulary lives in `.pr-rename-review.toml`
- that viewed state syncs through `gh`, and what happens without it
- that comments are made in GitHub via the ↗ links, by design
- the three caveats worth keeping from the current README: never pass a
  pathspec to a rename-detecting diff, `-l50000` is required, do not pipe the
  passes into `head`
- the regression baseline: 242 renames, 24 disagreements, 63 pairs,
  5,189 → 1,489 tokens, 181 frozen, 23 cancelling to zero, and that
  `uv run pytest` checks it given `REPO`

- [ ] **Step 4: Mark the spec implemented**

Change the spec's status line to `Status: implemented` and add one line
recording the outcome of the Step 1 round-trip check.

- [ ] **Step 5: Run everything once more and commit**

```bash
uv run pytest --verbose
git add README.md 2026-08-02-pr-rename-review-v1-spec.md
git commit --message "docs: document the v1 tool and record the GitHub round-trip"
```

---

## What this plan does not do

Recorded so the omissions read as decisions rather than oversights:

- **Glossary inference.** `.pr-rename-review.toml` is the seam it plugs into.
- **Lazy loading.** The page stays ~745 KB. Revisit above a few hundred files.
- **Writing comments.** Deep links only; see the spec's "Commenting" section.
- **Generalizing `render2.py`'s copy beyond the counts.** The prose still
  describes a German→English rename, because that is the PR it is for.
