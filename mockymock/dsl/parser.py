"""Parses .cut files into MockTestSuite objects.

v2 grammar: MOCK takes a category — quoted-key categories
(CALL/MQ/SQL/CICS/DLI) vs bare-COBOL-word categories (the eight file-op
verbs and ACCEPT). `MOCK MQ "X"` is sugar for `MOCK CALL "X"`. CALL alone
takes both forms: `MOCK CALL "X"` mocks a static CALL with literal 'X',
while `MOCK CALL WS-PGM` (bare word) mocks a *dynamic* CALL through the
identifier WS-PGM (parsed as MockCategory.DYNCALL; MQ stays quoted-only —
the MQI is invoked through static CALLs by definition). `MOCK PARAGRAPH
<name>` / `MOCK SECTION <name>` (bare COBOL names) mock an internal flow
target: the named paragraph's/section's body is replaced by the mock body
whenever it is entered through its own header while this test case runs.
VERIFY mirrors the same key syntax; a bare `VERIFY "X"` stays CALL for v1
back-compat, and CALLED/PERFORMED are interchangeable. Lines starting with `*>` outside
MOCK bodies are comments; inside a body they pass through (they're valid
free-form COBOL).

BEFORE-ALL/BEFORE-EACH (see
docs/2026-07-20-before-blocks-and-file-status-design.md): at most one of
each per TESTSUITE, appearing after the TESTSUITE header and before the
first TESTCASE, holding MOCK directives only. Resolved by desugaring,
purely inside this module: after the file is fully parsed, each
TESTCASE's own mocks list is extended with every BEFORE-EACH mock whose
(category, key) it didn't already declare, then every BEFORE-ALL mock
neither it nor BEFORE-EACH already declared -- so TESTCASE overrides
BEFORE-EACH overrides BEFORE-ALL, silently. No other module ever learns
these blocks existed; by the time parse_cut returns, every case's
`mocks` list looks exactly as if the author had typed everything by
hand.
"""

from __future__ import annotations

import re

from mockymock.dsl.model import (
    ExpectDirective,
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
    VerifyDirective,
)

_QUOTED_CATS = "CALL|MQ|SQL|CICS|DLI"
# CALL also appears here: the bare-key form is the dynamic-CALL mock.
# PARAGRAPH/SECTION mock an internal flow target (a PROCEDURE DIVISION
# paragraph or section) rather than an external boundary.
_BARE_CATS = (
    "CALL|OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START|UNLOCK|ACCEPT" "|PARAGRAPH|SECTION"
)

_TESTSUITE_RE = re.compile(r'^TESTSUITE\s+"(?P<name>[^"]*)"$')
_TESTCASE_RE = re.compile(
    r'^TESTCASE\s+"(?P<name>[^"]*)"(?:\s+TAGS\s+(?P<tags>"[^"]*"(?:\s+"[^"]*")*))?$'
)
_TAG_RE = re.compile(r'"([^"]*)"')
_BEFORE_ALL_RE = re.compile(r"^BEFORE-ALL$")
_BEFORE_EACH_RE = re.compile(r"^BEFORE-EACH$")
# END-BEFORE is deliberately lenient, same rationale as END-MOCK below: a
# missed terminator must not silently swallow the rest of the file.
_END_BEFORE_RE = re.compile(r"^END-BEFORE\.?$", re.IGNORECASE)
_MOCK_QUOTED_RE = re.compile(
    rf'^MOCK\s+(?P<cat>{_QUOTED_CATS})\s+"(?P<key>[^"]*)"(?:\s+(?P<rows>ROWS))?$'
)
_MOCK_BARE_RE = re.compile(
    rf"^MOCK\s+(?P<cat>{_BARE_CATS})\s+(?P<key>[A-Za-z0-9][A-Za-z0-9-]*)$"
)
# END-MOCK is deliberately more forgiving than the other keywords: an
# optional trailing period (the natural COBOL habit) and any letter case
# are accepted, because a missed END-MOCK doesn't fail at this line -- it
# silently swallows the rest of the file into the mock body and surfaces
# later as a confusing refusal or compile error. Every other DSL keyword
# stays case-sensitive uppercase (see the "Case rules" section in
# .okf/dsl.md).
_END_MOCK_RE = re.compile(r"^END-MOCK\.?$", re.IGNORECASE)
_MOVE_RE = re.compile(r"^MOVE\s+(?P<value>.+?)\s+TO\s+(?P<target>\S+)$")
_PERFORM_RE = re.compile(
    r"^PERFORM\s+(?P<target>\S+)(?:\s+(?:THRU|THROUGH)\s+(?P<thru>\S+))?$"
)
_EXPECT_RE = re.compile(r"^EXPECT\s+(?P<name>\S+)\s+TO\s+BE\s+(?P<value>.+)$")
_VERIFY_QUOTED_RE = re.compile(
    rf'^VERIFY\s+(?:(?P<cat>{_QUOTED_CATS})\s+)?"(?P<key>[^"]*)"'
    rf"\s+WAS\s+(?:CALLED|PERFORMED)\s+(?P<expectation>.+)$"
)
_VERIFY_BARE_RE = re.compile(
    rf"^VERIFY\s+(?P<cat>{_BARE_CATS})\s+(?P<key>[A-Za-z0-9][A-Za-z0-9-]*)"
    rf"\s+WAS\s+(?:CALLED|PERFORMED)\s+(?P<expectation>.+)$"
)
_COMMENT_RE = re.compile(r"^\*>")
_ROW_RE = re.compile(r"^\((?P<pairs>.+)\)$")
_ROW_PAIR_RE = re.compile(r"^(?P<field>[A-Za-z][A-Za-z0-9-]*)\s*=\s*(?P<value>.+)$")


