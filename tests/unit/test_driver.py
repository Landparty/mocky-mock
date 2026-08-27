"""Unit tests for the driver generator (generalized tallies/VERIFY, v2)."""

import pytest

from mockymock.dsl.model import (
    ExpectDirective,
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
    VerifyDirective,
)
from mockymock.splicer.driver import build_driver
from mockymock.splicer.naming import TallyRegistry


def _suite() -> MockTestSuite:
    case_one = MockTestCase(
        name="10% discount reduces net amount correctly",
        mocks=[
            MockDirective(
                MockCategory.CALL,
                "DISCRATE",
                body_lines=["MOVE 0.10 TO WS-DISCOUNT-PCT"],
            )
        ],
        setup_moves=[("100.00", "ORD-AMOUNT")],
        perform_target="PROCESS-ORDER",
        expectations=[ExpectDirective("WS-NET-AMOUNT", "90.00")],
        verifications=[VerifyDirective(MockCategory.CALL, "DISCRATE", "ONCE")],
    )
    return MockTestSuite(name="ORDRPROC discount calculation", test_cases=[case_one])


def _build(suite=None, reset_lines=None, record_targets=None):
    suite = suite or _suite()
    return build_driver(
        suite,
        reset_lines=reset_lines or [],
        registry=TallyRegistry(suite),
        record_targets=record_targets,
    )


def test_working_storage_declares_bookkeeping_fields():
    joined = "\n".join(_build().working_storage_lines)
    assert "UT-CURRENT-CASE" in joined
    assert "UT-DISCRATE-TALLY" in joined
    assert "UT-FAIL-COUNT" in joined


def test_extra_working_storage_lines_appended_after_bookkeeping_fields():
    suite = _suite()
    artifact = build_driver(
        suite,
        reset_lines=[],
        registry=TallyRegistry(suite),
        extra_working_storage_lines=[
            "01  DFHEIBLK.",
            "    05  EIBCALEN PIC S9(4) COMP.",
        ],
    )
    assert artifact.working_storage_lines[-2:] == [
        "01  DFHEIBLK.",
        "    05  EIBCALEN PIC S9(4) COMP.",
    ]


def test_extra_working_storage_lines_omitted_by_default():
    joined = "\n".join(_build().working_storage_lines)
    assert "DFHEIBLK" not in joined


def test_working_storage_declares_tally_per_mock_key():
    suite = _suite()
    suite.test_cases[0].mocks.append(MockDirective(MockCategory.READ, "INFILE"))
    suite.test_cases[0].mocks.append(MockDirective(MockCategory.SQL, "SELECT"))
    joined = "\n".join(_build(suite).working_storage_lines)
    assert "UT-READ-INFILE-TALLY" in joined
    assert "UT-SQL-SELECT-TALLY" in joined


def test_testsuite_paragraph_performs_each_case_and_stops():
    joined = "\n".join(_build().procedure_lines)
    assert "UT-TESTSUITE-" in joined
    assert "PERFORM UT-TESTCASE-001" in joined
    assert "STOP RUN" in joined
    assert "__MOCKYMOCK__ TESTSUITE: ORDRPROC discount calculation" in joined


def test_testcase_resets_and_sets_current_case():
    joined = "\n".join(_build(reset_lines=["MOVE 0 TO X"]).procedure_lines)
    assert "PERFORM UT-RESET-WORKING-STORAGE" in joined
    assert 'MOVE "001" TO UT-CURRENT-CASE' in joined
    assert "MOVE 0 TO UT-DISCRATE-TALLY" in joined


def test_testcase_resets_every_category_tally_it_mocks():
    suite = _suite()
    suite.test_cases[0].mocks.append(MockDirective(MockCategory.WRITE, "OUT-REC"))
    joined = "\n".join(_build(suite).procedure_lines)
    assert "MOVE 0 TO UT-WRITE-OUT-REC-TALLY" in joined


def test_testcase_emits_setup_moves_and_perform():
    joined = "\n".join(_build().procedure_lines)
    assert "MOVE 100.00 TO ORD-AMOUNT" in joined
    assert "PERFORM PROCESS-ORDER" in joined


