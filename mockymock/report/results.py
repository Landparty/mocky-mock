"""Parses __MOCKYMOCK__-prefixed stdout lines into structured results."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mockymock.dsl.parser import _SUBSCRIPTED_NAME

_MARKER = "__MOCKYMOCK__ "
_TESTSUITE_RE = re.compile(r"^__MOCKYMOCK__ TESTSUITE: (?P<name>.+)$")
# `.*`, not `.+`: a START marker the driver printed is never dropped, even
# for a name the parser should have refused (issue #308).
_CASE_START_RE = re.compile(r"^__MOCKYMOCK__ CASE (?P<id>\S+) START: ?(?P<name>.*)$")
_CASE_FAIL_RE = re.compile(r"^__MOCKYMOCK__ CASE (?P<id>\S+) FAIL: (?P<reason>.+)$")
_CASE_END_RE = re.compile(r"^__MOCKYMOCK__ CASE (?P<id>\S+) END$")
# Emitted only in trace mode, by the splicer's mock dispatch blocks. Carries
# no case id: it is attributed to the case whose START most recently
# printed, which is exactly where the driver places it.
_VALUE_END_RE = re.compile(r"^__MOCKYMOCK__ VALUE-END$")
_MOCK_RE = re.compile(r"^__MOCKYMOCK__ MOCK: (?P<label>.+)$")
# Emitted only by --record-expectations, by build_driver's per-case
# record_targets addition. Unlike MOCK:, this DOES carry a case id (the
# driver already has it in scope at the splice site), so it is attributed
# by id below, the same way FAIL/END are -- not positionally like MOCK:.
# `name` reuses dsl.parser's own _SUBSCRIPTED_NAME (not a bare \S+): a
# subscripted data-name like "WS-TABLE(1, 1)" contains a space after the
# comma (scan_stub_expectations explicitly supports this shape, and
# build_driver emits it into this exact line verbatim), which a plain
# \S+ would truncate at, making the required ": " that follows never
# match and silently dropping the whole recorded value.
_RECORD_RE = re.compile(
    rf"^__MOCKYMOCK__ RECORD (?P<id>\S+) (?P<name>{_SUBSCRIPTED_NAME}): (?P<value>.*)$"
)
# Emitted instead of a RECORD marker for a CAPTURE target whose mocked
# CALL never ran in the case (issue #384): recorded as a None value.
_UNREACHED_RE = re.compile(
    rf"^__MOCKYMOCK__ UNREACHED (?P<id>\S+) (?P<name>{_SUBSCRIPTED_NAME})$"
)
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
    #: (data-name, raw displayed value) pairs. Only populated by a
    #: --record-expectations run. The value is None for a CAPTURE target
    #: whose mocked CALL never ran in the case (an UNREACHED marker).
    recorded: list[tuple[str, str | None]] = field(default_factory=list)

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
    #: (case_id, previous_case_name, new_case_name) for every CASE START
    #: whose id collides with one already seen. previous_case_name is
    #: whichever name this specific collision overwrote -- not necessarily
    #: the very first START to use this id, since the same id can collide
    #: more than once. Defense in depth only -- the
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
    #: (id, name, value) for a RECORD marker whose id never STARTed. Same
    #: non-gating treatment as orphan_ends -- a marker that carries no
    #: pass/fail semantics has no failure evidence to lose by going
    #: unattributed. Only ever populated by a --record-expectations run.
    orphan_records: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        # The per-case cross-check (2026-08-12 audit Finding 1): the
        # SUMMARY line's FAILURES= counter is the driver's own claim, but
        # the formatters render each case from its parsed FAIL/END lines.
        # Deriving the exit code solely from the counter let the two
        # disagree -- a stray stdout line matching the CASE ... FAIL:
        # shape (program-controlled DISPLAY output; no adversarial intent
        # needed) produced exit 0 alongside a rendered [FAIL]. The exit
        # code must never claim less than what the report shows.
        return (
            self.failures == 0
            and self.tests_run > 0
            and not self.orphan_failures
            and not self.duplicate_case_starts
            and all(result.passed for result in self.results)
        )


def _append_continuation(pending: tuple[list, int], continuation: list[str]) -> None:
    """Rejoin a raw value split at its X'0A' bytes (see `parse_stdout`)."""
    values, index = pending
    tail = "\n" + "\n".join(continuation)
    current = values[index]
    if isinstance(current, tuple):
        values[index] = (*current[:-1], current[-1] + tail)
    else:
        values[index] = current + tail


def parse_stdout(stdout: str) -> TestSuiteResult:
    """Parse a compiled test binary's captured stdout into a TestSuiteResult.

    A FAIL or RECORD marker that DISPLAYs a raw field value is followed by
    a VALUE-END marker (issue #285, 2026-08-12 audit Finding 11): a value
    holding byte X'0A' splits its marker across physical lines, and the
    lines between the marker and VALUE-END are rejoined to it with LF, so
    neither a recorded golden nor a failure reason is cut at the byte.
    Without a VALUE-END (an older binary), the continuation is dropped as
    before."""
    suite = TestSuiteResult(suite_name="")
    by_id: dict[str, TestResult] = {}
    # Where the last raw-value marker's value lives -- (list, index), the
    # value being a str or the second item of a tuple -- and the lines
    # seen since it, pending a VALUE-END.
    pending: tuple[list, int] | None = None
    continuation: list[str] = []
    # MOCK: carries no case id, so it belongs to the case whose START was
    # seen and whose END was not; between cases (BEFORE-ALL/AFTER-ALL) it
    # belongs to no case at all (issue #334).
    open_case: TestResult | None = None

    # Split on LF only (dropping a CRLF's CR), never `str.splitlines()`:
    # that also breaks on form feed, VT, \x1c-\x1e, NEL and U+2028 -- bytes
    # a PIC X field can legitimately hold (X'0C' is common in data), and a
    # DISPLAY writes them raw. A FAIL/RECORD marker carrying one was cut
    # there and the rest silently dropped: a truncated failure reason, and
    # a --record-expectations golden that fails the very next run.
    for line in stdout.split("\n"):
        if line.endswith("\r"):
            line = line[:-1]
        # A marker need not start its physical line: a program's own
        # DISPLAY ... WITH NO ADVANCING leaves its text pending, and the
        # driver's next marker is appended to it ("PROGRESS...__MOCKYMOCK__
        # CASE 001 FAIL: ..."). Anchoring at column 1 dropped that marker --
        # a failing case reported PASS, a passing one CRASH (issue #139) --
        # so parse from the first marker on the line; whatever precedes it
        # is the program's output.
        marker_at = line.find(_MARKER)
        if marker_at < 0:
            if pending is not None:
                continuation.append(line)
            continue
        if marker_at > 0:
            line = line[marker_at:]
        if _VALUE_END_RE.match(line) is not None:
            if pending is not None and continuation:
                _append_continuation(pending, continuation)
            pending, continuation = None, []
            continue
        pending, continuation = None, []
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
            open_case = result
        elif (m := _CASE_FAIL_RE.match(line)) is not None:
            target = by_id.get(m.group("id"))
            if target is not None:
                target.failure_reasons.append(m.group("reason"))
                pending = (target.failure_reasons, len(target.failure_reasons) - 1)
            else:
                suite.orphan_failures.append((m.group("id"), m.group("reason")))
                pending = (suite.orphan_failures, len(suite.orphan_failures) - 1)
        elif (m := _MOCK_RE.match(line)) is not None:
            if open_case is not None:
                open_case.mock_hits.append(m.group("label"))
        elif (m := _RECORD_RE.match(line)) is not None:
            target = by_id.get(m.group("id"))
            if target is not None:
                target.recorded.append((m.group("name"), m.group("value")))
                pending = (target.recorded, len(target.recorded) - 1)
            else:
                suite.orphan_records.append(
                    (m.group("id"), m.group("name"), m.group("value"))
                )
                pending = (suite.orphan_records, len(suite.orphan_records) - 1)
        elif (m := _UNREACHED_RE.match(line)) is not None:
            target = by_id.get(m.group("id"))
            if target is not None:
                target.recorded.append((m.group("name"), None))
        elif (m := _SUMMARY_RE.match(line)) is not None:
            suite.tests_run = int(m.group("run"))
            suite.failures = int(m.group("failures"))
        elif (m := _CASE_END_RE.match(line)) is not None:
            case_id = m.group("id")
            target = by_id.get(case_id)
            if target is not None:
                target.ended = True
                if target is open_case:
                    open_case = None
            else:
                suite.orphan_ends.append(case_id)

    return suite
