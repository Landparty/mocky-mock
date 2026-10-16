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
    SORT = "SORT"
    MERGE = "MERGE"
    RELEASE = "RELEASE"
    RETURN = "RETURN"
    SQL = "SQL"
    CICS = "CICS"
    DLI = "DLI"
    ACCEPT = "ACCEPT"
    INITIATE = "INITIATE"
    GENERATE = "GENERATE"
    TERMINATE = "TERMINATE"
    PARAGRAPH = "PARAGRAPH"
    SECTION = "SECTION"

    @property
    def keyword(self) -> str:
        """The .cut-level keyword: what a user actually writes after MOCK/
        VERIFY. DYNCALL is spelled CALL (the bare-key form); everything
        else is its own name."""
        return "CALL" if self is MockCategory.DYNCALL else self.value


# File-op categories key on a bare COBOL word (file or record name);
# CALL/SQL/CICS/DLI key on a quoted literal. SORT/MERGE join this set too:
# a plain-file-form SORT/MERGE (USING ... GIVING ..., no INPUT/OUTPUT
# PROCEDURE) keys on its own SD file name, the same bare-word shape as
# READ/DELETE/START/UNLOCK -- see mock_surface.py's classification.
# RELEASE/RETURN -- the record-supply verbs used inside a SORT/MERGE's
# INPUT/OUTPUT PROCEDURE -- join it too: RELEASE keys on the record name
# (WRITE-shaped), RETURN keys on the SD file name (READ-shaped, including
# an AT END clause -- see FILE_OP_CATEGORIES' ROWS/TERMINAL note below).
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
        MockCategory.SORT,
        MockCategory.MERGE,
        MockCategory.RELEASE,
        MockCategory.RETURN,
    }
)

EXEC_CATEGORIES = frozenset({MockCategory.SQL, MockCategory.CICS, MockCategory.DLI})

# Report Writer verbs (2026-09-02). INITIATE/GENERATE/TERMINATE write
# through a report file's FD via the RD in the REPORT SECTION -- an output
# dependency exactly like WRITE, keyed on the report name (INITIATE/
# TERMINATE) or the report/group name (GENERATE) the statement names, as
# a bare COBOL word. Splicing the statement out is the whole mock: the
# RD/FD stay declared (GnuCOBOL compiles them), the file is never touched.
# An INITIATE/TERMINATE naming several reports is one site with several
# keys, like a multi-file OPEN/CLOSE. Deliberately NOT in
# FILE_OP_CATEGORIES/FILE_STATUS_CATEGORIES: no ROWS/TERMINAL/FILE-STATUS
# sugar applies (there is no status field on an RD), so a MOCK body is
# free-form COBOL only.
REPORT_WRITER_CATEGORIES = frozenset(
    {MockCategory.INITIATE, MockCategory.GENERATE, MockCategory.TERMINATE}
)

# Flow-target categories mock a PROCEDURE DIVISION paragraph/section (a
# bare COBOL name), not a boundary statement -- they never appear as
# BoundarySite categories; the splicer handles them via header dispatch
# (see splicer/flow_mocks in docs/2026-07-20-paragraph-section-mocks-design.md).
FLOW_CATEGORIES = frozenset({MockCategory.PARAGRAPH, MockCategory.SECTION})

# FILE-STATUS IS sugar and the implicit default-success MOVE apply only
# to these eight file-op categories. WRITE/REWRITE key on the *record*
# name, not the file name: `mock_surface.analyze_file_status_fields`
# maps every FD record name to its file's status field too, so a mocked
# WRITE/REWRITE sets "00" like the real statement does (issue #221 --
# without it the status kept its reset value or the previous mock's
# code, and the program's own success check took its error branch).
# SORT/MERGE are excluded: a SORT/MERGE's SD has no FILE STATUS clause
# of its own (the status, if any, belongs to the USING/GIVING FDs), so
# there is no single field to default/override.
# RELEASE/RETURN are excluded too, for the same reason -- a MOCK RETURN
# ... ROWS block's rows-exhausted branch therefore always needs its own
# TERMINAL group (there is no implicit-default fallback to lean on); see
# refusal.py's UNRESOLVED_FILE_STATUS_TARGET check and injector.py's ROWS
# dispatch, both widened from READ-only to (READ, RETURN).
FILE_STATUS_CATEGORIES = frozenset(
    {
        MockCategory.OPEN,
        MockCategory.CLOSE,
        MockCategory.READ,
        MockCategory.DELETE,
        MockCategory.START,
        MockCategory.UNLOCK,
        MockCategory.WRITE,
        MockCategory.REWRITE,
    }
)

