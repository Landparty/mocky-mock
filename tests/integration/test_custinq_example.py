"""End-to-end proof for the first EXEC CICS worked example: EXEC CICS
READ/RETURN are compiled and run for real in the mockymock-cobc container
-- closing the real-world-readiness audit's documented gap that CICS was
"never proven end-to-end (no example, absent from corpus)"."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "custinq"


@requires_docker
def test_committed_custinq_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "CUSTINQ.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "CUSTINQ.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_custinq_fails_when_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "CUSTINQ.cut").read_text()
    broken = tmp_path / "CUSTINQ.cut"
    broken.write_text(
        cut.replace(
            'EXPECT WS-INQUIRY-STATUS TO BE "FOUND"',
            'EXPECT WS-INQUIRY-STATUS TO BE "NOTFOUND"',
            1,
        )
    )
    exit_code = main(["run", str(EXAMPLE_DIR / "CUSTINQ.cbl"), "--cut", str(broken)])
    assert exit_code == 1
