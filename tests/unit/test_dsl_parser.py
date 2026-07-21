import pytest

from mockymock.dsl.parser import CutParseError, parse_cut

ORDRPROC_CUT = """\
TESTSUITE "ORDRPROC discount calculation"

TESTCASE "10% discount reduces net amount correctly"
    MOCK CALL "DISCRATE"
        MOVE 0.10 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 100.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 90.00
    VERIFY "DISCRATE" WAS CALLED ONCE

TESTCASE "Zero discount leaves amount unchanged"
    MOCK CALL "DISCRATE"
        MOVE 0.00 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 50.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 50.00
"""


def test_parses_suite_name():
    suite = parse_cut(ORDRPROC_CUT)
    assert suite.name == "ORDRPROC discount calculation"


def test_parses_two_test_cases():
    suite = parse_cut(ORDRPROC_CUT)
    assert len(suite.test_cases) == 2
    assert suite.test_cases[0].name == "10% discount reduces net amount correctly"
    assert suite.test_cases[1].name == "Zero discount leaves amount unchanged"


def test_parses_mock_call_body():
    suite = parse_cut(ORDRPROC_CUT)
    case_one = suite.test_cases[0]
    assert len(case_one.mocks) == 1
    assert case_one.mocks[0].program_name == "DISCRATE"
    assert case_one.mocks[0].body_lines == ["MOVE 0.10 TO WS-DISCOUNT-PCT"]


def test_parses_setup_moves_and_perform_target():
    suite = parse_cut(ORDRPROC_CUT)
    case_one = suite.test_cases[0]
    assert case_one.setup_moves == [("100.00", "ORD-AMOUNT")]
    assert case_one.perform_target == "PROCESS-ORDER"


def test_parses_expect_and_verify():
    suite = parse_cut(ORDRPROC_CUT)
    case_one = suite.test_cases[0]
    assert case_one.expectations[0].data_name == "WS-NET-AMOUNT"
    assert case_one.expectations[0].expected_value == "90.00"
    assert case_one.verifications[0].program_name == "DISCRATE"
    assert case_one.verifications[0].expectation == "ONCE"


def test_second_case_has_no_verify():
    suite = parse_cut(ORDRPROC_CUT)
    assert suite.test_cases[1].verifications == []


def test_testcase_before_testsuite_raises():
    with pytest.raises(CutParseError):
        parse_cut('TESTCASE "orphan"\nPERFORM X\n')


def test_unrecognized_line_raises():
    with pytest.raises(CutParseError):
        parse_cut('TESTSUITE "X"\n\nTESTCASE "Y"\nNOT-A-REAL-DIRECTIVE\n')


def test_unterminated_mock_body_raises():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOCK CALL "X"\n'
        "        MOVE 0 TO RETURN-CODE\n"
        "    PERFORM MAIN\n"  # no END-MOCK: silently swallowed today
    )
    with pytest.raises(CutParseError, match="unterminated MOCK"):
        parse_cut(text)


def test_duplicate_perform_raises():
    text = 'TESTSUITE "s"\n' 'TESTCASE "c"\n' "    PERFORM ONE\n" "    PERFORM TWO\n"
    with pytest.raises(CutParseError, match="already has a PERFORM"):
        parse_cut(text)


# --- audit 3.1: a second TESTSUITE must be an error --------------------------


def test_second_testsuite_line_raises_with_line_number():
    text = (
        'TESTSUITE "first"\n'
        'TESTCASE "c"\n'
        "    PERFORM MAIN\n"
        'TESTSUITE "second"\n'
    )
    with pytest.raises(CutParseError, match="line 4: second TESTSUITE"):
        parse_cut(text)


# --- audit 3.2: END-MOCK robustness ------------------------------------------


@pytest.mark.parametrize(
    "terminator", ["END-MOCK", "END-MOCK.", "end-mock", "End-Mock."]
)
def test_end_mock_accepts_trailing_period_and_any_case(terminator):
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOCK CALL "X"\n'
        "        MOVE 0 TO RETURN-CODE\n"
        f"    {terminator}\n"
        "    PERFORM MAIN\n"
    )
    case = parse_cut(text).test_cases[0]
    assert case.mocks[0].body_lines == ["MOVE 0 TO RETURN-CODE"]
    assert case.perform_target == "MAIN"  # the terminator really closed the body


