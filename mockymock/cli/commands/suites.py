"""`mockymock suites`: which program each suite tests, and where a new one goes."""

from __future__ import annotations

import argparse
from pathlib import Path

from mockymock.cli._common import _layout


def _cmd_suites(args: argparse.Namespace) -> int:
    """`mockymock suites [PROGRAM] [--name NAME] [--json]`: which program
    every suite tests (and by which lookup rule), or with PROGRAM, that
    program's suites plus where a new one would go. Docker-free and
    parse-free; the VS Code extension pairs files with this rather than
    its own copy of the rules. See project/discovery.py."""
    import json

    from mockymock.project.discovery import (
        DiscoveryError,
        default_suite_path,
        find_suites,
        project_cut_files,
        resolve_program,
    )

    layout = _layout(args)
    payload: dict = {
        "version": 1,
        "root": str(layout.root),
        "testsDir": str(layout.tests_dir),
        "sourceRoot": str(layout.source_root),
    }
    if args.program is not None:
        program = Path(args.program)
        if not program.is_file():
            message = f"mockymock suites: no such file: {program}"
            print(json.dumps({**payload, "error": message}) if args.json else message)
            return 1
        suites = find_suites(program, layout)
        new_path = default_suite_path(program, layout, args.name)
        payload.update(
            program=str(program.resolve()),
            suites=[str(p.resolve()) for p in suites],
            newSuitePath=str(new_path.resolve()),
        )
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            for suite in suites:
                print(suite)
            if not suites:
                print(f"mockymock suites: {program} has no suites yet")
            print(f"mockymock suites: a new suite would go to {new_path}")
        return 0

    rows: list[dict[str, str | None]] = []
    for cut in project_cut_files(layout):
        try:
            program, rule = resolve_program(cut, layout)
            rows.append(
                {
                    "cut": str(cut.resolve()),
                    "program": str(program.resolve()),
                    "rule": rule,
                }
            )
        except DiscoveryError as exc:
            rows.append({"cut": str(cut.resolve()), "program": None, "error": str(exc)})
    payload["suites"] = rows
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for row in rows:
            if row["program"]:
                print(f"{row['cut']} -> {row['program']} ({row['rule']})")
            else:
                print(f"{row['cut']} -> ? ({row['error']})")
    return 0
