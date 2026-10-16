"""Issue #230: under `SPECIAL-NAMES. DECIMAL-POINT IS COMMA.` a numeric
literal is written `1,25` and `1.25` is the literal 1 followed by a
sentence period. Every numeric literal mockymock writes -- the reset
paragraph, a scaffold's mock bodies, a recorded EXPECT golden -- must use
the comma, or the program stops compiling under test."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock._decimal import decimal_point_is_comma
from mockymock.dsl.parser import _split_top_level
from mockymock.report.record_rewrite import render_expect_value
from mockymock.splicer.reset import reset_move_lines
from tests.unit.test_bug_hunt_m1_fixes import _generate

COMMA_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DPC.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           DECIMAL-POINT IS COMMA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RATE              PIC 9V99 VALUE 1,25.
       01  WS-RATE2             PIC 9V99.
       01  WS-AMT               PIC 9(5)V99 VALUE 0.
       01  WS-OUT               PIC 9(5)V99 VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           CALL "GETRATE" USING WS-RATE2
           COMPUTE WS-OUT = WS-AMT * WS-RATE * WS-RATE2
           GOBACK.
"""
PERIOD_CBL = COMMA_CBL.replace(
    "       CONFIGURATION SECTION.\n"
    "       SPECIAL-NAMES.\n"
    "           DECIMAL-POINT IS COMMA.\n",
    "",
).replace("VALUE 1,25", "VALUE 1.25")


def _ast(source: str):
    result = parse_cobol(source, filename="DPC.cbl")
    assert result.success, result.errors
    return result.ast


def test_the_setting_is_read_from_special_names():
    assert decimal_point_is_comma(_ast(COMMA_CBL))
    assert not decimal_point_is_comma(_ast(PERIOD_CBL))


def test_reset_paragraph_restores_values_with_a_comma():
    assert "MOVE 1,25 TO WS-RATE" in reset_move_lines(_ast(COMMA_CBL))
    assert "MOVE 1.25 TO WS-RATE" in reset_move_lines(_ast(PERIOD_CBL))


def test_scaffolded_mock_body_writes_comma_literals(tmp_path):
    cut = _generate(tmp_path, "DPC", COMMA_CBL, "--seed", "1")
    move = [line.strip() for line in cut.splitlines() if "TO WS-RATE2" in line]
    assert move and "," in move[0] and "." not in move[0], move


def test_recorded_golden_uses_the_comma():
    assert render_expect_value("0058900", "9(5)V99", decimal_comma=True) == ("00589,00")
    assert render_expect_value("00589,00", None, decimal_comma=True) == "00589,00"
    assert render_expect_value("0058900", "9(5)V99") == "00589.00"


def test_a_decimal_comma_is_not_a_row_separator():
    assert [v.strip() for v in _split_top_level("100,5, 125,62", ",")] == [
        "100,5",
        "125,62",
    ]
    assert [v.strip() for v in _split_top_level("A, B", ",")] == ["A", "B"]
