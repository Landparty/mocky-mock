"""Issue #274: under SOURCE-COMPUTER ... WITH DEBUGGING MODE the D lines
are code -- parsed, gated and compiled like any other line."""

from mockymock.debugging_lines import (
    activate_debugging_lines,
    declares_debugging_mode,
)
from mockymock.engine.checks import run_static_checks

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DBG.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-370 WITH DEBUGGING MODE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A    PIC 9(3) VALUE 0.
       01  WS-TRC  PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           ADD 1 TO WS-A
      D    ADD 1 TO WS-TRC
           GOBACK.
"""


def test_d_lines_become_code_only_under_debugging_mode():
    active = activate_debugging_lines(PROGRAM)
    assert "           ADD 1 TO WS-TRC" in active.splitlines()
    plain = PROGRAM.replace(" WITH DEBUGGING MODE", "")
    assert activate_debugging_lines(plain) == plain
    commented = PROGRAM.replace(
        "       SOURCE-COMPUTER. IBM-370 WITH DEBUGGING MODE.",
        "      *SOURCE-COMPUTER. IBM-370 WITH DEBUGGING MODE.",
    )
    assert not declares_debugging_mode(commented)


def test_a_boundary_on_a_d_line_must_be_mocked(tmp_path):
    program = tmp_path / "DBG.cbl"
    program.write_text(
        PROGRAM.replace(
            "      D    ADD 1 TO WS-TRC", '      D    CALL "TRACER" USING WS-TRC'
        )
    )
    cut = tmp_path / "DBG.cut"
    cut.write_text(
        'TESTSUITE "dbg"\nTESTCASE "adds"\n    PERFORM 0000-MAIN\n'
        "    EXPECT WS-A TO BE 1\n"
    )
    problems = run_static_checks(program, cut, None).problems
    assert any("UNMOCKED_CALL" in p and "TRACER" in p for p in problems), problems
