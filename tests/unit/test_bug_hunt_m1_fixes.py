"""Regression tests for the 2026-10-05 executed bug hunt (mocky-mock
issues #139-#150). The executed counterparts live in
tests/integration/test_bug_hunt_m1_fixes.py."""

from __future__ import annotations

from mockymock.report.results import parse_stdout


def test_139_marker_after_no_advancing_output_is_still_parsed() -> None:
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: noadv\n"
        "__MOCKYMOCK__ CASE 001 START: one\n"
        "PROGRESS...__MOCKYMOCK__ CASE 001 FAIL: expected WS-A = 2, got 1\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ CASE 002 START: two\n"
        "PROGRESS...__MOCKYMOCK__ CASE 002 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=1\n"
    )
    suite = parse_stdout(stdout)
    one, two = suite.results
    assert one.failure_reasons == ["expected WS-A = 2, got 1"]
    assert one.ended and not one.passed
    assert two.passed
    assert not suite.all_passed


def _one_case_suite():
    from mockymock.dsl.model import ExpectDirective, MockTestCase, MockTestSuite

    case = MockTestCase(
        name="rc",
        perform_target="MAIN-PARA",
        expectations=[ExpectDirective("RETURN-CODE", "0")],
    )
    return MockTestSuite(name="rc", test_cases=[case])


def test_140_each_case_and_the_final_stop_run_reset_return_code() -> None:
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.naming import TallyRegistry

    suite = _one_case_suite()
    lines = [
        line.strip()
        for line in build_driver(suite, [], TallyRegistry(suite)).procedure_lines
    ]
    stop = lines.index("STOP RUN.")
    assert lines[stop - 1] == "MOVE 0 TO RETURN-CODE"
    case_start = lines.index("UT-TESTCASE-001.")
    perform = lines.index("PERFORM MAIN-PARA")
    assert "MOVE 0 TO RETURN-CODE" in lines[case_start:perform]


FETCH_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FETCH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  HV-ID     PIC X(4).
       01  WS-COUNT  PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL OPEN C1 END-EXEC
           PERFORM FETCH-PARA UNTIL SQLCODE = 100
           EXEC SQL CLOSE C1 END-EXEC
           DISPLAY WS-COUNT
           GOBACK.
       FETCH-PARA.
           EXEC SQL FETCH C1 INTO :HV-ID END-EXEC
           IF SQLCODE = 0
               ADD 1 TO WS-COUNT
           END-IF.
"""


def _generate(tmp_path, name: str, cbl: str, *extra: str) -> str:
    from mockymock.cli.main import main

    source = tmp_path / f"{name}.cbl"
    source.write_text(cbl)
    out = tmp_path / f"{name}.cut"
    assert main(["generate", str(source), "--with-data", "-o", str(out), *extra]) == 0
    return out.read_text()


def test_141_one_row_looped_fetch_is_mocked_with_rows_and_counted_once_more(
    tmp_path,
) -> None:
    cut = _generate(tmp_path, "FETCH", FETCH_CBL, "--seed", "1")
    assert 'MOCK SQL "FETCH" ROWS' in cut
    assert 'VERIFY SQL "FETCH" WAS CALLED 2 TIMES' in cut


def test_141_fetch_outside_a_loop_keeps_its_single_row_body(tmp_path) -> None:
    cbl = FETCH_CBL.replace(
        "PERFORM FETCH-PARA UNTIL SQLCODE = 100", "PERFORM FETCH-PARA"
    )
    cut = _generate(tmp_path, "FETCH", cbl, "--seed", "1")
    assert 'MOCK SQL "FETCH" ROWS' not in cut
    assert 'VERIFY SQL "FETCH" WAS CALLED 1 TIMES' in cut
