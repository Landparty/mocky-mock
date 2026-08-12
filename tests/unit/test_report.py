from xml.etree import ElementTree

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

# Simulates a PERFORM target that transitively reaches STOP RUN: the case
# START marker prints, the program's own DISPLAY output prints, then the
# process exits -- no CASE 002 END and no SUMMARY line ever print.
CRASH_STDOUT = (
    "__MOCKYMOCK__ TESTSUITE: DEPTMQP spike\n"
    "__MOCKYMOCK__ CASE 001 START: connects to MQ and primes the first read\n"
    "__MOCKYMOCK__ CASE 001 END\n"
    "__MOCKYMOCK__ CASE 002 START: full main-process run\n"
    "DEPTMQP: MQ DEPOSIT PRODUCER STARTED\n"
    "DEPTMQP: MQ DEPOSIT PRODUCER COMPLETE\n"
)

# A case FAILS and completes normally, then a later case crashes -- the
# SUMMARY line (and its FAILURES= count) is still eaten by the crash even
# though a real failure was recorded and rendered before it.
FAIL_THEN_CRASH_STDOUT = (
    "__MOCKYMOCK__ TESTSUITE: X\n"
    "__MOCKYMOCK__ CASE 001 START: fails a check\n"
    "__MOCKYMOCK__ CASE 001 FAIL: expected 5, got 6\n"
    "__MOCKYMOCK__ CASE 001 END\n"
    "__MOCKYMOCK__ CASE 002 START: crashes\n"
)


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


def test_all_passed_is_false_when_a_case_shows_fail_despite_clean_summary():
    """2026-08-12 audit Finding 1: all_passed was derived solely from the
    driver's own SUMMARY FAILURES= counter, never cross-checked against the
    per-case FAIL lines actually parsed. A COBOL program's own DISPLAY
    output starting a line with the __MOCKYMOCK__ CASE ... FAIL: shape
    (program-controlled data echoed to stdout -- no adversarial intent
    needed) then produced exit code 0 while console/JUnit/JSON all rendered
    that case as failed: an internally contradictory report whose dangerous
    half (the exit code) is the only part CI ever looks at."""
    contradictory = (
        "__MOCKYMOCK__ TESTSUITE: X\n"
        "__MOCKYMOCK__ CASE 001 START: only case\n"
        "__MOCKYMOCK__ CASE 001 FAIL: program-controlled text\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
    )
    suite = parse_stdout(contradictory)
    assert suite.results[0].passed is False  # what the report renders
    assert suite.all_passed is False  # the exit code must agree with it


def test_all_passed_is_false_when_a_case_never_ended_despite_clean_summary():
    """Companion to the cross-check above: a case whose START printed but
    whose END never did is rendered [CRASH] by every formatter, so
    all_passed must not report True for it even if a (spoofed or corrupt)
    SUMMARY line claims FAILURES=0."""
    truncated = (
        "__MOCKYMOCK__ TESTSUITE: X\n"
        "__MOCKYMOCK__ CASE 001 START: only case\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
    )
    suite = parse_stdout(truncated)
    assert suite.results[0].crashed is True
    assert suite.all_passed is False


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


def test_parse_stdout_case_with_no_end_marker_is_crashed():
    suite = parse_stdout(CRASH_STDOUT)
    case_002 = suite.results[1]
    assert case_002.crashed is True


def test_parse_stdout_case_with_no_end_marker_does_not_report_passed():
    suite = parse_stdout(CRASH_STDOUT)
    case_002 = suite.results[1]
    assert case_002.passed is False


def test_parse_stdout_case_with_end_marker_is_not_crashed():
    suite = parse_stdout(CRASH_STDOUT)
    case_001 = suite.results[0]
    assert case_001.crashed is False
    assert case_001.passed is True


def test_format_console_reports_crashed_case_distinctly_from_pass():
    suite = parse_stdout(CRASH_STDOUT)
    output = format_console(suite)
    lines = output.splitlines()
    crashed_line = next(line for line in lines if "full main-process run" in line)
    assert "[PASS]" not in crashed_line
    assert "[CRASH]" in crashed_line


def test_format_junit_xml_reports_crashed_case_as_error_not_failure():
    suite = parse_stdout(CRASH_STDOUT)
    xml_text = format_junit_xml(suite)
    assert 'errors="1"' in xml_text
    assert 'failures="0"' in xml_text
    assert "<error" in xml_text


