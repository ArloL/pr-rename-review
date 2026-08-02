"""The rename glossary, taken from
docs/superpowers/specs/2026-07-31-german-to-english-rename-design.md.

Nothing here is invented to make a file look clean: every entry is either a
row of that document's Glossary / Java renames / Database renames tables, or
the lowerCamel and snake_case variants of such a row.
"""
import re

# --- "Java renames" tables, verbatim ------------------------------------
CLASSES = {
    "AusschreibungDuplikatRepository": "TenderDuplicateRepository",
    "AusschreibungDuplikateService": "TenderDuplicateService",
    "AusschreibungDuplikatId": "TenderDuplicateId",
    "AusschreibungDuplikat": "TenderDuplicate",
    "AusschreibungQueryRepository": "TenderQueryRepository",
    "AusschreibungRepository": "TenderRepository",
    "AusschreibungQuery": "TenderQuery",
    "AusschreibungServiceImpl": "TenderServiceImpl",
    "AusschreibungService": "TenderService",
    "AusschreibungFacetCounts": "TenderFacetCounts",
    "AusschreibungNotFoundException": "TenderNotFoundException",
    "DuplikatGruppe": "DuplicateGroup",
    "DuplikatUebersicht": "DuplicateOverview",
    "KundenMemoriesRepository": "ClientMemoriesRepository",
    "KundenMemory": "ClientMemory",
    "BearbeiterFilter": "AssigneeFilter",
    "UnbekannterBearbeiterException": "UnknownAssigneeException",
    "ArchivierungScheduler": "ArchivingScheduler",
    "AusschreibungErstelltEvent": "TenderCreatedEvent",
    "AusschreibungExtrahiertEvent": "TenderExtractedEvent",
    "AusschreibungKlassifiziertEvent": "TenderClassifiedEvent",
    "AusschreibungKlassifikationKorrigiertEvent": "TenderClassificationCorrectedEvent",
    "AusschreibungKundeAktualisiertEvent": "TenderClientUpdatedEvent",
    "AusschreibungAgentConfiguration": "TenderAgentConfiguration",
    "AusschreibungAnalysierenAgent": "AnalyzeTenderAgent",
    "AusschreibungAnalysierenService": "TenderAnalysisService",
    "AusschreibungVerarbeitenAgent": "ProcessTenderAgent",
    "AusschreibungDaten": "TenderData",
    "ProjektdatenExtrahierenAgent": "ExtractProjectDataAgent",
    "SkillsExtrahierenAgent": "ExtractSkillsAgent",
    "VermittlerdatenExtrahierenAgent": "ExtractContactDataAgent",
    "DatenExtrahierenAgent": "ExtractDataAgent",
    "DuplikateErkennenService": "DuplicateDetectionService",
    "KundenBestGuessAgent": "ClientBestGuessAgent",
    "KundenBestGuessService": "ClientBestGuessService",
    "KundenMemoryAgent": "ClientMemoryAgent",
    "KundenMemoryLearningService": "ClientMemoryLearningService",
    "LookupKundenMemoryTool": "LookupClientMemoryTool",
    "AusschreibungAuslesenAgent": "ReadTenderAgent",
    "FreelancermapAuslesenAgent": "ReadFreelancermapTendersAgent",
    "AusschreibungMail": "TenderMail",
    "EmailKategorisierenAgent": "CategorizeEmailAgent",
    "EmailKategorisierung": "EmailCategorization",
    "LinkBesuchenAgent": "VisitLinkAgent",
    "ZusammenfassungErstellenAgent": "CreateSummaryAgent",
    "MoveMailToBearbeitetAgent": "MoveMailToProcessedAgent",
    "BestGuessErgebnis": "BestGuessResult",
}

# --- the "Glossary" table, as PascalCase / camelCase pairs ---------------
WORDS = {
    "Ausschreibungen": "Tenders", "Ausschreibung": "Tender",
    "Vermittlerdaten": "ContactData", "VermittlerDaten": "ContactData",
    "Vermittler": "Contact",
    "Projektdaten": "ProjectData", "ProjektDaten": "ProjectData",
    "Kunden": "Client", "Kunde": "Client",
    "BearbeitungsStatus": "ProcessingStatus", "Bearbeiter": "Assignee",
    "Klassifikation": "Classification",
    "Duplikate": "Duplicates", "Duplikat": "Duplicate",
    "Hauptausschreibung": "MainTender", "HauptAusschreibung": "MainTender",
    "Quelle": "Source", "Branche": "Industry",
    "Auslastung": "UtilizationRate", "Wochenstunden": "UtilizationRate",
    "RemoteAnteil": "RemoteRatio",
    # `ort` alone is only ever a DB column, so it lives in COLUMNS; adding a
    # PascalCase `Ort` here would rewrite German prompt prose and invent diffs
    "Einsatzort": "Location",
    "Veroeffentlichungsdatum": "PublicationDate",
    "Zusammenfassung": "Summary", "Titel": "Title",
    "Lektion": "Lesson", "Zuordnungsregel": "MatchingRule",
    "Begruendung": "Reason", "Grund": "Reason",
    "Erstellt": "Created", "Extrahiert": "Extracted", "Klassifiziert": "Classified",
    "ErstelltAm": "CreatedAt", "ArchiviertAm": "ArchivedAt",
    "Archivierung": "Archiving", "Archiviert": "Archived",
    "Daten": "Data", "Skills": "Skills",
}

