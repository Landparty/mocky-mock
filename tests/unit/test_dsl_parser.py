import pytest

from mockymock.dsl.model import MockCategory
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


# --- EXPECT data-name subscripts ---------------------------------------------


@pytest.mark.parametrize(
    "subscript",
    ["(1, 1)", "(1 1)", "(1,1)", "(WS-IDX-1, WS-IDX-2)", "(1: 5)"],
)
def test_expect_subscripted_table_name_parses(subscript):
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        "    PERFORM MAIN\n"
        f"    EXPECT WS-TABLE{subscript} TO BE 100\n"
    )
    case = parse_cut(text).test_cases[0]
    assert case.expectations[0].data_name == f"WS-TABLE{subscript}"
    assert case.expectations[0].expected_value == "100"


def test_expect_unsubscripted_name_still_parses():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        "    PERFORM MAIN\n"
        "    EXPECT WS-RESULT TO BE 100\n"
    )
    case = parse_cut(text).test_cases[0]
    assert case.expectations[0].data_name == "WS-RESULT"


def test_expect_unbalanced_paren_raises():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        "    PERFORM MAIN\n"
        "    EXPECT WS-A ( TO BE 5\n"
    )
    with pytest.raises(CutParseError, match="unrecognized statement"):
        parse_cut(text)


# --- MOVE target subscripts --------------------------------------------------


@pytest.mark.parametrize(
    "subscript",
    ["(1, 1)", "(1 1)", "(1,1)", "(WS-IDX-1, WS-IDX-2)", "(1: 5)"],
)
def test_move_subscripted_table_target_parses(subscript):
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        f"    MOVE 100 TO WS-TABLE{subscript}\n"
        "    PERFORM MAIN\n"
    )
    case = parse_cut(text).test_cases[0]
    assert case.setup_moves == [("100", f"WS-TABLE{subscript}")]


def test_move_subscripted_value_and_target_both_parse():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        "    MOVE WS-A(1, 1) TO WS-B(2, 2)\n"
        "    PERFORM MAIN\n"
    )
    case = parse_cut(text).test_cases[0]
    assert case.setup_moves == [("WS-A(1, 1)", "WS-B(2, 2)")]


def test_move_unsubscripted_target_still_parses():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        "    MOVE 100 TO WS-RESULT\n"
        "    PERFORM MAIN\n"
    )
    case = parse_cut(text).test_cases[0]
    assert case.setup_moves == [("100", "WS-RESULT")]


def test_move_unbalanced_paren_target_raises():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        "    MOVE 100 TO WS-A (\n"
        "    PERFORM MAIN\n"
    )
    with pytest.raises(CutParseError, match="unrecognized statement"):
        parse_cut(text)


# 2026-08-12 audit Finding 4: with NO space before the stray paren, the
# _SUBSCRIPTED_NAME fragment's first alternative fails (no closing paren)
# and the `\S+` fallback -- meant only for {Placeholder} tokens -- silently
# swallowed the whole malformed token as one opaque name ('WS-TAB(1'),
# producing a syntactically invalid COBOL target that only surfaced later
# as a confusing cobc compile error. The spaced form above was already
# covered; these no-space forms were the actual gap.
@pytest.mark.parametrize("target", ["WS-TAB(1", "WS-TAB(1))"])
def test_move_no_space_unbalanced_paren_target_raises(target):
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        f"    MOVE 100 TO {target}\n"
        "    PERFORM MAIN\n"
    )
    with pytest.raises(CutParseError, match="unbalanced"):
        parse_cut(text)


@pytest.mark.parametrize("name", ["WS-X(1", "WS-X(1))"])
def test_expect_no_space_unbalanced_paren_raises(name):
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        "    PERFORM MAIN\n"
        f"    EXPECT {name} TO BE 5\n"
    )
    with pytest.raises(CutParseError, match="unbalanced"):
        parse_cut(text)


def test_capture_no_space_unbalanced_paren_target_raises():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOCK CALL "SUBPGM"\n'
        "        CAPTURE ARG 1 INTO WS-X(1\n"
        "    END-MOCK\n"
        "    PERFORM MAIN\n"
    )
    with pytest.raises(CutParseError, match="unbalanced"):
        parse_cut(text)


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


def test_stray_move_inside_open_provider_raises():
    # Regression: a PROVIDER block never used to reset the current-testcase
    # state, so a MOVE placed between/after ROW lines silently attached to
    # the PREVIOUS TESTCASE (with its {Placeholder} left unsubstituted)
    # instead of being rejected. Must fail closed instead.
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "prev"\n'
        '    MOVE "1" TO WS-A\n'
        "    PERFORM MAIN\n"
        "PROVIDER P\n"
        "    HEADER N\n"
        '    ROW "5"\n'
        "    MOVE {N} TO WS-X\n"
        'TESTCASE "uses" USING PROVIDER P\n'
        "    MOVE {N} TO WS-B\n"
        "    PERFORM MAIN\n"
    )
    with pytest.raises(
        CutParseError,
        match=r"line 8: .*not allowed inside PROVIDER 'P'.*HEADER and ROW",
    ):
        parse_cut(text)


