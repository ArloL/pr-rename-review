import os, pathlib, subprocess
import pytest
from cli import ALL_PASSES, main


def test_no_subcommand_prints_usage_and_fails(capsys):
    assert main([]) == 2
    assert "build" in capsys.readouterr().err


def test_unknown_subcommand_fails():
    with pytest.raises(SystemExit):
        main(["frobnicate"])


def _pull(spec=None, cwd=None):
    """Stand-in for resolve_pr. Real specs (a number, a #number or a URL) all
    go to `gh` verbatim without being parsed here -- so a non-numeric spec,
    like the URL form, falls back to the same PR rather than being int()'d."""
    from github import PullRequest
    number = int(spec) if spec and str(spec).isdigit() else 259
    return PullRequest("haeger", "hsp", number, "main")


@pytest.fixture
def no_network(monkeypatch):
    """Nothing in this file may reach GitHub or a git remote."""
    monkeypatch.setattr("cli.resolve_pr", _pull)
    monkeypatch.setattr("cli.remote_for", lambda *a, **k: ("origin", True))
    monkeypatch.setattr("cli.fetch_pull",
                        lambda *a, **k: ("BASEREF", "HEADREF", []))
    for name in ("PR", "PR_OWNER", "PR_REPO", "BASE", "HEAD_REF"):
        monkeypatch.delenv(name, raising=False)


def test_the_pr_argument_reaches_the_passes(no_network, monkeypatch):
    seen = {}
    monkeypatch.setattr("cli.run_passes",
                        lambda passes, env: seen.update(env) or 0)
    assert main(["build", "259"]) == 0
    assert (seen["PR"], seen["PR_OWNER"], seen["PR_REPO"]) == (
        "259", "haeger", "hsp")
    assert (seen["BASE"], seen["HEAD_REF"]) == ("BASEREF", "HEADREF")


def test_without_a_pr_argument_the_current_branch_is_asked(no_network,
                                                           monkeypatch):
    seen = {}
    monkeypatch.setattr("cli.resolve_pr",
                        lambda spec, cwd=None: seen.update(spec=spec) or
                        _pull())
    monkeypatch.setattr("cli.run_passes", lambda passes, env: 0)
    assert main(["build"]) == 0
    assert seen["spec"] is None, "a spec was invented for the bare form"


def test_the_pr_argument_works_on_every_subcommand(no_network, monkeypatch,
                                                    tmp_path):
    """Asserting only the return code would pass even if the spec were
    dropped on the floor and the bare-branch PR resolved instead -- so this
    checks the spec actually reaches resolve_pr, on all three subcommands."""
    seen = []
    monkeypatch.setattr("cli.resolve_pr",
                        lambda spec, cwd=None: seen.append(spec) or _pull(spec))
    monkeypatch.setattr("cli.run_passes", lambda passes, env: 0)
    monkeypatch.setattr("server.serve", lambda page, gh, **kw: None)
    monkeypatch.setattr("cli._github", lambda pull, cwd=None: object())
    (tmp_path / "hidden-renames.html").write_text("<h1>page</h1>")

    assert main(["pairs", "259"]) == 0
    assert main(["build", "https://github.com/haeger/hsp/pull/259"]) == 0
    assert main(["--out", str(tmp_path), "--no-browser", "serve", "42"]) == 0

    assert seen == ["259", "https://github.com/haeger/hsp/pull/259", "42"]


def test_flags_parse_after_the_subcommand_too(no_network, monkeypatch,
                                               tmp_path):
    """--repo/--base/--head/--out/--no-build/--no-browser used to live only
    on the top-level parser, so `pr` being a positional on each subparser
    meant a flag typed after the subcommand -- as README:21-23's examples
    invite -- raised SystemExit 2 instead of being recognized."""
    (tmp_path / "hidden-renames.html").write_text("<h1>page</h1>")
    monkeypatch.setattr("cli.run_passes", lambda p, e: 0)
    monkeypatch.setattr("server.serve", lambda page, gh, **kw: None)
    monkeypatch.setattr("cli._github", lambda pull, cwd=None: object())
    assert main(["serve", "259", "--out", str(tmp_path), "--no-browser"]) == 0

    seen = {}
    monkeypatch.setattr("cli.run_passes",
                        lambda passes, env: seen.update(env) or 0)
    assert main(["build", "259", "--out", str(tmp_path)]) == 0
    assert seen["OUT"] == str(tmp_path)


