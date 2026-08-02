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
    historical figures in the design doc."""
    files = rebuilt["files"]
    assert len(files) == 62
    assert len(rebuilt["empties"]) == 11
    assert sum(f["raw_w"] for f in files) == 5187
    assert sum(f["nrm_w"] for f in files) == 1489
    assert sum(f["nrm_ph"] for f in files) == 181
    assert sum(1 for f in files if f["nrm_w"] == 0) == 22


def _without_paths(report):
    """Drop the trailing `wrote <abs path>` line -- OUT differs between the
    captured fixture and the test's scratch directory."""
    return [ln for ln in report.splitlines() if not ln.startswith("wrote ")]


def test_pairing_report_matches_golden(pair_report):
    assert _without_paths(pair_report) == _without_paths(
        (GOLDEN / "pair.log").read_text())


def test_pairing_finds_the_known_disagreements(pair_report):
    assert "total disagreements: 21" in pair_report
    assert "old files that moved: 242" in pair_report
    assert "collisions          : []" in pair_report