def test_provider_row_trailing_comma_missing_value_raises():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER StateNames\n"
        "    HEADER Abbreviation, Name\n"
        '    ROW "AZ",\n'
    )
    with pytest.raises(
        CutParseError,
        match=r"line 4: ROW value for column 'Name' in PROVIDER 'StateNames' "
        r"is blank",
    ):
        parse_cut(text)


def test_stray_mock_inside_open_provider_raises():
    # A preceding TESTCASE is essential to this regression: without one,
    # mock_target is already None and the buggy code rejects the MOCK on
    # its own merits ("MOCK outside TESTCASE/BEFORE-EACH/BEFORE-ALL"),
    # which doesn't exercise the bug at all. With a preceding TESTCASE,
    # mock_target still points at "prev".mocks while the PROVIDER is open,
    # so the buggy code would silently attach this MOCK to "prev" instead
    # of raising.
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "prev"\n'
        "    PERFORM MAIN\n"
        "PROVIDER P\n"
        "    HEADER N\n"
        '    ROW "5"\n'
        '    MOCK CALL "SUB"\n'
        "    END-MOCK\n"
    )
    with pytest.raises(
        CutParseError,
        match=r"line 7: .*not allowed inside PROVIDER 'P'.*HEADER and ROW",
    ):
        parse_cut(text)


def test_provider_row_bare_blank_value_between_commas_raises():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER Triple\n"
        "    HEADER A, B, C\n"
        '    ROW "x", , "z"\n'
    )
    with pytest.raises(
        CutParseError,
        match=r"line 4: ROW value for column 'B' in PROVIDER 'Triple' is blank",
    ):
        parse_cut(text)


def test_row_after_intervening_before_each_block_raises():
    # Related leniency: BEFORE-ALL/BEFORE-EACH didn't close an open
    # PROVIDER, so a ROW line appearing after an intervening END-BEFORE
    # would still append to the provider opened earlier. The simplest
    # consistent rule: BEFORE-EACH/BEFORE-ALL appearing while a PROVIDER is
    # open is itself an error (a PROVIDER block may hold only HEADER/ROW,
    # and is closed only by the next TESTCASE or PROVIDER).
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER P\n"
        "    HEADER N\n"
        '    ROW "1"\n'
        "BEFORE-EACH\n"
        '    MOCK CALL "SUB"\n'
        "    END-MOCK\n"
        "END-BEFORE\n"
        '    ROW "2"\n'
        'TESTCASE "c" USING PROVIDER P\n'
        "    PERFORM MAIN\n"
    )
    with pytest.raises(
        CutParseError,
        match=r"line 5: .*not allowed inside PROVIDER 'P'.*HEADER and ROW",
    ):
        parse_cut(text)


def test_statelkup_example_still_parses():
    # examples/statelkup/STATELKUP.cut is the canonical real-world usage of
    # PROVIDER/HEADER/ROW; must keep parsing after the fail-closed fix.
    import pathlib

    cut_path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "examples"
        / "statelkup"
        / "STATELKUP.cut"
    )
    suite = parse_cut(cut_path.read_text())
    assert len(suite.test_cases) == 3


