"""Parses __MOCKYMOCK__-prefixed stdout lines into structured results."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_TESTSUITE_RE = re.compile(r"^__MOCKYMOCK__ TESTSUITE: (?P<name>.+)$")
_CASE_START_RE = re.compile(r"^__MOCKYMOCK__ CASE (?P<id>\S+) START: (?P<name>.+)$")
_CASE_FAIL_RE = re.compile(r"^__MOCKYMOCK__ CASE (?P<id>\S+) FAIL: (?P<reason>.+)$")
_CASE_END_RE = re.compile(r"^__MOCKYMOCK__ CASE (?P<id>\S+) END$")
_SUMMARY_RE = re.compile(
    r"^__MOCKYMOCK__ SUMMARY: RUN=(?P<run>\d+) FAILURES=(?P<failures>\d+)$"
)


@dataclass
class TestResult:
    case_id: str
    case_name: str
    failure_reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failure_reasons


@dataclass
class TestSuiteResult:
    suite_name: str
    results: list[TestResult] = field(default_factory=list)
    tests_run: int = 0
    failures: int = 0

    @property
    def all_passed(self) -> bool:
        return self.failures == 0 and self.tests_run > 0


def parse_stdout(stdout: str) -> TestSuiteResult:
    """Parse a compiled test binary's captured stdout into a TestSuiteResult."""
    suite = TestSuiteResult(suite_name="")
    by_id: dict[str, TestResult] = {}

    for line in stdout.splitlines():
        if (m := _TESTSUITE_RE.match(line)) is not None:
            suite.suite_name = m.group("name")
        elif (m := _CASE_START_RE.match(line)) is not None:
            result = TestResult(case_id=m.group("id"), case_name=m.group("name"))
            by_id[result.case_id] = result
            suite.results.append(result)
        elif (m := _CASE_FAIL_RE.match(line)) is not None:
            target = by_id.get(m.group("id"))
            if target is not None:
                target.failure_reasons.append(m.group("reason"))
        elif (m := _SUMMARY_RE.match(line)) is not None:
            suite.tests_run = int(m.group("run"))
            suite.failures = int(m.group("failures"))
        # _CASE_END_RE intentionally not handled: END only matters for the
        # COBOL-side bracketing, not for parsing — failures are matched to
        # cases purely by id, so an END marker carries no information here.

    return suite
