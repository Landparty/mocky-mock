"""Executed regressions for the 2026-10-05 bug hunt (mocky-mock issues
#139-#150): each one compiles and runs a small program with real
GnuCOBOL, the way the issue was found. Unit-level counterparts live in
tests/unit/test_bug_hunt_m1_fixes.py."""

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
    from tests.unit.test_bug_hunt_m1_fixes import FETCH_CBL

    exit_code = _generate_and_run(tmp_path, "FETCH", FETCH_CBL, "--seed", "1")
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "1 run, 0 failed" in out


@requires_docker
def test_142_generated_verify_for_a_duplicated_call_passes(
    tmp_path: Path, capsys
) -> None:
    from tests.unit.test_bug_hunt_m1_fixes import TWO_CBL

    exit_code = _generate_and_run(tmp_path, "TWO", TWO_CBL, "--seed", "1")
    out = capsys.readouterr().out
    assert exit_code == 0, out


@requires_docker
def test_144_generated_names_compile_and_the_suite_passes(
    tmp_path: Path, capsys
) -> None:
    from tests.unit.test_bug_hunt_m1_fixes import DUPF_CBL, QUAL_CBL

    for name, cbl in (("QUAL", QUAL_CBL), ("DUPF", DUPF_CBL)):
        exit_code = _generate_and_run(tmp_path, name, cbl, "--seed", "1", "--rows", "2")
        out = capsys.readouterr().out
        assert exit_code == 0, out
