"""Unit tests for the `*> STUB EXPECT` raw-text scanner backing
`mockymock run --record-expectations`. See
docs/2026-08-04-record-expectations-design.md."""

from mockymock.analysis.stub_expectations import scan_stub_expectations
from mockymock.dsl.parser import parse_cut


def _scan(text: str):
    suite = parse_cut(text)
    return scan_stub_expectations(text, suite), suite


ONE_CASE = """\
TESTSUITE "S"

TESTCASE "calc"
    MOCK CALL "DISCOUNT"
        MOVE 5 TO RETURN-CODE
    END-MOCK
    PERFORM CALC-TOTALS
    EXPECT WS-DISCOUNT-CODE TO BE 5
    *> STUB EXPECT WS-NET-TOTAL -- computed in CALC-TOTALS
"""


def test_stub_inside_an_ordinary_case_is_recorded():
    result, _ = _scan(ONE_CASE)
    assert len(result.stubs) == 1
    stub = result.stubs[0]
    assert stub.data_name == "WS-NET-TOTAL"
    assert stub.note == "computed in CALC-TOTALS"
    assert stub.case_index == 1
    assert result.skipped == []


def test_stub_line_number_is_the_comment_s_own_line():
    result, _ = _scan(ONE_CASE)
    stub = result.stubs[0]
    assert (
        ONE_CASE.splitlines()[stub.line - 1]
        .strip()
        .startswith("*> STUB EXPECT WS-NET-TOTAL")
    )


def test_stub_with_no_note_has_none_note():
    text = ONE_CASE.replace(
        "*> STUB EXPECT WS-NET-TOTAL -- computed in CALC-TOTALS",
        "*> STUB EXPECT WS-NET-TOTAL",
    )
    result, _ = _scan(text)
    assert result.stubs[0].note is None


def test_subscripted_stub_name_parses():
    text = ONE_CASE.replace(
        "*> STUB EXPECT WS-NET-TOTAL -- computed in CALC-TOTALS",
        "*> STUB EXPECT WS-TABLE(1, 1) -- computed in CALC-TOTALS",
    )
    result, _ = _scan(text)
    assert result.stubs[0].data_name == "WS-TABLE(1, 1)"


def test_stub_before_any_testcase_is_skipped():
    text = """\
TESTSUITE "S"

*> STUB EXPECT WS-EARLY -- no case yet
TESTCASE "calc"
    PERFORM CALC-TOTALS
"""
    result, _ = _scan(text)
    assert result.stubs == []
    assert len(result.skipped) == 1
    assert result.skipped[0].data_name == "WS-EARLY"
    assert "not inside any TESTCASE" in result.skipped[0].reason


def test_stub_inside_provider_templated_case_is_skipped():
    text = """\
TESTSUITE "S"

PROVIDER RATES
    HEADER PCT
    ROW 0.10
    ROW 0.20

TESTCASE "calc" USING PROVIDER RATES
    MOVE {PCT} TO WS-DISCOUNT-PCT
    PERFORM CALC-TOTALS
    *> STUB EXPECT WS-NET-TOTAL -- computed in CALC-TOTALS
"""
    result, _ = _scan(text)
    assert result.stubs == []
    assert len(result.skipped) == 1
    assert result.skipped[0].data_name == "WS-NET-TOTAL"
    assert "PROVIDER" in result.skipped[0].reason
    assert "unsupported in v1" in result.skipped[0].reason


def test_stub_shaped_comment_inside_a_mock_body_is_ignored_entirely():
    """A mock body's contents are opaque free-form COBOL to the real .cut
    parser (dsl.md) -- a stub-shaped line inside one is inert COBOL-comment
    text, not a directive. It must not appear in stubs OR skipped: treating
    it as a real (if unattributable) stub risks the rewrite step later
    corrupting a MOCK body with an injected EXPECT line."""
    text = """\
TESTSUITE "S"

TESTCASE "calc"
    MOCK CALL "DISCOUNT"
        *> STUB EXPECT WS-DECOY -- not a real directive
        MOVE 5 TO RETURN-CODE
    END-MOCK
    PERFORM CALC-TOTALS
"""
    result, _ = _scan(text)
    assert result.stubs == []
    assert result.skipped == []


