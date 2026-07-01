"""Parses .cut files into MockTestSuite objects."""

from __future__ import annotations

import re

from mockymock.dsl.model import (
    ExpectDirective,
    MockCallDirective,
    MockTestCase,
    MockTestSuite,
    VerifyDirective,
)

_TESTSUITE_RE = re.compile(r'^TESTSUITE\s+"(?P<name>[^"]*)"$')
_TESTCASE_RE = re.compile(r'^TESTCASE\s+"(?P<name>[^"]*)"$')
_MOCK_CALL_RE = re.compile(r'^MOCK\s+CALL\s+"(?P<name>[^"]*)"$')
_END_MOCK_RE = re.compile(r"^END-MOCK$")
_MOVE_RE = re.compile(r"^MOVE\s+(?P<value>.+?)\s+TO\s+(?P<target>\S+)$")
_PERFORM_RE = re.compile(r"^PERFORM\s+(?P<target>\S+)$")
_EXPECT_RE = re.compile(r"^EXPECT\s+(?P<name>\S+)\s+TO\s+BE\s+(?P<value>.+)$")
_VERIFY_RE = re.compile(
    r'^VERIFY\s+"(?P<name>[^"]*)"\s+WAS\s+CALLED\s+(?P<expectation>.+)$'
)


class CutParseError(ValueError):
    """Raised when a .cut file doesn't match the v1 grammar."""


def parse_cut(text: str) -> MockTestSuite:
    suite: MockTestSuite | None = None
    case: MockTestCase | None = None
    in_mock: MockCallDirective | None = None

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

        if (m := _TESTSUITE_RE.match(line)) is not None:
            suite = MockTestSuite(name=m.group("name"))
        elif (m := _TESTCASE_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: TESTCASE before TESTSUITE")
            case = MockTestCase(name=m.group("name"))
            suite.test_cases.append(case)
        elif (m := _MOCK_CALL_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: MOCK CALL outside TESTCASE")
            in_mock = MockCallDirective(program_name=m.group("name"))
            case.mocks.append(in_mock)
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
        elif (m := _VERIFY_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: VERIFY outside TESTCASE")
            case.verifications.append(
                VerifyDirective(
                    program_name=m.group("name"), expectation=m.group("expectation")
                )
            )
        else:
            raise CutParseError(f"line {line_no}: unrecognized statement: {line!r}")

    if suite is None:
        raise CutParseError("no TESTSUITE found")
    return suite
