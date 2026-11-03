"""A keyed READ whose loop ends only on INVALID KEY reports record not
found once its rows run out (2026-11-03, NIST IX102A): answering "00"
forever hung the run until the timeout."""

from __future__ import annotations

from tests.unit.test_bug_hunt_m1_fixes import _generate

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. KEYLOOP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IX-FILE ASSIGN TO IXFILE
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS IX-KEY.
       DATA DIVISION.
       FILE SECTION.
       FD  IX-FILE.
       01  IX-REC.
           05  IX-KEY      PIC 9(4).
           05  IX-DATA     PIC X(20).
       WORKING-STORAGE SECTION.
       01  WS-COUNT        PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       OPEN-PARA.
           OPEN INPUT IX-FILE.
       READ-PARA.
           ADD 1 TO WS-COUNT
           MOVE WS-COUNT TO IX-KEY
           READ IX-FILE
               INVALID KEY GO TO DONE-PARA.
           GO TO READ-PARA.
       DONE-PARA.
           CLOSE IX-FILE
           GOBACK.
"""


def test_the_read_after_the_rows_finds_no_record(tmp_path) -> None:
    cut = _generate(tmp_path, "KEYLOOP", PROGRAM, "--seed", "1")
    start = cut.index("MOCK READ IX-FILE")
    body = cut[start : cut.index("END-MOCK", start)]
    assert "WHEN OTHER" in body
    assert 'MOVE "23" TO UT-MOCK-STATUS' in body


def test_a_read_outside_any_loop_keeps_its_rows_alone(tmp_path) -> None:
    program = PROGRAM.replace("           GO TO READ-PARA.\n", "")
    cut = _generate(tmp_path, "KEYLOOP", program, "--seed", "1")
    assert 'MOVE "23" TO UT-MOCK-STATUS' not in cut
