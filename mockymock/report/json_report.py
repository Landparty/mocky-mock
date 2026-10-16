"""Machine-readable JSON run report (`mockymock run --json-report`).

Where the JUnit XML formatter targets CI collectors, this report targets
editor integrations (the VS Code extension): it carries everything the XML
cannot -- the `.cut` line of each TESTCASE, the line of the specific
EXPECT/VERIFY that failed, the expected/actual pair split into separate
fields, tags, and an explicit entry (status "not_run") for every selected
case the binary never reached. Attribution works by re-matching the
driver's failure-reason strings (see splicer/driver.py's DISPLAY codegen)
against the parsed `.cut` model, so no COBOL codegen changes are involved;
a reason that matches no directive still appears, just without location or
expected/actual fields.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from mockymock.dsl.model import MockTestCase, MockTestSuite
from mockymock.report.results import TestResult, TestSuiteResult

JSON_REPORT_VERSION = 1

# The two failure-reason shapes _emit_case in splicer/driver.py can print.
# The ", got " separator can occur on BOTH sides of the codegen's own: the
# expected value may legally contain it, and so may the runtime value the
# driver DISPLAYs after it (a message field). No split point is safe for
# both, so _attribute_failure first matches the directive's exact rendered
# head; the LAST-occurrence split is only the fallback for a reason no
# parsed directive renders to.
_EXPECT_PREFIX = "expected "
_VERIFY_PREFIX = "VERIFY "
_GOT_SEPARATOR = ", got "

# An EXPECT failure head after _EXPECT_PREFIX: `<name> <operator>
# <expected>`, where <operator> is one of the canonical relation operators
# an ExpectDirective can carry (model.EXPECT_OPERATORS -- driver.py echoes
# the directive's own operator into the FAIL line verbatim). Compound
# alternatives must come before their prefixes ("NOT >=" before "NOT >",
# ">=" before ">") or the longer operator mis-splits. The non-greedy name
# stops at the FIRST operator occurrence, mirroring the pre-operator
# behavior of splitting on the first " = " -- an expected value that itself
# contains an operator-shaped substring keeps it.
_EXPECT_HEAD_RE = re.compile(
    r"^(?P<name>.+?) (?P<op>NOT >=|NOT <=|NOT =|NOT >|NOT <|>=|<=|=|>|<) "
    r"(?P<expected>.*)$"
)


@dataclass
class AttributedFailure:
    message: str
    kind: str  # "expect" | "verify" | "unknown"
    line: int | None = None
    expected: str | None = None
    actual: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "kind": self.kind,
            "line": self.line,
            "expected": self.expected,
            "actual": self.actual,
        }


def _attribute_failure(reason: str, case: MockTestCase | None) -> AttributedFailure:
    """Match one driver failure-reason string back to the EXPECT/VERIFY
    directive that produced it, recovering the .cut line and the
    expected/actual pair. Directives are matched by name/key (first match
    wins): the driver emits checks in directive order and each directive
    fails at most once per run, so name collisions across *distinct* lines
    only arise when the same field/key is asserted twice in one case -- in
    which case the first line is still a correct place to point the editor.
    """
    # Exact match first: the driver renders each EXPECT's FAIL head
    # verbatim from the directive, so when the parsed case is at hand the
    # head is known byte-for-byte and everything after it is the runtime
    # value -- which may itself contain ", got " (a message field). The
    # rsplit heuristic below would split inside that value instead.
    if case is not None and reason.startswith(_EXPECT_PREFIX):
        for expectation in case.expectations:
            prefix = (
                f"{_EXPECT_PREFIX}{expectation.data_name} {expectation.operator} "
                f"{expectation.expected_value}{_GOT_SEPARATOR}"
            )
            if reason.startswith(prefix):
                return AttributedFailure(
                    message=reason,
                    kind="expect",
                    line=expectation.line or None,
                    expected=(
                        expectation.expected_value
                        if expectation.operator == "="
                        else f"{expectation.operator} {expectation.expected_value}"
                    ),
                    actual=reason[len(prefix) :].rstrip(),
                )
    if _GOT_SEPARATOR in reason:
        head, actual = reason.rsplit(_GOT_SEPARATOR, 1)
        actual = actual.rstrip()
        if (
            head.startswith(_EXPECT_PREFIX)
            and (m := _EXPECT_HEAD_RE.match(head[len(_EXPECT_PREFIX) :])) is not None
        ):
            data_name = m.group("name")
            # Plain equality keeps the bare value (the pre-operator report
            # shape, so existing consumers see no change); any other
            # operator is prefixed so `expected` stays self-describing
            # ("> 5", "NOT = 0").
            expected = (
                m.group("expected")
                if m.group("op") == "="
                else f"{m.group('op')} {m.group('expected')}"
            )
            line = None
            if case is not None:
                for expectation in case.expectations:
                    if expectation.data_name == data_name:
                        line = expectation.line or None
                        break
            return AttributedFailure(
                message=reason,
                kind="expect",
                line=line,
                expected=expected,
                actual=actual,
            )
        if head.startswith(_VERIFY_PREFIX) and " WAS CALLED " in head:
            target, expectation_text = head[len(_VERIFY_PREFIX) :].rsplit(
                " WAS CALLED ", 1
            )
            line = None
            if case is not None:
                for verification in case.verifications:
                    described = f"{verification.category.keyword} {verification.key}"
                    if described == target:
                        line = verification.line or None
                        break
            return AttributedFailure(
                message=reason,
                kind="verify",
                line=line,
                expected=expectation_text,
                actual=actual,
            )
    return AttributedFailure(message=reason, kind="unknown")


def _case_status(result: TestResult) -> str:
    if result.crashed:
        return "crashed"
    return "passed" if result.passed else "failed"


def _case_index(case_id: str) -> int | None:
    """The driver assigns case_id = f"{index:03d}" over the same
    (possibly --case/--tag filtered) suite.test_cases list build_driver
    was given -- a 1-based position, not a name. Returns None for anything
    that doesn't parse as that, so a caller degrades to "no .cut model
    match" instead of crashing."""
    try:
        return int(case_id)
    except ValueError:
        return None


