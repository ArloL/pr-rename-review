#!/usr/bin/env python3
"""Build the side-by-side word-diff payload for every file of the PR."""
import subprocess, difflib, re, json, html, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from refs import load

OUT = pathlib.Path(os.environ.get("OUT") or (pathlib.Path(__file__).parent / "build"))
OUT.mkdir(parents=True, exist_ok=True)
REPO = os.environ.get("REPO") or subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
# Resolved by pairup.py. BASE being the merge base is what makes `show(BASE, ..)`
# below read the old file as the PR forked it, not as the base branch has it now.
_refs = load(OUT)
BASE, HEAD = _refs["base"], _refs["head"]
TOK = re.compile(r"[A-Za-z0-9_]+|\s+|[^\sA-Za-z0-9_]")


def show(ref, p):
    return subprocess.run(["git", "show", f"{ref}:{p}"], capture_output=True,
                          text=True, cwd=REPO).stdout


def esc(s):
    return html.escape(s)


def wordspans(a, b):
    ta, tb = TOK.findall(a), TOK.findall(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    L, R = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        sa, sb = "".join(ta[i1:i2]), "".join(tb[j1:j2])
        if op == "equal":
            L.append(("=", sa)); R.append(("=", sb))
        elif op == "delete":
            L.append(("-", sa))
        elif op == "insert":
            R.append(("+", sb))
        else:
            L.append(("-", sa)); R.append(("+", sb))
    return L, R


def render_spans(spans, kind):
    cls = "wd" if kind == "del" else "wa"
    out = []
    for t, s in spans:
        if t == "=":
            out.append(esc(s))
        else:
            out.append(f'<em class="{cls}">{esc(s)}</em>')
    return "".join(out) or "&nbsp;"


def build(old_text, new_text):
    a, b = old_text.splitlines(), new_text.splitlines()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    rows, changed, wordtok = [], 0, 0
    ops = sm.get_opcodes()
    for idx, (op, i1, i2, j1, j2) in enumerate(ops):
        if op == "equal":
            n, keep = i2 - i1, 3
            seg = list(range(i1, i2))
            if n > keep * 2 + 1:
                head = seg[:keep] if idx > 0 else []
                tail = seg[-keep:] if idx < len(ops) - 1 else []
                for k in head:
                    rows.append(("ctx", k + 1, j1 + (k - i1) + 1, esc(a[k]), esc(a[k])))
                if head or tail:
                    rows.append(("gap", None, None, "", ""))
                for k in tail:
                    rows.append(("ctx", k + 1, j1 + (k - i1) + 1, esc(a[k]), esc(a[k])))
            else:
                for off, k in enumerate(seg):
                    rows.append(("ctx", k + 1, j1 + off + 1, esc(a[k]), esc(a[k])))
        elif op == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                la = a[i1 + k] if i1 + k < i2 else None
                lb = b[j1 + k] if j1 + k < j2 else None
                if la is not None and lb is not None:
                    L, R = wordspans(la, lb)
                    real = sum(1 for t, _ in L if t == "-") + sum(1 for t, _ in R if t == "+")
                    wordtok += real
                    rows.append(("chg", i1 + k + 1, j1 + k + 1,
                                 render_spans(L, "del"), render_spans(R, "add")))
                    if real:
                        changed += 1
                elif la is not None:
                    rows.append(("del", i1 + k + 1, None, esc(la), "")); changed += 1; wordtok += 1
                else:
                    rows.append(("add", None, j1 + k + 1, "", esc(lb))); changed += 1; wordtok += 1
        elif op == "delete":
            for k in range(i1, i2):
                rows.append(("del", k + 1, None, esc(a[k]), "")); changed += 1; wordtok += 1
        else:
            for k in range(j1, j2):
                rows.append(("add", None, k + 1, "", esc(b[k]))); changed += 1; wordtok += 1
    return rows, changed, wordtok


scope = json.load(open(OUT / "scope.json"))

# A pair with identical blobs is a pure move: nothing to word-review, but
# GitHub lists it and it needs its Viewed tick, so it stays a file with an
# empty diff.
files = []
for r in scope:
    old, new = r["old"], r["new"]
    o, n = show(BASE, old), show(HEAD, new)
    raw_rows, raw_c, raw_w = build(o, n)
    area = ("test" if new.startswith("src/test/java") else
            "fixture" if "/resources/" in new else
            "doc" if new.startswith("docs/") else "main")
    files.append(dict(
        old=old, new=new, oldname=old.split("/")[-1], newname=new.split("/")[-1],
        oldpkg="/".join(old.split("/")[:-1]), newpkg="/".join(new.split("/")[:-1]),
        sim=r["sim"], kind=r["kind"], gh_target=r["gh_target"], gh_score=r["gh_score"],
        # `prev` marked files reviewed elsewhere, fed by a pairs.tsv no pass
        # has written since the prototype was split. Always false; the key
        # stays because render2.py still reads it.
        area=area, prev=False,
        raw=raw_rows, raw_c=raw_c, raw_w=raw_w, lines=len(n.splitlines())))

files.sort(key=lambda f: -f["raw_w"])
json.dump(dict(files=files), open(OUT / "diffdata2.json", "w"))

print(f"{len(files)} reviewable pairs")
print(f"{'file':44} {'lines':>5} {'tokens':>7} {'chg ln':>6}")
for f in files:
    print(f"{f['newname'][:44]:44} {f['lines']:>5} {f['raw_w']:>7} {f['raw_c']:>6}")
print(f"\nTOTAL tokens {sum(f['raw_w'] for f in files)}")
print(f"TOTAL lines  {sum(f['raw_c'] for f in files)}")
print(f"unchanged beyond the move: {sum(1 for f in files if f['raw_w']==0)}")
