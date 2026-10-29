"""Boundaries nested in another boundary's clause body (`READ ... NOT AT
END CALL "X"`, `CALL ... ON EXCEPTION WRITE ...`).

Before, both halves were refused: the inner site had no span ("splicing the
enclosing statement removes this site") and a mocked outer statement could
not lift a clause body holding another boundary (UNLIFTABLE_CLAUSE_BODY).
Now clause headers bound spans in the scope map, the inner site gets a span
of its own (opening with its clause header when it shares that line), and
the splicer splices it in place when the outer statement is left alone, or
into the outer statement's lifted clause body when the outer is mocked."""

from __future__ import annotations

from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock._lines import split_source_lines
from mockymock.analysis.clause_bodies import (
    clause_header_positions,
    clause_lift_problem,
    lift_clause_bodies,
)
from mockymock.analysis.mock_surface import analyze
from mockymock.cli.checks import run_static_checks
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import (
    annotate_nested_sites,
    collect_boundaries,
    collect_scope_map,
)

FIXTURES = Path(__file__).parents[1] / "integration" / "fixtures"
PROGRAM = (FIXTURES / "nested_clause_boundaries.cbl").read_text()
CUT = (FIXTURES / "nested_clause_boundaries.cut").read_text()

_EOFLOG_ONLY = """\
TESTSUITE "in place"
TESTCASE "eoflog alone"
    MOCK CALL "EOFLOG"
    END-MOCK
    PERFORM OTHER-PARA
"""


def _analyzed(source: str):
    program = parse_cobol(source).ast
    lines = split_source_lines(normalize_fixed_format(split_source_lines(source)))
    surface = analyze(program)
    annotate_nested_sites(surface, collect_scope_map(program, lines), lines)
    return program, lines, surface


def _site(surface, key: str):
    (site,) = [s for s in surface.boundary_sites if key in s.keys]
    return site


def _splice(source: str, cut: str) -> list[str]:
    program, lines, surface = _analyzed(source)
    suite = parse_cut(cut)
    return splice_program(
        lines, collect_boundaries(program), surface, suite, TallyRegistry(suite)
    )


def _code(lines: list[str]) -> list[str]:
    return [line for line in lines if not line.lstrip().startswith("*>")]


def test_clause_headers_are_located() -> None:
    program, lines, surface = _analyzed(PROGRAM)
    read = next(s for s in surface.boundary_sites if s.label == "READ")
    validate = _site(surface, "VALIDATE")
    assert clause_header_positions(read.statement, lines) == [
        (27, 13, "AT END"),
        (29, 13, "NOT AT END"),
    ]
    assert clause_header_positions(validate.statement, lines) == [
        (32, 21, "ON EXCEPTION")
    ]
    headers = [
        b for b in collect_scope_map(program, lines).boundaries if b.clause_header
    ]
    assert [(b.line, b.word) for b in headers] == [
        (27, "AT END"),
        (29, "NOT AT END"),
        (32, "ON EXCEPTION"),
    ]


def test_inner_sites_get_spans() -> None:
    _, _, surface = _analyzed(PROGRAM)
    eoflog, validate, write = (
        _site(surface, "EOFLOG"),
        _site(surface, "VALIDATE"),
        _site(surface, "ERR-REC"),
    )
    assert all(s.nested_in_boundary for s in (eoflog, validate, write))
    # AT END CALL "EOFLOG" ...: the span opens with the header's line and
    # stops before the next statement of the clause body.
    assert eoflog.span == (27, 27), eoflog.unspliceable_reason
    assert eoflog.span_lead is not None and eoflog.span_lead.strip() == "AT END"
    # A CALL with clause bodies of its own runs to its own END-CALL.
    assert validate.span == (31, 36), validate.unspliceable_reason
    assert validate.span_lead is None
    assert write.span == (34, 34), write.unspliceable_reason


def test_outer_statement_lifts_bodies_holding_boundaries() -> None:
    _, lines, surface = _analyzed(PROGRAM)
    read = next(s for s in surface.boundary_sites if s.label == "READ")
    assert clause_lift_problem(read.statement, lines) is None
    assert clause_lift_problem(_site(surface, "VALIDATE").statement, lines) is None


def test_all_levels_mocked_pass_the_static_checks(tmp_path) -> None:
    program = tmp_path / "NESTCLB.cbl"
    program.write_text(PROGRAM)
    cut = tmp_path / "NESTCLB.cut"
    cut.write_text(CUT)
    assert run_static_checks(program, cut, None).problems == []


