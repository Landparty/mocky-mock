"""`mockymock debug`: splice and compile with -g, then drive a DAP debug session."""

from __future__ import annotations

import argparse

from mockymock._lines import read_utf8_source, split_source_lines
from mockymock.cli._common import (
    _apply_config_to_args,
    _print_cics_eib_synthesis,
    _print_linkage_neutralization,
    _resolve_program_and_cut,
)
from mockymock.engine.build import BuildOptions, build_instrumented


def _cmd_debug(args: argparse.Namespace) -> int:
    """Splices and compiles exactly like `_cmd_run` (with `-g` instead of
    `--coverage`/`-ftraceall`), then instead of calling `run_binary` hands
    a `launch_session` closure to a `DapAdapter` and blocks driving the DAP
    protocol on stdio until the client disconnects. See
    docs/2026-07-22-dap-debugger-design.md and
    docs/archive/plans/2026-07-22-dap-debugger-cli.md."""

    import sys

    from mockymock.debug.adapter import DapAdapter, DebugSession
    from mockymock.debug.call_stack import ParagraphIndex, build_generated_c_line_map
    from mockymock.debug.gdb_session import GdbSession
    from mockymock.debug.line_map import LineMap
    from mockymock.debug.variable_map import (
        buffer_layouts,
        declared_data_names,
        parse_local_header,
        unavailable_names,
    )
    from mockymock.engine.checks import (
        run_static_checks,
    )
    from mockymock.report.coverage import build_original_line_map
    from mockymock.runtime.sandbox import sandbox_dir_maybe_kept
    from mockymock.runtime.toolchain import active as active_toolchain

    toolchain = active_toolchain()

    # Unlike --trace's plain-text mode, there is no useful human-facing
    # equivalent of a DAP session at a terminal -- refuse rather than
    # half-start a session a human cannot drive (see design doc's CLI
    # surface section).
    if not args.dap_stdio:
        print(
            "mockymock debug: a DAP session has no useful terminal-attached "
            "mode; drive it from the mocky-mock VS Code extension, or pass "
            "--dap-stdio to speak the protocol directly"
        )
        return 1

    pair = _resolve_program_and_cut("mockymock debug", args)
    if pair is None:
        return 1
    source_path, cut_path = pair
    _apply_config_to_args(args, source_path)

    if len(args.case or []) != 1:
        print(
            "mockymock debug: requires exactly one --case: the suite runs "
            "as a single binary and one execution stream, so a debug "
            "session cannot be attributed to more than one case"
        )
        return 1

    checked = run_static_checks(
        source_path, cut_path, args.copybook_path, case_names=args.case
    )
    if checked.real_programs:
        from mockymock.engine.checks import REAL_CALL_UNSUPPORTED

        print(f"mockymock debug: {REAL_CALL_UNSUPPORTED}")
        return 1
    for note in checked.notes:
        print(f"mockymock debug: {note}")
    if checked.linkage is not None:
        _print_linkage_neutralization(
            "debug",
            checked.linkage,
            applied=True,
            address_of=checked.linkage_address_of,
        )
    if checked.cics_eib is not None:
        _print_cics_eib_synthesis("debug", checked.cics_eib, applied=True)
    if checked.problems:
        for problem in checked.problems:
            if problem.startswith("  "):
                print(problem)
            else:
                print(f"mockymock debug: {problem}")
        return 1

    try:
        toolchain.ensure_toolchain()
    except toolchain.ToolchainNotAvailableError as exc:
        print(f"mockymock debug: {exc}")
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
    normalized_lines = list(lines)

    instrumented = build_instrumented(
        checked, BuildOptions(copybook_paths=args.copybook_path)
    ).source()

    original_lines = split_source_lines(read_utf8_source(source_path))

    # The sandbox stays alive for the entire DAP session (a long-lived
    # conversation, unlike run/trace/coverage's "compile, run, collect,
    # clean up" shape) -- it is only torn down once adapter.run() returns,
    # after the client disconnects.
    with sandbox_dir_maybe_kept(root=toolchain.WORK_ROOT, keep=False) as tmp:
        instrumented_path = tmp / source_path.with_suffix(".cbl").name
        instrumented_path.write_text(
            "\n".join(instrumented) + "\n", encoding="utf-8", newline="\n"
        )

        def launch_session(_dap_arguments: dict) -> DebugSession:
            compiled = toolchain.compile_source(instrumented_path, debug=True)
            if not compiled.success:
                raise RuntimeError(f"compile failed:\n{compiled.stderr}")
            assert compiled.binary_path is not None  # implied by compiled.success

            variable_table = parse_local_header(
                instrumented_path.with_suffix(".c.l.h").read_text(encoding="utf-8")
            )
            generated_c_lines = build_generated_c_line_map(
                instrumented_path.with_suffix(".c").read_text(encoding="utf-8")
            )
            line_map = LineMap.build(instrumented, normalized_lines, original_lines)
            paragraph_index = ParagraphIndex.build(
                result.ast,
                build_original_line_map(
                    normalized_lines, normalized_lines, original_lines
                ),
            )
            gdb = GdbSession(toolchain.start_gdb_session(compiled.binary_path))
            return DebugSession(
                gdb=gdb,
                line_map=line_map,
                variable_table=variable_table,
                generated_c_lines=generated_c_lines,
                paragraph_index=paragraph_index,
                instrumented_file=instrumented_path.name,
                original_file=str(source_path),
                buffer_layouts=buffer_layouts(result.ast),
                unavailable=tuple(
                    unavailable_names(declared_data_names(result.ast), variable_table)
                ),
            )

        adapter = DapAdapter(sys.stdin.buffer, sys.stdout.buffer, launch_session)
        adapter.run()

    return 0
