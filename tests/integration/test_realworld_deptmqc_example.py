"""End-to-end proof for the real-world DEPTMQC (MQ deposit consumer)
example -- mixes MQGET, DB2 INSERT, and a dual-commit/backout pattern
(MQCMIT+COMMIT together, ROLLBACK+MQBACK together on failure), adapted
from the sibling legacy-application repo's banking batch corpus and
compiled with GnuCOBOL in the mockymock-cobc container."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = (
    Path(__file__).parent.parent.parent / "examples" / "real-world" / "DEPTMQC"
)


@requires_docker
def test_committed_deptmqc_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "DEPTMQC.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "DEPTMQC.cut"),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_deptmqc_fails_when_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "DEPTMQC.cut").read_text()
    broken = tmp_path / "DEPTMQC.cut"
    broken.write_text(
        cut.replace(
            "EXPECT WS-ROWS-INSERTED TO BE 1", "EXPECT WS-ROWS-INSERTED TO BE 2"
        )
    )
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "DEPTMQC.cbl"),
            "--cut",
            str(broken),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 1
