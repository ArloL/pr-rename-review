"""The page's viewed/undo bookkeeping, driven through its own JavaScript.

`V` marks the open file viewed *and* jumps to the next unviewed one, so a
mispress leaves the wrong file ticked and behind you -- filtered out of the
list you are working through. These pin the undo that gets you back.
"""
import json, pathlib, shutil, subprocess
import pytest
from pagebuild import build_page, pair

DRIVE = pathlib.Path(__file__).resolve().parent / "js" / "drive.mjs"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node runs the page's JavaScript under a stub DOM")


def files(n=3):
    """n files GitHub already shows fine, so one path each and one tick each
    -- a sub-threshold pair would put two paths in every POST and make the
    assertions about undo harder to read."""
    return [pair(kind="modified", old=f"src/A{i}.java", new=f"src/A{i}.java",
                 oldname=f"A{i}.java", newname=f"A{i}.java",
                 oldpkg="src", newpkg="src", sim=None) for i in range(n)]


def drive(tmp_path, actions, states=None, reject_from=None, n=3):
    page = build_page(tmp_path, files(n))
    scenario = {"synced": True, "actions": actions, "rejectFrom": reject_from,
                "states": {f"src/A{i}.java": "UNVIEWED" for i in range(n)}}
    scenario["states"].update(states or {})
    proc = subprocess.run(["node", str(DRIVE), str(page)],
                          input=json.dumps(scenario), check=True,
                          capture_output=True, text=True)
    return json.loads(proc.stdout)


def test_undo_removes_a_tick_pressed_by_mistake(tmp_path):
    r = drive(tmp_path, ["v", "u"])
    assert r["viewed"] == []
    assert r["posts"] == [{"paths": ["src/A0.java"], "viewed": True},
                          {"paths": ["src/A0.java"], "viewed": False}]


def test_undo_returns_to_the_file_it_unticked(tmp_path):
    """The tick alone is not the undo: V has already moved on, and the file
    is gone from the unviewed filter, so leaving the cursor where it landed
    means hunting for the file you just rescued."""
    r = drive(tmp_path, ["v", "u"])
    assert r["cur"] == 0


def test_undo_walks_back_through_a_run_of_mistaken_ticks(tmp_path):
    r = drive(tmp_path, ["v", "v", "u", "u"])
    assert r["viewed"] == []
    assert r["cur"] == 0


def test_undo_does_nothing_when_no_tick_has_been_made(tmp_path):
    r = drive(tmp_path, ["u"])
    assert r["posts"] == []
    assert r["viewed"] == []
    assert r["cur"] == 0


def test_undo_restores_a_tick_you_removed(tmp_path):
    """Undo is symmetric. V on an already-viewed file unmarks it, and that
    is as easy to mispress as the other direction."""
    r = drive(tmp_path, ["v", "u"], states={"src/A0.java": "VIEWED"})
    assert r["viewed"] == ["src/A0.java"]


def test_an_undo_github_rejects_stays_on_the_stack(tmp_path):
    """A revert that never reached GitHub has not happened. Dropping the
    entry would leave the tick standing with no way left to take it back."""
    r = drive(tmp_path, ["v", "u"], reject_from=1)
    assert r["viewed"] == ["src/A0.java"]
    assert r["undoDepth"] == 1


def test_reset_clears_the_undo_stack(tmp_path):
    """Reset unmarks everything. Walking back into it one file at a time is
    not an undo anyone wants, and the entries it would push describe ticks
    that are already gone."""
    r = drive(tmp_path, ["v", "v", "reset", "u"])
    assert r["undoDepth"] == 0
    assert r["viewed"] == []
    assert [p["viewed"] for p in r["posts"]] == [True, True, False, False]


def test_the_undo_button_reverts_like_the_key(tmp_path):
    r = drive(tmp_path, ["v", "undo"])
    assert r["viewed"] == []


def test_the_undo_button_counts_what_it_would_undo(tmp_path):
    r = drive(tmp_path, ["v", "v"])
    assert r["undoLabel"] == "undo 2"
    assert r["undoDisabled"] is False


def test_the_undo_button_is_disabled_with_nothing_to_undo(tmp_path):
    """A key that silently does nothing reads as a broken key. The button
    shows the depth, so a press at zero is visibly a no-op."""
    r = drive(tmp_path, [])
    assert r["undoLabel"] == "undo"
    assert r["undoDisabled"] is True
