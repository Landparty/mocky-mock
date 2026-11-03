"""A looped DL/I get-next ends on the status its loop waits for
(2026-11-03, samples IMSORDER and IMSPATIE): a qualified GN reports GE at
the end of its range, not GB, so answering the default GB never satisfied
`PERFORM UNTIL PCB-STATUS = 'GE'` and the run spun until the timeout."""

from __future__ import annotations

from tests.unit.test_bug_hunt_m1_fixes import _generate

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DLIGE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-GN          PIC X(4) VALUE 'GN  '.
       01  WS-EOF          PIC X VALUE 'N'.
           88  AT-END      VALUE 'Y'.
       01  SEG-IO          PIC X(20).
       01  SSA-QUAL        PIC X(20).
       LINKAGE SECTION.
       01  DB-PCB.
           05  PCB-DBD     PIC X(8).
           05  PCB-LEVEL   PIC XX.
           05  PCB-STATUS  PIC XX.
       PROCEDURE DIVISION USING DB-PCB.
       MAIN-PARA.
           CALL 'CBLTDLI' USING DLI-GN DB-PCB SEG-IO SSA-QUAL
           LOOP
           GOBACK.
"""

UNTIL_STATUS = """\
           PERFORM UNTIL PCB-STATUS = 'GE'
               DISPLAY SEG-IO
               CALL 'CBLTDLI' USING DLI-GN DB-PCB SEG-IO SSA-QUAL
           END-PERFORM"""

UNTIL_FLAG = """\
           PERFORM UNTIL AT-END
               IF PCB-STATUS = 'GE'
                   MOVE 'Y' TO WS-EOF
               ELSE
                   CALL 'CBLTDLI' USING DLI-GN DB-PCB SEG-IO SSA-QUAL
               END-IF
           END-PERFORM"""


def test_a_loop_on_the_status_gets_that_status(tmp_path) -> None:
    cut = _generate(tmp_path, "DLIGE", PROGRAM.replace("           LOOP", UNTIL_STATUS))
    assert 'MOVE "GE" TO DB-PCB(11:2)' in cut
    assert 'MOVE "GB" TO DB-PCB(11:2)' not in cut


def test_a_loop_on_a_flag_set_from_the_status_gets_that_status(tmp_path) -> None:
    cut = _generate(tmp_path, "DLIGE", PROGRAM.replace("           LOOP", UNTIL_FLAG))
    assert 'MOVE "GE" TO DB-PCB(11:2)' in cut
    assert 'MOVE "GB" TO DB-PCB(11:2)' not in cut


def test_a_loop_on_gb_keeps_gb(tmp_path) -> None:
    program = PROGRAM.replace("           LOOP", UNTIL_STATUS.replace("'GE'", "'GB'"))
    cut = _generate(tmp_path, "DLIGE", program)
    assert 'MOVE "GB" TO DB-PCB(11:2)' in cut
