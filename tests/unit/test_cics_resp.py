"""`DFHRESP(<condition>)` expanded to its EIBRESP number, as the CICS
translator does, so a CICS program using the ordinary
`IF WS-RESP = DFHRESP(NORMAL)` idiom is no longer refused
`UNSUPPORTED_CICS_MACRO`. And macro calls inside `EXEC ... END-EXEC`, which
the splicer replaces wholesale, no longer refuse at all."""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.refusal import check_cics_eib_layout
from mockymock.cli.checks import run_static_checks
from mockymock.splicer.cics_resp import DFHRESP_VALUES, expand_dfhresp

RESP_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSRESP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP             PIC S9(8) COMP VALUE 0.
       01  WS-FLAG             PIC X VALUE SPACE.
       01  WS-TYPE             PIC S9(8) COMP VALUE 0.

       PROCEDURE DIVISION.
       2000-MAIN.
           EXEC CICS RECEIVE MAP('M1') RESP(WS-RESP)
               DATATYPE(DFHVALUE(CHAR))
           END-EXEC
           EVALUATE WS-RESP
               WHEN DFHRESP(NORMAL)
                   MOVE "N" TO WS-FLAG
               WHEN DFHRESP(MAPFAIL)
                   MOVE "M" TO WS-FLAG
           END-EVALUATE
           IF WS-RESP = DFHRESP(NOTFND) OR dfhresp ( duprec )
               MOVE "X" TO WS-FLAG
           END-IF
           DISPLAY 'DFHRESP(NORMAL)'
           GOBACK.
"""

RESP_CUT = """\
TESTSUITE "dfhresp"

TESTCASE "runs the main paragraph"
    MOCK CICS "RECEIVE"
        MOVE 36 TO WS-RESP
    END-MOCK
    PERFORM 2000-MAIN
    EXPECT WS-FLAG TO BE "M"
"""


def _lines(source: str) -> list[str]:
    return normalize_fixed_format(source.splitlines()).splitlines()


def test_values_match_ibm_eibresp_codes():
    # Spot checks against IBM's "Response codes of EXEC CICS commands".
    assert DFHRESP_VALUES["NORMAL"] == 0
    assert DFHRESP_VALUES["NOTFND"] == 13
    assert DFHRESP_VALUES["DUPREC"] == 14
    assert DFHRESP_VALUES["MAPFAIL"] == 36
    assert DFHRESP_VALUES["DSIDERR"] == DFHRESP_VALUES["FILENOTFOUND"] == 12
    assert DFHRESP_VALUES["BUSY"] == 128


def test_expand_replaces_each_call_in_place_without_moving_anything():
    lines = _lines(RESP_CBL)
    result, expansions = expand_dfhresp(list(lines))
    assert [len(line) for line in result] == [len(line) for line in lines]
    assert [(e.condition, e.value) for e in expansions] == [
        ("NORMAL", 0),
        ("MAPFAIL", 36),
        ("NOTFND", 13),
        ("DUPREC", 14),
    ]
    text = "\n".join(result)
    assert "WHEN 0 " in text
    assert "WHEN 36 " in text
    assert "IF WS-RESP = 13" in text
    assert "OR 14 " in text
    # A string literal is text, not a macro call: left untouched.
    assert "DISPLAY 'DFHRESP(NORMAL)'" in text
    # So is anything the table cannot vouch for.
    assert "DFHVALUE(CHAR)" in text


def test_an_unknown_condition_and_a_split_call_are_left_for_the_gate():
    lines = [
        "IF WS-RESP = DFHRESP(NOSUCHCOND)",
        "IF WS-RESP = DFHRESP",
        "    (NORMAL)",
    ]
    result, expansions = expand_dfhresp(list(lines))
    assert expansions == []
    assert result == lines


def test_gate_ignores_macro_calls_inside_exec_blocks():
    lines, _ = expand_dfhresp(_lines(RESP_CBL))
    program = parse_cobol(RESP_CBL, filename="CICSRESP.cbl").ast
    # Only the DFHVALUE inside EXEC CICS is left, and the splicer replaces
    # that whole block -- nothing to refuse.
    assert check_cics_eib_layout(program, lines) == []


def test_gate_still_refuses_dfhvalue_in_ordinary_cobol():
    source = RESP_CBL.replace(
        "           GOBACK.",
        "           MOVE DFHVALUE(CHAR) TO WS-TYPE\n           GOBACK.",
    )
    lines, _ = expand_dfhresp(_lines(source))
    program = parse_cobol(source, filename="CICSRESP.cbl").ast
    reasons = check_cics_eib_layout(program, lines)
    assert [r.code for r in reasons] == ["UNSUPPORTED_CICS_MACRO"]


def test_exec_inside_a_string_cannot_hide_a_later_macro():
    source = RESP_CBL.replace(
        "       2000-MAIN.\n",
        "       2000-MAIN.\n"
        "           DISPLAY 'EXEC FAILED'\n"
        "           MOVE DFHVALUE(CHAR) TO WS-TYPE\n",
    )
    lines, _ = expand_dfhresp(_lines(source))
    program = parse_cobol(source, filename="CICSRESP.cbl").ast
    reasons = check_cics_eib_layout(program, lines)
    assert [r.code for r in reasons] == ["UNSUPPORTED_CICS_MACRO"]


def test_run_static_checks_accepts_a_reachable_dfhresp(tmp_path):
    cbl = tmp_path / "CICSRESP.cbl"
    cbl.write_text(RESP_CBL)
    cut = tmp_path / "CICSRESP.cut"
    cut.write_text(RESP_CUT)
    result = run_static_checks(cbl, cut, None)
    assert result.ok, result.problems
    assert any("NORMAL=0" in note and "MAPFAIL=36" in note for note in result.notes)
    assert result.lines is not None
    assert not any(
        "DFHRESP(" in line.upper().replace(" ", "")
        for line in result.lines
        if "DISPLAY" not in line
    )