def test_testcase_emits_expect_check():
    joined = "\n".join(_build().procedure_lines)
    assert "IF WS-NET-AMOUNT NOT = 90.00" in joined
    assert "__MOCKYMOCK__ CASE 001 FAIL:" in joined
    assert "ADD 1 TO UT-FAIL-COUNT" in joined


def test_expect_failure_message_includes_actual_value():
    joined = "\n".join(_build().procedure_lines)
    assert 'expected WS-NET-AMOUNT = 90.00, got " WS-NET-AMOUNT' in joined


def test_testcase_emits_verify_check():
    joined = "\n".join(_build().procedure_lines)
    assert "IF UT-DISCRATE-TALLY NOT = 1" in joined


def test_verify_failure_message_includes_actual_tally():
    joined = "\n".join(_build().procedure_lines)
    assert "MOVE UT-DISCRATE-TALLY TO UT-TALLY-EDITED" in joined
    assert 'WAS CALLED ONCE, got " FUNCTION TRIM(UT-TALLY-EDITED)' in joined


def test_tally_edited_field_declared_only_when_verifications_exist():
    assert "UT-TALLY-EDITED" in "\n".join(_build().working_storage_lines)
    suite = _suite()
    suite.test_cases[0].verifications = []
    joined = "\n".join(_build(suite).working_storage_lines)
    assert "UT-TALLY-EDITED" not in joined


def test_verify_on_file_op_uses_category_tally():
    suite = _suite()
    suite.test_cases[0].mocks.append(MockDirective(MockCategory.READ, "INFILE"))
    suite.test_cases[0].verifications.append(
        VerifyDirective(MockCategory.READ, "INFILE", "3 TIMES")
    )
    joined = "\n".join(_build(suite).procedure_lines)
    assert "IF UT-READ-INFILE-TALLY NOT = 3" in joined


def test_verify_without_matching_mock_raises():
    suite = _suite()
    suite.test_cases[0].verifications.append(
        VerifyDirective(MockCategory.SQL, "SELECT", "ONCE")
    )
    with pytest.raises(ValueError, match="no MOCK directive"):
        _build(suite)


def test_verify_without_matching_mock_in_same_case_raises():
    case_one = MockTestCase(
        name="case one",
        mocks=[MockDirective(MockCategory.READ, "INFILE")],
        perform_target="P1",
    )
    case_two = MockTestCase(
        name="case two",
        perform_target="P2",
        verifications=[VerifyDirective(MockCategory.READ, "INFILE", "ONCE")],
    )
    suite = MockTestSuite(name="x", test_cases=[case_one, case_two])
    with pytest.raises(ValueError, match="this TESTCASE"):
        _build(suite)


def test_quoted_expect_value_is_escaped_in_fail_display():
    """EXPECT WS-STATUS TO BE "OK" -- the IF condition keeps the literal
    as-is, but inside the generated DISPLAY literal the quotes must be
    doubled ("" is COBOL's quote escape) or cobc splits the literal and
    reads OK as an undefined identifier (found by compiling for real)."""
    suite = _suite()
    suite.test_cases[0].expectations.append(ExpectDirective("WS-STATUS", '"OK"'))
    joined = "\n".join(_build(suite).procedure_lines)
    assert 'IF WS-STATUS NOT = "OK"' in joined
    assert 'expected WS-STATUS = ""OK""' in joined


def test_testcase_brackets_with_start_and_end_markers():
    joined = "\n".join(_build().procedure_lines)
    assert (
        "__MOCKYMOCK__ CASE 001 START: 10% discount reduces net amount correctly"
        in joined
    )
    assert "__MOCKYMOCK__ CASE 001 END" in joined


def test_summary_line_uses_total_case_count():
    joined = "\n".join(_build().procedure_lines)
    assert "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=" in joined


