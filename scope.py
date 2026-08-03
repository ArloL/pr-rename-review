#!/usr/bin/env python3
"""Work out which canonical pairs GitHub fails to show, and how it fails."""
import subprocess, os, pathlib, json, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from refs import load

SP = os.path.dirname(os.path.abspath(__file__))
OUT = pathlib.Path(os.environ.get("OUT") or (pathlib.Path(__file__).parent / "build"))
OUT.mkdir(parents=True, exist_ok=True)
REPO = os.environ.get("REPO") or subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
# Resolved by pairup.py, not re-derived here: one run reviews one pair of
# commits, and BASE is the merge base rather than the base branch's tip.
_refs = load(OUT)
BASE, HEAD = _refs["base"], _refs["head"]

canon = {}
for ln in open(OUT / "canonical-pairs.tsv"):
    o, n, score, status = ln.rstrip("\n").split("\t")
    canon[o] = n

# what GitHub itself renders: -M50%, its default rename threshold
gh_ren, gh_score = {}, {}
for ln in subprocess.run(["git", "diff", "-M50%", "-l50000", "--name-status", f"{BASE}..{HEAD}"],
                         capture_output=True, text=True, cwd=REPO).stdout.splitlines():
    f = ln.split("\t")
    if f[0].startswith("R"):
        gh_ren[f[1]] = f[2]
        gh_score[f[1]] = int(f[0][1:])

# git's low-threshold opinion, for reporting the true similarity
low = {}
for ln in subprocess.run(["git", "diff", "-M01%", "-l50000", "--name-status", f"{BASE}..{HEAD}"],
                         capture_output=True, text=True, cwd=REPO).stdout.splitlines():
    f = ln.split("\t")
    if f[0].startswith("R"):
        low[f[1]] = (f[2], int(f[0][1:]))

rows = []
for o, n in sorted(canon.items()):
    sim = low[o][1] if o in low and low[o][0] == n else None
    if o in gh_ren and gh_ren[o] == n:
        continue                              # GitHub shows it correctly - out of scope
    kind = "mispaired" if o in gh_ren else "split"
    rows.append(dict(old=o, new=n, sim=sim, kind=kind,
                     gh_target=gh_ren.get(o), gh_score=gh_score.get(o)))

# Blob identity. Two files with the same hash have nothing to review, and a
# pair that is empty on both sides is why git cross-links these at all --
# identical content gives similarity nothing to work with.
EMPTY = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


def blob(ref, path):
    return subprocess.run(["git", "rev-parse", f"{ref}:{path}"], capture_output=True,
                          text=True, cwd=REPO).stdout.strip()


for r in rows:
    ho, hn = blob(BASE, r["old"]), blob(HEAD, r["new"])
    r["empty"] = ho == EMPTY and hn == EMPTY
    r["identical"] = ho == hn

json.dump(rows, open(OUT / "scope.json", "w"), indent=1)
# Counts the page needs but cannot derive from diffdata2.json, which only
# carries the in-scope pairs. Separate file so diffdata2.json keeps its shape.
json.dump(dict(canon_total=len(canon), gh_correct=len(canon) - len(rows),
               in_scope=len(rows),
               split=sum(1 for r in rows if r["kind"] == "split"),
               mispaired=sum(1 for r in rows if r["kind"] == "mispaired")),
          open(OUT / "scope-summary.json", "w"), indent=1)
with open(OUT / "pairs2.tsv", "w") as fh:
    for r in rows:
        fh.write(f"{r['old']}\t{r['new']}\n")

print(f"canonical pairs total      : {len(canon)}")
print(f"GitHub shows correctly     : {len(canon) - len(rows)}")
print(f"IN SCOPE                   : {len(rows)}")
print(f"  shown as add+delete      : {sum(1 for r in rows if r['kind']=='split')}")
print(f"  shown paired to the WRONG file: {sum(1 for r in rows if r['kind']=='mispaired')}")
print(f"  of those, identical blobs (nothing to review): "
      f"{sum(1 for r in rows if r['identical'])}")
for r in rows:
    if r["kind"] == "mispaired":
        print(f"    {r['old'].split('/')[-1]:34} gh->{r['gh_target'].split('/')[-1]:28} ({r['gh_score']}%)  true->{r['new'].split('/')[-1]}")
