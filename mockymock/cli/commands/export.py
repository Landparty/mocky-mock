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
from mockymock.report.record_rewrite import numeric_edited_fields
from mockymock.splicer.insertion import insert_driver_with_origins


def _cmd_export(args: argparse.Namespace) -> int:
    """Write the instrumented source to a file, adjusted for a real
    fixed-format COBOL compile (e.g. z/OS) instead of GnuCOBOL-only. See
    docs/2026-08-03-mainframe-export-command-design.md. Docker-free:
    identical pre-splice pipeline to `run` (via run_static_checks),
    stopping before compile_source/run_binary."""
    from mockymock.analysis.flow_mocks import find_flow_mock_plans
    from mockymock.analysis.refusal import (
        find_goto_exit_plans,
        find_terminator_plans,
        needs_call_frame,
        program_end_thru,
    )
    from mockymock.engine.checks import (
        extra_reset_lines_for,
        extra_working_storage,
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
    from mockymock.splicer import cics_eib
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.linkage import extra_reset_lines
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.reset import reset_move_lines
    from mockymock.splicer.source_map import collect_boundaries
    from mockymock.splicer.sqlca import sqlca_reset_lines, transform_data_division_exec

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
    linkage = checked.linkage
    cics_eib_plan_ = checked.cics_eib
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

    boundaries = collect_boundaries(result.ast)
    registry = TallyRegistry(suite)
    terminator_plans, _ = find_terminator_plans(
        surface, result.ast, suite, scope_map, lines
    )
    goto_exit_plans, _ = find_goto_exit_plans(result.ast, scope_map, lines)
    flow_plans, _ = find_flow_mock_plans(result.ast, suite, lines)
    lines = splice_program(
        lines,
        boundaries,
        surface,
        suite,
        registry,
        terminator_plans,
        flow_plans,
        checked.file_status_fields,
        goto_exit_plans=goto_exit_plans,
        trace=False,
        column_offset=SEQUENCE_AREA_WIDTH,
        fallthrough_traps=checked.fallthrough_traps,
    )
    lines, _ = transform_data_division_exec(lines, copybook_paths=args.copybook_path)

    reset_lines = reset_move_lines(result.ast) + sqlca_reset_lines(lines)
    if linkage is not None:
        reset_lines = reset_lines + extra_reset_lines(linkage)
    if cics_eib_plan_ is not None:
        reset_lines = reset_lines + cics_eib.reset_lines(cics_eib_plan_)
    reset_lines = reset_lines + extra_reset_lines_for(checked)
    artifact = build_driver(
        suite,
        reset_lines,
        registry,
        extra_working_storage_lines=extra_working_storage(checked),
        snapshot=checked.snapshot,
        numeric_edited=numeric_edited_fields(result.ast, checked.captures),
        program_end=program_end_thru(result.ast, terminator_plans),
        call_frame=needs_call_frame(terminator_plans),
    )
    instrumented, driver_line_indices = insert_driver_with_origins(lines, artifact)

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