def test_format_junit_xml_case_that_fails_then_crashes_is_error_only():
    # A case can print FAIL lines before the process dies mid-case (e.g. a
    # VERIFY fails, then a later statement in the same PERFORM target
    # crashes) -- <error> and <failure> are mutually exclusive per <testcase>
    # in JUnit's model, so this must not emit both for the same case.
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: X\n"
        "__MOCKYMOCK__ CASE 001 START: fails then crashes\n"
        "__MOCKYMOCK__ CASE 001 FAIL: expected 5, got 6\n"
    )
    suite = parse_stdout(stdout)
    xml_text = format_junit_xml(suite)
    assert 'errors="1"' in xml_text
    assert 'failures="0"' in xml_text
    assert "<failure" not in xml_text
    assert "<error" in xml_text
    assert "expected 5, got 6" in xml_text


def test_format_console_summary_reflects_cases_seen_when_summary_line_never_printed():
    # CRASH_STDOUT has no SUMMARY line at all, so suite.tests_run/failures
    # stay at their zero defaults -- the summary must not just print "0 run"
    # underneath two case lines that were clearly seen and rendered above it.
    suite = parse_stdout(CRASH_STDOUT)
    output = format_console(suite)
    summary_line = output.splitlines()[-1]
    assert summary_line == "2 run, 0 failed, 1 crashed"


def test_format_junit_xml_tests_attribute_reflects_cases_seen_when_summary_line_never_printed():
    suite = parse_stdout(CRASH_STDOUT)
    xml_text = format_junit_xml(suite)
    assert 'tests="2"' in xml_text


def test_format_console_failed_count_reflects_recorded_reasons_when_summary_line_never_printed():
    # A real FAIL was recorded and rendered before the crash ate the SUMMARY
    # line -- the console must not print "0 failed" directly underneath the
    # visible [FAIL] line above it.
    suite = parse_stdout(FAIL_THEN_CRASH_STDOUT)
    output = format_console(suite)
    summary_line = output.splitlines()[-1]
    assert summary_line == "2 run, 1 failed, 1 crashed"


def test_fail_line_with_unknown_case_id_is_surfaced():
    out = (
        "__MOCKYMOCK__ TESTSUITE: s\n"
        "__MOCKYMOCK__ CASE 001 START: c\n"
        "__MOCKYMOCK__ CASE 999 FAIL: orphaned reason\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
    )
    suite = parse_stdout(out)
    assert ("999", "orphaned reason") in suite.orphan_failures
    assert suite.all_passed is False


def test_format_console_reports_orphaned_failures():
    out = (
        "__MOCKYMOCK__ TESTSUITE: s\n"
        "__MOCKYMOCK__ CASE 001 START: c\n"
        "__MOCKYMOCK__ CASE 999 FAIL: orphaned reason\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
    )
    suite = parse_stdout(out)
    output = format_console(suite)
    assert "ORPHANED FAILURES (unknown case id):" in output
    assert "999" in output
    assert "orphaned reason" in output


def test_format_junit_xml_reports_orphaned_failures_as_error_testcase():
    out = (
        "__MOCKYMOCK__ TESTSUITE: s\n"
        "__MOCKYMOCK__ CASE 001 START: c\n"
        "__MOCKYMOCK__ CASE 999 FAIL: orphaned reason\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
    )
    suite = parse_stdout(out)
    xml_text = format_junit_xml(suite)
    assert '<testcase name="orphan-999"' in xml_text
    assert 'message="orphaned reason"' in xml_text
    # No crashed cases here -- the single orphan is the only contributor to
    # errors=, proving orphans are counted into the same errors= total used
    # for crashed cases rather than a separate untracked attribute.
    assert 'errors="1"' in xml_text


def test_format_junit_xml_tests_attribute_counts_orphan_testcases():
    """The root tests="..." attribute must equal the actual number of
    <testcase> children. format_junit_xml emits one <testcase> per orphan
    failure in addition to the ones from suite.results, so tests= has to
    add len(suite.orphan_failures) or it undercounts against a suite that
    has orphans."""
    out = (
        "__MOCKYMOCK__ TESTSUITE: s\n"
        "__MOCKYMOCK__ CASE 001 START: c\n"
        "__MOCKYMOCK__ CASE 999 FAIL: orphaned reason\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
    )
    suite = parse_stdout(out)
    xml_text = format_junit_xml(suite)
    root = ElementTree.fromstring(xml_text)
    assert int(root.get("tests")) == len(root.findall("testcase"))


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


# --- audit 5.2: control characters must not crash the JUnit formatter --------