def _is_risky(result: TestResult, model_case: MockTestCase | None) -> bool:
    """Passed while asserting nothing (PHPUnit's "risky"): still a pass,
    but the pass only proves the PERFORM ran. Unknown without the .cut
    model, so never claimed then."""
    return (
        model_case is not None
        and not result.crashed
        and result.passed
        and model_case.assertion_count == 0
    )


def risky_case_ids(
    suite_result: TestSuiteResult, cut_suite: MockTestSuite | None
) -> list[str]:
    """Case ids of the cases that passed with no EXPECT/VERIFY, matched to
    the .cut model by position the same way `build_json_report` does (ids,
    not names: names need not be unique), for the console formatter."""
    if cut_suite is None:
        return []
    by_index = dict(enumerate(cut_suite.test_cases, start=1))
    names = []
    for result in suite_result.results:
        index = _case_index(result.case_id)
        model_case = by_index.get(index) if index is not None else None
        if _is_risky(result, model_case):
            names.append(result.case_id)
    return names


def not_run_case_names(
    suite_result: TestSuiteResult, cut_suite: MockTestSuite | None
) -> list[str]:
    """Names of the selected .cut cases the binary never printed a START
    marker for -- the same position match `build_json_report` uses for its
    "not_run" entries, for the console and JUnit formatters (issue #150)."""
    if cut_suite is None:
        return []
    seen = {_case_index(result.case_id) for result in suite_result.results}
    return [
        case.name
        for position, case in enumerate(cut_suite.test_cases, start=1)
        if position not in seen
    ]


