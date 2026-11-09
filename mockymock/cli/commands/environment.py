"""`mockymock setup`, `doctor` and `dashboard`: the toolchain/status commands."""

from __future__ import annotations

import argparse
from pathlib import Path


def _cmd_setup(args: argparse.Namespace) -> int:
    from mockymock.runtime.toolchain import active as active_toolchain

    toolchain = active_toolchain()

    try:
        toolchain.ensure_toolchain(force_rebuild=args.rebuild)
        version = toolchain.cobc_version()
    except toolchain.ToolchainNotAvailableError as exc:
        print(f"mockymock setup: {exc}")
        return 1
    if toolchain.CONTAINER == "native":
        print(
            f"mockymock setup: bundled GnuCOBOL at "
            f"{toolchain.gnucobol_home()} ready ({version})"
        )
    else:
        print(f"mockymock setup: container {toolchain.CONTAINER} ready ({version})")
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    from mockymock.web import server

    port = server.DEFAULT_PORT if args.port is None else args.port
    try:
        server.serve(
            port=port,
            open_browser=not args.no_browser,
            reports_root=(
                Path(args.reports_dir).expanduser() if args.reports_dir else None
            ),
        )
    except OSError as exc:
        # Almost always "address already in use" -- a second dashboard, or
        # something else on the port. Actionable message, not a traceback.
        print(f"mockymock dashboard: could not serve on {server.HOST}:{port}: {exc}")
        return 1
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    from mockymock.cli.doctor import (
        format_doctor_json,
        format_doctor_text,
        gather_full_status,
    )

    report = gather_full_status()
    if args.json:
        import json

        print(json.dumps(format_doctor_json(report), indent=2))
    else:
        print(format_doctor_text(report))
    return 0 if report.ready else 1


def register_setup(subparsers: argparse._SubParsersAction) -> None:
    """Add `mockymock setup` to the top-level parser."""
    setup_parser = subparsers.add_parser(
        "setup",
        help="Build the GnuCOBOL image and start the mockymock-cobc container",
        description=(
            "Build the GnuCOBOL image (from this package's Dockerfile) if "
            "it isn't already built or is stale, then start the long-lived "
            "mockymock-cobc container every other command compiles and runs "
            "against. Safe to re-run: a current image/container is left "
            "alone. See 'mockymock doctor' to check readiness without "
            "building or starting anything. With MOCKYMOCK_GNUCOBOL_HOME set "
            "(a bundled GnuCOBOL tree; MOCKYMOCK_TOOLCHAIN=auto|docker|native "
            "picks the backend) nothing is built: setup checks that tree and "
            "its C compiler instead."
        ),
    )
    setup_parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force a fresh image build even if a current one is cached",
    )
    setup_parser.set_defaults(func=_cmd_setup)


def register_dashboard(subparsers: argparse._SubParsersAction) -> None:
    """Add `mockymock dashboard` to the top-level parser."""
    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help=(
            "Serve a local web page showing whether Docker and the "
            "GnuCOBOL toolchain are up (read-only; does not build or start "
            "anything), the 'mockymock report' test results found under "
            "the current directory, and whether the cobol-testing skills "
            "are installed for Claude Code and GitHub Copilot (with a button to install them)"
        ),
    )
    dashboard_parser.add_argument(
        "--port",
        type=int,
        # Resolved in _cmd_dashboard rather than here: importing
        # web.server for its DEFAULT_PORT would pull runtime.docker_toolchain
        # (and its Dockerfile read) into every `mockymock --help`, breaking
        # this module's deferred-import rule. test_cli_dashboard.py pins the
        # literal below against web.server.DEFAULT_PORT.
        default=None,
        help="Port to serve on (default 8765; 0 picks a free one)",
    )
    dashboard_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open a browser window automatically",
    )
    dashboard_parser.add_argument(
        "--reports-dir",
        default=None,
        help=(
            "Where to look for 'mockymock report' HTML pages "
            "(*.report.html; default: the current directory)"
        ),
    )
    dashboard_parser.set_defaults(func=_cmd_dashboard)


def register_doctor(subparsers: argparse._SubParsersAction) -> None:
    """Add `mockymock doctor` to the top-level parser."""
    doctor_parser = subparsers.add_parser(
        "doctor",
        help=(
            "Terminal-native readiness report (Docker/GnuCOBOL toolchain, "
            "cobol-parser, config file) -- read-only, never builds or "
            "starts anything"
        ),
        description=(
            "Reuses the same read-only probe 'mockymock dashboard' serves "
            "over HTTP, plus two checks of its own: whether cobol-parser "
            "is importable, and which project config file (if any) this "
            "invocation would load. Exits 0 when everything checked is "
            "ready, 1 otherwise. Never mutates anything -- suggests "
            "'mockymock setup', never runs it."
        ),
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output for scripting",
    )
    doctor_parser.set_defaults(func=_cmd_doctor)
