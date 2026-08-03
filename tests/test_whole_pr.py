"""Every file the PR touches reaches the page, not just the renames.

A rename-paired file arrives through `canonical-pairs.tsv`, but a file the PR
only adds or only deletes has one side and no partner, so no pairing pass
would ever pick it up. Both went missing from a review that claims to carry
the whole PR -- the added ones silently, on a real branch.

These run the passes over synthetic repositories rather than the pinned
baseline because the baseline happens to contain no deletions at all: the
branch is a rename, so git pairs almost every removal with an addition. A
repository built to hold exactly one deletion and no additions is the only
way to make the case reproducible. Keeping the add and the delete in separate
repositories is deliberate too -- put both in one and git's 1% rename
detection is free to pair them with each other, which is the very guess this
tool exists to distrust.
"""
import json, os, pathlib, subprocess, sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

CONTENT = "".join(f"line {i} of some distinctive text\n" for i in range(12))


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _commit(repo, msg):
    _git(repo, "add", "--all")
    _git(repo, "commit", "--quiet", "--message", msg)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _run(repo, base, head):
    """The three data passes, in order, returning the payload the page reads."""
    out = repo / "out"
    env = {**os.environ, "REPO": str(repo), "BASE": base, "HEAD_REF": head,
           "OUT": str(out)}
    for script in ("pairup.py", "scope.py", "gen2.py"):
        subprocess.run([sys.executable, str(ROOT / script)], env=env, cwd=ROOT,
                       check=True, capture_output=True, text=True)
    return {f["new"]: f for f in
            json.loads((out / "diffdata2.json").read_text())["files"]}


def test_a_file_the_pr_deletes_stays_in_the_review(repo):
    """Nothing on the head side, so nothing paired it in. It rides along as
    kind "deleted" with an empty new side, which is what gives it a word-level
    view and a Viewed tick like every other file of the PR."""
    (repo / "gone.txt").write_text(CONTENT)
    (repo / "keep.txt").write_text(CONTENT)
    base = _commit(repo, "base")
    (repo / "gone.txt").unlink()
    (repo / "keep.txt").write_text(CONTENT + "one more line\n")
    head = _commit(repo, "delete one, edit the other")

    files = _run(repo, base, head)
    assert "gone.txt" in files, "the PR deletes gone.txt and the review drops it"
    assert files["gone.txt"]["kind"] == "deleted"
    assert files["gone.txt"]["old"] == "gone.txt"
    assert files["gone.txt"]["sim"] is None
    # Every line is a removal: nothing on the head side to diff against.
    assert all(r[0] == "del" for r in files["gone.txt"]["raw"])
    assert files["keep.txt"]["kind"] == "modified"


def test_a_file_the_pr_adds_stays_in_the_review(repo):
    (repo / "keep.txt").write_text(CONTENT)
    base = _commit(repo, "base")
    (repo / "fresh.txt").write_text(CONTENT)
    (repo / "keep.txt").write_text(CONTENT + "one more line\n")
    head = _commit(repo, "add one, edit the other")

    files = _run(repo, base, head)
    assert "fresh.txt" in files, "the PR adds fresh.txt and the review drops it"
    assert files["fresh.txt"]["kind"] == "added"
    assert files["fresh.txt"]["old"] == "fresh.txt"
    assert all(r[0] == "add" for r in files["fresh.txt"]["raw"])


def test_a_renamed_file_still_pairs_alongside_them(repo):
    """The add and delete rows are extra rows, not a replacement for the
    pairing: a recorded move still arrives as one file with both sides."""
    (repo / "old.txt").write_text(CONTENT)
    base = _commit(repo, "base")
    _git(repo, "mv", "old.txt", "new.txt")
    _commit(repo, "move")
    (repo / "new.txt").write_text(CONTENT + "one more line\n")
    head = _commit(repo, "edit")

    files = _run(repo, base, head)
    assert list(files) == ["new.txt"]
    assert files["new.txt"]["old"] == "old.txt"
    assert files["new.txt"]["kind"] == "shown"
