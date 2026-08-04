import json, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from github import pr_url
from refs import load

OUT = pathlib.Path(os.environ.get("OUT") or (pathlib.Path(__file__).parent / "build"))
OUT.mkdir(parents=True, exist_ok=True)
files = json.loads((OUT / "diffdata2.json").read_text())["files"]

# From the run, never from a ref name: with a moving head ref the name alone
# is true of every build ever made, and `--base`/`--head` overrides carry no
# name at all. Printing the commit is what makes a stale page look stale.
REFS = load(OUT)
BASE_SHORT, HEAD_SHORT = REFS["base"][:9], REFS["head"][:9]
SUMMARY = json.loads((OUT / "scope-summary.json").read_text()) if (
    OUT / "scope-summary.json").exists() else {}

# Resolved once by cli.py and handed down, so every pass agrees on which PR
# this is and only one gh call is made per run. `build` must work with no gh
# at all -- and with `--base`/`--head`, where there is no PR; the deep links
# are simply absent then.
PR = int(os.environ["PR"]) if os.environ.get("PR") else None
OWNER = os.environ.get("PR_OWNER") or None
REPO_NAME = os.environ.get("PR_REPO") or None


PFX = [("src/main/java/de/haegerconsulting/hsp/", "main·"),
       ("src/test/java/de/haegerconsulting/hsp/", "test·"),
       ("src/test/resources/", "res·"),
       ("src/main/resources/", "res·")]


def short(p):
    for a, b in PFX:
        if p.startswith(a):
            return b + p[len(a):]
    return p


compact = []
for f in files:
    compact.append({
        "id": f["new"], "oid": f["old"],
        "on": f["oldname"], "nn": f["newname"],
        "op": short(f["oldpkg"]), "np": short(f["newpkg"]),
        "sim": f["sim"], "kind": f["kind"],
        "ght": short(f["gh_target"] or "") if f["gh_target"] else None,
        "ghs": f["gh_score"], "area": f["area"], "prev": f["prev"],
        "gh": pr_url(OWNER, REPO_NAME, PR, f["new"]),
        "rc": f["raw_c"], "rw": f["raw_w"], "L": f["lines"],
        "R": [[r[0], r[1], r[2], r[3], r[4]] for r in f["raw"]]})

DATA = json.dumps(compact, separators=(",", ":"))
maxw = max(c["rw"] for c in compact) or 1
n_clean = sum(1 for c in compact if c["rw"] == 0)
n_wrong = sum(1 for c in compact if c["kind"] == "mispaired")
n_mod = sum(1 for c in compact if c["kind"] == "modified")
n_shown = sum(1 for c in compact if c["kind"] == "shown")
n_added = sum(1 for c in compact if c["kind"] == "added")
n_deleted = sum(1 for c in compact if c["kind"] == "deleted")
n_prev = sum(1 for c in compact if c["prev"])
n_pairs = len(compact)
# Counted directly rather than as the leftover: a new kind used to land in
# whichever bucket was the remainder, which is how added files first went
# missing from the prose while sitting in the list.
n_split = sum(1 for c in compact if c["kind"] == "split")
n_renames = SUMMARY.get("canon_total", n_pairs)
n_correct = SUMMARY.get("gh_correct", 0)
tot_raw = sum(c["rw"] for c in compact)


def _list(items):
    """`a`, `a and b`, `a, b and c`."""
    return " and ".join(items) if len(items) < 3 else (
        ", ".join(items[:-1]) + " and " + items[-1])


# The kinds that ride along because the review covers the whole PR, not
# because GitHub hides them. A branch that is purely a rename usually has no
# add and no deletion git cannot pair, and a sentence that announces "0 files
# the PR deletes" on every build teaches the eye to skip the whole paragraph,
# so each clause appears only when it has something to describe.
riders = ["those"]
if n_mod:
    riders.append(f"the {n_mod} files changed <b>in place</b>")
if n_added:
    riders.append(f"the {n_added} the PR <b>adds</b>")
