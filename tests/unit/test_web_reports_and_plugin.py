"""Tests for the dashboard's test-results panel (web/reports.py) and its
cobol-testing plugin check and install (web/plugin.py), plus the HTTP
endpoints behind them. No Docker involved."""

import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from mockymock.cli.skills_cmd import SKILL_NAMES, SKILLS_ROOT
from mockymock.web import plugin, reports, server


@pytest.fixture
def home(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    return fake_home


@pytest.fixture
def report_tree(tmp_path):
    root = tmp_path / "suite"
    (root / "cobol").mkdir(parents=True)
    (root / "cobol" / "CLAIMSEG.report.html").write_text("<p>claims</p>")
    (root / "ORDERS.report.html").write_text("<p>orders</p>")
    (root / "notes.html").write_text("not a report")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "X.report.html").write_text("hidden")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "Y.report.html").write_text("dependency")
    os.utime(root / "ORDERS.report.html", (1_000_000, 1_000_000))
    return root


@pytest.fixture
def dashboard(report_tree):
    httpd = ThreadingHTTPServer((server.HOST, 0), server.DashboardHandler)
    httpd.reports_root = report_tree
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{server.HOST}:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, response.headers, response.read()


def _post(url, body=b'{"force": false}', origin=None, content_type="application/json"):
    headers = {}
    if origin is not None:
        headers["Origin"] = origin
    if content_type is not None:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read())


# --- reports -----------------------------------------------------------


def test_find_reports_lists_report_pages_newest_first(report_tree):
    found, truncated = reports.find_reports(report_tree)
    assert [r.path for r in found] == [
        "cobol/CLAIMSEG.report.html",
        "ORDERS.report.html",
    ]
    assert [r.program for r in found] == ["CLAIMSEG", "ORDERS"]
    assert truncated is False


def test_find_reports_says_when_it_stopped_early(report_tree, monkeypatch):
    monkeypatch.setattr(reports, "MAX_REPORTS", 1)
    found, truncated = reports.find_reports(report_tree)
    assert len(found) == 1
    assert truncated is True


@pytest.mark.parametrize(
    "relative",
    ["../outside.report.html", "notes.html", "missing.report.html", ".."],
)
def test_resolve_report_refuses_anything_but_a_report_under_the_root(
    report_tree, relative
):
    (report_tree.parent / "outside.report.html").write_text("outside")
    assert reports.resolve_report(report_tree, relative) is None


def test_api_reports_and_report_page(dashboard, report_tree):
    code, _, body = _get(f"{dashboard}/api/reports")
    payload = json.loads(body)
    assert code == 200
    assert payload["root"] == str(report_tree.resolve())
    assert payload["reports"][0]["path"] == "cobol/CLAIMSEG.report.html"

    code, headers, body = _get(f"{dashboard}/reports/cobol/CLAIMSEG.report.html")
    assert code == 200
    assert body == b"<p>claims</p>"
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    # The report's own script runs, but with an opaque origin.
    assert headers["Content-Security-Policy"] == "sandbox allow-scripts"


@pytest.mark.parametrize(
    "path", ["/reports/notes.html", "/reports/..%2F..%2Fetc%2Fpasswd", "/reports/"]
)
def test_report_route_serves_only_report_pages(dashboard, path):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{dashboard}{path}")
    assert excinfo.value.code == 404


# --- plugin verification -------------------------------------------------


def test_verify_reports_every_skill_missing_on_a_clean_home(home):
    result = plugin.verify()
    assert result["installed"] is False
    assert [s["name"] for s in result["skills"]] == list(SKILL_NAMES)
    assert {s["state"] for s in result["skills"]} == {plugin.MISSING}
    assert result["location"] == str(home / ".claude" / "skills")


def test_install_then_verify_is_byte_identical(home):
    result = plugin.install()
    assert result["installed"] is True
    assert result["written"] == list(SKILL_NAMES)
    for name in SKILL_NAMES:
        packaged = SKILLS_ROOT / name / "SKILL.md"
        installed = home / ".claude" / "skills" / name / "SKILL.md"
        assert installed.read_bytes() == packaged.read_bytes()


def test_an_edited_copy_is_outdated_and_left_alone_without_force(home):
    plugin.install()
    edited = home / ".claude" / "skills" / "cobol-test" / "SKILL.md"
    edited.write_text("my own edits")
    (edited.parent / "notes.txt").write_text("extra")

    check = next(s for s in plugin.verify()["skills"] if s["name"] == "cobol-test")
    assert check["state"] == plugin.OUTDATED
    assert "changed: SKILL.md" in check["differing"]
    assert "extra: notes.txt" in check["differing"]

    result = plugin.install(force=False)
    assert result["written"] == []
    assert result["skipped"][0]["name"] == "cobol-test"
    assert edited.read_text() == "my own edits"

    result = plugin.install(force=True)
    assert result["written"] == ["cobol-test"]
    assert result["installed"] is True


def test_a_file_in_place_of_a_skill_is_broken(home):
    skills = home / ".claude" / "skills"
    skills.mkdir(parents=True)
    (skills / "mockymock").write_text("not a directory")
    check = plugin.check_skill("mockymock", skills / "mockymock")
    assert check.state == plugin.BROKEN


# --- plugin endpoints ----------------------------------------------------


def test_api_plugin_and_install_round_trip(dashboard, home):
    _, _, body = _get(f"{dashboard}/api/plugin")
    assert json.loads(body)["installed"] is False

    code, result = _post(f"{dashboard}/api/plugin/install", origin=dashboard)
    assert code == 200
    assert result["installed"] is True
    assert (home / ".claude" / "skills" / "cobol-test" / "SKILL.md").is_file()


@pytest.mark.parametrize(
    ("origin", "content_type"),
    [
        (None, "application/json"),  # no Origin at all
        ("http://evil.example", "application/json"),  # another site
        ("http://127.0.0.1:1", "application/json"),  # another local port
        ("SELF", "text/plain"),  # a simple (preflight-free) cross-site POST
        ("SELF", None),
    ],
)
def test_install_refuses_requests_not_from_the_dashboard_page(
    dashboard, home, origin, content_type
):
    if origin == "SELF":
        origin = dashboard
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(
            f"{dashboard}/api/plugin/install",
            origin=origin,
            content_type=content_type,
        )
    assert excinfo.value.code == 403
    assert not (home / ".claude").exists()


def test_install_rejects_a_non_object_body(dashboard, home):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(f"{dashboard}/api/plugin/install", body=b"[1]", origin=dashboard)
    assert excinfo.value.code == 400


def test_post_to_any_other_path_is_404(dashboard, home):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(f"{dashboard}/api/status", origin=dashboard)
    assert excinfo.value.code == 404


@pytest.mark.parametrize(
    ("origin", "content_type", "allowed"),
    [
        ("http://127.0.0.1:8765", "application/json", True),
        ("http://localhost:8765", "application/json; charset=utf-8", True),
        ("https://127.0.0.1:8765", "application/json", False),
        ("http://127.0.0.1", "application/json", False),
        ("http://127.0.0.1:8765", "text/plain", False),
        ("null", "application/json", False),
        (None, "application/json", False),
    ],
)
def test_post_allowed(origin, content_type, allowed):
    assert server.post_allowed(origin, content_type, 8765) is allowed
