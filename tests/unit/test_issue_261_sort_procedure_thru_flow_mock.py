"""Issue #261: a MOCK PARAGRAPH inside a SORT INPUT/OUTPUT PROCEDURE ...
THRU range is refused like one inside a PERFORM ... THRU range: the
range's fall-through would run the mock body and the real body."""

from mockymock.cli.checks import run_static_checks

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SRF.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SORT-FILE ASSIGN TO "SORTWK".
       DATA DIVISION.
       FILE SECTION.
       SD  SORT-FILE.
       01  SORT-REC.
           05  SR-KEY   PIC 9.
       WORKING-STORAGE SECTION.
       01  WS-LOADS  PIC 9(3) VALUE 0.
       01  WS-COUNT  PIC 9(3) VALUE 0.
       01  WS-EOF    PIC X VALUE "N".
       PROCEDURE DIVISION.
       MAIN-PARA.
           SORT SORT-FILE ON ASCENDING KEY SR-KEY
               INPUT PROCEDURE IS LOAD-PARA THRU LOAD-EXIT
               OUTPUT PROCEDURE IS DUMP-PARA
           GOBACK.
       LOAD-PARA.
           ADD 1 TO WS-LOADS
           MOVE 9 TO SR-KEY
           RELEASE SORT-REC.
       LOAD-EXIT.
           EXIT.
       DUMP-PARA.
           PERFORM RET-PARA UNTIL WS-EOF = "Y".
       RET-PARA.
           RETURN SORT-FILE AT END MOVE "Y" TO WS-EOF END-RETURN
           IF WS-EOF NOT = "Y" ADD 1 TO WS-COUNT END-IF.
"""

CUT = """TESTSUITE "srf"
TESTCASE "mock the input procedure"
    MOCK PARAGRAPH LOAD-PARA
        ADD 100 TO WS-LOADS
    END-MOCK
    MOCK RETURN SORT-FILE ROWS
        ( SR-KEY = 5 )
        TERMINAL ( WS-EOF = "Y" )
    END-MOCK
    PERFORM MAIN-PARA
    EXPECT WS-LOADS TO BE 100
"""


def _problems(tmp_path, cut):
    program = tmp_path / "SRF.cbl"
    program.write_text(PROGRAM)
    cut_path = tmp_path / "SRF.cut"
    cut_path.write_text(cut)
    return run_static_checks(program, cut_path, None).problems


def test_mock_inside_sort_input_procedure_thru_range_is_refused(tmp_path):
    problems = _problems(tmp_path, CUT)
    assert len(problems) == 1
    assert "UNSUPPORTED_FLOW_MOCK_TARGET" in problems[0]
    assert "LOAD-PARA THRU LOAD-EXIT" in problems[0]
    assert "SORT INPUT PROCEDURE" in problems[0]


def test_mock_of_a_procedure_without_thru_is_still_allowed(tmp_path):
    cut = CUT.replace("MOCK PARAGRAPH LOAD-PARA", "MOCK PARAGRAPH RET-PARA")
    cut = cut.replace("ADD 100 TO WS-LOADS", 'MOVE "Y" TO WS-EOF').replace(
        "WS-LOADS TO BE 100", "WS-LOADS TO BE 0"
    )
    problems = _problems(tmp_path, cut)
    assert not any("UNSUPPORTED_FLOW_MOCK_TARGET" in p for p in problems)