def test_provider_row_quoted_empty_string_value_is_accepted():
    # A quoted "" is a deliberate empty COBOL literal. It is distinguishable
    # from a missing/blank entry because the quote characters survive
    # .strip() -- only the missing/blank form (nothing at all between the
    # commas) is fail-closed rejected; a quoted "" is accepted and
    # substitutes as the literal two-character string.
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER StateNames\n"
        "    HEADER Abbreviation, Name\n"
        '    ROW "AZ", ""\n'
        'TESTCASE "c" USING PROVIDER StateNames\n'
        "    MOVE {Name} TO WS-NAME\n"
        "    PERFORM MAIN\n"
    )
    suite = parse_cut(text)
    assert suite.test_cases[0].setup_moves == [('""', "WS-NAME")]


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
    data_names. This pins the invariant from a final code review.

    Changed 2026-09-28: a PROVIDER column token in a NAME position (MOVE
    target, EXPECT data-name, PERFORM target) is now a parse error instead
    of being carried through verbatim -- it passed lint and then broke cobc
    (see test_provider_placeholder_in_a_name_position_raises).
    A non-column token in a MOCK body still stays literal."""
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER TestData\n"
        "    HEADER N, Field\n"
        "    ROW 42, WS-RESULT\n"
        'TESTCASE "verify substitution scope" USING PROVIDER TestData\n'
        '    MOCK CALL "HELPER"\n'
        "        MOVE {Other} TO WS-HELPER-VAL\n"
        "    END-MOCK\n"
        "    MOVE {N} TO WS-TARGET\n"
        "    PERFORM DO-SOMETHING\n"
        "    EXPECT WS-RESULT TO BE {N}\n"
    )
    suite = parse_cut(text)
    assert len(suite.test_cases) == 1
    case = suite.test_cases[0]

    # Verify MOVE value is substituted, target is NOT
    assert case.setup_moves == [("42", "WS-TARGET")]

    # Verify MOCK body is NOT substituted (a non-column token stays literal;
    # one naming a provider column is refused outright -- see
    # test_provider_placeholder_inside_mock_body_raises_at_its_line)
    assert case.mocks[0].body_lines == ["MOVE {Other} TO WS-HELPER-VAL"]

    # Verify EXPECT data_name is NOT substituted, expected_value IS
    assert case.expectations[0].data_name == "WS-RESULT"
    assert case.expectations[0].expected_value == "42"


@pytest.mark.parametrize(
    "line, where",
    [
        ("    MOVE 1 TO {Field}", "MOVE target"),
        ("    EXPECT {Field} TO BE {N}", "EXPECT data-name"),
    ],
)
def test_provider_placeholder_in_a_name_position_raises(line, where):
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER TestData\n"
        "    HEADER N, Field\n"
        "    ROW 42, WS-RESULT\n"
        'TESTCASE "c" USING PROVIDER TestData\n'
    )
    # A setup MOVE goes above the PERFORM, an EXPECT below it (issue #150).
    if line.strip().startswith("MOVE"):
        text += f"{line}\n    PERFORM DO-SOMETHING\n"
    else:
        text += f"    PERFORM DO-SOMETHING\n{line}\n"
    with pytest.raises(CutParseError, match=where):
        parse_cut(text)


def test_provider_placeholder_as_perform_target_raises():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER TestData\n"
        "    HEADER N, Para\n"
        "    ROW 42, MAIN-PARA\n"
        'TESTCASE "c" USING PROVIDER TestData\n'
        "    PERFORM {Para}\n"
    )
    with pytest.raises(CutParseError, match="PERFORM target"):
        parse_cut(text)


# -- ROWS on MOCK READ + TERMINAL group (with-data design 2026-08-04) --------

CUT_READ_ROWS = """\
TESTSUITE "read rows"
TESTCASE "case"
    MOCK READ ORDER-FILE ROWS
        ( ORDER-QTY = 50, ORDER-ID = "A1" )
        ( ORDER-QTY = 75, ORDER-ID = "A2" )
        TERMINAL ( WS-EOF-FLAG = "Y" )
    END-MOCK
    PERFORM MAIN-PARA
"""


def test_read_rows_with_terminal_parses():
    suite = parse_cut(CUT_READ_ROWS)
    mock = suite.test_cases[0].mocks[0]
    assert mock.category is MockCategory.READ
    assert mock.key == "ORDER-FILE"
    assert mock.rows == [
        [("ORDER-QTY", "50"), ("ORDER-ID", '"A1"')],
        [("ORDER-QTY", "75"), ("ORDER-ID", '"A2"')],
    ]
    assert mock.terminal_row == [("WS-EOF-FLAG", '"Y"')]
    assert mock.body_lines == []


def test_read_rows_without_terminal_parses():
    suite = parse_cut(
        CUT_READ_ROWS.replace('        TERMINAL ( WS-EOF-FLAG = "Y" )\n', "")
    )
    assert suite.test_cases[0].mocks[0].terminal_row is None


def test_rows_on_open_is_rejected():
    bad = CUT_READ_ROWS.replace(
        "MOCK READ ORDER-FILE ROWS", "MOCK OPEN ORDER-FILE ROWS"
    )
    with pytest.raises(CutParseError, match="ROWS is only supported"):
        parse_cut(bad)


def test_terminal_inside_sql_rows_is_rejected():
    bad = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK SQL "FETCH" ROWS
        ( X = 1 )
        TERMINAL ( Y = 2 )
    END-MOCK
    PERFORM P
"""
    with pytest.raises(CutParseError, match="TERMINAL"):
        parse_cut(bad)


def test_duplicate_terminal_is_rejected():
    bad = CUT_READ_ROWS.replace(
        '        TERMINAL ( WS-EOF-FLAG = "Y" )',
        '        TERMINAL ( WS-EOF-FLAG = "Y" )\n'
        '        TERMINAL ( WS-EOF-FLAG = "N" )',
    )
    with pytest.raises(CutParseError, match="duplicate TERMINAL"):
        parse_cut(bad)