def build_json_report(
    suite_result: TestSuiteResult,
    cut_suite: MockTestSuite | None = None,
    crash_detail: str | None = None,
    cut_file: str | None = None,
    program_file: str | None = None,
) -> dict[str, Any]:
    """Assemble the report dict. `cut_suite` is the parsed (and, under
    --case/--tag, already filtered) .cut model; when provided it supplies
    line numbers, tags, failure attribution, and synthesizes a "not_run"
    entry for every selected case the binary never printed a START marker
    for (a mid-suite crash ate them). Matched by position (case_id), not
    name: TESTCASE names are not required to be unique, and a name-keyed
    match would drop or misattribute duplicate-named cases."""
    cut_cases_by_index: dict[int, MockTestCase] = {}
    if cut_suite is not None:
        for position, cut_case in enumerate(cut_suite.test_cases, start=1):
            cut_cases_by_index[position] = cut_case

    cases: list[dict[str, Any]] = []
    seen_indices: set[int] = set()
    for result in suite_result.results:
        index = _case_index(result.case_id)
        model_case = cut_cases_by_index.get(index) if index is not None else None
        if index is not None:
            seen_indices.add(index)
        failures = [
            _attribute_failure(reason, model_case).to_dict()
            for reason in result.failure_reasons
        ]
        entry: dict[str, Any] = {
            "name": result.case_name,
            "line": (model_case.line or None) if model_case else None,
            "tags": list(model_case.tags) if model_case else [],
            "status": _case_status(result),
            "failures": failures,
            # Additive (report version unchanged): null when there is no
            # .cut model to count from.
            "assertions": model_case.assertion_count if model_case else None,
            "risky": _is_risky(result, model_case),
        }
        if result.crashed:
            entry["crashDetail"] = crash_detail
        cases.append(entry)

    not_run = 0
    if cut_suite is not None:
        for position, cut_case in enumerate(cut_suite.test_cases, start=1):
            if position in seen_indices:
                continue
            not_run += 1
            cases.append(
                {
                    "name": cut_case.name,
                    "line": cut_case.line or None,
                    "tags": list(cut_case.tags),
                    "status": "not_run",
                    "failures": [],
                    "assertions": cut_case.assertion_count,
                    "risky": False,
                    "crashDetail": crash_detail,
                }
            )

    return {
        "version": JSON_REPORT_VERSION,
        "suite": {
            "name": suite_result.suite_name or (cut_suite.name if cut_suite else ""),
            "line": (cut_suite.line or None) if cut_suite else None,
        },
        "cutFile": cut_file,
        "programFile": program_file,
        "cases": cases,
        "orphanFailures": [
            {"caseId": case_id, "message": reason}
            for case_id, reason in suite_result.orphan_failures
        ],
        "duplicateCaseStarts": [
            # previousCaseName is whatever name this specific collision
            # overwrote -- not necessarily the *first* START to use this
            # id, since the same id can collide more than once.
            {
                "caseId": case_id,
                "previousCaseName": previous_name,
                "duplicateCaseName": new_name,
            }
            for case_id, previous_name, new_name in suite_result.duplicate_case_starts
        ],
        "orphanEnds": list(suite_result.orphan_ends),
        "orphanRecords": [
            # A RECORD marker whose case id never STARTed -- non-gating
            # (no pass/fail evidence to lose) but previously surfaced in
            # NO output format at all (2026-08-12 audit Finding 12).
            {"caseId": case_id, "dataName": name, "value": value}
            for case_id, name, value in suite_result.orphan_records
        ],
        "summary": {
            "testsRun": suite_result.tests_run or len(suite_result.results),
            "casesFailed": sum(
                1 for r in suite_result.results if r.failure_reasons and not r.crashed
            ),
            "casesCrashed": sum(1 for r in suite_result.results if r.crashed),
            "casesNotRun": not_run,
            "casesRisky": sum(1 for case in cases if case["risky"]),
        },
    }


def format_json_report(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2) + "\n"
