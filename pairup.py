#!/usr/bin/env python3
"""Derive the canonical old->new pairing by name, independent of git's
content-similarity guess, then report where git disagrees."""
import re, sys, os, pathlib, subprocess

SP = os.path.dirname(os.path.abspath(__file__))
OUT = pathlib.Path(os.environ.get("OUT") or (pathlib.Path(__file__).parent / "build"))
OUT.mkdir(parents=True, exist_ok=True)

REPO = os.environ.get("REPO") or subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
BASE = os.environ.get("BASE", "main")
HEAD = os.environ.get("HEAD_REF", "HEAD")


def tree(ref):
    return set(subprocess.run(["git", "ls-tree", "-r", "--name-only", ref],
                              capture_output=True, text=True, cwd=REPO).stdout.split())


head = tree(HEAD)
main = tree(BASE)

# non-mechanical basename renames (semantic, not word-for-word)
OVERRIDE = {
    "AusschreibungAnalysierenService.java": "TenderAnalysisService.java",
    "AusschreibungAnalysierenAgent.java": "AnalyzeTenderAgent.java",
    "AusschreibungVerarbeitenAgent.java": "ProcessTenderAgent.java",
    "DuplikateErkennenService.java": "DuplicateDetectionService.java",
    "KundenBestGuessService.java": "ClientBestGuessService.java",
    "KundenMemoryLearningService.java": "ClientMemoryLearningService.java",
    "AusschreibungDaten.java": "TenderData.java",
    "AusschreibungErstelltEvent.java": "TenderCreatedEvent.java",
    "AusschreibungKlassifiziertEvent.java": "TenderClassifiedEvent.java",
    "AusschreibungExtrahiertEvent.java": "TenderExtractedEvent.java",
    "AusschreibungKlassifikationKorrigiertEvent.java": "TenderClassificationCorrectedEvent.java",
    "AusschreibungKundeAktualisiertEvent.java": "TenderClientUpdatedEvent.java",
    "Auslastung.java": "UtilizationRate.java",
    "RemoteAnteil.java": "RemoteRatio.java",
    "Einsatzort.java": "Location.java",
    "Branche.java": "Industry.java",
    "Quelle.java": "Source.java",
    "Klassifikation.java": "Classification.java",
    "Vermittler.java": "Contact.java",
    "Kunde.java": "Client.java",
    "EmailKategorisierung.java": "EmailCategorization.java",
    "MoveMailToBearbeitetAgent.java": "MoveMailToProcessedAgent.java",
    "UnbekannterBearbeiterException.java": "UnknownAssigneeException.java",
    "DuplikatUebersicht.java": "DuplicateOverview.java",
    "DuplikatGruppe.java": "DuplicateGroup.java",
    "BestGuessErgebnis.java": "BestGuessResult.java",
    "Lektion.java": "Lesson.java",
    "Zuordnungsregel.java": "MatchingRule.java",
}
WORDS = [
    ("AusschreibungDuplikatId", "TenderDuplicateId"),
    ("AusschreibungDuplikate", "TenderDuplicate"),
    ("AusschreibungDuplikat", "TenderDuplicate"),
    ("Ausschreibungen", "Tenders"), ("Ausschreibung", "Tender"),
    ("Duplikate", "Duplicate"), ("Duplikat", "Duplicate"),
    ("Kunden", "Client"), ("Kunde", "Client"),
    ("Vermittler", "Contact"),
    ("BearbeitungsStatus", "ProcessingStatus"),
    ("Bearbeiter", "Assignee"),
    ("Klassifikation", "Classification"),
]
# eval fixture directories were renamed too, and not word-for-word
DIRS = {
    "Projekt": "ProjectData", "Vermittler": "ContactData",
    "AusschreibungAuslesen": "ReadTender", "EmailKategorisieren": "CategorizeEmail",
    "BeschreibungExtrahieren": "ExtractDescription",
    "ProjektdatenExtrahieren": "ExtractProjectData",
    "Ausschreibung": "Tender",
}


def expect(old):
    d, b = os.path.split(old)
    d = d.replace("/ausschreibung", "/tender")
    if "/evals/" in d:
        d = "/".join(DIRS.get(seg, seg) for seg in d.split("/"))
    if b in OVERRIDE:
        b = OVERRIDE[b]
    else:
        for a, z in WORDS:
            b = b.replace(a, z)
    return f"{d}/{b}" if d else b


# git's own low-threshold opinion
git_pair, adds, dels = {}, [], []
for ln in subprocess.run(
    ["git", "diff", "-M01%", "-l50000", "--name-status", f"{BASE}...{HEAD}"],
    capture_output=True, text=True, cwd=REPO).stdout.splitlines():
    f = ln.split("\t")
    if f[0].startswith("R"):
        git_pair[f[1]] = (f[2], int(f[0][1:]))
    elif f[0] == "A":
        adds.append(f[1])
    elif f[0] == "D":
        dels.append(f[1])

# every old file that moved, per git (renamed or deleted)
moved_old = list(git_pair) + dels
canon, unresolved = {}, []
for o in moved_old:
    n = expect(o)
    if n in head:
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
    print(f"   {o}\n      guessed {guess} (absent)   git says {git_pair.get(o, ('-',))[0]}")
print(f"genuinely new files : {len(new_only)}")
for a in new_only:
    print(f"   {a}")
dupes = [v for v in used if list(canon.values()).count(v) > 1]
print(f"collisions          : {sorted(set(dupes))}")

print("\n=== git disagrees with the canonical pairing ===")
n_dis = 0
for o, n in sorted(canon.items()):
    g = git_pair.get(o)
    if g is None:
        print(f"  git UNPAIRED  {o}\n             -> {n}")
        n_dis += 1
    elif g[0] != n:
        print(f"  git MISPAIRED {o}\n     git  {g[0]}  ({g[1]}%)\n     true {n}")
        n_dis += 1
print(f"total disagreements: {n_dis}")

with open(OUT / "canonical-pairs.tsv", "w") as fh:
    for o, n in sorted(canon.items()):
        g = git_pair.get(o)
        fh.write(f"{o}\t{n}\t{g[1] if g and g[0]==n else ''}\t{'ok' if g and g[0]==n else ('unpaired' if g is None else 'mispaired')}\n")
print(f"\nwrote {OUT}/canonical-pairs.tsv")
