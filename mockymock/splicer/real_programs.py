"""Codegen side of `USE REAL CALL`: one binary, several programs.

The entry program keeps its driver; each real program is spliced with the
same suite and compiled into the same executable
(`toolchain.compile_source(..., extra_sources=...)`). Three things make
the programs behave as one test harness:

* **Shared bookkeeping.** The dispatch a real program's boundary sites get
  reads `UT-CURRENT-CASE` and adds to the same tallies `VERIFY` reads and
  the same `UT-FAIL-COUNT` its traps add to. Those driver fields become
  `EXTERNAL` items, declared identically in every program of the binary
  (`share_driver_state`). `EXTERNAL` items take no `VALUE` clause, so the
  values move into the suite paragraph's first statements.
* **Own outcome field.** `UT-MOCK-STATUS` (the outcome a replaced
  statement's clause bodies are selected by) stays local to each program:
  shared, a real program's mocks would overwrite the caller's outcome
  while the caller's CALL is still in its dispatch.
* **Fresh state per case.** `CANCEL "X"` for every real program at the
  start of each case (`cancel_lines`, run with the WORKING-STORAGE reset),
  so a program's WORKING-STORAGE starts from its VALUE clauses in every
  case, as the entry program's does.

See docs/2026-11-01-real-call-integration-design.md.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence

from mockymock.analysis.real_programs import PreparedReal, RealSpec
from mockymock.dsl.model import MockTestSuite
from mockymock.splicer.driver import DriverArtifact
from mockymock.splicer.naming import TallyRegistry

#: The driver fields every program of the binary shares.
_SHARED_FIXED = ("UT-CURRENT-CASE", "UT-FAIL-COUNT", "UT-EARLY-EXIT")
#: Local to each real program (see the module docstring).
_LOCAL_LINES = ('01  UT-MOCK-STATUS         PIC XX VALUE "00".',)

_ITEM_RE = re.compile(
    r"^01\s+(?P<name>UT-[A-Z0-9-]+)\s+(?P<pic>PIC\s+\S+?)"
    r"(?:\s+VALUE\s+(?P<value>\"[^\"]*\"|'[^']*'|\S+?))?\s*\.$",
    re.IGNORECASE,
)


def shared_names(registry: TallyRegistry) -> set[str]:
    """Every driver field a real program's splice may reference."""
    return {*_SHARED_FIXED, *(tally for _, tally in registry.items())}


def share_driver_state(
    artifact: DriverArtifact, registry: TallyRegistry
) -> tuple[DriverArtifact, list[str]]:
    """The entry program's driver with its shared fields made EXTERNAL, and
    the WORKING-STORAGE lines each real program declares."""
    names = shared_names(registry)
    working_storage: list[str] = []
    external: list[str] = []
    initial: list[str] = []
    declared: set[str] = set()
    for line in artifact.working_storage_lines:
        match = _ITEM_RE.match(line.strip())
        if match is None or match.group("name").upper() not in names:
            working_storage.append(line)
            continue
        declaration = f"01  {match.group('name')}  {match.group('pic')} EXTERNAL."
        working_storage.append(declaration)
        external.append(declaration)
        declared.add(match.group("name").upper())
        value = match.group("value")
        if value is not None:
            initial.append(f"           MOVE {value} TO {match.group('name')}")
    missing = names - declared
    if missing:
        raise ValueError(
            f"driver fields {sorted(missing)} were not declared by build_driver "
            f"-- cannot share them with the real programs"
        )
    procedure = list(artifact.procedure_lines)
    # procedure[0] is the suite paragraph's header: its first statements
    # give the EXTERNAL items the values their VALUE clauses used to.
    procedure[1:1] = initial
    shared = dataclasses.replace(
        artifact, working_storage_lines=working_storage, procedure_lines=procedure
    )
    return shared, [*external, *_LOCAL_LINES]


def cancel_lines(specs: Sequence[RealSpec]) -> list[str]:
    """Reset lines that give every real program a fresh WORKING-STORAGE."""
    return [f'CANCEL "{spec.key}"' for spec in specs]


def instrument_real_program(
    prepared: PreparedReal,
    suite: MockTestSuite,
    registry: TallyRegistry,
    shared_working_storage: list[str],
    copybook_paths: list[str] | None,
    trace: bool = False,
    behaviour: bool = False,
) -> list[str]:
    """The real program's source as it is compiled: every boundary site
    spliced into its case dispatch, EXEC blocks of the DATA DIVISION
    transformed, and the shared driver fields declared."""
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.source_map import collect_boundaries
    from mockymock.splicer.sqlca import transform_data_division_exec

    lines = splice_program(
        list(prepared.lines),
        collect_boundaries(prepared.ast),
        prepared.surface,
        suite,
        registry,
        file_status_fields=prepared.file_status_fields,
        trace=trace,
        behaviour=behaviour,
    )
    lines, _ = transform_data_division_exec(lines, copybook_paths=copybook_paths)
    declarations = list(shared_working_storage)
    if behaviour:
        from mockymock.splicer.behaviour import LENGTH_DECLARATION

        declarations.append(LENGTH_DECLARATION)
    return insert_working_storage(lines, declarations)


_WS_HEADER_RE = re.compile(r"^\s*WORKING-STORAGE\s+SECTION\s*\.", re.IGNORECASE)
_DATA_DIVISION_RE = re.compile(r"^\s*DATA\s+DIVISION\s*\.", re.IGNORECASE)
_AFTER_WS_RE = re.compile(
    r"^\s*(LOCAL-STORAGE|LINKAGE|REPORT|SCREEN)\s+SECTION\s*\.", re.IGNORECASE
)
_PROCEDURE_RE = re.compile(r"^\s*PROCEDURE\s+DIVISION\b", re.IGNORECASE)


def insert_working_storage(lines: list[str], declarations: list[str]) -> list[str]:
    """`declarations` right after the WORKING-STORAGE SECTION header, or in
    a WORKING-STORAGE SECTION synthesized where one belongs."""
    block = [f"       {line}" for line in declarations]
    for index, line in enumerate(lines):
        if _PROCEDURE_RE.match(line):
            break
        if _WS_HEADER_RE.match(line):
            return [*lines[: index + 1], *block, *lines[index + 1 :]]
    seen_data = False
    for index, line in enumerate(lines):
        if _DATA_DIVISION_RE.match(line):
            seen_data = True
            continue
        if (seen_data and _AFTER_WS_RE.match(line)) or _PROCEDURE_RE.match(line):
            head = [] if seen_data else ["       DATA DIVISION."]
            return [
                *lines[:index],
                *head,
                "       WORKING-STORAGE SECTION.",
                *block,
                *lines[index:],
            ]
    raise ValueError("no PROCEDURE DIVISION header to place WORKING-STORAGE before")
