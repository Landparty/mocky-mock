"""Issue #262: a SORT OUTPUT PROCEDURE's RETURN ... AT END loop. The
fixture bundle has no fixtures for RELEASE / RETURN, so generate falls
back to placeholder bodies; the RETURN's must report end-of-file (the
#302 placeholder end-of-file body), and the fallback is the expected
path, not a "should not happen" key mismatch."""

from __future__ import annotations

from tests.unit.test_bug_hunt_m1_fixes import _generate

SORT_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SRT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SORT-FILE ASSIGN TO "SORTWK".
       DATA DIVISION.
       FILE SECTION.
       SD  SORT-FILE.
       01  SORT-REC.
           05 SR-KEY            PIC 9(3).
       WORKING-STORAGE SECTION.
       01  WS-I                 PIC 9(2) VALUE 0.
       01  WS-EOF               PIC X VALUE "N".
       01  WS-COUNT             PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SORT SORT-FILE ON ASCENDING KEY SR-KEY
               INPUT PROCEDURE IS LOAD-PARA
               OUTPUT PROCEDURE IS DUMP-PARA.
           DISPLAY WS-COUNT
           GOBACK.
       LOAD-PARA.
           PERFORM REL-PARA VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3.
       REL-PARA.
           MOVE WS-I TO SR-KEY
           RELEASE SORT-REC.
       DUMP-PARA.
           PERFORM RET-PARA UNTIL WS-EOF = "Y".
       RET-PARA.
           RETURN SORT-FILE
               AT END MOVE "Y" TO WS-EOF
           END-RETURN
           IF WS-EOF NOT = "Y"
               ADD 1 TO WS-COUNT
           END-IF.
"""


def test_return_placeholder_ends_the_output_procedure_loop(tmp_path) -> None:
    cut = _generate(tmp_path, "SRT", SORT_CBL, "--seed", "1")
    begin = cut.index("MOCK RETURN SORT-FILE")
    body = [
        line.strip()
        for line in cut[begin : cut.index("END-MOCK", begin)].splitlines()[1:]
    ]
    assert 'MOVE "10" TO UT-MOCK-STATUS' in body
    assert 'MOVE "Y" TO WS-EOF' in body


def test_sort_release_return_are_not_a_key_mismatch(tmp_path, capsys) -> None:
    _generate(tmp_path, "SRT", SORT_CBL, "--seed", "1")
    assert "boundary key mismatch" not in capsys.readouterr().err