def test_reset_working_storage_paragraph_included_when_lines_given():
    joined = "\n".join(_build(reset_lines=["MOVE 0 TO ORD-AMOUNT"]).procedure_lines)
    assert "UT-RESET-WORKING-STORAGE." in joined
    assert "MOVE 0 TO ORD-AMOUNT" in joined


def test_verify_fail_display_includes_category():
    suite = _suite()
    suite.test_cases[0].mocks.append(MockDirective(MockCategory.READ, "INFILE"))
    suite.test_cases[0].verifications.append(
        VerifyDirective(MockCategory.READ, "INFILE", "3 TIMES")
    )
    joined = "\n".join(_build(suite).procedure_lines)
    assert "VERIFY READ INFILE WAS CALLED 3 TIMES" in joined


def test_suite_paragraph_name_is_a_valid_cobol_word():
    """Suite titles with punctuation ("... (via copybook)") must not produce
    consecutive or trailing hyphens in the generated paragraph name -- GnuCOBOL
    rejects a paragraph header like UT-TESTSUITE-X--VIA-COPYBOOK-. outright."""
    suite = MockTestSuite(
        name="MAINPGM discount calculation (via copybook)",
        test_cases=[MockTestCase(name="c", perform_target="P")],
    )
    artifact = _build(suite)
    header = artifact.procedure_lines[0].strip()
    assert header.endswith(".")
    word = header[:-1]
    assert "--" not in word
    assert not word.endswith("-")
    assert word == "UT-TESTSUITE-MAINPGM-DISCOUNT-CALCULATION-VIA-COPYBOOK"


def test_testcase_emits_perform_thru_when_set():
    suite = _suite()
    suite.test_cases[0].perform_thru = "PROCESS-EXIT"
    joined = "\n".join(_build(suite).procedure_lines)
    assert "PERFORM PROCESS-ORDER THRU PROCESS-EXIT" in joined


# --- field widths (audit 2.5, 2.7) and suite-name escaping (audit 2.8) -------


def test_tally_and_fail_count_fields_are_nine_digits():
    """PIC 9(4) wrapped silently at 10,000: `VERIFY ... 500 TIMES` passed
    with 10,500 actual calls and the SUMMARY fail count wrapped the same
    way. 9(9) keeps counts exact for any realistic batch loop."""
    joined = "\n".join(_build().working_storage_lines)
    assert "UT-FAIL-COUNT          PIC 9(9) VALUE 0." in joined
    assert "UT-DISCRATE-TALLY      PIC 9(9) VALUE 0." in joined
    assert "PIC 9(4)" not in joined


def test_current_case_field_is_wide_enough_for_four_digit_case_ids():
    """PIC X(3) truncated case 1000's MOVE to "100", executing case 100's
    mock branches; X(9) keeps the MOVE'd id and the injector's WHEN
    literals in sync far past any realistic suite size."""
    joined = "\n".join(_build().working_storage_lines)
    assert "UT-CURRENT-CASE        PIC X(9)." in joined
    assert "PIC X(3)" not in joined


def test_suite_name_quotes_are_escaped_in_testsuite_display():
    """suite.name was interpolated unescaped while case.name was escaped --
    a quote in the suite title would split the generated DISPLAY literal."""
    suite = MockTestSuite(
        name='say "hi" suite',
        test_cases=[MockTestCase(name="c", perform_target="P")],
    )
    joined = "\n".join(_build(suite).procedure_lines)
    assert 'DISPLAY "__MOCKYMOCK__ TESTSUITE: say ""hi"" suite"' in joined


def test_working_storage_declares_early_exit_flag():
    joined = "\n".join(_build().working_storage_lines)
    assert 'UT-EARLY-EXIT          PIC X VALUE "N".' in joined


def test_testcase_resets_early_exit_flag():
    joined = "\n".join(_build().procedure_lines)
    assert 'MOVE "N" TO UT-EARLY-EXIT' in joined


# --- --record-expectations (docs/2026-08-04-record-expectations-design.md) --


def test_record_targets_omitted_leaves_output_unchanged():
    """The whole feature is opt-in: ordinary run (no record_targets, or an
    explicit None) must never emit a RECORD marker."""
    joined = "\n".join(_build().procedure_lines)
    assert "RECORD" not in joined


