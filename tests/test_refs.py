"""refs.py against a real repository built in a tmpdir.

The scenario that matters is the one the pinned base used to hide: the base
branch moves on after the fork. Resolving to its tip pulls those commits into
the review; resolving to the merge base does not.
"""
import json, subprocess
import pytest

from refs import (RefError, fetch, fetch_pull, has_ref, load, remote_for,
                  remote_of, resolve, short)


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


@pytest.fixture
def pull_origin(tmp_path):
    """An origin carrying refs/pull/259/head, the way GitHub serves one.

    `git clone` copies refs/heads/* only, so the clone starts without the pull
    ref and without any branch for the PR -- exactly the state a fork's PR
    leaves you in.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "--initial-branch=main")
    git(origin, "config", "user.email", "t@example.com")
    git(origin, "config", "user.name", "T")
    (origin / "f.txt").write_text("one\n")
    git(origin, "add", "-A")
    git(origin, "commit", "--message", "one")
    fork = git(origin, "rev-parse", "HEAD")

    git(origin, "checkout", "-b", "pr-branch")
    (origin / "pr.txt").write_text("the PR's own work\n")
    git(origin, "add", "-A")
    git(origin, "commit", "--message", "PR work")
    head = git(origin, "rev-parse", "HEAD")
    git(origin, "update-ref", "refs/pull/259/head", head)

    git(origin, "checkout", "main")
    (origin / "unrelated.txt").write_text("not the PR's work\n")
    git(origin, "add", "-A")
    git(origin, "commit", "--message", "main moves on")

    # Deleted before the clone: `git clone` copies every branch that exists
    # at clone time, and the point of this fixture is a clone that never had
    # the PR branch, or these tests prove nothing about the pull ref.
    git(origin, "branch", "--delete", "--force", "pr-branch")

    work = tmp_path / "work"
    git(tmp_path, "clone", str(origin), str(work))
    return work, fork, head


def bare(tmp_path, name="repo"):
    r = tmp_path / name
    r.mkdir()
    git(r, "init", "--initial-branch=main")
    return r


def test_fetch_pull_brings_the_pr_ref_into_the_private_namespace(pull_origin):
    work, _, head = pull_origin
    base, head_ref, warnings = fetch_pull(work, "origin", 259, "main")
    assert warnings == []
    assert (base, head_ref) == ("refs/pr-rename-review/259/base",
                                "refs/pr-rename-review/259/head")
    assert git(work, "rev-parse", head_ref) == head


def test_fetch_pull_needs_no_branch_for_the_pr(pull_origin):
    """The whole point of refs/pull/N/head: a fork's branch is not a remote
    tracking branch here, and the review works anyway."""
    work, _, head = pull_origin
    probe = subprocess.run(["git", "rev-parse", "--verify", "--quiet",
                            "origin/pr-branch"], cwd=work, capture_output=True)
    assert probe.returncode != 0, "the fixture leaked a branch for the PR"
    _, head_ref, _ = fetch_pull(work, "origin", 259, "main")
    assert git(work, "rev-parse", head_ref) == head


def test_fetch_pull_feeds_resolve_and_yields_the_merge_base(pull_origin):
    """End to end: the two names go straight into resolve, and the base comes
    out as the fork point rather than main's tip."""
    work, fork, head = pull_origin
    base_ref, head_ref, _ = fetch_pull(work, "origin", 259, "main")
    assert resolve(work, base_ref, head_ref) == (fork, head)
    assert git(work, "rev-parse", base_ref) != fork, "main did not move on"


def test_fetch_pull_writes_no_remote_tracking_branch(pull_origin):
    """Private namespace: reviewing a PR must not move anything the user has
    their own opinions about."""
    work, _, _ = pull_origin
    before = git(work, "for-each-ref", "--format=%(refname)", "refs/remotes")
    fetch_pull(work, "origin", 259, "main")
    assert git(work, "for-each-ref", "--format=%(refname)",
               "refs/remotes") == before


def test_fetch_pull_is_repeatable(pull_origin):
    """Forced refspecs: a second run updates in place rather than failing."""
    work, _, _ = pull_origin
    once = fetch_pull(work, "origin", 259, "main")
    assert fetch_pull(work, "origin", 259, "main") == once


def test_fetch_pull_failure_with_refs_on_disk_is_only_a_warning(pull_origin):
    """Offline, an older state still describes something real, and the page
    names the commits it used."""
    work, _, _ = pull_origin
    fetch_pull(work, "origin", 259, "main")
    git(work, "remote", "set-url", "origin", str(work / "gone"))
    _, _, warnings = fetch_pull(work, "origin", 259, "main")
    assert len(warnings) == 1 and "already on disk" in warnings[0]


def test_fetch_pull_failure_with_nothing_on_disk_is_fatal(pull_origin):
    """There is genuinely nothing to review. A warning here would build a page
    from refs that do not exist."""
    work, _, _ = pull_origin
    git(work, "remote", "set-url", "origin", str(work / "gone"))
    with pytest.raises(RefError, match="never been fetched"):
        fetch_pull(work, "origin", 259, "main")


def test_remote_for_matches_the_url_rather_than_trusting_origin(tmp_path):
    """In a fork checkout, origin is the fork and the PR lives upstream."""
    r = bare(tmp_path)
    git(r, "remote", "add", "origin", "git@github.com:contributor/hsp.git")
    git(r, "remote", "add", "upstream", "https://github.com/haeger/hsp.git")
    assert remote_for(r, "haeger", "hsp") == ("upstream", True)


def test_remote_for_matches_the_ssh_url_form(tmp_path):
    r = bare(tmp_path)
    git(r, "remote", "add", "ssh", "git@github.com:haeger/hsp.git")
    assert remote_for(r, "haeger", "hsp") == ("ssh", True)


def test_remote_for_ignores_case(tmp_path):
    """GitHub owner and repository names are case-insensitive; git URLs record
    whatever the user typed."""
    r = bare(tmp_path)
    git(r, "remote", "add", "origin", "https://github.com/Haeger/HSP.git")
    assert remote_for(r, "haeger", "hsp") == ("origin", True)


def test_remote_for_falls_back_to_origin(tmp_path):
    """`matched` is False here -- the caller's cue that this remote was never
    actually verified to hold the pull request being asked for."""
    r = bare(tmp_path)
    git(r, "remote", "add", "origin", "https://example.invalid/other/thing.git")
    assert remote_for(r, "haeger", "hsp") == ("origin", False)


def test_remote_for_without_any_remote_names_the_problem(tmp_path):
    r = bare(tmp_path)
    with pytest.raises(RefError, match="no remote"):
        remote_for(r, "haeger", "hsp")


def test_has_ref(pull_origin):
    work, _, _ = pull_origin
    assert has_ref(work, "refs/heads/main")
    assert not has_ref(work, "refs/pr-rename-review/259/head")
