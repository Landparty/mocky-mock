"""Console and JUnit XML formatters for TestSuiteResult."""

from __future__ import annotations

import re
from collections.abc import Sequence
from xml.etree.ElementTree import Element, SubElement, indent, tostring

from mockymock.report.results import TestSuiteResult

# Everything XML 1.0 forbids outright (control characters other than
# tab/LF/CR, plus lone surrogates). Suite/case names and failure reasons
# come from the .cut file and the binary's stdout, both of which can carry
# control characters -- feeding them to ElementTree produces XML that
# minidom (and any downstream CI collector) rejects with an ExpatError.
_XML_ILLEGAL_RE = re.compile(
    "[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
)

# Hardcoding a hypothesis here would be wrong whenever the real cause was
# a timeout or a runtime abort -- the CLI passes the actual evidence
# (exit code / timeout) as `crash_detail` when it has any; the STOP RUN
# hypothesis is only offered when the binary exited cleanly (code 0),
# which is what STOP RUN does.
_DEFAULT_CRASH_HYPOTHESIS = "PERFORM target reached STOP RUN?"


def _xml_safe(text: str) -> str:
    """Replace XML-illegal characters with a visible \\xNN escape so the
    document stays well-formed without silently losing the evidence that
    a control character was present."""
    return _XML_ILLEGAL_RE.sub(lambda m: f"\\x{ord(m.group()):02x}", text)


def format_console(
    suite: TestSuiteResult,
    crash_detail: str | None = None,
    not_run: Sequence[str] = (),
    risky: Sequence[str] = (),
) -> str:
    """`not_run`: the selected cases that never printed a START marker
    (`json_report.not_run_case_names`) -- a GO TO or STOP RUN that ended
    the binary early used to make them vanish from this listing.
    `risky`: case ids of the passing cases with no EXPECT/VERIFY
    (`json_report.risky_case_ids`); still passes, labelled as such."""
    lines = [f"TESTSUITE: {suite.suite_name}"]
    crashed_count = 0
    risky_ids = set(risky)
    for result in suite.results:
        suffix = ""
        if result.crashed:
            status = "CRASH"
            crashed_count += 1
        elif result.passed:
            status = "PASS"
            if result.case_id in risky_ids:
                suffix = " (risky: asserts nothing)"
        else:
            status = "FAIL"
        lines.append(f"  [{status}] {result.case_name}{suffix}")
        if result.crashed and crash_detail:
            lines.append(f"         {crash_detail}")
        for reason in result.failure_reasons:
            lines.append(f"         {reason}")
    for name in not_run:
        lines.append(f"  [NOT RUN] {name}")
    # suite.tests_run/suite.failures are 0 whenever the SUMMARY line never
    # printed (a mid-suite crash prevents it), even though case lines were
    # clearly seen and rendered above -- fall back to counts reconstructed
    # from suite.results so the summary doesn't claim "0 run"/"0 failed"
    # underneath a visible PASS/FAIL/CRASH listing. The two are mutually
    # exclusive (SUMMARY printing means no crash occurred), so falling back
    # only when the SUMMARY-derived value is falsy never overwrites a real
    # clean-run count of 0.
    run_count = suite.tests_run or len(suite.results)
    failed_count = suite.failures or sum(len(r.failure_reasons) for r in suite.results)
    summary = f"{run_count} run, {failed_count} failed"
    if crashed_count:
        summary += f", {crashed_count} crashed"
    if not_run:
        summary += f", {len(not_run)} not run"
    if risky:
        summary += f", {len(risky)} risky"
    lines.append(summary)
    if crash_detail and not suite.results:
        lines.append(f"  process exited before any test case started: {crash_detail}")
    if suite.orphan_failures:
        lines.append("ORPHANED FAILURES (unknown case id):")
        for case_id, reason in suite.orphan_failures:
            lines.append(f"  [{case_id}] {reason}")
    if suite.duplicate_case_starts:
        lines.append("DUPLICATE CASE IDS (a later START overwrote an earlier one):")
        for case_id, previous_name, new_name in suite.duplicate_case_starts:
            lines.append(f"  [{case_id}] {previous_name!r} then {new_name!r}")
    return "\n".join(lines)


