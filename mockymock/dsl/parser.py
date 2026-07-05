"""Parses .cut files into MockTestSuite objects.

v2 grammar: MOCK takes a category — quoted-key categories
(CALL/MQ/SQL/CICS/DLI) vs bare-COBOL-word categories (the eight file-op
verbs and ACCEPT). `MOCK MQ "X"` is sugar for `MOCK CALL "X"`. VERIFY
mirrors the same key syntax; a bare `VERIFY "X"` stays CALL for v1
back-compat, and CALLED/PERFORMED are interchangeable. Lines starting with
`*>` outside MOCK bodies are comments; inside a body they pass through
(they're valid free-form COBOL).
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
_BARE_CATS = "OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START|UNLOCK|ACCEPT"

_TESTSUITE_RE = re.compile(r'^TESTSUITE\s+"(?P<name>[^"]*)"$')
_TESTCASE_RE = re.compile(r'^TESTCASE\s+"(?P<name>[^"]*)"$')
_MOCK_QUOTED_RE = re.compile(
    rf'^MOCK\s+(?P<cat>{_QUOTED_CATS})\s+"(?P<key>[^"]*)"$'
)
_MOCK_BARE_RE = re.compile(
    rf"^MOCK\s+(?P<cat>{_BARE_CATS})\s+(?P<key>[A-Za-z0-9][A-Za-z0-9-]*)$"
)
_END_MOCK_RE = re.compile(r"^END-MOCK$")
_MOVE_RE = re.compile(r"^MOVE\s+(?P<value>.+?)\s+TO\s+(?P<target>\S+)$")
_PERFORM_RE = re.compile(r"^PERFORM\s+(?P<target>\S+)$")
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


class CutParseError(ValueError):
    """Raised when a .cut file doesn't match the grammar."""


def _resolve_category(cat: str | None) -> MockCategory:
    if cat is None or cat == "MQ":  # bare VERIFY "X" and MOCK MQ are CALL
        return MockCategory.CALL
    return MockCategory(cat)


def parse_cut(text: str) -> MockTestSuite:
    suite: MockTestSuite | None = None
    case: MockTestCase | None = None
    in_mock: MockDirective | None = None

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        if in_mock is not None:
            if _END_MOCK_RE.match(line):
                in_mock = None
            else:
                in_mock.body_lines.append(line)
            continue

        if _COMMENT_RE.match(line):
            continue

        if (m := _TESTSUITE_RE.match(line)) is not None:
            suite = MockTestSuite(name=m.group("name"))
        elif (m := _TESTCASE_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: TESTCASE before TESTSUITE")
            case = MockTestCase(name=m.group("name"))
            suite.test_cases.append(case)
        elif (m := _MOCK_QUOTED_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: MOCK outside TESTCASE")
            in_mock = MockDirective(
                category=_resolve_category(m.group("cat")), key=m.group("key")
            )
            case.mocks.append(in_mock)
        elif (m := _MOCK_BARE_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: MOCK outside TESTCASE")
            in_mock = MockDirective(
                category=_resolve_category(m.group("cat")),
                key=m.group("key").upper(),
            )
            case.mocks.append(in_mock)
        elif line.startswith("MOCK"):
            raise CutParseError(
                f"line {line_no}: malformed MOCK directive: {line!r} "
                f"(CALL/MQ/SQL/CICS/DLI take a quoted key; "
                f"{_BARE_CATS.replace('|', '/')} take a bare COBOL name)"
            )
        elif (m := _MOVE_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: MOVE outside TESTCASE")
            case.setup_moves.append((m.group("value"), m.group("target")))
        elif (m := _PERFORM_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: PERFORM outside TESTCASE")
            case.perform_target = m.group("target")
        elif (m := _EXPECT_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: EXPECT outside TESTCASE")
            case.expectations.append(
                ExpectDirective(data_name=m.group("name"), expected_value=m.group("value"))
            )
        elif (m := _VERIFY_QUOTED_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: VERIFY outside TESTCASE")
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
            case.verifications.append(
                VerifyDirective(
                    category=_resolve_category(m.group("cat")),
                    key=m.group("key").upper(),
                    expectation=m.group("expectation"),
                )
            )
        else:
            raise CutParseError(f"line {line_no}: unrecognized statement: {line!r}")

    if suite is None:
        raise CutParseError("no TESTSUITE found")
    return suite
