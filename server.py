"""A stateless localhost proxy between the generated page and GitHub.

It exists for exactly one reason: a browser cannot hold the user's `gh`
credentials. No state is kept here -- GitHub is the store. Bound to loopback,
because the page carries private source.
"""
import http.server, json, webbrowser
from github import GitHubError


def make_server(page, gh, host="127.0.0.1", port=0):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, payload, ctype="application/json"):
            body = (payload if isinstance(payload, bytes)
                    else json.dumps(payload).encode())
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._send(200, page.read_bytes(),
                                  "text/html; charset=utf-8")
            if self.path == "/api/viewed":
                try:
                    return self._send(200, {"synced": True,
                                            "states": gh.viewed_states()})
                except GitHubError as exc:
                    # Degrade, never break: the page falls back to
                    # localStorage and says so in its banner.
                    return self._send(200, {"synced": False, "states": {},
                                            "reason": str(exc)})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/viewed":
                return self._send(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "malformed JSON"})
            # A list, because a sub-threshold rename is two entries in
            # GitHub's file list and one tick must cover both.
            paths = body.get("paths")
            if (not isinstance(paths, list) or not paths
                    or not all(isinstance(p, str) and p for p in paths)):
                return self._send(
                    400, {"error": "paths must be a non-empty list of strings"})
            try:
                for path in paths:
                    state = gh.set_viewed(path, bool(body.get("viewed")))
            except GitHubError as exc:
                # 502 rather than 200: the page must revert the tick, because
                # a tick that did not reach GitHub is a file marked reviewed
                # that nobody reviewed. A pair that failed on its second path
                # is reverted and retried whole; the mutations are idempotent,
                # so the retry converges.
                return self._send(502, {"error": str(exc)})
            self._send(200, {"paths": paths, "state": state})

    return http.server.ThreadingHTTPServer((host, port), Handler)


def serve(page, gh, host="127.0.0.1", port=0, open_browser=True):
    srv = make_server(page, gh, host, port)
    url = f"http://{host}:{srv.server_address[1]}/"
    # flush: stdout is block-buffered when redirected, and a URL you cannot
    # see until the process exits is a URL you do not have.
    print(f"serving {page.name} at {url}  (ctrl-c to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        srv.shutdown()
        srv.server_close()
