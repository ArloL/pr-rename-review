"""GitHub access via the `gh` CLI.

The tool never holds a token. `gh` is already authenticated as the user, and
`viewerViewedState` resolves against whoever holds the credential -- which is
why an app token sees nothing and this has to shell out. That token identity
is the reason the prototype could not sync viewed state at all.
"""
import hashlib, json, subprocess

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


def resolve_repo(runner=None, cwd=None):
    """(owner, repo) for the checkout. Used when the PR number is configured,
    so no branch has to be checked out to find it."""
    run = runner or runner_for(cwd)
    try:
        raw = run(["gh", "repo", "view", "--json", "name,owner"])
    except FileNotFoundError as exc:
        raise GitHubError(
            "gh not found -- install it and run `gh auth login`") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unexpected output from gh: {raw[:200]!r}") from exc
    return data["owner"]["login"], data["name"]


def resolve_target(runner=None, cwd=None, ref=None):
    """(owner, repo, pr_number) for the PR of `ref`, or of the current branch."""
    run = runner or runner_for(cwd)
    try:
        cmd = ["gh", "pr", "view"]
        if ref:
            cmd.append(ref)
        raw = run(cmd + ["--json", "number,headRepository,headRepositoryOwner"])
    except FileNotFoundError as exc:
        raise GitHubError(
            "gh not found -- install it and run `gh auth login`") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unexpected output from gh: {raw[:200]!r}") from exc
    return (data["headRepositoryOwner"]["login"],
            data["headRepository"]["name"], data["number"])
