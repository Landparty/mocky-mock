"""End-to-end proof for subscripted table EXPECT/MOVE, REDEFINES data
items, and DIVIDE ... GIVING ... ROUNDED: the committed regnavg example
compiles and runs for real in the mockymock-cobc container.

test_regnavg_fails_when_a_stale_redefines_value_is_asserted below is the
load-bearing check that the two-paragraph split actually proves cross-case
reset (see the .okf/log.md 2026-07-21 entry for why the original
single-paragraph draft's version of this proof was worthless)."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "regnavg"


@requires_docker
def test_committed_regnavg_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "REGNAVG.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "REGNAVG.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_regnavg_fails_when_rounded_expectation_is_truncated(tmp_path: Path):
    """Locks down that the ROUNDED assertion is actually load-bearing: real
    GnuCOBOL rounds 151.10 / 3 up to 50.37, not the truncated 50.36 --
    asserting the truncated value must FAIL."""
    cut = (EXAMPLE_DIR / "REGNAVG.cut").read_text()
    broken = tmp_path / "REGNAVG.cut"
    broken.write_text(
        cut.replace(
            "EXPECT WS-REGION-AVG(2) TO BE 50.37", "EXPECT WS-REGION-AVG(2) TO BE 50.36"
        )
    )
    exit_code = main(["run", str(EXAMPLE_DIR / "REGNAVG.cbl"), "--cut", str(broken)])
    assert exit_code == 1


@requires_docker
def test_regnavg_fails_when_a_stale_redefines_value_is_asserted(tmp_path: Path):
    """Locks down that the reset-across-cases proof is real: case 3 never
    recomputes region 2 (it PERFORMs 1000-CALCULATE-REGION-1-AVERAGE only),
    so asserting case 2's leftover 50.37/"0005037" there -- instead of the
    correctly-reset 0/"0000000" -- must FAIL. If it passed, WORKING-STORAGE
    reset wouldn't actually be running between cases."""
    cut = (EXAMPLE_DIR / "REGNAVG.cut").read_text()
    broken = tmp_path / "REGNAVG.cut"
    broken.write_text(
        cut.replace(
            'EXPECT WS-REGION-AVG-DISPLAY(2) TO BE "0000000"',
            'EXPECT WS-REGION-AVG-DISPLAY(2) TO BE "0005037"',
        )
    )
    exit_code = main(["run", str(EXAMPLE_DIR / "REGNAVG.cbl"), "--cut", str(broken)])
    assert exit_code == 1