def test_format_junit_xml_survives_control_characters():
    """Suite/case names and failure reasons come from the .cut file and the
    binary's stdout, either of which can carry control characters; the
    formatter used to hand them to ElementTree verbatim and minidom then
    died with an ExpatError (verified with \\x01)."""
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: bad\x01suite\n"
        "__MOCKYMOCK__ CASE 001 START: bad\x01case\n"
        "__MOCKYMOCK__ CASE 001 FAIL: reason with \x01 control char\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ CASE 999 FAIL: orphan \x02 reason\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=1\n"
    )
    suite = parse_stdout(stdout)
    xml_text = format_junit_xml(suite)  # must not raise
    root = ElementTree.fromstring(xml_text)  # and must be well-formed
    assert root.get("name") == "bad\\x01suite"
    assert "reason with \\x01 control char" in xml_text
    assert "orphan \\x02 reason" in xml_text


def test_format_junit_xml_crashed_case_with_control_char_in_name():
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: s\n" "__MOCKYMOCK__ CASE 001 START: crash\x1bname\n"
    )
    xml_text = format_junit_xml(parse_stdout(stdout))
    ElementTree.fromstring(xml_text)
    assert "crash\\x1bname" in xml_text


# --- audit 5.1: crash framing uses real evidence when the CLI has it ---------


def test_format_junit_xml_default_crash_message_keeps_stop_run_hypothesis():
    suite = parse_stdout(CRASH_STDOUT)
    xml_text = format_junit_xml(suite)
    assert "PERFORM target reached STOP RUN?" in xml_text


def test_format_junit_xml_crash_detail_replaces_stop_run_hypothesis():
    suite = parse_stdout(CRASH_STDOUT)
    xml_text = format_junit_xml(
        suite, crash_detail="binary timed out (exit 124); see stderr below"
    )
    assert "binary timed out (exit 124)" in xml_text
    assert "STOP RUN" not in xml_text


def test_format_console_crash_detail_rendered_under_crashed_case():
    suite = parse_stdout(CRASH_STDOUT)
    output = format_console(suite, crash_detail="binary exited with code 134")
    lines = output.splitlines()
    crash_index = next(i for i, line in enumerate(lines) if "[CRASH]" in line)
    assert lines[crash_index + 1].strip() == "binary exited with code 134"


def test_format_console_without_crash_detail_is_unchanged():
    suite = parse_stdout(CRASH_STDOUT)
    output = format_console(suite)
    assert "binary exited" not in output


def test_format_junit_xml_carries_suite_name_as_classname_on_every_testcase():
    """Suite-qualified case identity: consumers that merge multiple report
    files (or meet two suites sharing a case name) key on classname."""
    from xml.etree.ElementTree import fromstring

    suite = parse_stdout(
        "__MOCKYMOCK__ TESTSUITE: my suite\n"
        "__MOCKYMOCK__ CASE 001 START: a case\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ CASE 007 FAIL: orphaned\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=1\n"
    )
    root = fromstring(format_junit_xml(suite))
    testcases = root.findall("testcase")
    assert len(testcases) == 2  # the real case + the orphan
    for testcase in testcases:
        assert testcase.get("classname") == "my suite"


# --- audit 5.4: duplicate CASE ids and orphan END markers are surfaced -----


def test_duplicate_case_start_id_is_recorded_not_silently_overwritten():
    """Defense in depth: the driver's generated ids are sequential and this
    should never fire against real generated output. But a collision used to
    silently repoint `by_id`, permanently orphaning the earlier TestResult
    from any later FAIL/END line for that id -- it stayed `crashed` forever
    with no failure reason and no indication why. It must now be recorded as
    an explicit, attributable anomaly instead."""
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: X\n"
        "__MOCKYMOCK__ CASE 001 START: first case\n"
        "__MOCKYMOCK__ CASE 001 START: second case, same id\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=0\n"
    )
    suite = parse_stdout(stdout)
    assert suite.duplicate_case_starts == [
        ("001", "first case", "second case, same id")
    ]
    # Nothing is deleted -- both results still exist -- but the earlier one
    # is now a documented anomaly rather than a bare, unexplained crash.
    assert len(suite.results) == 2
    assert suite.results[0].case_name == "first case"
    assert suite.results[0].crashed is True
    assert suite.results[1].case_name == "second case, same id"
    assert suite.results[1].crashed is False


