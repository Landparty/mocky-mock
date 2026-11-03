"""A case that runs a program's whole main line (2026-11-02, NIST CCVS85):
`PERFORM <first> THRU <last>` runs every paragraph the program runs, the
STOP RUN it falls into ends the case and returns to the test, and the next
case still runs."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker
from tests.unit.test_main_line_cases import CCVS

CUT = """\
TESTSUITE "CCVS"

TESTCASE "main line"
    MOCK OPEN PRINT-FILE
    END-MOCK
    MOCK CLOSE PRINT-FILE
    END-MOCK
    MOCK WRITE PRINT-REC
    END-MOCK
    PERFORM OPEN-FILES THRU CCVS-999999
    EXPECT PASS-COUNTER TO BE 2
    EXPECT PRINT-REC TO BE "END"
    VERIFY OPEN PRINT-FILE WAS CALLED 1 TIMES
    VERIFY WRITE PRINT-REC WAS CALLED 1 TIMES
    VERIFY CLOSE PRINT-FILE WAS CALLED 1 TIMES

TESTCASE "one test after it"
    PERFORM TEST-1
    EXPECT PASS-COUNTER TO BE 1
"""


@requires_docker
def test_a_main_line_case_runs_to_its_stop_run_and_returns(tmp_path: Path, capsys):
    program = tmp_path / "CCVS.cbl"
    program.write_text(CCVS)
    cut = tmp_path / "CCVS.cut"
    cut.write_text(CUT)
    assert main(["run", str(program), "--cut", str(cut)]) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "2 run, 0 failed" in out


@requires_docker
def test_a_main_line_case_sees_what_the_main_line_did(tmp_path: Path, capsys):
    program = tmp_path / "CCVS.cbl"
    program.write_text(CCVS)
    cut = tmp_path / "CCVS.cut"
    cut.write_text(
        CUT.replace("EXPECT PASS-COUNTER TO BE 2", "EXPECT PASS-COUNTER TO BE 3")
    )
    assert main(["run", str(program), "--cut", str(cut)]) == 1
    assert "expected PASS-COUNTER = 3, got 2" in capsys.readouterr().out
