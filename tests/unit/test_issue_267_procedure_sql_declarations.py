"""Issue #267: a PROCEDURE DIVISION EXEC SQL DECLARE ... CURSOR (or
INCLUDE / BEGIN-END DECLARE SECTION) is a precompiler declaration, not a
boundary: it needs no mock and is spliced to CONTINUE."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.sql_whenever import is_sql_declaration
from mockymock.cli.checks import run_static_checks

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-CNT   PIC S9(9) COMP VALUE 0.
       01  WS-MSG   PIC X(3) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL SELECT COUNT(*) INTO :WS-CNT FROM CUST END-EXEC
           EXEC SQL DECLARE C1 CURSOR FOR SELECT NAME FROM CUST
           END-EXEC
           IF SQLCODE NOT = 0
               MOVE "ERR" TO WS-MSG
           ELSE
               MOVE "OK" TO WS-MSG
           END-IF
           GOBACK.
"""

CUT = """TESTSUITE "dc"
TESTCASE "select fails"
    MOCK SQL "SELECT"
        MOVE -911 TO SQLCODE
    END-MOCK
    PERFORM MAIN-PARA
    EXPECT WS-MSG TO BE "ERR"
"""

STALE_CUT = """TESTSUITE "dc"
TESTCASE "select fails"
    MOCK SQL "SELECT"
        MOVE -911 TO SQLCODE
    END-MOCK
    MOCK SQL "DECLARE C1"
        MOVE 0 TO SQLCODE
    END-MOCK
    PERFORM MAIN-PARA
    EXPECT WS-MSG TO BE "ERR"
"""


def test_declarations_are_recognized():
    assert is_sql_declaration("DECLARE C1 CURSOR FOR SELECT NAME FROM CUST")
    assert is_sql_declaration("  begin declare section")
    assert is_sql_declaration("INCLUDE SQLCA")
    assert not is_sql_declaration("WHENEVER SQLERROR GO TO X")
    assert not is_sql_declaration("SELECT DECLARED FROM T")


def test_declare_cursor_is_not_a_boundary():
    surface = analyze(parse_cobol(PROGRAM).ast)
    texts = [site.match_text or "" for site in surface.boundary_sites]
    assert not any("DECLARE" in text for text in texts)
    assert [s.label for s in surface.whenever_sites] == ["SQL DECLARATION"]


def _problems(tmp_path, cut):
    program = tmp_path / "DC.cbl"
    program.write_text(PROGRAM)
    cut_path = tmp_path / "DC.cut"
    cut_path.write_text(cut)
    return run_static_checks(program, cut_path, None).problems


def test_unmocked_declare_lints_clean(tmp_path):
    assert _problems(tmp_path, CUT) == []


def test_a_stale_declare_mock_says_why_it_goes(tmp_path):
    problems = _problems(tmp_path, STALE_CUT)
    assert len(problems) == 1
    assert "UNMATCHED_MOCK" in problems[0]
    assert "EXEC SQL declaration" in problems[0]
