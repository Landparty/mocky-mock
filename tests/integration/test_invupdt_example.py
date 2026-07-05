"""End-to-end proof for the v2 all-boundaries example: file I/O + EXEC SQL
(with SQLCA injection) + MQ CALL + console ACCEPT, compiled with GnuCOBOL
in the mockymock-cobc container and executed for real.

This also empirically verifies the design's FD-record-area assumption: the
READ mock MOVEs into INV-QTY (a FILE SECTION record field) while INV-FILE
is never actually opened."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "invupdt"


@requires_docker
def test_committed_invupdt_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "INVUPDT.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "INVUPDT.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_invupdt_fails_when_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "INVUPDT.cut").read_text()
    broken = tmp_path / "INVUPDT.cut"
    broken.write_text(cut.replace("EXPECT WS-TOTAL-QTY TO BE 10", "EXPECT WS-TOTAL-QTY TO BE 11"))
    exit_code = main(
        ["run", str(EXAMPLE_DIR / "INVUPDT.cbl"), "--cut", str(broken)]
    )
    assert exit_code == 1
