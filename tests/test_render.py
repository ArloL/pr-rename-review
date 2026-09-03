import hashlib
import pytest
from github import pr_url
from pagebuild import build_html, pair


def test_pr_url_points_at_the_file_in_the_github_diff():
    url = pr_url("haeger", "hsp", 252, "src/Foo.java")
    digest = hashlib.sha256(b"src/Foo.java").hexdigest()
    assert url == f"https://github.com/haeger/hsp/pull/252/files#diff-{digest}"


def test_pr_url_can_target_a_line_on_the_new_side():
    assert pr_url("haeger", "hsp", 252, "src/Foo.java", 12).endswith("R12")


def test_pr_url_without_a_pr_number_returns_none():
    """A broken link is worse than no link."""
    assert pr_url("haeger", "hsp", None, "src/Foo.java") is None


def test_pr_url_without_a_resolved_repo_returns_none():
    assert pr_url(None, None, 252, "src/Foo.java") is None


def test_appending_a_line_to_the_file_url_gives_the_line_url():
    """The page builds line links in JavaScript as `${f.gh}R${n}` rather than
    carrying 1,489 precomputed URLs in the payload. That only works while the
    file URL ends with the anchor, which this pins down."""
    file_url = pr_url("haeger", "hsp", 252, "src/Foo.java")
    line_url = pr_url("haeger", "hsp", 252, "src/Foo.java", 12)
    assert f"{file_url}R12" == line_url


def test_page_has_no_deep_links_without_a_resolved_pr(tmp_path):
    """Nothing currently asserts on the `gh` field either way: a change that
    broke deep links entirely, or one that leaked ambient PR env vars into
    the page, would both pass silently otherwise."""
    html = build_html(tmp_path, [pair()])
    assert '"gh":null' in html
    assert "github.com" not in html


def test_page_has_deep_links_when_the_pr_is_resolved(tmp_path):
    html = build_html(tmp_path, [pair()],
                        PR="252", PR_OWNER="haeger", PR_REPO="hsp")
    digest = hashlib.sha256(b"src/new/Foo.java").hexdigest()
    assert (f'"gh":"https://github.com/haeger/hsp/pull/252/files'
            f'#diff-{digest}"') in html


def test_page_carries_the_old_path_of_eachpair(tmp_path):
    """One tick must reach both of GitHub's entries for a sub-threshold
    rename, so the payload has to carry the deleted old path -- the display
    fields hold only its basename and package."""
    html = build_html(tmp_path, [pair()])
    assert '"oid":"src/old/Foo.java"' in html


def test_page_posts_a_path_list(tmp_path):
    html = build_html(tmp_path, [pair()])
    assert "JSON.stringify({paths" in html


def onesided(kind):
    """An added or deleted file: one path, repeated on both sides."""
    return pair(kind=kind, old="src/new/Foo.java", oldname="Foo.java",
                oldpkg="src/new", sim=None)


@pytest.mark.parametrize("kind", ["added", "deleted"])
def test_page_does_not_count_a_one_sided_file_as_a_hiddenpair(tmp_path, kind):
    """`split` used to be whatever was left after the other kinds were
    subtracted, so a kind the arithmetic did not know about inflated the
    count of pairs GitHub hides. Counting each kind directly is what keeps a
    future kind from landing in the wrong bucket."""
    html = build_html(tmp_path, [onesided(kind)])
    assert 'data-f="hidden" aria-pressed="false">Hidden 0<' in html


def test_page_names_the_one_sided_files_in_the_summary(tmp_path):
    html = build_html(tmp_path, [onesided("added"), onesided("deleted")])
    assert "the 1 the PR <b>adds</b> and the 1 it <b>deletes</b>" in html


def test_page_summary_omits_a_clause_with_nothing_to_describe(tmp_path):
    """A rename branch usually deletes nothing git cannot pair. Printing
    "0 files the PR deletes" on every build teaches the eye to skip the
    paragraph that explains what the page is showing."""
    html = build_html(tmp_path, [onesided("added")])
    assert "deletes" not in html
    assert "the 1 the PR <b>adds</b>" in html


def test_page_declares_its_own_encoding(tmp_path):
    """server.py sends `charset=utf-8`, but the page is also opened straight
    out of `build/` and served by other static servers. Without the meta tag
    the arrows and em dashes come out as mojibake wherever the header is
    absent, which is a broken-looking page for a reason nothing on it
    explains."""
    html = build_html(tmp_path, [pair()])
    assert html.startswith('<meta charset="utf-8">')


def test_page_has_no_glossary_ui(tmp_path):
    """The page is a plain word-level diff: no mode toggle in the bar, no
    frozen-German legend entry. The glossary was removed as noise."""
    html = build_html(tmp_path, [pair()])
    assert "Glossary cancelled" not in html
    assert "frozen German" not in html
    assert "Raw rename" not in html


def test_page_names_the_undo_key_in_the_shortcut_hint(tmp_path):
    """V ticks and moves on, so a mispress is only recoverable if you know
    the key that takes it back. An undo nobody is told about is one nobody
    reaches for."""
    html = build_html(tmp_path, [pair()])
    assert "U undoes the last tick" in html


def test_page_offers_an_undo_control_disabled_until_there_is_something_to_undo(tmp_path):
    html = build_html(tmp_path, [pair()])
    assert '<button class="linkbtn" id="undo" disabled>undo</button>' in html
