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
    monkeypatch.setattr("cli.remote_for", lambda *a, **k: "origin")
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


def test_the_pr_argument_works_on_every_subcommand(no_network, monkeypatch):
    monkeypatch.setattr("cli.run_passes", lambda passes, env: 0)
    assert main(["pairs", "259"]) == 0
    assert main(["build", "https://github.com/haeger/hsp/pull/259"]) == 0


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
    monkeypatch.setattr("cli.remote_for", lambda *a, **k: "origin")

    def never_fetched(*a, **k):
        raise RefError("git fetch origin failed (offline), and pull request "
                       "#259 has never been fetched here")

    monkeypatch.setattr("cli.fetch_pull", never_fetched)
    monkeypatch.setattr("cli.run_passes", lambda p, env: 0)
    assert main(["build", "259"]) == 1
    assert "never been fetched" in capsys.readouterr().err


def test_build_accepts_ref_overrides(monkeypatch):
    monkeypatch.setattr("cli.fetch_refs", lambda repo, base, head: None)
    for name in ("PR", "PR_OWNER", "PR_REPO"):
        monkeypatch.delenv(name, raising=False)
    seen = {}
    monkeypatch.setattr("cli.run_passes",
                        lambda passes, env: seen.update(env) or 0)
    assert main(["--base", "abc", "--head", "def", "build"]) == 0
    assert seen["BASE"] == "abc"
    assert seen["HEAD_REF"] == "def"


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