# --- sentence-terminating periods in MOCK bodies ------------------------------
# Body text is spliced verbatim into a WHEN branch of the generated
# EVALUATE UT-CURRENT-CASE: a trailing `.` (the COBOL sentence habit) ended
# the sentence mid-EVALUATE, so `lint` passed and cobc then failed on
# generated code ("unexpected END-EVALUATE").


def _cut_with_body(body_line: str) -> str:
    return (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOCK CALL "SUBX"\n'
        f"        {body_line}\n"
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
    )


@pytest.mark.parametrize(
    "body_line",
    [
        "MOVE 5 TO WS-A.",
        "MOVE 5 TO WS-A. MOVE 6 TO WS-B",
        "MOVE 5 TO WS-A .   *> set the return value",
    ],
)
def test_sentence_period_in_mock_body_fails_closed(body_line):
    with pytest.raises(CutParseError, match="line 4: .* ends a COBOL sentence"):
        parse_cut(_cut_with_body(body_line))


@pytest.mark.parametrize(
    "body_line",
    [
        "MOVE 1.5 TO WS-RATE",
        'MOVE "DONE. OK." TO WS-MSG',
        "MOVE 'A.' TO WS-MSG",
        "MOVE 0 TO RETURN-CODE *> no period needed.",
        "*> a comment line may end with a period.",
    ],
)
def test_periods_that_do_not_end_a_sentence_are_kept(body_line):
    suite = parse_cut(_cut_with_body(body_line))
    assert suite.test_cases[0].mocks[0].body_lines == [body_line]


def test_sentence_period_in_a_rows_value_fails_closed():
    bad = CUT_READ_ROWS.replace(
        '        TERMINAL ( WS-EOF-FLAG = "Y" )',
        "        TERMINAL ( WS-EOF-FLAG = 1. )",
    )
    with pytest.raises(CutParseError, match="ends a COBOL sentence"):
        parse_cut(bad)


def test_provider_placeholder_inside_mock_body_raises_at_its_line():
    """PROVIDER values are substituted into MOVE/EXPECT values only; a MOCK
    body is spliced verbatim. A `{Column}` token there used to lint clean
    and then fail cobc with `invalid symbol '{'` in generated code."""
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER AMTS\n"
        "    HEADER AMT, RES\n"
        "    ROW 50, 2\n"
        'TESTCASE "amt {AMT}" USING PROVIDER AMTS\n'
        '    MOCK CALL "GETAMT"\n'
        "        MOVE {AMT} TO WS-AMT\n"
        "    END-MOCK\n"
        "    PERFORM MAIN\n"
        "    EXPECT WS-RES TO BE {RES}\n"
    )
    with pytest.raises(
        CutParseError,
        match=r'line 7: placeholder \{AMT\} inside MOCK CALL "GETAMT"',
    ):
        parse_cut(text)


def test_braces_in_mock_body_of_unbound_case_or_comment_still_parse():
    """Only a token naming the bound PROVIDER's own column is refused: a
    case with no PROVIDER, or a `*>` comment in the body, is untouched."""
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER AMTS\n"
        "    HEADER AMT\n"
        "    ROW 50\n"
        'TESTCASE "amt {AMT}" USING PROVIDER AMTS\n'
        '    MOCK CALL "GETAMT"\n'
        "        *> would like {AMT} here one day\n"
        '        MOVE "{OTHER}" TO WS-TXT\n'
        "    END-MOCK\n"
        "    PERFORM MAIN\n"
        'TESTCASE "plain"\n'
        '    MOCK CALL "GETAMT"\n'
        '        MOVE "{AMT}" TO WS-TXT\n'
        "    END-MOCK\n"
        "    PERFORM MAIN\n"
    )
    suite = parse_cut(text)
    assert len(suite.test_cases) == 2


def test_perform_names_are_upper_cased_but_placeholders_kept_verbatim():
    """Issue #164: COBOL names are case-insensitive, so a .cut PERFORM
    target and THRU end are upper-cased like bare MOCK keys. A `{Column}`
    token is not a COBOL name and stays as written, so the provider
    placeholder refusal still names it exactly."""
    suite = parse_cut(
        'TESTSUITE "s"\n'
        'TESTCASE "lower"\n'
        "    PERFORM read-one THRU Read-One-Exit\n"
        'TESTCASE "placeholder"\n'
        "    PERFORM {Para}\n"
    )

    assert suite.test_cases[0].perform_target == "READ-ONE"
    assert suite.test_cases[0].perform_thru == "READ-ONE-EXIT"
    assert suite.test_cases[1].perform_target == "{Para}"
