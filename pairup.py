#!/usr/bin/env python3
"""Derive the canonical old->new pairing by name, independent of git's
content-similarity guess, then report where git disagrees.

Pairing by name rather than by content is the whole point: below git's 50%
rename threshold, content similarity starts pairing files that merely have the
same shape, and a confidently wrong pairing is worse than no pairing.
"""
import json, os, pathlib, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from config import load_config
from refs import resolve, short

S = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(os.environ.get("OUT") or (S / "build"))


class PairingError(Exception):
    pass


def expected_path(old, pairing):
    """Derive the new path from the old one by name alone.

    Content similarity is never consulted here. Directory segments are
    rewritten first, then the basename -- by an explicit override if there is
    one, otherwise by the ordered word list.
    """
    d, b = os.path.split(old)
    for a, z in pairing.path_rules:
        d = d.replace(a, z)
    if pairing.dir_segments and (
            pairing.dir_scope is None or pairing.dir_scope in d):
        d = "/".join(pairing.dir_segments.get(seg, seg) for seg in d.split("/"))
    if b in pairing.basenames:
        b = pairing.basenames[b]
    else:
        for a, z in pairing.words:
            b = b.replace(a, z)
    return f"{d}/{b}" if d else b


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

    # every old file that moved, per git (renamed or deleted)
    moved_old = list(git_pair) + dels
    canon, unresolved = {}, []
    for o in moved_old:
        n = expected_path(o, cfg.pairing)
        if n in head_tree:
            canon[o] = n
        elif o in git_pair:
            # no name-derived target exists (frozen rest/ names, verb-flipped
            # agents); git's own pairing is the best evidence we have
            canon[o] = git_pair[o][0]
        else:
            unresolved.append((o, n))

    used = set(canon.values())
    new_only = [a for a in adds if a not in used]

    print(f"old files that moved: {len(moved_old)}")
    print(f"canonically paired  : {len(canon)}")
    print(f"unresolved olds     : {len(unresolved)}")
    for o, guess in unresolved:
        print(f"   {o}\n      guessed {guess} (absent)   "
              f"git says {git_pair.get(o, ('-',))[0]}")
    print(f"genuinely new files : {len(new_only)}")
    for a in new_only:
        print(f"   {a}")
    check_collisions(canon)
    print("collisions          : []")

    print("\n=== git disagrees with the canonical pairing ===")
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
    print(f"\nwrote {OUT}/canonical-pairs.tsv")


if __name__ == "__main__":
    main()
