"""End-to-end proof for the real-world DEPTMQP (MQ deposit producer)
example -- a stateful MQCONN/MQOPEN/MQPUT/MQCMIT/MQCLOSE/MQDISC CALL
sequence plus sequential file I/O, adapted from the sibling
legacy-application repo's banking batch corpus and compiled with GnuCOBOL
in the mockymock-cobc container."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = (
    Path(__file__).parent.parent.parent / "examples" / "real-world" / "DEPTMQP"
)


@requires_docker
def test_committed_deptmqp_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "DEPTMQP.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "DEPTMQP.cut"),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 0


# Exercises the intended wrong-expectation path: DEPTMQP compiles and runs
# cleanly (see test_committed_deptmqp_example_passes above), so this exit 1
# comes from the deliberately broken EXPECT assertion, not from a whole-file
# parse/mock refusal.
@requires_docker
def test_deptmqp_fails_when_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "DEPTMQP.cut").read_text()
    broken = tmp_path / "DEPTMQP.cut"
    broken.write_text(
        cut.replace("EXPECT WS-MSGS-PUT TO BE 1", "EXPECT WS-MSGS-PUT TO BE 2")
    )
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "DEPTMQP.cbl"),
            "--cut",
            str(broken),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 1
