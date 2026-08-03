"""Tests for `mockymock dashboard`'s CLI wiring."""

import subprocess
import sys
from unittest import mock

import pytest

from mockymock.cli.main import build_parser, main
from mockymock.web import server


def test_dashboard_defaults_to_the_servers_default_port():
    """The parser stores None and _cmd_dashboard resolves it, so nothing
    imports web.server at parser-build time (see the deferred-import test
    below)."""
    assert build_parser().parse_args(["dashboard"]).port is None

    with mock.patch.object(server, "serve") as serve:
        assert main(["dashboard"]) == 0
    serve.assert_called_once_with(port=server.DEFAULT_PORT, open_browser=True)


def test_port_help_text_matches_the_actual_default(capsys):
    """--port's help text carries the only literal copy of the port
    number; pin it against the real constant so the two can't drift."""
    with pytest.raises(SystemExit):
        main(["dashboard", "--help"])
    assert f"default {server.DEFAULT_PORT}" in capsys.readouterr().out


def test_explicit_port_and_no_browser_are_passed_through():
    with mock.patch.object(server, "serve") as serve:
        assert main(["dashboard", "--port", "0", "--no-browser"]) == 0
    serve.assert_called_once_with(port=0, open_browser=False)


def test_port_in_use_reports_cleanly_instead_of_raising(capsys):
    with mock.patch.object(server, "serve", side_effect=OSError("address in use")):
        assert main(["dashboard", "--port", "8765"]) == 1
    out = capsys.readouterr().out
    assert "could not serve on 127.0.0.1:8765" in out
    assert "address in use" in out


def test_building_the_parser_does_not_import_the_docker_toolchain():
    """`mockymock --help` must stay fast and daemon-free: every heavy
    import is deferred into a _cmd_* body. Adding `dashboard` regressed
    this once -- its port default was read from web.server at parser-build
    time, which pulls in docker_toolchain and its Dockerfile read."""
    probe = (
        "import sys; from mockymock.cli.main import build_parser; "
        "build_parser(); "
        "print('mockymock.runtime.docker_toolchain' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
