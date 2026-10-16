"""Issue #313: a `MOCK SQL ... ROWS` reported only SQLCODE, so a cursor
loop ended by `UNTIL SQLSTATE = '02000'` never ended."""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import (
    annotate_nested_sites,
    collect_boundaries,
    collect_scope_map,
)

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 HV-NAME  PIC X(10).
       01 WS-COUNT PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL FETCH C1 INTO :HV-NAME END-EXEC
           PERFORM UNTIL SQLSTATE = '02000'
               ADD 1 TO WS-COUNT
               EXEC SQL FETCH C1 INTO :HV-NAME END-EXEC
           END-PERFORM
           GOBACK.
"""

CUT = """\
TESTSUITE "s"
TESTCASE "rows"
    MOCK SQL "FETCH C1" ROWS
        ( HV-NAME = "A" )
        ( HV-NAME = "B", SQLSTATE = "01004" )
    END-MOCK
    PERFORM MAIN-PARA
"""


def _splice(cbl: str) -> list[str]:
    result = parse_cobol(cbl, filename="SQS.cbl")
    assert result.success, result.errors
    suite = parse_cut(CUT)
    lines = normalize_fixed_format(cbl.splitlines()).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    spliced = splice_program(
        lines,
        collect_boundaries(result.ast),
        surface,
        suite,
        TallyRegistry(suite),
    )
    return [line.strip() for line in spliced]


def test_rows_report_sqlstate_when_the_program_reads_it() -> None:
    lines = _splice(PROGRAM)
    first = lines.index('MOVE "00000" TO SQLSTATE')
    # The default precedes the row's own MOVEs, so a row's SQLSTATE wins.
    second = lines.index('MOVE "00000" TO SQLSTATE', first + 1)
    assert lines.index('MOVE "01004" TO SQLSTATE') > second
    other = lines.index("WHEN OTHER", second)
    assert lines[other + 1 : other + 3] == [
        "MOVE 100 TO SQLCODE",
        'MOVE "02000" TO SQLSTATE',
    ]


def test_rows_leave_sqlstate_alone_when_the_program_never_names_it() -> None:
    lines = _splice(PROGRAM.replace("UNTIL SQLSTATE = '02000'", "UNTIL SQLCODE = 100"))
    assert 'MOVE "00000" TO SQLSTATE' not in lines
    assert 'MOVE "02000" TO SQLSTATE' not in lines
    assert "MOVE 100 TO SQLCODE" in lines