# --- the "Database renames" section, verbatim ---------------------------
COLUMNS = {
    "ausschreibung_duplikat": "tender_duplicate",
    "ausschreibung_embeddings": "tender_embeddings",
    "ausschreibung_skill": "tender_skill",
    "ausschreibung_id": "tender_id", "ausschreibung": "tender",
    "vermittler": "contact", "kunden_memory": "client_memory",
    "titel": "title", "zusammenfassung": "summary",
    "start_datum": "start_date", "end_datum": "end_date",
    "wochenstunden": "utilization_rate", "ort": "location",
    "klassifikations_grund": "classification_reason",
    "klassifikation": "classification",
    "remote_anteil": "remote_ratio",
    "veroeffentlichungsdatum": "publication_date",
    "kunden_begruendung": "client_reason", "kunde": "client",
    "branche": "industry",
    "bearbeitungs_status": "processing_status",
    "bearbeitungs_begruendung": "processing_reason",
    "bearbeiter_identity_id": "assignee_identity_id",
    "quelle_urspruengliche_klassifikation": "source_original_classification",
    "quelle_neue_klassifikation": "source_new_classification",
    "quelle_ausschreibung_id": "source_tender_id",
    "quelle_benutzer_grund": "source_user_reason",
    "quelle": "source",
    "vermutete_kunden_begruendung": "suspected_client_reason",
    "vermuteter_kunde": "suspected_client",
    "erstellt_am": "created_at", "aktiv_seit": "active_since",
    "archiviert_am": "archived_at", "archiviert_von": "archived_by",
    "archiviert": "archived", "such_vektor": "search_vector",
    "duplikat_id": "duplicate_id",
    "vorname": "first_name", "nachname": "last_name",
    "telefonnummer": "phone_number", "firma": "company",
    "email_adresse": "email_address",
    "lektion": "lesson", "zuordnungsregel": "matching_rule",
    "duplikat.threshold": "duplicate.threshold",
    "archivierung.cron": "archiving-schedule.cron",
}


def _lower1(s):
    return s[0].lower() + s[1:]


def _build():
    rules = []
    for k, v in CLASSES.items():
        rules.append((k, v))
        rules.append((_lower1(k), _lower1(v)))
    for k, v in WORDS.items():
        rules.append((k, v))
        rules.append((_lower1(k), _lower1(v)))
        rules.append((k.upper(), v.upper()))
    for k, v in COLUMNS.items():
        rules.append((k, v))
        rules.append((k.upper(), v.upper()))
    # longest source first, so TenderDuplicateRepository wins over Tender
    rules.sort(key=lambda kv: -len(kv[0]))
    return [(re.compile(r"\b" + re.escape(k) + r"\b"), v) for k, v in rules]


RULES = _build()

# --- component-level pass ------------------------------------------------
# The tables above only fire on whole words, so a compound the design doc
# never spells out (`AusschreibungPersistenceTest`, `duplikatRepository`)
# survives and reads as a decision when it is really the same mechanical
# substitution one level down. Split identifiers on camel/snake boundaries
# and map each part through the same glossary — no new vocabulary, only the
# existing entries applied inside compounds.
PARTS = {
    # the doc's `Hauptausschreibung → mainTender` row, decomposed so it also
    # fires in `hauptAusschreibungId` and friends
    "haupt": "Main",
}
for _k, _v in list(WORDS.items()) + [(a, b) for a, b in CLASSES.items()]:
    PARTS[_k.lower()] = _v
for _k, _v in COLUMNS.items():
    if "_" not in _k and "." not in _k:
        PARTS.setdefault(_k.lower(), _v[0].upper() + _v[1:])

IDENT = re.compile(r"[A-Za-z0-9_]+")
CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+|_+")


def _recase(part, repl):
    if part.isupper() and len(part) > 1:
        return repl.upper()
    if part[:1].islower():
        return repl[0].lower() + repl[1:]
    return repl


def _map_ident(m):
    tok = m.group(0)
    parts = CAMEL.findall(tok)
    if len(parts) < 2:
        return tok
    out, hit = [], False
    for p in parts:
        r = PARTS.get(p.lower())
        if r and p != "_":
            out.append(_recase(p, r)); hit = True
        else:
            out.append(p)
    return "".join(out) if hit else tok


def normalize(text):
    for pat, repl in RULES:
        text = pat.sub(repl, text)
    return IDENT.sub(_map_ident, text)
