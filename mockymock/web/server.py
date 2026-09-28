"""Loopback-only HTTP server behind `mockymock dashboard`.

The page itself is static assets (plain HTML/CSS/JS, no build step); this
server exists solely because a browser cannot ask Docker anything on its
own. It serves those assets plus one read-only JSON endpoint,
`/api/status`, which the page polls.

Two deliberate constraints:

* **Loopback only.** The bind address is not configurable. The endpoint
  reports the state of *this* machine's Docker toolchain and has no
  authentication; exposing it on `0.0.0.0` would hand that out to the
  network for nothing. No CORS headers are sent either, so the browser's
  same-origin policy keeps other sites from reading it -- and a request
  whose `Host` header is not `127.0.0.1`/`localhost` is refused, which
  closes the DNS-rebinding route around that policy
  (`host_header_allowed`).
* **Read-only.** `/api/status` calls `runtime.status.probe()`, never
  `ensure_toolchain()` -- see that module's docstring for why a polling
  page must not be able to trigger image builds.

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
from urllib.parse import urlparse

from mockymock.runtime import status

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


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "mockymock-dashboard"
    # Every response below sets Content-Length, which is what HTTP/1.1
    # keep-alive requires; without it the browser would hang on each poll.
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's API
        address = self.server.server_address
        port = int(address[1]) if isinstance(address, tuple) else -1
        if not host_header_allowed(self.headers.get("Host"), port):
            self._send(
                HTTPStatus.MISDIRECTED_REQUEST,
                b"unexpected Host header",
                "text/plain; charset=utf-8",
            )
            return
        path = urlparse(self.path).path
        if path == "/api/status":
            self._send_json(_cached_probe())
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

    def _send_json(self, payload: dict[str, Any]) -> None:
        self._send(
            HTTPStatus.OK,
            json.dumps(payload).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _send(self, code: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(code)
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


def serve(port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    """Serve the dashboard on loopback until interrupted. `port=0` picks a
    free port, which is what the tests use. Raises OSError if the port is
    already taken -- the CLI turns that into a clean message."""
    httpd = ThreadingHTTPServer((HOST, port), DashboardHandler)
    url = f"http://{HOST}:{httpd.server_address[1]}/"
    print(f"mockymock dashboard: serving {url} (Ctrl-C to stop)")
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
