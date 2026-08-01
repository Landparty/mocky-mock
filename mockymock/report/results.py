"""Parses __MOCKYMOCK__-prefixed stdout lines into structured results."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_TESTSUITE_RE = re.compile(r"^__MOCKYMOCK__ TESTSUITE: (?P<name>.+)$")
_CASE_START_RE = re.compile(r"^__MOCKYMOCK__ CASE (?P<id>\S+) START: (?P<name>.+)$")
_CASE_FAIL_RE = re.compile(r"^__MOCKYMOCK__ CASE (?P<id>\S+) FAIL: (?P<reason>.+)$")
_CASE_END_RE = re.compile(r"^__MOCKYMOCK__ CASE (?P<id>\S+) END$")
# Emitted only in trace mode, by the splicer's mock dispatch blocks. Carries
# no case id: it is attributed to the case whose START most recently
# printed, which is exactly where the driver places it.
_MOCK_RE = re.compile(r"^__MOCKYMOCK__ MOCK: (?P<label>.+)$")
_SUMMARY_RE = re.compile(
    r"^__MOCKYMOCK__ SUMMARY: RUN=(?P<run>\d+) FAILURES=(?P<failures>\d+)$"
)


@dataclass
class TestResult:
    case_id: str
    case_name: str
    failure_reasons: list[str] = field(default_factory=list)
    ended: bool = False
    #: Mock labels in firing order. Only populated by a --trace run.
    mock_hits: list[str] = field(default_factory=list)

    @property
    def crashed(self) -> bool:
        """True if the case's START marker printed but its END marker never
        did -- the process died before this case's checks finished running
        (e.g. its PERFORM target transitively reached STOP RUN)."""
        return not self.ended

    @property
    def passed(self) -> bool:
        return not self.failure_reasons and not self.crashed


@dataclass
class TestSuiteResult:
    suite_name: str
    results: list[TestResult] = field(default_factory=list)
    tests_run: int = 0
    failures: int = 0
    orphan_failures: list[tuple[str, str]] = field(default_factory=list)
    #: (case_id, first_case_name, duplicate_case_name) for every CASE START
    #: whose id collides with one already seen. Defense in depth only -- the
    #: driver's generated ids are sequential and this should never fire
    #: against real generated output -- but a collision used to silently
    #: repoint `by_id` in parse_stdout, permanently orphaning the earlier
    #: TestResult from any later FAIL/END line for that id: it stayed
    #: `crashed` forever with no failure reason and no indication why.
    #: Recording it here turns that into a loud, attributable anomaly
    #: instead of a misleading, unexplained CRASH (audit finding 5.4).
    duplicate_case_starts: list[tuple[str, str, str]] = field(default_factory=list)
    #: Case ids seen in a CASE END line with no matching START. Recorded for
    #: diagnosability but does NOT gate all_passed: an unattributable END
    #: carries no failure evidence to lose (see orphan_failures for the
    #: FAIL-line equivalent, which does gate all_passed since a FAIL line
    #: does carry evidence).
    orphan_ends: list[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return (
            self.failures == 0
            and self.tests_run > 0
            and not self.orphan_failures
            and not self.duplicate_case_starts
        )


def parse_stdout(stdout: str) -> TestSuiteResult:
    """Parse a compiled test binary's captured stdout into a TestSuiteResult."""
    suite = TestSuiteResult(suite_name="")
    by_id: dict[str, TestResult] = {}

    for line in stdout.splitlines():
        if (m := _TESTSUITE_RE.match(line)) is not None:
            suite.suite_name = m.group("name")
        elif (m := _CASE_START_RE.match(line)) is not None:
            case_id = m.group("id")
            case_name = m.group("name")
            existing = by_id.get(case_id)
            if existing is not None:
                suite.duplicate_case_starts.append(
                    (case_id, existing.case_name, case_name)
                )
            result = TestResult(case_id=case_id, case_name=case_name)
            by_id[case_id] = result
            suite.results.append(result)
        elif (m := _CASE_FAIL_RE.match(line)) is not None:
            target = by_id.get(m.group("id"))
            if target is not None:
                target.failure_reasons.append(m.group("reason"))
            else:
                suite.orphan_failures.append((m.group("id"), m.group("reason")))
        elif (m := _MOCK_RE.match(line)) is not None:
            if suite.results:
                suite.results[-1].mock_hits.append(m.group("label"))
        elif (m := _SUMMARY_RE.match(line)) is not None:
            suite.tests_run = int(m.group("run"))
            suite.failures = int(m.group("failures"))
        elif (m := _CASE_END_RE.match(line)) is not None:
            case_id = m.group("id")
            target = by_id.get(case_id)
            if target is not None:
                target.ended = True
            else:
                suite.orphan_ends.append(case_id)

    return suite
