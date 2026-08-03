"""Resolve the two refs under review to concrete commits.

Every pass must diff and read blobs at the *same* pair of commits. pairup.py
resolves once and writes refs.json; every later pass loads it rather than
resolving again, so one run reviews one pair of commits even if the refs move
underneath it.

Resolving the base to the merge base rather than to the base branch's tip is
what makes a moving base branch safe to name in config.
"""
import json, os, pathlib, subprocess


class RefError(Exception):
    pass


def _git(repo, *args):
    proc = subprocess.run(["git", *args], capture_output=True, text=True,
                          cwd=repo)
    if proc.returncode:
        raise RefError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def resolve(repo, base, head):
    """Return (base_commit, head_commit) for the review.

    `base_commit` is `git merge-base base head`, never the base branch's tip.
    Against the tip, every commit the base branch gained since the fork shows
    up inside the review as if the PR had made it, and `git show <tip>:path`
    renders old files in a state the PR never touched.

    Idempotent: commits that are already resolved come back unchanged.
    """
    head_commit = _git(repo, "rev-parse", f"{head}^{{commit}}")
    return _git(repo, "merge-base", base, head_commit), head_commit


def short(repo, commit):
    return _git(repo, "rev-parse", "--short", commit)


def load(out):
    """The commits pairup.py resolved for this run."""
    path = pathlib.Path(out) / "refs.json"
    if not path.exists():
        raise RefError(f"{path} missing; run pairup.py first")
    return json.loads(path.read_text())


FETCH_TIMEOUT = 60


def remote_of(repo, ref, remotes=None):
    """The remote a ref tracks, or None for a commit, a local branch or HEAD.

    Split on the first slash only: branch names contain slashes, remote names
    do not.
    """
    remotes = set(_git(repo, "remote").split()) if remotes is None else remotes
    remote, slash, branch = ref.partition("/")
    return remote if slash and remote in remotes and branch else None


def fetch(repo, refs, timeout=FETCH_TIMEOUT):
    """Update the remotes the review's refs live on. Returns (done, warnings).

    A failure is never fatal: the refs already on disk still describe a real,
    if older, state, and the page names the commits it used -- a stale review
    that says which commits it is beats no review at all. The timeout is why
    this is not just a `git fetch`; a remote the user cannot reach would
    otherwise hang the build.
    """
    remotes = set(_git(repo, "remote").split())
    wanted = sorted({r for ref in refs
                     if (r := remote_of(repo, ref, remotes))})

    done, warnings = [], []
    for remote in wanted:
        try:
            proc = subprocess.run(
                ["git", "fetch", "--quiet", remote], cwd=repo,
                capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL,
                # Fail fast instead of prompting. The timeout alone would not
                # do it: a credential prompt reaches for the terminal, not
                # stdin, and the user is looking at pass output, not at git.
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        except subprocess.TimeoutExpired:
            warnings.append(f"git fetch {remote} timed out after {timeout}s; "
                            "reviewing the refs already on disk")
            continue
        if proc.returncode:
            detail = (proc.stderr.strip().splitlines() or ["no output"])[-1]
            warnings.append(f"git fetch {remote} failed ({detail}); "
                            "reviewing the refs already on disk")
        else:
            done.append(remote)
    return done, warnings
