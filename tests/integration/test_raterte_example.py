"""End-to-end proof for a business-flavored dynamic CALL example: a single
bare-key MOCK CALL WS-PGM-NAME directive routes to a different subprogram
name per test case (STDRATE/PRMRATE/VIPRATE), compiled and run for real in
the mockymock-cobc container."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "raterte"


@requires_docker
def test_committed_raterte_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "RATERTE.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "RATERTE.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_raterte_fails_when_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "RATERTE.cut").read_text()
    broken = tmp_path / "RATERTE.cut"
    broken.write_text(
        cut.replace(
            "EXPECT WS-INTEREST TO BE 300.00", "EXPECT WS-INTEREST TO BE 301.00", 1
        )
    )
    exit_code = main(["run", str(EXAMPLE_DIR / "RATERTE.cbl"), "--cut", str(broken)])
    assert exit_code == 1
