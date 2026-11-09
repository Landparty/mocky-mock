"""Executed regressions for the 2026-10-05 bug hunt (mocky-mock issues
#139-#150): each one compiles and runs a small program with real
GnuCOBOL, the way the issue was found. Unit-level counterparts live in
the unit feature files (each block marked `# Regression:`)."""

from __future__ import annotations

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker


def _run(tmp_path: Path, name: str, cbl: str, cut: str, *extra: str) -> int:
    (tmp_path / f"{name}.cbl").write_text(cbl)
    (tmp_path / f"{name}.cut").write_text(cut)
    return main(["run", str(tmp_path / f"{name}.cbl"), *extra])


NOADV_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOADV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A
           DISPLAY "PROGRESS..." WITH NO ADVANCING.
           GOBACK.
"""

NOADV_CUT = """\
TESTSUITE "noadv"
TESTCASE "one"
PERFORM MAIN-PARA
EXPECT WS-A TO BE 2
TESTCASE "two"
PERFORM MAIN-PARA
EXPECT WS-A TO BE 1
"""


@requires_docker
def test_139_no_advancing_does_not_turn_a_failure_into_a_pass(
    tmp_path: Path, capsys
) -> None:
    exit_code = _run(tmp_path, "NOADV", NOADV_CBL, NOADV_CUT)
    out = capsys.readouterr().out
    assert exit_code == 1, out
    assert "[FAIL] one" in out
    assert "[PASS] two" in out
    assert "CRASH" not in out


RC_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG PIC X VALUE "N".
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-FLAG = "Y"
               MOVE 8 TO RETURN-CODE
           END-IF
           GOBACK.
"""

RC_CUT = """\
TESTSUITE "rc"
TESTCASE "good"
MOVE "N" TO WS-FLAG
PERFORM MAIN-PARA
EXPECT RETURN-CODE TO BE 0
TESTCASE "bad sets rc 8"
MOVE "Y" TO WS-FLAG
PERFORM MAIN-PARA
EXPECT RETURN-CODE TO BE 8
TESTCASE "good again"
MOVE "N" TO WS-FLAG
PERFORM MAIN-PARA
EXPECT RETURN-CODE TO BE 0
"""


@requires_docker
def test_140_return_code_does_not_leak_and_an_all_pass_suite_exits_0(
    tmp_path: Path, capsys
) -> None:
    exit_code = _run(tmp_path, "RC", RC_CBL, RC_CUT)
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "3 run, 0 failed" in out

    exit_code = _run(tmp_path, "RC", RC_CBL, RC_CUT, "--case", "bad sets rc 8")
    out = capsys.readouterr().out
    assert exit_code == 0, out


def _generate_and_run(tmp_path: Path, name: str, cbl: str, *gen: str) -> int:
    source = tmp_path / f"{name}.cbl"
    source.write_text(cbl)
    cut = tmp_path / f"{name}.cut"
    assert main(["generate", str(source), "--with-data", "-o", str(cut), *gen]) == 0
    return main(["run", str(source), "--timeout", "60"])


@requires_docker
def test_141_generated_suite_for_a_looped_one_row_fetch_terminates_and_passes(
    tmp_path: Path, capsys
) -> None:
    from tests.unit.test_cli_generate_with_data import FETCH_CBL

    exit_code = _generate_and_run(tmp_path, "FETCH", FETCH_CBL, "--seed", "1")
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "1 run, 0 failed" in out


@requires_docker
def test_142_generated_verify_for_a_duplicated_call_passes(
    tmp_path: Path, capsys
) -> None:
    from tests.unit.test_cli_generate_with_data import TWO_CBL

    exit_code = _generate_and_run(tmp_path, "TWO", TWO_CBL, "--seed", "1")
    out = capsys.readouterr().out
    assert exit_code == 0, out


@requires_docker
def test_144_generated_names_compile_and_the_suite_passes(
    tmp_path: Path, capsys
) -> None:
    from tests.unit.test_cli_generate_with_data import DUPF_CBL, QUAL_CBL

    for name, cbl in (("QUAL", QUAL_CBL), ("DUPF", DUPF_CBL)):
        exit_code = _generate_and_run(tmp_path, name, cbl, "--seed", "1", "--rows", "2")
        out = capsys.readouterr().out
        assert exit_code == 0, out


@requires_docker
def test_read_outside_any_loop_generated_suite_passes(tmp_path: Path, capsys) -> None:
    from tests.unit.test_cli_generate_with_data import PARM_CBL

    exit_code = _generate_and_run(
        tmp_path, "PARM", PARM_CBL, "--seed", "1", "--rows", "5"
    )
    out = capsys.readouterr().out
    assert exit_code == 0, out


@requires_docker
def test_145_dibstat_program_compiles_and_runs(tmp_path: Path, capsys) -> None:
    from tests.unit.test_cics_eib import DIB_CBL, DIB_CUT

    exit_code = _run(tmp_path, "DIB", DIB_CBL, DIB_CUT)
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "3 run, 0 failed" in out


