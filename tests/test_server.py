import json, threading, urllib.error, urllib.request
import pytest
from github import GitHubError
from server import make_server


class FakeGitHub:
    def __init__(self, states=None, fail=False):
        self.states = states or {}
        self.fail = fail
        self.writes = []

    def viewed_states(self):
        if self.fail:
            raise GitHubError("not authenticated")
        return dict(self.states)

    def set_viewed(self, path, viewed):
        if self.fail:
            raise GitHubError("not authenticated")
        self.writes.append((path, viewed))
        self.states[path] = "VIEWED" if viewed else "UNVIEWED"
        return self.states[path]


@pytest.fixture
def live(tmp_path):
    page = tmp_path / "hidden-renames.html"
    page.write_text("<h1>page</h1>")
    servers = []

    def start(gh):
        srv = make_server(page, gh, "127.0.0.1", 0)
        servers.append(srv)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{srv.server_address[1]}"

    yield start
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read().decode()


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read().decode())


def test_root_serves_the_page(live):
    status, body = get(live(FakeGitHub()) + "/")
    assert status == 200 and "<h1>page</h1>" in body


def test_get_viewed_returns_states(live):
    status, body = get(live(FakeGitHub({"a.java": "VIEWED"})) + "/api/viewed")
    assert status == 200
    assert json.loads(body) == {"synced": True, "states": {"a.java": "VIEWED"}}


def test_get_viewed_reports_unsynced_rather_than_failing(live):
    """No gh login must leave the page usable, not break it."""
    status, body = get(live(FakeGitHub(fail=True)) + "/api/viewed")
    payload = json.loads(body)
    assert status == 200
    assert payload["synced"] is False
    assert "not authenticated" in payload["reason"]
    assert payload["states"] == {}


def test_post_viewed_marks_the_file(live):
    gh = FakeGitHub()
    status, body = post(live(gh) + "/api/viewed",
                        {"paths": ["a.java"], "viewed": True})
    assert status == 200 and body == {"paths": ["a.java"], "state": "VIEWED"}
    assert gh.writes == [("a.java", True)]


def test_post_viewed_marks_every_path_of_a_pair(live):
    """A sub-threshold rename is two entries in GitHub's file list -- the
    deleted old path and the added new path. One tick must cover both, or
    GitHub's own progress never reaches 100%."""
    gh = FakeGitHub()
    _, body = post(live(gh) + "/api/viewed",
                   {"paths": ["new/B.java", "old/A.java"], "viewed": True})
    assert body == {"paths": ["new/B.java", "old/A.java"], "state": "VIEWED"}
    assert gh.writes == [("new/B.java", True), ("old/A.java", True)]


def test_post_viewed_unmarks(live):
    gh = FakeGitHub({"a.java": "VIEWED", "b.java": "VIEWED"})
    _, body = post(live(gh) + "/api/viewed",
                   {"paths": ["a.java", "b.java"], "viewed": False})
    assert body["state"] == "UNVIEWED"
    assert gh.writes == [("a.java", False), ("b.java", False)]


def test_post_failure_is_a_502_so_the_page_can_revert(live):
    """A tick that never reached GitHub would mean a file marked reviewed
    that nobody reviewed, so the page must be told."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(live(FakeGitHub(fail=True)) + "/api/viewed",
             {"paths": ["a.java"], "viewed": True})
    assert exc.value.code == 502


def test_post_without_paths_is_a_400(live):
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(live(FakeGitHub()) + "/api/viewed", {"viewed": True})
    assert exc.value.code == 400


def test_post_with_empty_paths_is_a_400(live):
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(live(FakeGitHub()) + "/api/viewed", {"paths": [], "viewed": True})
    assert exc.value.code == 400


def test_post_with_a_bare_string_path_is_a_400(live):
    """A string iterates as characters; marking one file per character must
    be rejected, not half-executed."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(live(FakeGitHub()) + "/api/viewed",
             {"paths": "a.java", "viewed": True})
    assert exc.value.code == 400


def test_post_with_malformed_json_is_a_400(live):
    base = live(FakeGitHub())
    req = urllib.request.Request(base + "/api/viewed", data=b"{nope",
                                 method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400


def test_unknown_route_is_a_404(live):
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(live(FakeGitHub()) + "/nope")
    assert exc.value.code == 404


def test_post_to_unknown_route_is_a_404(live):
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(live(FakeGitHub()) + "/nope", {"path": "a", "viewed": True})
    assert exc.value.code == 404


def test_binds_loopback_only(tmp_path):
    """A review page carrying private source must not be reachable off-box."""
    page = tmp_path / "p.html"
    page.write_text("x")
    srv = make_server(page, FakeGitHub(), "127.0.0.1", 0)
    assert srv.server_address[0] == "127.0.0.1"
    srv.server_close()
