import pytest
from config import Pairing
from pairup import PairingError, check_collisions, expected_path


def test_path_rules_apply_to_directories_only():
    p = Pairing(path_rules=[("/ausschreibung", "/tender")])
    assert expected_path("src/de/ausschreibung/Foo.java", p) == \
        "src/de/tender/Foo.java"


def test_path_rules_do_not_touch_the_basename():
    """The basename is handled by basenames/words. A path rule that also hit
    the filename would apply lowercase package vocabulary to a class name."""
    p = Pairing(path_rules=[("/ausschreibung", "/tender")])
    assert expected_path("a/b/ausschreibung.java", p) == "a/b/ausschreibung.java"


def test_basename_override_beats_word_substitution():
    """A semantic rename is not word-for-word, so the override wins outright
    rather than being applied on top of the word list."""
    p = Pairing(basenames={"Auslastung.java": "UtilizationRate.java"},
                words=[("Auslastung", "Workload")])
    assert expected_path("a/Auslastung.java", p) == "a/UtilizationRate.java"


def test_words_apply_in_file_order():
    p = Pairing(words=[("Ausschreibungen", "Tenders"),
                       ("Ausschreibung", "Tender")])
    assert expected_path("a/AusschreibungenRepo.java", p) == "a/TendersRepo.java"


def test_reversed_word_order_would_break_the_plural():
    """Documents why order is significant, so nobody sorts the table."""
    p = Pairing(words=[("Ausschreibung", "Tender"),
                       ("Ausschreibungen", "Tenders")])
    assert expected_path("a/AusschreibungenRepo.java", p) == "a/TenderenRepo.java"


def test_dir_segments_apply_only_inside_their_scope():
    p = Pairing(dir_scope="/evals/", dir_segments={"Projekt": "ProjectData"})
    assert expected_path("t/evals/Projekt/a.json", p) == \
        "t/evals/ProjectData/a.json"
    assert expected_path("src/Projekt/a.json", p) == "src/Projekt/a.json"


def test_dir_segments_match_whole_segments_only():
    p = Pairing(dir_scope="/evals/", dir_segments={"Projekt": "ProjectData"})
    assert expected_path("t/evals/ProjektAlt/a.json", p) == \
        "t/evals/ProjektAlt/a.json"


def test_dir_segments_with_no_scope_apply_everywhere():
    p = Pairing(dir_segments={"Projekt": "ProjectData"})
    assert expected_path("src/Projekt/a.json", p) == "src/ProjectData/a.json"


def test_file_with_no_directory():
    p = Pairing(words=[("Ausschreibung", "Tender")])
    assert expected_path("Ausschreibung.java", p) == "Tender.java"


def test_empty_pairing_is_the_identity():
    assert expected_path("a/b/Foo.java", Pairing()) == "a/b/Foo.java"


def test_collisions_are_an_error():
    with pytest.raises(PairingError, match="new/Tender.java"):
        check_collisions({"a/Alt.java": "new/Tender.java",
                          "b/Alt.java": "new/Tender.java"})


def test_collision_message_names_both_sources():
    with pytest.raises(PairingError) as exc:
        check_collisions({"a/Alt.java": "x.java", "b/Alt.java": "x.java"})
    assert "a/Alt.java" in str(exc.value) and "b/Alt.java" in str(exc.value)


def test_no_collisions_passes():
    check_collisions({"a.java": "b.java", "c.java": "d.java"})
