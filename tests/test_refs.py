"""refs.py against a real repository built in a tmpdir.

The scenario that matters is the one the pinned base used to hide: the base
branch moves on after the fork. Resolving to its tip pulls those commits into
the review; resolving to the merge base does not.
"""
import json, subprocess
import pytest

from refs import RefError, fetch, load, remote_of, resolve, short


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """main forks at `base`, then both sides gain a commit."""
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "--initial-branch=main")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "T")
    (r / "shared.txt").write_text("fork point\n")
    git(r, "add", "-A")
    git(r, "commit", "--message", "fork point")
    fork = git(r, "rev-parse", "HEAD")

    git(r, "checkout", "-b", "feature")
    (r / "feature.txt").write_text("the PR's own work\n")
    git(r, "add", "-A")
    git(r, "commit", "--message", "PR work")

    git(r, "checkout", "main")
    (r / "shared.txt").write_text("main moved on\n")
    (r / "unrelated.txt").write_text("not the PR's work\n")
    git(r, "add", "-A")
    git(r, "commit", "--message", "main moves on")
    git(r, "checkout", "feature")
    return r, fork


def test_base_resolves_to_the_merge_base_not_the_branch_tip(repo):
    r, fork = repo
    base, head = resolve(r, "main", "feature")
    assert base == fork
    assert base != git(r, "rev-parse", "main")
    assert head == git(r, "rev-parse", "feature")


def test_the_diff_excludes_commits_the_base_branch_gained(repo):
    """The point of the merge base, stated as the diff the page renders."""
    r, _ = repo
    base, head = resolve(r, "main", "feature")
    changed = git(r, "diff", "--name-only", f"{base}..{head}").split()
    assert changed == ["feature.txt"]

    tip = git(r, "rev-parse", "main")
    against_tip = git(r, "diff", "--name-only", f"{tip}..{head}").split()
    assert "unrelated.txt" in against_tip  # what the old pinned base risked


def test_old_file_content_comes_from_the_fork_point(repo):
    """gen2.py reads old blobs with `git show BASE:path`."""
    r, _ = repo
    base, _ = resolve(r, "main", "feature")
    assert git(r, "show", f"{base}:shared.txt") == "fork point"


def test_resolution_is_idempotent(repo):
    r, _ = repo
    once = resolve(r, "main", "feature")
    assert resolve(r, *once) == once


def test_unknown_ref_is_reported(repo):
    r, _ = repo
    with pytest.raises(RefError):
        resolve(r, "main", "no-such-branch")


def test_short_abbreviates(repo):
    r, fork = repo
    abbreviated = short(r, fork)
    assert fork.startswith(abbreviated) and len(abbreviated) < len(fork)


def test_load_reads_what_pairup_wrote(tmp_path):
    (tmp_path / "refs.json").write_text(json.dumps(
        dict(base_ref="origin/main", head_ref="origin/f", base="a1", head="b2")))
    assert load(tmp_path)["base"] == "a1"


def test_load_without_refs_json_says_which_pass_is_missing(tmp_path):
    with pytest.raises(RefError, match="pairup"):
        load(tmp_path)


@pytest.fixture
def clone(tmp_path):
    """A clone whose origin gains a commit after the clone was taken."""
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "--initial-branch=main")
    git(origin, "config", "user.email", "t@example.com")
    git(origin, "config", "user.name", "T")
    (origin / "f.txt").write_text("one\n")
    git(origin, "add", "-A")
    git(origin, "commit", "--message", "one")
    git(origin, "checkout", "-b", "refactor/deep/name")
    git(origin, "commit", "--allow-empty", "--message", "branch work")

    work = tmp_path / "work"
    git(tmp_path, "clone", str(origin), str(work))
    git(origin, "commit", "--allow-empty", "--message", "pushed later")
    return work, git(origin, "rev-parse", "HEAD")


def test_fetch_advances_the_remote_tracking_ref(clone):
    """The whole point: work pushed after the last fetch becomes reviewable."""
    work, pushed = clone
    stale = git(work, "rev-parse", "origin/refactor/deep/name")
    assert stale != pushed

    done, warnings = fetch(work, ["origin/main", "origin/refactor/deep/name"])
    assert done == ["origin"] and warnings == []
    assert git(work, "rev-parse", "origin/refactor/deep/name") == pushed


def test_fetch_is_skipped_when_the_refs_name_commits(clone):
    """What keeps the pinned replay baseline off the network."""
    work, _ = clone
    assert fetch(work, ["52efff3", "1ce7bfa"]) == ([], [])


def test_fetch_failure_is_reported_but_not_raised(clone):
    """A build must survive being offline: older refs still describe a real
    state, and the page names the commits it used."""
    work, _ = clone
    git(work, "remote", "set-url", "origin", str(work / "gone"))
    done, warnings = fetch(work, ["origin/main"])
    assert done == []
    assert len(warnings) == 1 and "already on disk" in warnings[0]


def test_remote_of_handles_slashes_in_branch_names(clone):
    work, _ = clone
    assert remote_of(work, "origin/refactor/deep/name") == "origin"
    assert remote_of(work, "main") is None
    assert remote_of(work, "HEAD") is None
    assert remote_of(work, "52efff3") is None
