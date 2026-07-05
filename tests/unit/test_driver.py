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
                MockCategory.CALL, "DISCRATE", body_lines=["MOVE 0.10 TO WS-DISCOUNT-PCT"]
            )
        ],
        setup_moves=[("100.00", "ORD-AMOUNT")],
        perform_target="PROCESS-ORDER",
        expectations=[ExpectDirective("WS-NET-AMOUNT", "90.00")],
        verifications=[VerifyDirective(MockCategory.CALL, "DISCRATE", "ONCE")],
    )
    return MockTestSuite(name="ORDRPROC discount calculation", test_cases=[case_one])


def _build(suite=None, reset_lines=None):
    suite = suite or _suite()
    return build_driver(suite, reset_lines=reset_lines or [], registry=TallyRegistry(suite))


def test_working_storage_declares_bookkeeping_fields():
    joined = "\n".join(_build().working_storage_lines)
    assert "UT-CURRENT-CASE" in joined
    assert "UT-DISCRATE-TALLY" in joined
    assert "UT-FAIL-COUNT" in joined


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


def test_testcase_emits_verify_check():
    joined = "\n".join(_build().procedure_lines)
    assert "IF UT-DISCRATE-TALLY NOT = 1" in joined


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
