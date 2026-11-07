"""EXEC SQL reply helpers: SQLCODE status lines, INTO-layout discovery and
the cursor-loop ROWS decision."""

from __future__ import annotations

from mockymock.analysis.loops import site_in_loop
from mockymock.analysis.mock_surface import BoundarySite
from mockymock.dsl.fixture_bundle import BoundaryFixture, FieldSpec
from mockymock.dsl.generator._context import _DEFAULT_SUCCESS_CODES, ProgramContext
from mockymock.dsl.model import MockCategory


def _sql_status_lines(fixture: BoundaryFixture) -> list[str]:
    lines = [f"MOVE {code} TO {name}" for name, code in fixture.status.items()]
    if not any(name.upper() == "SQLCODE" for name in fixture.status):
        lines.append("MOVE 0 TO SQLCODE")
    return lines


def _sql_output_layout(
    fixture: BoundaryFixture, source: ProgramContext | None
) -> list[FieldSpec]:
    """`fixture.layout` restricted to the INTO host variables (and their
    null indicators) of the fixture's own SELECT / FETCH statement(s)
    (issue #239). The bundle lays out every host variable, the WHERE
    clause's input key included, so a generated SELECT mock overwrote the
    key the program had just set and `--record-expectations` recorded the
    random text as golden. Left unchanged when no statement is found or
    any of them carries no INTO list (UPDATE / INSERT / an unparsed one)."""
    surface = source.surface if source is not None else None
    if surface is None or fixture.category != "SQL":
        return list(fixture.layout)
    key = " ".join(fixture.key.upper().split())
    sql_sites = [
        site
        for site in surface.boundary_sites
        if site.category is MockCategory.SQL
        and (site.match_text or "").upper().startswith(key)
    ]
    statements = [
        site.statement for site in sql_sites if site.line == fixture.line
    ] or [site.statement for site in sql_sites]
    into: set[str] = set()
    for statement in statements:
        names = getattr(statement, "into_variables", None)
        if not isinstance(names, list) or not names:
            return list(fixture.layout)
        into |= {str(name).upper() for name in names}
    if not into:
        return list(fixture.layout)
    return [
        spec
        for spec in fixture.layout
        if set(spec.qualified_name.upper().split(".")) & into
    ]


def _is_looped_fetch(
    fixture: BoundaryFixture, site: BoundarySite, source: ProgramContext | None
) -> bool:
    """A cursor FETCH that runs inside a looping PERFORM (issue #141). Its
    mock must report SQLCODE 100 once the generated rows run out -- a
    single-row body reporting success on every call never ends the loop
    -- and it is called once more than it has rows: the exhausting call.
    Other SQL in a loop (a per-record SELECT INTO) is left alone: making
    its second call "not found" would change what the program does."""
    if source is None or not fixture.sequence:
        return False
    if not fixture.key.upper().startswith("FETCH"):
        return False
    return site_in_loop(site, source.looped)


def _sql_wants_rows(fixture: BoundaryFixture, looped_fetch: bool = False) -> bool:
    """`ROWS (...)` sugar hardcodes SQLCODE 0-on-match/100-on-exhaustion --
    not in `splicer/injector.build_rows_block` itself (generalized to a
    `row_suffix_moves`/`exhausted_moves` parameter pair so it can also
    drive `MOCK READ ... ROWS`), but at its SQL call site inside
    `splicer/injector.build_site_dispatch`, which passes the literal
    `["MOVE 0 TO SQLCODE"]`/`["MOVE 100 TO SQLCODE"]` -- it cannot express
    an error-status override, so a scenario pinning one (an "error status"
    fixed-family scenario, or a branch witness on SQLCODE) must fall back
    to a plain body with an explicit MOVE instead."""
    return (len(fixture.sequence) > 1 or looped_fetch) and all(
        code in _DEFAULT_SUCCESS_CODES for code in fixture.status.values()
    )


#: The exhausted-branch SQLCODE `splicer/injector.py`'s own
#: `build_rows_block` call site hardcodes for a `MOCK SQL ... ROWS` mock
#: (DB2's real "not found" code, `exhausted_moves=["MOVE 100 TO
#: SQLCODE"]`) -- mirrored here, not derived from any fixture data (there
#: is none once a cursor is exhausted), so a `--placeholder` downgrade of
#: a fixture that would have used ROWS sugar (`_sql_wants_rows`) replicates
#: the SAME termination signal instead of silently reverting to permanent
#: success (`_placeholder_body_for`'s ordinary `MOVE 0 TO SQLCODE`) --
#: see `_bundle_directive_for`'s own downgrade branch. A cursor
#: FETCH loop keyed on `PERFORM UNTIL SQLCODE = 100` would otherwise never
#: terminate, the SQL analogue of the READ infinite-loop hazard
#: `_read_exhaustion_lines` closes (fix round 1, unify-with-data Task 4).
_SQL_ROWS_EXHAUSTED_BODY = ["MOVE 100 TO SQLCODE"]