def test_record_targets_empty_dict_leaves_output_unchanged():
    joined = "\n".join(_build(record_targets={}).procedure_lines)
    assert "RECORD" not in joined


def test_record_target_emits_one_display_per_name():
    joined = "\n".join(_build(record_targets={1: ["WS-NET-TOTAL"]}).procedure_lines)
    assert 'DISPLAY "__MOCKYMOCK__ RECORD 001 WS-NET-TOTAL: " WS-NET-TOTAL' in joined


def test_record_target_emits_one_line_per_name_in_order():
    lines = _build(record_targets={1: ["WS-NET-TOTAL", "WS-TAX-TOTAL"]}).procedure_lines
    joined = "\n".join(lines)
    net_index = joined.index("RECORD 001 WS-NET-TOTAL")
    tax_index = joined.index("RECORD 001 WS-TAX-TOTAL")
    assert net_index < tax_index


def test_record_marker_appears_after_expect_and_before_case_end():
    joined = "\n".join(_build(record_targets={1: ["WS-NET-TOTAL"]}).procedure_lines)
    expect_index = joined.index("IF WS-NET-AMOUNT NOT =")
    record_index = joined.index("RECORD 001 WS-NET-TOTAL")
    end_index = joined.index("__MOCKYMOCK__ CASE 001 END")
    assert expect_index < record_index < end_index


def test_record_target_for_a_different_case_index_is_not_emitted():
    """A record_targets entry keyed by a case index this suite doesn't have
    is silently a no-op for THIS suite -- it only ever fires for the case
    index it's keyed to."""
    joined = "\n".join(
        _build(record_targets={2: ["WS-NOT-IN-THIS-SUITE"]}).procedure_lines
    )
    assert "RECORD" not in joined


def test_record_targets_route_to_the_correct_case():
    case_one = MockTestCase(name="first", perform_target="P1")
    case_two = MockTestCase(name="second", perform_target="P2")
    suite = MockTestSuite(name="two cases", test_cases=[case_one, case_two])
    joined = "\n".join(_build(suite, record_targets={2: ["WS-B"]}).procedure_lines)
    assert "RECORD 001" not in joined
    assert 'DISPLAY "__MOCKYMOCK__ RECORD 002 WS-B: " WS-B' in joined


# --- EXPECT negation/comparison operators ------------------------------------


@pytest.mark.parametrize(
    ("operator", "fail_condition"),
    [
        ("=", "NOT ="),
        ("NOT =", "="),
        (">", "NOT >"),
        ("NOT >", ">"),
        ("<", "NOT <"),
        ("NOT <", "<"),
        (">=", "<"),
        ("NOT >=", ">="),
        ("<=", ">"),
        ("NOT <=", "<="),
    ],
)
def test_expect_operator_compiles_to_its_negated_fail_condition(
    operator, fail_condition
):
    """The generated IF guards the *failure* branch, so each operator
    emits its negation; >=/<= negate to the equivalent plain relation
    (</>) rather than a NOT-prefixed compound."""
    suite = _suite()
    suite.test_cases[0].expectations = [ExpectDirective("WS-X", "5", operator=operator)]
    joined = "\n".join(_build(suite).procedure_lines)
    assert f"IF WS-X {fail_condition} 5" in joined


def test_expect_fail_message_carries_the_asserted_operator():
    suite = _suite()
    suite.test_cases[0].expectations = [ExpectDirective("WS-X", "5", operator="NOT =")]
    joined = "\n".join(_build(suite).procedure_lines)
    assert 'expected WS-X NOT = 5, got " WS-X' in joined


def test_unrecognized_expect_operator_raises():
    """Parser validation is the real gate; codegen still fails loudly on a
    hand-built directive carrying an operator it cannot compile."""
    suite = _suite()
    suite.test_cases[0].expectations = [ExpectDirective("WS-X", "5", operator="<>")]
    with pytest.raises(ValueError, match="unrecognized EXPECT operator"):
        _build(suite)
