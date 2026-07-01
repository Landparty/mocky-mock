"""Console and JUnit XML formatters for TestSuiteResult."""

from __future__ import annotations

from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring

from mockymock.report.results import TestSuiteResult


def format_console(suite: TestSuiteResult) -> str:
    lines = [f"TESTSUITE: {suite.suite_name}"]
    for result in suite.results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(f"  [{status}] {result.case_name}")
        for reason in result.failure_reasons:
            lines.append(f"         {reason}")
    lines.append(f"{suite.tests_run} run, {suite.failures} failed")
    return "\n".join(lines)


def format_junit_xml(suite: TestSuiteResult) -> str:
    # suite.failures is the SUMMARY line's count of failed CHECKS (a case
    # with 2 failure reasons contributes 2 to that number), but standard CI
    # tooling (Jenkins, GitHub Actions, GitLab) interprets the <testsuite
    # failures="..."> attribute as the count of failed test CASES. Derive it
    # from suite.results instead so e.g. 1 case with 2 failure reasons
    # reports failures="1", not "2".
    failed_cases = sum(1 for r in suite.results if not r.passed)
    testsuite_el = Element(
        "testsuite",
        name=suite.suite_name,
        tests=str(suite.tests_run),
        failures=str(failed_cases),
    )
    for result in suite.results:
        testcase_el = SubElement(testsuite_el, "testcase", name=result.case_name)
        for reason in result.failure_reasons:
            failure_el = SubElement(testcase_el, "failure", message=reason)
            failure_el.text = reason
    rough = tostring(testsuite_el, encoding="unicode")
    return minidom.parseString(rough).toprettyxml(indent="  ")
