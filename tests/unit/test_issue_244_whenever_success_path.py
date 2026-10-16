"""Issue #244: an emulated `EXEC SQL WHENEVER ... GO TO` handler is a GO TO
target only for a test case whose SQL mocks can make the WHENEVER fire
(option B). A success-path case is no longer refused for the handler's
GOBACK, and is not asked to mock the handler's own boundaries; a case that
can fire it is still refused, naming the WHENEVER rather than a GO TO the
program never wrote."""

from __future__ import annotations

from pathlib import Path

from cobolparser import parse_cobol

from mockymock.analysis.sql_whenever import whenever_can_fire
from mockymock.cli.checks import run_static_checks
from mockymock.cli.main import main
from mockymock.dsl.model import MockCategory, MockDirective

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLW.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-BAL     PIC S9(7)V99 COMP-3 VALUE 0.
       01  WS-ID      PIC X(8) VALUE SPACES.
       01  WS-STATUS  PIC X(2) VALUE SPACES.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       PROCEDURE DIVISION.
       0000-MAIN.
           EXEC SQL WHENEVER SQLERROR GO TO 9900-SQL-ERROR END-EXEC
           PERFORM 1000-UPDATE
           EXEC SQL COMMIT END-EXEC
           GOBACK.
       1000-UPDATE.
           EXEC SQL UPDATE ACCT SET BAL = :WS-BAL
                WHERE ID = :WS-ID
           END-EXEC
           MOVE "OK" TO WS-STATUS.
       9900-SQL-ERROR.
           EXEC SQL ROLLBACK END-EXEC
           MOVE 12 TO RETURN-CODE
           GOBACK.
"""

SUCCESS = """\
TESTSUITE "w"
TESTCASE "update ok"
    MOCK SQL "UPDATE ACCT"
        MOVE 0 TO SQLCODE
    END-MOCK
    PERFORM 1000-UPDATE
    EXPECT WS-STATUS TO BE "OK"
"""

FAILURE = """\
TESTSUITE "w"
TESTCASE "update fails"
    MOCK SQL "UPDATE ACCT"
        MOVE -803 TO SQLCODE
    END-MOCK
    MOCK SQL "ROLLBACK"
        MOVE 0 TO SQLCODE
    END-MOCK
    PERFORM 1000-UPDATE
    EXPECT RETURN-CODE TO BE 12
"""


def _check(tmp_path: Path, cut: str):
    program = tmp_path / "SQLW.cbl"
    program.write_text(PROGRAM)
    cut_path = tmp_path / "SQLW.cut"
    cut_path.write_text(cut)
    return run_static_checks(program, cut_path, None)


def test_success_path_case_is_not_refused(tmp_path) -> None:
    assert _check(tmp_path, SUCCESS).problems == []


def test_a_case_that_can_fire_the_whenever_is_refused_naming_it(tmp_path) -> None:
    problems = _check(tmp_path, FAILURE).problems
    assert len(problems) == 1
    assert problems[0].startswith("refused (UNSUPPORTED_TERMINATOR_LAYOUT)")
    assert "EXEC SQL WHENEVER at line 11" in problems[0]
    assert "replace the `GO TO 9900-SQL-ERROR`" not in problems[0]


def _sql(body: list[str] | None = None, rows=None) -> MockDirective:
    return MockDirective(MockCategory.SQL, "X", body_lines=body or [], rows=rows)


def test_whenever_can_fire_is_fail_closed() -> None:
    program = parse_cobol(PROGRAM).ast
    quiet = [_sql(["MOVE 0 TO SQLCODE", "MOVE 5 TO WS-BAL"])]
    assert not whenever_can_fire(program, quiet)
    for body in (
        ["MOVE -803 TO SQLCODE"],
        [],  # SQLCODE left as it was
        ["MOVE WS-CODE TO SQLCODE"],
        ["IF WS-ID = SPACES", "MOVE 0 TO SQLCODE", "END-IF"],
        ["MOVE 0 TO SQLCODE", "ADD -1 TO SQLCODE"],
    ):
        assert whenever_can_fire(program, [_sql(body)]), body
    assert not whenever_can_fire(program, [_sql(rows=[[("WS-BAL", "1")]])])
    assert whenever_can_fire(program, [_sql(rows=[[("SQLCODE", "-911")]])])
    not_found = parse_cobol(PROGRAM.replace("SQLERROR", "NOT FOUND", 1)).ast
    assert whenever_can_fire(not_found, [_sql(rows=[[("WS-BAL", "1")]])])
    assert whenever_can_fire(not_found, [_sql(["MOVE 100 TO SQLCODE"])])


def test_generate_leaves_the_handler_out_of_a_success_path_case(tmp_path) -> None:
    for extra in ([], ["--per-paragraph"]):
        program = tmp_path / "SQLW.cbl"
        program.write_text(PROGRAM)
        out = tmp_path / "GEN.cut"
        args = ["generate", str(program), "-o", str(out), "--force", "--seed", "1"]
        assert main(args + extra) == 0
        text = out.read_text()
        assert 'MOCK SQL "UPDATE' in text
        if not extra:
            assert "ROLLBACK" not in text
        else:
            # Only the case that PERFORMs the handler itself mocks it.
            assert text.count('MOCK SQL "ROLLBACK"') == 1
        assert run_static_checks(program, out, None).problems == []
