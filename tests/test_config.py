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


def test_missing_repo_section_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="repo"):
        load_config(write(tmp_path, "[other]\n"))


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.toml")


def test_the_real_config_loads():
    """The shipped config must parse and name the PR under review."""
    import pathlib
    cfg = load_config(pathlib.Path(__file__).resolve().parent.parent
                      / ".pr-rename-review.toml")
    assert cfg.pr == 259
