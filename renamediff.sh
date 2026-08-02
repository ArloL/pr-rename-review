#!/usr/bin/env bash
# Word-diff a rename pair with the glossary cancelled out, so only genuine
# changes light up instead of every renamed token.
#   renamediff.sh <old-ref:path> <new-path> [--stat]
set -uo pipefail
OLD_REF=${OLD_REF:-origin/main}
NEW_REF=${NEW_REF:-HEAD}

normalize() {
  sed -E '
    s/\bAusschreibungDuplikatId\b/TenderDuplicateId/g
    s/\bAusschreibungDuplikat\b/TenderDuplicate/g
    s/\bDuplikatGruppe\b/DuplicateGroup/g
    s/\bDuplikatUebersicht\b/DuplicateOverview/g
    s/\bVermittlerdaten\b/ContactData/g; s/\bVermittlerDaten\b/ContactData/g
    s/\bvermittlerdaten\b/contactData/g
    s/\bProjektdaten\b/ProjectData/g; s/\bprojektdaten\b/projectData/g
    s/\bAusschreibungen\b/Tenders/g; s/\bausschreibungen\b/tenders/g
    s/\bAusschreibung\b/Tender/g;    s/\bausschreibung\b/tender/g
    s/\bAUSSCHREIBUNG\b/TENDER/g
    s/\bVermittler\b/Contact/g;      s/\bvermittler\b/contact/g
    s/\bKunden\b/Client/g;           s/\bkunden\b/client/g
    s/\bKunde\b/Client/g;            s/\bkunde\b/client/g
    s/\bBearbeitungsStatus\b/ProcessingStatus/g; s/\bbearbeitungsStatus\b/processingStatus/g
    s/\bbearbeitungs_status\b/processing_status/g
    s/\bBearbeiter\b/Assignee/g;     s/\bbearbeiter\b/assignee/g
    s/\bKlassifikation\b/Classification/g; s/\bklassifikation\b/classification/g
    s/\bklassifizieren\b/classify/g
    s/\bDuplikate\b/Duplicates/g;    s/\bduplikate\b/duplicates/g
    s/\bDuplikat\b/Duplicate/g;      s/\bduplikat\b/duplicate/g
    s/\bQuelle\b/Source/g;           s/\bquelle\b/source/g
    s/\bBranche\b/Industry/g;        s/\bbranche\b/industry/g
    s/\bAuslastung\b/UtilizationRate/g; s/\bauslastung\b/utilizationRate/g
    s/\bwochenstunden\b/utilizationRate/g
    s/\bRemoteAnteil\b/RemoteRatio/g; s/\bremoteAnteil\b/remoteRatio/g
    s/\bEinsatzort\b/Location/g;     s/\beinsatzort\b/location/g
    s/\bLektion\b/Lesson/g;          s/\blektion\b/lesson/g
    s/\bZuordnungsregel\b/MatchingRule/g; s/\bzuordnungsregel\b/matchingRule/g
    s/\bHauptausschreibung\b/mainTender/g; s/\bhauptAusschreibung\b/mainTender/g
    s/\bBegruendung\b/Reason/g;      s/\bbegruendung\b/reason/g
    s/\bGrund\b/Reason/g;            s/\bgrund\b/reason/g
    s/\bTitel\b/Title/g;             s/\btitel\b/title/g
    s/\bZusammenfassung\b/Summary/g; s/\bzusammenfassung\b/summary/g
    s/\berstellt\b/created/g;        s/\bErstellt\b/Created/g
    s/\bneue\b/new/g; s/\bneuer\b/new/g; s/\balte\b/old/g; s/\balten\b/old/g
    s/\bhaegerconsulting\.hsp\.tender/haegerconsulting.hsp.tender/g
  '
}
old=$1; new=$2; shift 2
git show "$OLD_REF:$old" | normalize > /tmp/.rd-old.$$
git show "$NEW_REF:$new"              > /tmp/.rd-new.$$
git --no-pager diff --no-index "$@" \
    --word-diff=color --word-diff-regex='[A-Za-z0-9_]+|[^[:space:]]' \
    /tmp/.rd-old.$$ /tmp/.rd-new.$$
rc=$?
rm -f /tmp/.rd-old.$$ /tmp/.rd-new.$$
exit $rc
