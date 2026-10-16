"""Issue #307: EXPECT TRUE/FALSE on a non-88 item, or a value on an 88,
must be refused at its .cut line rather than reaching cobc."""

from mockymock.cli.checks import run_static_checks

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FLAGP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STATUS           PIC X VALUE "N".
           88  WS-DONE         VALUE "Y".
       01  WS-COUNT            PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           ADD 1 TO WS-COUNT
           SET WS-DONE TO TRUE
           GOBACK.
"""


def _problems(tmp_path, body):
    program = tmp_path / "FLAGP.cbl"
    program.write_text(PROGRAM)
    cut = tmp_path / "FLAGP.cut"
    cut.write_text('TESTSUITE "f"\nTESTCASE "c"\n    PERFORM 0000-MAIN\n' + body)
    return run_static_checks(program, cut, None).problems


def test_truth_value_on_a_plain_item_is_refused(tmp_path):
    problems = _problems(tmp_path, "    EXPECT WS-COUNT TO BE TRUE\n")
    assert len(problems) == 1
    assert problems[0].startswith(
        "refused (CONDITION_NAME_MISMATCH): .cut line 4: EXPECT WS-COUNT"
    )


def test_value_on_a_condition_name_is_refused(tmp_path):
    problems = _problems(tmp_path, '    EXPECT WS-DONE TO BE "Y"\n')
    assert len(problems) == 1
    assert "(CONDITION_NAME_MISMATCH): .cut line 4: EXPECT WS-DONE" in problems[0]
    assert "TO BE TRUE" in problems[0]


def test_matching_kinds_pass(tmp_path):
    body = (
        "    EXPECT WS-DONE TO BE TRUE\n    EXPECT WS-DONE NOT TO BE FALSE\n"
        '    EXPECT WS-COUNT TO BE 1\n    EXPECT WS-STATUS TO BE "Y"\n'
    )
    assert _problems(tmp_path, body) == []