if n_deleted:
    riders.append(f"the {n_deleted} it <b>deletes</b>")
RIDERS = _list(riders)

CSS = """
:root{
  --ground:#FAFAFC; --surface:#FFFFFF; --ink:#171A22; --ink-2:#5A6072; --ink-3:#8A90A2;
  --rule:#E3E5ED; --accent:#4C4FD4; --accent-soft:#EDEDFA;
  --del-bg:#FDEAEF; --del-mark:#F6BFCC; --del-ink:#96203E;
  --add-bg:#E7F4EB; --add-mark:#ABE2BD; --add-ink:#1A6335;
  --warn:#B4571B; --warn-soft:#FBEEE3;
  --mono:ui-monospace,"SF Mono","Cascadia Code","JetBrains Mono",Menlo,Consolas,monospace;
  --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
}
@media (prefers-color-scheme:dark){:root{
  --ground:#0F1116; --surface:#161923; --ink:#E6E8F0; --ink-2:#979DB2; --ink-3:#6E7488;
  --rule:#252A37; --accent:#9294F7; --accent-soft:#1D1F31;
  --del-bg:#33191F; --del-mark:#5D2333; --del-ink:#F2A8BA;
  --add-bg:#12291C; --add-mark:#1E5233; --add-ink:#8AD8A5;
  --warn:#E39152; --warn-soft:#2C1E12;
}}
:root[data-theme="dark"]{
  --ground:#0F1116; --surface:#161923; --ink:#E6E8F0; --ink-2:#979DB2; --ink-3:#6E7488;
  --rule:#252A37; --accent:#9294F7; --accent-soft:#1D1F31;
  --del-bg:#33191F; --del-mark:#5D2333; --del-ink:#F2A8BA;
  --add-bg:#12291C; --add-mark:#1E5233; --add-ink:#8AD8A5;
  --warn:#E39152; --warn-soft:#2C1E12;
}
:root[data-theme="light"]{
  --ground:#FAFAFC; --surface:#FFFFFF; --ink:#171A22; --ink-2:#5A6072; --ink-3:#8A90A2;
  --rule:#E3E5ED; --accent:#4C4FD4; --accent-soft:#EDEDFA;
  --del-bg:#FDEAEF; --del-mark:#F6BFCC; --del-ink:#96203E;
  --add-bg:#E7F4EB; --add-mark:#ABE2BD; --add-ink:#1A6335;
  --warn:#B4571B; --warn-soft:#FBEEE3;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--mono);
     font-size:13px;line-height:1.55;-webkit-font-smoothing:antialiased}
.masthead{border-bottom:1px solid var(--rule);background:var(--surface);padding:22px 26px 18px}
.masthead h1{margin:0;font-size:15px;font-weight:650;letter-spacing:-.01em;text-wrap:balance}
.sub{margin:5px 0 0;font-size:11.5px;color:var(--ink-3);letter-spacing:.02em}
.sub .sha{font-family:var(--mono);opacity:.75}
.note{font-family:var(--sans);font-size:12.5px;line-height:1.62;color:var(--ink-2);
      max-width:70ch;margin:14px 0 0}
.note b{color:var(--ink);font-weight:600}
.note code{font-family:var(--mono);font-size:11.5px;background:var(--accent-soft);
      color:var(--accent);padding:1px 5px;border-radius:3px}
.tally{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));margin:16px 0 0;
      border:1px solid var(--rule);border-radius:7px;overflow:hidden;max-width:70ch}
.tally div{padding:9px 14px;border-right:1px solid var(--rule);min-width:0;
      display:flex;flex-direction:column;justify-content:space-between;gap:4px}
.tally div:last-child{border-right:0}
@media (max-width:720px){.tally{grid-template-columns:repeat(2,minmax(0,1fr))}
  .tally div{border-bottom:1px solid var(--rule)}}
.tally .k{font-size:9.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-3);
      line-height:1.35}
.tally .v{font-size:16px;font-weight:600;font-variant-numeric:tabular-nums}
.bar{display:flex;flex-wrap:wrap;gap:16px;align-items:center;padding:11px 26px;
     border-bottom:1px solid var(--rule);background:var(--surface);position:sticky;top:0;z-index:5}
.seg{display:flex;border:1px solid var(--rule);border-radius:6px;overflow:hidden}
.seg button{font:inherit;font-size:11.5px;padding:5px 13px;background:transparent;color:var(--ink-2);
     border:0;cursor:pointer;letter-spacing:.01em}
.seg button+button{border-left:1px solid var(--rule)}
.seg button[aria-pressed="true"]{background:var(--accent);color:#fff}
.seg button:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:11px;color:var(--ink-3);letter-spacing:.03em}
.legend i{font-style:normal;padding:1px 6px;border-radius:3px}
.legend .d{background:var(--del-mark);color:var(--del-ink)}
.legend .a{background:var(--add-mark);color:var(--add-ink)}
.console{display:grid;grid-template-columns:290px minmax(0,1fr);min-height:calc(100vh - 240px)}
.index{border-right:1px solid var(--rule);background:var(--surface);padding:12px 0;overflow-y:auto}
.ixhead{font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3);
     padding:4px 18px 9px}
.item{display:block;width:100%;text-align:left;font:inherit;background:transparent;border:0;
     cursor:pointer;padding:8px 18px;border-left:2px solid transparent;color:var(--ink)}
.item:hover{background:var(--accent-soft)}
.item[aria-current="true"]{background:var(--accent-soft);border-left-color:var(--accent)}
.item:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.item .nm{font-size:12px;display:flex;gap:6px;align-items:baseline}
.item .nm .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.item .mt{font-size:10.5px;color:var(--ink-3);display:flex;justify-content:space-between;
     gap:8px;margin-top:3px;font-variant-numeric:tabular-nums}
.item .mt .p{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.item .mt .n{flex:none}
.meter{display:block;height:2px;background:var(--rule);margin-top:5px;border-radius:2px;
     overflow:hidden}
.meter span{display:block;height:2px;background:var(--accent)}
.tag{font-size:9.5px;letter-spacing:.05em;text-transform:uppercase;padding:1px 5px;
     border-radius:3px;flex:none;font-weight:600}
.tag.wrong{background:var(--warn-soft);color:var(--warn)}
.tag.seen{background:var(--rule);color:var(--ink-3)}
.tag.mod{background:var(--rule);color:var(--ink-3)}
.tag.clean{background:var(--add-mark);color:var(--add-ink)}
.tag.gone{background:var(--del-mark);color:var(--del-ink)}
.item.done .nm .t{color:var(--ink-3);text-decoration:line-through;
     text-decoration-color:var(--rule)}
.item.done .tick{color:var(--add-ink);flex:none;font-size:11px}
.prog{font-size:11px;color:var(--ink-3);font-variant-numeric:tabular-nums;
     display:flex;align-items:center;gap:9px}
.prog .track{width:70px;height:3px;background:var(--rule);border-radius:2px;overflow:hidden}
.prog .track span{display:block;height:3px;background:var(--add-ink)}
.linkbtn{font:inherit;font-size:11px;background:none;border:0;color:var(--ink-3);
     cursor:pointer;padding:0;text-decoration:underline;text-underline-offset:2px}
.linkbtn:hover{color:var(--ink)}
.linkbtn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.acts{display:flex;gap:9px;align-items:center;margin-top:10px;flex-wrap:wrap}
.btn{font:inherit;font-size:11.5px;padding:5px 12px;border-radius:6px;cursor:pointer;
     border:1px solid var(--accent);background:var(--accent);color:#fff}
.btn.ghost{background:transparent;color:var(--ink-2);border-color:var(--rule)}
.btn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.kbd{font-size:10.5px;color:var(--ink-3);letter-spacing:.02em}
.pane{overflow:auto;padding:0 0 60px}
.paths{padding:16px 26px 13px;border-bottom:1px solid var(--rule);background:var(--surface)}
.paths .old{color:var(--del-ink)}
.paths .new{color:var(--add-ink)}
.paths .arrow{color:var(--ink-3);padding:0 8px}
.paths .stat{font-size:11px;color:var(--ink-3);margin-top:6px;font-variant-numeric:tabular-nums}
.flag{font-family:var(--sans);font-size:12px;line-height:1.55;color:var(--warn);
     background:var(--warn-soft);border:1px solid var(--warn);border-radius:6px;
     padding:9px 12px;margin:12px 0 0;max-width:82ch}
.flag b{font-weight:650}
.wrap{overflow-x:auto}
table.diff{border-collapse:collapse;width:100%;table-layout:fixed;font-size:12.5px}
table.diff col.g{width:52px}
table.diff td{padding:1px 10px;vertical-align:top;white-space:pre-wrap;word-break:break-word}
td.gut{color:var(--ink-3);text-align:right;user-select:none;font-variant-numeric:tabular-nums;
     font-size:11px;padding-top:2px;border-right:1px solid var(--rule);background:var(--surface)}
tr.chg td.l,tr.del td.l{background:var(--del-bg)}
tr.chg td.r,tr.add td.r{background:var(--add-bg)}
td.l,td.r{border-right:1px solid var(--rule)}
em.wd{font-style:normal;background:var(--del-mark);color:var(--del-ink);border-radius:2px}
em.wa{font-style:normal;background:var(--add-mark);color:var(--add-ink);border-radius:2px}
tr.gap td{background:var(--ground);color:var(--ink-3);text-align:center;font-size:10px;
     letter-spacing:.3em;padding:3px 0}
.empty{padding:26px;font-family:var(--sans);font-size:12.5px;color:var(--ink-2)}
.foot{border-top:1px solid var(--rule);background:var(--surface);padding:20px 26px 30px}
.foot h2{margin:0 0 8px;font-size:12px;font-weight:650;letter-spacing:.02em}
.foot p{font-family:var(--sans);font-size:12.5px;line-height:1.6;color:var(--ink-2);
     max-width:70ch;margin:0 0 12px}
.foot .scroll{overflow-x:auto;max-width:100%}
.foot table{border-collapse:collapse;font-size:11.5px}
.foot td{padding:2px 14px 2px 0;color:var(--ink-3);white-space:nowrap}
.foot td.ok{color:var(--add-ink)}
@media (max-width:880px){
  .console{grid-template-columns:1fr}
  .index{border-right:0;border-bottom:1px solid var(--rule);max-height:230px}
  table.diff col.g{width:38px}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
.syncst{font-size:12px;color:var(--ink-3);white-space:nowrap}
.syncst.warn{color:var(--warn);font-weight:600}
.ghlink{margin-left:6px;color:var(--ink-3);text-decoration:none;font-size:12px}
.ghlink:hover{color:var(--accent)}
a.btn.ghost{text-decoration:none;display:inline-block}
/* Gutter line numbers double as "comment on this line in GitHub" links. They
   must not read as links until hovered, or 1,489 changed lines turn blue. */
td.gut a{color:inherit;text-decoration:none}
td.gut a:hover{color:var(--accent);text-decoration:underline}
td.gut a:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
#unk{margin-top:24px}
#unk ul{margin:8px 0 0 18px;font-family:var(--mono);font-size:12px}
"""

