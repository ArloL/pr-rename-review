import json, os, pathlib, subprocess
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "golden"

# The golden fixtures were captured at this commit. HEAD_REF must be pinned:
# `origin/refactor/german-to-english-rename` is a moving ref, and a fetch that
# advances it silently changes every number the replay asserts.
BASELINE_BASE = "52efff3"
BASELINE_HEAD = "1ce7bfa"


@pytest.fixture(scope="session")
def repo_env():
    """Environment for a replay against the pinned PR #252 baseline."""
    repo = os.environ.get("REPO")
    if not repo:
        pytest.skip("set REPO to the checkout PR #252 lives in")
    for ref in (BASELINE_BASE, BASELINE_HEAD):
        probe = subprocess.run(["git", "cat-file", "-e", f"{ref}^{{commit}}"],
                               cwd=repo, capture_output=True)
        if probe.returncode:
            pytest.skip(f"{repo} does not contain the baseline commit {ref}")
    return {**os.environ, "REPO": repo,
            "BASE": BASELINE_BASE, "HEAD_REF": BASELINE_HEAD}


@pytest.fixture(scope="session")
def pipeline(tmp_path_factory, repo_env):
    """Run the three data passes once and return (payload, pair_report)."""
    out = tmp_path_factory.mktemp("build")
    env = {**repo_env, "OUT": str(out)}
    reports = {}
    for script in ("pairup.py", "scope.py", "gen2.py"):
        proc = subprocess.run(["python3", str(ROOT / script)], env=env,
                              cwd=ROOT, check=True, capture_output=True,
                              text=True)
        reports[script] = proc.stdout
    return json.loads((out / "diffdata2.json").read_text()), reports


@pytest.fixture(scope="session")
def rebuilt(pipeline):
    return pipeline[0]


@pytest.fixture(scope="session")
def pair_report(pipeline):
    return pipeline[1]["pairup.py"]
