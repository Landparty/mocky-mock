"""`mockymock export`: a self-contained, mainframe-ready test program."""

from __future__ import annotations

import argparse
from pathlib import Path

from mockymock.cli._common import (
    _apply_config_to_args,
    _print_cics_eib_synthesis,
    _print_linkage_neutralization,
    _report_unsupported_boundaries,
    _resolve_program_and_cut,
    _write_report_file,
)
from mockymock.engine.build import BuildOptions, build_instrumented


def _cmd_export(args: argparse.Namespace) -> int:
    """Write the instrumented source to a file, adjusted for a real
    fixed-format COBOL compile (e.g. z/OS) instead of GnuCOBOL-only. See
    docs/2026-08-03-mainframe-export-command-design.md. Docker-free:
    identical pre-splice pipeline to `run` (via run_static_checks),
    stopping before compile_source/run_binary."""
    from mockymock.engine.checks import (
        run_static_checks,
    )
    from mockymock.engine.mainframe_export import (
        SEQUENCE_AREA_WIDTH,
        SourceAttribution,
        build_provenance_header,
        fit_within_columns,
        insert_provenance_header,
        restore_fixed_format_columns,
    )

    pair = _resolve_program_and_cut("mockymock export", args)
    if pair is None:
        return 1
    source_path, cut_path = pair
    _apply_config_to_args(args, source_path)

    checked = run_static_checks(
        source_path,
        cut_path,
        args.copybook_path,
        case_names=args.case,
        tag_names=args.tag,
        preserve_compiler_directives=True,
        model_rebinds=False,
    )
    if checked.real_programs:
        from mockymock.engine.checks import REAL_CALL_UNSUPPORTED

        print(f"mockymock export: {REAL_CALL_UNSUPPORTED}")
        return 1
    for note in checked.notes:
        print(f"mockymock export: {note}")
    if checked.unmodelled_rebinds:
        print(
            f"mockymock export: warning: `SET ADDRESS OF` on "
            f"{', '.join(checked.unmodelled_rebinds)} is not modelled in the "
            f"export -- `run` keeps it as a real rebind with BASED, which IBM "
            f"Enterprise COBOL does not have, so the export redirects it to a "
            f"scratch pointer instead and a case relying on the rebind may "
            f"fail there"
        )
    if checked.linkage is not None:
        _print_linkage_neutralization(
            "export",
            checked.linkage,
            applied=True,
            address_of=checked.linkage_address_of,
        )
    if checked.cics_eib is not None:
        _print_cics_eib_synthesis("export", checked.cics_eib, applied=True)
    if checked.problems:
        for problem in checked.problems:
            if problem.startswith("  "):
                print(problem)
            else:
                print(f"mockymock export: {problem}")
        return 1

    result = checked.parse_result
    suite = checked.suite
    surface = checked.surface
    lines = checked.lines
    scope_map = checked.scope_map
    assert (
        result is not None
        and suite is not None
        and surface is not None
        and lines is not None
        and scope_map is not None
    )  # implied by checked.problems being empty

    # Restore the 7 columns normalize_fixed_format stripped BEFORE
    # splicing: collect_boundaries/splice_program are line-granular, so
    # this uniform prefix is transparent to them and matches the column
    # convention splicer-generated lines already assume -- except the
    # clause-body lift, which slices by AST column and is told the shift
    # (`column_offset`, issue #325: without it every mocked statement's
    # AT END / NOT AT END / INVALID KEY / ON EXCEPTION body was dropped).
    lines = restore_fixed_format_columns(lines)

    built = build_instrumented(
        checked,
        BuildOptions(
            copybook_paths=args.copybook_path, column_offset=SEQUENCE_AREA_WIDTH
        ),
        lines=lines,
    )
    instrumented, driver_line_indices = built.source_with_origins()

    instrumented, overflow_problems = fit_within_columns(
        instrumented,
        attribution=SourceAttribution(
            driver_line_indices=driver_line_indices,
            cut_path=str(cut_path),
            cut_text=cut_path.read_text(encoding="utf-8", errors="replace"),
            program_path=str(source_path),
            program_text=source_path.read_text(encoding="utf-8", errors="replace"),
        ),
    )
    if overflow_problems:
        for problem in overflow_problems:
            print(f"mockymock export: refused (COLUMN_OVERFLOW): {problem}")
        return 1

    header = build_provenance_header(
        str(source_path), str(cut_path), checked.unmodelled_rebinds
    )
    instrumented = insert_provenance_header(instrumented, header)

    output_path = (
        Path(args.output) if args.output else source_path.with_suffix(".mainframe.cbl")
    )
    if not _write_report_file(
        "export", "--output", str(output_path), "\n".join(instrumented) + "\n"
    ):
        return 1

    print(
        f"mockymock export: wrote mainframe-compilable source "
        f"({len(suite.test_cases)} test case(s)) -> {output_path}"
    )
    _report_unsupported_boundaries(surface, "export", checked.source_location_map)
    return 0
