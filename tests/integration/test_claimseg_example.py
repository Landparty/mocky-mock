"""End-to-end proof for the first EXEC DLI worked example: EXEC DLI
GU/ISRT are compiled and run for real in the mockymock-cobc container --
closing the gap that MOCK DLI was classified since the v2 all-boundaries
design but, until this example, proven only by unit tests (the same
"classified but never proven" gap EXEC CICS had before examples/custinq
closed it)."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "claimseg"


@requires_docker
def test_committed_claimseg_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "CLAIMSEG.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "CLAIMSEG.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_claimseg_fails_when_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "CLAIMSEG.cut").read_text()
    broken = tmp_path / "CLAIMSEG.cut"
    broken.write_text(
        cut.replace(
            "EXPECT WS-CLAIM-AMOUNT TO BE 250.00",
            "EXPECT WS-CLAIM-AMOUNT TO BE 999.00",
            1,
        )
    )
    exit_code = main(["run", str(EXAMPLE_DIR / "CLAIMSEG.cbl"), "--cut", str(broken)])
    assert exit_code == 1
