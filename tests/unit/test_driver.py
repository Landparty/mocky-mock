"""Unit tests for the driver generator (Task 12)."""

from mockymock.dsl.model import (
    ExpectDirective,
    MockCallDirective,
    MockTestCase,
    MockTestSuite,
    VerifyDirective,
)
from mockymock.splicer.driver import build_driver


def _suite() -> MockTestSuite:
    case_one = MockTestCase(
        name="10% discount reduces net amount correctly",
        mocks=[
            MockCallDirective(
                program_name="DISCRATE", body_lines=["MOVE 0.10 TO WS-DISCOUNT-PCT"]
            )
        ],
        setup_moves=[("100.00", "ORD-AMOUNT")],
        perform_target="PROCESS-ORDER",
        expectations=[ExpectDirective("WS-NET-AMOUNT", "90.00")],
        verifications=[VerifyDirective("DISCRATE", "ONCE")],
    )
    return MockTestSuite(name="ORDRPROC discount calculation", test_cases=[case_one])


def test_working_storage_declares_bookkeeping_fields():
    artifact = build_driver(_suite(), reset_lines=[], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.working_storage_lines)
    assert "UT-CURRENT-CASE" in joined
    assert "UT-DISCRATE-TALLY" in joined
    assert "UT-FAIL-COUNT" in joined


def test_testsuite_paragraph_performs_each_case_and_stops():
    artifact = build_driver(_suite(), reset_lines=[], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.procedure_lines)
    assert "UT-TESTSUITE-" in joined
    assert "PERFORM UT-TESTCASE-001" in joined
    assert "STOP RUN" in joined
    assert "__MOCKYMOCK__ TESTSUITE: ORDRPROC discount calculation" in joined


def test_testcase_resets_and_sets_current_case():
    artifact = build_driver(_suite(), reset_lines=["MOVE 0 TO X"], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.procedure_lines)
    assert "PERFORM UT-RESET-WORKING-STORAGE" in joined
    assert 'MOVE "001" TO UT-CURRENT-CASE' in joined
    assert "MOVE 0 TO UT-DISCRATE-TALLY" in joined


def test_testcase_emits_setup_moves_and_perform():
    artifact = build_driver(_suite(), reset_lines=[], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.procedure_lines)
    assert "MOVE 100.00 TO ORD-AMOUNT" in joined
    assert "PERFORM PROCESS-ORDER" in joined


def test_testcase_emits_expect_check():
    artifact = build_driver(_suite(), reset_lines=[], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.procedure_lines)
    assert "IF WS-NET-AMOUNT NOT = 90.00" in joined
    assert "__MOCKYMOCK__ CASE 001 FAIL:" in joined
    assert "ADD 1 TO UT-FAIL-COUNT" in joined


def test_testcase_emits_verify_check():
    artifact = build_driver(_suite(), reset_lines=[], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.procedure_lines)
    assert "IF UT-DISCRATE-TALLY NOT = 1" in joined


def test_testcase_brackets_with_start_and_end_markers():
    artifact = build_driver(_suite(), reset_lines=[], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.procedure_lines)
    assert (
        "__MOCKYMOCK__ CASE 001 START: 10% discount reduces net amount correctly"
        in joined
    )
    assert "__MOCKYMOCK__ CASE 001 END" in joined


def test_summary_line_uses_total_case_count():
    artifact = build_driver(_suite(), reset_lines=[], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.procedure_lines)
    assert 'DISPLAY "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES="' in joined or (
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=" in joined
    )


def test_reset_working_storage_paragraph_included_when_lines_given():
    artifact = build_driver(
        _suite(), reset_lines=["MOVE 0 TO ORD-AMOUNT"], mocked_call_names=["DISCRATE"]
    )
    joined = "\n".join(artifact.procedure_lines)
    assert "UT-RESET-WORKING-STORAGE." in joined
    assert "MOVE 0 TO ORD-AMOUNT" in joined