def test_duplicate_case_start_records_the_previous_name_not_the_first():
    """The same id can collide more than twice. Each collision's recorded
    "previous" name must be whatever START it actually overwrote (the
    second case, on the third START) -- not the very first START to ever
    use this id -- or the field is misleading past the second collision."""
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: X\n"
        "__MOCKYMOCK__ CASE 001 START: first\n"
        "__MOCKYMOCK__ CASE 001 START: second\n"
        "__MOCKYMOCK__ CASE 001 START: third\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=3 FAILURES=0\n"
    )
    suite = parse_stdout(stdout)
    assert suite.duplicate_case_starts == [
        ("001", "first", "second"),
        ("001", "second", "third"),
    ]


def test_all_passed_is_false_when_duplicate_case_start_ids_seen():
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: X\n"
        "__MOCKYMOCK__ CASE 001 START: a\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ CASE 001 START: b\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=0\n"
    )
    suite = parse_stdout(stdout)
    assert suite.all_passed is False


def test_format_console_reports_duplicate_case_starts():
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: X\n"
        "__MOCKYMOCK__ CASE 001 START: first case\n"
        "__MOCKYMOCK__ CASE 001 START: second case\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=0\n"
    )
    suite = parse_stdout(stdout)
    output = format_console(suite)
    assert "DUPLICATE CASE IDS" in output
    assert "first case" in output
    assert "second case" in output


def test_format_junit_xml_reports_duplicate_case_starts_as_error_testcase():
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: X\n"
        "__MOCKYMOCK__ CASE 001 START: first case\n"
        "__MOCKYMOCK__ CASE 001 START: second case\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=0\n"
    )
    suite = parse_stdout(stdout)
    xml_text = format_junit_xml(suite)
    assert '<testcase name="duplicate-001"' in xml_text
    root = ElementTree.fromstring(xml_text)
    # tests= must still equal the real number of <testcase> children once a
    # duplicate-marker testcase is added on top of the two real results.
    assert int(root.get("tests")) == len(root.findall("testcase"))


def test_orphan_end_marker_is_recorded_not_silently_dropped():
    """An END for a case id that never STARTed used to vanish with zero
    trace anywhere. It still must not gate all_passed -- an unattributable
    END carries no failure evidence to lose, unlike an orphaned FAIL line --
    but it must be recorded somewhere, not silently discarded."""
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: X\n"
        "__MOCKYMOCK__ CASE 001 START: only case\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ CASE 999 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
    )
    suite = parse_stdout(stdout)
    assert suite.orphan_ends == ["999"]
    assert suite.all_passed is True  # unchanged: no failure evidence lost


# --- execution trace (docs/2026-07-21-debug-trace-design.md) ---------------


def test_parse_stdout_records_mock_hits_in_firing_order():
    stdout = "\n".join(
        [
            "__MOCKYMOCK__ TESTSUITE: S",
            "__MOCKYMOCK__ CASE 001 START: posts a credit",
            "__MOCKYMOCK__ MOCK: CALL 'CUSTLOOK'",
            "__MOCKYMOCK__ MOCK: READ ACCT-FILE",
            "__MOCKYMOCK__ CASE 001 END",
            "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0",
        ]
    )

    suite = parse_stdout(stdout)

    assert suite.results[0].mock_hits == ["CALL 'CUSTLOOK'", "READ ACCT-FILE"]


def test_parse_stdout_attributes_mock_hits_to_their_own_case():
    """Markers land between the driver's CASE START/END lines, which is what
    makes per-case attribution free."""
    stdout = "\n".join(
        [
            "__MOCKYMOCK__ TESTSUITE: S",
            "__MOCKYMOCK__ CASE 001 START: first",
            "__MOCKYMOCK__ MOCK: CALL 'A'",
            "__MOCKYMOCK__ CASE 001 END",
            "__MOCKYMOCK__ CASE 002 START: second",
            "__MOCKYMOCK__ MOCK: CALL 'B'",
            "__MOCKYMOCK__ CASE 002 END",
            "__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=0",
        ]
    )

    suite = parse_stdout(stdout)

    assert suite.results[0].mock_hits == ["CALL 'A'"]
    assert suite.results[1].mock_hits == ["CALL 'B'"]


def test_parse_stdout_has_empty_mock_hits_for_a_normal_run():
    suite = parse_stdout(
        "\n".join(
            [
                "__MOCKYMOCK__ TESTSUITE: S",
                "__MOCKYMOCK__ CASE 001 START: only",
                "__MOCKYMOCK__ CASE 001 END",
                "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0",
            ]
        )
    )
    assert suite.results[0].mock_hits == []


# --- --record-expectations (docs/2026-08-04-record-expectations-design.md) --


