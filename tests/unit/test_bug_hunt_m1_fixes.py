"""Regression tests for the 2026-10-05 executed bug hunt (mocky-mock
issues #139-#150). The executed counterparts live in
tests/integration/test_bug_hunt_m1_fixes.py."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

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


TWO_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "FMT" USING WS-N
           CALL "FMT" USING WS-N
           GOBACK.
"""


def test_142_two_call_sites_of_one_key_render_one_summed_verify(tmp_path) -> None:
    cut = _generate(tmp_path, "TWO", TWO_CBL, "--seed", "1")
    assert cut.count('VERIFY CALL "FMT"') == 1
    assert 'VERIFY CALL "FMT" WAS CALLED 2 TIMES' in cut


def test_142_a_conditional_extra_site_demotes_the_summed_count(tmp_path) -> None:
    cbl = TWO_CBL.replace(
        '           CALL "FMT" USING WS-N\n           GOBACK.',
        '           IF WS-N > 5\n               CALL "FMT" USING WS-N\n'
        "           END-IF\n           GOBACK.",
    )
    cut = _generate(tmp_path, "TWO", cbl, "--seed", "1")
    assert 'VERIFY CALL "FMT" WAS CALLED 2 TIMES' not in cut
    assert '*> VERIFY CALL "FMT" WAS CALLED <count not exact' in cut


UNR_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "SUBA" USING WS-N
           GOBACK.
       DEAD-PARA.
           CALL "SUBB" USING WS-N.
"""


def test_143_generate_does_not_mock_a_boundary_the_case_cannot_reach(
    tmp_path, capsys
) -> None:
    from mockymock.cli.main import main

    cut = _generate(tmp_path, "UNR", UNR_CBL, "--seed", "1")
    assert 'MOCK CALL "SUBA"' in cut
    assert '"SUBB"' not in cut
    capsys.readouterr()
    assert main(["lint", str(tmp_path / "UNR.cbl")]) == 0, capsys.readouterr().out


_ENTERPRISE = Path(__file__).resolve().parents[1] / "fixtures" / "enterprise"


@pytest.mark.parametrize(
    "program", sorted(p.stem for p in _ENTERPRISE.glob("*.cbl")), ids=str
)
def test_143_no_generated_enterprise_cut_has_an_unmatched_mock(
    tmp_path, capsys, program
) -> None:
    from mockymock.cli.main import main

    source = tmp_path / f"{program}.cbl"
    shutil.copy(_ENTERPRISE / f"{program}.cbl", source)
    shutil.copytree(_ENTERPRISE / "copybooks", tmp_path / "copybooks")
    copybooks = ["--copybook-path", str(tmp_path / "copybooks")]
    out = tmp_path / f"{program}.cut"
    if (
        main(
            [
                "generate",
                str(source),
                "--with-data",
                "--seed",
                "1",
                "-o",
                str(out),
                *copybooks,
            ]
        )
        != 0
    ):
        pytest.skip("generate --with-data does not support this program")
    capsys.readouterr()
    main(["lint", str(source), *copybooks])
    assert "UNMATCHED_MOCK" not in capsys.readouterr().out