def test_other_keywords_stay_case_sensitive():
    with pytest.raises(CutParseError, match="unrecognized statement"):
        parse_cut('testsuite "s"\n')


# --- audit 3.3: VERIFY expectations validated at parse time ------------------


@pytest.mark.parametrize(
    "expectation", ["ONCE", "NEVER", "AT LEAST ONCE", "3 TIMES", "once"]
)
def test_valid_verify_expectations_parse(expectation):
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        "    PERFORM MAIN\n"
        f'    VERIFY "X" WAS CALLED {expectation}\n'
    )
    suite = parse_cut(text)
    assert suite.test_cases[0].verifications[0].expectation == expectation


@pytest.mark.parametrize("expectation", ["TWICE", "SOMETIMES", "TIMES 3"])
def test_invalid_verify_expectation_raises_with_line_number(expectation):
    """Previously exploded much later in driver codegen as a raw ValueError
    traceback with no .cut line number (audit 3.3)."""
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        "    PERFORM MAIN\n"
        f'    VERIFY "X" WAS CALLED {expectation}\n'
    )
    with pytest.raises(CutParseError, match="line 4: unrecognized VERIFY expectation"):
        parse_cut(text)


def test_invalid_bare_verify_expectation_also_raises():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        "    PERFORM MAIN\n"
        "    VERIFY READ INFILE WAS PERFORMED TWICE\n"
    )
    with pytest.raises(CutParseError, match="line 4"):
        parse_cut(text)


# --- audit 3.5/3.6: duplicate MOCKs, unterminated line no., empty keys -------


def test_duplicate_mock_key_in_one_testcase_raises_with_both_lines():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOCK CALL "X"\n'
        "    END-MOCK\n"
        '    MOCK CALL "X"\n'
        "    END-MOCK\n"
        "    PERFORM MAIN\n"
    )
    with pytest.raises(
        CutParseError,
        match=r"line 5: duplicate MOCK .*first declared at line 3",
    ):
        parse_cut(text)


def test_same_mock_key_in_different_testcases_is_fine():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "one"\n'
        '    MOCK CALL "X"\n'
        "    END-MOCK\n"
        "    PERFORM MAIN\n"
        'TESTCASE "two"\n'
        '    MOCK CALL "X"\n'
        "    END-MOCK\n"
        "    PERFORM MAIN\n"
    )
    assert len(parse_cut(text).test_cases) == 2


def test_unterminated_mock_error_carries_its_opening_line_number():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOCK CALL "X"\n'
        "        MOVE 0 TO RETURN-CODE\n"
    )
    with pytest.raises(CutParseError, match="line 3: unterminated MOCK"):
        parse_cut(text)


def test_empty_quoted_mock_key_rejected_at_parse_time():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOCK CALL ""\n'
        "    END-MOCK\n"
        "    PERFORM MAIN\n"
    )
    with pytest.raises(CutParseError, match="line 3: empty MOCK CALL key"):
        parse_cut(text)


# --- PROVIDER parameterized test cases: grammar ------------------------------


def test_provider_block_parses_without_affecting_unrelated_cases():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER StateNames\n"
        "    HEADER Abbreviation, Name\n"
        '    ROW "AZ", "Arizona"\n'
        '    ROW "KY", "Kentucky"\n'
        'TESTCASE "unrelated"\n'
        "    PERFORM MAIN\n"
    )
    suite = parse_cut(text)
    assert len(suite.test_cases) == 1
    assert suite.test_cases[0].name == "unrelated"


def test_provider_row_before_header_raises():
    text = 'TESTSUITE "s"\n' "PROVIDER StateNames\n" '    ROW "AZ", "Arizona"\n'
    with pytest.raises(CutParseError, match="line 3: ROW before HEADER"):
        parse_cut(text)


def test_provider_row_arity_mismatch_raises():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER StateNames\n"
        "    HEADER Abbreviation, Name\n"
        '    ROW "AZ"\n'
    )
    with pytest.raises(
        CutParseError,
        match=r"line 4: ROW has 1 value\(s\) but PROVIDER 'StateNames'.*2 column\(s\)",
    ):
        parse_cut(text)


