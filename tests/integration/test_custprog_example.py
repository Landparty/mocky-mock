"""End-to-end proof for the documented ROWS/DCLGEN worked example: mirrors
tests/integration/test_sql_cursor_rows_example.py (same COBOL/.cut,
proven identical output) but against the committed examples/custprog/
copy, which now has a README explaining the MOCK SQL ... ROWS cursor-fetch
sugar and DCLGEN-style EXEC SQL INCLUDE resolution -- previously proven
only by that terser regression fixture, never by a polished example."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "custprog"


@requires_docker
def test_committed_custprog_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "CUSTPROG.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "CUSTPROG.cut"),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_custprog_fails_when_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "CUSTPROG.cut").read_text()
    broken = tmp_path / "CUSTPROG.cut"
    broken.write_text(
        cut.replace("EXPECT WS-ROW-COUNT TO BE 2", "EXPECT WS-ROW-COUNT TO BE 3")
    )
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "CUSTPROG.cbl"),
            "--cut",
            str(broken),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 1
