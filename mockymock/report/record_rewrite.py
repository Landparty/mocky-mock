"""Combines a stub scan (`analysis.stub_expectations`) with a recorded test
run (`report.results`) into a rewritten `.cut` file: every stub whose case
actually reached the record point becomes a real `EXPECT` line, in place.
See docs/2026-08-04-record-expectations-design.md for the full design.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mockymock.analysis.stub_expectations import (
    SkippedStub,
    StubExpectation,
    StubScanResult,
)
from mockymock.report.results import TestSuiteResult

_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")


def render_expect_value(raw_value: str) -> str:
    """Render one RECORDed field's raw DISPLAY text as `.cut` `EXPECT`
    value text.

    A plain numeric-looking value is rendered bare (`12345`, `-3.50`);
    anything else is quoted, with trailing spaces trimmed and embedded `"`
    doubled the same way `driver._display_text` already escapes one.
    Trimming trailing spaces changes no runtime behavior: COBOL's `=`
    comparison pads the shorter of two operands with spaces before
    comparing, so `WS-NAME = "SMITH"` and `WS-NAME = "SMITH    "` are the
    identical comparison against a fixed-width alphanumeric field.

    This decides bare-vs-quoted from the observed text's own shape, not by
    resolving the field's PICTURE -- see the design doc's "Value
    formatting" section for why, and for the flagged numeric-edited
    PICTURE caveat (`PIC ZZZ9`-style fields render leading spaces/`$`/`,`
    and so fall to the quoted path here, not yet empirically verified
    against a real EXPECT comparison for that PICTURE family).
    """
    if _NUMERIC_RE.match(raw_value):
        return raw_value
    escaped = raw_value.rstrip().replace('"', '""')
    return f'"{escaped}"'


@dataclass
class RecordedExpectation:
    stub: StubExpectation
    #: Raw text as DISPLAY rendered it -- render_expect_value() does the
    #: bare-vs-quoted decision at rewrite time, not here.
    value: str


@dataclass
class RecordingReport:
    recorded: list[RecordedExpectation] = field(default_factory=list)
    skipped: list[SkippedStub] = field(default_factory=list)


def build_recording_report(
    scan: StubScanResult, suite_result: TestSuiteResult
) -> RecordingReport:
    """Match every stub the scanner found against this run's recorded
    values (by case id + data-name).

    `scan.stubs` only ever contains stubs whose case survived
    `--case`/`--tag` selection (the scanner is expected to run against the
    post-filter suite -- see `scan_stub_expectations`), so the only reason
    a stub's case-id has no matching recorded value here is that the case
    started but crashed before reaching the record point (a `RECORD`
    marker, like `EXPECT`/`VERIFY` checks, is only ever printed after the
    case's own `PERFORM` returns -- a case that never gets there prints
    none of its RECORD markers, not a partial set).
    """
    recorded_by_case: dict[str, dict[str, str]] = {
        result.case_id: dict(result.recorded) for result in suite_result.results
    }

    report = RecordingReport(skipped=list(scan.skipped))
    for stub in scan.stubs:
        case_id = f"{stub.case_index:03d}"
        values = recorded_by_case.get(case_id, {})
        if stub.data_name not in values:
            report.skipped.append(
                SkippedStub(
                    stub.line,
                    stub.data_name,
                    "case crashed before reaching the record point",
                )
            )
            continue
        report.recorded.append(
            RecordedExpectation(stub=stub, value=values[stub.data_name])
        )
    return report


def rewrite_cut_text(cut_text: str, report: RecordingReport) -> str | None:
    """Replace each recorded stub's comment line with a real `EXPECT` line,
    preserving that line's own leading whitespace. No line is inserted or
    removed (a stub comment and its replacement are both exactly one line),
    so application order never matters.

    Returns `None` (write nothing) when nothing was recorded -- a command
    that recorded zero stubs must not touch the file at all.
    """
    if not report.recorded:
        return None
    lines = cut_text.splitlines()
    for item in report.recorded:
        stub = item.stub
        original = lines[stub.line - 1]
        indent = original[: len(original) - len(original.lstrip())]
        rendered = render_expect_value(item.value)
        lines[stub.line - 1] = f"{indent}EXPECT {stub.data_name} TO BE {rendered}"
    text = "\n".join(lines)
    return text + "\n" if cut_text.endswith("\n") else text
