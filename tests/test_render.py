import hashlib
from config import Config, GlossaryTables, Pairing
from render2 import pr_url


def cfg(pr=252):
    return Config(base="main", head="HEAD", pr=pr,
                  pairing=Pairing(), glossary=GlossaryTables())


def test_pr_url_points_at_the_file_in_the_github_diff():
    url = pr_url(cfg(), "haeger", "hsp", "src/Foo.java")
    digest = hashlib.sha256(b"src/Foo.java").hexdigest()
    assert url == f"https://github.com/haeger/hsp/pull/252/files#diff-{digest}"


def test_pr_url_can_target_a_line_on_the_new_side():
    assert pr_url(cfg(), "haeger", "hsp", "src/Foo.java", 12).endswith("R12")


def test_pr_url_without_a_pr_number_returns_none():
    """A broken link is worse than no link."""
    assert pr_url(cfg(pr=None), "haeger", "hsp", "src/Foo.java") is None


def test_pr_url_without_a_resolved_repo_returns_none():
    assert pr_url(cfg(), None, None, "src/Foo.java") is None
