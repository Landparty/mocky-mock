"""`mutate --fail-under` must agree with the score it prints.

`MutationOutcome.score` divides before `* 100` multiplies, so 29/50 is
57.99999999999999: printed as "58.0%" and yet, compared as a float, below
`--fail-under 58`. The gate compares exactly instead (issue #206).
"""

import pytest

from mockymock.mutation.operators import Mutant
from mockymock.mutation.report import MutantResult, MutationOutcome, format_console


def _outcome(killed: int, survived: int) -> MutationOutcome:
    m = Mutant(1, "x", "a", "b", "d")
    return MutationOutcome(
        program="P.cbl",
        cut="P.cut",
        results=[MutantResult(m, "killed")] * killed
        + [MutantResult(m, "survived")] * survived,
    )


@pytest.mark.parametrize(
    "killed,total",
    [(29, 50), (29, 100), (57, 100), (58, 100), (87, 150), (58, 200), (116, 200)],
)
def test_a_score_printed_at_the_threshold_meets_it(killed, total):
    outcome = _outcome(killed, total - killed)
    percent = 100 * killed / total
    threshold = round(percent)
    assert format_console(outcome).splitlines()[-1] == (
        f"mutation score: {threshold:.1f}%"
    )
    assert not outcome.score_below(threshold)


def test_a_score_just_under_the_threshold_is_below_it():
    outcome = _outcome(57, 43)
    assert outcome.score_below(57.5)
    assert outcome.score_below(57.01)
    assert not outcome.score_below(57)


def test_a_decimal_threshold_means_the_decimal_not_its_binary_float():
    # 573/1000 is exactly 57.3%; float 57.3 is a hair above 57.3, which a
    # Fraction(57.3) would read as "57.3% is below 57.3".
    assert not _outcome(573, 427).score_below(57.3)


def test_no_scored_mutant_is_below_any_threshold():
    assert MutationOutcome(program="P.cbl", cut="P.cut", results=[]).score_below(0)
