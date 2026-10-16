"""Issue #288: LINKAGE is folded into WORKING-STORAGE, so `IF ADDRESS OF
LK-OPT = NULL` is always false and `NUMBER-OF-CALL-PARAMETERS` never sees an
omitted argument -- the program's omitted-argument branch cannot be tested.
lint and run said nothing; they now warn when a selected case reaches such a
test (option 2 of the issue; the OMIT feature, option 1, is not built)."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock.analysis.linkage import linkage_plan, omitted_argument_tests

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N                PIC 9 VALUE 0.
       01  WS-P                USAGE POINTER.
       LINKAGE SECTION.
       01  LK-RESP.
           05 LK-RC            PIC 99.
       01  LK-OPT              PIC X(4).
       PROCEDURE DIVISION USING LK-RESP OPTIONAL LK-OPT.
       0000-MAIN.
           PERFORM 1000-CALC
           GOBACK.
       1000-CALC.
           IF ADDRESS OF LK-OPT = NULL
               MOVE 9 TO LK-RC
           ELSE
               MOVE 0 TO LK-RC
           END-IF.
       2000-COUNT.
           MOVE NUMBER-OF-CALL-PARAMETERS TO WS-N.
       3000-OTHER.
           IF NULL IS NOT EQUAL TO ADDRESS OF LK-OPT
               MOVE 8 TO LK-RC
           END-IF
           SET WS-P TO ADDRESS OF LK-OPT
           IF ADDRESS OF LK-RESP = WS-P
               MOVE 7 TO LK-RC
           END-IF.
"""

CUT = """\
TESTSUITE "SB"
TESTCASE "optional parameter omitted"
    PERFORM 1000-CALC
    EXPECT LK-RC TO BE 9
"""


def test_omitted_argument_tests_are_found() -> None:
    plan = linkage_plan(parse_cobol(PROGRAM, filename="sb.cbl").ast)
    assert plan is not None
    found = omitted_argument_tests(PROGRAM.splitlines(), plan)
    assert [(t.line, t.item_name) for t in found] == [
        (16, "LK-OPT"),
        (22, None),
        (24, "LK-OPT"),
    ]


def test_a_rebound_item_is_not_reported() -> None:
    plan = linkage_plan(parse_cobol(PROGRAM, filename="sb.cbl").ast)
    assert plan is not None
    found = omitted_argument_tests(PROGRAM.splitlines(), plan, {"LK-OPT"})
    assert [t.item_name for t in found] == [None]


def test_set_address_to_null_is_not_a_test() -> None:
    program = PROGRAM.replace(
        "SET WS-P TO ADDRESS OF LK-OPT", "SET ADDRESS OF LK-OPT TO NULL"
    )
    plan = linkage_plan(parse_cobol(program, filename="sb.cbl").ast)
    assert plan is not None
    lines = [t.line for t in omitted_argument_tests(program.splitlines(), plan)]
    assert 26 not in lines


def test_lint_warns_on_a_reached_test_only(tmp_path, capsys) -> None:
    from mockymock.cli.main import main

    source = tmp_path / "SB.cbl"
    source.write_text(PROGRAM)
    cut = tmp_path / "SB.cut"
    cut.write_text(CUT)
    assert main(["lint", str(source), "--cut", str(cut)]) == 0
    out = capsys.readouterr().out
    assert "warning (OMITTED_ARGUMENT_UNTESTABLE): paragraph 1000-CALC, line 16" in out
    assert "1 warning(s)." in out
    # 2000-COUNT and 3000-OTHER are reached by no case.
    assert "NUMBER-OF-CALL-PARAMETERS" not in out
    assert "line 24" not in out

    cut.write_text(CUT.replace("PERFORM 1000-CALC", "PERFORM 2000-COUNT"))
    assert main(["lint", str(source), "--cut", str(cut)]) == 0
    out = capsys.readouterr().out
    assert "paragraph 2000-COUNT, line 22: NUMBER-OF-CALL-PARAMETERS" in out
