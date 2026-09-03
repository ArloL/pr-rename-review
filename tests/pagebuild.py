"""Building the review page from a hand-made payload.

Shared by the tests that read the built HTML and the ones that run its
JavaScript, so both drive the real render2.py rather than a fixture that
can drift away from it.
"""
import json, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def pair(**kw):
    base = dict(old="src/old/Foo.java", new="src/new/Foo.java",
                oldname="Foo.java", newname="Foo.java",
                oldpkg="src/old", newpkg="src/new",
                sim=34, kind="split", gh_target=None, gh_score=None,
                area="main", prev=False, raw=[],
                raw_c=0, raw_w=3, lines=10)
    base.update(kw)
    return base


def build_page(tmp_path, files, **env_overrides):
    out = tmp_path / "build"
    out.mkdir(exist_ok=True)
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
    return out / "hidden-renames.html"


def build_html(tmp_path, files, **env_overrides):
    return build_page(tmp_path, files, **env_overrides).read_text()
