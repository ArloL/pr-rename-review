import pytest
from cli import ALL_PASSES, main


def test_no_subcommand_prints_usage_and_fails(capsys):
    assert main([]) == 2
    assert "build" in capsys.readouterr().err


def test_unknown_subcommand_fails():
    with pytest.raises(SystemExit):
        main(["frobnicate"])


def test_build_accepts_ref_overrides(monkeypatch):
    seen = {}
    monkeypatch.setattr("cli.run_passes",
                        lambda passes, env: seen.update(env) or 0)
    assert main(["--base", "abc", "--head", "def", "build"]) == 0
    assert seen["BASE"] == "abc"
    assert seen["HEAD_REF"] == "def"


def test_refs_default_to_config(monkeypatch):
    """Config values reach the passes. Asserted against the config rather than
    against literal refs: [repo] names moving refs now, and a test that pins
    them would fail every time the tool is aimed at a different PR."""
    from config import load_config
    from cli import ROOT
    cfg = load_config(ROOT / ".pr-rename-review.toml")
    seen = {}
    monkeypatch.setattr("cli.run_passes",
                        lambda passes, env: seen.update(env) or 0)
    main(["build"])
    assert seen["BASE"] == cfg.base
    assert seen["HEAD_REF"] == cfg.head


def test_pairs_runs_only_the_pairing_pass(monkeypatch):
    seen = {}
    monkeypatch.setattr("cli.run_passes",
                        lambda passes, env: seen.update(p=passes) or 0)
    assert main(["pairs"]) == 0
    assert seen["p"] == ["pairup.py"]


def test_build_runs_all_four_passes(monkeypatch):
    seen = {}
    monkeypatch.setattr("cli.run_passes",
                        lambda passes, env: seen.update(p=passes) or 0)
    main(["build"])
    assert seen["p"] == ALL_PASSES
    assert seen["p"] == ["pairup.py", "scope.py", "gen2.py", "render2.py"]


def test_serve_can_skip_the_build(monkeypatch, tmp_path):
    called, served = [], []
    (tmp_path / "hidden-renames.html").write_text("<h1>page</h1>")
    monkeypatch.setattr("cli.run_passes", lambda p, e: called.append(p) or 0)
    monkeypatch.setattr("server.serve",
                        lambda page, gh, **kw: served.append(page))
    monkeypatch.setattr("cli._github", lambda cfg, cwd=None: object())
    assert main(["--out", str(tmp_path), "--no-build", "--no-browser",
                 "serve"]) == 0
    assert called == [], "serve --no-build must not run the passes"
    assert served and served[0].name == "hidden-renames.html"


def test_serve_rebuilds_by_default(monkeypatch, tmp_path):
    """No staleness heuristic: a stale page that looks current is the exact
    failure this tool exists to prevent."""
    called, served = [], []
    (tmp_path / "hidden-renames.html").write_text("<h1>page</h1>")
    monkeypatch.setattr("cli.run_passes", lambda p, e: called.append(p) or 0)
    monkeypatch.setattr("server.serve",
                        lambda page, gh, **kw: served.append(page))
    monkeypatch.setattr("cli._github", lambda cfg, cwd=None: object())
    main(["--out", str(tmp_path), "--no-browser", "serve"])
    assert called == [ALL_PASSES]


def test_serve_without_a_page_fails_clearly(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("cli.run_passes", lambda p, e: 0)
    assert main(["--out", str(tmp_path), "--no-build", "serve"]) == 1
    assert "does not exist" in capsys.readouterr().err


def test_a_failing_pass_stops_the_run(monkeypatch, tmp_path):
    """A pass that fails must not let later passes run against its stale
    output -- that is how a truncated file becomes a wrong answer."""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        class P:
            returncode = 1 if len(calls) == 1 else 0
            stdout, stderr = "", "boom"
        return P()

    # The fetch would otherwise be the first subprocess call and absorb the
    # simulated failure; this test is about the passes.
    monkeypatch.setattr("cli.fetch_refs", lambda env: None)
    monkeypatch.setattr("cli.subprocess.run", fake_run)
    code = main(["--out", str(tmp_path), "build"])
    assert code == 1
    assert len(calls) == 1, "later passes ran after a failure"
