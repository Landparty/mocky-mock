"""Loopback-only HTTP server behind `mockymock dashboard`.

The page itself is static assets (plain HTML/CSS/JS, no build step); this
server exists solely because a browser cannot ask Docker anything on its
own. It serves those assets plus:

* `GET /api/status` -- the read-only toolchain probe the page polls.
* `GET /api/reports` and `GET /reports/<path>` -- the `mockymock report`
  HTML pages found under the dashboard's reports root (web/reports.py).
* `GET /api/plugin` and `POST /api/plugin/install` -- verify, and install,
  the cobol-testing Claude Code skills (web/plugin.py). The install is the
  one thing this server ever writes, and only on an explicit button press.

Two deliberate constraints:

* **Loopback only.** The bind address is not configurable. The endpoint
  reports the state of *this* machine's Docker toolchain and has no
  authentication; exposing it on `0.0.0.0` would hand that out to the
  network for nothing. No CORS headers are sent either, so the browser's
  same-origin policy keeps other sites from reading it -- and a request
  whose `Host` header is not `127.0.0.1`/`localhost` is refused, which
  closes the DNS-rebinding route around that policy
  (`host_header_allowed`).
* **Read-only toolchain.** `/api/status` calls `runtime.status.probe()`,
  never `ensure_toolchain()` -- see that module's docstring for why a
  polling page must not be able to trigger image builds.
* **The one write is guarded against other sites.** `POST
  /api/plugin/install` copies files into the user's home directory, so
  besides the Host check it requires an `Origin` naming this server and a
  JSON body (`post_allowed`): a cross-site form or `fetch` either sends a
  foreign Origin or needs a CORS preflight this server never answers.

Assets live under `mockymock/web/static/` (inside the package, resolved
via `Path(__file__)`) rather than at the repo root, for the same reason
the Dockerfile does: setuptools packages nothing outside `mockymock/`, so
a repo-root path would vanish under `uv tool install`. They are listed in
pyproject's `[tool.setuptools.package-data]`.
"""

from __future__ import annotations

import json
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from mockymock.runtime import status
from mockymock.web import plugin, reports

STATIC_DIR = Path(__file__).resolve().parent / "static"

HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# Server-side probe coalescing (2026-08-12 audit Finding 19).
# ThreadingHTTPServer spawns an unbounded thread per request, and one
# probe shells out to docker up to four times with PROBE_TIMEOUT-bounded
# calls -- against a slow daemon, a page polling every few seconds piles
# up concurrent docker subprocesses without this. The lock keeps at most
# one probe in flight; the short TTL collapses a burst of polls (and any
# threads that queued on the lock behind the winner) into one docker
# sweep. Well under the page's own poll interval, so the browser-facing
# `Cache-Control: no-store` freshness contract is unaffected.
_PROBE_CACHE_TTL = 2.0
_probe_lock = threading.Lock()
_probe_cache: tuple[float, dict[str, Any]] | None = None


def _cached_probe() -> dict[str, Any]:
    global _probe_cache
    with _probe_lock:
        if (
            _probe_cache is not None
            and time.monotonic() - _probe_cache[0] < _PROBE_CACHE_TTL
        ):
            return _probe_cache[1]
        payload = status.probe().to_dict()
        _probe_cache = (time.monotonic(), payload)
        return payload


_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def resolve_static(url_path: str) -> Path | None:
    """Map a request path to a file under STATIC_DIR, or None if it escapes
    that directory or doesn't exist. `..` traversal and (on Windows) an
    absolute drive path smuggled in as `/C:/...` both survive the join, so
    containment is checked after `resolve()` rather than by inspecting the
    string."""
    relative = url_path.lstrip("/") or "index.html"
    candidate = (STATIC_DIR / relative).resolve()
    if not candidate.is_relative_to(STATIC_DIR):
        return None
    if not candidate.is_file():
        return None
    return candidate


_LOOPBACK_HOST_NAMES = frozenset({HOST, "localhost"})


def host_header_allowed(host_header: str | None, port: int) -> bool:
    """True when a request's `Host` header names this loopback server.

    Binding to 127.0.0.1 keeps other machines out but not other *sites*: a
    page on an attacker's domain whose DNS name is re-pointed at 127.0.0.1
    (DNS rebinding) is same-origin with its own name, so the browser lets
    it read `/api/status` -- the browser still sends that attacker name in
    `Host`, which is the one thing it cannot forge. Only `127.0.0.1` and
    `localhost`, on this server's own port (or with no port), are served."""
    if not host_header:
        return False
    name, sep, host_port = host_header.strip().rpartition(":")
    if not sep:
        name, host_port = host_header.strip(), ""
    if name.lower() not in _LOOPBACK_HOST_NAMES:
        return False
    return host_port in ("", str(port))


