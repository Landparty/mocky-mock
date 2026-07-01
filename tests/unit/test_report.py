from mockymock.report.formatters import format_console, format_junit_xml
from mockymock.report.results import parse_stdout

SAMPLE_STDOUT = """\
__MOCKYMOCK__ TESTSUITE: ORDRPROC discount calculation
__MOCKYMOCK__ CASE 001 START: 10% discount reduces net amount correctly
__MOCKYMOCK__ CASE 001 END
__MOCKYMOCK__ CASE 002 START: Zero discount leaves amount unchanged
__MOCKYMOCK__ CASE 002 FAIL: expected WS-NET-AMOUNT = 50.00, got 49.99
__MOCKYMOCK__ CASE 002 FAIL: VERIFY DISCRATE WAS CALLED ONCE
__MOCKYMOCK__ CASE 002 END
__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=2
"""


def test_parse_stdout_extracts_suite_name():
    suite = parse_stdout(SAMPLE_STDOUT)
    assert suite.suite_name == "ORDRPROC discount calculation"


def test_parse_stdout_extracts_summary_counts():
    suite = parse_stdout(SAMPLE_STDOUT)
    assert suite.tests_run == 2
    assert suite.failures == 2


def test_parse_stdout_groups_two_failures_under_one_case():
    suite = parse_stdout(SAMPLE_STDOUT)
    assert len(suite.results) == 2
    case_002 = suite.results[1]
    assert case_002.case_id == "002"
    assert case_002.passed is False
    assert case_002.failure_reasons == [
        "expected WS-NET-AMOUNT = 50.00, got 49.99",
        "VERIFY DISCRATE WAS CALLED ONCE",
    ]


def test_parse_stdout_case_with_no_fail_lines_passes():
    suite = parse_stdout(SAMPLE_STDOUT)
    case_001 = suite.results[0]
    assert case_001.passed is True
    assert case_001.failure_reasons == []


def test_all_passed_is_false_when_any_failure():
    suite = parse_stdout(SAMPLE_STDOUT)
    assert suite.all_passed is False


def test_all_passed_is_true_for_clean_run():
    clean = (
        "__MOCKYMOCK__ TESTSUITE: X\n"
        "__MOCKYMOCK__ CASE 001 START: only case\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
    )
    assert parse_stdout(clean).all_passed is True


def test_format_console_lists_each_case_and_reasons():
    suite = parse_stdout(SAMPLE_STDOUT)
    output = format_console(suite)
    assert "[PASS]" in output
    assert "[FAIL]" in output
    assert "VERIFY DISCRATE WAS CALLED ONCE" in output


def test_format_junit_xml_is_well_formed_and_has_failures():
    suite = parse_stdout(SAMPLE_STDOUT)
    xml_text = format_junit_xml(suite)
    assert '<testsuite name="ORDRPROC discount calculation"' in xml_text
    assert xml_text.count("<testcase") == 2
    assert xml_text.count("<failure") == 2


def test_format_junit_xml_failures_attribute_counts_failed_cases_not_reasons():
    """SAMPLE_STDOUT has 1 passing case and 1 failing case with TWO failure
    reasons (suite.failures == 2, the SUMMARY line's count of failed CHECKS).
    Standard CI tooling (Jenkins/GitHub Actions/GitLab) interprets the
    <testsuite failures="..."> attribute as the count of failed test CASES,
    not failed checks -- so it must report "1" (one failed case), not "2",
    or CI would misreport "2 failed tests" for what is actually 1 failing
    test case."""
    suite = parse_stdout(SAMPLE_STDOUT)
    assert suite.failures == 2  # sanity: the SUMMARY line's raw check count
    xml_text = format_junit_xml(suite)
    assert 'failures="1"' in xml_text
    # The per-case <failure> elements (one per reason) are unaffected --
    # only the testsuite-level attribute's semantics change.
    assert xml_text.count("<failure") == 2


def test_format_junit_xml_failures_attribute_with_multiple_failed_cases():
    """Two failing cases (one reason each) plus one passing case must report
    failures="2", proving the count tracks failed cases generically, not
    just as a special case of the two-reasons-one-case fixture above."""
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: X\n"
        "__MOCKYMOCK__ CASE 001 START: passes\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ CASE 002 START: fails one\n"
        "__MOCKYMOCK__ CASE 002 FAIL: reason A\n"
        "__MOCKYMOCK__ CASE 002 END\n"
        "__MOCKYMOCK__ CASE 003 START: fails two\n"
        "__MOCKYMOCK__ CASE 003 FAIL: reason B\n"
        "__MOCKYMOCK__ CASE 003 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=3 FAILURES=2\n"
    )
    suite = parse_stdout(stdout)
    xml_text = format_junit_xml(suite)
    assert 'failures="2"' in xml_text
