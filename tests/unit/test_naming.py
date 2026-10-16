"""Unit tests for the (category, key) -> tally-field registry."""

import re

from mockymock.dsl.model import MockCategory, MockDirective, MockTestCase, MockTestSuite
from mockymock.splicer.naming import TallyRegistry, tally_name


def _suite_with(*mocks: MockDirective) -> MockTestSuite:
    case = MockTestCase(name="c", mocks=list(mocks), perform_target="P")
    return MockTestSuite(name="S", test_cases=[case])


def test_call_keeps_v1_field_shape():
    registry = TallyRegistry(_suite_with(MockDirective(MockCategory.CALL, "DISCRATE")))
    assert registry.name(MockCategory.CALL, "DISCRATE") == "UT-DISCRATE-TALLY"


def test_call_sanitizes_non_cobol_name_chars():
    registry = TallyRegistry(
        _suite_with(MockDirective(MockCategory.CALL, "sub.pgm 01"))
    )
    # Folding "." to "-" loses information ("sub-pgm 01" would sanitize the
    # same), so the name carries a hash of the full key (#314).
    name = registry.name(MockCategory.CALL, "sub.pgm 01")
    assert re.fullmatch(r"UT-SUB-PGM-01-[0-9A-F]{4}-TALLY", name)


def test_file_ops_prefix_the_category_word():
    registry = TallyRegistry(
        _suite_with(
            MockDirective(MockCategory.READ, "INFILE"),
            MockDirective(MockCategory.WRITE, "OUT-REC"),
        )
    )
    assert registry.name(MockCategory.READ, "INFILE") == "UT-READ-INFILE-TALLY"
    assert registry.name(MockCategory.WRITE, "OUT-REC") == "UT-WRITE-OUT-REC-TALLY"


def test_sql_key_is_sanitized_and_capped():
    key = "UPDATE ORDERS SET STATUS = 'X' WHERE ID = :WS-ID"
    registry = TallyRegistry(_suite_with(MockDirective(MockCategory.SQL, key)))
    name = registry.name(MockCategory.SQL, key)
    assert name.startswith("UT-SQL-UPDATE-ORDER")
    assert len(name) <= 30
    assert "--" not in name


def test_colliding_sanitized_keys_get_distinct_names():
    key_a = "UPDATE ORDERS SET STATUS-A-VERY-LONG-TAIL-1"
    key_b = "UPDATE ORDERS SET STATUS-A-VERY-LONG-TAIL-2"
    registry = TallyRegistry(
        _suite_with(
            MockDirective(MockCategory.SQL, key_a),
            MockDirective(MockCategory.SQL, key_b),
        )
    )
    name_a = registry.name(MockCategory.SQL, key_a)
    name_b = registry.name(MockCategory.SQL, key_b)
    assert name_a != name_b
    assert len(name_b) <= 30


def test_same_key_across_cases_registered_once():
    case_one = MockTestCase(
        name="a", mocks=[MockDirective(MockCategory.CALL, "X")], perform_target="P"
    )
    case_two = MockTestCase(
        name="b", mocks=[MockDirective(MockCategory.CALL, "X")], perform_target="P"
    )
    registry = TallyRegistry(MockTestSuite(name="S", test_cases=[case_one, case_two]))
    assert len(registry.items()) == 1


def test_known_reports_membership():
    registry = TallyRegistry(_suite_with(MockDirective(MockCategory.DLI, "GU")))
    assert registry.known(MockCategory.DLI, "GU")
    assert not registry.known(MockCategory.SQL, "GU")


# --- #314: a tally name never depends on which other keys the suite holds ---

_OLD = MockDirective(MockCategory.READ, "CUSTOMER-MASTER-OLD")
_TRANS = MockDirective(MockCategory.READ, "CUSTOMER-MASTER-TRANS")


def test_names_cut_at_the_cap_do_not_depend_on_mock_order():
    one = TallyRegistry(_suite_with(_OLD, _TRANS))
    two = TallyRegistry(_suite_with(_TRANS, _OLD))
    alone = TallyRegistry(_suite_with(_OLD))
    old = one.name(MockCategory.READ, "CUSTOMER-MASTER-OLD")
    trans = one.name(MockCategory.READ, "CUSTOMER-MASTER-TRANS")
    assert old != trans
    assert two.name(MockCategory.READ, "CUSTOMER-MASTER-OLD") == old
    assert two.name(MockCategory.READ, "CUSTOMER-MASTER-TRANS") == trans
    assert alone.name(MockCategory.READ, "CUSTOMER-MASTER-OLD") == old
    assert re.fullmatch(r"UT-READ-CUSTOMER-MA-[0-9A-F]{4}-TALLY", old)
    assert len(old) <= 30


def test_tally_name_is_the_registry_name():
    registry = TallyRegistry(_suite_with(_TRANS, _OLD))
    for (category, key), name in registry.items():
        assert tally_name(category, key) == name
