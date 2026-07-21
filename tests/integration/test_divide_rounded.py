"""End-to-end proof for DIVIDE ... GIVING ... ROUNDED: real GnuCOBOL rounds
half-up (5 / 2 -> 3, 7 / 2 -> 4) rather than truncating (which would give 2
and 3), and a MOCK CALL boundary immediately after the ROUNDED clause in the
same paragraph is still found and spliced correctly."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"


@requires_docker
def test_divide_rounded_run_passes():
    exit_code = main(
        [
            "run",
            str(FIXTURES / "divide_rounded.cbl"),
            "--cut",
            str(FIXTURES / "divide_rounded.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_divide_rounded_fails_when_expectation_is_truncated_not_rounded(
    tmp_path: Path,
):
    """Locks down that the assertion is actually load-bearing: if ROUNDED
    were silently ignored (truncating instead), WS-RESULT would be 2, not 3
    -- so asserting 2 here must FAIL against the real rounded behavior."""
    cut = (FIXTURES / "divide_rounded.cut").read_text()
    broken = tmp_path / "divide_rounded.cut"
    broken.write_text(cut.replace("EXPECT WS-RESULT TO BE 3", "EXPECT WS-RESULT TO BE 2"))
    exit_code = main(
        ["run", str(FIXTURES / "divide_rounded.cbl"), "--cut", str(broken)]
    )
    assert exit_code == 1
