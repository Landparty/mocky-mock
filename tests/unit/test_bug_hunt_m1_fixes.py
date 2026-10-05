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


QUAL_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. QUAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC.
           05  WS-QTY PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 42 TO WS-QTY
           DISPLAY WS-QTY
           GOBACK.
"""

DUPF_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DUPF.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-IN-STATUS.
           SELECT OUT-FILE ASSIGN TO "OUT.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  CUST-ID   PIC X(5).
           05  CUST-AMT  PIC 9(5).
       FD  OUT-FILE.
       01  OUT-REC.
           05  CUST-ID   PIC X(5).
           05  CUST-AMT  PIC 9(5).
       WORKING-STORAGE SECTION.
       01  WS-IN-STATUS PIC XX.
       01  WS-EOF       PIC X VALUE "N".
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           OPEN OUTPUT OUT-FILE
           PERFORM READ-PARA UNTIL WS-EOF = "Y"
           CLOSE IN-FILE
           CLOSE OUT-FILE
           GOBACK.
       READ-PARA.
           READ IN-FILE
               AT END MOVE "Y" TO WS-EOF
           END-READ
           IF WS-EOF = "N"
               MOVE CUST-ID OF IN-REC TO CUST-ID OF OUT-REC
               MOVE CUST-AMT OF IN-REC TO CUST-AMT OF OUT-REC
               WRITE OUT-REC
           END-IF.
"""


def test_144_expect_uses_the_cobol_leaf_name_not_record_dot_field(tmp_path) -> None:
    cut = _generate(tmp_path, "QUAL", QUAL_CBL, "--seed", "1")
    assert "EXPECT WS-QTY TO BE 42" in cut
    assert "WS-REC.WS-QTY" not in cut


def test_144_ambiguous_read_fields_are_qualified_with_their_record(tmp_path) -> None:
    cut = _generate(tmp_path, "DUPF", DUPF_CBL, "--seed", "1", "--rows", "2")
    assert "TO CUST-ID OF IN-REC" in cut
    assert "TO CUST-ID\n" not in cut


def test_144_parser_refuses_a_dotted_data_name() -> None:
    from mockymock.dsl.parser import CutParseError, parse_cut

    with pytest.raises(CutParseError, match="contains a '.'"):
        parse_cut(
            'TESTSUITE "Q"\nTESTCASE "c"\nPERFORM MAIN-PARA\n'
            "EXPECT WS-REC.WS-QTY TO BE 42\n"
        )


def test_144_ambiguous_folded_field_becomes_a_stub_not_a_dotted_expect() -> None:
    from mockymock.dsl.fixture_bundle import Expectation
    from mockymock.dsl.generator import ProgramContext, _render_expectation

    source = ProgramContext(lines=[], statement_starts=[], name_counts={"QTY": 2})
    lines = _render_expectation(
        Expectation(kind="field_equals", ref="A-REC.QTY", value="5"),
        set(),
        source=source,
    )
    assert lines[0].startswith("*> STUB EXPECT A-REC.QTY")


def test_144_dotted_stub_is_not_recorded() -> None:
    from mockymock.analysis.stub_expectations import scan_stub_expectations
    from mockymock.dsl.parser import parse_cut

    text = (
        'TESTSUITE "Q"\nTESTCASE "c"\nPERFORM MAIN-PARA\n'
        "*> STUB EXPECT A-REC.QTY -- x\n"
    )
    result = scan_stub_expectations(text, parse_cut(text))
    assert not result.stubs
    assert result.skipped[0].data_name == "A-REC.QTY"


PARM_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PARM.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PARM-FILE ASSIGN TO "PARM.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  PARM-FILE.
       01  PARM-REC.
           05  PARM-DAYS  PIC 9(3).
       WORKING-STORAGE SECTION.
       01  WS-DAYS PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT PARM-FILE
           READ PARM-FILE
           MOVE PARM-DAYS TO WS-DAYS
           CLOSE PARM-FILE
           GOBACK.