def test_two_stubs_in_the_same_case_share_its_case_index():
    text = """\
TESTSUITE "S"

TESTCASE "calc"
    PERFORM CALC-TOTALS
    *> STUB EXPECT WS-NET-TOTAL -- one
    *> STUB EXPECT WS-TAX-TOTAL -- two
"""
    result, _ = _scan(text)
    assert [s.data_name for s in result.stubs] == ["WS-NET-TOTAL", "WS-TAX-TOTAL"]
    assert result.stubs[0].case_index == 1
    assert result.stubs[1].case_index == 1


def test_second_testcase_gets_the_second_case_index():
    text = """\
TESTSUITE "S"

TESTCASE "first"
    PERFORM FIRST-PARA
    *> STUB EXPECT WS-A -- in first

TESTCASE "second"
    PERFORM SECOND-PARA
    *> STUB EXPECT WS-B -- in second
"""
    result, _ = _scan(text)
    by_name = {s.data_name: s.case_index for s in result.stubs}
    assert by_name == {"WS-A": 1, "WS-B": 2}


def test_stub_case_sensitivity_matches_dsl_convention():
    """Every other DSL keyword is case-sensitive uppercase; a lowercase
    "stub expect" must not be mistaken for the directive."""
    text = """\
TESTSUITE "S"

TESTCASE "calc"
    PERFORM CALC-TOTALS
    *> stub expect WS-NET-TOTAL -- not a real directive in this casing
"""
    result, _ = _scan(text)
    assert result.stubs == []
    assert result.skipped == []


def test_case_excluded_by_filtering_is_skipped_not_misattributed():
    """Simulates checks.filter_suite_cases removing an unselected case from
    suite.test_cases before the scanner runs (the same object build_driver
    will iterate) -- the excluded case's stub must be reported skipped, not
    silently attributed to whichever case now sits at its old index."""
    text = """\
TESTSUITE "S"

TESTCASE "first"
    PERFORM FIRST-PARA
    *> STUB EXPECT WS-A -- in first

TESTCASE "second"
    PERFORM SECOND-PARA
    *> STUB EXPECT WS-B -- in second
"""
    suite = parse_cut(text)
    # Keep only "second" -- as --case "second" would.
    suite.test_cases = [c for c in suite.test_cases if c.name == "second"]

    result = scan_stub_expectations(text, suite)

    by_name = {s.data_name: s.case_index for s in result.stubs}
    assert by_name == {"WS-B": 1}  # "second" is now index 1 in the filtered list
    skipped_names = {s.data_name: s.reason for s in result.skipped}
    assert "WS-A" in skipped_names
    assert "not run this time" in skipped_names["WS-A"]


def test_stub_inside_provider_block_is_skipped_not_credited_to_previous_case():
    """A PROVIDER block closes the preceding TESTCASE (the parser resets
    case state when one opens), so a stub comment inside the PROVIDER's
    HEADER/ROW lines belongs to no case. It used to be attributed to the
    nearest preceding TESTCASE header, and --record-expectations would
    write an EXPECT into a case the author never put it in."""
    text = """\
TESTSUITE "S"

TESTCASE "plain"
    PERFORM MAIN-PARA

PROVIDER AMOUNTS
    *> STUB EXPECT WS-TOTAL -- about the provider rows
    HEADER AMT
    ROW 1

TESTCASE "templated {AMT}" USING PROVIDER AMOUNTS
    PERFORM MAIN-PARA
"""
    result, _ = _scan(text)
    assert result.stubs == []
    assert len(result.skipped) == 1
    assert result.skipped[0].data_name == "WS-TOTAL"
    assert "PROVIDER block" in result.skipped[0].reason
