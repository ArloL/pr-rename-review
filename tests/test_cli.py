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
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        class P:
            returncode = 1 if len(calls) == 1 else 0
            stdout, stderr = "", "boom"
        return P()

    monkeypatch.setattr("cli.subprocess.run", fake_run)
    code = main(["--out", str(tmp_path), "build"])
    assert code == 1
    assert len(calls) == 1, "later passes ran after a failure"


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
