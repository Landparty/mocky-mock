"""Issues #463, #464, #467 and cobol-parser#907 (2026-11-13 sweep)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from cobolparser import parse_cobol

from mockymock.dsl.entry_parameters import _entry_parameter_layout
from mockymock.dsl.real_branches import KeyMatch, found_record_mock
from mockymock.jobstream.conditions import step_runs
from mockymock.jobstream.utilities import UtilityGap, control_statements, sort_data

DATA = b"C\nA\nD\nB\n"


@pytest.mark.parametrize(
    ("statements", "expected"),
    [
        (["  SORT FIELDS=(1,1,CH,A),SKIPREC=2"], b"B\nD\n"),
        (["  SORT FIELDS=(1,1,CH,A),STOPAFT=2"], b"A\nC\n"),
        (["  SORT FIELDS=(1,1,CH,A),SKIPREC=1,STOPAFT=2"], b"A\nD\n"),
        (["  SORT FIELDS=(1,1,CH,A)", "  OPTION SKIPREC=2"], b"B\nD\n"),
        (["  SORT FIELDS=COPY,STOPAFT=1"], b"C\n"),
        (["  OPTION COPY,SKIPREC=3"], b"B\n"),
        (["  SORT FIELDS=(1,1,CH,A),EQUALS"], b"A\nB\nC\nD\n"),
    ],
)
def test_sort_skiprec_and_stopaft(statements: list[str], expected: bytes) -> None:
    # #463: applied to the input records, before the sort.
    assert sort_data(DATA, control_statements(statements), 1) == expected


@pytest.mark.parametrize(
    "statement",
    [
        "  SORT FIELDS=(1,1,CH,A),SKIPREC=X",
        "  SORT FIELDS=(1,1,CH,A),FOO=1",
        "  MERGE FIELDS=(1,1,CH,A),SKIPREC=1",
    ],
)
def test_other_sort_operands_are_gaps(statement: str) -> None:
    with pytest.raises(UtilityGap):
        sort_data(DATA, control_statements([statement]), 1)


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("(S1.RUN = TRUE)", True),
        ("(S1.RUN NE TRUE)", False),
        ("(S1.ABEND ¬= TRUE)", True),
        ("(ABEND ¬= FALSE)", False),
        ("(ABEND = TRUE)", False),
    ],
)
def test_if_truth_value_comparisons(condition: str, expected: bool) -> None:
    # #464
    assert step_runs(condition, {"S1": 0}, False, step="S3") is expected


RATE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RATELK.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RATE-FILE ASSIGN TO RATEF.
       DATA DIVISION.
       FILE SECTION.
       FD  RATE-FILE.
       01  RATE-REC.
           05  RATE-PART     PIC X(6).
           05  RATE-TIER OCCURS 3 TIMES.
               10  RATE-AMT  PIC 9(3)V99.
           05  RATE-DESC     PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-SAVE.
           05  RATE-DESC     PIC X(10).
       LINKAGE SECTION.
       01  LK-PART           PIC X(6).
       01  LK-AMT            PIC 9(3)V99.
       PROCEDURE DIVISION USING LK-PART LK-AMT.
       MAIN-PARA.
           OPEN INPUT RATE-FILE
           READ RATE-FILE
              AT END MOVE 0 TO LK-AMT
              NOT AT END
              IF RATE-PART = LK-PART
                 MOVE RATE-AMT(1) TO LK-AMT
              END-IF
           END-READ
           CLOSE RATE-FILE
           GOBACK.
"""


def test_found_record_mock_subscripts_and_qualifies() -> None:
    # #467
    ast = parse_cobol(RATE, filename="rate.cbl").ast
    match = KeyMatch("RATELK", "RATE-FILE", "RATE-PART", "LK-PART", 27)
    lines = found_record_mock(SimpleNamespace(ast=ast), match, ["CONTINUE"])
    text = "\n".join(lines)
    assert "IF RATE-PART OF RATE-REC = LK-PART" in text
    for n in (1, 2, 3):
        assert f"TO RATE-AMT OF RATE-REC ({n})" in text
    assert "TO RATE-DESC OF RATE-REC" in text
    assert "MOVE LK-PART TO RATE-PART OF RATE-REC" in text
    assert not any(line.rstrip().endswith("TO RATE-AMT") for line in lines)


REDEFINED_RC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBR.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-AREA.
           05  LK-IN         PIC X(4).
           05  LK-RC         PIC 9(4).
           05  LK-RC-X REDEFINES LK-RC PIC X(4).
       PROCEDURE DIVISION USING LK-AREA.
       MAIN-PARA.
           IF LK-IN = 'ABCD'
              MOVE '0000' TO LK-RC-X
           END-IF
           GOBACK.
"""


def test_entry_output_written_through_redefines(tmp_path) -> None:
    # cobol-parser#907, mocky-mock's top-up half.
    program = tmp_path / "SUBR.cbl"
    program.write_text(REDEFINED_RC, encoding="utf-8")
    layout = _entry_parameter_layout(str(program), None)
    assert layout is not None
    assert layout[3] == ["LK-AREA.LK-RC"]
