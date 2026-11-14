"""A called subprogram's own PROCEDURE DIVISION USING items as its test
interface (issue #275).

A subprogram reads its input from, and returns its result through, the
items its caller passes. The fixture bundle models only boundaries (CALL,
file, SQL, CICS, DLI, ACCEPT), so a scaffold for such a program used to set
no input and assert nothing. cobol-parser can now generate the parameters
itself (`ProgramFixtureGenerator(entry_parameters=True)`: a value row per
scenario, a stub per field the program writes, and branch scenarios on the
parameters). `fixture_generator` asks for that when the installed
cobol-parser supports it; `add_entry_parameters` gives an older one's
bundle the same shape for every scenario, without the branch targeting,
and tops up the stubs a newer one's misses.
"""

from __future__ import annotations

import random
import zlib
from typing import Any


def fixture_generator(rows: int | None) -> Any:
    """A `ProgramFixtureGenerator` that generates the entry parameters
    itself when the installed cobol-parser knows the keyword."""
    from cobolparser.generators.data import DataGeneratorOptions
    from cobolparser.generators.program_fixtures import ProgramFixtureGenerator

    options = DataGeneratorOptions(rows=rows) if rows is not None else None
    try:
        return ProgramFixtureGenerator(options, entry_parameters=True)
    except TypeError:
        return ProgramFixtureGenerator(options)


def add_entry_parameters(
    bundle: dict[str, Any],
    program_path: str,
    copybook_paths: list[str] | None,
) -> dict[str, Any]:
    """Give every scenario of `bundle` (a `FixtureBundle.to_dict()`) an
    `entry_parameters` fixture and a `stub` expectation per USING field the
    program writes, the shape newer cobol-parser releases emit themselves.
    A scenario that already has its fixture keeps it and only gets the
    stubs it lacks: cobol-parser's own (3.1) misses a field written only
    through its level-88s (`SET LK-NEG TO TRUE`). Best effort: a program
    the layout index or xref cannot read keeps the bundle unchanged."""
    try:
        parameters = _entry_parameter_layout(program_path, copybook_paths)
    except Exception:  # noqa: BLE001 -- older cobol-parser, unreadable layout
        return bundle
    if parameters is None:
        return bundle
    program, line, fields, outputs = parameters
    # A field under an OCCURS has one stub per occurrence (`LK-AMT(2)`):
    # a bare table element, as cobol-parser's own stubs name it, splices
    # an unsubscripted DISPLAY that does not compile (issue #474).
    tables = {spec.qualified_name for spec in fields if spec.subscripts}
    from cobolparser.generators.data import DataGeneratorOptions, ValueFactory

    seed = int(bundle.get("seed") or 0)
    for scenario in bundle.get("scenarios") or []:
        if scenario.get("entry_parameters") is not None:
            if tables:
                scenario["expectations"] = [
                    e
                    for e in scenario.get("expectations") or []
                    if not (e.get("kind") == "stub" and e.get("ref") in tables)
                ]
            stubbed = {
                e.get("ref")
                for e in scenario.get("expectations") or []
                if e.get("kind") == "stub"
            }
            scenario.setdefault("expectations", []).extend(
                _output_stub(qualified_name, program)
                for qualified_name in outputs
                if qualified_name not in stubbed
            )
            continue
        name = str(scenario.get("name") or "")
        rng = random.Random(zlib.crc32(f"{seed}:{name}:ENTRY:{program}".encode()))
        factory = ValueFactory(rng, DataGeneratorOptions())
        scenario["entry_parameters"] = {
            "category": "ENTRY",
            "key": program,
            "paragraph": scenario.get("entry"),
            "line": line,
            "direction": "BIDIRECTIONAL",
            "layout": [spec.to_dict() for spec in fields],
            "sequence": [{spec.column: factory.value_for(spec, 0) for spec in fields}],
            "terminal": None,
            "status": {},
            "provenance": "picture-random",
            "unresolved": [],
        }
        scenario.setdefault("expectations", []).extend(
            _output_stub(qualified_name, program) for qualified_name in outputs
        )
    return bundle


def _output_stub(qualified_name: str, program: str) -> dict[str, Any]:
    return {
        "kind": "stub",
        "ref": qualified_name,
        "value": None,
        "note": f"returned to the caller of {program}",
    }