def test_provider_with_zero_rows_raises():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER StateNames\n"
        "    HEADER Abbreviation, Name\n"
        'TESTCASE "c"\n'
        "    PERFORM MAIN\n"
    )
    with pytest.raises(
        CutParseError, match="line 2: PROVIDER 'StateNames' has no ROWs"
    ):
        parse_cut(text)


def test_duplicate_provider_name_raises_with_both_lines():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER StateNames\n"
        "    HEADER Abbreviation, Name\n"
        '    ROW "AZ", "Arizona"\n'
        "PROVIDER StateNames\n"
        "    HEADER Abbreviation, Name\n"
        '    ROW "KY", "Kentucky"\n'
    )
    with pytest.raises(
        CutParseError,
        match=r"line 5: duplicate PROVIDER 'StateNames' \(first declared at line 2\)",
    ):
        parse_cut(text)


def test_provider_before_testsuite_raises():
    with pytest.raises(CutParseError, match="line 1: PROVIDER before TESTSUITE"):
        parse_cut("PROVIDER StateNames\n    HEADER A, B\n    ROW 1, 2\n")


def test_header_outside_provider_raises():
    text = 'TESTSUITE "s"\n' "HEADER A, B\n"
    with pytest.raises(CutParseError, match="line 2: HEADER outside PROVIDER"):
        parse_cut(text)


def test_row_outside_provider_raises():
    text = 'TESTSUITE "s"\n' '    ROW "x"\n'
    with pytest.raises(CutParseError, match="line 2: ROW outside PROVIDER"):
        parse_cut(text)


def test_duplicate_header_in_provider_raises():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER StateNames\n"
        "    HEADER Abbreviation, Name\n"
        "    HEADER A, B\n"
    )
    with pytest.raises(
        CutParseError, match="line 4: duplicate HEADER in PROVIDER 'StateNames'"
    ):
        parse_cut(text)


def test_provider_row_values_preserve_commas_inside_quotes():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER Names\n"
        "    HEADER Full-Name\n"
        '    ROW "SMITH, JR."\n'
        'TESTCASE "c"\n'
        "    PERFORM MAIN\n"
    )
    # If the comma inside the quoted value had split the row into two
    # fields, this would raise a ROW-arity CutParseError against the
    # 1-column HEADER instead of parsing cleanly.
    suite = parse_cut(text)
    assert len(suite.test_cases) == 1


# --- PROVIDER parameterized test cases: binding & expansion ------------------

PROVIDER_CUT = """\
TESTSUITE "state lookup"

PROVIDER StateNames
    HEADER Abbreviation, Name
    ROW "AZ", "Arizona"
    ROW "KY", "Kentucky"
    ROW "XX", "*Undefined*"

TESTCASE "lookup state" USING PROVIDER StateNames
    MOVE {Abbreviation} TO WS-STATE-CODE
    PERFORM LOOKUP-STATE
    EXPECT WS-STATE-NAME TO BE {Name}
"""


def test_using_provider_expands_into_one_case_per_row():
    suite = parse_cut(PROVIDER_CUT)
    assert len(suite.test_cases) == 3


def test_expanded_case_names_and_substituted_values():
    suite = parse_cut(PROVIDER_CUT)
    names = [case.name for case in suite.test_cases]
    assert names == [
        "lookup state [row 1: AZ]",
        "lookup state [row 2: KY]",
        "lookup state [row 3: XX]",
    ]
    first = suite.test_cases[0]
    assert first.setup_moves == [('"AZ"', "WS-STATE-CODE")]
    assert first.expectations[0].expected_value == '"Arizona"'
    third = suite.test_cases[2]
    assert third.expectations[0].expected_value == '"*Undefined*"'


def test_expanded_case_line_points_at_its_own_row():
    suite = parse_cut(PROVIDER_CUT)
    # ROW "AZ" is line 5, ROW "KY" is line 6, ROW "XX" is line 7.
    assert [case.line for case in suite.test_cases] == [5, 6, 7]


PROVIDER_WITH_MOCK_AND_TAGS_CUT = """\
TESTSUITE "s"

PROVIDER Nums
    HEADER N
    ROW 1
    ROW 2

TESTCASE "c" TAGS "fast" USING PROVIDER Nums
    MOCK CALL "X"
        MOVE 0 TO RETURN-CODE
    END-MOCK
    MOVE {N} TO WS-N
    PERFORM MAIN
    VERIFY "X" WAS CALLED ONCE
"""


