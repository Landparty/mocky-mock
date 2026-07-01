"""Model classes for the .cut DSL (v1: TESTSUITE/TESTCASE/MOCK CALL/
MOVE/PERFORM/EXPECT/VERIFY)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MockCallDirective:
    program_name: str
    body_lines: list[str] = field(default_factory=list)


@dataclass
class ExpectDirective:
    data_name: str
    expected_value: str


@dataclass
class VerifyDirective:
    program_name: str
    expectation: str  # "ONCE", "AT LEAST ONCE", "NEVER", or "<n> TIMES"


@dataclass
class MockTestCase:
    name: str
    mocks: list[MockCallDirective] = field(default_factory=list)
    setup_moves: list[tuple[str, str]] = field(default_factory=list)  # (value, target)
    perform_target: str = ""
    expectations: list[ExpectDirective] = field(default_factory=list)
    verifications: list[VerifyDirective] = field(default_factory=list)


@dataclass
class MockTestSuite:
    name: str
    test_cases: list[MockTestCase] = field(default_factory=list)