def format_junit_xml(
    suite: TestSuiteResult,
    crash_detail: str | None = None,
    not_run: Sequence[str] = (),
) -> str:
    # `not_run` cases (never STARTed) each get a <testcase> with an <error>,
    # counted in tests= and errors=: dropping them read as a smaller, clean
    # suite to CI (issue #150).
    # suite.failures is the SUMMARY line's count of failed CHECKS (a case
    # with 2 failure reasons contributes 2 to that number), but standard CI
    # tooling (Jenkins, GitHub Actions, GitLab) interprets the <testsuite
    # failures="..."> attribute as the count of failed test CASES. Derive it
    # from suite.results instead so e.g. 1 case with 2 failure reasons
    # reports failures="1", not "2". Crashed cases (START but no END -- the
    # process died before their checks finished) are reported separately as
    # errors="...", matching JUnit's own failure-vs-error distinction, and
    # are excluded from failures so a crash isn't double-counted as a failure.
    # FAIL lines whose case id was never seen in a START marker (orphans) are
    # likewise unattributable to any test case's pass/fail lifecycle, so
    # they're folded into the same errors= total rather than a separate
    # attribute -- otherwise a CI consumer that only reads failures=/errors=
    # would still see a "clean" run despite orphaned output being present.
    # Duplicate CASE START ids are the same class of anomaly: the earlier
    # TestResult is silently orphaned from further FAIL/END attribution and
    # reports as a bare, unexplained crash, so it gets folded in here too.
    failed_cases = sum(1 for r in suite.results if r.failure_reasons and not r.crashed)
    crashed_cases = sum(1 for r in suite.results if r.crashed)
    # The binary died before any CASE START printed (crash_detail carries
    # the nonzero exit / timeout): with no <testcase> to hang it on, the
    # report used to read tests="0" failures="0" errors="0" -- a clean
    # empty suite to every CI collector, while the run itself failed.
    died_before_first_case = crash_detail is not None and not suite.results
    error_count = (
        crashed_cases
        + len(suite.orphan_failures)
        + len(suite.duplicate_case_starts)
        + int(died_before_first_case)
        + len(not_run)
    )
    # Same fallback as format_console: suite.tests_run is 0 when a mid-suite
    # crash ate the SUMMARY line, but JUnit consumers expect tests="..." to
    # match the actual number of <testcase> children below. Orphan failures
    # and duplicate-id markers each get their own <testcase> (see the loops
    # below) but aren't part of suite.results/suite.tests_run, so they must
    # be added here too or tests= undercounts the real number of <testcase>
    # children.
    tests_seen = (
        (suite.tests_run or len(suite.results))
        + len(suite.orphan_failures)
        + len(suite.duplicate_case_starts)
        + int(died_before_first_case)
        + len(not_run)
    )
    testsuite_el = Element(
        "testsuite",
        name=_xml_safe(suite.suite_name),
        tests=str(tests_seen),
        failures=str(failed_cases),
        errors=str(error_count),
    )
    # classname carries the suite name on every <testcase>: consumers that
    # flatten multiple report files into one table (or two suites that share
    # a case name) need a suite-qualified identity per case, and classname
    # is the attribute JUnit tooling already treats as that qualifier.
    suite_classname = _xml_safe(suite.suite_name)
    for result in suite.results:
        testcase_el = SubElement(
            testsuite_el,
            "testcase",
            name=_xml_safe(result.case_name),
            classname=suite_classname,
        )
        if result.crashed:
            # A crashed case is reported as a single <error>, never also as
            # <failure> -- even when it printed FAIL lines before dying
            # mid-case (a VERIFY failure followed by a crash in the same
            # PERFORM target is a real sequence, not a hypothetical). JUnit
            # consumers treat error and failure as mutually exclusive
            # outcomes for a single <testcase>; emitting both would count
            # the case twice. Any pre-crash failure reasons are folded into
            # the error message so they aren't lost.
            detail = crash_detail or _DEFAULT_CRASH_HYPOTHESIS
            message_parts = [
                "process exited before this case's END marker printed -- "
                f"its checks did not finish running ({detail})"
            ]
            if result.failure_reasons:
                message_parts.append(
                    "failures observed before the crash: "
                    + "; ".join(result.failure_reasons)
                )
            message = _xml_safe(" | ".join(message_parts))
            error_el = SubElement(testcase_el, "error", message=message)
            error_el.text = message
        else:
            for reason in result.failure_reasons:
                safe_reason = _xml_safe(reason)
                failure_el = SubElement(testcase_el, "failure", message=safe_reason)
                failure_el.text = safe_reason
    for name in not_run:
        message = _xml_safe(
            "never started -- the binary ended before this case's START "
            f"marker printed ({crash_detail or 'an earlier case ended the run'})"
        )
        not_run_el = SubElement(
            testsuite_el,
            "testcase",
            name=_xml_safe(name),
            classname=suite_classname,
        )
        error_el = SubElement(not_run_el, "error", message=message)
        error_el.text = message
    for case_id, reason in suite.orphan_failures:
        orphan_el = SubElement(
            testsuite_el,
            "testcase",
            name=_xml_safe(f"orphan-{case_id}"),
            classname=suite_classname,
        )
        safe_reason = _xml_safe(reason)
        error_el = SubElement(orphan_el, "error", message=safe_reason)
        error_el.text = safe_reason
    for case_id, previous_name, new_name in suite.duplicate_case_starts:
        # "reused"/"from here on", not "twice"/"the second START": the same
        # id can collide more than once, and previous_name is only the name
        # this particular collision overwrote, not necessarily the very
        # first START to use this id -- wording must stay accurate for any
        # collision count, not just exactly two.
        message = _xml_safe(
            f"CASE START id {case_id!r} reused ({previous_name!r} then "
            f"{new_name!r}) -- any FAIL/END lines up to this point were "
            f"attributed to {previous_name!r}; every line from here on is "
            f"attributed to {new_name!r} instead"
        )
        dup_el = SubElement(
            testsuite_el,
            "testcase",
            name=_xml_safe(f"duplicate-{case_id}"),
            classname=suite_classname,
        )
        error_el = SubElement(dup_el, "error", message=message)
        error_el.text = message
    if died_before_first_case:
        message = _xml_safe(
            f"process exited before any test case started ({crash_detail})"
        )
        run_el = SubElement(
            testsuite_el,
            "testcase",
            name="(test binary)",
            classname=suite_classname,
        )
        error_el = SubElement(run_el, "error", message=message)
        error_el.text = message
    # ElementTree, not minidom's toprettyxml: minidom writes a tab, LF or
    # CR inside an attribute value raw, and an XML reader's attribute-value
    # normalization then turns each into a space -- a failure message's
    # line structure (and any tab in a compared value) silently lost.
    # ElementTree escapes them as `&#09;` / `&#10;` / `&#13;`.
    indent(testsuite_el, space="  ")
    body = tostring(testsuite_el, encoding="unicode")
    return f'<?xml version="1.0" ?>\n{body}\n'
