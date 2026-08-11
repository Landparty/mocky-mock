"""Model classes for the .cut DSL (v2: TESTSUITE/TESTCASE/MOCK <category>/
MOVE/PERFORM/EXPECT/VERIFY across CALL, file-op, EXEC, and ACCEPT
boundaries)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MockCategory(Enum):
    """Every mockable category. Most are external *boundaries*; PARAGRAPH
    and SECTION are internal *flow targets* -- they mock a whole
    paragraph's/section's body so a test can isolate its entry point from
    collaborator paragraphs (and from any boundary statements inside them).
    `MOCK MQ` is parsed as CALL (MQ is invoked through static CALL
    statements), so MQ is not a category here. DYNCALL is never written in
    .cut files either: `MOCK CALL <bare-word>` parses to it (a dynamic CALL
    keyed by the identifier it calls through), while `MOCK CALL "<literal>"`
    stays CALL. Distinct categories keep the two from colliding in every
    (category, key)-keyed structure (tally registry, declared-VERIFY set)
    and make cross-matching impossible: a quoted directive can never match
    a dynamic site or vice versa."""

    CALL = "CALL"
    DYNCALL = "DYNCALL"
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
    PARAGRAPH = "PARAGRAPH"
    SECTION = "SECTION"

    @property
    def keyword(self) -> str:
        """The .cut-level keyword: what a user actually writes after MOCK/
        VERIFY. DYNCALL is spelled CALL (the bare-key form); everything
        else is its own name."""
        return "CALL" if self is MockCategory.DYNCALL else self.value


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

# Flow-target categories mock a PROCEDURE DIVISION paragraph/section (a
# bare COBOL name), not a boundary statement -- they never appear as
# BoundarySite categories; the splicer handles them via header dispatch
# (see splicer/flow_mocks in docs/2026-07-20-paragraph-section-mocks-design.md).
FLOW_CATEGORIES = frozenset({MockCategory.PARAGRAPH, MockCategory.SECTION})

# FILE-STATUS IS sugar and the implicit default-success MOVE apply only
# to these six file-op categories -- WRITE/REWRITE key on the *record*
# name, not the file name, and resolving record -> owning FD -> file
# name is out of scope (see
# docs/2026-07-20-before-blocks-and-file-status-design.md).
FILE_STATUS_CATEGORIES = frozenset(
    {
        MockCategory.OPEN,
        MockCategory.CLOSE,
        MockCategory.READ,
        MockCategory.DELETE,
        MockCategory.START,
        MockCategory.UNLOCK,
    }
)

# CAPTURE ARG <n> INTO <target> is valid only inside a mock body whose
# category can carry a COBOL USING clause -- CALL/DYNCALL. MQ is sugar
# for CALL at parse time (see MockCategory docstring), so it never
# appears here as its own category.
CAPTURE_CATEGORIES = frozenset({MockCategory.CALL, MockCategory.DYNCALL})


@dataclass
class MockDirective:
    category: MockCategory
    key: str
    body_lines: list[str] = field(default_factory=list)
    rows: list[list[tuple[str, str]]] | None = None
    """Structured rows for `MOCK SQL "..." ROWS (...) (...) END-MOCK` or
    `MOCK READ <file> ROWS (...) (...) END-MOCK`. `None` for an ordinary
    mock (its body lives in `body_lines` instead); populated only for
    SQL- and READ-category ROWS mocks, mutually exclusive with
    `body_lines`."""
    file_status: str | None = None
    """Resolved two-character status code from `FILE-STATUS IS
    <mnemonic-or-code>` inside this mock's body -- only ever set for
    FILE_STATUS_CATEGORIES. `None` when the body didn't use the sugar
    (the file may still get an implicit default-success MOVE at splice
    time if it declares a FILE STATUS field -- see
    injector.build_site_dispatch)."""
    terminal_row: list[tuple[str, str]] | None = None
    """Field assignments for the WHEN OTHER (rows-exhausted) branch of a
    `MOCK READ ... ROWS` block, from its optional `TERMINAL ( F = v, ... )`
    line. Always `None` for SQL rows (SQLCODE 100 is fixed) and for
    non-ROWS mocks."""
    captures: list[tuple[int, str]] = field(default_factory=list)
    """CAPTURE ARG <n> INTO <target> lines from this mock's body: (n, target)
    pairs, n a 1-based USING-parameter position, in declaration order.
    Only ever populated for CAPTURE_CATEGORIES (CALL/DYNCALL) directives;
    empty for every other category. Resolved against the real call site's
    CallStatement.using_parameters at splice time -- see
    injector.build_site_dispatch."""

    @property
    def program_name(self) -> str:
        """v1 compat: the CALL key. Only meaningful for CALL directives."""
        return self.key

    def describe(self) -> str:
        """Human-readable form used in refusal messages and codegen traps,
        mirroring the .cut syntax: `CALL "X"`, `CALL WS-PGM` (dynamic),
        `READ INFILE`, `SQL "SELECT"`."""
        if (
            self.category in FILE_OP_CATEGORIES
            or self.category in FLOW_CATEGORIES
            or self.category
            in (
                MockCategory.ACCEPT,
                MockCategory.DYNCALL,
            )
        ):
            return f"{self.category.keyword} {self.key}"
        return f'{self.category.keyword} "{self.key}"'


@dataclass
class ExpectDirective:
    data_name: str
    expected_value: str
    line: int = 0
    """1-based .cut line of the EXPECT statement (0 when built outside the
    parser, e.g. hand-assembled in tests)."""


@dataclass
class VerifyDirective:
    category: MockCategory
    key: str
    expectation: str  # "ONCE", "AT LEAST ONCE", "NEVER", or "<n> TIMES"
    line: int = 0
    """1-based .cut line of the VERIFY statement (0 when built outside the
    parser)."""

    @property
    def program_name(self) -> str:
        """v1 compat: the CALL key. Only meaningful for CALL verifications."""
        return self.key


@dataclass
class DataProvider:
    """A named, columnar test-data table declared with `PROVIDER <name>` /
    `HEADER <col>, ...` / `ROW <value>, ...`. Resolved and consumed
    entirely within parser.py's `_expand_providers` -- never stored on
    MockTestSuite/MockTestCase, so every downstream consumer (analysis,
    splicer, runtime, report, cli) sees only ordinary, already-expanded
    MockTestCase objects and never learns PROVIDER exists."""

    name: str
    line: int = 0
    """1-based .cut line of the PROVIDER header."""
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    row_lines: list[int] = field(default_factory=list)
    """1-based .cut line of each row in `rows`, same index alignment."""


@dataclass
class MockTestCase:
    name: str
    mocks: list[MockDirective] = field(default_factory=list)
    setup_moves: list[tuple[str, str]] = field(default_factory=list)  # (value, target)
    perform_target: str = ""
    perform_thru: str | None = None  # PERFORM <target> THRU <perform_thru>
    expectations: list[ExpectDirective] = field(default_factory=list)
    verifications: list[VerifyDirective] = field(default_factory=list)
    line: int = 0
    """1-based .cut line of the TESTCASE header (0 when built outside the
    parser)."""
    tags: list[str] = field(default_factory=list)
    """Tags from `TESTCASE "..." TAGS "a" "b"`, in declaration order.
    Selection (`run --tag`) and reporting only -- no runtime semantics."""


@dataclass
class MockTestSuite:
    name: str
    test_cases: list[MockTestCase] = field(default_factory=list)
    line: int = 0
    """1-based .cut line of the TESTSUITE header (0 when built outside the
    parser)."""

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
