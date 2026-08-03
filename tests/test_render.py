import hashlib, json, os, pathlib, subprocess, sys
from config import Config
from github import pr_url

ROOT = pathlib.Path(__file__).resolve().parent.parent


def cfg(pr=252):
    return Config(base="main", head="HEAD", pr=pr)


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


def test_appending_a_line_to_the_file_url_gives_the_line_url():
    """The page builds line links in JavaScript as `${f.gh}R${n}` rather than
    carrying 1,489 precomputed URLs in the payload. That only works while the
    file URL ends with the anchor, which this pins down."""
    file_url = pr_url(cfg(), "haeger", "hsp", "src/Foo.java")
    line_url = pr_url(cfg(), "haeger", "hsp", "src/Foo.java", 12)
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


def _build_page(tmp_path, files):
    out = tmp_path / "build"
    out.mkdir()
    (out / "diffdata2.json").write_text(json.dumps({"files": files}))
    (out / "refs.json").write_text(json.dumps(
        {"base": "a" * 40, "head": "b" * 40,
         "base_ref": "main", "head_ref": "topic"}))
    # REPO points at a directory that is not a checkout, so the deep links
    # are deterministically absent instead of resolving whatever repository
    # the test happens to run inside.
    env = {**os.environ, "OUT": str(out), "REPO": str(tmp_path)}
    subprocess.run([sys.executable, str(ROOT / "render2.py")], env=env,
                   cwd=ROOT, check=True, capture_output=True, text=True)
    return (out / "hidden-renames.html").read_text()


def test_page_carries_the_old_path_of_each_pair(tmp_path):
    """One tick must reach both of GitHub's entries for a sub-threshold
    rename, so the payload has to carry the deleted old path -- the display
    fields hold only its basename and package."""
    html = _build_page(tmp_path, [_pair()])
    assert '"oid":"src/old/Foo.java"' in html


def test_page_posts_a_path_list(tmp_path):
    html = _build_page(tmp_path, [_pair()])
    assert "JSON.stringify({paths" in html


def test_page_has_no_glossary_ui(tmp_path):
    """The page is a plain word-level diff: no mode toggle in the bar, no
    frozen-German legend entry. The glossary was removed as noise."""
    html = _build_page(tmp_path, [_pair()])
    assert "Glossary cancelled" not in html
    assert "frozen German" not in html
    assert "Raw rename" not in html
