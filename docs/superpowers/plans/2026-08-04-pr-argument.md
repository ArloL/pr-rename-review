# Take a Pull Request, Not Two Configured Branches — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two hand-configured refs in `.pr-rename-review.toml` with a pull request named on the command line, deriving base and head from GitHub.

**Architecture:** `gh pr view` yields the PR's number, base branch and base repository. `git fetch` then pulls `refs/pull/N/head` and the base branch into a private ref namespace, and those two ref names feed the existing `refs.resolve` merge-base logic unchanged. `cli.py` resolves once per run and hands `PR`/`PR_OWNER`/`PR_REPO` down to the passes through the environment, beside the `BASE`/`HEAD_REF`/`REPO` variables they already read. `--base`/`--head` remain as the offline path that skips GitHub entirely.

**Tech Stack:** Python 3.11+ standard library only (`argparse`, `subprocess`, `dataclasses`, `re`, `json`), the `gh` CLI, git, pytest.

**Spec:** `docs/superpowers/specs/2026-08-04-pr-rename-review-pr-argument-spec.md`

## Global Constraints

- **Python 3.11+, standard library only.** The project has no runtime dependencies and must keep none. Dev dependency is `pytest>=8`.
- **The tool never holds a GitHub token.** `gh` holds the credential. `tests/test_github.py::test_no_token_ever_appears_in_a_command` enforces this.
- **Every `gh` and `git` call runs inside the checkout under review** (`cwd=REPO`), never inside this tool's own directory. `gh` resolves the repository from its working directory.
- **No test may touch the network.** Use `FakeRunner` for `gh`, and real git repositories built in `tmp_path` for git.
- **Never pass a pathspec to a rename-detecting diff.** Enforced by `tests/test_no_pathspec.py`. No task here touches diff invocation, but do not introduce one.
- **The passes stay scripts run in sequence**, communicating through the environment. Do not convert them to imported functions — see the module docstring in `cli.py`.
- **The replay baseline is `BASE=eb1b00665 HEAD_REF=47c9dc7`**, pinned in `tests/conftest.py`. It must keep working untouched, and every number in the README's Baseline section must still reproduce at the end.
- Comments explain *why*, not *what*. Match the density and voice of the surrounding code.
- Prefer CLI long options (`--message`, not `-m`) everywhere, including in commit commands.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `github.py` | All `gh` access. Gains `PullRequest` + `resolve_pr`; `pr_url` takes a number instead of a config. Loses `resolve_repo`/`resolve_target`. | Modify |
| `refs.py` | All git ref resolution and fetching. Gains `remote_for` + `fetch_pull` + `has_ref`. Keeps `fetch`/`remote_of` for the `--base`/`--head` path. | Modify |
| `cli.py` | Argument parsing and one-time resolution; hands results to the passes through the environment. | Modify |
| `render2.py` | Reads `PR`/`PR_OWNER`/`PR_REPO` from the environment instead of loading config and calling `gh` itself. | Modify |
| `pairup.py` | Requires `BASE`/`HEAD_REF` from the environment; no config fallback. | Modify |
| `config.py`, `.pr-rename-review.toml`, `tests/test_config.py` | — | **Delete** |
| `README.md`, `run.sh`, `pyproject.toml` | Documentation and packaging still name the config file. | Modify |

Task order keeps the suite green at every commit: new functions land first (Tasks 1–2), consumers switch over (Tasks 3–4), and only then is the old path deleted (Task 5).

---

### Task 1: `resolve_pr` in github.py

Resolve a PR spec to owner, repository, number and base branch. Nothing consumes it yet, so the suite stays green.

**Files:**
- Modify: `github.py:1-8` (imports), and append after `resolve_target`
- Test: `tests/test_github.py`

**Interfaces:**
- Consumes: `runner_for`, `GitHubError` (existing in `github.py`)
- Produces: `PullRequest(owner: str, repo: str, number: int, base_ref: str)` and `resolve_pr(spec=None, runner=None, cwd=None) -> PullRequest`. Task 3 calls `resolve_pr`; Tasks 3 and 4 read all four attributes.

- [ ] **Step 1: Write the failing tests**

First extend the import on line 3 to `from github import GitHub, GitHubError, anchor, resolve_pr, resolve_target`, then append these tests.

