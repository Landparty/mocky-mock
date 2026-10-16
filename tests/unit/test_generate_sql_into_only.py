"""Issue #239: a generated SELECT mock writes only its INTO host
variables (and their null indicators), never the WHERE clause's input
key the program set before the SELECT."""

from __future__ import annotations

from tests.unit.test_bug_hunt_m1_fixes import _generate

SEL_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SEL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-CUST-ID           PIC X(6).
       01  WS-NAME              PIC X(20).
       01  WS-BAL               PIC S9(7)V99 COMP-3.
       01  WS-BAL-IND           PIC S9(4) COMP.
       01  WS-LINE              PIC X(40).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "000042" TO WS-CUST-ID
           EXEC SQL
               SELECT NAME, BALANCE INTO :WS-NAME, :WS-BAL :WS-BAL-IND
                 FROM CUSTOMER WHERE CUST_ID = :WS-CUST-ID
           END-EXEC
           IF SQLCODE = 0
               STRING "CUST " WS-CUST-ID " " WS-NAME
                   DELIMITED BY SIZE INTO WS-LINE
           END-IF
           DISPLAY WS-LINE
           GOBACK.
"""


def test_select_mock_leaves_the_where_key_alone(tmp_path) -> None:
    for seed in ("1", "2"):
        cut = _generate(tmp_path, "SEL", SEL_CBL, "--seed", seed, "--force")
        begin = cut.index('MOCK SQL "SELECT"')
        body = cut[begin : cut.index("END-MOCK", begin)]
        assert " TO WS-CUST-ID" not in body
        for target in ("WS-NAME", "WS-BAL", "WS-BAL-IND"):
            assert f" TO {target}\n" in body
