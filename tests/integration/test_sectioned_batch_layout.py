"""End to end: the classic sectioned batch layout (sweep of 2026-10-29).
Every section's main line sits under its header, leaves early with `GO TO
NNNN-EXIT`, and an error section STOP RUNs from inside the read loop."""

from __future__ import annotations

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

SECTIONED_BATCH_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECBATCH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EOF-SW    PIC X VALUE 'N'.
           88 WS-EOF    VALUE 'Y'.
       01  WS-RC        PIC S9(4) COMP VALUE 0.
       01  WS-COUNT     PIC 9(4) VALUE 0.
       01  WS-STEP      PIC X(10) VALUE SPACES.
       PROCEDURE DIVISION.
       0000-MAINLINE SECTION.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-PROCESS UNTIL WS-EOF
           MOVE 'DONE' TO WS-STEP
           GOBACK.
       0000-EXIT.
           EXIT.
       1000-INITIALIZE SECTION.
           PERFORM 2100-READ.
       1000-EXIT.
           EXIT.
       2000-PROCESS SECTION.
           ADD 1 TO WS-COUNT
           CALL 'SUBPGM1' USING WS-RC
           IF WS-RC NOT = 0
              GO TO 2000-EXIT
           END-IF
           PERFORM 2100-READ.
       2000-EXIT.
           EXIT.
       2100-READ SECTION.
           CALL 'GETREC' USING WS-RC
           IF WS-RC = 4
              SET WS-EOF TO TRUE
           END-IF
           IF WS-RC > 4
              PERFORM 9999-ABEND
           END-IF.
       2100-EXIT.
           EXIT.
       9999-ABEND SECTION.
           MOVE 'ABEND' TO WS-STEP
           MOVE 16 TO RETURN-CODE
           STOP RUN.
       9999-EXIT.
           EXIT.
"""

SECTIONED_BATCH_CUT = """\
TESTSUITE "SECBATCH"

TESTCASE "abend inside the read loop stops the run"
    MOCK CALL "SUBPGM1"
        IF UT-SUBPGM1-TALLY = 1
            MOVE 4 TO WS-RC
        ELSE
            MOVE 0 TO WS-RC
        END-IF
    END-MOCK
    MOCK CALL "GETREC"
        IF UT-GETREC-TALLY < 3
            MOVE 0 TO WS-RC
        ELSE
            MOVE 8 TO WS-RC
        END-IF
    END-MOCK
    PERFORM 0000-MAINLINE
    EXPECT WS-STEP TO BE "ABEND"
    EXPECT WS-COUNT TO BE 3
    VERIFY CALL "GETREC" WAS CALLED 3 TIMES

TESTCASE "end of file ends the run normally"
    MOCK CALL "SUBPGM1"
        MOVE 0 TO WS-RC
    END-MOCK
    MOCK CALL "GETREC"
        IF UT-GETREC-TALLY < 3
            MOVE 0 TO WS-RC
        ELSE
            MOVE 4 TO WS-RC
        END-IF
    END-MOCK
    PERFORM 0000-MAINLINE
    EXPECT WS-STEP TO BE "DONE"
    EXPECT WS-COUNT TO BE 2
"""


@requires_docker
def test_sectioned_batch_layout_runs_and_stops_where_the_program_does(
    tmp_path: Path, capsys
):
    """Refused (UNSUPPORTED_TERMINATOR_LAYOUT) before: the first case's
    first loop iteration takes `GO TO 2000-EXIT`, the third read (in the
    third iteration) fails
    and 9999-ABEND's STOP RUN must end the run inside the UNTIL loop -- the
    loop stops there instead of iterating on, and the next case runs."""
    cbl_path = tmp_path / "SECBATCH.cbl"
    cbl_path.write_text(SECTIONED_BATCH_CBL)
    cut_path = tmp_path / "SECBATCH.cut"
    cut_path.write_text(SECTIONED_BATCH_CUT)

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "[PASS] abend inside the read loop stops the run" in out
    assert "[PASS] end of file ends the run normally" in out