```python
PR_VIEW = json.dumps({"url": "https://github.com/haeger/hsp/pull/259",
                      "number": 259, "baseRefName": "main"})


def test_resolve_pr_reads_owner_repo_number_and_base():
    pull = resolve_pr(runner=FakeRunner(PR_VIEW))
    assert (pull.owner, pull.repo, pull.number, pull.base_ref) == (
        "haeger", "hsp", 259, "main")


def test_resolve_pr_without_a_spec_asks_about_the_current_branch():
    runner = FakeRunner(PR_VIEW)
    resolve_pr(runner=runner)
    assert runner.calls[0][:3] == ["gh", "pr", "view"]
    assert runner.calls[0][3] == "--json", "a spec was passed when none was given"


def test_resolve_pr_passes_a_number_through():
    runner = FakeRunner(PR_VIEW)
    resolve_pr("259", runner=runner)
    assert runner.calls[0][3] == "259"


def test_resolve_pr_strips_a_leading_hash():
    """`gh pr view '#259'` is rejected by gh; a user typing it should not be."""
    runner = FakeRunner(PR_VIEW)
    resolve_pr("#259", runner=runner)
    assert runner.calls[0][3] == "259"


def test_resolve_pr_passes_a_url_through():
    url = "https://github.com/haeger/hsp/pull/259"
    runner = FakeRunner(PR_VIEW)
    resolve_pr(url, runner=runner)
    assert runner.calls[0][3] == url


def test_resolve_pr_uses_the_base_repository_not_the_fork():
    """A pull request lives on the repository it targets. Asking the fork
    about #259 finds nothing, and every viewed tick would silently no-op --
    which is why headRepository* is the wrong field to read."""
    payload = json.dumps({"url": "https://github.com/haeger/hsp/pull/259",
                          "number": 259, "baseRefName": "main",
                          "headRepository": {"name": "hsp-fork"},
                          "headRepositoryOwner": {"login": "contributor"}})
    pull = resolve_pr(runner=FakeRunner(payload))
    assert (pull.owner, pull.repo) == ("haeger", "hsp")


def test_resolve_pr_without_a_pr_for_the_branch_names_the_fix():
    """The branch having no PR is the one failure a new user will hit."""
    runner = FakeRunner(GitHubError("no pull requests found for branch main"))
    with pytest.raises(GitHubError, match="pr-rename-review serve 259"):
        resolve_pr(runner=runner)


def test_resolve_pr_with_a_spec_reports_ghs_own_error_unchanged():
    """gh already says what is wrong with an explicit spec; do not bury it."""
    runner = FakeRunner(GitHubError("no pull request found for 999"))
    with pytest.raises(GitHubError, match="999"):
        resolve_pr("999", runner=runner)


def test_resolve_pr_without_gh_names_the_fix():
    with pytest.raises(GitHubError, match="gh auth login"):
        resolve_pr(runner=FakeRunner(FileNotFoundError("gh")))


def test_resolve_pr_with_unparseable_output_becomes_GitHubError():
    with pytest.raises(GitHubError, match="unexpected"):
        resolve_pr(runner=FakeRunner("not json"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_github.py --quiet`
Expected: FAIL — `ImportError: cannot import name 'resolve_pr' from 'github'`

- [ ] **Step 3: Implement `PullRequest` and `resolve_pr`**

In `github.py`, change the import line 8 from `import hashlib, json, subprocess` to:

```python
import hashlib, json, re, subprocess
from dataclasses import dataclass
```

Then append after `resolve_target`:

