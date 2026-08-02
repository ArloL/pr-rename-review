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
    seen = {}
    monkeypatch.setattr("cli.run_passes",
                        lambda passes, env: seen.update(env) or 0)
    main(["build"])
    assert seen["BASE"] == "52efff3"
    assert seen["HEAD_REF"] == "1ce7bfa"


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

    monkeypatch.setattr("cli.subprocess.run", fake_run)
    code = main(["--out", str(tmp_path), "build"])
    assert code == 1
    assert len(calls) == 1, "later passes ran after a failure"