"""


def test_read_outside_any_loop_is_verified_once_whatever_the_row_count(
    tmp_path,
) -> None:
    """Found while checking #144 against the legacy corpus (DORMACCT): a
    parameter-card READ got `VERIFY ... 10 TIMES` from the bundle's row
    count."""
    cut = _generate(tmp_path, "PARM", PARM_CBL, "--seed", "1", "--rows", "5")
    assert "VERIFY READ PARM-FILE WAS CALLED 1 TIMES" in cut


DIB_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DIB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SEG    PIC X(20).
       01  WS-FOUND  PIC X VALUE "N".
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC DLI GU SEGMENT(CLAIM) INTO(WS-SEG) END-EXEC
           IF DIBSTAT = SPACES
               MOVE "Y" TO WS-FOUND
           ELSE
               MOVE "N" TO WS-FOUND
           END-IF
           GOBACK.
"""

DIB_CUT = """\
TESTSUITE "dib"
TESTCASE "found"
MOCK DLI "GU"
    MOVE "CLAIM-1" TO WS-SEG
END-MOCK
PERFORM MAIN-PARA
EXPECT WS-FOUND TO BE "Y"
TESTCASE "not found"
MOCK DLI "GU"
    MOVE "GE" TO DIBSTAT
END-MOCK
PERFORM MAIN-PARA
EXPECT WS-FOUND TO BE "N"
TESTCASE "found again after a GE"
MOCK DLI "GU"
    MOVE "CLAIM-2" TO WS-SEG
END-MOCK
PERFORM MAIN-PARA
EXPECT WS-FOUND TO BE "Y"
"""


def _parsed(cbl: str):
    from cobolparser import parse_cobol
    from cobolparser.preprocess import normalize_fixed_format

    return parse_cobol(cbl).ast, normalize_fixed_format(cbl.splitlines()).splitlines()


def test_145_dibstat_reference_plans_a_dlidib_block() -> None:
    from mockymock.analysis.cics_eib import cics_eib_plan
    from mockymock.splicer import cics_eib

    program, lines = _parsed(DIB_CBL)
    plan = cics_eib_plan(program, lines)
    assert plan is not None
    assert plan.referenced_names == []
    assert plan.dib_names == ["DIBSTAT"]
    storage = cics_eib.working_storage_lines(plan)
    assert storage[0] == "01  DLIDIB."
    assert any("DIBSTAT" in line for line in storage)
    assert not any("DFHEIBLK" in line for line in storage)
    assert cics_eib.reset_lines(plan) == ["INITIALIZE DLIDIB"]


def test_145_a_declared_dib_is_left_alone() -> None:
    from mockymock.analysis.cics_eib import cics_eib_plan

    cbl = DIB_CBL.replace(
        "       01  WS-SEG    PIC X(20).",
        "       01  DLIDIB.\n           05  DIBSTAT PIC XX.\n"
        "       01  WS-SEG    PIC X(20).",
    )
    program, lines = _parsed(cbl)
    assert cics_eib_plan(program, lines) is None


SCAN_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCAN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SEG    PIC X(20).
       01  WS-COUNT  PIC 9(3) VALUE 0.
       01  WS-DONE   PIC X VALUE "N".
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM UNTIL WS-DONE = "Y"
               EXEC DLI GNP SEGMENT(ACCT) INTO(WS-SEG) END-EXEC
               IF DIBSTAT = SPACES
                   ADD 1 TO WS-COUNT
               ELSE
                   MOVE "Y" TO WS-DONE
               END-IF
           END-PERFORM
           GOBACK.
"""


def test_145_looped_get_next_dli_mock_reports_end_of_segments(tmp_path) -> None:
    cut = _generate(tmp_path, "SCAN", SCAN_CBL, "--seed", "1")
    assert 'MOVE "GE" TO DIBSTAT' in cut
    assert "-TALLY > 1" in cut
