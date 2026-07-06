"""End-to-end proof for the real-world DEPTMQP (MQ deposit producer)
example -- a stateful MQCONN/MQOPEN/MQPUT/MQCMIT/MQCLOSE/MQDISC CALL
sequence plus sequential file I/O, adapted from the sibling
legacy-application repo's banking batch corpus and compiled with GnuCOBOL
in the mockymock-cobc container."""

from pathlib import Path

import pytest

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = (
    Path(__file__).parent.parent.parent / "examples" / "real-world" / "DEPTMQP"
)

# cobolparser silently drops the CALL 'MQOPEN' (and everything after it in
# the same sentence) from 1200-MQ-OPEN's AST: a COMPUTE statement with no
# explicit terminator (no ON SIZE ERROR/END-COMPUTE) swallows the following
# statement when there's no period between them. c68a8ff fixed this for
# MOVE/SUBTRACT/MULTIPLY/DIVIDE but not COMPUTE -- see the filed follow-up
# (task_24002e6a) for the isolated repro. Remove this xfail mark once
# cobolparser fixes COMPUTE's statement-boundary parsing.
_COMPUTE_SWALLOWS_CALL_REASON = (
    "cobolparser drops CALL 'MQOPEN' from the AST: COMPUTE without an "
    "explicit terminator swallows the following statement (c68a8ff fixed "
    "this for MOVE/SUBTRACT/MULTIPLY/DIVIDE but not COMPUTE)"
)


@requires_docker
@pytest.mark.xfail(strict=True, reason=_COMPUTE_SWALLOWS_CALL_REASON)
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


# NOTE: this currently passes for the wrong reason -- the whole-file
# UNMATCHED_MOCK refusal above also exits 1, before the intended
# wrong-expectation path ever runs. Once the COMPUTE fix lands this test
# starts exercising the real path (and should still exit 1).
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
