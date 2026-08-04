"""GitHub access via the `gh` CLI.

The tool never holds a token. `gh` is already authenticated as the user, and
`viewerViewedState` resolves against whoever holds the credential -- which is
why an app token sees nothing and this has to shell out. That token identity
is the reason the prototype could not sync viewed state at all.
"""
import hashlib, json, re, subprocess
from dataclasses import dataclass

FILES_QUERY = """
query($owner:String!,$repo:String!,$pr:Int!,$after:String){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$pr){
      files(first:100,after:$after){
        nodes{ path viewerViewedState }
        pageInfo{ hasNextPage endCursor }
      }}}}
"""

PR_ID_QUERY = """
query($owner:String!,$repo:String!,$pr:Int!){
  repository(owner:$owner,name:$repo){ pullRequest(number:$pr){ id }}}
"""

MARK = """
mutation($id:ID!,$path:String!){
  markFileAsViewed(input:{pullRequestId:$id,path:$path}){ clientMutationId }}
"""

UNMARK = """
mutation($id:ID!,$path:String!){
  unmarkFileAsViewed(input:{pullRequestId:$id,path:$path}){ clientMutationId }}
"""


class GitHubError(Exception):
    pass


def runner_for(cwd=None):
    """`gh` resolves the repository from its working directory, so this must
    run inside the checkout being reviewed -- not inside this tool."""
    def run(cmd):
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              cwd=cwd or None)
        if proc.returncode:
            raise GitHubError(proc.stderr.strip() or f"{cmd[0]} failed")
        return proc.stdout
    return run


def anchor(path, line=None):
    """GitHub keys each file in a PR diff by the sha256 of its path."""
    frag = f"#diff-{hashlib.sha256(path.encode()).hexdigest()}"
    return f"{frag}R{line}" if line else frag


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


def _graphql(run, query, **variables):
    # In `gh api`, --field is TYPED (numbers and booleans are converted) and
    # --raw-field is always a string. An Int! variable therefore needs
    # --field, and everything else --raw-field so a numeric-looking ref or
    # path is not silently turned into a number.
    cmd = ["gh", "api", "graphql", "--raw-field", f"query={query}"]
    for key, value in variables.items():
        if value is None:
            continue
        flag = "--raw-field" if isinstance(value, str) else "--field"
        cmd += [flag, f"{key}={value}"]
    try:
        raw = run(cmd)
    except FileNotFoundError as exc:
        raise GitHubError(
            "gh not found -- install it and run `gh auth login`") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unexpected output from gh: {raw[:200]!r}") from exc
    if payload.get("errors"):
        raise GitHubError("; ".join(e.get("message", "?")
                                    for e in payload["errors"]))
    return payload.get("data", {})


class GitHub:
    def __init__(self, owner, repo, pr, runner=None, cwd=None):
        self.owner, self.repo, self.pr = owner, repo, pr
        self._run = runner or runner_for(cwd)
        self._pr_id = None

    def viewed_states(self):
        """Path -> VIEWED / UNVIEWED / DISMISSED for every file in the PR."""
        states, cursor = {}, None
        while True:
            data = _graphql(self._run, FILES_QUERY, owner=self.owner,
                            repo=self.repo, pr=self.pr, after=cursor)
            files = data["repository"]["pullRequest"]["files"]
            for node in files["nodes"]:
                states[node["path"]] = node["viewerViewedState"]
            if not files["pageInfo"].get("hasNextPage"):
                return states
            cursor = files["pageInfo"]["endCursor"]

    def _id(self):
        if self._pr_id is None:
            data = _graphql(self._run, PR_ID_QUERY, owner=self.owner,
                            repo=self.repo, pr=self.pr)
            self._pr_id = data["repository"]["pullRequest"]["id"]
        return self._pr_id

    def set_viewed(self, path, viewed):
        _graphql(self._run, MARK if viewed else UNMARK,
                 id=self._id(), path=path)
        return "VIEWED" if viewed else "UNVIEWED"


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
