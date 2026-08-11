"""End-to-end proof for `MOCK READ ... ROWS ... TERMINAL (...)`: a real
sequential-file READ loop, spliced with the generalized `build_rows_block`
and the `build_site_dispatch` READ-rows branch (#46), is compiled and run
by GnuCOBOL in the mockymock-cobc container. INV-FILE declares no FILE
STATUS field, so the loop's only path to termination is the TERMINAL
group's own MOVE landing in the WHEN OTHER branch -- proving rows are
consumed in order, the TERMINAL group fires on exhaustion, and the loop
does not hang.

Follow-up from the review of #46 (issue #48): the ROWS/TERMINAL grammar
was previously covered only by unit tests asserting on generated COBOL
text, never actually compiled and executed."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"


@requires_docker
def test_read_rows_terminal_example_passes():
    exit_code = main(
        [
            "run",
            str(FIXTURES / "read_rows_terminal.cbl"),
            "--cut",
            str(FIXTURES / "read_rows_terminal.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_read_rows_terminal_example_fails_when_row_count_expectation_is_wrong(
    tmp_path: Path,
):
    cut = (FIXTURES / "read_rows_terminal.cut").read_text()
    broken = tmp_path / "read_rows_terminal.cut"
    broken.write_text(
        cut.replace("EXPECT WS-ROW-COUNT TO BE 2", "EXPECT WS-ROW-COUNT TO BE 3")
    )
    exit_code = main(
        ["run", str(FIXTURES / "read_rows_terminal.cbl"), "--cut", str(broken)]
    )
    assert exit_code == 1