def post_allowed(origin: str | None, content_type: str | None, port: int) -> bool:
    """True when a POST comes from this dashboard's own page.

    The Host check alone does not stop cross-site requests: any page the
    user has open can submit a form or a no-cors `fetch` to
    `http://127.0.0.1:<port>/`, and the browser sends the real loopback
    Host. It always sends `Origin` on a cross-origin POST, though, and a
    `Content-Type: application/json` body from another origin needs a
    CORS preflight that this server never grants."""
    if not origin or not content_type:
        return False
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        return False
    scheme, sep, rest = origin.strip().partition("://")
    if not sep or scheme.lower() != "http":
        return False
    # An Origin carries no port only for the scheme default, so a bare
    # name is this server only when it really listens on 80.
    name, colon, origin_port = rest.rpartition(":")
    if not colon:
        name, origin_port = rest, "80"
    return name.lower() in _LOOPBACK_HOST_NAMES and origin_port == str(port)


_MAX_POST_BODY = 4096


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "mockymock-dashboard"
    # Every response below sets Content-Length, which is what HTTP/1.1
    # keep-alive requires; without it the browser would hang on each poll.
    protocol_version = "HTTP/1.1"

    def _port(self) -> int:
        address = self.server.server_address
        return int(address[1]) if isinstance(address, tuple) else -1

    def _reports_root(self) -> Path:
        root = getattr(self.server, "reports_root", None)
        return Path(root) if root is not None else Path.cwd()

    def _host_ok(self) -> bool:
        if host_header_allowed(self.headers.get("Host"), self._port()):
            return True
        self._send(
            HTTPStatus.MISDIRECTED_REQUEST,
            b"unexpected Host header",
            "text/plain; charset=utf-8",
        )
        return False

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's API
        if not self._host_ok():
            return
        path = unquote(urlparse(self.path).path)
        if path == "/api/status":
            self._send_json(_cached_probe())
            return
        if path == "/api/reports":
            self._send_json(reports.reports_payload(self._reports_root()))
            return
        if path == "/api/plugin":
            self._send_json(plugin.verify())
            return
        if path.startswith("/reports/"):
            report = reports.resolve_report(
                self._reports_root(), path[len("/reports/") :]
            )
            if report is None:
                self._send(
                    HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8"
                )
                return
            # The report is a self-contained page with its own inline
            # script. `sandbox allow-scripts` gives it an opaque origin, so
            # even opened in its own tab it cannot call this server's API.
            self._send(
                HTTPStatus.OK,
                report.read_bytes(),
                "text/html; charset=utf-8",
                extra_headers={"Content-Security-Policy": "sandbox allow-scripts"},
            )
            return
        target = resolve_static(path)
        if target is None:
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")
            return
        self._send(
            HTTPStatus.OK,
            target.read_bytes(),
            _CONTENT_TYPES.get(target.suffix, "application/octet-stream"),
        )

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's API
        # Read (or refuse) the body first: on a keep-alive connection an
        # unread body would be parsed as the next request.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > _MAX_POST_BODY:
            self.close_connection = True
            self._send(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                b"body too large",
                "text/plain; charset=utf-8",
            )
            return
        body = self.rfile.read(length) if length else b""
        if not self._host_ok():
            return
        if not post_allowed(
            self.headers.get("Origin"), self.headers.get("Content-Type"), self._port()
        ):
            self._send(
                HTTPStatus.FORBIDDEN,
                b"cross-site request refused",
                "text/plain; charset=utf-8",
            )
            return
        if urlparse(self.path).path != "/api/plugin/install":
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")
            return
        try:
            options = json.loads(body or b"{}")
        except ValueError:
            options = None
        if not isinstance(options, dict):
            self._send(
                HTTPStatus.BAD_REQUEST,
                b"expected a JSON object",
                "text/plain; charset=utf-8",
            )
            return
        self._send_json(plugin.install(force=options.get("force") is True))

    def _send_json(self, payload: dict[str, Any]) -> None:
        self._send(
            HTTPStatus.OK,
            json.dumps(payload).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _send(
        self,
        code: HTTPStatus,
        body: bytes,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(code)
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The whole point is live state; a cached /api/status would show a
        # daemon as up long after it went down.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Silence the default per-request stderr log -- the page polls
        every few seconds, which would otherwise scroll the terminal
        forever. The CLI prints one line when the server starts."""


def serve(
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    reports_root: Path | None = None,
) -> None:
    """Serve the dashboard on loopback until interrupted. `port=0` picks a
    free port, which is what the tests use. `reports_root` is where the
    page looks for `*.report.html` files (default: the current
    directory). Raises OSError if the port is already taken -- the CLI
    turns that into a clean message."""
    httpd = ThreadingHTTPServer((HOST, port), DashboardHandler)
    root = (reports_root or Path.cwd()).resolve()
    httpd.reports_root = root  # type: ignore[attr-defined]
    url = f"http://{HOST}:{httpd.server_address[1]}/"
    print(f"mockymock dashboard: serving {url} (Ctrl-C to stop)")
    print(f"mockymock dashboard: test reports from {root}")
    # The socket is already bound and listening, so a browser that beats
    # serve_forever() to the punch just waits in the accept backlog.
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nmockymock dashboard: stopped")
    finally:
        httpd.server_close()
