"""Parses .cut files into MockTestSuite objects.

v2 grammar: MOCK takes a category — quoted-key categories
(CALL/MQ/SQL/CICS/DLI) vs bare-COBOL-word categories (the eight file-op
verbs and ACCEPT). `MOCK MQ "X"` is sugar for `MOCK CALL "X"`. CALL alone
takes both forms: `MOCK CALL "X"` mocks a static CALL with literal 'X',
while `MOCK CALL WS-PGM` (bare word) mocks a *dynamic* CALL through the
identifier WS-PGM (parsed as MockCategory.DYNCALL; MQ stays quoted-only —
the MQI is invoked through static CALLs by definition). VERIFY mirrors the
same key syntax; a bare `VERIFY "X"` stays CALL for v1 back-compat, and
CALLED/PERFORMED are interchangeable. Lines starting with `*>` outside
MOCK bodies are comments; inside a body they pass through (they're valid
free-form COBOL).
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
_BARE_CATS = "CALL|OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START|UNLOCK|ACCEPT"

_TESTSUITE_RE = re.compile(r'^TESTSUITE\s+"(?P<name>[^"]*)"$')
_TESTCASE_RE = re.compile(r'^TESTCASE\s+"(?P<name>[^"]*)"$')
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


def parse_cut(text: str) -> MockTestSuite:
    suite: MockTestSuite | None = None
    case: MockTestCase | None = None
    in_mock: MockDirective | None = None
    in_mock_line = 0
    # (category, key) -> declaring line, reset per TESTCASE: a duplicate
    # MOCK would otherwise parse fine and surface much later as an
    # AMBIGUOUS_MOCK refusal with no line numbers and misleading advice.
    mock_lines: dict[tuple[MockCategory, str], int] = {}

    def _open_mock(directive: MockDirective, line_no: int) -> MockDirective:
        assert case is not None
        mock_id = (directive.category, directive.key)
        if mock_id in mock_lines:
            raise CutParseError(
                f"line {line_no}: duplicate MOCK {directive.describe()} in "
                f"TESTCASE {case.name!r} (first declared at line "
                f"{mock_lines[mock_id]})"
            )
        mock_lines[mock_id] = line_no
        case.mocks.append(directive)
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
            suite = MockTestSuite(name=m.group("name"))
        elif (m := _TESTCASE_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: TESTCASE before TESTSUITE")
            case = MockTestCase(name=m.group("name"))
            suite.test_cases.append(case)
            mock_lines = {}
        elif (m := _MOCK_QUOTED_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: MOCK outside TESTCASE")
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
            if case is None:
                raise CutParseError(f"line {line_no}: MOCK outside TESTCASE")
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
                raise CutParseError(f"line {line_no}: MOVE outside TESTCASE")
            case.setup_moves.append((m.group("value"), m.group("target")))
        elif (m := _PERFORM_RE.match(line)) is not None:
            if case is None:
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
                raise CutParseError(f"line {line_no}: EXPECT outside TESTCASE")
            case.expectations.append(
                ExpectDirective(
                    data_name=m.group("name"), expected_value=m.group("value")
                )
            )
        elif (m := _VERIFY_QUOTED_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: VERIFY outside TESTCASE")
            _validate_expectation(m.group("expectation"), line_no)
            case.verifications.append(
                VerifyDirective(
                    category=_resolve_category(m.group("cat")),
                    key=m.group("key"),
                    expectation=m.group("expectation"),
                )
            )
        elif (m := _VERIFY_BARE_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: VERIFY outside TESTCASE")
            _validate_expectation(m.group("expectation"), line_no)
            case.verifications.append(
                VerifyDirective(
                    category=_resolve_category(m.group("cat"), bare_key=True),
                    key=m.group("key").upper(),
                    expectation=m.group("expectation"),
                )
            )
        else:
            raise CutParseError(f"line {line_no}: unrecognized statement: {line!r}")

    if in_mock is not None:
        raise CutParseError(
            f"line {in_mock_line}: unterminated MOCK {in_mock.describe()}: "
            f"reached end of file with no END-MOCK"
        )

    if suite is None:
        raise CutParseError("no TESTSUITE found")
    return suite
