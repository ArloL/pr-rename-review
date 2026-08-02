import hashlib, json
import pytest
from github import GitHub, GitHubError, anchor, resolve_target


class FakeRunner:
    """Records the commands it is given and replays canned stdout."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def files_page(nodes, has_next=False, cursor=None):
    return json.dumps({"data": {"repository": {"pullRequest": {"files": {
        "nodes": nodes,
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}}}}}})


PR_ID = json.dumps({"data": {"repository": {"pullRequest": {"id": "PR_1"}}}})


def test_anchor_is_sha256_of_the_path():
    want = hashlib.sha256(b"src/main/java/Foo.java").hexdigest()
    assert anchor("src/main/java/Foo.java") == f"#diff-{want}"


def test_anchor_with_a_line_targets_the_new_side():
    assert anchor("a.java", 42).endswith("R42")


def test_anchor_line_zero_is_not_treated_as_a_line():
    assert not anchor("a.java", 0).endswith("R0")


def test_viewed_states_are_keyed_by_path():
    gh = GitHub("o", "r", 252, runner=FakeRunner(files_page([
        {"path": "a.java", "viewerViewedState": "VIEWED"},
        {"path": "b.java", "viewerViewedState": "UNVIEWED"}])))
    assert gh.viewed_states() == {"a.java": "VIEWED", "b.java": "UNVIEWED"}


def test_viewed_states_follow_pagination():
    """A 242-file PR needs more than one page; stopping at the first would
    report most of the PR as unviewed."""
    runner = FakeRunner(
        files_page([{"path": "a.java", "viewerViewedState": "VIEWED"}],
                   has_next=True, cursor="CUR"),
        files_page([{"path": "b.java", "viewerViewedState": "UNVIEWED"}]))
    gh = GitHub("o", "r", 252, runner=runner)
    assert set(gh.viewed_states()) == {"a.java", "b.java"}
    assert len(runner.calls) == 2
    assert any("after=CUR" in part for part in runner.calls[1])


def test_set_viewed_marks_and_returns_the_new_state():
    runner = FakeRunner(PR_ID, json.dumps(
        {"data": {"markFileAsViewed": {"clientMutationId": None}}}))
    gh = GitHub("o", "r", 252, runner=runner)
    assert gh.set_viewed("a.java", True) == "VIEWED"
    assert "markFileAsViewed" in " ".join(runner.calls[1])


def test_set_viewed_unmarks():
    runner = FakeRunner(PR_ID, json.dumps(
        {"data": {"unmarkFileAsViewed": {"clientMutationId": None}}}))
    gh = GitHub("o", "r", 252, runner=runner)
    assert gh.set_viewed("a.java", False) == "UNVIEWED"
    assert "unmarkFileAsViewed" in " ".join(runner.calls[1])


def test_the_pr_id_is_fetched_once_and_reused():
    runner = FakeRunner(PR_ID, "{}", "{}")
    gh = GitHub("o", "r", 252, runner=runner)
    gh.set_viewed("a.java", True)
    gh.set_viewed("b.java", True)
    assert len(runner.calls) == 3, "the PR id was re-fetched"


def test_graphql_errors_become_GitHubError():
    payload = json.dumps({"errors": [{"message": "Could not resolve to a User"}]})
    gh = GitHub("o", "r", 252, runner=FakeRunner(payload))
    with pytest.raises(GitHubError, match="Could not resolve"):
        gh.viewed_states()


def test_missing_gh_becomes_GitHubError_with_a_fix():
    gh = GitHub("o", "r", 252, runner=FakeRunner(FileNotFoundError("gh")))
    with pytest.raises(GitHubError, match="gh auth login"):
        gh.viewed_states()


def test_unparseable_output_becomes_GitHubError():
    gh = GitHub("o", "r", 252, runner=FakeRunner("not json"))
    with pytest.raises(GitHubError, match="unexpected"):
        gh.viewed_states()


def test_resolve_target_reads_owner_repo_and_number():
    payload = json.dumps({"number": 252,
                          "headRepository": {"name": "hsp"},
                          "headRepositoryOwner": {"login": "haeger"}})
    assert resolve_target(runner=FakeRunner(payload)) == ("haeger", "hsp", 252)


def test_no_token_ever_appears_in_a_command():
    """The tool must never handle a token; gh holds the credential."""
    runner = FakeRunner(files_page([]))
    GitHub("o", "r", 252, runner=runner).viewed_states()
    joined = " ".join(" ".join(c) for c in runner.calls)
    assert "token" not in joined.lower()
    assert "Authorization" not in joined