def _stub_ref(spec: Any) -> str:
    """`spec`'s stub ref: its qualified name, subscripted for an
    occurrence of a table element (`LK-TAB.LK-ENT.LK-AMT(2)`)."""
    subscripts = tuple(spec.subscripts or ())
    if not subscripts:
        return str(spec.qualified_name)
    return f"{spec.qualified_name}({', '.join(str(s) for s in subscripts)})"


def _written_through_redefines(
    index: Any, names: list[str], written: set[str]
) -> set[str]:
    """Names of USING fields the program writes through a REDEFINES of them
    (cobol-parser#907): `MOVE '0000' TO LK-RC-X` with `LK-RC-X REDEFINES
    LK-RC`, or a move to `01 LK-ALIAS REDEFINES LK-TOTAL`. Each written
    item's byte range marks the elementary items of the USING record it
    overlaps; an ambiguous offset is left out."""
    from cobolparser.layout.offsets import compute_record_layout

    linkage = index.linkage_records()
    found: set[str] = set()
    for name in names:
        record = index.record_named(name)
        if record is None:
            continue
        base = str(record.name).upper()
        views = [record] + [
            other
            for other in linkage
            if other is not record and str(other.redefines or "").upper() == base
        ]
        ranges = [
            (item.byte_offset, item.byte_offset + item.byte_length)
            for view in views
            for item in compute_record_layout(view)
            if item.byte_offset is not None
            and not item.offset_ambiguous
            and item.name.upper() in written
        ]
        for item in compute_record_layout(record) if ranges else []:
            if item.is_group or item.byte_offset is None or item.offset_ambiguous:
                continue
            start, end = item.byte_offset, item.byte_offset + item.byte_length
            if any(lo < end and start < hi for lo, hi in ranges):
                found.add(item.name.upper())
    return found


def _entry_parameter_layout(
    program_path: str, copybook_paths: list[str] | None
) -> tuple[str, int | None, list[Any], list[str]] | None:
    """(PROGRAM-ID, PROCEDURE DIVISION line, the USING items' elementary
    fields, the stub refs of those the program writes -- one per occurrence
    of a table element), or None when the program takes no parameters."""
    from cobolparser.analysis.xref import XrefAnalyzer
    from cobolparser.generators.data import (
        DataGeneratorOptions,
        ProgramLayoutIndex,
        flatten_record,
    )

    index = ProgramLayoutIndex.from_file(program_path, copybook_paths=copybook_paths)
    ast = index.ast
    if ast is None:
        return None
    procedure = ast.get_division("PROCEDURE")
    if procedure is None:
        return None
    names = [
        str(n)
        for n in procedure.get_metadata("using_parameters") or []
        if str(n).upper() not in ("DFHEIBLK", "DFHCOMMAREA")
    ]
    if not names:
        return None
    fields: list[Any] = []
    seen: set[str] = set()
    for name in names:
        resolved = index.resolve(name)
        if resolved is not None:
            found = [resolved.spec]
        else:
            record = index.record_named(name)
            found = flatten_record(record, DataGeneratorOptions()) if record else []
        for spec in found:
            identity = f"{spec.qualified_name}{tuple(spec.subscripts)}"
            if identity not in seen:
                seen.add(identity)
                fields.append(spec)
    if len({spec.column for spec in fields}) != len(fields):
        # Two USING items with a same-named field: one row cannot key both.
        return None
    written = {
        entry.name.upper()
        for entry in XrefAnalyzer().analyze(ast).entries
        if entry.section == "LINKAGE"
        and any(ref.role == "write" for ref in entry.references)
    }
    # `SET LK-NEG TO TRUE` is a write of the level-88's conditional
    # variable, which xref files under the 88's own name: map it back, or
    # a return code set only through its 88s gets no stub.
    for name in list(written):
        resolved = index.resolve(name)
        if resolved is not None:
            written.add(str(resolved.spec.name).upper())
    written |= _written_through_redefines(index, names, written)
    outputs = list(
        dict.fromkeys(
            _stub_ref(spec)
            for spec in fields
            if any(part.upper() in written for part in spec.path)
        )
    )
    program = str(ast.program_name or "PROGRAM").upper()
    location = getattr(procedure, "location", None)
    return program, getattr(location, "line", None), fields, outputs