# CAPTURE ARG <n> INTO <target> is valid only inside a mock body whose
# category can carry a COBOL USING clause -- CALL/DYNCALL. MQ is sugar
# for CALL at parse time (see MockCategory docstring), so it never
# appears here as its own category.
CAPTURE_CATEGORIES = frozenset({MockCategory.CALL, MockCategory.DYNCALL})

# Per-invocation sequencing (`MOCK CALL "X" ROWS ( ... ) TERMINAL ( ... )`,
# 2026-10-05): row N answers the Nth call of the mocked key within one
# test case, counted by the key's own tally across every site it matches.
# These categories have no implicit end-of-data value (no SQLCODE, no FILE
# STATUS), so their TERMINAL group is mandatory -- without it the last
# row's response would repeat forever and a retrieve-and-loop program
# would spin until `run --timeout`. MQ is CALL at parse time. CICS
# (2026-10-13, #169) is the STARTBR/READNEXT browse loop's case: EXEC CICS
# reports its end through RESP, which only the TERMINAL group can set.
# ACCEPT (#263) is the SYSIN control-card loop's case: `PERFORM ... UNTIL
# WS-IN = "END"` around `ACCEPT WS-IN` needs card 1, card 2, then the
# sentinel, and the sentinel is what its TERMINAL group sets.
SEQUENCED_CALL_CATEGORIES = frozenset(
    {
        MockCategory.CALL,
        MockCategory.DYNCALL,
        MockCategory.DLI,
        MockCategory.CICS,
        MockCategory.ACCEPT,
    }
)

# Every category ROWS is valid on. SQL ends with SQLCODE 100 (no TERMINAL),
# READ/RETURN end with a status/TERMINAL group, the sequenced-call
# categories end with their mandatory TERMINAL group.
ROWS_CATEGORIES = frozenset(
    {MockCategory.SQL, MockCategory.READ, MockCategory.RETURN}
    | SEQUENCED_CALL_CATEGORIES
)

# Categories whose ROWS block takes a TERMINAL ( ... ) group.
TERMINAL_CATEGORIES = frozenset(
    {MockCategory.READ, MockCategory.RETURN} | SEQUENCED_CALL_CATEGORIES
)


@dataclass
class MockDirective:
    category: MockCategory
    key: str
    body_lines: list[str] = field(default_factory=list)
    rows: list[list[tuple[str, str]]] | None = None
    """Structured rows for a `MOCK <cat> <key> ROWS (...) (...) END-MOCK`
    directive (SQL, READ, RETURN, and the SEQUENCED_CALL_CATEGORIES
    CALL/DYNCALL/DLI/CICS). `None` for an ordinary mock (its body lives in
    `body_lines` instead); populated only for ROWS_CATEGORIES, mutually
    exclusive with `body_lines`."""
    file_status: str | None = None
    """Resolved two-character status code from `FILE-STATUS IS
    <mnemonic-or-code>` inside this mock's body -- only ever set for
    FILE_STATUS_CATEGORIES. `None` when the body didn't use the sugar
    (the file may still get an implicit default-success MOVE at splice
    time if it declares a FILE STATUS field -- see
    injector.build_site_dispatch)."""
    terminal_row: list[tuple[str, str]] | None = None
    """Field assignments for the WHEN OTHER (rows-exhausted) branch of a
    READ/RETURN/CALL/DYNCALL/DLI/CICS `... ROWS` block, from its
    `TERMINAL ( F = v, ... )` line (optional for READ, mandatory for the
    SEQUENCED_CALL_CATEGORIES, refused-without for RETURN). Always `None`
    for SQL rows (SQLCODE 100 is fixed) and for non-ROWS mocks."""
    captures: list[tuple[int, str]] = field(default_factory=list)
    """CAPTURE ARG <n> INTO <target> lines from this mock's body: (n, target)
    pairs, n a 1-based USING-parameter position, in declaration order.
    Only ever populated for CAPTURE_CATEGORIES (CALL/DYNCALL) directives;
    empty for every other category. Resolved against the real call site's
    CallStatement.using_parameters at splice time -- see
    injector.build_site_dispatch."""
    capture_lines: list[int] = field(default_factory=list)
    """1-based .cut line of each `captures` entry, same index alignment
    (empty when built outside the parser)."""

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
            or self.category in REPORT_WRITER_CATEGORIES
            or self.category
            in (
                MockCategory.ACCEPT,
                MockCategory.DYNCALL,
            )
        ):
            return f"{self.category.keyword} {self.key}"
        return f'{self.category.keyword} "{self.key}"'


