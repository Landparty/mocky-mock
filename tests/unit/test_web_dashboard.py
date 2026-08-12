"""Tests for the read-only status probe and the dashboard server.

Like tests/unit/test_docker_toolchain.py, everything here mocks the docker
CLI -- these must pass on a machine with no Docker installed.
"""

import json
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import pytest

from mockymock.runtime import docker_toolchain, status
from mockymock.web import server


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(["docker"], returncode, stdout, stderr)


# --- probe ------------------------------------------------------------


def test_probe_reports_ready_when_everything_is_up():
    with (
        mock.patch.object(docker_toolchain, "_docker", return_value=_completed()),
        mock.patch.object(
            docker_toolchain,
            "_inspect_container",
            return_value=(True, docker_toolchain.IMAGE),
        ),
        mock.patch.object(
            docker_toolchain, "cobc_version", return_value="cobc (GnuCOBOL) 3.2.0"
        ),
    ):
        result = status.probe()

    assert result.ready is True
    assert [check.state for check in result.checks] == [status.OK] * 4
    assert result.cobc_version == "cobc (GnuCOBOL) 3.2.0"
    assert result.container == docker_toolchain.CONTAINER


def test_probe_short_circuits_the_rest_when_the_daemon_is_down():
    """A down daemon makes every later check unanswerable, so they report
    `unknown` rather than a misleading `down`."""
    with mock.patch.object(
        docker_toolchain,
        "_docker",
        return_value=_completed(returncode=1, stderr="nope"),
    ):
        result = status.probe()

    assert result.ready is False
    states = {check.id: check.state for check in result.checks}
    assert states == {
        "daemon": status.DOWN,
        "image": status.UNKNOWN,
        "container": status.UNKNOWN,
        "cobc": status.UNKNOWN,
    }


def test_probe_survives_a_missing_docker_cli():
    with mock.patch.object(
        docker_toolchain,
        "_docker",
        side_effect=docker_toolchain.DockerNotAvailableError("no docker"),
    ):
        result = status.probe()

    assert result.ready is False
    assert result.checks[0].state == status.DOWN
    assert "no docker" in result.checks[0].detail


def test_probe_flags_a_stopped_container_as_warn_not_down():
    with (
        mock.patch.object(docker_toolchain, "_docker", return_value=_completed()),
        mock.patch.object(
            docker_toolchain,
            "_inspect_container",
            return_value=(False, docker_toolchain.IMAGE),
        ),
    ):
        result = status.probe()

    container = next(c for c in result.checks if c.id == "container")
    cobc = next(c for c in result.checks if c.id == "cobc")
    assert container.state == status.WARN
    assert "stopped" in container.detail
    # cobc can't be queried through a stopped container.
    assert cobc.state == status.UNKNOWN
    assert result.ready is False


def test_probe_flags_a_container_built_from_a_stale_image():
    with (
        mock.patch.object(docker_toolchain, "_docker", return_value=_completed()),
        mock.patch.object(
            docker_toolchain,
            "_inspect_container",
            return_value=(True, "mockymock-gnucobol:deadbeef"),
        ),
    ):
        result = status.probe()

    container = next(c for c in result.checks if c.id == "container")
    assert container.state == status.WARN
    assert "deadbeef" in container.detail
    assert result.ready is False


def test_probe_never_mutates_the_toolchain():
    """The dashboard polls every few seconds; if the probe reached for
    ensure_toolchain it would kick off image builds and container
    recreation from a page refresh."""
    calls = []

    def record(*args, **kwargs):
        calls.append(args)
        return _completed()

    with (
        mock.patch.object(docker_toolchain, "_docker", side_effect=record),
        mock.patch.object(
            docker_toolchain,
            "_inspect_container",
            return_value=(True, docker_toolchain.IMAGE),
        ),
        mock.patch.object(docker_toolchain, "cobc_version", return_value="cobc 3.2.0"),
        mock.patch.object(docker_toolchain, "ensure_toolchain") as ensure,
    ):
        status.probe()

    ensure.assert_not_called()
    mutating = {"build", "run", "rm", "start", "create", "pull"}
    assert not [args for args in calls if args and args[0] in mutating]


def test_every_probe_docker_call_is_bounded_by_probe_timeout():
    """2026-08-12 audit Finding 18: _probe_container/_probe_cobc reused
    docker_toolchain helpers whose timeout was hardcoded at 30s with no
    override, so the documented 15s PROBE_TIMEOUT ceiling only actually
    bounded two of the four checks -- one degraded-daemon poll could block
    ~90s, six times the per-check bound the module docstring promises."""
    seen_timeouts = []
    real_docker = docker_toolchain._docker

    def record(*args, timeout=None):
        seen_timeouts.append(timeout)
        if args[:2] == ("inspect", "-f"):
            return _completed(stdout=f"true {docker_toolchain.IMAGE}\n")
        if args[0] == "exec":
            return _completed(stdout="cobc (GnuCOBOL) 3.2.0\n")
        return _completed()

    del real_docker  # only the recorder runs; nothing shells out
    with mock.patch.object(docker_toolchain, "_docker", side_effect=record):
        result = status.probe()

    assert result.ready is True
    assert seen_timeouts == [status.PROBE_TIMEOUT] * 4