def test_inner_sites_are_spliced_into_the_lifted_bodies() -> None:
    code = _code(_splice(PROGRAM, CUT))
    text = "\n".join(code)
    # Each inner site is spliced exactly once, inside the READ's dispatch.
    for tally in ("UT-EOFLOG-TALLY", "UT-VALIDATE-TALLY", "UT-WRITE-ERR-REC-TALLY"):
        assert text.count(f"ADD 1 TO {tally}") == 1, tally
    # No original inner statement survives uncommented.
    assert not any(
        'CALL "EOFLOG"' in line or 'CALL "VALIDATE"' in line for line in code
    )
    assert not any(line.strip() == "WRITE ERR-REC" for line in code)
    # Nesting: READ guard -> VALIDATE dispatch -> VALIDATE's ON EXCEPTION
    # guard -> WRITE dispatch, and the AT END header is not re-emitted.
    order = [
        text.index('WHEN UT-MOCK-STATUS(1:1) = "1"'),
        text.index("ADD 1 TO UT-EOFLOG-TALLY"),
        text.index("SET EOF TO TRUE"),
        text.index('WHEN UT-MOCK-STATUS(1:1) = "0"'),
        text.index("ADD 1 TO UT-VALIDATE-TALLY"),
        text.index('WHEN UT-MOCK-STATUS = "EX"'),
        text.index("ADD 1 TO UT-WRITE-ERR-REC-TALLY"),
        text.index("ADD 1 TO WS-ERRS"),
    ]
    assert order == sorted(order)
    assert not any(line.strip().startswith("AT END") for line in code)


def test_inner_site_is_spliced_in_place_when_the_outer_is_not_mocked(
    tmp_path,
) -> None:
    source = PROGRAM.replace(
        "           GOBACK.\n",
        "           GOBACK.\n       OTHER-PARA.\n"
        '           CALL "EOFLOG" USING WS-COUNT\n           GOBACK.\n',
    )
    code = _code(_splice(source, _EOFLOG_ONLY))
    # The READ is left alone; its AT END header stays, on a line of its own,
    # ahead of the EOFLOG dispatch, and the clause's next statement follows.
    read = next(i for i, line in enumerate(code) if line.strip() == "READ IN-FILE")
    assert code[read + 1].strip() == "AT END"
    assert "EVALUATE UT-CURRENT-CASE" in code[read + 2]
    assert sum("ADD 1 TO UT-EOFLOG-TALLY" in line for line in code) == 2
    assert any(line.strip() == "NOT AT END" for line in code)
    assert any('CALL "VALIDATE"' in line for line in code)

    program = tmp_path / "NESTCLB.cbl"
    program.write_text(source)
    cut = tmp_path / "NESTCLB.cut"
    cut.write_text(_EOFLOG_ONLY)
    assert run_static_checks(program, cut, None).problems == []


def test_unmocked_inner_site_reached_is_still_refused(tmp_path) -> None:
    program = tmp_path / "NESTCLB.cbl"
    program.write_text(PROGRAM)
    cut = tmp_path / "NESTCLB.cut"
    cut.write_text(
        CUT.replace("    MOCK WRITE ERR-REC\n    END-MOCK\n", "").replace(
            "    VERIFY WRITE ERR-REC WAS CALLED ONCE\n", ""
        )
    )
    checked = run_static_checks(program, cut, None)
    reasons = [r for rs in checked.unmocked_reasons.values() for r in rs]
    assert any("WRITE" in r.message and "line 34" in r.message for r in reasons)


def test_statement_of_its_own_kind_closed_by_its_own_terminator_is_lifted() -> None:
    # The first END-CALL closes the inner CALL, the second the outer one.
    source = PROGRAM.replace(
        "                               WRITE ERR-REC\n",
        '                               CALL "ERRLOG" USING ERR-REC\n'
        "                               END-CALL\n",
    )
    _, lines, surface = _analyzed(source)
    validate = _site(surface, "VALIDATE")
    assert clause_lift_problem(validate.statement, lines) is None
    assert validate.span is not None, validate.unspliceable_reason
    lifted = lift_clause_bodies(validate.statement, lines)
    assert lifted is not None
    body = "\n".join(lifted[0].source_lines)
    assert 'CALL "ERRLOG" USING ERR-REC' in body
    assert body.count("END-CALL") == 1


def test_statement_of_its_own_kind_without_its_own_terminator_is_not_lifted() -> None:
    # The inner CALL takes the only END-CALL, so the outer one has none.
    source = PROGRAM.replace(
        "                               WRITE ERR-REC\n",
        '                               CALL "ERRLOG" USING ERR-REC\n'
        '                                   ON EXCEPTION DISPLAY "X"\n',
    )
    _, lines, surface = _analyzed(source)
    validate = _site(surface, "VALIDATE")
    problem = clause_lift_problem(validate.statement, lines)
    assert problem is not None and "of its own kind" in problem, problem
    assert validate.span is None
    assert "of its own kind" in (validate.unspliceable_reason or "")


def test_site_in_a_clause_body_on_the_terminator_line_stays_refused() -> None:
    source = PROGRAM.replace(
        '                   AT END CALL "EOFLOG" USING WS-COUNT\n'
        "                          SET EOF TO TRUE\n",
        '                   AT END CALL "EOFLOG" USING WS-COUNT SET EOF TO TRUE\n',
    )
    _, _, surface = _analyzed(source)
    eoflog = _site(surface, "EOFLOG")
    assert eoflog.span is None
    assert "shares its start line" in (eoflog.unspliceable_reason or "")