# The page names its own encoding rather than relying on the server's
# Content-Type. server.py sends `charset=utf-8`, but the file is also opened
# straight from `build/` and served by other static servers, and without this
# the arrows and em dashes come out as mojibake wherever the header is absent.
HTML = f"""<meta charset="utf-8">
<title>The German→English rename — word-level review</title>
<style>{CSS}</style>
<div class="masthead">
  <h1>The German→English rename · word-level review</h1>
  <p class="sub">{REFS["head_ref"]} <span class="sha">{HEAD_SHORT}</span> &nbsp;·&nbsp; forked from {REFS["base_ref"]} at <span class="sha">{BASE_SHORT}</span> &nbsp;·&nbsp; {n_renames} renames total, {n_correct} of them GitHub shows correctly &nbsp;·&nbsp; {n_mod} files changed in place</p>
  <p class="note">Every file the PR touches is here. GitHub shows {n_shown} of the renames
  correctly; {RIDERS} ride along so the whole PR can
  be reviewed and ticked in one spot. The rest is what GitHub's diff does <b>not</b> put side by
  side, failing two ways: {n_split} pairs fall under its 50&#37; rename threshold and render as an
  unrelated delete plus add, and {n_wrong} it <i>does</i> pair — to the <b>wrong file</b>,
  because content similarity picked the partner rather than the name.
  <br><br>GitHub's per-file <b>Viewed</b> ticks are read and written through your own
  <code>gh</code> login, so a tick here is a tick on the PR and a tick on the PR shows up here.
  <b>V</b> marks the open file viewed and jumps to the next one; <b>J</b> and <b>K</b> step
  through the list. To comment, follow the ↗ link into GitHub's diff — this page does not write
  comments.</p>
  <div class="tally">
    <div><div class="k">files</div><div class="v">{n_pairs}</div></div>
    <div><div class="k">changed tokens</div><div class="v">{tot_raw:,}</div></div>
    <div><div class="k">clean</div><div class="v">{n_clean}</div></div>
  </div>
</div>
<div class="bar">
  <div class="seg" role="group" aria-label="Filter">
    <button class="flt" data-f="all" aria-pressed="true">All {n_pairs}</button>
    <button class="flt" data-f="todo" aria-pressed="false">Unviewed {n_pairs}</button>
    <button class="flt" data-f="work" aria-pressed="false">Needs a look {n_pairs - n_clean}</button>
    <button class="flt" data-f="hidden" aria-pressed="false">Hidden {n_split + n_wrong}</button>
    <button class="flt" data-f="wrong" aria-pressed="false">Wrong pair {n_wrong}</button>
    <button class="flt" data-f="mod" aria-pressed="false">In place {n_mod}</button>
  </div>
  <div class="prog"><span class="track"><span id="pbar" style="width:0%"></span></span>
    <span id="ptxt">0 of {n_pairs} viewed</span>
    <button class="linkbtn" id="reset">reset</button></div>
  <span id="syncst" class="syncst">Checking GitHub…</span>
  <div class="legend"><i class="d">removed</i><i class="a">added</i></div>
</div>
<div class="console">
  <nav class="index" aria-label="Files"><div class="ixhead" id="ixh"></div><div id="ix"></div></nav>
  <section class="pane"><div id="pane"></div></section>
</div>
<div class="foot">
  <div id="unk"></div>
</div>
<script>
const D={DATA},MAXW={maxw};
let cur=0,flt='all';
const ix=document.getElementById('ix'),pane=document.getElementById('pane'),ixh=document.getElementById('ixh');

// Viewed state lives in GitHub, reached through the local server, so a tick
// here is the same tick a teammate sees on the PR. localStorage is the
// fallback for when `gh` is unavailable.
const KEY='hsp-hidden-renames-viewed-v1';
let viewed=new Set(),synced=false,unknown=[],known=new Set();
function saveLocal(){{try{{localStorage.setItem(KEY,JSON.stringify([...viewed]));}}catch(e){{}}}}
function loadLocal(){{try{{viewed=new Set(JSON.parse(localStorage.getItem(KEY)||'[]'));}}catch(e){{}}}}
function isDone(f){{return viewed.has(f.id);}}

function banner(text,warn){{
  const el=document.getElementById('syncst');
  if(!el)return;
  el.textContent=text;
  el.className=warn?'syncst warn':'syncst';
}}

async function loadViewed(){{
  try{{
    const r=await fetch('/api/viewed');
    const j=await r.json();
    if(j.synced){{
      synced=true;
      viewed=new Set(Object.entries(j.states)
        .filter(([,v])=>v==='VIEWED').map(([k])=>k));
      known=new Set(Object.keys(j.states));
      unknown=D.filter(f=>!known.has(f.id)).map(f=>f.id);
      banner(unknown.length
        ? 'Synced with GitHub — '+unknown.length+' file(s) missing from its list, see below'
        : 'Viewed state synced with GitHub', unknown.length>0);
    }}else{{
      loadLocal();
      banner('Not synced with GitHub ('+(j.reason||'unknown')+
             ') — ticks stay in this browser',true);
    }}
  }}catch(e){{
    loadLocal();
    banner('Local-only: the review server is not reachable',true);
  }}
  draw();
}}

// A sub-threshold pair is two entries in GitHub's file list -- the deleted
// old path and the added new path -- so one tick covers both. Mispaired
// files are excluded: GitHub folded their old path into a bogus rename
// entry, and there is nothing separate to tick. So is an old path GitHub
// does not list, because the mutation would be rejected whole.
function ghPaths(id){{
  const f=D.find(f=>f.id===id);
  return f&&f.kind==='split'&&known.has(f.oid)?[id,f.oid]:[id];
}}

async function setViewed(id,on){{
  const paths=ghPaths(id);
  const had=paths.filter(p=>viewed.has(p));
  paths.forEach(p=>on?viewed.add(p):viewed.delete(p));
  draw();
  if(!synced||unknown.includes(id)){{saveLocal();return true;}}
  try{{
    const r=await fetch('/api/viewed',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{paths,viewed:on}})}});
    if(!r.ok)throw new Error(await r.text());
    return true;
  }}catch(e){{
    // Revert. A tick that never reached GitHub would mean a file marked
    // reviewed that nobody reviewed.
    paths.forEach(p=>had.includes(p)?viewed.add(p):viewed.delete(p));
    banner('GitHub rejected that change — tick reverted',true);
    draw();
    return false;
  }}
}}

function drawUnknown(){{
  const el=document.getElementById('unk');
  if(!el)return;
  el.innerHTML=unknown.length
    ? '<h2>Not in GitHub&#39;s file list</h2><p>These ticks stay in this browser. '+
      'A path here usually means the derived new path is wrong — check the '+
      'pairing report.</p><ul>'+unknown.map(u=>`<li>${{u}}</li>`).join('')+'</ul>'
    : '';
}}

function pass(f){{
  if(flt==='todo')return !isDone(f);
  if(flt==='work')return f.rw>0;
  if(flt==='hidden')return f.kind==='split'||f.kind==='mispaired';
  if(flt==='wrong')return f.kind==='mispaired';
  if(flt==='mod')return f.kind==='modified';
  return true;
}}
function view(){{return D.map((f,i)=>[f,i]).filter(([f])=>pass(f));}}
function drawProgress(){{
  const n=D.filter(isDone).length;
  document.getElementById('pbar').style.width=Math.round(100*n/D.length)+'%';
  document.getElementById('ptxt').textContent=`${{n}} of ${{D.length}} viewed`;
  document.querySelector('.flt[data-f="todo"]').textContent=`Unviewed ${{D.length-n}}`;
}}
function drawIndex(){{
  const v=view();
  ixh.textContent=`${{v.length}} file${{v.length===1?'':'s'}} · ranked by changed tokens`;
  ix.innerHTML=v.map(([f,i])=>{{
    const w=f.rw, c=f.rc, done=isDone(f);
    const tags=(f.kind==='mispaired'?'<span class="tag wrong">wrong pair</span>':'')+
               (f.kind==='modified'?'<span class="tag mod">in place</span>':'')+
               (f.kind==='added'?'<span class="tag mod">new file</span>':'')+
               (f.kind==='deleted'?'<span class="tag gone">deleted</span>':'')+
               (f.prev?'<span class="tag seen">prev</span>':'')+
               (f.rw===0?'<span class="tag clean">clean</span>':'');
    // stopPropagation: without it the link click also fires the row handler.
    const gh=f.gh?`<a class="ghlink" href="${{f.gh}}" target="_blank" rel="noopener"
      onclick="event.stopPropagation()" title="Open in GitHub to comment">↗</a>`:'';
    return `<button class="item${{done?' done':''}}" data-i="${{i}}" aria-current="${{i===cur}}">
      <span class="nm">${{done?'<span class="tick">✓</span>':''}}<span class="t">${{f.nn}}</span>${{tags}}${{gh}}</span>
      <span class="mt"><span class="p">${{f.np}}</span><span class="n">${{w}} tok · ${{c}} ln</span></span>
      <span class="meter"><span style="width:${{Math.max(2,Math.round(100*w/MAXW))}}%"></span></span>
    </button>`;}}).join('')||'<div class="empty">Nothing left under this filter.</div>';
}}
function drawPane(){{
  const f=D[cur];
  if(!f){{pane.innerHTML='<div class="empty">Nothing selected.</div>';return;}}
  const rows=f.R;
  const body=rows.map(r=>{{
    if(r[0]==='gap')return '<tr class="gap"><td colspan="4">···</td></tr>';
    const ln=r[1]==null?'':r[1], rn=r[2]==null?'':r[2];
    // The new-side line number links to that line in GitHub's diff. f.gh
    // already ends with the file anchor, so R<n> targets the right side.
    const rcell=(f.gh&&rn)
      ? `<a href="${{f.gh}}R${{rn}}" target="_blank" rel="noopener"
           title="Comment on line ${{rn}} in GitHub">${{rn}}</a>`
      : rn;
    return `<tr class="${{r[0]}}"><td class="gut">${{ln}}</td><td class="l">${{r[3]||'&nbsp;'}}</td>`+
           `<td class="gut">${{rcell}}</td><td class="r">${{r[4]||'&nbsp;'}}</td></tr>`;
  }}).join('');
  const how=f.kind==='shown'
    ? (f.rw===0
       ? `<div class="flag">A pure move — the content is identical, so beyond the new path there
          is nothing to review. GitHub shows the rename correctly.</div>`
       : `<div class="flag">GitHub pairs this rename correctly${{f.ghs?` at ${{f.ghs}}&#37;
          similarity`:''}} — nothing hidden; it is here so the whole PR reviews in one
          place.</div>`)
    : f.kind==='modified'
    ? `<div class="flag">Changed <b>in place</b> — the path never moved, so GitHub shows this
       diff normally. It is here so the review covers every file the rename touched.</div>`
    : f.kind==='added'
    ? `<div class="flag"><b>New file</b> — the PR adds it, so there is no base side and every
       line is an addition. GitHub shows it normally; it is here so the review covers every
       file the PR touches.</div>`
    : f.kind==='deleted'
    ? `<div class="flag"><b>Deleted</b> — the PR removes it, and no rename claims the content,
       so there is no head side and every line is a removal. If this file was meant to move
       rather than go, the pairing report is where that shows up.</div>`
    : f.kind==='mispaired'
    ? `<div class="flag"><b>GitHub shows this file paired to the wrong partner.</b> It renders
       <code>${{f.on}}</code> → <code>${{f.ght}}</code> at ${{f.ghs}}&#37; similarity. The pairing above is
       the one the names support.</div>`
    : (f.sim==null
       ? `<div class="flag"><b>Git pairs this at no threshold at all.</b> There is no rename-detection
          setting, on GitHub or locally, that shows these two files side by side.</div>`
       : `<div class="flag">Similarity <b>${{f.sim}}&#37;</b> — under GitHub's 50&#37; threshold, so it
          renders there as an unrelated delete plus add. Locally:
          <code>git diff -M${{Math.max(1,f.sim-2)}}% --word-diff</code>, with <b>both</b> paths in the
          pathspec or rename detection silently switches off again.</div>`);
  pane.innerHTML=`<div class="paths">
      ${{f.kind==='modified'||f.kind==='added'||f.kind==='deleted'
        ? `<span class="new">${{f.nn}}</span>`
        : `<span class="old">${{f.on}}</span><span class="arrow">→</span><span class="new">${{f.nn}}</span>`}}
      <div class="stat">${{f.kind==='modified'||f.kind==='added'||f.kind==='deleted'?f.np:`${{f.op}} → ${{f.np}}`}}</div>
      <div class="stat">${{f.L}} lines · ${{f.rc}} changed lines · ${{f.rw}} highlighted tokens</div>
      ${{how}}
      <div class="acts">
        <button class="btn" id="mv">${{isDone(f)?'Next unviewed':'Mark viewed &amp; next'}}</button>
        ${{isDone(f)?'<button class="btn ghost" id="unmv">Unmark</button>':''}}
        ${{f.gh?`<a class="btn ghost" href="${{f.gh}}" target="_blank" rel="noopener">Open in GitHub ↗</a>`:''}}
        <span class="kbd">V marks viewed · J / K step through files · click a right-hand line number to comment on it</span>
      </div>
    </div>
    <div class="wrap"><table class="diff"><colgroup><col class="g"><col><col class="g"><col></colgroup><tbody>${{body}}</tbody></table></div>`;
}}
function draw(){{drawIndex();drawPane();drawProgress();drawUnknown();bindActions();}}
function toTop(){{
  document.querySelector('.pane').scrollTop=0;
  // The columns scroll with the document, not internally, so selecting a file
  // far down the index would otherwise land mid-diff. Scroll the window back
  // up until the content view sits just under the sticky bar.
  const top=document.querySelector('.console').getBoundingClientRect().top
            +window.scrollY-document.querySelector('.bar').offsetHeight;
  if(window.scrollY>top)window.scrollTo(0,top);
}}
function step(d){{
  const v=view(); if(!v.length)return;
  let at=v.findIndex(([,i])=>i===cur);
  if(at<0)at=0; else at=Math.min(v.length-1,Math.max(0,at+d));
  cur=v[at][1];draw();toTop();
}}
function nextTodo(){{
  const v=view().filter(([f,i])=>i!==cur&&!isDone(f));
  if(!v.length){{draw();return;}}
  // The next unviewed file below the current one, wrapping to the top only
  // when everything below is already done.
  const nxt=v.find(([,i])=>i>cur)||v[0];
  cur=nxt[1];draw();toTop();
}}
function bindActions(){{
  const mv=document.getElementById('mv');
  if(mv)mv.onclick=async()=>{{
    if(isDone(D[cur])){{nextTodo();return;}}
    if(await setViewed(D[cur].id,true))nextTodo();}};
  const un=document.getElementById('unmv');
  if(un)un.onclick=()=>setViewed(D[cur].id,false);
}}
document.addEventListener('keydown',e=>{{
  if(e.metaKey||e.ctrlKey||e.altKey)return;
  const k=e.key.toLowerCase();
  if(k==='v'){{e.preventDefault();
    if(isDone(D[cur])){{setViewed(D[cur].id,false);}}
    else{{setViewed(D[cur].id,true).then(ok=>{{if(ok)nextTodo();}});}}}}
  else if(k==='j'){{e.preventDefault();step(1);}}
  else if(k==='k'){{e.preventDefault();step(-1);}}
}});
// Unmark through the server rather than clearing a local set GitHub still
// disagrees with.
document.getElementById('reset').onclick=async()=>{{
  const btn=document.getElementById('reset');
  btn.disabled=true;
  // Unmarking a pair's new path already unmarked its old path, so skip
  // entries an earlier iteration cleared.
  for(const id of [...viewed]){{if(viewed.has(id))await setViewed(id,false);}}
  btn.disabled=false;}};
ix.addEventListener('click',e=>{{const b=e.target.closest('.item');if(!b)return;cur=+b.dataset.i;draw();toTop();}});
document.querySelectorAll('.flt').forEach(b=>b.onclick=()=>{{
  flt=b.dataset.f;
  document.querySelectorAll('.flt').forEach(o=>o.setAttribute('aria-pressed',o===b));
  const v=view();
  if(!v.some(([,i])=>i===cur)&&v.length)cur=v[0][1];
  draw();}});
loadViewed();
</script>"""

out = OUT / "hidden-renames.html"
out.write_text(HTML)
print("wrote", out, f"{out.stat().st_size/1024:.0f} KB")