```python
PR_URL = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")


@dataclass
class PullRequest:
    """The pull request under review: who to ask about it, and where it forks
    from. `base_ref` is a branch name on the base repository, not a commit."""
    owner: str
    repo: str
    number: int
    base_ref: str


def resolve_pr(spec=None, runner=None, cwd=None):
    """The PR named by `spec`, or the one for the checked-out branch.

    `spec` goes to `gh` verbatim -- it already accepts a number, a URL or
    nothing -- less a leading `#`, which gh rejects and users type anyway.

    owner/repo come from the `url` field, which names the repository the PR
    *targets*. `headRepositoryOwner`/`headRepository` name the fork on a
    cross-repository PR, and the viewed-state query would then run against a
    repository that has no such pull request: every tick a silent no-op.
    """
    run = runner or runner_for(cwd)
    cmd = ["gh", "pr", "view"]
    if spec:
        cmd.append(str(spec).lstrip("#"))
    try:
        raw = run(cmd + ["--json", "url,number,baseRefName"])
    except FileNotFoundError as exc:
        raise GitHubError(
            "gh not found -- install it and run `gh auth login`") from exc
    except GitHubError as exc:
        if spec:
            raise
        raise GitHubError(f"{exc}; name the pull request instead, e.g. "
                          "`pr-rename-review serve 259`") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unexpected output from gh: {raw[:200]!r}") from exc
    match = PR_URL.search(data.get("url") or "")
    if not match:
        raise GitHubError(f"cannot read a pull request url from gh: "
                          f"{data.get('url')!r}")
    owner, repo, _ = match.groups()
    return PullRequest(owner, repo, int(data["number"]), data["baseRefName"])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_github.py --quiet`
Expected: PASS, and the pre-existing `github` tests still pass.

- [ ] **Step 5: Commit**

```bash
git add github.py tests/test_github.py
git commit --message "feat: resolve a pull request spec to its refs and base repo"
```

---

### Task 2: `remote_for` and `fetch_pull` in refs.py

Fetch the PR's own ref and its base branch into a private namespace. Still unconsumed, so the suite stays green.

**Files:**
- Modify: `refs.py` (append after `fetch`)
- Test: `tests/test_refs.py`

**Interfaces:**
- Consumes: `_git`, `RefError`, `FETCH_TIMEOUT`, `resolve` (existing in `refs.py`)
- Produces:
  - `remote_for(repo, owner, name) -> str` — remote name, raises `RefError` when there is no match and no `origin`
  - `has_ref(repo, ref) -> bool`
  - `fetch_pull(repo, remote, number, base_ref, timeout=FETCH_TIMEOUT) -> (base_ref_name, head_ref_name, warnings)` — two **ref names**, not commits, suitable for `resolve`. Raises `RefError` when the fetch fails and nothing is on disk.
  - `PULL_NS = "refs/pr-rename-review"`

Task 3 calls `remote_for` and `fetch_pull`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_refs.py`. The `git` helper and `resolve` import already exist at the top of that file; extend line 10's import to include the new names.

```python
@pytest.fixture
def pull_origin(tmp_path):
    """An origin carrying refs/pull/259/head, the way GitHub serves one.

    `git clone` copies refs/heads/* only, so the clone starts without the pull
    ref and without any branch for the PR -- exactly the state a fork's PR
    leaves you in.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "--initial-branch=main")
    git(origin, "config", "user.email", "t@example.com")
    git(origin, "config", "user.name", "T")
    (origin / "f.txt").write_text("one\n")
    git(origin, "add", "-A")
    git(origin, "commit", "--message", "one")
    fork = git(origin, "rev-parse", "HEAD")

    git(origin, "checkout", "-b", "pr-branch")
    (origin / "pr.txt").write_text("the PR's own work\n")
    git(origin, "add", "-A")
    git(origin, "commit", "--message", "PR work")
    head = git(origin, "rev-parse", "HEAD")
    git(origin, "update-ref", "refs/pull/259/head", head)

    git(origin, "checkout", "main")
    (origin / "unrelated.txt").write_text("not the PR's work\n")
    git(origin, "add", "-A")
    git(origin, "commit", "--message", "main moves on")

    work = tmp_path / "work"
    git(tmp_path, "clone", str(origin), str(work))
    # The clone must not already have the PR branch, or these tests prove
    # nothing about the pull ref.
    git(origin, "branch", "--delete", "--force", "pr-branch")
    return work, fork, head


def bare(tmp_path, name="repo"):
    r = tmp_path / name
    r.mkdir()
    git(r, "init", "--initial-branch=main")
    return r


def test_fetch_pull_brings_the_pr_ref_into_the_private_namespace(pull_origin):
    work, _, head = pull_origin
    base, head_ref, warnings = fetch_pull(work, "origin", 259, "main")
    assert warnings == []
    assert (base, head_ref) == ("refs/pr-rename-review/259/base",
                                "refs/pr-rename-review/259/head")
    assert git(work, "rev-parse", head_ref) == head


def test_fetch_pull_needs_no_branch_for_the_pr(pull_origin):
    """The whole point of refs/pull/N/head: a fork's branch is not a remote
    tracking branch here, and the review works anyway."""
    work, _, head = pull_origin
    probe = subprocess.run(["git", "rev-parse", "--verify", "--quiet",
                            "origin/pr-branch"], cwd=work, capture_output=True)
    assert probe.returncode != 0, "the fixture leaked a branch for the PR"
    _, head_ref, _ = fetch_pull(work, "origin", 259, "main")
    assert git(work, "rev-parse", head_ref) == head


def test_fetch_pull_feeds_resolve_and_yields_the_merge_base(pull_origin):
    """End to end: the two names go straight into resolve, and the base comes
    out as the fork point rather than main's tip."""
    work, fork, head = pull_origin
    base_ref, head_ref, _ = fetch_pull(work, "origin", 259, "main")
    assert resolve(work, base_ref, head_ref) == (fork, head)
    assert git(work, "rev-parse", base_ref) != fork, "main did not move on"


def test_fetch_pull_writes_no_remote_tracking_branch(pull_origin):
    """Private namespace: reviewing a PR must not move anything the user has
    their own opinions about."""
    work, _, _ = pull_origin
    before = git(work, "for-each-ref", "--format=%(refname)", "refs/remotes")
    fetch_pull(work, "origin", 259, "main")
    assert git(work, "for-each-ref", "--format=%(refname)",
               "refs/remotes") == before


def test_fetch_pull_is_repeatable(pull_origin):
    """Forced refspecs: a second run updates in place rather than failing."""
    work, _, _ = pull_origin
    once = fetch_pull(work, "origin", 259, "main")
    assert fetch_pull(work, "origin", 259, "main") == once


def test_fetch_pull_failure_with_refs_on_disk_is_only_a_warning(pull_origin):
    """Offline, an older state still describes something real, and the page
    names the commits it used."""
    work, _, _ = pull_origin
    fetch_pull(work, "origin", 259, "main")
    git(work, "remote", "set-url", "origin", str(work / "gone"))
    _, _, warnings = fetch_pull(work, "origin", 259, "main")
    assert len(warnings) == 1 and "already on disk" in warnings[0]


def test_fetch_pull_failure_with_nothing_on_disk_is_fatal(pull_origin):
    """There is genuinely nothing to review. A warning here would build a page
    from refs that do not exist."""
    work, _, _ = pull_origin
    git(work, "remote", "set-url", "origin", str(work / "gone"))
    with pytest.raises(RefError, match="never been fetched"):
        fetch_pull(work, "origin", 259, "main")


def test_remote_for_matches_the_url_rather_than_trusting_origin(tmp_path):
    """In a fork checkout, origin is the fork and the PR lives upstream."""
    r = bare(tmp_path)
    git(r, "remote", "add", "origin", "git@github.com:contributor/hsp.git")
    git(r, "remote", "add", "upstream", "https://github.com/haeger/hsp.git")
    assert remote_for(r, "haeger", "hsp") == "upstream"


def test_remote_for_matches_the_ssh_url_form(tmp_path):
    r = bare(tmp_path)
    git(r, "remote", "add", "ssh", "git@github.com:haeger/hsp.git")
    assert remote_for(r, "haeger", "hsp") == "ssh"


def test_remote_for_ignores_case(tmp_path):
    """GitHub owner and repository names are case-insensitive; git URLs record
    whatever the user typed."""
    r = bare(tmp_path)
    git(r, "remote", "add", "origin", "https://github.com/Haeger/HSP.git")
    assert remote_for(r, "haeger", "hsp") == "origin"


def test_remote_for_falls_back_to_origin(tmp_path):
    r = bare(tmp_path)
    git(r, "remote", "add", "origin", "https://example.invalid/other/thing.git")
    assert remote_for(r, "haeger", "hsp") == "origin"


def test_remote_for_without_any_remote_names_the_problem(tmp_path):
    r = bare(tmp_path)
    with pytest.raises(RefError, match="no remote"):
        remote_for(r, "haeger", "hsp")


def test_has_ref(pull_origin):
    work, _, _ = pull_origin
    assert has_ref(work, "refs/heads/main")
    assert not has_ref(work, "refs/pr-rename-review/259/head")
```

Change line 10 of `tests/test_refs.py` to:

```python
from refs import (RefError, fetch, fetch_pull, has_ref, load, remote_for,
                  remote_of, resolve, short)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_refs.py --quiet`
Expected: FAIL — `ImportError: cannot import name 'fetch_pull' from 'refs'`

- [ ] **Step 3: Implement the three functions**

Append to `refs.py`:

```python
PULL_NS = "refs/pr-rename-review"


def _slug(url):
    """`owner/name`, lowercased, from either URL form git accepts.

    Turning `:` into `/` collapses the SSH form onto the HTTPS one, and taking
    the last two segments then works for both.
    """
    tail = url.strip().rstrip("/").removesuffix(".git").replace(":", "/")
    parts = [p for p in tail.split("/") if p]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else ""


def remote_for(repo, owner, name):
    """The remote pointing at owner/name, else origin.

    Matching the URL rather than assuming origin is what makes a fork checkout
    work: there origin is the fork, and the pull request lives upstream.
    """
    remotes = _git(repo, "remote").split()
    want = f"{owner}/{name}".lower()
    for remote in remotes:
        if _slug(_git(repo, "remote", "get-url", remote)) == want:
            return remote
    if "origin" in remotes:
        return "origin"
    raise RefError(f"no remote points at {owner}/{name} and there is no "
                   f"origin; remotes found: {', '.join(remotes) or 'none'}")


def has_ref(repo, ref):
    return subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref],
                          cwd=repo, capture_output=True).returncode == 0


def fetch_pull(repo, remote, number, base_ref, timeout=FETCH_TIMEOUT):
    """Fetch the PR's own ref and its base branch. Returns (base, head,
    warnings) -- two ref *names* for `resolve`, not commits.

    `refs/pull/N/head` exists for every pull request, fork or not, and is
    exactly the commit GitHub is showing: no local branch has to exist and no
    fork has to be a configured remote. Both endpoints land in a private
    namespace, so reviewing a PR never moves a ref the user has opinions
    about, and the refspecs are forced so a second run updates in place.

    A failed fetch is fatal only when nothing is on disk to fall back to --
    see `fetch` for why an older state still beats no review at all.
    """
    head, base = f"{PULL_NS}/{number}/head", f"{PULL_NS}/{number}/base"
    try:
        proc = subprocess.run(
            ["git", "fetch", "--quiet", remote,
             f"+refs/pull/{number}/head:{head}",
             f"+refs/heads/{base_ref}:{base}"],
            cwd=repo, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
            # Fail fast instead of prompting, for the reason `fetch` gives.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        failed = proc.returncode and (
            (proc.stderr.strip().splitlines() or ["no output"])[-1])
    except subprocess.TimeoutExpired:
        failed = f"timed out after {timeout}s"
    if not failed:
        return base, head, []
    if not (has_ref(repo, head) and has_ref(repo, base)):
        raise RefError(f"git fetch {remote} failed ({failed}), and pull "
                       f"request #{number} has never been fetched here")
    return base, head, [f"git fetch {remote} failed ({failed}); "
                        "reviewing the refs already on disk"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_refs.py --quiet`
Expected: PASS, including the pre-existing `fetch`/`remote_of` tests.

- [ ] **Step 5: Commit**

```bash
git add refs.py tests/test_refs.py
git commit --message "feat: fetch a PR's own ref and base into a private namespace"
```

---

### Task 3: Wire the CLI to the pull request

The positional `PR` argument, one-time resolution, and the environment handed to the passes. `render2.py` and `pairup.py` still read the config file after this task, and the config file still exists, so the suite stays green.

**Files:**
- Modify: `cli.py:8-10` (imports), `:42-49` (`_env`), `:52-67` (`fetch_refs`), `:84-100` (`_github`), `:103-119` (`_parser`), `:122-155` (`main`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `resolve_pr`, `PullRequest` (Task 1); `remote_for`, `fetch_pull` (Task 2); `fetch`, `RefError` (existing)
- Produces: pass environment containing `REPO`, `BASE`, `HEAD_REF`, `OUT`, and — when a PR was resolved — `PR`, `PR_OWNER`, `PR_REPO`. Task 4 reads the last three in `render2.py`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, **delete** `test_refs_default_to_config` entirely (the config file it asserts against is going away), and add this helper plus the new tests:

```python
def _pull(spec=None, cwd=None):
    from github import PullRequest
    return PullRequest("haeger", "hsp", int(spec or 259), "main")


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
    for name in ("PR", "PR_OWNER", "PR_REPO"):
        monkeypatch.delenv(name, raising=False)
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
```

Then update the three existing tests that patch `cli._github` or run the fetch, so they use the fixture and the new `_github` signature:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py --quiet`
Expected: FAIL — `AttributeError: <module 'cli'> has no attribute 'resolve_pr'`

- [ ] **Step 3: Rewrite the CLI**

Replace `cli.py` lines 8-10 (the import block) with:

```python
import argparse, os, pathlib, subprocess, sys

from github import GitHub, GitHubError, resolve_pr
from refs import RefError, fetch, fetch_pull, remote_for
```

Replace `_env` and `fetch_refs` (lines 42-67) with:

```python
def _env(args, pull, base, head):
    """The environment every pass reads. Resolved once here so one run asks
    GitHub once and no pass can form a second opinion about which PR this is.

    The PR keys are cleared before being set, so a stray `PR` in the ambient
    environment cannot make an offline build claim to know the pull request.
    """
    env = {**os.environ,
           "REPO": args.repo or os.environ.get("REPO", ""),
           "BASE": base, "HEAD_REF": head,
           "OUT": args.out or os.environ.get("OUT") or str(ROOT / "build")}
    for key in ("PR", "PR_OWNER", "PR_REPO"):
        env.pop(key, None)
    if pull:
        env |= {"PR": str(pull.number), "PR_OWNER": pull.owner,
                "PR_REPO": pull.repo}
    return env


def fetch_refs(repo, base, head):
    """Update the remotes the overridden refs live on.

    Never fatal: the refs already on disk still describe a real, if older,
    state, and the page names the commits it used. Skipped entirely when
    neither ref tracks a remote -- the replay baseline names commits, and
    there is nothing to fetch for a commit.
    """
    try:
        done, warnings = fetch(repo, [base, head])
    except RefError as exc:
        warnings, done = [f"{exc}; reviewing the refs already on disk"], []
    for remote in done:
        print(f"== fetch {remote}", file=sys.stderr)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)


def prepare(args, need_refs=True):
    """Work out what to review. Returns (env, pull); pull is None offline.

    `--base`/`--head` (or $BASE/$HEAD_REF) skip GitHub entirely. That is the
    offline path, and the one tests/conftest.py drives the pinned replay
    baseline through -- which is why it must never consult gh.
    """
    repo = args.repo or os.environ.get("REPO") or None
    base = args.base or os.environ.get("BASE")
    head = args.head or os.environ.get("HEAD_REF")
    if base and head:
        fetch_refs(repo, base, head)
        return _env(args, None, base, head), None
    if base or head:
        raise RefError("--base and --head must be given together, or neither "
                       "-- otherwise name a pull request")

    pull = resolve_pr(args.pr, cwd=repo)
    if not need_refs:
        # serve --no-build: the PR is still needed to sync viewed ticks, but
        # nothing is being built, so nothing is fetched.
        return _env(args, pull, "", ""), pull
    remote = remote_for(repo, pull.owner, pull.repo)
    print(f"== fetch {remote} refs/pull/{pull.number}/head", file=sys.stderr)
    base, head, warnings = fetch_pull(repo, remote, pull.number, pull.base_ref)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return _env(args, pull, base, head), pull
```

Replace `_github` (lines 84-100, keeping `_OfflineGitHub` above it unchanged) with:

```python
def _github(pull, cwd=None):
    """The user's own gh login, or an offline stand-in with the reason.

    `gh` resolves the repository from its working directory, so every call is
    made inside the checkout under review rather than inside this tool.
    """
    if pull is None:
        return _OfflineGitHub("--base/--head given, so no pull request is "
                              "known; name one to sync viewed state")
    return GitHub(pull.owner, pull.repo, pull.number, cwd=cwd)
```

Replace `_parser` and `main` (lines 103-155) with:

```python
def _parser():
    p = argparse.ArgumentParser(
        prog="pr-rename-review",
        description="Review a rename-heavy PR that GitHub's diff cannot pair")
    p.add_argument("--repo", help="checkout to diff (default: $REPO or cwd)")
    p.add_argument("--base", help="base ref, skipping GitHub (needs --head)")
    p.add_argument("--head", help="head ref, skipping GitHub (needs --base)")
    p.add_argument("--out", help="output directory (default: ./build)")
    p.add_argument("--no-build", action="store_true",
                   help="serve the existing build/ without rebuilding")
    p.add_argument("--no-browser", action="store_true",
                   help="do not open a browser when serving")
    sub = p.add_subparsers(dest="cmd")
    for name, help_text in (
            ("build", "run the passes and write the page"),
            ("pairs", "print the pairing disagreement report"),
            ("serve", "build, then serve the page on localhost")):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("pr", nargs="?", metavar="PR",
                       help="pull request: number, #number or URL "
                            "(default: the PR of the checked-out branch)")
    return p


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = _parser()
    args = parser.parse_args(argv)

    if not args.cmd:
        parser.print_usage(sys.stderr)
        print("error: pick a subcommand: build, pairs, serve", file=sys.stderr)
        return 2

    building = args.cmd != "serve" or not args.no_build
    try:
        env, pull = prepare(args, need_refs=building)
    except (GitHubError, RefError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.cmd in ("pairs", "build"):
        return run_passes(["pairup.py"] if args.cmd == "pairs" else ALL_PASSES,
                          env)

    # serve. Rebuilds every time unless told not to: the passes take seconds,
    # and a staleness heuristic that guesses wrong serves a stale page that
    # looks current -- the exact failure this tool exists to prevent.
    from server import serve
    if building:
        code = run_passes(ALL_PASSES, env)
        if code:
            return code
    page = pathlib.Path(env["OUT"]) / "hidden-renames.html"
    if not page.exists():
        print(f"error: {page} does not exist; run without --no-build",
              file=sys.stderr)
        return 1
    serve(page, _github(pull, cwd=env["REPO"] or None),
          open_browser=not args.no_browser)
    return 0
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest --quiet`
Expected: PASS. `render2.py` and `pairup.py` still load the config file; it still exists.

- [ ] **Step 5: Commit**

```bash
git add cli.py tests/test_cli.py
git commit --message "feat: take a pull request argument instead of configured refs"
```

---

### Task 4: Deep links from the environment

`pr_url` takes a number; `render2.py` reads the PR from the environment instead of loading config and making its own `gh repo view` call.

**Files:**
- Modify: `github.py:58-68` (`pr_url`)
- Modify: `render2.py:1-27` (imports and resolution), `:52` (the call)
- Test: `tests/test_render.py:1-40`

**Interfaces:**
- Consumes: `PR`, `PR_OWNER`, `PR_REPO` from the environment (Task 3)
- Produces: `pr_url(owner, repo, pr, path, line=None) -> str | None`

- [ ] **Step 1: Update the failing tests**

In `tests/test_render.py`, delete the `from config import Config` import and the `cfg()` helper, and rewrite the five `pr_url` tests:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_render.py --quiet`
Expected: FAIL — `pr_url` still expects a config object first, so the URL comes out wrong or raises.

- [ ] **Step 3: Change `pr_url` and `render2.py`**

In `github.py`, replace the `pr_url` signature and guard (lines 58-68) with:

```python
def pr_url(owner, repo, pr, path, line=None):
    """Deep link into GitHub's own diff. Commenting happens there -- this tool
    does not write comments, by design.

    Here rather than in render2.py because it is a pure function of its
    arguments, and render2.py cannot be imported without a build directory.
    """
    if not (pr and owner and repo):
        return None
    return (f"https://github.com/{owner}/{repo}/pull/{pr}/files"
            f"{anchor(path, line)}")
```

In `render2.py`, replace lines 1-27 with:

```python
import json, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from github import pr_url
from refs import load

S = pathlib.Path(__file__).parent
OUT = pathlib.Path(os.environ.get("OUT") or (pathlib.Path(__file__).parent / "build"))
OUT.mkdir(parents=True, exist_ok=True)
files = json.loads((OUT / "diffdata2.json").read_text())["files"]

# From the run, never from a ref name: with a moving head ref the name alone
# is true of every build ever made, and `--base`/`--head` overrides carry no
# name at all. Printing the commit is what makes a stale page look stale.
REFS = load(OUT)
BASE_SHORT, HEAD_SHORT = REFS["base"][:9], REFS["head"][:9]
SUMMARY = json.loads((OUT / "scope-summary.json").read_text()) if (
    OUT / "scope-summary.json").exists() else {}

# Resolved once by cli.py and handed down, so every pass agrees on which PR
# this is and only one gh call is made per run. `build` must work with no gh
# at all -- and with `--base`/`--head`, where there is no PR; the deep links
# are simply absent then.
PR = int(os.environ["PR"]) if os.environ.get("PR") else None
OWNER = os.environ.get("PR_OWNER") or None
REPO_NAME = os.environ.get("PR_REPO") or None
```

Then change line 52 (now renumbered) from `"gh": pr_url(CFG, OWNER, REPO_NAME, f["new"]),` to:

```python
        "gh": pr_url(OWNER, REPO_NAME, PR, f["new"]),
```

Note the `anchor` and `GitHubError` imports are dropped: `anchor` was only mentioned in a JavaScript comment, never called from Python, and `GitHubError` was only used by the `resolve_repo` try/except that is now gone.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest --quiet`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add github.py render2.py tests/test_render.py
git commit --message "refactor: build deep links from the resolved PR, not from config"
```

---

### Task 5: Delete the config file and its loader

The last consumers go, then the config itself, then the documentation that describes it.

**Files:**
- Modify: `pairup.py:107-115` (`main`)
- Delete: `config.py`, `.pr-rename-review.toml`, `tests/test_config.py`
- Modify: `github.py` (delete `resolve_repo` and `resolve_target`), `tests/test_github.py:3,123-135`
- Modify: `pyproject.toml` (wheel include list), `run.sh`, `README.md`

**Interfaces:**
- Consumes: `BASE`/`HEAD_REF` from the environment (Task 3)
- Produces: nothing new. This task is subtraction.

- [ ] **Step 1: Write the failing test for pairup's new requirement**

Add to `tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_pairup_without_refs_says_how_to_run_it --quiet`
Expected: FAIL — pairup currently falls back to the config file and gets as far as resolving refs.

- [ ] **Step 3: Drop the config fallback from pairup.py**

Replace `pairup.py` lines 107-115 with:

```python
def main():
    repo = os.environ.get("REPO") or subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True).stdout.strip()
    base_ref, head_ref = os.environ.get("BASE"), os.environ.get("HEAD_REF")
    if not (base_ref and head_ref):
        sys.exit("BASE and HEAD_REF must both be set; run this through "
                 "`pr-rename-review`, which resolves them from the PR")
    base, head = resolve(repo, base_ref, head_ref)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_pairup_without_refs_says_how_to_run_it --quiet`
Expected: PASS

- [ ] **Step 5: Delete the config, its loader, and the superseded resolvers**

```bash
git rm config.py .pr-rename-review.toml tests/test_config.py
```

In `github.py`, delete the `resolve_repo` and `resolve_target` functions entirely (currently lines 129-161, after Task 1's additions shifted them). `resolve_pr` supersedes both.

In `tests/test_github.py`: change line 3 to `from github import GitHub, GitHubError, anchor, resolve_pr`, and delete `test_resolve_repo_reads_owner_and_name` and `test_resolve_target_reads_owner_repo_and_number`.

In `pyproject.toml`, remove `"config.py",` from the wheel include list, leaving:

```toml
[tool.hatch.build.targets.wheel]
include = ["cli.py", "pairup.py", "scope.py",
           "gen2.py", "render2.py"]
```

- [ ] **Step 6: Verify nothing still references the config**

Run: `git grep --line-number "load_config\|pr-rename-review.toml\|from config\|import config"`
Expected: no output at all. If anything matches, fix it before continuing.

Run: `uv run pytest --quiet`
Expected: PASS.

- [ ] **Step 7: Update `run.sh`**

Replace its comment block, since the config file it names is gone:

```bash
#!/usr/bin/env bash
# Compatibility shim. `uv run pr-rename-review build` is the real entry point.
#
#   ./run.sh 259
#   REPO=/path/to/checkout ./run.sh https://github.com/owner/repo/pull/259
#   REPO=/path/to/checkout BASE=52efff3 HEAD_REF=1ce7bfa ./run.sh
#
# With no argument, the PR of the checked-out branch is reviewed. BASE and
# HEAD_REF skip GitHub entirely.
set -euo pipefail
cd "$(dirname "$0")"
exec uv run pr-rename-review build "$@"
```

- [ ] **Step 8: Update the README**

Three edits:

1. Replace the "Using it" block:

````markdown
## Using it

```sh
export REPO=/path/to/the/checkout          # the repo the PR lives in

uv run pr-rename-review serve 259          # build, serve, open a browser
uv run pr-rename-review build 259          # passes only, no server
uv run pr-rename-review pairs 259          # disagreement report, then exit
```

The pull request can be a number, `#259`, or its URL. Leave it out and the PR
of the branch checked out in `$REPO` is reviewed.

Base and head come from the PR itself: `gh` reports which branch it targets,
and `refs/pull/259/head` is fetched into a private ref namespace along with
that base branch. Nothing is configured, and nothing local has to be checked
out — a PR from a fork needs no remote of its own.

Flags: `--repo`, `--out`, `--no-build` (serve the existing `build/`),
`--no-browser`, and `--base`/`--head`, which review two refs directly and
skip GitHub entirely.
````

2. Delete the "## Configuration" section entirely.

3. In the section on the merge base, fold in the reasoning the deleted
   `.pr-rename-review.toml` carried, adding this paragraph:

````markdown
The base is resolved to `git merge-base base head`, never to the base branch's
tip. Against the tip, every commit the base branch gained since the fork would
appear inside the review as if the PR had made it. That is what makes a moving
base safe: the PR is re-fetched on every build, so a push shows up on the page,
and the page prints the commits it actually built from, so an older build is
visibly older.
````

- [ ] **Step 9: Run everything and commit**

Run: `uv run pytest --quiet`
Expected: PASS

```bash
git add --all
git commit --message "refactor: delete the config file now the PR supplies the refs"
```

---

### Task 6: Verify the baseline still reproduces

The acceptance test from the spec: the input surface changed, the output must not. This task writes no code — if a number moved, something in Tasks 1–5 is wrong.

**Files:** none modified unless a defect is found.

**Interfaces:**
- Consumes: everything from Tasks 1–5.

- [ ] **Step 1: Run the full suite against the real checkout**

The replay tests skip without `REPO`. The checkout is `~/Developer/hc/hsp/hsp-backend`.

```bash
REPO=~/Developer/hc/hsp/hsp-backend uv run pytest --quiet
```

Expected: PASS with **zero skips** among the replay tests, meaning
`tests/golden/` still matches a fresh run at `BASE=eb1b00665 HEAD_REF=47c9dc7`.
The pinned baseline drives the `--base`/`--head` path, so this also proves that
path never consults `gh`.

- [ ] **Step 2: Check the baseline numbers by hand**

```bash
REPO=~/Developer/hc/hsp/hsp-backend BASE=eb1b00665 HEAD_REF=47c9dc7 \
  uv run pr-rename-review pairs
```

Expected, per the README's Baseline section: **244 recorded moves, 10 pairing
disagreements**. If either differs, stop — the pairing pass has changed
behaviour and it should not have.

- [ ] **Step 3: Exercise the new path end to end**

```bash
REPO=~/Developer/hc/hsp/hsp-backend uv run pr-rename-review pairs 259
```

Expected: a `== fetch <remote> refs/pull/259/head` line, then a report. The
numbers will differ from the baseline — the baseline is a pinned commit and
this is the branch as it stands — which is the point. Confirm the header line
names the commits it resolved.

Then confirm the bare form works:

```bash
cd ~/Developer/hc/hsp/hsp-backend && git checkout refactor/german-to-english-rename-v2
REPO=~/Developer/hc/hsp/hsp-backend uv run pr-rename-review pairs
```

Expected: resolves to PR #259 without being told.

- [ ] **Step 4: Confirm the viewed-state round trip still works**

```bash
REPO=~/Developer/hc/hsp/hsp-backend uv run pr-rename-review serve 259
```

Open the page, tick a file you have genuinely reviewed, reload PR #259's Files
tab on GitHub, and confirm the tick is there. This is the claim that justifies
the server, and Task 4 changed how the PR reaches the page — so it must be
re-checked rather than assumed. Untick it in GitHub, reload the tool's page,
and confirm it shows unviewed there.

- [ ] **Step 5: Record the outcome**

If every check passed, no commit is needed — Task 5 already committed. If a
check failed, fix the cause and amend the relevant task's commit rather than
adding a "fix" commit on top.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Command surface (positional PR, number/`#`/URL, bare form) | 3 (parser), 1 (spec forms) |
| `--base`/`--head` skip GitHub | 3 |
| Resolving the PR via `gh pr view --json url,number,baseRefName` | 1 |
| owner/repo from `url`, not `headRepository*` | 1 |
| Remote selection by URL tail, fallback to `origin` | 2 |
| Fetch `refs/pull/N/head` + base into a private namespace, forced | 2 |
| `merge-base` unchanged | 2 (test), unchanged code |
| `PR`/`PR_OWNER`/`PR_REPO` through the environment | 3, 4 |
| `pr_url` loses its `cfg` parameter | 4 |
| Error table (5 rows) | 1 (rows 3–4), 2 (rows 1–2, 5), 3 (surfacing) |
| Deletions (`config.py`, toml, `test_config.py`, `resolve_repo`/`resolve_target`) | 5 |
| `run.sh` and README updated | 5 |
| Testing: `resolve_pr`, remote selection, refspec, warnings | 1, 2 |
| `test_cli` gains positional + bypass, loses `test_refs_default_to_config` | 3 |
| `conftest.py` and golden replay untouched; baseline reproduces | 6 |

No gaps.

**Placeholder scan:** every step carries the actual code or the actual command. The only judgement call deferred to the implementer is the exact line numbers of `resolve_repo`/`resolve_target` in Task 5 Step 5, which shift depending on where Task 1's code was appended — the function names are unambiguous.

**Type consistency:** `PullRequest` fields are `owner`, `repo`, `number`, `base_ref` in Task 1 and are read under exactly those names in Tasks 3 (`pull.owner`, `pull.repo`, `pull.number`, `pull.base_ref`) and 4. `fetch_pull` returns `(base, head, warnings)` in Task 2 and is unpacked in that order in Task 3. `pr_url(owner, repo, pr, path, line=None)` is defined in Task 4 and called with that order in both `render2.py` and `tests/test_render.py`. `remote_for(repo, owner, name)` is defined in Task 2 and called as `remote_for(repo, pull.owner, pull.repo)` in Task 3.
