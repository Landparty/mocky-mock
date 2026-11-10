"""Build one instrumented program from a checked program and `.cut` suite.

Every command that compiles or writes the instrumented program (`run`,
`debug`, `export`, `mutate`) used to spell out the same sequence here
itself: plans, splice, data-division EXEC transform, between-case resets,
driver, real-program instrumentation. One copy means a step added for
`run` reaches the debugger, the export and the mutation run too, so what
they compile is what the tests ran.

`build_instrumented` takes the `StaticCheckResult` the caller already
printed notes for and refused on (each command reports those its own
way), and returns the spliced lines plus the driver. Inserting the driver
is the caller's last step (`InstrumentedProgram.source`), because
`export` needs the inserted lines' positions too.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mockymock.splicer.insertion import insert_driver, insert_driver_with_origins

if TYPE_CHECKING:
    from mockymock.engine.checks import StaticCheckResult
    from mockymock.splicer.driver import DriverArtifact
    from mockymock.splicer.naming import TallyRegistry


@dataclass(frozen=True)
class BuildOptions:
    """What differs between the commands that build a program.

    `trace`: compile in the statement-trace instrumentation (`run --trace`).
    `behaviour`: report what every mocked boundary is sent, for baselines
    (`run --record-baseline` / `--baseline`); also compiles in the
    hex-dump helper program. `column_offset`: the columns the caller
    restored in front of every line before splicing (`export` puts the
    sequence area back), so the clause-body lift slices by the right
    column. `record_targets`: case index -> data names to record
    (`run --record-expectations`)."""

    copybook_paths: list[str] | None = None
    trace: bool = False
    behaviour: bool = False
    column_offset: int = 0
    record_targets: Mapping[int, list[str]] = field(default_factory=dict)


@dataclass
class InstrumentedProgram:
    """The program under test with its mocks spliced in, and its driver.

    `lines` is the spliced program WITHOUT the driver; `source()` inserts
    it. `extra_sources` are further COBOL sources compiled into the same
    binary as (file name, lines): instrumented `USE REAL CALL` programs
    and, for a behaviour build, the hex-dump helper. `condition_names`
    are the 88-levels a `--record-expectations` rewrite must respect."""

    lines: list[str]
    artifact: DriverArtifact
    registry: TallyRegistry
    extra_sources: list[tuple[str, list[str]]]
    condition_names: set[str]

    def source(self) -> list[str]:
        """The instrumented program: `lines` with the driver inserted."""
        return insert_driver(self.lines, self.artifact)

    def source_with_origins(self) -> tuple[list[str], set[int]]:
        """`source()`, plus the 0-based indices of the driver's lines."""
        return insert_driver_with_origins(self.lines, self.artifact)


