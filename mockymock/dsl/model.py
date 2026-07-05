"""Model classes for the .cut DSL (v2: TESTSUITE/TESTCASE/MOCK <category>/
MOVE/PERFORM/EXPECT/VERIFY across CALL, file-op, EXEC, and ACCEPT
boundaries)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MockCategory(Enum):
    """Every mockable boundary category. `MOCK MQ` is parsed as CALL (MQ is
    invoked through static CALL statements), so MQ is not a category here."""

    CALL = "CALL"
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    READ = "READ"
    WRITE = "WRITE"
    REWRITE = "REWRITE"
    DELETE = "DELETE"
    START = "START"
    UNLOCK = "UNLOCK"
    SQL = "SQL"
    CICS = "CICS"
    DLI = "DLI"
    ACCEPT = "ACCEPT"


# File-op categories key on a bare COBOL word (file or record name);
# CALL/SQL/CICS/DLI key on a quoted literal.
FILE_OP_CATEGORIES = frozenset(
    {
        MockCategory.OPEN,
        MockCategory.CLOSE,
        MockCategory.READ,
        MockCategory.WRITE,
        MockCategory.REWRITE,
        MockCategory.DELETE,
        MockCategory.START,
        MockCategory.UNLOCK,
    }
)

EXEC_CATEGORIES = frozenset({MockCategory.SQL, MockCategory.CICS, MockCategory.DLI})


@dataclass
class MockDirective:
    category: MockCategory
    key: str
    body_lines: list[str] = field(default_factory=list)

    @property
    def program_name(self) -> str:
        """v1 compat: the CALL key. Only meaningful for CALL directives."""
        return self.key

    def describe(self) -> str:
        """Human-readable form used in refusal messages and codegen traps,
        mirroring the .cut syntax: `CALL "X"`, `READ INFILE`, `SQL "SELECT"`."""
        if self.category in FILE_OP_CATEGORIES or self.category is MockCategory.ACCEPT:
            return f"{self.category.value} {self.key}"
        return f'{self.category.value} "{self.key}"'


@dataclass
class ExpectDirective:
    data_name: str
    expected_value: str


@dataclass
class VerifyDirective:
    category: MockCategory
    key: str
    expectation: str  # "ONCE", "AT LEAST ONCE", "NEVER", or "<n> TIMES"

    @property
    def program_name(self) -> str:
        """v1 compat: the CALL key. Only meaningful for CALL verifications."""
        return self.key


@dataclass
class MockTestCase:
    name: str
    mocks: list[MockDirective] = field(default_factory=list)
    setup_moves: list[tuple[str, str]] = field(default_factory=list)  # (value, target)
    perform_target: str = ""
    expectations: list[ExpectDirective] = field(default_factory=list)
    verifications: list[VerifyDirective] = field(default_factory=list)


@dataclass
class MockTestSuite:
    name: str
    test_cases: list[MockTestCase] = field(default_factory=list)

    def all_mock_keys(self) -> list[tuple[MockCategory, str]]:
        """Every distinct (category, key) mocked anywhere in the suite, in
        first-appearance order — the unit the tally registry, driver
        bookkeeping, and splice loop all iterate over."""
        seen: list[tuple[MockCategory, str]] = []
        for case in self.test_cases:
            for mock in case.mocks:
                pair = (mock.category, mock.key)
                if pair not in seen:
                    seen.append(pair)
        return seen
