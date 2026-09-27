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
# How GnuCOBOL -std=mvs (the only mode mockymock compiles in, see
# runtime/docker_toolchain.py) DISPLAYs a plain numeric item: its digits
# with NO decimal point for an implied `V`, and -- for a signed item -- a
# separate sign, trailing for USAGE DISPLAY (`005+`, `00350-`) and leading
# for binary/packed (`+00007`). Verified against the mockymock-cobc
# container (GnuCOBOL 3.2). A decimal point is accepted too, for a runtime
# configured with pretty-display.
_RAW_NUMERIC_RE = re.compile(
    r"^(?P<lead>[+-]?)(?P<int>\d+)(?:\.(?P<frac>\d+))?(?P<trail>[+-]?)$"
)
_PICTURE_REPEAT_RE = re.compile(r"(.)\((\d+)\)")


def numeric_scale(picture: str | None) -> int | None:
    """Digits after the implied decimal point for a plain numeric PICTURE
    (`S9(3)V99` -> 2, `9(5)` -> 0), or None for anything else -- an
    alphanumeric or numeric-edited PICTURE, or one with `P` scaling, whose
    DISPLAY text this module does not re-interpret."""
    if not picture:
        return None
    expanded = _PICTURE_REPEAT_RE.sub(
        lambda m: m.group(1) * int(m.group(2)), picture.upper()
    )
    body = expanded[1:] if expanded.startswith("S") else expanded
    if not body or set(body) - {"9", "V"} or body.count("V") > 1:
        return None
    _, _, fraction = body.partition("V")
    return len(fraction)


def _render_numeric(raw_value: str, scale: int) -> str | None:
    """Rebuild a COBOL numeric literal from a plain numeric item's raw
    DISPLAY text (see _RAW_NUMERIC_RE), or None if the text is not that
    shape (e.g. a field left holding non-numeric bytes)."""
    m = _RAW_NUMERIC_RE.match(raw_value)
    if m is None or (m.group("lead") and m.group("trail")):
        return None
    digits = m.group("int")
    if m.group("frac") is not None:
        digits = f"{digits}.{m.group('frac')}"
    elif scale:
        if len(digits) <= scale:
            digits = digits.rjust(scale + 1, "0")
        digits = f"{digits[:-scale]}.{digits[-scale:]}"
    negative = "-" in (m.group("lead"), m.group("trail"))
    return f"-{digits}" if negative else digits


