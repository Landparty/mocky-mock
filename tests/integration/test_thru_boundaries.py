"""End-to-end proof for PERFORM ... THRU: a GO-TO-exit-style range is
invoked via a driver-side `PERFORM PROCESS-ORDER THRU PROCESS-EXIT`,
its mid-range fall-through paragraph's CALL is mocked, and the range's
in-range GO TO short-circuit is observable at runtime -- the layout that
was blanket-refused (UNSUPPORTED_PERFORM_THRU) before
docs/2026-07-06-perform-thru-design.md."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"


@requires_docker
def test_thru_boundaries_run_passes():
    exit_code = main(
        [
            "run",
            str(FIXTURES / "thru_boundaries.cbl"),
            "--cut",
            str(FIXTURES / "thru_boundaries.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_thru_boundaries_fail_when_expectation_is_wrong(tmp_path: Path):
    cut = (FIXTURES / "thru_boundaries.cut").read_text()
    broken = tmp_path / "thru_boundaries.cut"
    broken.write_text(
        cut.replace('EXPECT WS-STATUS TO BE "OK"', 'EXPECT WS-STATUS TO BE "XX"')
    )
    exit_code = main(
        ["run", str(FIXTURES / "thru_boundaries.cbl"), "--cut", str(broken)]
    )
    assert exit_code == 1
