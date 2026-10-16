"""Issue #204: `.cut` data-names that the program does not declare are
refused at their `.cut` line by lint/run, not left for cobc to reject at a
line of a deleted sandbox copy."""

import json

from mockymock.analysis.cut_names import check_cut_data_names
from mockymock.cli.checks import run_static_checks
from mockymock.cli.main import main
from mockymock.dsl.parser import parse_cut

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MUT1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N           PIC 9(3) VALUE 0.
       01  WS-T.
           05 WS-EL       PIC X OCCURS 3.
       01  WS-FLAG        PIC X VALUE "N".
           88 WS-FLAG-ON  VALUE "Y".
       PROCEDURE DIVISION.
       0000-MAIN.
           ADD 1 TO WS-N
           MOVE "Y" TO WS-FLAG
           GOBACK.
"""

TYPO_CUT = """\
TESTSUITE "x"
TESTCASE "a"
    MOVE 3 TO WS-NOPE
    PERFORM 0000-MAIN
    EXPECT WS-NOPE2 TO BE 1
    EXPECT WS-FLAG TO BE Y
"""


def _write(tmp_path, cut_text):
    program = tmp_path / "MUT1.cbl"
    program.write_text(PROGRAM)
    cut = tmp_path / "MUT1.cut"
    cut.write_text(cut_text)
    return program, cut


def test_typod_names_and_bare_word_values_are_refused_at_their_cut_line(tmp_path):
    program, cut = _write(tmp_path, TYPO_CUT)
    result = run_static_checks(program, cut, None)
    unknown = [p for p in result.problems if "UNKNOWN_DATA_NAME" in p]
    assert unknown == [
        "refused (UNKNOWN_DATA_NAME): .cut line 3: MOVE target WS-NOPE is not "
        "a data item of MUT1",
        "refused (UNKNOWN_DATA_NAME): .cut line 5: EXPECT WS-NOPE2 is not a "
        "data item of MUT1",
        "refused (UNKNOWN_DATA_NAME): .cut line 6: EXPECT value Y is neither "
        "a literal nor a data item of MUT1 -- quote it if it is text",
    ]


def test_declared_subscripted_and_harness_names_are_accepted():
    suite = parse_cut("""\
TESTSUITE "x"
BEFORE-EACH
    MOVE ZERO TO WS-N
END-BEFORE
TESTCASE "a"
    MOVE "A" TO WS-EL (2)
    MOVE WS-N TO WS-EL(1)
    PERFORM 0000-MAIN
    EXPECT WS-N TO BE 1
    EXPECT WS-FLAG TO BE "Y"
    EXPECT RETURN-CODE TO BE ZERO
    EXPECT EIBRESP TO BE 0
    EXPECT UT-CAP-X TO BE SPACES
""")
    lines = PROGRAM.splitlines()
    assert check_cut_data_names(suite, lines, "MUT1") == []


def test_a_name_only_inside_a_literal_is_not_declared():
    suite = parse_cut(
        'TESTSUITE "x"\nTESTCASE "a"\n    PERFORM 0000-MAIN\n'
        "    EXPECT WS-FLAG TO BE Y\n"
    )
    reasons = check_cut_data_names(suite, PROGRAM.splitlines())
    assert [r.code for r in reasons] == ["UNKNOWN_DATA_NAME"]


def test_refused_run_json_report_keeps_cut_and_program_files(tmp_path):
    program, cut = _write(tmp_path, TYPO_CUT)
    report = tmp_path / "r.json"
    assert (
        main(["run", str(program), "--cut", str(cut), "--json-report", str(report)])
        == 1
    )
    payload = json.loads(report.read_text())
    assert payload["cutFile"] == str(cut)
    assert payload["programFile"] == str(program)
    assert payload["suite"]["line"] == 1


def test_rows_and_terminal_names_are_checked_at_their_lines():
    # Issue #299: ROWS rows and the TERMINAL group are spliced as MOVEs too.
    suite = parse_cut(
        'TESTSUITE "x"\n'
        'TESTCASE "a"\n'
        '    MOCK CALL "SVC" ROWS\n'
        "        ( WS-N = 1, WS-NX = 10 )\n"
        "        ( WS-N = 2, WS-FLAG = Q )\n"
        '        TERMINAL ( WS-EOFF = "Y" )\n'
        "    END-MOCK\n"
        "    PERFORM 0000-MAIN\n"
    )
    reasons = check_cut_data_names(suite, PROGRAM.splitlines(), "MUT1")
    assert [r.message for r in reasons] == [
        ".cut line 4: ROWS field WS-NX is not a data item of MUT1",
        ".cut line 5: ROWS value Q is neither a literal nor a data item of "
        "MUT1 -- quote it if it is text",
        ".cut line 6: TERMINAL field WS-EOFF is not a data item of MUT1",
    ]
