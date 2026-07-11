"""End-to-end proof for EXEC SQL INCLUDE host-variable copybook resolution
+ MOCK SQL ... ROWS cursor sugar: a DCLGEN-shaped copybook (with its own
embedded EXEC SQL DECLARE TABLE stanza) is resolved via --copybook-path,
and a DECLARE CURSOR/OPEN/FETCH-loop/CLOSE is driven entirely by a
MOCK SQL "FETCH ..." ROWS block, compiled with GnuCOBOL in the
mockymock-cobc container and executed for real."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sql_cursor_example"


@requires_docker
def test_cursor_rows_example_passes():
    exit_code = main(
        [
            "run",
            str(FIXTURE_DIR / "CUSTPROG.cbl"),
            "--cut",
            str(FIXTURE_DIR / "CUSTPROG.cut"),
            "--copybook-path",
            str(FIXTURE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_cursor_rows_example_fails_when_row_count_expectation_is_wrong(
    tmp_path: Path,
):
    cut = (FIXTURE_DIR / "CUSTPROG.cut").read_text()
    broken = tmp_path / "CUSTPROG.cut"
    broken.write_text(
        cut.replace("EXPECT WS-ROW-COUNT TO BE 2", "EXPECT WS-ROW-COUNT TO BE 3")
    )
    exit_code = main(
        [
            "run",
            str(FIXTURE_DIR / "CUSTPROG.cbl"),
            "--cut",
            str(broken),
            "--copybook-path",
            str(FIXTURE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 1


@requires_docker
def test_cursor_rows_example_refuses_without_copybook_path():
    """Without --copybook-path, EXEC SQL INCLUDE CUSTREC cannot resolve --
    proves the refusal fires end-to-end through the CLI, not just in the
    sqlca.py unit tests."""
    exit_code = main(
        [
            "run",
            str(FIXTURE_DIR / "CUSTPROG.cbl"),
            "--cut",
            str(FIXTURE_DIR / "CUSTPROG.cut"),
        ]
    )
    assert exit_code == 1
