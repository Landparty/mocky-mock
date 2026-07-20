"""End-to-end proof for MOCK PARAGRAPH / MOCK SECTION: the committed
flowmock example compiles and runs for real in the mockymock-cobc
container -- mock bodies replace flow-target bodies per case, unmocked
cases run the relocated real bodies, and the flow tallies verify."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "flowmock"


@requires_docker
def test_committed_flowmock_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "FLOWMOCK.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "FLOWMOCK.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_flowmock_fails_when_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "FLOWMOCK.cut").read_text()
    broken = tmp_path / "FLOWMOCK.cut"
    broken.write_text(
        cut.replace("EXPECT WS-TOTAL TO BE 50", "EXPECT WS-TOTAL TO BE 51", 1)
    )
    exit_code = main(["run", str(EXAMPLE_DIR / "FLOWMOCK.cbl"), "--cut", str(broken)])
    assert exit_code == 1


@requires_docker
def test_flow_tally_counts_loop_iterations(tmp_path: Path):
    """PERFORM ... TIMES of a mocked paragraph increments the tally once
    per iteration -- the dispatch runs on every entry through the header."""
    source = tmp_path / "LOOPY.cbl"
    source.write_text("""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOOPY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TOTAL       PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           PERFORM ADD-STEP 3 TIMES.
       ADD-STEP.
           ADD 500 TO WS-TOTAL.
""")
    cut = tmp_path / "LOOPY.cut"
    cut.write_text("""\
TESTSUITE "loop tally"

TESTCASE "mock body runs once per iteration"
    MOCK PARAGRAPH ADD-STEP
        ADD 2 TO WS-TOTAL
    END-MOCK
    PERFORM MAIN-PROCESS
    EXPECT WS-TOTAL TO BE 6
    VERIFY PARAGRAPH ADD-STEP WAS PERFORMED 3 TIMES
""")
    exit_code = main(["run", str(source), "--cut", str(cut)])
    assert exit_code == 0
