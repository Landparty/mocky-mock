"""Issue #350: an EXPECT on a numeric-edited field with an unquoted number
compares the de-edited value; a quoted string stays byte-exact."""

import pytest

from mockymock.dsl.model import ExpectDirective, MockTestCase, MockTestSuite
from mockymock.report.record_rewrite import is_numeric_edited_picture
from mockymock.splicer.driver import build_driver
from mockymock.splicer.naming import TallyRegistry


def _build(*expectations, numeric_edited=frozenset({"WS-BAL"})):
    case = MockTestCase(
        name="c",
        mocks=[],
        setup_moves=[],
        perform_target="MAIN-PARA",
        expectations=list(expectations),
        verifications=[],
    )
    suite = MockTestSuite(name="s", test_cases=[case])
    return build_driver(
        suite,
        reset_lines=[],
        registry=TallyRegistry(suite),
        numeric_edited=numeric_edited,
    )


def test_unquoted_number_on_a_numeric_edited_field_compares_by_value():
    artifact = _build(ExpectDirective("WS-BAL", "100.00"))
    procedure = "\n".join(artifact.procedure_lines)
    assert "MOVE WS-BAL TO UT-DEEDIT-VALUE" in procedure
    assert "IF UT-DEEDIT-VALUE NOT = 100.00" in procedure
    assert "01  UT-DEEDIT-VALUE            PIC S9(18)V9(13)." in (
        artifact.working_storage_lines
    )


def test_a_decimal_comma_number_compares_by_value():
    """Under DECIMAL-POINT IS COMMA the number is written `1234,50`."""
    procedure = "\n".join(_build(ExpectDirective("WS-BAL", "1234,50")).procedure_lines)
    assert "MOVE WS-BAL TO UT-DEEDIT-VALUE" in procedure
    assert "IF UT-DEEDIT-VALUE NOT = 1234,50" in procedure


def test_operators_and_subscripts_carry_over():
    procedure = "\n".join(
        _build(
            ExpectDirective("WS-BAL (2)", "-7.5", operator=">="),
        ).procedure_lines
    )
    assert "MOVE WS-BAL (2) TO UT-DEEDIT-VALUE" in procedure
    assert "IF UT-DEEDIT-VALUE < -7.5" in procedure


@pytest.mark.parametrize(
    "expectation",
    [
        ExpectDirective("WS-BAL", '"    100.00"'),  # quoted: byte-exact
        ExpectDirective("WS-BAL", "WS-OTHER"),  # a data-name
        ExpectDirective("WS-BAL", '"  1" OR "  2"'),  # combined, text operands
        ExpectDirective("WS-BAL(1:3)", "100"),  # reference-modified
        ExpectDirective("WS-PLAIN", "100"),  # not numeric-edited
    ],
)
def test_everything_else_keeps_the_direct_compare(expectation):
    artifact = _build(expectation)
    assert "UT-DEEDIT-VALUE" not in "\n".join(artifact.procedure_lines)
    assert not any("UT-DEEDIT" in line for line in artifact.working_storage_lines)


@pytest.mark.parametrize(
    ("picture", "edited"),
    [
        ("Z,ZZZ,ZZZ,ZZ9.99", True),
        ("ZZ,ZZ9.99CR", True),
        ("$***,**9.99", True),
        ("-ZZ9.99", True),
        ("99/99/99", True),
        ("Z(5)9", True),
        ("9(10)", False),  # the repeat count is not an inserted 0
        ("S9(7)V99", False),
        ("X(10)", False),
        ("XX/XX", False),  # alphanumeric-edited
        ("", False),
    ],
)
def test_numeric_edited_pictures(picture, edited):
    assert is_numeric_edited_picture(picture) is edited
