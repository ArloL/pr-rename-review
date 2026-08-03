#!/usr/bin/env python3
"""Build the side-by-side diff payload for every pair GitHub fails to show."""
import subprocess, difflib, re, json, html, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from config import load_config
from glossary import build_glossary
from refs import load

S = pathlib.Path(__file__).parent
CFG = load_config(S / ".pr-rename-review.toml")
normalize = build_glossary(CFG.glossary).normalize
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


def canon(s):
    """Case- and underscore-insensitive key. A German word that names both a
    Java field and a DB column has two right answers (`publicationDate`,
    `publication_date`); the glossary can only pick one, so a span that
    differs from its partner by nothing but case convention is the glossary's
    ambiguity, not a naming decision."""
    return s.replace("_", "").lower()


def wordspans(a, b, normalized):
    """Word-level spans. In normalized mode a span pair whose *new* side
    normalizes onto the *old* side is a phantom: German the rename froze on
    purpose (exception messages, prompt prose, log lines) that only differs
    because the glossary was applied to one side. Marked, never counted."""
    ta, tb = TOK.findall(a), TOK.findall(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    L, R = [], []
    phantom = 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        sa, sb = "".join(ta[i1:i2]), "".join(tb[j1:j2])
        if op == "equal":
            L.append(("=", sa)); R.append(("=", sb))
        elif op == "delete":
            L.append(("-", sa))
        elif op == "insert":
            R.append(("+", sb))
        elif normalized and canon(sa) == canon(sb):
            L.append(("=", sa)); R.append(("=", sb))
        elif normalized and normalize(sb) == sa:
            L.append(("~", sa)); R.append(("~", sb)); phantom += 1
        else:
            L.append(("-", sa)); R.append(("+", sb))
    return L, R, phantom


def render_spans(spans, kind):
    cls = "wd" if kind == "del" else "wa"
    out = []
    for t, s in spans:
        if t == "=":
            out.append(esc(s))
        elif t == "~":
            out.append(f'<em class="ph">{esc(s)}</em>')
        else:
            out.append(f'<em class="{cls}">{esc(s)}</em>')
    return "".join(out) or "&nbsp;"


def build(old_text, new_text, normalized=False):
    a, b = old_text.splitlines(), new_text.splitlines()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    rows, changed, wordtok, phantoms = [], 0, 0, 0
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
                    L, R, ph = wordspans(la, lb, normalized)
                    real = sum(1 for t, _ in L if t == "-") + sum(1 for t, _ in R if t == "+")
                    wordtok += real
                    phantoms += ph
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
    return rows, changed, wordtok, phantoms


scope = json.load(open(OUT / "scope.json"))

files = []
for r in scope:
    if r["identical"]:
        continue
    old, new = r["old"], r["new"]
    o, n = show(BASE, old), show(HEAD, new)
    raw_rows, raw_c, raw_w, _ = build(o, n)
    nrm_rows, nrm_c, nrm_w, nrm_ph = build(normalize(o), n, normalized=True)
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
        raw=raw_rows, nrm=nrm_rows, raw_c=raw_c, nrm_c=nrm_c,
        raw_w=raw_w, nrm_w=nrm_w, nrm_ph=nrm_ph, lines=len(n.splitlines())))

files.sort(key=lambda f: -f["nrm_w"])
empties = [r for r in scope if r["identical"]]
json.dump(dict(files=files, empties=empties), open(OUT / "diffdata2.json", "w"))

print(f"{len(files)} reviewable pairs, {len(empties)} identical-blob shuffles")
print(f"{'file':44} {'lines':>5} {'raw tok':>8} {'left':>6} {'froz':>5}  {'raw ln':>6} {'left':>5}")
for f in files:
    print(f"{f['newname'][:44]:44} {f['lines']:>5} {f['raw_w']:>8} {f['nrm_w']:>6} "
          f"{f['nrm_ph']:>5} {f['raw_c']:>6} {f['nrm_c']:>5}")
print(f"\nTOTAL tokens {sum(f['raw_w'] for f in files)} -> {sum(f['nrm_w'] for f in files)}"
      f"  (+{sum(f['nrm_ph'] for f in files)} frozen German)")
print(f"TOTAL lines  {sum(f['raw_c'] for f in files)} -> {sum(f['nrm_c'] for f in files)}")
print(f"cancel to zero: {sum(1 for f in files if f['nrm_w']==0)}")