def build_instrumented(
    checked: StaticCheckResult,
    options: BuildOptions,
    *,
    lines: list[str] | None = None,
) -> InstrumentedProgram:
    """Splice `checked`'s program for its suite and build its driver.

    `checked` must have no problems (the caller refuses first). `lines`
    replaces `checked.lines` when the caller rewrote the normalized source
    before splicing (`run`'s real-file ASSIGNs, `export`'s restored
    columns); the AST-derived plans still come from `checked`."""
    from mockymock.analysis.flow_mocks import find_flow_mock_plans
    from mockymock.analysis.refusal import (
        find_goto_exit_plans,
        find_terminator_plans,
        needs_call_frame,
        program_end_thru,
    )
    from mockymock.engine.checks import extra_reset_lines_for, extra_working_storage
    from mockymock.report.record_rewrite import condition_names as _condition_names
    from mockymock.report.record_rewrite import numeric_edited_fields
    from mockymock.splicer import cics_eib
    from mockymock.splicer.behaviour import returned_items
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.linkage import extra_reset_lines
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.reset import reset_move_lines
    from mockymock.splicer.source_map import collect_boundaries
    from mockymock.splicer.sqlca import sqlca_reset_lines, transform_data_division_exec

    result = checked.parse_result
    suite = checked.suite
    surface = checked.surface
    scope_map = checked.scope_map
    source_lines = checked.lines if lines is None else lines
    if (
        checked.problems
        or result is None
        or suite is None
        or surface is None
        or source_lines is None
        or scope_map is None
    ):
        raise ValueError("build_instrumented needs a check result with no problems")

    boundaries = collect_boundaries(result.ast)
    registry = TallyRegistry(suite)
    terminator_plans, _ = find_terminator_plans(
        surface, result.ast, suite, scope_map, source_lines
    )
    goto_exit_plans, _ = find_goto_exit_plans(result.ast, scope_map, source_lines)
    flow_plans, _ = find_flow_mock_plans(result.ast, suite, source_lines)
    spliced = splice_program(
        source_lines,
        boundaries,
        surface,
        suite,
        registry,
        terminator_plans,
        flow_plans,
        checked.file_status_fields,
        goto_exit_plans=goto_exit_plans,
        trace=options.trace,
        column_offset=options.column_offset,
        fallthrough_traps=checked.fallthrough_traps,
        behaviour=options.behaviour,
    )
    spliced, _ = transform_data_division_exec(
        spliced, copybook_paths=options.copybook_paths
    )

    reset_lines = reset_move_lines(result.ast) + sqlca_reset_lines(spliced)
    if checked.linkage is not None:
        # LINKAGE items `neutralize` folded into WORKING-STORAGE live under
        # the LINKAGE section in `result.ast` still (the transform edited
        # text, not the AST), so `reset_move_lines`'s WORKING-STORAGE walk
        # never sees them -- add their reset lines explicitly.
        reset_lines = reset_lines + extra_reset_lines(checked.linkage)
    if checked.cics_eib is not None:
        reset_lines = reset_lines + cics_eib.reset_lines(checked.cics_eib)
    # Synthesized CAPTURE targets need a between-case reset too: the suite
    # compiles to ONE binary, so without it a case that never reached its
    # CALL would assert against the previous case's captured value.
    reset_lines = reset_lines + extra_reset_lines_for(checked)
    real_programs = checked.real_programs
    if real_programs:
        from mockymock.splicer.real_programs import cancel_lines

        # Every real program starts each case from its VALUE clauses.
        reset_lines = reset_lines + cancel_lines([p.spec for p in real_programs])

    record_targets = {k: list(v) for k, v in options.record_targets.items()}
    record_conditions = _condition_names(result.ast) if record_targets else set()
    artifact = build_driver(
        suite,
        reset_lines,
        registry,
        record_targets=record_targets,
        extra_working_storage_lines=extra_working_storage(checked),
        snapshot=checked.snapshot,
        numeric_edited=numeric_edited_fields(result.ast, checked.captures),
        program_end=program_end_thru(result.ast, terminator_plans),
        call_frame=needs_call_frame(terminator_plans),
        condition_names=record_conditions,
        behaviour=options.behaviour,
        returned=returned_items(result.ast) if options.behaviour else (),
    )

    extra_sources: list[tuple[str, list[str]]] = []
    if real_programs:
        from mockymock.splicer.real_programs import (
            instrument_real_program,
            share_driver_state,
        )

        # USE REAL CALL: the programs share the driver's bookkeeping
        # (EXTERNAL items) and are compiled into the same binary.
        artifact, shared_ws = share_driver_state(artifact, registry)
        for prepared in real_programs:
            extra_sources.append(
                (
                    f"real_{prepared.program_id.upper()}.cbl",
                    instrument_real_program(
                        prepared,
                        suite,
                        registry,
                        shared_ws,
                        options.copybook_paths,
                        trace=options.trace,
                        behaviour=options.behaviour,
                    ),
                )
            )
    if options.behaviour:
        from mockymock.splicer.behaviour import HEXDUMP_PROGRAM, hexdump_program

        extra_sources.append((f"{HEXDUMP_PROGRAM.lower()}.cbl", hexdump_program()))

    return InstrumentedProgram(
        lines=spliced,
        artifact=artifact,
        registry=registry,
        extra_sources=extra_sources,
        condition_names=set(record_conditions),
    )