def test_base_and_head_skip_github_entirely(monkeypatch):
    """The offline path, and the one tests/conftest.py drives the pinned
    replay baseline through."""
    def boom(*a, **k):
        raise AssertionError("gh was consulted despite --base/--head")

    monkeypatch.setattr("cli.resolve_pr", boom)
    monkeypatch.setattr("cli.fetch_refs", lambda repo, base, head: None)
    for name in ("PR_OWNER", "PR_REPO"):
        monkeypatch.delenv(name, raising=False)
    # A stray PR left over from some earlier ambient shell must not leak
    # through: this is what _env's pop-before-set is actually guarding.
    monkeypatch.setenv("PR", "999")
    seen = {}
    monkeypatch.setattr("cli.run_passes", lambda p, env: seen.update(env) or 0)
    assert main(["--base", "abc", "--head", "def", "build"]) == 0
    assert (seen["BASE"], seen["HEAD_REF"]) == ("abc", "def")
    assert "PR" not in seen, "an offline build claimed to know the PR"


def test_only_one_of_base_and_head_is_an_error(monkeypatch, capsys):
    # $HEAD_REF in the ambient environment would satisfy the pair and make
    # this pass for the wrong reason.
    monkeypatch.delenv("HEAD_REF", raising=False)
    monkeypatch.setattr("cli.run_passes", lambda p, env: 0)
    assert main(["--base", "abc", "build"]) == 1
    assert "together" in capsys.readouterr().err


def test_no_pr_for_the_branch_fails_with_a_usable_message(monkeypatch, capsys):
    from github import GitHubError

    def no_pr(spec, cwd=None):
        raise GitHubError("no pull requests found; name one instead, e.g. "
                          "`pr-rename-review serve 259`")

    monkeypatch.setattr("cli.resolve_pr", no_pr)
    monkeypatch.setattr("cli.run_passes", lambda p, env: 0)
    assert main(["build"]) == 1
    assert "serve 259" in capsys.readouterr().err


def test_a_fetch_that_cannot_fall_back_fails_the_build(monkeypatch, capsys):
    from refs import RefError
    monkeypatch.setattr("cli.resolve_pr", _pull)
    monkeypatch.setattr("cli.remote_for", lambda *a, **k: ("origin", True))

    def never_fetched(*a, **k):
        raise RefError("git fetch origin failed (offline), and pull request "
                       "#259 has never been fetched here")

    monkeypatch.setattr("cli.fetch_pull", never_fetched)
    monkeypatch.setattr("cli.run_passes", lambda p, env: 0)
    assert main(["build", "259"]) == 1
    assert "never been fetched" in capsys.readouterr().err


def test_pairs_runs_only_the_pairing_pass(no_network, monkeypatch):
    seen = {}
    monkeypatch.setattr("cli.run_passes",
                        lambda passes, env: seen.update(p=passes) or 0)
    assert main(["pairs"]) == 0
    assert seen["p"] == ["pairup.py"]


def test_build_runs_all_four_passes(no_network, monkeypatch):
    seen = {}
    monkeypatch.setattr("cli.run_passes",
                        lambda passes, env: seen.update(p=passes) or 0)
    main(["build"])
    assert seen["p"] == ALL_PASSES
    assert seen["p"] == ["pairup.py", "scope.py", "gen2.py", "render2.py"]


def test_serve_can_skip_the_build(no_network, monkeypatch, tmp_path):
    called, served = [], []
    (tmp_path / "hidden-renames.html").write_text("<h1>page</h1>")
    monkeypatch.setattr("cli.run_passes", lambda p, e: called.append(p) or 0)
    monkeypatch.setattr("server.serve",
                        lambda page, gh, **kw: served.append(page))
    monkeypatch.setattr("cli._github", lambda pull, cwd=None: object())
    assert main(["--out", str(tmp_path), "--no-build", "--no-browser",
                 "serve"]) == 0
    assert called == [], "serve --no-build must not run the passes"
    assert served and served[0].name == "hidden-renames.html"


