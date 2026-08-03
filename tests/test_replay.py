"""The regression gate.

Config extraction is a pure refactor, so any difference between a fresh run
and the golden fixture is a transcription bug. Comparing per path before
comparing wholesale is deliberate: a bare `assert rebuilt == golden` on 790 KB
of JSON produces an unreadable failure, and the value of this test is telling
you *which* file a dropped glossary entry broke.
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

    assert rebuilt["empties"] == golden["empties"]


def test_replay_totals(rebuilt):
    """Measured at 52efff3...1ce7bfa. These move whenever the branch moves,
    so they are asserted against the pinned baseline, not against the
    historical figures in the design doc. 62 of the files are pairs GitHub
    hides, 169 are renames it shows correctly (19 of them pure moves), and
    15 changed in place."""
    files = rebuilt["files"]
    assert len(files) == 246
    assert len(rebuilt["empties"]) == 11
    assert sum(1 for f in files if f["kind"] == "split") == 59
    assert sum(1 for f in files if f["kind"] == "mispaired") == 3
    assert sum(1 for f in files if f["kind"] == "modified") == 15
    assert sum(1 for f in files if f["kind"] == "shown") == 169
    assert sum(f["raw_w"] for f in files) == 10522
    assert sum(f["nrm_w"] for f in files) == 2860
    assert sum(f["nrm_ph"] for f in files) == 1525
    assert sum(1 for f in files if f["nrm_w"] == 0) == 150


def test_replay_includes_files_renamed_in_place(rebuilt):
    """The rename also changes identifiers inside files whose paths never
    move. GitHub shows those diffs fine, but the glossary-cancelled view is
    worth having for them too, so they ride along as kind "modified"."""
    files = {f["new"]: f for f in rebuilt["files"]}
    sched = ("src/main/java/de/haegerconsulting/hsp/events/"
             "EventPublicationScheduler.java")
    assert sched in files
    assert files[sched]["kind"] == "modified"
    assert files[sched]["old"] == sched


def test_replay_includes_renames_github_shows_correctly(rebuilt):
    """Renames over GitHub's 50% threshold render fine there, but the tool
    is the review surface for the whole PR, so they ride along as kind
    "shown" -- glossary-cancelled view and viewed tick included."""
    files = {f["new"]: f for f in rebuilt["files"]}
    impl = ("src/main/java/de/haegerconsulting/hsp/tender/domain/users/"
            "UserDirectoryServiceImpl.java")
    assert impl in files
    assert files[impl]["kind"] == "shown"
    assert files[impl]["old"] == ("src/main/java/de/haegerconsulting/hsp/"
                                  "ausschreibung/domain/users/"
                                  "UserDirectoryServiceImpl.java")


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
    assert "total disagreements: 21" in pair_report
    assert "old files that moved: 242" in pair_report
    assert "collisions          : []" in pair_report
