"""Combines a stub scan (`analysis.stub_expectations`) with a recorded test
run (`report.results`) into a rewritten `.cut` file: every stub whose case
actually reached the record point becomes a real `EXPECT` line, in place.
See docs/2026-08-04-record-expectations-design.md for the full design.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mockymock._decimal import delocalize_numeric, localize_numeric
from mockymock.analysis.stub_expectations import (
    SkippedStub,
    StubExpectation,
    StubScanResult,
)
from mockymock.report.results import TestSuiteResult
from mockymock.splicer.reset import _POINTER_USAGES

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
# C0/C1 controls, DEL and the Unicode line/paragraph separators: none can
# be written raw into a quoted `.cut` literal (see render_expect_value).
_CONTROL_CHAR_RE = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]")


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


def render_expect_value(
    raw_value: str, picture: str | None = None, *, decimal_comma: bool = False
) -> str:
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

    `decimal_comma` (`DECIMAL-POINT IS COMMA`, issue #230): the program
    DISPLAYs `00125,00` and must be given `125,00` back -- a period there
    is a sentence end and the next run does not compile.
    """
    numeric_text = delocalize_numeric(raw_value, decimal_comma)
    scale = numeric_scale(picture)
    if scale is not None:
        rendered = _render_numeric(numeric_text, scale)
        if rendered is not None:
            return localize_numeric(rendered, decimal_comma)
    if _NUMERIC_RE.match(numeric_text) and not is_alphanumeric_picture(picture):
        return localize_numeric(numeric_text, decimal_comma)
    # Spaces only: str.rstrip() also strips X'09'-X'0D' and X'1C'-X'1F',
    # which are ordinary field data (X'0C' ends every positive packed
    # zero), and dropping them wrote a golden that failed the next run
    # (issue #194). COBOL's space padding makes only spaces insignificant.
    trimmed = raw_value.rstrip(" ")
    if not trimmed:
        # `""` is a zero-length literal: GnuCOBOL warns and assumes a
        # space, IBM Enterprise COBOL rejects it. SPACES is the same
        # comparison and valid everywhere.
        return "SPACES"
    if _CONTROL_CHAR_RE.search(trimmed) and "\ufffd" not in trimmed:
        # A control byte (X'0C' and friends are ordinary field data) cannot
        # sit raw inside a quoted golden: the .cut is split into lines on
        # form feed / VT / NEL too, so the EXPECT line itself broke apart
        # and the rewritten file no longer parsed. A hexadecimal literal
        # carries the same bytes and compares the same way (alphanumeric,
        # space-padded).
        return f'X"{trimmed.encode("utf-8").hex().upper()}"'
    escaped = trimmed.replace('"', '""')
    return f'"{escaped}"'


def has_p_scaling(picture: str | None) -> bool:
    """Whether `picture` is a numeric PICTURE with `P` scaling positions
    (`9(3)PP`, `SVP9(2)`). DISPLAY prints only the stored digits of such
    an item (12300 in a `9(3)PP` shows as `00123`), so its recorded text
    is not the value it stands for and no golden can be built from it."""
    if not picture or is_alphanumeric_picture(picture):
        return False
    return "P" in _PICTURE_REPEAT_RE.sub(lambda m: m.group(1), picture.upper())


def is_alphanumeric_picture(picture: str | None) -> bool:
    """Whether `picture` is alphanumeric/alphabetic/national/DBCS (it
    holds an `X`, `A`, `N` or `G` symbol). A value recorded from such a
    field is compared as text, so it must be rendered quoted even when it
    looks numeric: `IF WS-X NOT = -3` or `NOT = 1.5` against a `PIC X`
    field holding `-3` / `1.5` is TRUE under GnuCOBOL (verified against
    the mockymock-cobc container), so a bare golden fails on the very next
    run -- and a non-integer or signed literal compared with an
    alphanumeric item is not even valid COBOL."""
    if not picture:
        return False
    expanded = _PICTURE_REPEAT_RE.sub(
        lambda m: m.group(1) * int(m.group(2)), picture.upper()
    )
    return bool(set(expanded) & {"X", "A", "N", "G"})


@dataclass
class RecordedExpectation:
    stub: StubExpectation
    #: Raw text as DISPLAY rendered it -- render_expect_value() does the
    #: bare-vs-quoted decision at rewrite time, not here.
    value: str
    #: The EXPECT value text to write as-is, bypassing render_expect_value:
    #: TRUE/FALSE for a level-88 name, the bare occurrence number for an
    #: INDEXED BY index-name (issue #237).
    rendered: str | None = None