def test_mocks_tags_verify_inherited_unchanged_across_rows():
    suite = parse_cut(PROVIDER_WITH_MOCK_AND_TAGS_CUT)
    assert len(suite.test_cases) == 2
    for case in suite.test_cases:
        assert case.tags == ["fast"]
        assert len(case.mocks) == 1
        assert case.mocks[0].program_name == "X"
        assert case.verifications[0].expectation == "ONCE"
    assert suite.test_cases[0].setup_moves == [("1", "WS-N")]
    assert suite.test_cases[1].setup_moves == [("2", "WS-N")]


def test_value_with_no_placeholder_repeated_identically():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER Nums\n"
        "    HEADER N\n"
        "    ROW 1\n"
        "    ROW 2\n"
        'TESTCASE "c" USING PROVIDER Nums\n'
        "    MOVE 999 TO WS-FIXED\n"
        "    MOVE {N} TO WS-N\n"
        "    PERFORM MAIN\n"
    )
    suite = parse_cut(text)
    assert suite.test_cases[0].setup_moves == [("999", "WS-FIXED"), ("1", "WS-N")]
    assert suite.test_cases[1].setup_moves == [("999", "WS-FIXED"), ("2", "WS-N")]


def test_undeclared_provider_reference_raises():
    text = 'TESTSUITE "s"\n' 'TESTCASE "c" USING PROVIDER Ghost\n' "    PERFORM MAIN\n"
    with pytest.raises(
        CutParseError,
        match="line 2: TESTCASE 'c' uses PROVIDER 'Ghost', which was never declared",
    ):
        parse_cut(text)


def test_unknown_placeholder_raises():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER Nums\n"
        "    HEADER N\n"
        "    ROW 1\n"
        'TESTCASE "c" USING PROVIDER Nums\n'
        "    MOVE {Bogus} TO WS-N\n"
        "    PERFORM MAIN\n"
    )
    with pytest.raises(
        CutParseError,
        match=r"unknown placeholder \{Bogus\} in TESTCASE 'c'.*columns are N",
    ):
        parse_cut(text)


def test_non_provider_testcase_with_literal_braces_is_untouched():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOVE "{NotAPlaceholder}" TO WS-FIELD\n'
        "    PERFORM MAIN\n"
    )
    suite = parse_cut(text)
    assert suite.test_cases[0].setup_moves == [('"{NotAPlaceholder}"', "WS-FIELD")]


def test_placeholder_substitution_works_inside_a_larger_literal():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER Nums\n"
        "    HEADER N\n"
        "    ROW 1\n"
        'TESTCASE "c" USING PROVIDER Nums\n'
        "    PERFORM MAIN\n"
        '    EXPECT WS-MSG TO BE "value: {N}"\n'
    )
    suite = parse_cut(text)
    assert suite.test_cases[0].expectations[0].expected_value == '"value: 1"'


def test_placeholder_substitution_scoped_to_move_and_expect_values_only():
    """Verify placeholder tokens are substituted ONLY in MOVE values and
    EXPECT expected_values, never in MOVE targets, MOCK bodies, or EXPECT
    data_names. This pins the invariant from a final code review."""
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER TestData\n"
        "    HEADER N, Field\n"
        "    ROW 42, WS-RESULT\n"
        'TESTCASE "verify substitution scope" USING PROVIDER TestData\n'
        "    MOCK CALL \"HELPER\"\n"
        "        MOVE {N} TO WS-HELPER-VAL\n"
        "    END-MOCK\n"
        "    MOVE {N} TO WS-TARGET\n"
        "    PERFORM DO-SOMETHING\n"
        "    EXPECT {Field} TO BE {N}\n"
    )
    suite = parse_cut(text)
    assert len(suite.test_cases) == 1
    case = suite.test_cases[0]

    # Verify MOVE value is substituted, target is NOT
    assert case.setup_moves == [("42", "WS-TARGET")]

    # Verify MOCK body is NOT substituted (literal {N} remains)
    assert case.mocks[0].body_lines == ["MOVE {N} TO WS-HELPER-VAL"]

    # Verify EXPECT data_name is NOT substituted, expected_value IS
    assert case.expectations[0].data_name == "{Field}"
    assert case.expectations[0].expected_value == "42"
