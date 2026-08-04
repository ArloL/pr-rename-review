import hashlib, json, os, pathlib, subprocess, sys
import pytest
from github import pr_url

ROOT = pathlib.Path(__file__).resolve().parent.parent


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


def _pair(**kw):
    base = dict(old="src/old/Foo.java", new="src/new/Foo.java",
                oldname="Foo.java", newname="Foo.java",
                oldpkg="src/old", newpkg="src/new",
                sim=34, kind="split", gh_target=None, gh_score=None,
                area="main", prev=False, raw=[],
                raw_c=0, raw_w=3, lines=10)
    base.update(kw)
    return base


def _build_page(tmp_path, files, **env_overrides):
    out = tmp_path / "build"
    out.mkdir()
    (out / "diffdata2.json").write_text(json.dumps({"files": files}))
    (out / "refs.json").write_text(json.dumps(
        {"base": "a" * 40, "head": "b" * 40,
         "base_ref": "main", "head_ref": "topic"}))
    # render2.py reads PR/PR_OWNER/PR_REPO straight from the environment now,
    # with no `gh` call to redirect -- so they are stripped from the
    # forwarded environment here rather than merely left unset, guaranteeing
    # deep links stay absent even if the shell running pytest happens to have
    # them set. Tests that want deep links opt back in via env_overrides.
    env = {k: v for k, v in os.environ.items()
           if k not in ("PR", "PR_OWNER", "PR_REPO")}
    env["OUT"] = str(out)
    env.update(env_overrides)
    subprocess.run([sys.executable, str(ROOT / "render2.py")], env=env,
                   cwd=ROOT, check=True, capture_output=True, text=True)
    return (out / "hidden-renames.html").read_text()


def test_page_has_no_deep_links_without_a_resolved_pr(tmp_path):
    """Nothing currently asserts on the `gh` field either way: a change that
    broke deep links entirely, or one that leaked ambient PR env vars into
    the page, would both pass silently otherwise."""
    html = _build_page(tmp_path, [_pair()])
    assert '"gh":null' in html
    assert "github.com" not in html


def test_page_has_deep_links_when_the_pr_is_resolved(tmp_path):
    html = _build_page(tmp_path, [_pair()],
                        PR="252", PR_OWNER="haeger", PR_REPO="hsp")
    digest = hashlib.sha256(b"src/new/Foo.java").hexdigest()
    assert (f'"gh":"https://github.com/haeger/hsp/pull/252/files'
            f'#diff-{digest}"') in html


def test_page_carries_the_old_path_of_each_pair(tmp_path):
    """One tick must reach both of GitHub's entries for a sub-threshold
    rename, so the payload has to carry the deleted old path -- the display
    fields hold only its basename and package."""
    html = _build_page(tmp_path, [_pair()])
    assert '"oid":"src/old/Foo.java"' in html


def test_page_posts_a_path_list(tmp_path):
    html = _build_page(tmp_path, [_pair()])
    assert "JSON.stringify({paths" in html


def _onesided(kind):
    """An added or deleted file: one path, repeated on both sides."""
    return _pair(kind=kind, old="src/new/Foo.java", oldname="Foo.java",
                 oldpkg="src/new", sim=None)


@pytest.mark.parametrize("kind", ["added", "deleted"])
def test_page_does_not_count_a_one_sided_file_as_a_hidden_pair(tmp_path, kind):
    """`split` used to be whatever was left after the other kinds were
    subtracted, so a kind the arithmetic did not know about inflated the
    count of pairs GitHub hides. Counting each kind directly is what keeps a
    future kind from landing in the wrong bucket."""
    html = _build_page(tmp_path, [_onesided(kind)])
    assert 'data-f="hidden" aria-pressed="false">Hidden 0<' in html


def test_page_names_the_one_sided_files_in_the_summary(tmp_path):
    html = _build_page(tmp_path, [_onesided("added"), _onesided("deleted")])
    assert "the 1 the PR <b>adds</b> and the 1 it <b>deletes</b>" in html


def test_page_summary_omits_a_clause_with_nothing_to_describe(tmp_path):
    """A rename branch usually deletes nothing git cannot pair. Printing
    "0 files the PR deletes" on every build teaches the eye to skip the
    paragraph that explains what the page is showing."""
    html = _build_page(tmp_path, [_onesided("added")])
    assert "deletes" not in html
    assert "the 1 the PR <b>adds</b>" in html


def test_page_declares_its_own_encoding(tmp_path):
    """server.py sends `charset=utf-8`, but the page is also opened straight
    out of `build/` and served by other static servers. Without the meta tag
    the arrows and em dashes come out as mojibake wherever the header is
    absent, which is a broken-looking page for a reason nothing on it
    explains."""
    html = _build_page(tmp_path, [_pair()])
    assert html.startswith('<meta charset="utf-8">')


def test_page_has_no_glossary_ui(tmp_path):
    """The page is a plain word-level diff: no mode toggle in the bar, no
    frozen-German legend entry. The glossary was removed as noise."""
    html = _build_page(tmp_path, [_pair()])
    assert "Glossary cancelled" not in html
    assert "frozen German" not in html
    assert "Raw rename" not in html
