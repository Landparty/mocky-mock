"""Unit tests for the mock injector (Task 11)."""

from mockymock.dsl.model import MockCallDirective, MockTestCase, MockTestSuite
from mockymock.splicer.injector import build_call_dispatch, tally_field_name


def _suite() -> MockTestSuite:
    case_one = MockTestCase(name="10% discount")
    case_one.mocks.append(
        MockCallDirective(
            program_name="DISCRATE", body_lines=["MOVE 0.10 TO WS-DISCOUNT-PCT"]
        )
    )

    case_two = MockTestCase(name="Zero discount")
    case_two.mocks.append(
        MockCallDirective(
            program_name="DISCRATE", body_lines=["MOVE 0.00 TO WS-DISCOUNT-PCT"]
        )
    )

    return MockTestSuite(name="ORDRPROC", test_cases=[case_one, case_two])


def test_tally_field_name_is_call_name_uppercased():
    assert tally_field_name("DISCRATE") == "UT-DISCRATE-TALLY"


def test_tally_field_name_sanitizes_non_cobol_name_chars():
    assert tally_field_name("sub.pgm 01") == "UT-SUB-PGM-01-TALLY"


def test_dispatch_increments_tally():
    lines = build_call_dispatch("DISCRATE", _suite())
    joined = "\n".join(lines)
    assert "ADD 1 TO UT-DISCRATE-TALLY" in joined


def test_dispatch_has_one_when_branch_per_test_case():
    lines = build_call_dispatch("DISCRATE", _suite())
    joined = "\n".join(lines)
    assert 'WHEN "001"' in joined
    assert 'WHEN "002"' in joined
    assert "MOVE 0.10 TO WS-DISCOUNT-PCT" in joined
    assert "MOVE 0.00 TO WS-DISCOUNT-PCT" in joined


def test_dispatch_has_when_other_error_fallback():
    lines = build_call_dispatch("DISCRATE", _suite())
    joined = "\n".join(lines)
    assert "WHEN OTHER" in joined
    assert "DISCRATE called" in joined


def test_dispatch_excludes_test_cases_that_dont_mock_this_call():
    case_unrelated = MockTestCase(name="Doesn't mock DISCRATE")
    suite = MockTestSuite(name="X", test_cases=[case_unrelated])
    lines = build_call_dispatch("DISCRATE", suite)
    joined = "\n".join(lines)
    assert 'WHEN "001"' not in joined
    assert "WHEN OTHER" in joined
