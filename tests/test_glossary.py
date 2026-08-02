import pytest
from config import GlossaryTables
from glossary import GlossaryError, build_glossary


def test_longest_source_wins():
    """Without longest-first ordering, `Ausschreibung` fires inside
    `AusschreibungDuplikat` and produces `TenderDuplikat`."""
    g = build_glossary(GlossaryTables(
        classes={"AusschreibungDuplikat": "TenderDuplicate"},
        words={"Ausschreibung": "Tender"}))
    assert g.normalize("AusschreibungDuplikat") == "TenderDuplicate"


def test_equal_length_keys_keep_table_precedence():
    """The sort is stable and classes are emitted first, so a class entry
    beats a word entry of the same key length."""
    g = build_glossary(GlossaryTables(
        classes={"Quelle": "SourceRef"}, words={"Quelle": "Source"}))
    assert g.normalize("Quelle") == "SourceRef"


def test_lower_camel_variant_is_derived():
    g = build_glossary(GlossaryTables(words={"Ausschreibung": "Tender"}))
    assert g.normalize("ausschreibung") == "tender"


def test_upper_variant_is_derived_for_words_and_columns():
    g = build_glossary(GlossaryTables(
        words={"Quelle": "Source"}, columns={"ausschreibung_id": "tender_id"}))
    assert g.normalize("QUELLE") == "SOURCE"
    assert g.normalize("AUSSCHREIBUNG_ID") == "TENDER_ID"


def test_classes_get_no_upper_variant():
    """Only words and columns are cased up. A SCREAMING class name is not a
    thing, and inventing the rule would widen what the glossary rewrites."""
    g = build_glossary(GlossaryTables(classes={"KundenMemory": "ClientMemory"}))
    assert g.normalize("KUNDENMEMORY") == "KUNDENMEMORY"


def test_compound_identifiers_map_component_wise():
    """`AusschreibungPersistenceTest` is in no table, but its first component
    is, and that is mechanical rather than a naming decision."""
    g = build_glossary(GlossaryTables(words={"Ausschreibung": "Tender"}))
    assert g.normalize("AusschreibungPersistenceTest") == "TenderPersistenceTest"
    assert g.normalize("duplikatRepository") == "duplikatRepository"


def test_component_pass_preserves_case_of_each_part():
    g = build_glossary(GlossaryTables(words={"Ausschreibung": "Tender"}))
    assert g.normalize("hauptAusschreibungId") == "hauptTenderId"


def test_parts_table_fires_only_inside_compounds():
    """A component-only entry rewrites `hauptAusschreibungId` but leaves a
    bare `haupt` in prose alone."""
    g = build_glossary(GlossaryTables(
        words={"Ausschreibung": "Tender"}, parts={"haupt": "Main"}))
    assert g.normalize("hauptAusschreibungId") == "mainTenderId"
    assert g.normalize("haupt") == "haupt"


def test_words_and_classes_outrank_the_parts_seed():
    g = build_glossary(GlossaryTables(
        words={"Haupt": "Primary"}, parts={"haupt": "Main"}))
    assert g.normalize("hauptSacheId") == "primarySacheId"


def test_single_component_identifiers_are_left_alone():
    """The component pass requires >= 2 parts, so a bare word only changes if
    a whole-word rule matched it earlier."""
    g = build_glossary(GlossaryTables(words={"Daten": "Data"}))
    assert g.normalize("unrelated") == "unrelated"


def test_whole_word_rules_do_not_fire_on_substrings():
    g = build_glossary(GlossaryTables(columns={"quelle": "source"}))
    assert g.normalize("quellex quelle") == "quellex source"


def test_snake_case_components_are_mapped():
    """`quelle_x` is not a whole-word match -- `_` is a word character -- but
    it is two components, so the component pass rewrites the first."""
    g = build_glossary(GlossaryTables(columns={"quelle": "source"}))
    assert g.normalize("quelle_x") == "source_x"


def test_columns_seed_parts_only_when_simple():
    """A column key with `_` or `.` is not a single identifier component, so
    it must not enter the component table."""
    g = build_glossary(GlossaryTables(
        columns={"start_datum": "start_date", "titel": "title"}))
    assert g.normalize("titelFeld") == "titleFeld"
    assert g.normalize("startDatumFeld") == "startDatumFeld"


def test_regex_patterns_run_before_the_word_tables():
    g = build_glossary(GlossaryTables(
        words={"Tender": "Ausschreibung"}, patterns=[(r"\bfoo\b", "Tender")]))
    assert g.normalize("foo") == "Ausschreibung"


def test_non_idempotent_glossary_is_rejected():
    """A rule whose output an earlier rule would have rewritten breaks
    phantom detection: frozen German stops being recognised and reappears as
    residual noise, which reads as a review problem rather than a config bug."""
    with pytest.raises(GlossaryError, match="idempotent"):
        build_glossary(GlossaryTables(words={"Beta": "Alpha", "Alpha": "Gamma"}))


def test_idempotent_glossary_is_accepted():
    build_glossary(GlossaryTables(words={"Ausschreibung": "Tender"}))


def test_the_shipped_config_is_idempotent():
    """Load-time assertion over the real PR #252 vocabulary."""
    import pathlib
    from config import load_config
    cfg = load_config(pathlib.Path(__file__).resolve().parent.parent
                      / ".pr-rename-review.toml")
    build_glossary(cfg.glossary)
