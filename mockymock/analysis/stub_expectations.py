"""Finds `*> STUB EXPECT <data-name> [-- <note>]` comments in raw `.cut`
text and attributes each one to the ordinary (non-PROVIDER) TESTCASE it
falls inside, by that case's runtime case id.

This is a raw-text scanner, not a grammar addition: `mockymock collect`
parses `.cut` files with no matching `.cbl` at all (see `.okf/cli.md`), and
a stub comment only matters to `mockymock run --record-expectations` -- one
caller, not the shared `parse_cut()` path every subcommand relies on. See
docs/2026-08-04-record-expectations-design.md for the full design.

Callers are expected to run this only against a `.cut` file that already
passed `parse_cut()` (i.e. `run_static_checks` reported no problems) --
every `MOCK`/`END-MOCK` pair is therefore already known to be balanced,
which is what makes the lightweight `in_mock` tracking below safe: it does
not need to be a real parser, only agree with one that already validated
the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mockymock._lines import split_cut_lines
from mockymock.dsl.model import MockTestSuite
from mockymock.dsl.parser import _DOTTED_NAME_RE, _SUBSCRIPTED_NAME, _TESTCASE_RE

_TESTCASE_HEADER_RE = re.compile(r'^\s*TESTCASE\s+"')
_MOCK_OPEN_RE = re.compile(r"^\s*MOCK\s+\S")
# A PROVIDER block is not part of any TESTCASE (the parser closes the
# preceding case when one opens), so it bounds attribution just like a
# TESTCASE header does -- a stub inside it belongs to no case.
_PROVIDER_HEADER_RE = re.compile(r"^\s*PROVIDER\s+\S")
_MOCK_CLOSE_RE = re.compile(r"^\s*END-MOCK\.?\s*$", re.IGNORECASE)
# A TESTCASE's PERFORM line: its RECORD point is after it, and the parser
# refuses an EXPECT above it (issue #150).
_PERFORM_LINE_RE = re.compile(r"^\s*PERFORM\s")
_STUB_RE = re.compile(
    rf"^\s*\*>\s*STUB EXPECT\s+(?P<name>{_SUBSCRIPTED_NAME})\s*"
    rf"(?:--\s*(?P<note>.*?)\s*)?$"
)

# Any `*> STUB EXPECT` comment at all, parseable or not: one `_STUB_RE`
# rejects is reported skipped, never silently dropped (issue #255 -- older
# scaffolds wrote `*> STUB EXPECT WRITE OUT-REC -- ...`).
_ANY_STUB_RE = re.compile(r"^\s*\*>\s*STUB EXPECT\b\s*(?P<rest>.*?)\s*$")


@dataclass
class StubExpectation:
    """One `*> STUB EXPECT` comment found in the raw `.cut` text, attributed
    to a real, recordable (non-PROVIDER) TESTCASE."""

    line: int  # 1-based .cut line of the comment itself
    data_name: str
    note: str | None
    #: 1-based position in MockTestSuite.test_cases -- the same index
    #: driver.py's UT-TESTCASE-{index:03d} / case-id convention uses.
    case_index: int


@dataclass
class SkippedStub:
    """A `*> STUB EXPECT` comment found but not attributable to a
    recordable case -- reported, never silently dropped."""

    line: int
    data_name: str
    reason: str


@dataclass
class StubScanResult:
    stubs: list[StubExpectation]
    skipped: list[SkippedStub]


def scan_stub_expectations(cut_text: str, suite: MockTestSuite) -> StubScanResult:
    """Scan `cut_text` (the raw `.cut` file contents `suite` was parsed
    from) for `*> STUB EXPECT` comments and resolve each one to the
    TESTCASE it belongs to.

    A stub is attributed to the nearest preceding `TESTCASE "..."` header
    line. That header's line number is then cross-referenced against
    `suite.test_cases` (a non-PROVIDER case's `.line` is documented to be
    its original header line verbatim -- see `.okf/dsl.md`) to recover the
    case's real 1-based position, which is exactly the case id `driver.py`
    will assign it at codegen time. A header carrying `USING PROVIDER`
    expands into N independently-lined runtime cases from one physical
    template block -- a shape this scanner does not attempt to resolve (see
    the design doc's Scope) -- so a stub whose owning header is
    provider-templated is reported skipped, not guessed at.

    Pass the POST-`--case`/`--tag`-filter suite (`checks.filter_suite_cases`
    already applied) -- the same object `build_driver` will iterate -- so a
    stub's `case_index` always means the same thing `build_driver` means by
    it. A TESTCASE header with no matching `suite.test_cases` entry at all
    (most commonly: that case was excluded by `--case`/`--tag` this run) is
    reported skipped rather than guessed at.
    """
    raw_lines = split_cut_lines(cut_text)

    # (line, kind): kind is "case", "provider-case" (TESTCASE ... USING
    # PROVIDER) or "provider-block" (a PROVIDER data block).
    headers: list[tuple[int, str]] = []
    # TESTCASE header line -> line of that case's PERFORM.
    perform_line_by_header: dict[int, int] = {}
    in_mock = False
    for line_no, text in enumerate(raw_lines, start=1):
        if in_mock:
            if _MOCK_CLOSE_RE.match(text):
                in_mock = False
            continue
        if _MOCK_OPEN_RE.match(text):
            in_mock = True
            continue
        if _TESTCASE_HEADER_RE.match(text):
            # Classified with the parser's own TESTCASE grammar, not a
            # substring test: "USING PROVIDER" inside the quoted case NAME
            # misread an ordinary case as provider-templated (its stubs
            # skipped), and `USING  PROVIDER` with extra spaces -- which
            # the parser accepts -- misread a templated one as ordinary.
            header = _TESTCASE_RE.match(text.strip())
            is_provider = header is not None and header.group("provider") is not None
            kind = "provider-case" if is_provider else "case"
            headers.append((line_no, kind))
        elif _PROVIDER_HEADER_RE.match(text):
            headers.append((line_no, "provider-block"))
        elif _PERFORM_LINE_RE.match(text) and headers:
            perform_line_by_header.setdefault(headers[-1][0], line_no)

    case_index_by_line = {
        case.line: index for index, case in enumerate(suite.test_cases, start=1)
    }

    stubs: list[StubExpectation] = []
    skipped: list[SkippedStub] = []
    in_mock = False
    for line_no, text in enumerate(raw_lines, start=1):
        if in_mock:
            if _MOCK_CLOSE_RE.match(text):
                in_mock = False
            continue
        if _MOCK_OPEN_RE.match(text):
            in_mock = True
            continue

        m = _STUB_RE.match(text)
        if m is None:
            loose = _ANY_STUB_RE.match(text)
            if loose is not None:
                rest = loose.group("rest").partition("--")[0].strip()
                skipped.append(
                    SkippedStub(
                        line_no,
                        rest,
                        "not a data name -- write `*> STUB EXPECT <data-name>` "
                        "(for a WRITE, the record it writes)",
                    )
                )
            continue
        name = m.group("name")
        note = m.group("note") or None
        if _DOTTED_NAME_RE.search(name.partition("(")[0]):
            # `RECORD.FIELD`, left by generate --with-data when the leaf
            # is ambiguous: not a COBOL name, so not recordable (#144).
            skipped.append(
                SkippedStub(
                    line_no,
                    name,
                    "a dotted RECORD.FIELD name is not COBOL -- write the "
                    "EXPECT by hand for this field",
                )
            )
            continue

        owning_header: tuple[int, str] | None = None
        for header_line, kind in headers:
            if header_line > line_no:
                break
            owning_header = (header_line, kind)

        if owning_header is None:
            skipped.append(SkippedStub(line_no, name, "not inside any TESTCASE"))
            continue
        header_line, kind = owning_header
        if kind == "provider-block":
            skipped.append(
                SkippedStub(
                    line_no,
                    name,
                    f"inside the PROVIDER block at line {header_line}, "
                    f"not inside any TESTCASE",
                )
            )
            continue
        if kind == "provider-case":
            skipped.append(
                SkippedStub(
                    line_no,
                    name,
                    "inside a PROVIDER-templated TESTCASE, unsupported in v1",
                )
            )
            continue
        perform_line = perform_line_by_header.get(header_line)
        if perform_line is None or line_no < perform_line:
            # The recorded value is the post-PERFORM state and the rewrite
            # replaces the stub line in place: an EXPECT above the PERFORM
            # is refused by the parser (issue #150), so recording it would
            # leave a .cut that no longer runs.
            skipped.append(
                SkippedStub(
                    line_no,
                    name,
                    "above the PERFORM of its TESTCASE -- assertions are "
                    "checked after the PERFORM, so move the stub below it "
                    "to record it",
                )
            )
            continue
        case_index = case_index_by_line.get(header_line)
        if case_index is None:
            # Most commonly: this TESTCASE was excluded by --case/--tag this
            # run (filter_suite_cases removes it from suite.test_cases
            # entirely, so it simply has no entry here). Could also mean a
            # non-provider header this scan found didn't match any parsed
            # MockTestCase.line for some other reason -- either way, fail
            # closed (skip, don't guess a case id) rather than misattribute.
            skipped.append(
                SkippedStub(
                    line_no,
                    name,
                    f"TESTCASE at line {header_line} was not run this time "
                    f"(excluded by --case/--tag, or did not resolve to a "
                    f"parsed test case)",
                )
            )
            continue
        stubs.append(StubExpectation(line_no, name, note, case_index))

    return StubScanResult(stubs=stubs, skipped=skipped)


def skip_unsubscripted_table_stubs(
    scan: StubScanResult, table_names: set[str] | frozenset[str]
) -> StubScanResult:
    """Move every stub naming a table element with no subscript
    (`*> STUB EXPECT LK-AMT` for `LK-AMT` under an OCCURS) from `stubs` to
    `skipped`: the driver would splice `DISPLAY LK-AMT`, which does not
    compile, and the whole run would fail (issue #474). `table_names` are
    the uppercased names declared only inside a table
    (`record_rewrite.table_fields`)."""
    kept: list[StubExpectation] = []
    skipped = list(scan.skipped)
    for stub in scan.stubs:
        base, paren, _ = stub.data_name.partition("(")
        leaf = base.strip().split()[0].upper() if base.strip() else ""
        if not paren and leaf in table_names:
            skipped.append(
                SkippedStub(
                    stub.line,
                    stub.data_name,
                    "it is an element of an OCCURS table and names no "
                    "occurrence -- add a subscript (e.g. "
                    f"`*> STUB EXPECT {stub.data_name}(1)`)",
                )
            )
        else:
            kept.append(stub)
    return StubScanResult(stubs=kept, skipped=skipped)