def test_parse_stdout_records_recorded_values_in_order():
    stdout = "\n".join(
        [
            "__MOCKYMOCK__ TESTSUITE: S",
            "__MOCKYMOCK__ CASE 001 START: calc",
            "__MOCKYMOCK__ RECORD 001 WS-NET-TOTAL: 145.50",
            "__MOCKYMOCK__ RECORD 001 WS-STATUS: OK",
            "__MOCKYMOCK__ CASE 001 END",
            "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0",
        ]
    )
    suite = parse_stdout(stdout)
    assert suite.results[0].recorded == [
        ("WS-NET-TOTAL", "145.50"),
        ("WS-STATUS", "OK"),
    ]


def test_parse_stdout_records_a_subscripted_name_containing_a_space():
    """scan_stub_expectations explicitly supports a subscripted data-name
    like "WS-TABLE(1, 1)" (a space after the comma -- see
    test_stub_expectations.py::test_subscripted_stub_name_parses), and
    build_driver emits it verbatim into the RECORD marker -- a bare \\S+
    name group would stop at that space, never find the ": " it then
    requires, and silently drop the whole recorded value instead of
    raising anything."""
    stdout = "\n".join(
        [
            "__MOCKYMOCK__ TESTSUITE: S",
            "__MOCKYMOCK__ CASE 001 START: calc",
            "__MOCKYMOCK__ RECORD 001 WS-TABLE(1, 1): 42",
            "__MOCKYMOCK__ CASE 001 END",
            "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0",
        ]
    )
    suite = parse_stdout(stdout)
    assert suite.results[0].recorded == [("WS-TABLE(1, 1)", "42")]


def test_parse_stdout_attributes_recorded_values_by_case_id_not_position():
    """Unlike MOCK:, a RECORD marker carries a real case id -- attribution
    must use it, not "whichever case's START printed most recently"."""
    stdout = "\n".join(
        [
            "__MOCKYMOCK__ TESTSUITE: S",
            "__MOCKYMOCK__ CASE 001 START: first",
            "__MOCKYMOCK__ CASE 001 END",
            "__MOCKYMOCK__ CASE 002 START: second",
            "__MOCKYMOCK__ RECORD 002 WS-B: 7",
            "__MOCKYMOCK__ CASE 002 END",
            "__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=0",
        ]
    )
    suite = parse_stdout(stdout)
    assert suite.results[0].recorded == []
    assert suite.results[1].recorded == [("WS-B", "7")]


def test_parse_stdout_has_empty_recorded_for_a_normal_run():
    suite = parse_stdout(SAMPLE_STDOUT)
    assert all(result.recorded == [] for result in suite.results)


def test_record_marker_with_unknown_case_id_is_an_orphan_not_dropped():
    stdout = "\n".join(
        [
            "__MOCKYMOCK__ TESTSUITE: S",
            "__MOCKYMOCK__ CASE 001 START: only",
            "__MOCKYMOCK__ RECORD 999 WS-GHOST: 1",
            "__MOCKYMOCK__ CASE 001 END",
            "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0",
        ]
    )
    suite = parse_stdout(stdout)
    assert suite.orphan_records == [("999", "WS-GHOST", "1")]
    assert suite.results[0].recorded == []


def test_orphan_record_does_not_gate_all_passed():
    """A RECORD marker carries no pass/fail semantics -- unlike an orphaned
    FAIL line, an orphaned RECORD has no failure evidence to lose."""
    stdout = "\n".join(
        [
            "__MOCKYMOCK__ TESTSUITE: S",
            "__MOCKYMOCK__ CASE 001 START: only",
            "__MOCKYMOCK__ RECORD 999 WS-GHOST: 1",
            "__MOCKYMOCK__ CASE 001 END",
            "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0",
        ]
    )
    suite = parse_stdout(stdout)
    assert suite.all_passed is True


def test_recorded_value_may_be_empty_or_contain_a_colon():
    """The value capture group is `.*` (greedy, may be empty) so a blank
    DISPLAY (an all-spaces alphanumeric field) or a value that happens to
    contain a literal colon still parses whole, not truncated at the first
    colon."""
    stdout = "\n".join(
        [
            "__MOCKYMOCK__ TESTSUITE: S",
            "__MOCKYMOCK__ CASE 001 START: only",
            "__MOCKYMOCK__ RECORD 001 WS-BLANK: ",
            "__MOCKYMOCK__ RECORD 001 WS-TIME: 12:30:00",
            "__MOCKYMOCK__ CASE 001 END",
            "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0",
        ]
    )
    suite = parse_stdout(stdout)
    assert suite.results[0].recorded == [
        ("WS-BLANK", ""),
        ("WS-TIME", "12:30:00"),
    ]