#: Every comparison operator an EXPECT directive can carry, in the
#: canonical COBOL-relation spelling the parser normalizes the English
#: phrase down to ("TO BE GREATER THAN OR EQUAL TO" -> ">=", "NOT TO BE"
#: -> "NOT ="). splicer/driver.py compiles each one's *negation* into the
#: generated IF (the IF guards the failure branch) -- keep this set in
#: sync with driver.py's _EXPECT_FAIL_CONDITIONS.
EXPECT_OPERATORS = frozenset(
    {"=", "NOT =", ">", "NOT >", "<", "NOT <", ">=", "NOT >=", "<=", "NOT <="}
)


@dataclass
class ExpectDirective:
    data_name: str
    expected_value: str
    line: int = 0
    """1-based .cut line of the EXPECT statement (0 when built outside the
    parser, e.g. hand-assembled in tests)."""
    operator: str = "="
    """The asserted relation between `data_name` and `expected_value`, as a
    canonical COBOL relation operator -- one of EXPECT_OPERATORS. `"="` is
    the plain `EXPECT ... TO BE ...` form (and the default, so every
    hand-built directive and pre-operator caller keeps its old meaning);
    the parser sets the others from `NOT TO BE` / `TO BE GREATER THAN` /
    `TO BE LESS THAN [OR EQUAL TO]` phrases."""


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
    setup_move_lines: list[int] = field(default_factory=list)
    """1-based .cut line of each `setup_moves` entry, same index alignment
    (empty when built outside the parser)."""
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

    @property
    def assertion_count(self) -> int:
        """EXPECT + VERIFY directives. Zero means the case passes whenever
        its PERFORM runs without crashing -- lint warns (NO_ASSERTION) and
        the run reports flag it as risky."""
        return len(self.expectations) + len(self.verifications)


@dataclass
class HookStep:
    """One statement of a BEFORE-ALL/BEFORE-EACH/AFTER-EACH/AFTER-ALL hook,
    in declaration order: `MOVE <value> TO <target>` or `PERFORM <target>
    [THRU <thru>]`. See docs/2026-10-10-suite-hooks-design.md."""

    kind: str  # "MOVE" or "PERFORM"
    target: str
    value: str = ""  # MOVE only
    thru: str | None = None  # PERFORM only
    line: int = 0
    """1-based .cut line (0 when built outside the parser)."""


HOOK_NAMES = ("BEFORE-ALL", "BEFORE-EACH", "AFTER-EACH", "AFTER-ALL")

# UT-CURRENT-CASE while BEFORE-ALL/AFTER-ALL steps run: never a real case id
# (those are zero-padded digits), so the mock dispatch can give the suite
# phase its own WHEN branch holding BEFORE-ALL's mocks.
SUITE_PHASE_ID = "SUITE"


