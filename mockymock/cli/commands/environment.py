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
