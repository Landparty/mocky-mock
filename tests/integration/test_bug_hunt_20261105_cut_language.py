"""Bug hunt of 2026-11-05 on the .cut suite language, end to end on
GnuCOBOL (see tests/unit/test_bug_hunt_20261105_cut_language.py)."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LONGNM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CUST-REC.
           05  CUST-ID        PIC 9(5).
       01  OUT-REC.
           05  CUST-ID        PIC 9(5).
       01  WS-B               PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO CUST-ID OF CUST-REC
           CALL "SUBPGM" USING WS-B
           ADD 1 TO WS-B
           GOBACK.
"""

NAME = "a test case name well past one source line " * 15


def _write(tmp_path: Path, cut_text: str) -> Path:
    (tmp_path / "LONGNM.cbl").write_text(PROGRAM)
    (tmp_path / "LONGNM.cut").write_text(cut_text)
    return tmp_path / "LONGNM.cbl"


@requires_docker
def test_long_suite_and_case_names_compile_and_report_whole(tmp_path, capsys):
    program = _write(
        tmp_path,
        f'TESTSUITE "{NAME}"\n'
        "*> a page eject \x0c inside a comment\n"
        f'TESTCASE "{NAME}"\n'
        '    MOCK CALL "SUBPGM"\n'
        "        MOVE 5 TO WS-B\n"
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
        "    EXPECT WS-B TO BE 6\n"
        "    EXPECT CUST-ID OF CUST-REC TO BE 1\n"
        '    VERIFY "SUBPGM" WAS CALLED ONCE\n',
    )
    assert main(["run", str(program)]) == 0
    out = capsys.readouterr().out
    assert f"[PASS] {NAME}" in out
    assert "1 run, 0 failed" in out


@requires_docker
def test_an_ambiguous_expect_is_refused_before_the_compile(tmp_path, capsys):
    program = _write(
        tmp_path,
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOCK CALL "SUBPGM"\n'
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
        "    EXPECT CUST-ID TO BE 1\n",
    )
    assert main(["run", str(program)]) != 0
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "AMBIGUOUS_DATA_NAME" in out and ".cut line 6" in out
    assert "compile failed" not in out
    assert "mockymock bug" not in out
