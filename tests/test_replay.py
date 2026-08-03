"""The regression gate.

Any difference between a fresh run and the golden fixture is unintended
drift. Comparing per path before comparing wholesale is deliberate: a bare
`assert rebuilt == golden` on megabytes of JSON produces an unreadable
failure, and the value of this test is telling you *which* file broke.
"""
import json, pathlib

GOLDEN = pathlib.Path(__file__).resolve().parent / "golden"


def test_replay_matches_golden(rebuilt):
    golden = json.loads((GOLDEN / "diffdata2.json").read_text())

    got = {f["new"]: f for f in rebuilt["files"]}
    want = {f["new"]: f for f in golden["files"]}
    assert sorted(got) == sorted(want), "the set of reviewable pairs changed"

    for path in sorted(want):
        assert got[path] == want[path], f"payload changed for {path}"


def test_replay_totals(rebuilt):
    """Measured at eb1b00665...47c9dc7, the two-commit branch shape. These
    move whenever the branch moves, so they are asserted against the pinned
    baseline. 62 of the files are pairs GitHub hides, 182 are renames it
    shows correctly (30 of them byte-identical moves, the zero-byte eval
    fixtures included), and 15 changed in place."""
    files = rebuilt["files"]
    assert len(files) == 259
    assert sum(1 for f in files if f["kind"] == "split") == 59
    assert sum(1 for f in files if f["kind"] == "mispaired") == 3
    assert sum(1 for f in files if f["kind"] == "modified") == 15
    assert sum(1 for f in files if f["kind"] == "shown") == 182
    assert sum(f["raw_w"] for f in files) == 11187
    assert sum(1 for f in files if f["raw_w"] == 0) == 30


def test_replay_includes_files_renamed_in_place(rebuilt):
    """The rename also changes identifiers inside files whose paths never
    move. GitHub shows those diffs fine, but the word-level view is worth
    having for them too, so they ride along as kind "modified"."""
    files = {f["new"]: f for f in rebuilt["files"]}
    sched = ("src/main/java/de/haegerconsulting/hsp/events/"
             "EventPublicationScheduler.java")
    assert sched in files
    assert files[sched]["kind"] == "modified"
    assert files[sched]["old"] == sched


def test_replay_includes_renames_github_shows_correctly(rebuilt):
    """Renames over GitHub's 50% threshold render fine there, but the tool
    is the review surface for the whole PR, so they ride along as kind
    "shown" -- word-level view and viewed tick included."""
    files = {f["new"]: f for f in rebuilt["files"]}
    impl = ("src/main/java/de/haegerconsulting/hsp/tender/domain/users/"
            "UserDirectoryServiceImpl.java")
    assert impl in files
    assert files[impl]["kind"] == "shown"
    assert files[impl]["old"] == ("src/main/java/de/haegerconsulting/hsp/"
                                  "ausschreibung/domain/users/"
                                  "UserDirectoryServiceImpl.java")


def test_replay_carries_no_glossary_fields(rebuilt):
    """The payload is a plain word-level diff: no normalized rows, no
    frozen-German counts. The glossary was removed as noise -- the plain
    diff tracks the renames closely enough."""
    for f in rebuilt["files"]:
        for key in ("nrm", "nrm_c", "nrm_w", "nrm_ph"):
            assert key not in f


def test_replay_keeps_pure_moves_tickable(rebuilt):
    """A file moved without a content change has nothing to word-review,
    but GitHub still lists it and it still needs its Viewed tick, so it
    stays in the list with an empty diff rather than falling out."""
    assert any(f["kind"] == "shown" and f["raw_w"] == 0
               and f["old"] != f["new"] for f in rebuilt["files"])


def _pairing_only(report):
    """Drop the lines that describe the run rather than the pairing: `wrote
    <abs path>` (OUT differs between the fixture and the test's scratch dir)
    and `reviewing <ref> ...` (names the commits under review). The golden
    records what the pass decides, not what it was pointed at."""
    return [ln for ln in report.splitlines()
            if not ln.startswith(("wrote ", "reviewing "))]


def test_pairing_report_matches_golden(pair_report):
    assert _pairing_only(pair_report) == _pairing_only(
        (GOLDEN / "pair.log").read_text())


def test_pairing_finds_the_known_disagreements(pair_report):
    assert "old files that moved: 244" in pair_report
    assert "recorded by rename commits : 228" in pair_report
    assert "total disagreements: 10" in pair_report
    assert "collisions          : []" in pair_report
