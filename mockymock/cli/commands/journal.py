"""`mockymock journal`: append an entry to a suite's assistant journal."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mockymock._lines import read_utf8_source
from mockymock.cli._common import _layout


def _journal_suite(args: argparse.Namespace) -> Path | None:
    """The `.cut` whose journal `journal --cut` appends to. The journal
    goes beside the suite, and a journal written before the suite exists
    (a plan step) used to land wherever the typed path pointed, which is
    not where `generate` then put the suite (the 2026-10-25 field run's
    first entries). A program path resolves to its suite, or to the place
    `generate` would create it; a `.cut` that does not exist yet beside a
    program whose suites `generate` puts elsewhere is redirected there,
    and said so."""
    from mockymock.cli.discovery import (
        COBOL_SOURCE_EXTENSIONS,
        DiscoveryError,
        default_suite_path,
        find_suites,
    )

    given = Path(args.cut)
    layout = _layout(args)
    program: Path | None = None
    if given.suffix.lower() == ".cut":
        if given.is_file():
            return given
        program = next(
            (
                given.with_suffix(ext)
                for ext in COBOL_SOURCE_EXTENSIONS
                if given.with_suffix(ext).is_file()
            ),
            None,
        )
        if program is None:
            return given
    elif given.is_file():
        program = given
    else:
        print(f"mockymock journal: {given} does not exist; pass the suite's .cut")
        return None
    suites = find_suites(program, layout)
    if len(suites) > 1:
        listed = ", ".join(str(s) for s in suites)
        print(f"mockymock journal: {program} has several suites ({listed}); pass --cut")
        return None
    try:
        target = suites[0] if suites else default_suite_path(program, layout)
    except DiscoveryError as exc:
        print(f"mockymock journal: {exc}")
        return None
    if target.resolve() != given.resolve():
        print(
            f"mockymock journal: using the suite {target} ('mockymock report' "
            "reads the journal beside it)"
        )
    return target


def _cmd_journal(args: argparse.Namespace) -> int:
    """Append one entry to a suite's assistant journal (report/journal.py),
    which `mockymock report` shows as a timeline."""
    from mockymock.report.journal import (
        JournalError,
        append_entry,
        default_journal_path,
        entry_time,
        parse_batch,
    )

    if args.file:
        path = Path(args.file)
    elif args.cut:
        cut_path = _journal_suite(args)
        if cut_path is None:
            return 1
        path = default_journal_path(cut_path)
    else:
        print("mockymock journal: pass --cut (journal next to it) or --file")
        return 1
    single = (args.step, args.summary, args.command_text, args.decision)
    if args.from_file is not None:
        if any(value is not None for value in single):
            print(
                "mockymock journal: --from takes every entry from its input -- "
                "drop --step/--summary/--command/--decision"
            )
            return 1
        try:
            text = (
                sys.stdin.read()
                if args.from_file == "-"
                else read_utf8_source(Path(args.from_file))
            )
        except OSError as exc:
            print(f"mockymock journal: could not read {args.from_file}: {exc}")
            return 1
        try:
            entries = parse_batch(text)
            for entry in entries:
                append_entry(
                    path,
                    step=entry["step"],
                    summary=entry["summary"],
                    # --status is the default for entries without their own.
                    status=entry.get("status", args.status or "ok"),
                    command=entry.get("command"),
                    decision=entry.get("decision"),
                    now=entry_time(entry),
                )
        except JournalError as exc:
            print(f"mockymock journal: {exc}")
            return 1
        print(f"mockymock journal: appended {len(entries)} entries to {path}")
        return 0
    if args.step is None or args.summary is None:
        print("mockymock journal: pass --step and --summary, or --from FILE")
        return 1
    try:
        append_entry(
            path,
            step=args.step,
            summary=args.summary,
            status=args.status or "ok",
            command=args.command_text,
            decision=args.decision,
        )
    except JournalError as exc:
        print(f"mockymock journal: {exc}")
        return 1
    print(f"mockymock journal: appended to {path}")
    return 0