class CutParseError(ValueError):
    """Raised when a .cut file doesn't match the grammar."""


def _resolve_category(cat: str | None, bare_key: bool = False) -> MockCategory:
    if cat is None or cat == "MQ":  # bare VERIFY "X" and MOCK MQ are CALL
        return MockCategory.CALL
    if cat == "CALL" and bare_key:  # CALL <identifier> is the dynamic form
        return MockCategory.DYNCALL
    return MockCategory(cat)


def _validate_expectation(expectation: str, line_no: int) -> None:
    """Reject a VERIFY expectation the driver codegen cannot compile.

    Must accept exactly what splicer/driver.py's `_verify_condition`
    accepts (it upper-cases and strips before matching) -- keep the two in
    sync. Validating here turns a late, tracebacking ValueError in codegen
    into a line-numbered CutParseError at parse time."""
    normalized = expectation.strip().upper()
    if normalized in ("ONCE", "NEVER", "AT LEAST ONCE"):
        return
    if re.match(r"^\d+\s+TIMES$", normalized):
        return
    raise CutParseError(
        f"line {line_no}: unrecognized VERIFY expectation {expectation!r} "
        f"(expected ONCE, NEVER, AT LEAST ONCE, or <n> TIMES)"
    )


def _split_top_level(text: str, sep: str) -> list[str]:
    """Split `text` on `sep`, ignoring any occurrence inside a '...' or
    "..." span -- so a ROWS row value like EMP-NAME = "SMITH, JR." isn't
    cut at the comma inside the quoted literal."""
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in text:
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
            current.append(char)
            continue
        if char == sep:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _apply_before_blocks(
    suite: MockTestSuite,
    before_all: list[MockDirective],
    before_each: list[MockDirective],
) -> None:
    """Desugar BEFORE-ALL/BEFORE-EACH into every TESTCASE's own mocks list.
    Precedence when a (category, key) appears in more than one place:
    TESTCASE > BEFORE-EACH > BEFORE-ALL, silently -- see
    docs/2026-07-20-before-blocks-and-file-status-design.md."""
    if not before_all and not before_each:
        return
    for case in suite.test_cases:
        declared = {(m.category, m.key) for m in case.mocks}
        for directive in before_each:
            key = (directive.category, directive.key)
            if key in declared:
                continue
            declared.add(key)
            case.mocks.append(directive)
        for directive in before_all:
            key = (directive.category, directive.key)
            if key in declared:
                continue
            declared.add(key)
            case.mocks.append(directive)