def render_expect_value(raw_value: str, picture: str | None = None) -> str:
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

    `picture`, when the recorded field's PICTURE is known, is what makes a
    plain numeric item render correctly: under `-std=mvs` DISPLAY drops
    the implied decimal point and prints a separate sign (`00350-` for
    -3.50 in a `S9(3)V99`), which the text-shape check alone would turn
    into a quoted literal (or, for an unsigned `9(3)V99`, the bare but
    100x-too-large `00350`) -- a golden that fails on the very next run.
    """
    scale = numeric_scale(picture)
    if scale is not None:
        rendered = _render_numeric(raw_value, scale)
        if rendered is not None:
            return rendered
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
    post-filter suite -- see `scan_stub_expectations`), so a stub's
    case-id having no matching recorded value here normally means the case
    started but crashed before reaching the record point (a `RECORD`
    marker, like `EXPECT`/`VERIFY` checks, is only ever printed after the
    case's own `PERFORM` returns -- a case that never gets there prints
    none of its RECORD markers, not a partial set). The one other cause is
    a RECORD marker that parsed but could not be attributed to any case
    (`suite_result.orphan_records`) -- reported with its own reason, not
    the misleading crash one (2026-08-12 audit Finding 12).

    Values are matched per (case, data-name) in emission order, NOT via a
    name-keyed dict: two stubs for the same data-name in one TESTCASE
    (e.g. a counter captured before and after a step) each consume their
    own recorded value -- a dict collapse silently gave both stubs the
    LAST value, corrupting the earlier golden (2026-08-12 audit Finding
    10). Emission order is stub line order: `record_targets` is built by
    appending stubs in scan order and the driver DISPLAYs in list order.
    """
    recorded_by_case: dict[str, dict[str, list[str]]] = {}
    for result in suite_result.results:
        queues = recorded_by_case.setdefault(result.case_id, {})
        for name, value in result.recorded:
            queues.setdefault(name, []).append(value)
    # Keyed on (case_id, data_name), not data-name alone: an orphan
    # record for an UNRELATED case id must not hijack a legitimate
    # crashed-before-record diagnosis for this stub's own case (Copilot
    # review on PR #68). The id-matching shape this catches is the
    # lost-START one: the RECORD line parsed with this case's id, but no
    # TestResult exists for that id to attach it to.
    orphaned = {(case_id, name) for case_id, name, _ in suite_result.orphan_records}

    report = RecordingReport(skipped=list(scan.skipped))
    for stub in scan.stubs:
        case_id = f"{stub.case_index:03d}"
        queue = recorded_by_case.get(case_id, {}).get(stub.data_name)
        if not queue:
            if (case_id, stub.data_name) in orphaned:
                reason = (
                    "its RECORD marker was unattributable to any case "
                    "(orphan record -- see the run's parsed output "
                    "anomalies), not recorded for this one"
                )
            else:
                reason = "case crashed before reaching the record point"
            report.skipped.append(SkippedStub(stub.line, stub.data_name, reason))
            continue
        report.recorded.append(RecordedExpectation(stub=stub, value=queue.pop(0)))
    return report


def field_pictures(program, captures=()) -> dict[str, str]:
    """Name (uppercased, unqualified) -> PICTURE for every elementary data
    item in `program`, plus every synthesized `UT-CAP-` capture target
    (`splicer.captures.CapturePlan`, which mirrors its source item's
    PICTURE) -- the names a `*> STUB EXPECT` can point at. Best-effort: a
    layout walk that fails leaves the map empty, and rendering falls back
    to the text-shape check."""
    from mockymock.splicer.captures import _data_item_index

    try:
        index = _data_item_index(program)
    except Exception:  # pragma: no cover - never break a run over this
        return {}
    pictures = {
        name: str(item["picture"])
        for name, item in index.items()
        if item.get("picture") and not item.get("is_group")
    }
    for plan in captures:
        source_picture = pictures.get(plan.source_name.upper())
        if source_picture is not None:
            pictures[plan.target.upper()] = source_picture
    return pictures


def picture_for(data_name: str, pictures: dict[str, str] | None) -> str | None:
    """Look a stub's data-name up in a name (uppercased, unqualified) ->
    PICTURE map, ignoring any subscript/reference-modification group: a
    table element shares its item's PICTURE. A reference-modified name is
    alphanumeric by definition, so it gets no PICTURE."""
    if not pictures:
        return None
    base, paren, subscript = data_name.partition("(")
    if paren and ":" in subscript:
        return None
    return pictures.get(base.strip().upper())


def rewrite_cut_text(
    cut_text: str,
    report: RecordingReport,
    pictures: dict[str, str] | None = None,
) -> str | None:
    """Replace each recorded stub's comment line with a real `EXPECT` line,
    preserving that line's own leading whitespace. No line is inserted or
    removed (a stub comment and its replacement are both exactly one line),
    so application order never matters.

    `pictures` (data-name -> PICTURE) lets a plain numeric field's raw
    DISPLAY text be rendered as the numeric literal it stands for -- see
    `render_expect_value`.

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
        rendered = render_expect_value(
            item.value, picture_for(stub.data_name, pictures)
        )
        lines[stub.line - 1] = f"{indent}EXPECT {stub.data_name} TO BE {rendered}"
    text = "\n".join(lines)
    return text + "\n" if cut_text.endswith("\n") else text
