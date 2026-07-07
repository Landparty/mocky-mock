"""Unit tests for the mock injector (per-site dispatch, v2)."""

import pytest

from mockymock.analysis.mock_surface import BoundarySite
from mockymock.dsl.model import (
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
)
from mockymock.splicer.injector import build_exec_trap, build_site_dispatch
from mockymock.splicer.naming import TallyRegistry


def _site(
    category=MockCategory.CALL, label="CALL", keys=("DISCRATE",), match_text=None
):
    return BoundarySite(
        category=category,
        label=label,
        keys=keys,
        match_text=match_text,
        paragraph_name="P",
        line=10,
        nested=False,
        statement=object(),
    )


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


def _dispatch(suite, site=None):
    return build_site_dispatch(site or _site(), suite, TallyRegistry(suite))


def test_dispatch_increments_tally_inside_when_branch():
    lines = _dispatch(_suite())
    when_001 = lines.index('               WHEN "001"')
    assert lines[when_001 + 1].strip() == "ADD 1 TO UT-DISCRATE-TALLY"


def test_dispatch_has_one_when_branch_per_test_case():
    joined = "\n".join(_dispatch(_suite()))
    assert 'WHEN "001"' in joined
    assert 'WHEN "002"' in joined
    assert "MOVE 0.10 TO WS-DISCOUNT-PCT" in joined
    assert "MOVE 0.00 TO WS-DISCOUNT-PCT" in joined


def test_dispatch_has_when_other_error_fallback():
    joined = "\n".join(_dispatch(_suite()))
    assert "WHEN OTHER" in joined
    assert "CALL boundary (line 10) reached" in joined
    assert "ADD 1 TO UT-FAIL-COUNT" in joined


def test_dispatch_excludes_test_cases_that_dont_mock_this_site():
    suite = _suite()
    suite.test_cases.insert(0, MockTestCase(name="unrelated"))
    joined = "\n".join(_dispatch(suite))
    assert 'WHEN "001"' not in joined
    assert 'WHEN "002"' in joined
    assert 'WHEN "003"' in joined


def test_same_site_matched_via_different_keys_credits_each_cases_tally():
    """Case 1 mocks OPEN IN-FILE, case 2 mocks OPEN OUT-FILE; both match the
    one OPEN statement, and each WHEN branch increments its own tally."""
    site = _site(MockCategory.OPEN, "OPEN", keys=("IN-FILE", "OUT-FILE"))
    case_one = MockTestCase(
        name="a", mocks=[MockDirective(MockCategory.OPEN, "IN-FILE")]
    )
    case_two = MockTestCase(
        name="b", mocks=[MockDirective(MockCategory.OPEN, "OUT-FILE")]
    )
    suite = MockTestSuite(name="S", test_cases=[case_one, case_two])
    joined = "\n".join(_dispatch(suite, site))
    assert "ADD 1 TO UT-OPEN-IN-FILE-TALLY" in joined
    assert "ADD 1 TO UT-OPEN-OUT-FILE-TALLY" in joined


def test_sql_site_dispatch_matches_by_prefix():
    site = _site(
        MockCategory.SQL, "SQL", keys=(), match_text="UPDATE ORDERS SET STATUS = 'Y'"
    )
    case = MockTestCase(
        name="sql",
        mocks=[MockDirective(MockCategory.SQL, "UPDATE ORDERS", ["MOVE 0 TO SQLCODE"])],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    joined = "\n".join(_dispatch(suite, site))
    assert "MOVE 0 TO SQLCODE" in joined
    assert "ADD 1 TO UT-SQL-UPDATE-ORDERS-TALLY" in joined


def test_ambiguous_match_raises():
    site = _site(MockCategory.OPEN, "OPEN", keys=("IN-FILE", "OUT-FILE"))
    case = MockTestCase(
        name="a",
        mocks=[
            MockDirective(MockCategory.OPEN, "IN-FILE"),
            MockDirective(MockCategory.OPEN, "OUT-FILE"),
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    with pytest.raises(ValueError, match="AMBIGUOUS_MOCK"):
        _dispatch(suite, site)


def test_exec_trap_displays_and_fails():
    lines = build_exec_trap("SQL", 42)
    joined = "\n".join(lines)
    assert "unmocked EXEC SQL reached (line 42)" in joined
    assert "ADD 1 TO UT-FAIL-COUNT" in joined
