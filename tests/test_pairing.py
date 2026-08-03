import os, pathlib, subprocess, sys
import pytest
from pairup import PairingError, check_collisions, history_pairing

ROOT = pathlib.Path(__file__).resolve().parent.parent


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


CONTENT = "".join(f"line {i} of some distinctive text\n" for i in range(12))


def test_collisions_are_an_error():
    with pytest.raises(PairingError, match="new/Tender.java"):
        check_collisions({"a/Alt.java": "new/Tender.java",
                          "b/Alt.java": "new/Tender.java"})


def test_collision_message_names_both_sources():
    with pytest.raises(PairingError) as exc:
        check_collisions({"a/Alt.java": "x.java", "b/Alt.java": "x.java"})
    assert "a/Alt.java" in str(exc.value) and "b/Alt.java" in str(exc.value)


def test_no_collisions_passes():
    check_collisions({"a.java": "b.java", "c.java": "d.java"})


def test_history_pairing_records_a_pure_move_then_edit(repo):
    """A rename commit followed by a content commit is the branch shape the
    tool prefers: the move is recorded exactly and cannot go stale, however
    heavily the content commit rewrites the file."""
    (repo / "a.txt").write_text(CONTENT)
    base = _commit(repo, "base")
    _git(repo, "mv", "a.txt", "b.txt")
    _commit(repo, "move")
    (repo / "b.txt").write_text("entirely different now\n")
    head = _commit(repo, "rewrite")
    assert history_pairing(repo, base, head) == {"a.txt": "b.txt"}


def test_history_pairing_chains_successive_moves(repo):
    (repo / "a.txt").write_text(CONTENT)
    base = _commit(repo, "base")
    _git(repo, "mv", "a.txt", "b.txt")
    _commit(repo, "first move")
    _git(repo, "mv", "b.txt", "c.txt")
    head = _commit(repo, "second move")
    assert history_pairing(repo, base, head) == {"a.txt": "c.txt"}


def test_history_pairing_ignores_inexact_renames(repo):
    """A commit that renames and edits at once is back to similarity
    guessing, which is the failure mode this tool exists for -- only exact
    moves count as recorded."""
    (repo / "a.txt").write_text(CONTENT)
    base = _commit(repo, "base")
    _git(repo, "mv", "a.txt", "b.txt")
    (repo / "b.txt").write_text(CONTENT + "one more line\n")
    head = _commit(repo, "move and edit")
    assert history_pairing(repo, base, head) == {}


def test_history_pairing_drops_ambiguous_identical_blobs(repo):
    """Exact-rename detection pairs identical files arbitrarily (the
    zero-byte eval fixtures). An arbitrary pair recorded as truth would be
    worse than falling back to the name tables, so both are dropped."""
    (repo / "e1.txt").write_text("")
    (repo / "e2.txt").write_text("")
    base = _commit(repo, "base")
    _git(repo, "mv", "e1.txt", "x.txt")
    _git(repo, "mv", "e2.txt", "y.txt")
    head = _commit(repo, "move empties")
    assert history_pairing(repo, base, head) == {}


def test_recorded_moves_pair_end_to_end(repo):
    """Through pairup.py itself: a full rewrite still pairs, because the
    rename commit recorded the move. There is no name vocabulary -- the
    branch's own history is the only pairing authority."""
    (repo / "a.txt").write_text(CONTENT)
    base = _commit(repo, "base")
    _git(repo, "mv", "a.txt", "b.txt")
    _commit(repo, "move")
    (repo / "b.txt").write_text("entirely different now\n")
    head = _commit(repo, "rewrite")
    out = repo / "out"
    env = {**os.environ, "REPO": str(repo), "BASE": base, "HEAD_REF": head,
           "OUT": str(out)}
    subprocess.run([sys.executable, str(ROOT / "pairup.py")], env=env,
                   cwd=ROOT, check=True, capture_output=True, text=True)
    pairs = dict(ln.split("\t")[:2]
                 for ln in (out / "canonical-pairs.tsv").read_text().splitlines())
    assert pairs == {"a.txt": "b.txt"}
