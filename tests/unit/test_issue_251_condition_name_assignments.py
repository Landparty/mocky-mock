"""Issue #251: a .cut MOVE / ROWS / TERMINAL assigning TRUE or FALSE to a
level-88 condition-name splices as SET <88> TO TRUE|FALSE (COBOL cannot
MOVE to an 88), and lint refuses the forms cobc would reject."""

from mockymock.cli.checks import run_static_checks
from mockymock.dsl.model import HookStep
from mockymock.splicer.driver import _step_lines
from mockymock.splicer.injector import build_rows_block
from mockymock.splicer.naming import assign

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T8.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC              PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-FLAG   PIC X VALUE "N".
           88  FLAG-ON  VALUE "Y" WHEN SET TO FALSE "N".
       01  WS-EOF    PIC X VALUE "N".
           88  EOF-YES  VALUE "Y".
       01  WS-COUNT  PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           PERFORM UNTIL EOF-YES
               READ IN-FILE
                   AT END CONTINUE
                   NOT AT END ADD 1 TO WS-COUNT
               END-READ
           END-PERFORM
           CLOSE IN-FILE
           GOBACK.
"""

READ_MOCK = (
    "    MOCK OPEN IN-FILE\n    END-MOCK\n    MOCK CLOSE IN-FILE\n    END-MOCK\n"
    '    MOCK READ IN-FILE ROWS\n        ( IN-REC = "A" )\n'
    "        TERMINAL ( {terminal} )\n    END-MOCK\n"
)


def _problems(tmp_path, setup, terminal="EOF-YES = TRUE"):
    program = tmp_path / "T8.cbl"
    program.write_text(PROGRAM)
    cut = tmp_path / "T8.cut"
    cut.write_text(
        'TESTSUITE "t8"\nTESTCASE "c"\n'
        + setup
        + READ_MOCK.format(terminal=terminal)
        + "    PERFORM MAIN-PARA\n    EXPECT WS-COUNT TO BE 1\n"
    )
    return run_static_checks(program, cut, None).problems


def test_truth_assignments_splice_as_set():
    assert assign("TRUE", "FLAG-ON") == "SET FLAG-ON TO TRUE"
    assert assign(" false ", "FLAG-ON") == "SET FLAG-ON TO FALSE"
    assert assign('"Y"', "WS-FLAG") == 'MOVE "Y" TO WS-FLAG'
    hook = HookStep(kind="MOVE", target="FLAG-ON", value="TRUE", line=3)
    assert _step_lines([hook]) == ["           SET FLAG-ON TO TRUE"]
    block = build_rows_block(
        "UT-T",
        [[("EOF-YES", "TRUE")]],
        row_suffix_moves=[],
        exhausted_moves=[],
    )
    assert "        SET EOF-YES TO TRUE" in block


def test_valid_condition_name_assignments_pass_lint(tmp_path):
    assert _problems(tmp_path, "    MOVE TRUE TO FLAG-ON\n") == []
    assert _problems(tmp_path, "    MOVE FALSE TO FLAG-ON\n") == []


def test_value_moved_to_a_condition_name_is_refused(tmp_path):
    problems = _problems(tmp_path, '    MOVE "Y" TO FLAG-ON\n')
    assert len(problems) == 1
    assert problems[0].startswith(
        'refused (CONDITION_NAME_MISMATCH): .cut line 3: MOVE "Y" TO FLAG-ON'
    )


def test_truth_moved_to_a_plain_item_is_refused(tmp_path):
    problems = _problems(tmp_path, "    MOVE TRUE TO WS-FLAG\n")
    assert len(problems) == 1
    assert ".cut line 3: MOVE TRUE TO WS-FLAG" in problems[0]


def test_false_without_when_set_to_false_is_refused(tmp_path):
    problems = _problems(tmp_path, "", terminal="EOF-YES = FALSE")
    assert len(problems) == 1
    assert "(CONDITION_NAME_MISMATCH): .cut line 9: TERMINAL EOF-YES = FALSE" in (
        problems[0]
    )
    assert "WHEN SET TO FALSE" in problems[0]
