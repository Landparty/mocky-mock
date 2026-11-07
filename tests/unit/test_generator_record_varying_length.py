"""Issue #214: a READ of a file whose FD says `RECORD VARYING FROM n TO m
DEPENDING ON item` stores the length of the record it read in `item`. The
generated READ mock never set it, so every generated record read as length
0 -- below the FD's minimum -- and a program checking the length took its
short-record path for all the happy-path data. Each generated row now also
moves the record's length (the layout's, clamped into the FD's range)."""

from __future__ import annotations

from tests.unit._generate import _generate

VARYING_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMP-FILE ASSIGN TO "EMP.DAT"
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  EMP-FILE
           RECORD VARYING FROM 20 TO 60 DEPENDING ON WS-LEN.
       01  EMP-REC.
           05  EMP-ID   PIC X(5).
           05  EMP-NAME PIC X(15).
           05  EMP-NOTE PIC X(40).
       WORKING-STORAGE SECTION.
       01  WS-FS    PIC XX.
       01  WS-LEN   PIC 9(4) VALUE 0.
       01  WS-EOF   PIC X VALUE "N".
       01  WS-BAD   PIC 9(3) VALUE 0.
       01  WS-OK    PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT EMP-FILE
           PERFORM 1000-READ
           PERFORM UNTIL WS-EOF = "Y"
               IF WS-LEN < 20
                   ADD 1 TO WS-BAD
               ELSE
                   ADD 1 TO WS-OK
               END-IF
               PERFORM 1000-READ
           END-PERFORM
           CLOSE EMP-FILE
           GOBACK.
       1000-READ.
           READ EMP-FILE
               AT END MOVE "Y" TO WS-EOF
           END-READ.
"""


def test_every_generated_row_sets_the_depending_on_item(tmp_path) -> None:
    cut = _generate(tmp_path, "VL", VARYING_CBL, "--seed", "1", "--rows", "3")
    assert cut.count("-TALLY = ") == 3
    assert cut.count("MOVE 60 TO WS-LEN") == 3


def test_a_fixed_length_file_gets_no_length_move(tmp_path) -> None:
    cbl = VARYING_CBL.replace(
        "           RECORD VARYING FROM 20 TO 60 DEPENDING ON WS-LEN.\n", ""
    ).replace("       FD  EMP-FILE\n", "       FD  EMP-FILE.\n")
    cut = _generate(tmp_path, "VL", cbl, "--seed", "1", "--rows", "3")
    assert "TO WS-LEN" not in cut
