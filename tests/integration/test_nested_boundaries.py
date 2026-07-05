"""End-to-end proof for nested mock targets: a CALL inside an IF branch,
a CALL inside an EVALUATE WHEN branch, and an EXEC SQL inside an IF are
spliced at their annotated spans, compiled with GnuCOBOL in the
mockymock-cobc container, and executed for real -- the layouts that were
blanket-refused (UNSUPPORTED_NESTED_MOCK_TARGET / NESTED_EXEC) before
docs/2026-07-05-nested-mock-targets-design.md."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"


@requires_docker
def test_nested_boundaries_run_passes():
    exit_code = main(
        [
            "run",
            str(FIXTURES / "nested_boundaries.cbl"),
            "--cut",
            str(FIXTURES / "nested_boundaries.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_nested_boundaries_fail_when_expectation_is_wrong(tmp_path: Path):
    cut = (FIXTURES / "nested_boundaries.cut").read_text()
    broken = tmp_path / "nested_boundaries.cut"
    broken.write_text(
        cut.replace("EXPECT WS-TAX-RATE TO BE 7", "EXPECT WS-TAX-RATE TO BE 8")
    )
    exit_code = main(
        ["run", str(FIXTURES / "nested_boundaries.cbl"), "--cut", str(broken)]
    )
    assert exit_code == 1
