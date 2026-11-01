"""End-to-end proof that mockymock's compile does not inherit GnuCOBOL
3.2's broken OS/VS intermediate arithmetic. `-std=mvs` turns on
`arithmetic-osvs`, under which `COMPUTE X = P * (1 - D)` gives 0 whenever
D is zero; compile_source turns it back off with `-fno-arithmetic-osvs`.
Without that flag the first case below fails on every EXPECT."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"


@requires_docker
def test_multiplying_by_a_parenthesised_difference_with_a_zero_operand():
    exit_code = main(
        [
            "run",
            str(FIXTURES / "osvs_arith.cbl"),
            "--cut",
            str(FIXTURES / "osvs_arith.cut"),
        ]
    )
    assert exit_code == 0