def parse_cut(text: str) -> MockTestSuite:
    suite: MockTestSuite | None = None
    case: MockTestCase | None = None
    in_mock: MockDirective | None = None
    in_mock_line = 0
    # (category, key) -> declaring line, reset per TESTCASE/BEFORE-EACH/
    # BEFORE-ALL: a duplicate MOCK would otherwise parse fine and surface
    # much later as an AMBIGUOUS_MOCK refusal with no line numbers and
    # misleading advice.
    mock_lines: dict[tuple[MockCategory, str], int] = {}
    # The list new MOCK directives are appended to: case.mocks inside a
    # TESTCASE, before_each/before_all inside those blocks, None
    # otherwise (MOCK outside any of them is a parse error).
    mock_target: list[MockDirective] | None = None
    before_all: list[MockDirective] = []
    before_each: list[MockDirective] = []
    before_all_seen = False
    before_each_seen = False
    seen_testcase = False
    in_before: str | None = None  # None, "BEFORE-ALL", or "BEFORE-EACH"
    before_open_line = 0

    def _current_scope_label() -> str:
        if case is not None:
            return f"TESTCASE {case.name!r}"
        assert in_before is not None
        return in_before

    def _open_mock(directive: MockDirective, line_no: int) -> MockDirective:
        assert mock_target is not None
        mock_id = (directive.category, directive.key)
        if mock_id in mock_lines:
            raise CutParseError(
                f"line {line_no}: duplicate MOCK {directive.describe()} in "
                f"{_current_scope_label()} (first declared at line "
                f"{mock_lines[mock_id]})"
            )
        mock_lines[mock_id] = line_no
        mock_target.append(directive)
        return directive

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        if in_mock is not None:
            if _END_MOCK_RE.match(line):
                if in_mock.rows is not None and not in_mock.rows:
                    raise CutParseError(
                        f"line {line_no}: MOCK {in_mock.describe()} ROWS "
                        f"block has no rows -- give at least one row or "
                        f"drop ROWS entirely"
                    )
                in_mock = None
            elif in_mock.rows is not None:
                row_match = _ROW_RE.match(line)
                if row_match is None:
                    raise CutParseError(
                        f"line {line_no}: malformed ROWS row {line!r} -- "
                        f"expected ( FIELD = value, FIELD = value, ... )"
                    )
                row: list[tuple[str, str]] = []
                for raw_pair in _split_top_level(row_match.group("pairs"), ","):
                    pair_match = _ROW_PAIR_RE.match(raw_pair.strip())
                    if pair_match is None:
                        raise CutParseError(
                            f"line {line_no}: malformed ROWS field "
                            f"assignment {raw_pair.strip()!r} -- expected "
                            f"FIELD = value"
                        )
                    row.append(
                        (pair_match.group("field"), pair_match.group("value").strip())
                    )
                in_mock.rows.append(row)
            else:
                in_mock.body_lines.append(line)
            continue

        if _COMMENT_RE.match(line):
            continue

        if (m := _TESTSUITE_RE.match(line)) is not None:
            if suite is not None:
                raise CutParseError(
                    f"line {line_no}: second TESTSUITE line (suite "
                    f"{suite.name!r} is already open); a .cut file holds "
                    f"exactly one TESTSUITE -- concatenated files would "
                    f"silently run only the last suite"
                )
            suite = MockTestSuite(name=m.group("name"), line=line_no)
        elif (m := _TESTCASE_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: TESTCASE before TESTSUITE")
            if in_before is not None:
                raise CutParseError(
                    f"line {line_no}: TESTCASE inside {in_before} -- "
                    f"missing END-BEFORE"
                )
            tags = _TAG_RE.findall(m.group("tags") or "")
            for tag in tags:
                if not tag.strip():
                    raise CutParseError(
                        f"line {line_no}: empty tag in TAGS list -- every "
                        f"tag must be a non-blank quoted word"
                    )
            case = MockTestCase(name=m.group("name"), line=line_no, tags=tags)
            suite.test_cases.append(case)
            seen_testcase = True
            mock_target = case.mocks
            mock_lines = {}
        elif (m := _BEFORE_ALL_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: BEFORE-ALL before TESTSUITE")
            if seen_testcase:
                raise CutParseError(
                    f"line {line_no}: BEFORE-ALL must appear before the "
                    f"first TESTCASE"
                )
            if before_all_seen:
                raise CutParseError(
                    f"line {line_no}: a second BEFORE-ALL block -- a "
                    f"TESTSUITE holds at most one"
                )
            before_all_seen = True
            in_before = "BEFORE-ALL"
            before_open_line = line_no
            mock_target = before_all
            mock_lines = {}
        elif (m := _BEFORE_EACH_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: BEFORE-EACH before TESTSUITE")
            if seen_testcase:
                raise CutParseError(
                    f"line {line_no}: BEFORE-EACH must appear before the "
                    f"first TESTCASE"
                )
            if before_each_seen:
                raise CutParseError(
                    f"line {line_no}: a second BEFORE-EACH block -- a "
                    f"TESTSUITE holds at most one"
                )
            before_each_seen = True
            in_before = "BEFORE-EACH"
            before_open_line = line_no
            mock_target = before_each
            mock_lines = {}
        elif _END_BEFORE_RE.match(line):
            if in_before is None:
                raise CutParseError(
                    f"line {line_no}: END-BEFORE without an open "
                    f"BEFORE-EACH/BEFORE-ALL"
                )
            in_before = None
            mock_target = None
            mock_lines = {}
        elif (m := _MOCK_QUOTED_RE.match(line)) is not None:
            if mock_target is None:
                raise CutParseError(
                    f"line {line_no}: MOCK outside TESTCASE/BEFORE-EACH/"
                    f"BEFORE-ALL"
                )
            if not m.group("key"):
                raise CutParseError(
                    f'line {line_no}: empty MOCK {m.group("cat")} key -- '
                    f"the quoted key must name what to mock"
                )
            category = _resolve_category(m.group("cat"))
            if m.group("rows") and category is not MockCategory.SQL:
                raise CutParseError(
                    f"line {line_no}: ROWS is only supported for MOCK SQL, "
                    f'not MOCK {m.group("cat")}'
                )
            in_mock = _open_mock(
                MockDirective(
                    category=category,
                    key=m.group("key"),
                    rows=[] if m.group("rows") else None,
                ),
                line_no,
            )
            in_mock_line = line_no
        elif (m := _MOCK_BARE_RE.match(line)) is not None:
            if mock_target is None:
                raise CutParseError(
                    f"line {line_no}: MOCK outside TESTCASE/BEFORE-EACH/"
                    f"BEFORE-ALL"
                )
            in_mock = _open_mock(
                MockDirective(
                    category=_resolve_category(m.group("cat"), bare_key=True),
                    key=m.group("key").upper(),
                ),
                line_no,
            )
            in_mock_line = line_no
        elif line.startswith("MOCK"):
            raise CutParseError(
                f"line {line_no}: malformed MOCK directive: {line!r} "
                f"(MQ/SQL/CICS/DLI take a quoted key; "
                f"{_BARE_CATS.replace('|', '/')} take a bare COBOL name; "
                f'CALL takes both -- quoted "X" for a static CALL, bare '
                f"WS-NAME for a dynamic CALL through that identifier)"
            )
        elif (m := _MOVE_RE.match(line)) is not None:
            if case is None:
                if in_before is not None:
                    raise CutParseError(
                        f"line {line_no}: MOVE not allowed inside "
                        f"{in_before} (only MOCK directives are)"
                    )
                raise CutParseError(f"line {line_no}: MOVE outside TESTCASE")
            case.setup_moves.append((m.group("value"), m.group("target")))
        elif (m := _PERFORM_RE.match(line)) is not None:
            if case is None:
                if in_before is not None:
                    raise CutParseError(
                        f"line {line_no}: PERFORM not allowed inside "
                        f"{in_before} (only MOCK directives are)"
                    )
                raise CutParseError(f"line {line_no}: PERFORM outside TESTCASE")
            if case.perform_target:
                raise CutParseError(
                    f"line {line_no}: TESTCASE {case.name!r} already has a "
                    f"PERFORM target {case.perform_target!r}; one PERFORM "
                    f"per test case"
                )
            case.perform_target = m.group("target")
            case.perform_thru = m.group("thru")
        elif (m := _EXPECT_RE.match(line)) is not None:
            if case is None:
                if in_before is not None:
                    raise CutParseError(
                        f"line {line_no}: EXPECT not allowed inside "
                        f"{in_before} (only MOCK directives are)"
                    )
                raise CutParseError(f"line {line_no}: EXPECT outside TESTCASE")
            case.expectations.append(
                ExpectDirective(
                    data_name=m.group("name"),
                    expected_value=m.group("value"),
                    line=line_no,
                )
            )
        elif (m := _VERIFY_QUOTED_RE.match(line)) is not None:
            if case is None:
                if in_before is not None:
                    raise CutParseError(
                        f"line {line_no}: VERIFY not allowed inside "
                        f"{in_before} (only MOCK directives are)"
                    )
                raise CutParseError(f"line {line_no}: VERIFY outside TESTCASE")
            _validate_expectation(m.group("expectation"), line_no)
            case.verifications.append(
                VerifyDirective(
                    category=_resolve_category(m.group("cat")),
                    key=m.group("key"),
                    expectation=m.group("expectation"),
                    line=line_no,
                )
            )
        elif (m := _VERIFY_BARE_RE.match(line)) is not None:
            if case is None:
                if in_before is not None:
                    raise CutParseError(
                        f"line {line_no}: VERIFY not allowed inside "
                        f"{in_before} (only MOCK directives are)"
                    )
                raise CutParseError(f"line {line_no}: VERIFY outside TESTCASE")
            _validate_expectation(m.group("expectation"), line_no)
            case.verifications.append(
                VerifyDirective(
                    category=_resolve_category(m.group("cat"), bare_key=True),
                    key=m.group("key").upper(),
                    expectation=m.group("expectation"),
                    line=line_no,
                )
            )
        else:
            raise CutParseError(f"line {line_no}: unrecognized statement: {line!r}")

    if in_mock is not None:
        raise CutParseError(
            f"line {in_mock_line}: unterminated MOCK {in_mock.describe()}: "
            f"reached end of file with no END-MOCK"
        )

    if in_before is not None:
        raise CutParseError(
            f"line {before_open_line}: unterminated {in_before}: reached "
            f"end of file with no END-BEFORE"
        )

    if suite is None:
        raise CutParseError("no TESTSUITE found")
    _apply_before_blocks(suite, before_all, before_each)
    return suite