def test_serve_no_build_skips_the_fetch_on_the_offline_path_too(
        no_network, monkeypatch, tmp_path):
    """The mirror of test_serve_no_build_still_resolves_the_pr, but for
    --base/--head: prepare() honoured need_refs on the PR path already, and
    not on this one, so `serve --no-build --base X --head Y` paid for a fetch
    (up to 60s per remote) that was explicitly told not to rebuild."""
    fetched = []
    (tmp_path / "hidden-renames.html").write_text("<h1>page</h1>")
    monkeypatch.setattr("cli.fetch_refs",
                        lambda *a, **k: fetched.append(a) or None)
    monkeypatch.setattr("server.serve", lambda page, gh, **kw: None)
    monkeypatch.setattr("cli._github", lambda pull, cwd=None: object())
    assert main(["--out", str(tmp_path), "--no-build", "--no-browser",
                 "--base", "abc", "--head", "def", "serve"]) == 0
    assert fetched == [], "--no-build fetched anyway"


def test_serve_no_build_still_resolves_the_pr(no_network, monkeypatch,
                                              tmp_path):
    """Viewed ticks sync even when the page is not rebuilt, so the PR still
    has to be known -- but nothing is fetched."""
    fetched = []
    (tmp_path / "hidden-renames.html").write_text("<h1>page</h1>")
    monkeypatch.setattr("cli.fetch_pull",
                        lambda *a, **k: fetched.append(a) or ("B", "H", []))
    monkeypatch.setattr("server.serve", lambda page, gh, **kw: None)
    seen = {}
    monkeypatch.setattr("cli._github",
                        lambda pull, cwd=None: seen.update(pr=pull.number))
    main(["--out", str(tmp_path), "--no-build", "--no-browser", "serve"])
    assert seen["pr"] == 259
    assert fetched == [], "--no-build fetched anyway"


def test_serve_rebuilds_by_default(no_network, monkeypatch, tmp_path):
    """No staleness heuristic: a stale page that looks current is the exact
    failure this tool exists to prevent."""
    called, served = [], []
    (tmp_path / "hidden-renames.html").write_text("<h1>page</h1>")
    monkeypatch.setattr("cli.run_passes", lambda p, e: called.append(p) or 0)
    monkeypatch.setattr("server.serve",
                        lambda page, gh, **kw: served.append(page))
    monkeypatch.setattr("cli._github", lambda pull, cwd=None: object())
    main(["--out", str(tmp_path), "--no-browser", "serve"])
    assert called == [ALL_PASSES]


def test_serve_without_a_page_fails_clearly(no_network, monkeypatch, tmp_path,
                                            capsys):
    monkeypatch.setattr("cli.run_passes", lambda p, e: 0)
    assert main(["--out", str(tmp_path), "--no-build", "serve"]) == 1
    assert "does not exist" in capsys.readouterr().err


def test_pairup_without_refs_says_how_to_run_it(tmp_path):
    """pairup.py is runnable on its own -- conftest.py drives it directly --
    so it has to say what it needs rather than resolve None."""
    import os, subprocess, sys
    from cli import ROOT
    env = {k: v for k, v in os.environ.items()
           if k not in ("BASE", "HEAD_REF")}
    proc = subprocess.run([sys.executable, str(ROOT / "pairup.py")],
                          env={**env, "OUT": str(tmp_path)}, cwd=ROOT,
                          capture_output=True, text=True)
    assert proc.returncode != 0
    assert "BASE and HEAD_REF" in proc.stderr


def test_a_failing_pass_stops_the_run(no_network, monkeypatch, tmp_path):
    """A pass that fails must not let later passes run against its stale
    output -- that is how a truncated file becomes a wrong answer."""
    # Only the pass invocations are counted: cli.subprocess.run also carries
    # repo_root's `git rev-parse --show-toplevel`, and counting that as the
    # first call would let the first pass succeed and pass this test for the
    # wrong reason.
    passes = []

    def fake_run(cmd, **kw):
        is_pass = any(str(part).endswith(".py") for part in cmd)
        if is_pass:
            passes.append(cmd)
        class P:
            returncode = 1 if is_pass and len(passes) == 1 else 0
            stdout, stderr = "", "boom"
        return P()

    monkeypatch.setattr("cli.subprocess.run", fake_run)
    code = main(["--out", str(tmp_path), "build"])
    assert code == 1
    assert len(passes) == 1, "later passes ran after a failure"


