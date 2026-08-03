#!/usr/bin/env python3
"""Derive the canonical old->new pairing from the branch's own history, then
report where git's endpoint guess disagrees.

The branch records its renames: a pure rename commit shows every move as an
exact (R100) per-commit rename, which cannot go stale the way a hand-kept
name table could. Endpoint content similarity is only the fallback for moves
the history cannot prove.
"""
import json, os, pathlib, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from refs import resolve, short

S = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(os.environ.get("OUT") or (S / "build"))


class PairingError(Exception):
    pass


def check_collisions(canon):
    """Two old paths deriving one new path is ambiguous, and silently keeping
    the last one would drop a file from the review entirely."""
    seen = {}
    for old, new in canon.items():
        seen.setdefault(new, []).append(old)
    clashes = {new: olds for new, olds in seen.items() if len(olds) > 1}
    if clashes:
        detail = "; ".join(f"{new} <- {', '.join(sorted(olds))}"
                           for new, olds in sorted(clashes.items()))
        raise PairingError(f"two old paths derive the same new path: {detail}")


def tree(repo, ref):
    return set(subprocess.run(["git", "ls-tree", "-r", "--name-only", ref],
                              capture_output=True, text=True,
                              cwd=repo).stdout.split())


def history_pairing(repo, base, head):
    """Moves recorded by the branch's own commits, chained across the range.

    Only exact (R100) per-commit renames count -- `git mv`'s fingerprint,
    immune to similarity guessing however heavily a later commit rewrites
    the file. Within one commit, exact candidates sharing a blob (zero-byte
    eval fixtures) are paired arbitrarily by git, so they are dropped rather
    than recorded as truth. Merge commits are skipped: their renames belong
    to the branch being merged.
    """
    pairs, origin = {}, {}
    commits = subprocess.run(["git", "rev-list", "--reverse", "--no-merges",
                              f"{base}..{head}"],
                             capture_output=True, text=True, cwd=repo).stdout.split()
    for c in commits:
        moves = []
        for ln in subprocess.run(["git", "diff", "-M50%", "-l50000",
                                  "--name-status", f"{c}^..{c}"],
                                 capture_output=True, text=True,
                                 cwd=repo).stdout.splitlines():
            f = ln.split("\t")
            if f[0] == "R100":
                moves.append((f[1], f[2]))
        if not moves:
            continue
        blob = {}
        for ln in subprocess.run(["git", "ls-tree", "-r", f"{c}^"],
                                 capture_output=True, text=True,
                                 cwd=repo).stdout.splitlines():
            meta, path = ln.split("\t", 1)
            blob[path] = meta.split()[2]
        counts = {}
        for o, _ in moves:
            counts[blob[o]] = counts.get(blob[o], 0) + 1
        for o, n in moves:
            if counts[blob[o]] > 1:
                continue
            first = origin.pop(o, o)
            pairs[first] = n
            origin[n] = first
    return pairs


def git_pairing(repo, base, head):
    """git's own low-threshold opinion. -l50000 defeats the default rename
    limit, which is well below the size of a repo-wide rename. No pathspec:
    filtering by the new path silently disables rename detection.

    Two dots, not three: `base` arrives already resolved to the merge base.
    """
    pairs, adds, dels = {}, [], []
    for ln in subprocess.run(
            ["git", "diff", "-M01%", "-l50000", "--name-status",
             f"{base}..{head}"],
            capture_output=True, text=True, cwd=repo).stdout.splitlines():
        f = ln.split("\t")
        if f[0].startswith("R"):
            pairs[f[1]] = (f[2], int(f[0][1:]))
        elif f[0] == "A":
            adds.append(f[1])
        elif f[0] == "D":
            dels.append(f[1])
    return pairs, adds, dels


def main():
    from config import load_config
    cfg = load_config(S / ".pr-rename-review.toml")
    repo = os.environ.get("REPO") or subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True).stdout.strip()
    base_ref = os.environ.get("BASE", cfg.base)
    head_ref = os.environ.get("HEAD_REF", cfg.head)
    base, head = resolve(repo, base_ref, head_ref)

    OUT.mkdir(parents=True, exist_ok=True)
    # The commits every later pass must use. A separate file rather than a key
    # in diffdata2.json, for the reason scope-summary.json is separate: that
    # payload's shape is the replay contract.
    json.dump(dict(base_ref=base_ref, head_ref=head_ref, base=base, head=head),
              open(OUT / "refs.json", "w"), indent=1)
    print(f"reviewing {head_ref} ({short(repo, head)}) "
          f"against merge base {short(repo, base)} of {base_ref}")

    head_tree = tree(repo, head)
    git_pair, adds, dels = git_pairing(repo, base, head)
    hist = history_pairing(repo, base, head)

    # every old file that moved, per git (renamed or deleted)
    moved_old = list(git_pair) + dels
    canon, unresolved = {}, []
    n_recorded = n_fallback = 0
    for o in moved_old:
        h = hist.get(o)
        if h and h in head_tree:
            canon[o] = h
            n_recorded += 1
        elif o in git_pair:
            # the history cannot prove this move (identical-blob shuffle, or
            # a rename folded into a content commit); git's endpoint guess is
            # the only evidence left
            canon[o] = git_pair[o][0]
            n_fallback += 1
        else:
            unresolved.append(o)

    used = set(canon.values())
    new_only = [a for a in adds if a not in used]

    print(f"old files that moved: {len(moved_old)}")
    print(f"recorded by rename commits : {n_recorded}")
    print(f"endpoint-similarity fallback: {n_fallback}")
    print(f"deleted or unpaired : {len(unresolved)}")
    for o in unresolved:
        print(f"   {o}")
    print(f"genuinely new files : {len(new_only)}")
    for a in new_only:
        print(f"   {a}")
    check_collisions(canon)
    print("collisions          : []")

    print("\n=== git's endpoint guess disagrees with the recorded moves ===")
    n_dis = 0
    for o, n in sorted(canon.items()):
        g = git_pair.get(o)
        if g is None:
            print(f"  git UNPAIRED  {o}\n             -> {n}")
            n_dis += 1
        elif g[0] != n:
            print(f"  git MISPAIRED {o}\n     git  {g[0]}  ({g[1]}%)\n"
                  f"     true {n}")
            n_dis += 1
    print(f"total disagreements: {n_dis}")

    with open(OUT / "canonical-pairs.tsv", "w") as fh:
        for o, n in sorted(canon.items()):
            g = git_pair.get(o)
            ok = g and g[0] == n
            status = "ok" if ok else ("unpaired" if g is None else "mispaired")
            fh.write(f"{o}\t{n}\t{g[1] if ok else ''}\t{status}\n")
    # The one-sided files, for scope.py to fold into the review. Separate from
    # canonical-pairs.tsv because that is a mapping of old->new and these have
    # only the one side; deriving either list again downstream would be a
    # second opinion that can drift from the one printed above.
    with open(OUT / "new-files.txt", "w") as fh:
        for a in sorted(new_only):
            fh.write(f"{a}\n")
    with open(OUT / "deleted-files.txt", "w") as fh:
        for d in sorted(unresolved):
            fh.write(f"{d}\n")
    print(f"\nwrote {OUT}/canonical-pairs.tsv")
    print(f"wrote {OUT}/new-files.txt")
    print(f"wrote {OUT}/deleted-files.txt")


if __name__ == "__main__":
    main()
