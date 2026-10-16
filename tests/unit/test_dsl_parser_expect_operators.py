"""EXPECT negation/comparison operators:
`EXPECT <name> [NOT] TO BE [GREATER|LESS THAN [OR EQUAL TO]] <value>`.

Each English phrase normalizes to one canonical COBOL relation operator on
ExpectDirective.operator (see model.EXPECT_OPERATORS); the plain `TO BE`
form stays `=` so every pre-operator .cut file parses byte-identically.
"""

import pytest

from mockymock.dsl.model import EXPECT_OPERATORS
from mockymock.dsl.parser import CutParseError, parse_cut


def _cut(expect_line: str) -> str:
    return (
        'TESTSUITE "ops"\n'
        'TESTCASE "case"\n'
        "    PERFORM MAIN\n"
        f"    {expect_line}\n"
    )


PHRASES = [
    ("TO BE", "="),
    ("NOT TO BE", "NOT ="),
    ("TO BE GREATER THAN", ">"),
    ("NOT TO BE GREATER THAN", "NOT >"),
    ("TO BE LESS THAN", "<"),
    ("NOT TO BE LESS THAN", "NOT <"),
    ("TO BE GREATER THAN OR EQUAL TO", ">="),
    ("NOT TO BE GREATER THAN OR EQUAL TO", "NOT >="),
    ("TO BE LESS THAN OR EQUAL TO", "<="),
    ("NOT TO BE LESS THAN OR EQUAL TO", "NOT <="),
]


@pytest.mark.parametrize(("phrase", "operator"), PHRASES)
def test_each_phrase_resolves_to_its_canonical_operator(phrase, operator):
    suite = parse_cut(_cut(f"EXPECT WS-X {phrase} 5"))
    expectation = suite.test_cases[0].expectations[0]
    assert expectation.operator == operator
    assert expectation.data_name == "WS-X"
    assert expectation.expected_value == "5"


def test_phrase_table_covers_every_model_operator():
    assert {operator for _, operator in PHRASES} == set(EXPECT_OPERATORS)


def test_plain_to_be_defaults_to_equality():
    suite = parse_cut(_cut("EXPECT WS-X TO BE 5"))
    assert suite.test_cases[0].expectations[0].operator == "="


def test_subscripted_name_with_comparison_operator():
    suite = parse_cut(_cut("EXPECT WS-TAB(1, 2) TO BE GREATER THAN 10"))
    expectation = suite.test_cases[0].expectations[0]
    assert expectation.data_name == "WS-TAB(1, 2)"
    assert expectation.operator == ">"
    assert expectation.expected_value == "10"


def test_quoted_value_containing_phrase_words_is_kept_verbatim():
    suite = parse_cut(_cut('EXPECT WS-MSG NOT TO BE "GREATER GOOD"'))
    expectation = suite.test_cases[0].expectations[0]
    assert expectation.operator == "NOT ="
    assert expectation.expected_value == '"GREATER GOOD"'


def test_hyphenated_identifier_value_starting_with_phrase_word_parses():
    """GREATER-VALUE is an ordinary COBOL data-name, not a dangling
    comparison phrase -- the fail-closed guard keys on a whole word."""
    suite = parse_cut(_cut("EXPECT WS-X TO BE GREATER-VALUE"))
    expectation = suite.test_cases[0].expectations[0]
    assert expectation.operator == "="
    assert expectation.expected_value == "GREATER-VALUE"


@pytest.mark.parametrize(
    "line",
    [
        "EXPECT WS-X TO BE GREATER 5",
        "EXPECT WS-X TO BE LESS 5",
        "EXPECT WS-X TO BE THAN 5",
        "EXPECT WS-X TO BE GREATER THAN OR EQUAL 5",
        "EXPECT WS-X TO BE LESS THAN OR 5",
        "EXPECT WS-X NOT TO BE EQUAL TO 5",
    ],
)
def test_dangling_comparison_phrase_fails_closed(line):
    """A malformed phrase must raise at the .cut line, not splice the
    leftover words verbatim into the generated IF (a cobc compile error
    pointing at generated code)."""
    with pytest.raises(CutParseError, match="malformed EXPECT comparison"):
        parse_cut(_cut(line))


def test_lowercase_phrase_is_rejected():
    """DSL keywords are case-sensitive uppercase (END-MOCK is the one
    deliberate exception) -- the new phrase words follow the same rule."""
    with pytest.raises(CutParseError, match="unrecognized statement"):
        parse_cut(_cut("EXPECT WS-X not to be 5"))


def test_provider_expansion_preserves_the_operator():
    text = (
        'TESTSUITE "ops"\n'
        "PROVIDER LIMITS\n"
        "    HEADER Limit\n"
        "    ROW 10\n"
        "    ROW 20\n"
        'TESTCASE "limits" USING PROVIDER LIMITS\n'
        "    PERFORM MAIN\n"
        "    EXPECT WS-X TO BE LESS THAN {Limit}\n"
    )
    suite = parse_cut(text)
    assert [c.expectations[0].operator for c in suite.test_cases] == ["<", "<"]
    assert [c.expectations[0].expected_value for c in suite.test_cases] == [
        "10",
        "20",
    ]


@pytest.mark.parametrize(
    "line",
    [
        "EXPECT WS-X TO BE 5.",
        'EXPECT WS-X TO BE "OK".',
        "EXPECT WS-X NOT TO BE GREATER THAN 10 .",
    ],
)
def test_trailing_sentence_period_on_expect_value_fails_closed(line):
    """`EXPECT WS-X TO BE 5.` (the COBOL sentence habit) used to lint
    clean and splice `IF WS-X NOT = 5.` into the driver, where the period
    ends the sentence mid-IF and cobc rejects the generated code."""
    with pytest.raises(
        CutParseError, match="line 4: EXPECT value .* ends with a period"
    ):
        parse_cut(_cut(line))


def test_period_inside_a_quoted_expect_value_is_kept():
    suite = parse_cut(_cut('EXPECT WS-X TO BE "DONE."'))
    assert suite.test_cases[0].expectations[0].expected_value == '"DONE."'


def test_trailing_period_substituted_from_a_provider_row_fails_closed():
    text = (
        'TESTSUITE "ops"\n'
        "PROVIDER LIMITS\n"
        "    HEADER Limit\n"
        "    ROW 5\n"
        "    ROW 7.\n"
        'TESTCASE "case" USING PROVIDER LIMITS\n'
        "    PERFORM MAIN\n"
        "    EXPECT WS-X TO BE {Limit}\n"
    )
    with pytest.raises(CutParseError, match="line 5: EXPECT value '7.'"):
        parse_cut(text)


@pytest.mark.parametrize(
    "line",
    [
        "EXPECT FLAG-ON TO BE GREATER THAN TRUE",
        "EXPECT FLAG-ON NOT TO BE LESS THAN OR EQUAL TO FALSE",
    ],
)
def test_condition_truth_value_refuses_an_ordering_comparison(line):
    """Issue #189: TRUE/FALSE tests a level-88 condition-name, which has no
    order, so only [NOT] TO BE may precede it."""
    with pytest.raises(CutParseError, match="can only follow"):
        parse_cut(_cut(line))


def test_condition_truth_value_parses_with_to_be():
    suite = parse_cut(_cut("EXPECT FLAG-ON NOT TO BE TRUE"))
    expectation = suite.test_cases[0].expectations[0]
    assert (expectation.operator, expectation.expected_value) == ("NOT =", "TRUE")
