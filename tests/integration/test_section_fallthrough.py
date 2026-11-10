"""Bug hunt of 2026-10-27, end to end on GnuCOBOL (see
the unit feature files (each block marked `# Regression:`) for the analysis side)."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker
from tests.unit.test_terminators import RUNAWAY, TRAILING_EXIT_PROGRAM

RUNAWAY_CUT = """\
TESTSUITE "RUNAWAY"

TESTCASE "p1"
    MOCK CALL "APGM"
    END-MOCK
    PERFORM P1
"""


@requires_docker
def test_falling_through_a_section_traps_the_unmocked_call(tmp_path: Path, capsys):
    """The CALL in S3 used to run for real (`module 'CPGM' not found`)
    while lint found nothing; now lint warns and the splice traps it."""
    (tmp_path / "RUNAWAY.cbl").write_text(RUNAWAY)
    (tmp_path / "RUNAWAY.cut").write_text(RUNAWAY_CUT)

    exit_code = main(["run", str(tmp_path / "RUNAWAY.cbl")])
    captured = capsys.readouterr()
    out = captured.out + captured.err

    assert exit_code != 0
    assert "FALLTHROUGH_BOUNDARY" in out
    assert "unmocked CALL boundary" in out
    assert "module 'CPGM' not found" not in out


EXPGM_CUT = """\
TESTSUITE "EXPGM"

TESTCASE "early"
    MOCK CALL "CHKSUB"
        MOVE 8 TO WS-RC
    END-MOCK
    PERFORM A-MAIN
    EXPECT WS-STEP TO BE "EARLY"

TESTCASE "normal"
    MOCK CALL "CHKSUB"
        MOVE 0 TO WS-RC
    END-MOCK
    PERFORM A-MAIN
    EXPECT WS-STEP TO BE "DONE"
"""


@requires_docker
def test_a_section_ending_in_exit_program_runs(tmp_path: Path, capsys):
    (tmp_path / "EXPGM.cbl").write_text(TRAILING_EXIT_PROGRAM)
    (tmp_path / "EXPGM.cut").write_text(EXPGM_CUT)

    exit_code = main(["run", str(tmp_path / "EXPGM.cbl")])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "[PASS] early" in out
    assert "[PASS] normal" in out
