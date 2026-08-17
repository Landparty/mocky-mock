"""Composes cobolparser analyzers into a single mock-surface report.

v2 mocks static CALL sites (including MQ API calls), dynamic CALL sites
(keyed by the identifier they call through -- `CALL WS-PGM-NAME` is
mockable as `MOCK CALL WS-PGM-NAME`; the splicer replaces the whole
statement, so the runtime target never needs resolving), the eight file-op
verbs (OPEN/CLOSE/READ/WRITE/REWRITE/DELETE/START/UNLOCK), a plain-file-form
SORT/MERGE (`SORT ... USING ... GIVING ...`, no INPUT/OUTPUT PROCEDURE --
keyed by its own SD file name, same bare-word shape as READ/DELETE/START/
UNLOCK), RELEASE/RETURN (the record-supply verbs used inside a SORT's
INPUT/OUTPUT PROCEDURE -- RELEASE is WRITE-shaped, RETURN is READ-shaped
including its AT END clause), EXEC SQL/CICS/DLI, and console ACCEPT. Each
mockable statement is recorded as a `BoundarySite` carrying its AST
statement reference so the splicer can compute replacement spans without
re-scanning paragraphs. A SORT/MERGE mixing a USING/GIVING file with an
INPUT/OUTPUT PROCEDURE on the other side, CANCEL, and -- fail closed -- a
dynamic CALL whose identifier cobolparser did not capture are *detected*
(category None) for the refusal gate but never spliced (CANCEL counts as
covered when the test case mocks the CALL for the same program name; a
SORT using INPUT PROCEDURE *and* OUTPUT PROCEDURE with no USING/GIVING at
all touches no physical file, so it is left real/unspliced instead of
detected as unmockable -- see refusal.py and `_is_pure_procedure_sort`
below).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
)
from cobolparser.models.sql_statements import ExecSQLStatement
from cobolparser.models.statements.call import CallStatement
from cobolparser.models.statements.control import (
    EvaluateStatement,
    SearchStatement,
    StopStatement,
)
from cobolparser.models.statements.io import (
    IOAcceptStatement,
    IOCloseStatement,
    IODeleteStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOStartStatement,
    IOUnlockStatement,
    IOWriteStatement,
)
from cobolparser.models.statements.misc import (
    CancelStatement,
    GobackStatement,
    MergeStatement,
    ReleaseStatement,
    ReturnStatement,
    SelectStatement,
    SortStatement,
)
from cobolparser.parsers.statements.ibm_exec_statements import (
    ExecCicsStatement,
    ExecImsStatement,
)

from mockymock.dsl.model import MockCategory


class CallKind(Enum):
    STATIC = "static"
    DYNAMIC = "dynamic"


# The IBM MQ MQI is invoked through static CALLs to these bootstrap-stub
# program names; flagging them lets `generate` label queue boundaries
# distinctly and lets `.cut` authors write MOCK MQ for intent.
MQ_API_NAMES = frozenset(
    {
        "MQCONN",
        "MQCONNX",
        "MQDISC",
        "MQOPEN",
        "MQCLOSE",
        "MQGET",
        "MQPUT",
        "MQPUT1",
        "MQINQ",
        "MQSET",
        "MQSUB",
        "MQSUBRQ",
        "MQBEGIN",
        "MQCMIT",
        "MQBACK",
        "MQSTAT",
        "MQCB",
        "MQCTL",
    }
)


@dataclass
class CallSite:
    program_name: str | None  # literal name if STATIC, None if DYNAMIC
    kind: CallKind
    paragraph_name: str
    line: int
    nested: bool = False


@dataclass
class BoundarySite:
    """One mockable (or detected-but-unmockable) boundary statement.

    `category` is the MockCategory a directive must use to mock this site,
    or None for detected-but-unmockable sites (dynamic CALL with no
    captured identifier, a SORT/MERGE mixing a USING/GIVING file with an
    INPUT/OUTPUT PROCEDURE on the other side -- see
    `_is_pure_procedure_sort`). `keys` holds the candidate match keys
    (call name, file names, record name, SORT/MERGE SD file name, ACCEPT
    target); `match_text` holds the normalized EXEC text that SQL/CICS/DLI
    prefix keys match against.
    """

    category: MockCategory | None
    label: str  # for messages: "CALL", "READ", "SQL", "dynamic CALL", "SORT/MERGE"
    keys: tuple[str, ...]
    match_text: str | None
    paragraph_name: str
    line: int
    nested: bool
    statement: object
    is_mq: bool = False
    # True when an ancestor statement is itself a boundary statement (a
    # CALL/file-op clause body): the ancestor's splice would remove this
    # site, so it can never be spliced independently.
    nested_in_boundary: bool = False
    # Filled in by splicer.source_map.annotate_nested_sites for nested
    # sites: a validated replacement span, or the reason none exists.
    span: tuple[int, int] | None = None
    unspliceable_reason: str | None = None


@dataclass
class MockSurface:
    call_sites: list[CallSite] = field(default_factory=list)
    boundary_sites: list[BoundarySite] = field(default_factory=list)
    file_io_paragraphs: set[str] = field(default_factory=set)
    exec_paragraphs: set[str] = field(default_factory=set)
    console_accept_paragraphs: set[str] = field(default_factory=set)

    def static_call_sites(self) -> list[CallSite]:
        return [c for c in self.call_sites if c.kind is CallKind.STATIC]

    def dynamic_call_sites(self) -> list[CallSite]:
        return [c for c in self.call_sites if c.kind is CallKind.DYNAMIC]

    def sites_in(self, paragraph_names: set[str]) -> list[BoundarySite]:
        return [s for s in self.boundary_sites if s.paragraph_name in paragraph_names]

    def exec_sites(self) -> list[BoundarySite]:
        return [
            s
            for s in self.boundary_sites
            if s.category in (MockCategory.SQL, MockCategory.CICS, MockCategory.DLI)
        ]


# (statement type, MockCategory, key attribute(s)) for the file-op verbs.
# OPEN/CLOSE name files in `file_names`; READ/DELETE/START/UNLOCK name one
# file in `file_name`; WRITE/REWRITE name the *record* (COBOL syntax names
# the record, not the FD) in `record_name`.
_FILE_OP_SPECS: tuple[tuple[type, MockCategory], ...] = (
    (IOOpenStatement, MockCategory.OPEN),
    (IOCloseStatement, MockCategory.CLOSE),
    (IOReadStatement, MockCategory.READ),
    (IOWriteStatement, MockCategory.WRITE),
    (IORewriteStatement, MockCategory.REWRITE),
    (IODeleteStatement, MockCategory.DELETE),
    (IOStartStatement, MockCategory.START),
    (IOUnlockStatement, MockCategory.UNLOCK),
)

# SORT/MERGE read and write real files (USING/GIVING and the SD sort file);
# RELEASE/RETURN are the sort-file write/read verbs used inside INPUT/OUTPUT
# PROCEDUREs. COBOL's grammar requires exactly one of {USING, INPUT
# PROCEDURE} and exactly one of {GIVING, OUTPUT PROCEDURE} on every
# SORT/MERGE, giving three shapes with three different mockability
# stories:
#   - Plain file form (`USING ... GIVING ...`, no procedure clause):
#     mockable as a single boundary statement, exactly like any other
#     file-op verb -- see `_is_plain_sort_merge`.
#   - Pure procedure form (SORT only -- `INPUT PROCEDURE ... OUTPUT
#     PROCEDURE ...`, no USING/GIVING at all -- MERGE has no INPUT
#     PROCEDURE clause so it can never reach this shape): touches no
#     physical file at all, so the SORT statement itself is left real and
#     unspliced (not a boundary, like DISPLAY); RELEASE/RETURN inside its
#     INPUT/OUTPUT PROCEDURE paragraphs are independently mockable
#     per-statement boundaries instead -- see `_is_pure_procedure_sort`.
#     refusal.py's reachability BFS models the implicit PERFORM those
#     procedure names represent (a SORT/MERGE is not a PerformStatement,
#     so this needs its own edge -- see `_reachable_paragraphs`).
#   - Mixed form (`USING ... OUTPUT PROCEDURE ...` or `INPUT PROCEDURE
#     ... GIVING ...`): touches one physical file AND runs a procedure.
#     Neither whole-statement replacement (would skip the procedure's own
#     logic) nor leaving it real (would touch a physical file mockymock
#     has no mechanism to seed/read) is safe, so this shape stays
#     unmockable and gates UNSUPPORTED_SORT_MERGE exactly as the
#     INPUT/OUTPUT PROCEDURE form did before RELEASE/RETURN-level mocking
#     existed.
_SORT_MERGE_TYPES = (SortStatement, MergeStatement, ReleaseStatement, ReturnStatement)

# The MockCategory a plain-file-form SORT/MERGE site is classified under,
# keyed by its own AST node type.
_SORT_MERGE_MOCKABLE_CATEGORY: dict[type, MockCategory] = {
    SortStatement: MockCategory.SORT,
    MergeStatement: MockCategory.MERGE,
}


def _is_plain_sort_merge(statement: SortStatement | MergeStatement) -> bool:
    """True for a SORT/MERGE using only the USING/GIVING file form -- no
    INPUT PROCEDURE and no OUTPUT PROCEDURE. `MergeStatement` has no
    `input_procedure` attribute at all (MERGE has no INPUT PROCEDURE
    clause in COBOL -- it always reads from USING files); `getattr(...,
    None)` covers both statement shapes without an isinstance branch."""
    return (
        getattr(statement, "input_procedure", None) is None
        and statement.output_procedure is None
    )


def _is_pure_procedure_sort(statement: SortStatement | MergeStatement) -> bool:
    """True for a SORT using INPUT PROCEDURE and OUTPUT PROCEDURE with NO
    USING/GIVING file at all -- the only SORT/MERGE shape that touches no
    physical file. `using_files`/`giving_files` are checked defensively
    (not just `input_procedure`/`output_procedure`) since cobolparser's
    grammar does not itself enforce the "exactly one of USING/INPUT
    PROCEDURE" mutual exclusivity -- a malformed source combining both
    must not be misclassified as safe to leave real. `isinstance(...,
    SortStatement)` gates this because MERGE has no `input_procedure`
    attribute at all, so it can never satisfy this shape."""
    return (
        isinstance(statement, SortStatement)
        and statement.input_procedure is not None
        and statement.output_procedure is not None
        and not statement.using_files
        and not statement.giving_files
    )


# STOP RUN/GOBACK are detected (category None, like CANCEL/SORT-MERGE) but
# never spliced by directive-matching -- a .cut author never writes a MOCK
# for these; the terminator-support feature neutralizes them automatically
# when found safe (see docs/2026-07-08-goback-stop-run-support-design.md).
# Exported so refusal.py can recognize these labels without duplicating
# the literal set.
_TERMINATOR_LABELS = frozenset({"STOP RUN", "GOBACK"})

# Statement types whose nested clause bodies (AT END, INVALID KEY, ON
# EXCEPTION, ...) belong to a *boundary* statement: sites found inside them
# are marked nested_in_boundary because splicing the enclosing statement
# removes them wholesale.
_BOUNDARY_STATEMENT_TYPES = (
    CallStatement,
    *(statement_type for statement_type, _ in _FILE_OP_SPECS),
    *_SORT_MERGE_TYPES,
    ExecSQLStatement,
    ExecCicsStatement,
    ExecImsStatement,
    IOAcceptStatement,
)

# ACCEPT sources that never read the console: system registers and runtime
# values GnuCOBOL resolves without touching stdin. Anything else (no FROM at
# all, FROM CONSOLE, or an unrecognized mnemonic -- fail closed) is console
# input: at test runtime it would read whatever stdin happens to be attached,
# making the run nondeterministic (or hang until the executor timeout).
_NON_INTERACTIVE_ACCEPT_SOURCES = frozenset(
    {
        "DATE",
        "DAY",
        "DAY-OF-WEEK",
        "TIME",
        "COMMAND-LINE",
        "ENVIRONMENT",
        "ENVIRONMENT-VALUE",
        "ARGUMENT-NUMBER",
        "ARGUMENT-VALUE",
    }
)

# NOTE: Verified against cobolparser source (not guessed):
#   - EXEC SQL   -> ExecSQLStatement (cobolparser/models/sql_statements.py),
#                   node_type == "EXEC-SQL" (hyphen, not underscore)
#   - EXEC CICS  -> ExecCicsStatement (cobolparser/parsers/statements/
#                   ibm_exec_statements.py), node_type == "EXEC_CICS"
#   - EXEC DLI   -> ExecImsStatement (same file), node_type == "EXEC_IMS"
# isinstance is used instead of node_type string matching so that
# ExecSQLStatement subclasses (DeclareCursorStatement, FetchStatement,
# DynamicSQLStatement, etc. — all of which keep node_type == "EXEC-SQL")
# are caught without hardcoding every subclass's node_type string.

# Attribute names that hold nested statement bodies (IF/EVALUATE branches,
# inline PERFORM, IO AT END/INVALID KEY/AT END-OF-PAGE clauses, CALL
# exception handlers). Verified directly against cobolparser source — see
# task-5-brief-amended.md Step 7 for the exact file:line citations. Reused
# via getattr() below because CobolStatement's base class doesn't define any
# of these, so a plain getattr(..., None) never misfires on unrelated types.
_NESTED_STATEMENT_ATTRS = (
    "then_statements",
    "else_statements",
    "inline_statements",
    "at_end_clause",
    "not_at_end_clause",
    "invalid_key_clause",
    "not_invalid_key_clause",
    "at_eop_clause",
    "not_at_eop_clause",
    "on_exception",
    "not_on_exception",
    "on_overflow",
    "not_on_overflow",
    "on_size_error",
    "not_on_size_error",
)


def normalize_exec_text(text: str) -> str:
    """Uppercase and collapse all whitespace — the form SQL/CICS/DLI mock
    keys prefix-match against."""
    return " ".join(text.upper().split())


def _nested_statement_lists(statement) -> list[list]:
    """Return every nested `list[CobolStatement]` body attached to `statement`.

    Covers IF/ELSE branches, inline PERFORM bodies, IO clause bodies
    (AT END, INVALID KEY, AT END-OF-PAGE), CALL exception handlers, and
    (via the EvaluateStatement/SearchStatement special cases) every
    EVALUATE WHEN/WHEN OTHER branch and every SEARCH WHEN body.
    """
    lists = [
        value
        for attr in _NESTED_STATEMENT_ATTRS
        if (value := getattr(statement, attr, None))
    ]
    if isinstance(statement, EvaluateStatement):
        for when in statement.when_clauses:
            if when.statements:
                lists.append(when.statements)
        if statement.default_when is not None and statement.default_when.statements:
            lists.append(statement.default_when.statements)
    if isinstance(statement, SearchStatement):
        # SearchStatement.when_clauses is a list[dict] with a "statements"
        # key (verified against cobolparser's control.py), unlike
        # EvaluateStatement's WhenClause nodes. SEARCH's AT END body is
        # already covered by "at_end_clause" in _NESTED_STATEMENT_ATTRS.
        for when in statement.when_clauses:
            if when.get("statements"):
                lists.append(when["statements"])
    return lists


def _file_op_keys(statement, category: MockCategory) -> tuple[str, ...]:
    if category in (MockCategory.OPEN, MockCategory.CLOSE):
        return tuple(name.upper() for name in statement.file_names if name)
    if category in (MockCategory.WRITE, MockCategory.REWRITE):
        name = statement.record_name
    else:
        name = statement.file_name
    return (name.upper(),) if name else ()


def _classify_statement(
    statement,
    paragraph_name: str,
    surface: MockSurface,
    nested: bool,
    in_boundary: bool = False,
) -> None:
    """Classify a single statement (top-level or nested) into `surface`."""
    line = statement.location.line

    def add_site(
        category: MockCategory | None,
        label: str,
        keys: tuple[str, ...] = (),
        match_text: str | None = None,
        is_mq: bool = False,
    ) -> None:
        surface.boundary_sites.append(
            BoundarySite(
                category=category,
                label=label,
                keys=keys,
                match_text=match_text,
                paragraph_name=paragraph_name,
                line=line,
                nested=nested,
                statement=statement,
                is_mq=is_mq,
                nested_in_boundary=in_boundary,
            )
        )

    if isinstance(statement, CallStatement):
        kind = CallKind.DYNAMIC if statement.is_dynamic else CallKind.STATIC
        surface.call_sites.append(
            CallSite(
                program_name=None if statement.is_dynamic else statement.called_program,
                kind=kind,
                paragraph_name=paragraph_name,
                line=line,
                nested=nested,
            )
        )
        if statement.is_dynamic:
            # called_program holds the identifier NAME for a dynamic call
            # (verified empirically; see interface-contract.md). No name
            # captured -> keep the site unmockable, fail closed.
            identifier = (statement.called_program or "").upper()
            if identifier:
                add_site(MockCategory.DYNCALL, "dynamic CALL", keys=(identifier,))
            else:
                add_site(None, "dynamic CALL")
        else:
            name = statement.called_program or ""
            add_site(
                MockCategory.CALL,
                "CALL",
                keys=(name,),
                is_mq=name.upper() in MQ_API_NAMES,
            )
        return

    for statement_type, category in _FILE_OP_SPECS:
        if isinstance(statement, statement_type):
            surface.file_io_paragraphs.add(paragraph_name)
            add_site(category, category.value, keys=_file_op_keys(statement, category))
            return

    if isinstance(statement, (SortStatement, MergeStatement)):
        surface.file_io_paragraphs.add(paragraph_name)
        if _is_plain_sort_merge(statement):
            category = _SORT_MERGE_MOCKABLE_CATEGORY[type(statement)]
            name = statement.file_name or ""
            add_site(category, category.value, keys=(name.upper(),) if name else ())
        elif _is_pure_procedure_sort(statement):
            # Touches no physical file at all -- left real and unspliced,
            # not recorded as a boundary site (like DISPLAY). Its
            # INPUT/OUTPUT PROCEDURE paragraphs are reached via the
            # implicit-PERFORM edge refusal.py's `_reachable_paragraphs`
            # models for a SORT/MERGE statement, and the RELEASE/RETURN
            # statements inside them are classified as their own,
            # independently mockable, boundary sites below.
            pass
        else:
            # A USING/GIVING file paired with a procedure clause on the
            # other side: neither whole-statement replacement (would skip
            # the procedure's own logic) nor leaving it real (would touch
            # a physical file mockymock cannot seed/read) is safe.
            add_site(None, "SORT/MERGE")
        return

    if isinstance(statement, ReleaseStatement):
        # RELEASE only ever appears inside a SORT/MERGE's INPUT
        # PROCEDURE, but that no longer determines mockability on its
        # own: it is an ordinary, independently mockable boundary
        # statement (WRITE-shaped -- keyed by record name) regardless of
        # whether the enclosing SORT turned out to be pure-procedure
        # (left real) or mixed-form (still unmockable,
        # UNSUPPORTED_SORT_MERGE) -- a mixed-form SORT/MERGE already
        # refuses the whole test case on its own account, so a RELEASE
        # inside one being "mockable in principle" is moot in practice
        # but not unsound.
        surface.file_io_paragraphs.add(paragraph_name)
        name = statement.record_name or ""
        add_site(MockCategory.RELEASE, "RELEASE", keys=(name.upper(),) if name else ())
        return

    if isinstance(statement, ReturnStatement):
        # RETURN only ever appears inside a SORT/MERGE's OUTPUT
        # PROCEDURE. READ-shaped -- keyed by the SD file name, its own
        # AT END/NOT AT END clause already covered by
        # _NESTED_STATEMENT_ATTRS. See RELEASE's comment above for why
        # mockability no longer tracks the enclosing SORT/MERGE's shape.
        surface.file_io_paragraphs.add(paragraph_name)
        name = statement.file_name or ""
        add_site(MockCategory.RETURN, "RETURN", keys=(name.upper(),) if name else ())
        return

    if isinstance(statement, CancelStatement):
        # CANCEL is never spliced (category None keeps it out of the
        # splicer and out of directive matching), but it is not unmockable
        # like SORT/MERGE either: under the refusal gate no mocked CALL
        # ever loads a real module, so CANCEL of a program whose CALLs the
        # test case mocks is a guaranteed GnuCOBOL no-op and counts as
        # covered. The gate checks `keys` against the case's CALL/DYNCALL
        # directives; a CANCEL naming anything else refuses (UNMOCKED_CANCEL).
        add_site(None, "CANCEL", keys=tuple(statement.program_names))
        return

    if isinstance(statement, StopStatement):
        # STOP "literal" (stop_type == "literal") displays the literal and
        # continues -- only STOP RUN terminates the run unit.
        if statement.stop_type == "RUN":
            add_site(None, "STOP RUN")
        return

    if isinstance(statement, GobackStatement):
        add_site(None, "GOBACK")
        return

    if isinstance(statement, ExecSQLStatement):
        surface.exec_paragraphs.add(paragraph_name)
        add_site(
            MockCategory.SQL,
            "SQL",
            match_text=normalize_exec_text(getattr(statement, "sql_text", "") or ""),
        )
        return

    if isinstance(statement, ExecCicsStatement):
        surface.exec_paragraphs.add(paragraph_name)
        add_site(
            MockCategory.CICS,
            "CICS",
            match_text=normalize_exec_text(
                f"{statement.cics_command} {statement.cics_text}"
            ),
        )
        return

    if isinstance(statement, ExecImsStatement):
        surface.exec_paragraphs.add(paragraph_name)
        add_site(
            MockCategory.DLI,
            "DLI",
            match_text=normalize_exec_text(
                f"{statement.ims_command} {statement.ims_text}"
            ),
        )
        return

    if isinstance(statement, IOAcceptStatement):
        if statement.from_source not in _NON_INTERACTIVE_ACCEPT_SOURCES:
            surface.console_accept_paragraphs.add(paragraph_name)
            target = (statement.target or "").upper()
            add_site(MockCategory.ACCEPT, "ACCEPT", keys=(target,) if target else ())


def _walk_statements(
    statements,
    paragraph_name: str,
    surface: MockSurface,
    nested: bool = False,
    in_boundary: bool = False,
) -> None:
    """Classify `statements` and recurse into every nested statement body.

    Nesting depth doesn't change which paragraph a refusal-gate check cares
    about, so nested statements are still attributed to `paragraph_name`.
    Every recursive call passes `nested=True` literally (not the parent's
    `nested` value) so a site is marked nested at every depth >= 1, while
    top-level statements (the initial call, where `nested` defaults to
    `False`) stay correctly unmarked. `in_boundary`, by contrast, is
    sticky: once the recursion enters a boundary statement's clause body,
    everything below it is nested_in_boundary.
    """
    for statement in statements:
        _classify_statement(statement, paragraph_name, surface, nested, in_boundary)
        child_in_boundary = in_boundary or isinstance(
            statement, _BOUNDARY_STATEMENT_TYPES
        )
        for nested_list in _nested_statement_lists(statement):
            _walk_statements(
                nested_list,
                paragraph_name,
                surface,
                nested=True,
                in_boundary=child_in_boundary,
            )


def analyze(program: CobolProgram) -> MockSurface:
    """Walk PROCEDURE DIVISION and classify every CALL/file-IO/EXEC/ACCEPT
    statement into per-site `BoundarySite` records (plus the v1 paragraph
    sets).

    Recurses into nested statement bodies (IF/EVALUATE branches, inline
    PERFORM, IO AT END/INVALID KEY clauses, CALL exception handlers) so that
    e.g. a CALL hidden inside an IF is not missed.
    """
    surface = MockSurface()
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return surface

    for paragraph in _all_paragraphs(procedure):
        _walk_statements(paragraph.statements, paragraph.paragraph_name, surface)

    return surface


def analyze_file_status_fields(program: CobolProgram) -> dict[str, str]:
    """Uppercased file name -> its declared `FILE STATUS IS <field>` name,
    read from the ENVIRONMENT DIVISION's FILE-CONTROL SELECT statements. A
    file whose SELECT entry has no FILE STATUS clause has no entry -- there
    is no WORKING-STORAGE field to default or target with FILE-STATUS IS
    sugar (see docs/2026-07-20-before-blocks-and-file-status-design.md)."""
    fields: dict[str, str] = {}
    environment = program.get_division("ENVIRONMENT")
    if environment is None:
        return fields
    io_section = environment.get_section_by_name("INPUT-OUTPUT")
    if not isinstance(io_section, CobolSection):
        return fields
    file_control = io_section.get_paragraph_by_name("FILE-CONTROL")
    if file_control is None:
        return fields
    for statement in file_control.statements:
        if not isinstance(statement, SelectStatement):
            continue
        if statement.file_name and statement.file_status:
            fields[statement.file_name.upper()] = statement.file_status
    return fields


def _all_paragraphs(procedure_division: CobolDivision) -> list[CobolParagraph]:
    """Mirrors CoverageAnalyzer._analyze_paragraphs's traversal pattern."""
    paragraphs = list(procedure_division.paragraphs)
    for section in procedure_division._sections.values():
        paragraphs.extend(section.paragraphs)
    return paragraphs
