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
from dataclasses import dataclass
from typing import Any

from mockymock.dsl.model import MockTestCase, MockTestSuite
from mockymock.report.results import TestResult, TestSuiteResult

JSON_REPORT_VERSION = 1

# The two failure-reason shapes _emit_case in splicer/driver.py can print.
# The ", got " separator also appears in the message tail (`, got " WS-X`),
# and the expected value itself may legally contain ", got " -- so parsing
# splits on the LAST occurrence, which is always the codegen's own.
_EXPECT_PREFIX = "expected "
_VERIFY_PREFIX = "VERIFY "
_GOT_SEPARATOR = ", got "


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
    if _GOT_SEPARATOR in reason:
        head, actual = reason.rsplit(_GOT_SEPARATOR, 1)
        actual = actual.strip()
        if head.startswith(_EXPECT_PREFIX) and " = " in head:
            data_name, expected = head[len(_EXPECT_PREFIX) :].split(" = ", 1)
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
    for (a mid-suite crash ate them)."""
    cut_cases_by_name: dict[str, MockTestCase] = {}
    if cut_suite is not None:
        for cut_case in cut_suite.test_cases:
            cut_cases_by_name.setdefault(cut_case.name, cut_case)

    cases: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for result in suite_result.results:
        model_case = cut_cases_by_name.get(result.case_name)
        seen_names.add(result.case_name)
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
        }
        if result.crashed:
            entry["crashDetail"] = crash_detail
        cases.append(entry)

    not_run = 0
    if cut_suite is not None:
        for cut_case in cut_suite.test_cases:
            if cut_case.name in seen_names:
                continue
            not_run += 1
            cases.append(
                {
                    "name": cut_case.name,
                    "line": cut_case.line or None,
                    "tags": list(cut_case.tags),
                    "status": "not_run",
                    "failures": [],
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
        "summary": {
            "testsRun": suite_result.tests_run or len(suite_result.results),
            "casesFailed": sum(
                1 for r in suite_result.results if r.failure_reasons and not r.crashed
            ),
            "casesCrashed": sum(1 for r in suite_result.results if r.crashed),
            "casesNotRun": not_run,
        },
    }


def format_json_report(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2) + "\n"