def test_to_dict_is_json_serializable_with_the_agreed_keys():
    payload = status.ToolchainStatus(
        ready=True,
        checked_at="2026-08-03T00:00:00+00:00",
        image="img",
        container="ctr",
        cobc_version="cobc 3.2.0",
        checks=(status.Check("daemon", "Docker daemon", status.OK, "reachable"),),
    ).to_dict()

    round_tripped = json.loads(json.dumps(payload))
    assert set(round_tripped) == {
        "ready",
        "checked_at",
        "image",
        "container",
        "cobc_version",
        "checks",
    }
    assert round_tripped["checks"][0] == {
        "id": "daemon",
        "label": "Docker daemon",
        "state": "ok",
        "detail": "reachable",
    }


# --- static asset resolution -----------------------------------------


def test_static_assets_are_bundled_under_the_package():
    """Regression guard of the same shape as the Dockerfile's: assets
    resolved via Path(__file__) must live inside mockymock/ or they don't
    ship in the wheel."""
    assert server.STATIC_DIR == Path(server.__file__).resolve().parent / "static"
    for name in ("index.html", "app.js", "style.css"):
        assert (server.STATIC_DIR / name).is_file()


def test_resolve_static_serves_index_for_root():
    assert server.resolve_static("/") == server.STATIC_DIR / "index.html"


@pytest.mark.parametrize(
    "path",
    [
        "/../pyproject.toml",
        "/../../pyproject.toml",
        "/..%2f",  # not decoded, so it is simply a missing filename
        "/nope.css",
    ],
)
def test_resolve_static_refuses_traversal_and_misses(path):
    assert server.resolve_static(path) is None


# --- server -----------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_probe_cache():
    """The probe-coalescing cache is module-global; a payload cached by
    one test must never satisfy another test's request."""
    server._probe_cache = None
    yield
    server._probe_cache = None


@pytest.fixture
def dashboard():
    """A dashboard bound to an ephemeral port, torn down after the test."""
    httpd = ThreadingHTTPServer((server.HOST, 0), server.DashboardHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{server.HOST}:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_api_status_coalesces_a_burst_of_polls_into_one_probe(dashboard):
    """2026-08-12 audit Finding 19: ThreadingHTTPServer spawns an
    unbounded thread per request and each probe shells out to docker up
    to four times; a polling page against a slow daemon piled up
    concurrent docker subprocesses. Requests inside the short TTL window
    must be served from the coalescing cache -- exactly one probe runs."""
    fake = status.ToolchainStatus(
        ready=True,
        checked_at="2026-08-03T00:00:00+00:00",
        image="img",
        container="ctr",
        cobc_version="cobc 3.2.0",
        checks=(status.Check("daemon", "Docker daemon", status.OK, "reachable"),),
    )
    with mock.patch.object(status, "probe", return_value=fake) as probe:
        for _ in range(3):
            code, _, _ = _get(f"{dashboard}/api/status")
            assert code == 200
    assert probe.call_count == 1


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, response.headers, response.read()


def test_api_status_returns_the_probe_payload(dashboard):
    fake = status.ToolchainStatus(
        ready=False,
        checked_at="2026-08-03T00:00:00+00:00",
        image="img",
        container="ctr",
        cobc_version=None,
        checks=(status.Check("daemon", "Docker daemon", status.DOWN, "not running"),),
    )
    with mock.patch.object(status, "probe", return_value=fake):
        code, headers, body = _get(f"{dashboard}/api/status")

    assert code == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    # A cached status would show a daemon as up long after it went down.
    assert headers["Cache-Control"] == "no-store"
    assert json.loads(body)["checks"][0]["detail"] == "not running"


def test_root_serves_the_page_and_assets(dashboard):
    code, headers, body = _get(f"{dashboard}/")
    assert code == 200
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert b"<title>mockymock" in body

    for name, content_type in (
        ("app.js", "text/javascript; charset=utf-8"),
        ("style.css", "text/css; charset=utf-8"),
    ):
        code, headers, _ = _get(f"{dashboard}/{name}")
        assert code == 200
        assert headers["Content-Type"] == content_type


def test_unknown_path_is_404(dashboard):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{dashboard}/secrets")
    assert excinfo.value.code == 404


def test_serve_binds_loopback_only():
    """The endpoint has no auth and reports local Docker state; the bind
    address is deliberately not user-configurable."""
    assert server.HOST == "127.0.0.1"