@dataclass
class RecordingReport:
    recorded: list[RecordedExpectation] = field(default_factory=list)
    skipped: list[SkippedStub] = field(default_factory=list)


def build_recording_report(
    scan: StubScanResult,
    suite_result: TestSuiteResult,
    address_items: set[str] | frozenset[str] = frozenset(),
    pictures: dict[str, str] | None = None,
    condition_names: set[str] | frozenset[str] = frozenset(),
    index_names: set[str] | frozenset[str] = frozenset(),
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
        value = queue.pop(0)
        base_name = stub.data_name.partition("(")[0].strip().upper()
        if base_name in condition_names and value.strip() in ("TRUE", "FALSE"):
            # The driver records an 88's truth value (issue #237).
            report.recorded.append(
                RecordedExpectation(stub=stub, value=value, rendered=value.strip())
            )
            continue
        if base_name in index_names:
            # An INDEXED BY index-name DISPLAYs its occurrence number
            # (`+000000003`); quoted, the golden did not compile next run.
            try:
                occurrence = int(value.strip())
            except ValueError:
                report.skipped.append(
                    SkippedStub(
                        stub.line,
                        stub.data_name,
                        f"it is an INDEXED BY index-name whose DISPLAY text "
                        f"{value.strip()!r} is not an occurrence number",
                    )
                )
                continue
            report.recorded.append(
                RecordedExpectation(stub=stub, value=value, rendered=str(occurrence))
            )
            continue
        if base_name in address_items:
            # DISPLAY of a POINTER-family item prints an address, of an
            # INDEX item an implementation-defined number: neither is a
            # value a golden can pin, and `EXPECT P TO BE "0x..."` does not
            # even compile (a pointer is not comparable with a literal).
            report.skipped.append(
                SkippedStub(
                    stub.line,
                    stub.data_name,
                    "it is a USAGE POINTER/PROCEDURE-POINTER/INDEX item, "
                    "whose DISPLAY text is an address, not data -- assert it "
                    "by hand if at all (e.g. TO BE NULL)",
                )
            )
            continue
        if has_p_scaling(picture_for(stub.data_name, pictures)):
            # DISPLAY shows a P-scaled item's stored digits without its
            # scaling positions (12300 in a `9(3)PP` prints `00123`), so
            # the recorded text is not the value: a golden built from it
            # fails the next run (issue #194).
            report.skipped.append(
                SkippedStub(
                    stub.line,
                    stub.data_name,
                    "its PICTURE has P scaling positions, which DISPLAY "
                    "leaves out of the text it prints -- write this EXPECT "
                    "by hand with the scaled value",
                )
            )
            continue
        if "\ufffd" in value:
            # The run's stdout is decoded with errors="replace", so a byte
            # that is not UTF-8 (HIGH-VALUES' X'FF', packed data) arrives
            # as U+FFFD and the real bytes are gone. Quoting the
            # replacement text wrote a golden that failed the next run
            # (issue #146): skip it, and say why.
            report.skipped.append(
                SkippedStub(
                    stub.line,
                    stub.data_name,
                    "its value holds bytes that are not text (HIGH-VALUES, "
                    "binary or packed data) and the run's output could not "
                    "carry them -- write this EXPECT by hand (e.g. TO BE "
                    "HIGH-VALUES)",
                )
            )
            continue
        report.recorded.append(RecordedExpectation(stub=stub, value=value))
    return report


def field_pictures(program, captures=()) -> dict[str, str]:
    """Name (uppercased, unqualified) -> PICTURE for every elementary data
    item in `program`, plus every synthesized `UT-CAP-` capture target
    (`splicer.captures.CapturePlan`, which mirrors its source item's
    PICTURE) -- the names a `*> STUB EXPECT` can point at. A group item
    maps to `X(length)`: it is compared as alphanumeric text whatever its
    content, so `1.5` held in a group must render quoted, never bare
    (issue #194). Best-effort: a layout walk that fails leaves the map
    empty, and rendering falls back to the text-shape check."""
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
    for name, item in index.items():
        if item.get("is_group"):
            length = item.get("byte_length")
            pictures[name] = f"X({length})" if length else "X"
    for plan in captures:
        source_picture = pictures.get(plan.source_name.upper())
        if source_picture is not None:
            pictures[plan.target.upper()] = source_picture
    return pictures


_ADDRESS_USAGES = _POINTER_USAGES | {"INDEX"}


def address_fields(program) -> set[str]:
    """Names (uppercased, unqualified) of every POINTER-family or INDEX
    item in `program` -- the stubs `build_recording_report` must not turn
    into an EXPECT. Best-effort like `field_pictures`."""
    from mockymock.splicer.captures import _data_item_index

    try:
        index = _data_item_index(program)
    except Exception:  # pragma: no cover - never break a run over this
        return set()
    return {
        name
        for name, item in index.items()
        if str(item.get("usage") or "").upper() in _ADDRESS_USAGES
    }


def condition_names(program) -> set[str]:
    """Names (uppercased, unqualified) of every level-88 condition-name in
    `program`, declared once or under several parents alike (none of them
    can be DISPLAYed). Best-effort like `field_pictures`."""
    from cobolparser.generators.data.layout_offsets import compute_program_data_items

    try:
        items = compute_program_data_items(program).get("items", [])
    except Exception:  # pragma: no cover - never break a run over this
        return set()
    return {
        str(item.get("name") or "").upper()
        for item in items
        if item.get("level") == 88 and item.get("name")
    }


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
    *,
    label: bool = True,
    decimal_comma: bool = False,
) -> str | None:
    """Replace each recorded stub's comment line with a real `EXPECT` line,
    preserving that line's own leading whitespace.

    `pictures` (data-name -> PICTURE) lets a plain numeric field's raw
    DISPLAY text be rendered as the numeric literal it stands for -- see
    `render_expect_value`.

    With `label` (the default) each run of consecutive recorded lines also
    gets a `*> CHARACTERIZATION: recorded by ...` comment above it (see
    analysis/assertion_labels.py), so a recorded value can never pass for
    one somebody derived from the program's intent. A recorded value pins
    what the program did, not what it should do. Should the line right
    after the run be a hand-written EXPECT/VERIFY, the label is closed off
    again (by a copy of the label that covered that line, or a blank line
    when none did) so the CHARACTERIZATION label never spreads onto it.
    Labels are inserted bottom-up, so every stub's original line number
    stays valid while the earlier ones are rewritten.

    Returns `None` (write nothing) when nothing was recorded -- a command
    that recorded zero stubs must not touch the file at all. Lines are
    joined with `cut_text`'s own newline (`\r\n` when it has one), so the
    caller must read without newline translation and write with
    `newline=""`.
    """
    if not report.recorded:
        return None
    from mockymock.analysis.assertion_labels import (
        RECORDED_LABEL,
        scan_assertion_labels,
    )

    lines = cut_text.splitlines()
    recorded_lines: set[int] = set()
    for item in report.recorded:
        stub = item.stub
        original = lines[stub.line - 1]
        indent = original[: len(original) - len(original.lstrip())]
        rendered = item.rendered or render_expect_value(
            item.value,
            picture_for(stub.data_name, pictures),
            decimal_comma=decimal_comma,
        )
        lines[stub.line - 1] = f"{indent}EXPECT {stub.data_name} TO BE {rendered}"
        recorded_lines.add(stub.line)

    if label:
        original_lines = cut_text.splitlines()
        covering = {
            a.line: a.label_line
            for a in scan_assertion_labels(cut_text)
            if a.label_line is not None
        }
        runs: list[tuple[int, int]] = []
        for line_no in sorted(recorded_lines):
            if runs and runs[-1][1] == line_no - 1:
                runs[-1] = (runs[-1][0], line_no)
            else:
                runs.append((line_no, line_no))
        for first, last in reversed(runs):
            after = last + 1
            if after <= len(lines) and re.match(
                r"^\s*(EXPECT|VERIFY)\b", lines[after - 1], re.IGNORECASE
            ):
                label_line = covering.get(after)
                closer = original_lines[label_line - 1] if label_line else ""
                lines.insert(last, closer)
            above = lines[first - 2].strip() if first >= 2 else ""
            if above != RECORDED_LABEL:
                indent_text = lines[first - 1]
                indent = indent_text[: len(indent_text) - len(indent_text.lstrip())]
                lines.insert(first - 1, f"{indent}{RECORDED_LABEL}")
    # The file's own newline convention, so a CRLF .cut is not rewritten
    # as LF throughout (issue #199); splitlines() above already took the
    # "\r" off every line.
    newline = "\r\n" if "\r\n" in cut_text else "\n"
    text = newline.join(lines)
    return text + newline if cut_text.endswith("\n") else text
