"""Unit tests for the mock injector (generalized dispatch, v2)."""

from mockymock.dsl.model import (
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
)
from mockymock.splicer.injector import build_dispatch, build_exec_trap
from mockymock.splicer.naming import TallyRegistry


def _suite() -> MockTestSuite:
    case_one = MockTestCase(name="10% discount")
    case_one.mocks.append(
        MockDirective(
            MockCategory.CALL, "DISCRATE", body_lines=["MOVE 0.10 TO WS-DISCOUNT-PCT"]
        )
    )

    case_two = MockTestCase(name="Zero discount")
    case_two.mocks.append(
        MockDirective(
            MockCategory.CALL, "DISCRATE", body_lines=["MOVE 0.00 TO WS-DISCOUNT-PCT"]
        )
    )

    return MockTestSuite(name="ORDRPROC", test_cases=[case_one, case_two])


def _dispatch(suite, category=MockCategory.CALL, key="DISCRATE"):
    return build_dispatch(category, key, suite, TallyRegistry(suite))


def test_dispatch_increments_tally():
    joined = "\n".join(_dispatch(_suite()))
    assert "ADD 1 TO UT-DISCRATE-TALLY" in joined


def test_dispatch_has_one_when_branch_per_test_case():
    joined = "\n".join(_dispatch(_suite()))
    assert 'WHEN "001"' in joined
    assert 'WHEN "002"' in joined
    assert "MOVE 0.10 TO WS-DISCOUNT-PCT" in joined
    assert "MOVE 0.00 TO WS-DISCOUNT-PCT" in joined


def test_dispatch_has_when_other_error_fallback():
    joined = "\n".join(_dispatch(_suite()))
    assert "WHEN OTHER" in joined
    assert "DISCRATE reached" in joined
    assert "ADD 1 TO UT-FAIL-COUNT" in joined


def test_dispatch_excludes_test_cases_that_dont_mock_this_site():
    case_unrelated = MockTestCase(name="Doesn't mock DISCRATE")
    case_unrelated.mocks.append(MockDirective(MockCategory.CALL, "DISCRATE", []))
    suite = MockTestSuite(name="X", test_cases=[MockTestCase(name="a"), case_unrelated])
    joined = "\n".join(_dispatch(suite))
    assert 'WHEN "001"' not in joined
    assert 'WHEN "002"' in joined


def test_dispatch_empty_mock_body_emits_continue():
    case = MockTestCase(name="open is a no-op")
    case.mocks.append(MockDirective(MockCategory.OPEN, "INFILE", body_lines=[]))
    suite = MockTestSuite(name="X", test_cases=[case])
    joined = "\n".join(_dispatch(suite, MockCategory.OPEN, "INFILE"))
    assert "ADD 1 TO UT-OPEN-INFILE-TALLY" in joined
    assert "CONTINUE" in joined


def test_dispatch_file_category_tally_includes_category_word():
    case = MockTestCase(name="read")
    case.mocks.append(
        MockDirective(MockCategory.READ, "INFILE", body_lines=["MOVE 1 TO X"])
    )
    suite = MockTestSuite(name="X", test_cases=[case])
    joined = "\n".join(_dispatch(suite, MockCategory.READ, "INFILE"))
    assert "UT-READ-INFILE-TALLY" in joined


def test_sql_dispatch_error_text_has_no_quotes_inside_display():
    case = MockTestCase(name="sql")
    case.mocks.append(
        MockDirective(MockCategory.SQL, "UPDATE ORDERS", body_lines=["MOVE 0 TO SQLCODE"])
    )
    suite = MockTestSuite(name="X", test_cases=[case])
    lines = _dispatch(suite, MockCategory.SQL, "UPDATE ORDERS")
    display = next(line for line in lines if "__MOCKYMOCK__ ERROR" in line)
    # the literal is delimited by exactly one pair of quotes
    assert display.count('"') == 2


def test_exec_trap_displays_and_fails():
    lines = build_exec_trap("SQL", 42)
    joined = "\n".join(lines)
    assert "unmocked EXEC SQL reached (line 42)" in joined
    assert "ADD 1 TO UT-FAIL-COUNT" in joined