@dataclass
class HookCheck:
    """One hook PERFORM step as the static checks see it: a synthetic
    MockTestCase whose perform target is the step's and whose mocks are
    the ones in force while the step runs -- the test case's own (EACH
    hooks, one HookCheck per test case) or BEFORE-ALL's (ALL hooks)."""

    hook: str  # one of HOOK_NAMES
    step: HookStep
    case: MockTestCase
    for_case: MockTestCase | None  # the real test case (EACH hooks), else None


@dataclass
class MockTestSuite:
    name: str
    test_cases: list[MockTestCase] = field(default_factory=list)
    line: int = 0
    """1-based .cut line of the TESTSUITE header (0 when built outside the
    parser)."""
    program_path: str | None = None
    """The optional `PROGRAM "<path>"` line: the program under test, as
    written (relative paths resolve against the .cut file's folder; see
    cli/discovery.py). None when the suite names no program and pairing
    falls back to file-name conventions."""
    program_line: int = 0
    """1-based .cut line of the PROGRAM line (0 when absent)."""
    before_all_steps: list[HookStep] = field(default_factory=list)
    """Run once, before the first test case; every test case then starts
    from the WORKING-STORAGE state they leave behind (splicer.snapshot)."""
    before_each_steps: list[HookStep] = field(default_factory=list)
    """Run at the start of every test case, before its own MOVEs."""
    after_each_steps: list[HookStep] = field(default_factory=list)
    """Run at the end of every test case, after its EXPECTs/VERIFYs."""
    after_all_steps: list[HookStep] = field(default_factory=list)
    """Run once, after the last test case."""
    before_each_mocks: list[MockDirective] = field(default_factory=list)
    """BEFORE-EACH's MOCK blocks, already desugared into every test case;
    kept so the static checks can tell a shared mock from a case's own."""
    before_all_mocks: list[MockDirective] = field(default_factory=list)
    """BEFORE-ALL's MOCK blocks. Besides being desugared into every test
    case (parser._apply_before_blocks), they are the mocks in force while
    the BEFORE-ALL and AFTER-ALL steps run (dispatch id SUITE_PHASE_ID)."""

    @property
    def has_suite_phase(self) -> bool:
        """True when BEFORE-ALL or AFTER-ALL has steps to run outside any
        test case."""
        return bool(self.before_all_steps or self.after_all_steps)

    def hook_checks(self) -> list[HookCheck]:
        """Every hook PERFORM step as a synthetic test case, for the static
        gates (reachability, unmocked boundaries, terminators, flow mocks)
        -- a hook PERFORM reaches program code exactly like a TESTCASE's
        own PERFORM does, so it is refused exactly like one."""
        checks: list[HookCheck] = []

        def performs(steps: list[HookStep]) -> list[HookStep]:
            return [s for s in steps if s.kind == "PERFORM"]

        for hook, steps in (
            ("BEFORE-ALL", self.before_all_steps),
            ("AFTER-ALL", self.after_all_steps),
        ):
            for step in performs(steps):
                synthetic = MockTestCase(
                    name=f"{hook} PERFORM {step.target}",
                    mocks=list(self.before_all_mocks),
                    perform_target=step.target,
                    perform_thru=step.thru,
                    line=step.line,
                )
                checks.append(HookCheck(hook, step, synthetic, None))
        for hook, steps in (
            ("BEFORE-EACH", self.before_each_steps),
            ("AFTER-EACH", self.after_each_steps),
        ):
            for step in performs(steps):
                for case in self.test_cases:
                    synthetic = MockTestCase(
                        name=f"{hook} PERFORM {step.target} (for {case.name!r})",
                        mocks=case.mocks,
                        perform_target=step.target,
                        perform_thru=step.thru,
                        line=step.line,
                    )
                    checks.append(HookCheck(hook, step, synthetic, case))
        return checks

    def analysis_cases(self) -> list[MockTestCase]:
        """Every entry point the program is entered through: the test
        cases plus each hook PERFORM step (see hook_checks). Static
        analyses that ask "what could execute?" iterate this, not
        test_cases."""
        return self.test_cases + [c.case for c in self.hook_checks()]

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
