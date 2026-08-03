"""Resolve the two refs under review to concrete commits.

Every pass must diff and read blobs at the *same* pair of commits. pairup.py
resolves once and writes refs.json; every later pass loads it rather than
resolving again, so one run reviews one pair of commits even if the refs move
underneath it.

Resolving the base to the merge base rather than to the base branch's tip is
what makes a moving base branch safe to name in config.
"""
import json, pathlib, subprocess


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