@requires_docker
def test_145_generated_suite_for_a_looped_get_next_terminates(
    tmp_path: Path, capsys
) -> None:
    from tests.unit.test_generator_dli_end_status import SCAN_CBL

    exit_code = _generate_and_run(tmp_path, "SCAN", SCAN_CBL, "--seed", "1")
    out = capsys.readouterr().out
    assert exit_code == 0, out


REC_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-HIGH PIC X(2).
       01  WS-NAME PIC X(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE HIGH-VALUES TO WS-HIGH
           MOVE "SAM" TO WS-NAME
           GOBACK.
"""

REC_CUT = """\
TESTSUITE "rec"
TESTCASE "c"
PERFORM MAIN-PARA
*> STUB EXPECT WS-HIGH
*> STUB EXPECT WS-NAME
"""


@requires_docker
def test_146_recorded_goldens_pass_on_the_next_run(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, "REC", REC_CBL, REC_CUT, "--record-expectations") == 0
    rewritten = (tmp_path / "REC.cut").read_text()
    assert "�" not in rewritten
    assert 'EXPECT WS-NAME TO BE "SAM"' in rewritten
    capsys.readouterr()
    exit_code = main(["run", str(tmp_path / "REC.cbl")])
    assert exit_code == 0, capsys.readouterr().out


@requires_docker
def test_147_cases_pass_in_the_suite_not_just_alone(tmp_path: Path, capsys) -> None:
    from tests.unit.test_reset import LS_CBL, LS_CUT

    exit_code = _run(tmp_path, "LS", LS_CBL, LS_CUT)
    out = capsys.readouterr().out
    assert exit_code == 0, out


SQLL_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  HV-NAME   PIC X(10).
       01  WS-FOUND  PIC X VALUE "N".
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL SELECT NAME INTO :HV-NAME FROM CUST END-EXEC
           IF SQLCODE = 0
               MOVE "Y" TO WS-FOUND
           ELSE
               MOVE "N" TO WS-FOUND
           END-IF
           GOBACK.
"""

SQLL_CUT = """\
TESTSUITE "sqll"
TESTCASE "not found"
MOCK SQL "SELECT"
    MOVE 100 TO SQLCODE
END-MOCK
PERFORM MAIN-PARA
EXPECT WS-FOUND TO BE "N"
TESTCASE "found, mock leaves SQLCODE alone"
MOCK SQL "SELECT"
    MOVE "SAM" TO HV-NAME
END-MOCK
PERFORM MAIN-PARA
EXPECT WS-FOUND TO BE "Y"
"""


@requires_docker
def test_148_sqlcode_does_not_leak_into_the_next_case(tmp_path: Path, capsys) -> None:
    exit_code = _run(tmp_path, "SQLL", SQLL_CBL, SQLL_CUT)
    out = capsys.readouterr().out
    assert exit_code == 0, out


@requires_docker
def test_149_read_into_and_write_from_keep_their_implicit_move(
    tmp_path: Path, capsys
) -> None:
    from tests.unit.test_cli_export import RINTO_CBL

    cut = """\
TESTSUITE "into"
TESTCASE "read into"
MOCK READ IN-FILE ROWS
    ( IN-AMT = 5 )
    ( IN-AMT = 7 )
    TERMINAL ( WS-EOF = "Y" )
END-MOCK
PERFORM MAIN-PARA
EXPECT WS-TOTAL TO BE 12
TESTCASE "read into, body"
MOCK READ IN-FILE
    MOVE 9 TO IN-AMT
    MOVE "Y" TO WS-EOF
END-MOCK
PERFORM READ-PARA
EXPECT WS-AMT TO BE 9
TESTCASE "legacy body sets the INTO field"
MOCK READ IN-FILE
    MOVE 4 TO WS-AMT
END-MOCK
PERFORM READ-PARA
EXPECT WS-TOTAL TO BE 4
TESTCASE "write from"
MOCK WRITE OUT-REC
END-MOCK
PERFORM WRITE-PARA
EXPECT OUT-REC TO BE "HELLO"
"""
    exit_code = _run(tmp_path, "RINTO", RINTO_CBL, cut)
    out = capsys.readouterr().out
    assert exit_code == 0, out
    for name in (
        "read into",
        "read into, body",
        "legacy body sets the INTO field",
        "write from",
    ):
        assert f"[PASS] {name}" in out, out


GOTO1_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTO1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A
           GO TO LAST-PARA.
       LAST-PARA.
           MOVE 2 TO WS-A.
"""

GOTO1_CUT = """\
TESTSUITE "goto"
TESTCASE "one"
PERFORM MAIN-PARA
EXPECT WS-A TO BE 2
TESTCASE "two"
PERFORM MAIN-PARA
EXPECT WS-A TO BE 2
"""


@requires_docker
def test_150_a_case_the_run_never_reached_is_reported(tmp_path: Path, capsys) -> None:
    junit = tmp_path / "junit.xml"
    exit_code = _run(tmp_path, "GOTO1", GOTO1_CBL, GOTO1_CUT, "--junit-xml", str(junit))
    out = capsys.readouterr().out
    assert exit_code == 1, out
    assert "[NOT RUN] two" in out
    assert 'tests="2"' in junit.read_text()