# _github is the only wiring between the resolved PR and the viewed-state
# feature, and every serve test above monkeypatches it away -- so neither
# branch is otherwise exercised. GitHub.__init__ makes no `gh` call, so
# testing the real construction here still touches no network.
def test_github_is_offline_when_no_pull_request_is_known():
    from cli import _github
    from github import GitHubError

    gh = _github(None)
    with pytest.raises(GitHubError, match="base/--head"):
        gh.viewed_states()
    with pytest.raises(GitHubError, match="base/--head"):
        gh.set_viewed("a.java", True)


def test_github_wires_the_resolved_pull_to_a_real_client():
    from cli import _github
    from github import GitHub, PullRequest

    pull = PullRequest("haeger", "hsp", 259, "main")
    gh = _github(pull, cwd="/some/checkout")
    assert isinstance(gh, GitHub)
    assert (gh.owner, gh.repo, gh.pr) == ("haeger", "hsp", 259)


def test_a_remote_falling_back_to_origin_is_reported(monkeypatch, capsys):
    """refs.py:128-129 -- in a fork checkout with no upstream remote, the
    origin fallback can point refs/pull/<N>/head at a different repository's
    PR #<N>. Silent, that is the one scenario where the tool is confidently
    wrong rather than loudly wrong."""
    monkeypatch.setattr("cli.resolve_pr", _pull)
    monkeypatch.setattr("cli.remote_for", lambda *a, **k: ("origin", False))
    monkeypatch.setattr("cli.fetch_pull",
                        lambda *a, **k: ("BASEREF", "HEADREF", []))
    monkeypatch.setattr("cli.run_passes", lambda p, env: 0)
    assert main(["build", "259"]) == 0
    err = capsys.readouterr().err
    assert "no remote points at haeger/hsp" in err
    assert "origin" in err


def test_a_remote_that_matched_is_not_reported(no_network, monkeypatch,
                                                capsys):
    monkeypatch.setattr("cli.run_passes", lambda p, env: 0)
    assert main(["build", "259"]) == 0
    assert "no remote points at" not in capsys.readouterr().err


# --- running the tool from the repository under review -------------------
#
# `uvx --from git+https://github.com/ArloL/pr-rename-review pr-rename-review
# serve 259`, typed inside the checkout the PR lives in, has to work with
# neither --repo nor $REPO. There the tool is unpacked into a uv cache
# directory: cli.ROOT is no checkout at all, so nothing about where this file
# lives can name the repository or a place to write.


