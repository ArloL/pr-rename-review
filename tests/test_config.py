import textwrap
import pytest
from config import ConfigError, load_config


def write(tmp_path, body):
    p = tmp_path / ".pr-rename-review.toml"
    p.write_text(textwrap.dedent(body))
    return p


def test_loads_repo_section(tmp_path):
    cfg = load_config(write(tmp_path, """
        [repo]
        base = "main"
        head = "origin/branch"
        pr = 252
    """))
    assert (cfg.base, cfg.head, cfg.pr) == ("main", "origin/branch", 252)


def test_pr_is_optional(tmp_path):
    cfg = load_config(write(tmp_path, """
        [repo]
        base = "main"
        head = "HEAD"
    """))
    assert cfg.pr is None


def test_pairing_words_keep_file_order(tmp_path):
    """Order is significant: the plural must be tried before the singular,
    because pairup applies these as a sequence of str.replace calls."""
    cfg = load_config(write(tmp_path, """
        [repo]
        base = "main"
        head = "HEAD"
        [pairing]
        words = [["Ausschreibungen", "Tenders"], ["Ausschreibung", "Tender"]]
    """))
    assert cfg.pairing.words == [
        ("Ausschreibungen", "Tenders"), ("Ausschreibung", "Tender")]


def test_dir_segments_carry_their_scope(tmp_path):
    cfg = load_config(write(tmp_path, """
        [repo]
        base = "main"
        head = "HEAD"
        [pairing.dir_segments]
        scope = "/evals/"
        segments = { Projekt = "ProjectData" }
    """))
    assert cfg.pairing.dir_scope == "/evals/"
    assert cfg.pairing.dir_segments == {"Projekt": "ProjectData"}


def test_missing_repo_section_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="repo"):
        load_config(write(tmp_path, "[pairing]\n"))


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.toml")


def test_malformed_pair_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="pairing.words"):
        load_config(write(tmp_path, """
            [repo]
            base = "main"
            head = "HEAD"
            [pairing]
            words = [["only-one-element"]]
        """))


def test_empty_defaults_are_usable(tmp_path):
    """A config with no vocabulary at all must load. Pairing then falls back
    entirely to git similarity, which is a legitimate way to run the tool."""
    cfg = load_config(write(tmp_path, """
        [repo]
        base = "main"
        head = "HEAD"
    """))
    assert cfg.pairing.words == []
    assert cfg.pairing.dir_scope is None


def test_the_real_config_loads():
    """The shipped config must parse and carry the rename vocabulary."""
    import pathlib
    cfg = load_config(pathlib.Path(__file__).resolve().parent.parent
                      / ".pr-rename-review.toml")
    assert cfg.pr == 259
    assert cfg.pairing.dir_scope == "/evals/"
