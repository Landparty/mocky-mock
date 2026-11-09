"""Issue #268 (option 1, emulate): EXEC CICS HANDLE/IGNORE CONDITION is a
label registration, not a boundary. It is spliced to CONTINUE, a MOCK CICS
body may raise a condition with CONDITION IS <name>, and the dispatch then
jumps to the label in force."""

import pytest
from cobolparser import parse_cobol

from mockymock.analysis.cics_handle import resolve_condition
from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.parser import CutParseError, parse_cut
from mockymock.engine.checks import run_static_checks
from mockymock.splicer.injector import build_site_dispatch
from mockymock.splicer.naming import TallyRegistry

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MSG PIC X(10).
       01  WS-REC PIC X(10).
       01  WS-KEY PIC X(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS HANDLE CONDITION NOTFND(NOT-FOUND-PARA) END-EXEC
           EXEC CICS READ FILE('CUSTF') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC
           MOVE "FOUND" TO WS-MSG
           GO TO MAIN-EXIT.
       NOT-FOUND-PARA.
           MOVE "NOT FOUND" TO WS-MSG.
       MAIN-EXIT.
           EXIT.
"""

CUT = """\
TESTSUITE "hc"
TESTCASE "not found"
    MOCK CICS "READ"
        CONDITION IS NOTFND
    END-MOCK
    PERFORM MAIN-PARA THRU MAIN-EXIT
    EXPECT WS-MSG TO BE "NOT FOUND"
TESTCASE "found"
    MOCK CICS "READ"
        MOVE "ROW" TO WS-REC
    END-MOCK
    PERFORM MAIN-PARA THRU MAIN-EXIT
    EXPECT WS-MSG TO BE "FOUND"
"""


def _problems(tmp_path, cut, program=PROGRAM):
    cbl = tmp_path / "HC.cbl"
    cbl.write_text(program)
    cut_path = tmp_path / "HC.cut"
    cut_path.write_text(cut)
    return run_static_checks(cbl, cut_path, None).problems


def _read_site(program):
    return next(s for s in analyze(program).boundary_sites if s.label == "CICS")


def test_handle_is_not_a_boundary_and_the_suite_lints_clean(tmp_path):
    surface = analyze(parse_cobol(PROGRAM).ast)
    assert [s.label for s in surface.whenever_sites] == ["CICS HANDLE"]
    assert [s.label for s in surface.boundary_sites] == ["CICS"]
    assert _problems(tmp_path, CUT) == []


def test_a_raised_condition_jumps_to_its_handler_label():
    suite = parse_cut(CUT)
    site = _read_site(parse_cobol(PROGRAM).ast)
    text = "\n".join(build_site_dispatch(site, suite, TallyRegistry(suite)))
    assert "GO TO NOT-FOUND-PARA" in text
    # Only the case that raises the condition jumps.
    assert text.count("GO TO") == 1


def test_condition_without_handler_is_refused(tmp_path):
    problems = _problems(
        tmp_path, CUT.replace("CONDITION IS NOTFND", "CONDITION IS DUPREC")
    )
    assert len(problems) == 1
    assert "UNSUPPORTED_CICS_CONDITION" in problems[0]
    assert "DUPREC" in problems[0]


def test_error_label_catches_other_conditions_and_ignore_does_nothing():
    source = PROGRAM.replace(
        "           EXEC CICS HANDLE CONDITION NOTFND(NOT-FOUND-PARA) END-EXEC\n",
        "           EXEC CICS IGNORE CONDITION LENGERR END-EXEC\n"
        "           EXEC CICS HANDLE CONDITION ERROR(NOT-FOUND-PARA) DUPREC\n"
        "           END-EXEC\n",
    )
    program = parse_cobol(source).ast
    read = _read_site(program).statement
    assert resolve_condition(program, read, "NOTFND") == ("NOT-FOUND-PARA", None)
    assert resolve_condition(program, read, "LENGERR") == (None, None)
    label, problem = resolve_condition(program, read, "DUPREC")
    assert label is None and "system default" in problem


def test_resp_command_refuses_a_raised_condition(tmp_path):
    program = PROGRAM.replace(
        '           END-EXEC\n           MOVE "FOUND"',
        '                RESP(WS-KEY) END-EXEC\n           MOVE "FOUND"',
    )
    assert "RESP(WS-KEY)" in program
    problems = _problems(tmp_path, CUT, program)
    assert any("RESP/NOHANDLE" in p for p in problems), problems


def test_handler_boundaries_must_be_mocked_when_a_condition_reaches_them(
    tmp_path,
):
    program = PROGRAM.replace(
        '           MOVE "NOT FOUND" TO WS-MSG.\n',
        '           MOVE "NOT FOUND" TO WS-MSG\n           CALL "LOGNF".\n',
    )
    cut = CUT.replace("PERFORM MAIN-PARA THRU MAIN-EXIT", "PERFORM MAIN-PARA")
    problems = [p for p in _problems(tmp_path, cut, program) if p.startswith("refused")]
    # Only the case raising NOTFND reaches NOT-FOUND-PARA.
    assert len(problems) == 1, problems
    assert "UNMOCKED_CALL" in problems[0] and "LOGNF" in problems[0]


def test_stale_handle_mock_says_why_it_goes(tmp_path):
    cut = CUT.replace(
        '    MOCK CICS "READ"\n        CONDITION IS NOTFND\n',
        '    MOCK CICS "HANDLE"\n    END-MOCK\n'
        '    MOCK CICS "READ"\n        CONDITION IS NOTFND\n',
    )
    problems = _problems(tmp_path, cut)
    assert any("UNMATCHED_MOCK" in p and "HANDLE" in p for p in problems)


def test_condition_is_only_in_a_mock_cics_body():
    with pytest.raises(CutParseError, match="only supported in a MOCK CICS"):
        parse_cut(CUT.replace('MOCK CICS "READ"', 'MOCK CALL "READ"', 1))
    with pytest.raises(CutParseError, match="malformed CONDITION"):
        parse_cut(CUT.replace("CONDITION IS NOTFND", "CONDITION NOTFND"))