def _checkout(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet"], cwd=path, check=True)
    return path.resolve()


@pytest.fixture
def standing_in(tmp_path, monkeypatch):
    """A real checkout, entered, with $REPO and $OUT out of the way so the
    defaults are what these tests actually exercise."""
    repo = _checkout(tmp_path / "target")
    for name in ("REPO", "OUT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(repo)
    return repo


@pytest.fixture
def built(monkeypatch):
    """Capture the environment the passes would have been run with."""
    seen = {}
    monkeypatch.setattr("cli.run_passes",
                        lambda passes, env: seen.update(env) or 0)
    return seen


def _same(a, b):
    # Absoluteness is asserted, not assumed: `Path("").resolve()` is the
    # current directory, so an empty $REPO -- what the passes used to be
    # handed -- would compare equal to the checkout the test is standing in
    # and prove nothing.
    assert a and pathlib.Path(a).is_absolute(), f"not an absolute path: {a!r}"
    return pathlib.Path(a).resolve() == pathlib.Path(b).resolve()


def test_the_checkout_you_are_standing_in_is_reviewed(no_network, built,
                                                       standing_in):
    """The feature: no --repo, no $REPO, and the PR of the repo you are in."""
    assert main(["build", "259"]) == 0
    assert _same(built["REPO"], standing_in)


def test_a_subdirectory_resolves_to_the_top_level(no_network, built,
                                                   standing_in, monkeypatch):
    """`git show <ref>:<path>` reads root-relative paths wherever it runs, so
    a run from src/main/java has to review the whole checkout, not fail on
    every path in it."""
    deeper = standing_in / "src" / "main" / "java"
    deeper.mkdir(parents=True)
    monkeypatch.chdir(deeper)
    assert main(["build", "259"]) == 0
    assert _same(built["REPO"], standing_in)


def test_a_directory_that_is_no_checkout_is_passed_through(no_network, built,
                                                            tmp_path,
                                                            monkeypatch):
    """Not this tool's directory, and not empty: git then fails naming the
    path the user actually chose."""
    from cli import ROOT
    for name in ("REPO", "OUT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["build", "259"]) == 0
    assert _same(built["REPO"], tmp_path)
    assert not _same(built["REPO"], ROOT)


def test_repo_still_wins_over_where_you_stand(no_network, built, standing_in,
                                              tmp_path):
    elsewhere = _checkout(tmp_path / "elsewhere")
    assert main(["build", "259", "--repo", str(elsewhere)]) == 0
    assert _same(built["REPO"], elsewhere)


def test_the_repo_env_var_still_wins_over_where_you_stand(no_network, built,
                                                           standing_in,
                                                           tmp_path,
                                                           monkeypatch):
    elsewhere = _checkout(tmp_path / "elsewhere")
    monkeypatch.setenv("REPO", str(elsewhere))
    assert main(["build", "259"]) == 0
    assert _same(built["REPO"], elsewhere)


def test_gh_is_asked_inside_the_resolved_checkout(built, standing_in,
                                                   monkeypatch):
    """`gh` resolves the repository from its working directory. Left to
    default, it would answer for whatever repo the tool itself sits in -- the
    wrong PR, resolved without a word."""
    seen = {}
    monkeypatch.setattr("cli.resolve_pr",
                        lambda spec, cwd=None: seen.update(cwd=cwd) or _pull())
    monkeypatch.setattr("cli.remote_for", lambda *a, **k: ("origin", True))
    monkeypatch.setattr("cli.fetch_pull", lambda *a, **k: ("B", "H", []))
    assert main(["build"]) == 0
    assert seen["cwd"] and _same(seen["cwd"], standing_in)


def test_out_defaults_beside_the_passes_when_run_from_this_checkout(
        no_network, built, standing_in, monkeypatch, tmp_path):
    """`uv run` in this repository keeps writing ./build, as before."""
    monkeypatch.setattr("cli.ROOT", tmp_path / "tool")
    monkeypatch.setattr("cli.FROM_SOURCE", True)
    assert main(["build", "259"]) == 0
    assert _same(built["OUT"], tmp_path / "tool" / "build")


def test_an_installed_run_writes_neither_into_the_repo_nor_into_the_install(
        no_network, built, standing_in, monkeypatch, tmp_path):
    """An installed copy lives in a cache uv may discard, and `build/` inside
    the repository under review is Gradle's. So it goes to the user's cache
    directory instead, and the page's path is printed."""
    monkeypatch.setattr("cli.ROOT", tmp_path / "install")
    monkeypatch.setattr("cli.FROM_SOURCE", False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert main(["build", "259"]) == 0
    out = pathlib.Path(built["OUT"])
    assert out.is_relative_to(tmp_path / "cache" / "pr-rename-review")
    assert not out.is_relative_to(standing_in)
    assert not out.is_relative_to(tmp_path / "install")


def test_an_installed_run_keys_the_output_by_checkout(monkeypatch, tmp_path):
    """Two repositories reviewed from one install must not overwrite each
    other's page -- and same-named checkouts in different places are two
    repositories, not one."""
    import cli
    monkeypatch.setattr("cli.FROM_SOURCE", False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    a = cli.out_dir(None, "/home/u/one/hsp")
    b = cli.out_dir(None, "/home/u/two/hsp")
    assert a != b
    assert cli.out_dir(None, "/home/u/one/hsp") == a, "not stable across runs"


def test_out_still_wins_over_every_default(no_network, built, standing_in,
                                            monkeypatch, tmp_path):
    monkeypatch.setattr("cli.FROM_SOURCE", False)
    assert main(["build", "259", "--out", str(tmp_path / "here")]) == 0
    assert _same(built["OUT"], tmp_path / "here")
    monkeypatch.setenv("OUT", str(tmp_path / "env"))
    assert main(["build", "259"]) == 0
    assert _same(built["OUT"], tmp_path / "env")
