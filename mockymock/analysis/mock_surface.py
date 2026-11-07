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

Since 2026-09-02 the classification is fail-closed over the statement
TYPE as well: every statement class is either a known pass-through
(`_PASSTHROUGH_STATEMENT_NAMES` -- MOVE/IF/COMPUTE/DISPLAY/..., nothing
outside the program), a classified boundary, or a detected-unmockable site
(`category=None`) -- INVOKE, CHAIN, the Communication Module verbs
(SEND/RECEIVE/ENABLE/DISABLE/PURGE), `STOP <literal>`, and, as the
catch-all, any statement class this module does not know (label
"unsupported statement"). cobol-parser's 2026-09-02 statement-coverage
work gave every COBOL verb its own AST node; before it those verbs were
warned-and-discarded, and mockymock's PARSE_WARNING refusal caught them --
a verb that now parses cleanly would otherwise walk straight past this
module unseen. The Report Writer verbs INITIATE/GENERATE/TERMINATE became
mockable categories in the same change (keyed on report name, spliced out
whole like any other boundary statement).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mockymock.analysis.declaratives import UseProcedures

from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
)
from cobolparser.models.sql_statements import ExecSQLStatement
from cobolparser.models.statements.call import CallStatement
from cobolparser.models.statements.communication import (
    DisableStatement,
    EnableStatement,
    PurgeStatement,
    ReceiveStatement,
    SendStatement,
)
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
from cobolparser.models.statements.legacy import ChainStatement
from cobolparser.models.statements.misc import (
    CancelStatement,
    ExitStatement,
    GenerateStatement,
    GobackStatement,
    InvokeStatement,
    MergeStatement,
    ReleaseStatement,
    ReturnStatement,
    SelectStatement,
    SortStatement,
    XmlJsonStatement,
)
from cobolparser.models.statements.report_writer import (
    InitiateStatement,
    TerminateStatement,
)
from cobolparser.parsers.statements.ibm_exec_statements import (
    ExecCicsStatement,
    ExecImsStatement,
)

from mockymock.analysis.cics_handle import handle_states, is_handle_declaration
from mockymock.analysis.sql_whenever import (
    Whenever,
    is_sql_declaration,
    is_whenever,
    parse_whenever,
    whenever_actions,
)
from mockymock.dsl.model import MockCategory
from mockymock.splicer.io_copy import DataLayout, data_layout

# Verb-coverage node classes (cobol-parser's 2026-09-02 statement work),
# as isinstance-ready tuples so the classifier below can match them.
_INVOKE_TYPES: tuple[type, ...] = (InvokeStatement,)
_GENERATE_TYPES: tuple[type, ...] = (GenerateStatement,)
_XML_JSON_TYPES: tuple[type, ...] = (XmlJsonStatement,)
_CHAIN_TYPES: tuple[type, ...] = (ChainStatement,)
_COMMUNICATION_TYPES: tuple[type, ...] = (
    SendStatement,
    ReceiveStatement,
    EnableStatement,
    DisableStatement,
    PurgeStatement,
)
_INITIATE_TYPES: tuple[type, ...] = (InitiateStatement,)
_TERMINATE_TYPES: tuple[type, ...] = (TerminateStatement,)

# Statement classes verified to touch nothing outside the program (data
# movement, arithmetic, control flow, console DISPLAY, compiler-directing
# and no-op legacy verbs). Closed by NAME rather than by imported class so
# the list is independent of which cobol-parser release is installed, and
# so a class this module has never heard of -- a future verb, a renamed
# node -- can never be assumed harmless: `_classify_statement` records
# anything outside this set that no boundary branch claimed as a
# detected-unmockable "unsupported statement" site. Swept 2026-09-02
# against every COBOL file in both repos (582 programs, NIST suite
# included): the only classes outside this set and the boundary branches
# were the Communication Module, Report Writer and STOP-literal ones, each
# of which now has its own branch below.
#
# Notes on the less obvious members: ALTER and USE are handled whole-
# program elsewhere (`analysis.alter`, `analysis.declaratives`);
# SUPPRESS only ever appears inside a Report Writer USE BEFORE REPORTING
# declarative (same refusal); ENTRY is handled by analysis.linkage;
# COMMIT/ROLLBACK are file-commit verbs whose files are all mocked or
# refused already; XML/JSON GENERATE/PARSE act on WORKING-STORAGE only
# (an XML PARSE's PROCESSING PROCEDURE is a flow edge refusal.py models,
# and its ON EXCEPTION bodies are walked via _NESTED_STATEMENT_ATTRS).
_PASSTHROUGH_STATEMENT_NAMES = frozenset(
    {
        "AddStatement",
        "AllocateStatement",
        "AlterStatement",
        "ArithmeticStatement",
        "CommitStatement",
        "ComputeStatement",
        "ContinueStatement",
        "CopyStatement",
        "DisplayStatement",
        "DivideStatement",
        "EjectStatement",
        "EnterStatement",
        "EntryStatement",
        "EvaluateStatement",
        "ExamineStatement",
        "ExhibitStatement",
        "ExitStatement",
        "FreeStatement",
        "GoStatement",
        "IfStatement",
        "InitializeStatement",
        "InspectStatement",
        "MoveStatement",
        "MultiplyStatement",
        "NextSentenceStatement",
        "NoteStatement",
        "PerformStatement",
        "RaiseStatement",
        "ResumeStatement",
        "RollbackStatement",
        "SearchStatement",
        "SelectStatement",
        "ServiceStatement",
        "SetStatement",
        "SkipStatement",
        "StringStatement",
        "SubtractStatement",
        "SuppressStatement",
        "TitleStatement",
        "TraceStatement",
        "TransformStatement",
        "UnstringStatement",
        "UseStatement",
        "ValidateStatement",
        "XmlJsonStatement",
    }
)

# The label every detected-unmockable site for an unknown statement class
# carries; refusal.py keys its UNSUPPORTED_STATEMENT reason on it. The
# site's `keys` holds the statement's own verb text for the message.
UNSUPPORTED_STATEMENT_LABEL = "unsupported statement"

# XML PARSE's optional processing-procedure clause, matched against
# `clause_text` only to fail closed on a cobol-parser that keeps the
# clause as text without exposing `processing_procedure` (see
# refusal._reachability's XML PARSE edge).
XML_PROCESSING_PROCEDURE_RE = re.compile(r"\bPROCESSING\s+PROCEDURE\b", re.IGNORECASE)
_XML_EXCEPTION_RE = re.compile(r"\bEXCEPTION\b", re.IGNORECASE)


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
    # for messages: "CALL", "READ", "SQL", "GENERATE", "dynamic CALL",
    # "SORT/MERGE", "INVOKE", "CHAIN", "communication", "STOP literal",
    # "unsupported statement" (the last five always with category None)
    label: str
    keys: tuple[str, ...]
    match_text: str | None
    paragraph_name: str
    line: int
    nested: bool
    statement: object
    is_mq: bool = False
    # A dynamic CALL whose identifier can only name MQI entry points
    # (`_mark_dynamic_mq_calls`): answered like a static MQ call.
    mq_target: bool = False
    # True when an ancestor statement is itself a boundary statement (a
    # CALL/file-op clause body). Such a site still gets a span when every
    # such ancestor's clause bodies are lifted and re-run after a mock: the
    # splicer then splices it inside the lifted copy
    # (splicer.source_map._in_boundary_problem).
    nested_in_boundary: bool = False
    # Filled in by splicer.source_map.annotate_nested_sites for nested
    # sites: a validated replacement span, or the reason none exists.
    span: tuple[int, int] | None = None
    unspliceable_reason: str | None = None
    # The clause header the span's first line opens with, before the
    # statement (`AT END` of `AT END CALL "X"`): a splice in place emits it
    # back on its own line ahead of the replacement.
    span_lead: str | None = None
    # An `EXEC SQL WHENEVER` site (`MockSurface.whenever_sites` only): its
    # parsed declaration. Never mocked -- the splicer replaces it with
    # CONTINUE (issue #195, see analysis.sql_whenever).
    whenever: Whenever | None = None
    # A mockable CICS site: the EXEC CICS HANDLE/IGNORE CONDITION map in
    # force at it (issue #268, analysis.cics_handle), for the GO TO a mock
    # raising a condition (`CONDITION IS`) ends with.
    cics_handle_state: dict[str, str | None] = field(default_factory=dict)
    # A mockable SQL site: the (condition, GO TO target) checks the WHENEVER
    # declarations above it in the source put after it, in DB2's order.
    whenever_checks: tuple[tuple[str, str], ...] = ()
    # A console ACCEPT site: its whole target as written, subscript or
    # qualifier included (`WS-ENT ( WS-I )`), while `keys` holds the
    # data-name alone (issue #311).
    accept_target: str | None = None
    # An opt-in site (`promote_clock_accepts`, issue #240): an `ACCEPT x
    # FROM DATE/TIME/DAY/DAY-OF-WEEK` some MOCK names. It is spliced, but a
    # test case that does not mock it runs the real statement (the
    # dispatch's WHEN OTHER), so it is never refused as unmocked.
    opt_in: bool = False
    # A READ site: its access form (`model.READ_ACCESS_WORDS`): "NEXT",
    # "PREVIOUS", "KEY", or "KEY <alternate key>" -- what a qualified
    # `MOCK READ <file> <form>` matches (`read_form_of`).
    read_form: str | None = None
    # An OPEN site: the mode each file it opens is opened in, by uppercased
    # file name (`model.OPEN_MODE_WORDS`) -- what a qualified `MOCK OPEN
    # <file> <mode>` matches (`open_modes_of`).
    open_modes: dict[str, str] = field(default_factory=dict)
    # A mixed-form SORT/MERGE site (a USING/GIVING file on one side, an
    # INPUT/OUTPUT PROCEDURE on the other, 2026-11-03): (side, first, thru)
    # of its procedure, side "INPUT" or "OUTPUT". The mock answers the file
    # side, and the splice PERFORMs the procedure before it (INPUT) or after
    # it (OUTPUT), as the SORT would (`mixed_sort_procedure`).
    sort_procedure: tuple[str, str, str | None] | None = None


@dataclass
class NonInteractiveAccept:
    """An `ACCEPT <target> FROM <system source>` -- DATE, TIME, DAY,
    COMMAND-LINE, ... (`_NON_INTERACTIVE_ACCEPT_SOURCES`).

    These are deliberately NOT boundary sites: GnuCOBOL resolves them from
    the runtime without ever touching stdin, so there is nothing to mock
    and nothing that could hang a test. Recording them anyway is purely for
    error quality: a `MOCK ACCEPT WS-NOW` aimed at one of them matches no
    boundary site, and without this list the refusal gate can only report
    the generic UNMATCHED_MOCK ("does not match any boundary site reachable
    from ..."), which reads as a reachability problem and sends the author
    off verifying their call graph. The real answer -- this ACCEPT variant
    is not mockable at all -- is a different problem and gets its own
    refusal code (UNMOCKABLE_ACCEPT_SOURCE)."""

    target: str
    from_source: str
    paragraph_name: str
    line: int
    # What `promote_clock_accepts` needs to turn a clock ACCEPT into an
    # opt-in boundary site when a MOCK names it.
    statement: object = None
    nested: bool = False
    nested_in_boundary: bool = False

    @property
    def reads_clock(self) -> bool:
        """FROM DATE / TIME / DAY / DAY-OF-WEEK: a value that changes from
        run to run, so a test can only pin it by mocking the ACCEPT."""
        words = self.from_source.upper().split()
        return bool(words) and words[0] in CLOCK_ACCEPT_SOURCES


@dataclass
class MockSurface:
    call_sites: list[CallSite] = field(default_factory=list)
    boundary_sites: list[BoundarySite] = field(default_factory=list)
    file_io_paragraphs: set[str] = field(default_factory=set)
    exec_paragraphs: set[str] = field(default_factory=set)
    console_accept_paragraphs: set[str] = field(default_factory=set)
    #: Detected-and-deliberately-unmockable system ACCEPTs, for error
    #: messages only -- see `NonInteractiveAccept`. Never spliced, never
    #: refused on their own, never reported as unsupported boundaries (an
    #: `ACCEPT WS-TODAY FROM DATE` is ordinary, working COBOL that needs no
    #: mock; listing it as a gap would be noise on almost every program).
    non_interactive_accepts: list[NonInteractiveAccept] = field(default_factory=list)
    #: FD records and data-item subtrees, for the implicit INTO/FROM MOVE a
    #: mocked READ ... INTO / WRITE ... FROM keeps (`splicer.io_copy`).
    data_layout: DataLayout | None = None
    #: `EXEC SQL WHENEVER` declarations (issue #195): SQL-category sites
    #: kept OUT of `boundary_sites`, since nothing mocks them -- they are
    #: spliced to CONTINUE, and their GO TO checks follow every later SQL
    #: site (`BoundarySite.whenever_checks`). The other precompiler
    #: declarations (`DECLARE ... CURSOR`, `INCLUDE`, `BEGIN/END DECLARE
    #: SECTION`, issue #267) are here too, with `whenever` None: spliced to
    #: CONTINUE, nothing else.
    whenever_sites: list[BoundarySite] = field(default_factory=list)
    #: Every SELECT, by uppercased file name: organization, access mode and
    #: keys, for the READ forms and the key a keyed READ asks for.
    file_selects: dict[str, FileSelect] = field(default_factory=dict)
    #: The program's USE AFTER EXCEPTION/ERROR procedures (DECLARATIVES),
    #: which the splicer runs after a mocked file statement's exception
    #: outcome (`analysis.declaratives`); None when it has none.
    use_procedures: UseProcedures | None = None
    #: Every paragraph and section name inside DECLARATIVES.
    declarative_names: frozenset[str] = frozenset()
    #: `ALTER P TO PROCEED TO <its own target>` for every paragraph an
    #: ALTER changes: each case starts with the GO TOs as written
    #: (`analysis.alter.alter_reset_lines`).
    alter_resets: tuple[str, ...] = ()

    def static_call_sites(self) -> list[CallSite]:
        return [c for c in self.call_sites if c.kind is CallKind.STATIC]

    def dynamic_call_sites(self) -> list[CallSite]:
        return [c for c in self.call_sites if c.kind is CallKind.DYNAMIC]

    def sites_in(self, paragraph_names: set[str]) -> list[BoundarySite]:
        return [s for s in self.boundary_sites if s.paragraph_name in paragraph_names]

    def exec_sites(self) -> list[BoundarySite]:
        """Every EXEC site, WHENEVER declarations included: each one must be
        spliced out for cobc to compile the program."""
        return [
            s
            for s in [*self.boundary_sites, *self.whenever_sites]
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


def mixed_sort_procedure(
    statement: SortStatement | MergeStatement,
) -> tuple[str, str, str | None] | None:
    """(side, first, thru) of a mixed-form SORT/MERGE's one procedure: an
    INPUT PROCEDURE with GIVING files, or USING files with an OUTPUT
    PROCEDURE. None for any other shape."""
    input_procedure = getattr(statement, "input_procedure", None)
    output_procedure = statement.output_procedure
    using = getattr(statement, "using_files", None)
    giving = getattr(statement, "giving_files", None)
    if input_procedure and not output_procedure and giving and not using:
        thru = getattr(statement, "input_procedure_thru", None)
        return ("INPUT", input_procedure.upper(), thru.upper() if thru else None)
    if output_procedure and not input_procedure and using and not giving:
        thru = getattr(statement, "output_procedure_thru", None)
        return ("OUTPUT", output_procedure.upper(), thru.upper() if thru else None)
    return None


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


# STOP RUN/GOBACK/EXIT PROGRAM are detected (category None, like
# CANCEL/SORT-MERGE) but never spliced by directive-matching -- a .cut
# author never writes a MOCK for these; the terminator-support feature
# neutralizes them automatically when found safe (see
# docs/2026-07-08-goback-stop-run-support-design.md). EXIT PROGRAM joined
# them for issue #212: the driver makes the program under test the main
# program of the run unit, where EXIT PROGRAM is a no-op, but the only
# program it ever appears in for real is a called subprogram, where it
# returns to the caller -- left alone, it silently fell through.
# Exported so refusal.py can recognize these labels without duplicating
# the literal set.
_TERMINATOR_LABELS = frozenset({"STOP RUN", "GOBACK", "EXIT PROGRAM"})

# Category-None sites the splicer replaces with CONTINUE: the console or
# screen answers at once (STOP <literal> waits for the operator; a screen
# DISPLAY would switch GnuCOBOL to screen mode).
ANSWERED_LABELS = frozenset({"STOP literal", "screen DISPLAY"})


def is_answered_site(site: BoundarySite) -> bool:
    """Whether the splicer answers this site with CONTINUE: an
    `ANSWERED_LABELS` site at the top level that owns its line, or one
    nested in an IF / EVALUATE / inline PERFORM with a validated `span`
    (`annotate_nested_sites`). One nested in another boundary's clause body
    has no span -- splicing that statement would remove it -- and is
    refused when a case reaches it (issue #422)."""
    if site.label not in ANSWERED_LABELS or site.unspliceable_reason:
        return False
    return not site.nested or site.span is not None


# EXEC CICS commands that never give control back to the next statement
# (issue #215): RETURN ends the task (or returns to the LINKing program),
# XCTL transfers to another program for good, ABEND ends the task. They
# stay ordinary, mockable CICS sites -- the mock body runs -- but the
# splicer then ends the run under test the way a neutralized GOBACK does
# (`refusal.find_terminator_plans`), instead of carrying on past them.
CICS_TERMINATOR_COMMANDS = frozenset({"RETURN", "XCTL", "ABEND"})


def accept_key(target: str) -> str:
    """The data-name an ACCEPT target is mocked by: its first word, cut at
    a subscript / reference modification and before any `OF`/`IN`
    qualifier (`WS-ENT ( WS-I )` -> `WS-ENT`, `FLD OF REC-B` -> `FLD`)."""
    words = target.upper().split("(", 1)[0].split()
    return words[0] if words else ""


def is_cics_terminator(statement) -> bool:
    """True for an EXEC CICS RETURN/XCTL/ABEND statement."""
    return (
        isinstance(statement, ExecCicsStatement)
        and str(getattr(statement, "cics_command", "") or "").upper()
        in CICS_TERMINATOR_COMMANDS
    )


def is_terminator_site(site) -> bool:
    """A site whose statement ends the run under test: STOP RUN/GOBACK/
    EXIT PROGRAM (category None) or an EXEC CICS RETURN/XCTL/ABEND."""
    if site.category is None:
        return site.label in _TERMINATOR_LABELS
    return site.category is MockCategory.CICS and is_cics_terminator(site.statement)


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
    # RECEIVE's NO DATA / WITH DATA bodies and INVOKE belong to sites that
    # are refused outright, but the sticky flag still describes them
    # correctly: nothing inside could ever be spliced independently.
    *_COMMUNICATION_TYPES,
    *_INVOKE_TYPES,
    *_INITIATE_TYPES,
    *_GENERATE_TYPES,
    *_TERMINATE_TYPES,
)

# ACCEPT sources that never read the console: system registers and runtime
# values GnuCOBOL resolves without touching stdin. Anything else (no FROM at
# all, FROM CONSOLE, or an unrecognized mnemonic -- fail closed) is console
# input: at test runtime it would read whatever stdin happens to be attached,
# making the run nondeterministic (or hang until the executor timeout).
#: The `_NON_INTERACTIVE_ACCEPT_SOURCES` that read the system clock.
CLOCK_ACCEPT_SOURCES = frozenset({"DATE", "DAY", "DAY-OF-WEEK", "TIME"})

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
    # RECEIVE ... NO DATA / WITH DATA (Communication Module, cobol-parser
    # 2026-09-02). XML/JSON GENERATE/PARSE's ON EXCEPTION / NOT ON
    # EXCEPTION bodies arrive under the CALL-shaped names already listed.
    "no_data_clause",
    "with_data_clause",
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
        for search_when in statement.when_clauses:
            if search_when.get("statements"):
                lists.append(search_when["statements"])
    return lists


def _file_op_keys(statement, category: MockCategory) -> tuple[str, ...]:
    if category in (MockCategory.OPEN, MockCategory.CLOSE):
        return tuple(name.upper() for name in statement.file_names if name)
    if category in (MockCategory.WRITE, MockCategory.REWRITE):
        # A record name qualified by its file (`WRITE PRINT-REC IN
        # PRINT-FILE`, NIST SQ207M) keys on the record name: the .cut
        # grammar takes one bare COBOL name, and generate wrote the whole
        # phrase into a MOCK the suite then failed to parse.
        name = (statement.record_name or "").split()
        return (name[0].upper(),) if name else ()
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
        into: list[BoundarySite] | None = None,
    ) -> BoundarySite:
        site = BoundarySite(
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
        (surface.boundary_sites if into is None else into).append(site)
        return site

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
        elif (procedure := mixed_sort_procedure(statement)) is not None:
            # A USING/GIVING file paired with a procedure clause on the
            # other side (2026-11-03): mocked like the plain form, and the
            # splice PERFORMs the procedure on its side of the mock, so its
            # own logic still runs (RELEASE/RETURN inside it are their own
            # sites).
            category = _SORT_MERGE_MOCKABLE_CATEGORY[type(statement)]
            name = statement.file_name or ""
            site = add_site(
                category, category.value, keys=(name.upper(),) if name else ()
            )
            site.sort_procedure = procedure
        else:
            # Both procedure clauses AND a file, or neither side readable:
            # a shape the grammar does not allow, left refused.
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

    if getattr(statement, "is_screen_display", False):
        # DISPLAY ... AT / LINE / COL / HIGHLIGHT / UPON CRT writes to the
        # screen: GnuCOBOL switches the terminal to screen mode, and every
        # later DISPLAY of the test driver lands on that screen, out of the
        # run's output (the case then looks like it never finished). Never
        # a pass-through: spliced to CONTINUE, as STOP literal is.
        add_site(None, "screen DISPLAY")
        return

    if isinstance(statement, StopStatement):
        # Only STOP RUN terminates the run unit. Every other form (`STOP
        # "literal"`, `STOP ZERO`, `STOP 123` -- `stop_type` holds the
        # operand text) displays the operand and then waits for the
        # operator on the console before continuing: a console read, so
        # it fails closed exactly like an unmocked ACCEPT would.
        if statement.stop_type == "RUN":
            add_site(None, "STOP RUN")
        else:
            operand = str(statement.stop_type or "").strip()
            add_site(None, "STOP literal", keys=(operand,) if operand else ())
        return

    if isinstance(statement, _INVOKE_TYPES):
        # INVOKE object-ref "method": an external (object-oriented) call
        # mockymock has no mock category for. Detected, never spliced.
        keys = tuple(
            k
            for k in (
                getattr(statement, "object_name", None),
                getattr(statement, "method_name", None),
            )
            if k
        )
        add_site(None, "INVOKE", keys=keys)
        return

    if isinstance(statement, _CHAIN_TYPES):
        # CHAIN "PROG" USING ...: a CALL that never returns (Micro Focus).
        name = getattr(statement, "program", None) or ""
        add_site(None, "CHAIN", keys=(name,) if name else ())
        return

    if isinstance(statement, _COMMUNICATION_TYPES):
        # SEND/RECEIVE/ENABLE/DISABLE/PURGE: the COBOL-85 Communication
        # Module's message queues, keyed by the CD name for the message.
        cd_name = (getattr(statement, "cd_name", None) or "").upper()
        add_site(None, "communication", keys=(cd_name,) if cd_name else ())
        return

    if isinstance(statement, (*_INITIATE_TYPES, *_TERMINATE_TYPES)):
        # INITIATE/TERMINATE report-name ...: one site, one key per report
        # (like a multi-file OPEN/CLOSE).
        category = (
            MockCategory.INITIATE
            if isinstance(statement, _INITIATE_TYPES)
            else MockCategory.TERMINATE
        )
        surface.file_io_paragraphs.add(paragraph_name)
        report_names = getattr(statement, "report_names", None) or []
        keys = tuple(name.upper() for name in report_names if name)
        add_site(category, category.value, keys=keys)
        return

    if isinstance(statement, _GENERATE_TYPES):
        # GENERATE report-or-group-name: writes the detail group (or the
        # whole report's summary) through the report file.
        surface.file_io_paragraphs.add(paragraph_name)
        name = (getattr(statement, "report_name", None) or "").upper()
        add_site(MockCategory.GENERATE, "GENERATE", keys=(name,) if name else ())
        return

    if isinstance(statement, _XML_JSON_TYPES):
        # XML/JSON GENERATE/PARSE act on WORKING-STORAGE only -- not a
        # boundary. Two fail-closed guards for older cobol-parser releases
        # that kept the whole clause region as text: an exception-handler
        # body hidden in `clause_text` could contain a CALL/file-op this
        # walk would never see, and a PROCESSING PROCEDURE not exposed as
        # `processing_procedure` is a flow edge refusal.py could not
        # follow. Either makes the statement unmodelable here.
        clause_text = getattr(statement, "clause_text", None) or ""
        handlers_modeled = hasattr(statement, "on_exception")
        procedure_modeled = hasattr(statement, "processing_procedure")
        if (_XML_EXCEPTION_RE.search(clause_text) and not handlers_modeled) or (
            XML_PROCESSING_PROCEDURE_RE.search(clause_text) and not procedure_modeled
        ):
            add_site(
                None,
                UNSUPPORTED_STATEMENT_LABEL,
                keys=(
                    f"{getattr(statement, 'statement_type', 'XML/JSON')} (this cobol-parser keeps its "
                    f"handler/PROCESSING PROCEDURE clause as text only)",
                ),
            )
        return

    if isinstance(statement, GobackStatement):
        add_site(None, "GOBACK")
        return

    if isinstance(statement, ExitStatement) and statement.exit_type == "PROGRAM":
        # Returns to the caller in a called subprogram (the only place it
        # is ever written), so it ends the run under test exactly like
        # GOBACK -- see _TERMINATOR_LABELS. Every other EXIT form
        # (PARAGRAPH/SECTION/PERFORM, bare EXIT) stays a passthrough.
        add_site(None, "EXIT PROGRAM")
        return

    if isinstance(statement, ExecSQLStatement):
        sql_text = getattr(statement, "sql_text", "") or ""
        if is_whenever(sql_text):
            # A precompiler declaration, not a boundary: never mocked, its
            # checks are emulated after every later SQL site (issue #195).
            site = add_site(
                MockCategory.SQL, "SQL WHENEVER", into=surface.whenever_sites
            )
            site.whenever = parse_whenever(sql_text)
            return
        if is_sql_declaration(sql_text):
            # DECLARE CURSOR/TABLE, INCLUDE, BEGIN/END DECLARE SECTION: no
            # runtime behavior and no SQLCA update, so not a boundary --
            # spliced to CONTINUE alongside WHENEVER (issue #267).
            add_site(MockCategory.SQL, "SQL DECLARATION", into=surface.whenever_sites)
            return
        surface.exec_paragraphs.add(paragraph_name)
        add_site(
            MockCategory.SQL,
            "SQL",
            match_text=normalize_exec_text(sql_text),
        )
        return

    if isinstance(statement, ExecCicsStatement):
        if is_handle_declaration(statement):
            # HANDLE/IGNORE CONDITION registers a label, it is not a
            # boundary: spliced to CONTINUE, its jumps emulated after the
            # mocked commands that raise a condition (issue #268).
            add_site(MockCategory.CICS, "CICS HANDLE", into=surface.whenever_sites)
            return
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
        full_target = " ".join((statement.target or "").upper().split())
        # Keyed on the data-name alone, like a dynamic CALL's identifier:
        # `ACCEPT WS-ENT(WS-I)` / `ACCEPT FLD OF REC-B` kept the subscript or
        # qualifier in the key, which `MOCK ACCEPT <name>` cannot express
        # (issue #311). The full text stays on the site for the scaffold's
        # `MOVE SPACES TO <target>` body.
        target = accept_key(full_target)
        # cobolparser keeps a date-format qualifier in `from_source`
        # (`ACCEPT X FROM DATE YYYYMMDD` -> "DATE YYYYMMDD", `FROM DAY
        # YYYYDDD` -> "DAY YYYYDDD"), so the source is its first word --
        # compared whole, that very common idiom read as console input and
        # refused UNMOCKED_CONSOLE_ACCEPT.
        source_words = str(statement.from_source or "").upper().split()
        source = source_words[0] if source_words else None
        if source not in _NON_INTERACTIVE_ACCEPT_SOURCES:
            surface.console_accept_paragraphs.add(paragraph_name)
            site = add_site(
                MockCategory.ACCEPT, "ACCEPT", keys=(target,) if target else ()
            )
            site.accept_target = full_target or None
        elif target:
            # Not a boundary site (nothing to mock), but recorded so a
            # MOCK ACCEPT aimed at it can be refused with the real reason
            # instead of a generic "not reachable" -- see
            # NonInteractiveAccept.
            surface.non_interactive_accepts.append(
                NonInteractiveAccept(
                    target=target,
                    from_source=str(statement.from_source),
                    paragraph_name=paragraph_name,
                    line=line,
                    statement=statement,
                    nested=nested,
                    nested_in_boundary=in_boundary,
                )
            )
        return

    if type(statement).__name__ not in _PASSTHROUGH_STATEMENT_NAMES:
        # Fail closed: a statement class no branch above claimed and this
        # module has not verified as side-effect free. Never silently
        # passed through -- see _PASSTHROUGH_STATEMENT_NAMES.
        verb = getattr(statement, "statement_type", None) or type(statement).__name__
        add_site(None, UNSUPPORTED_STATEMENT_LABEL, keys=(str(verb),))


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


def _mark_dynamic_mq_calls(program: CobolProgram, surface: MockSurface) -> None:
    """Set `BoundarySite.mq_target` on each dynamic CALL that can only reach
    MQI entry points (`CALL WS-MQGET USING ...` with WS-MQGET VALUE
    'MQGET', the usual IBM sample style): the splicer then answers it
    MQCC_OK / MQRC_NONE like a static MQ call. The targets come from
    cobol-parser's `DynamicCallAnalyzer` (VALUE clauses and MOVEs of
    literals); an incomplete or mixed list leaves the site an ordinary
    dynamic CALL."""
    sites = [
        site
        for site in surface.boundary_sites
        if site.category is MockCategory.DYNCALL and site.keys
    ]
    if not sites:
        return
    try:
        from cobolparser.analysis.value_tracker import DynamicCallAnalyzer

        DynamicCallAnalyzer().analyze(program)
    except Exception:  # noqa: BLE001 -- an analysis gap only loses the default
        return
    for site in sites:
        statement = site.statement
        get_metadata = getattr(statement, "get_metadata", None)
        if get_metadata is not None and get_metadata("possible_values_incomplete"):
            continue
        names = {
            str(value).strip(" '\"\x00\xff").upper()
            for value in getattr(statement, "possible_values", None) or []
        }
        names.discard("")
        if names and names <= MQ_API_NAMES:
            site.mq_target = True


def analyze(program: CobolProgram) -> MockSurface:
    """Walk PROCEDURE DIVISION and classify every CALL/file-IO/EXEC/ACCEPT
    statement into per-site `BoundarySite` records (plus the v1 paragraph
    sets).

    Recurses into nested statement bodies (IF/EVALUATE branches, inline
    PERFORM, IO AT END/INVALID KEY clauses, CALL exception handlers) so that
    e.g. a CALL hidden inside an IF is not missed.
    """
    surface = MockSurface(data_layout=data_layout(program))
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return surface

    for paragraph in _all_paragraphs(procedure):
        _walk_statements(paragraph.statements, paragraph.paragraph_name, surface)

    selects = file_selects(program)
    surface.file_selects = selects
    from mockymock.analysis.declaratives import declarative_paragraphs, use_procedures

    surface.use_procedures = use_procedures(program)
    surface.declarative_names = frozenset(declarative_paragraphs(program))
    from mockymock.analysis.alter import alter_reset_lines

    surface.alter_resets = tuple(alter_reset_lines(program))
    for site in surface.boundary_sites:
        if site.category is MockCategory.READ:
            site.read_form = read_form_of(site.statement, selects)
        elif site.category is MockCategory.OPEN:
            site.open_modes = open_modes_of(site.statement)

    _mark_dynamic_mq_calls(program, surface)

    states = handle_states(program)
    if states:
        for site in surface.boundary_sites:
            if site.category is MockCategory.CICS:
                site.cics_handle_state = states.get(id(site.statement), {})

    if surface.whenever_sites:
        actions = whenever_actions(program)
        for site in surface.boundary_sites:
            if site.category is MockCategory.SQL:
                site.whenever_checks = actions.get(id(site.statement), ())

    return surface


def promote_clock_accepts(surface: MockSurface, mocks) -> list[BoundarySite]:
    """Make every clock ACCEPT (`ACCEPT x FROM DATE/TIME/DAY/DAY-OF-WEEK`)
    that a MOCK ACCEPT in `mocks` names an opt-in boundary site (issue
    #240), and return the new sites.

    Such an ACCEPT reads the system clock, so a test asserting on anything
    derived from it passes only on the day (or second) it was recorded.
    Mocking it gives the test a fixed clock. Opt-in, so a program whose
    tests never name one is spliced exactly as before: an unmocked case
    runs the real statement through the dispatch's WHEN OTHER instead of
    being refused UNMOCKED_CONSOLE_ACCEPT."""
    named = {
        directive.key.upper()
        for directive in mocks
        if directive.category is MockCategory.ACCEPT
    }
    promoted: list[BoundarySite] = []
    kept: list[NonInteractiveAccept] = []
    for accept in surface.non_interactive_accepts:
        if not (accept.reads_clock and accept.target in named):
            kept.append(accept)
            continue
        promoted.append(
            BoundarySite(
                category=MockCategory.ACCEPT,
                label="ACCEPT",
                keys=(accept.target,),
                match_text=None,
                paragraph_name=accept.paragraph_name,
                line=accept.line,
                nested=accept.nested,
                statement=accept.statement,
                nested_in_boundary=accept.nested_in_boundary,
                opt_in=True,
                # Keyed on the bare data-name like a console ACCEPT; the
                # whole target, subscript included, rides along (#311).
                accept_target=" ".join(
                    str(getattr(accept.statement, "target", "") or "").upper().split()
                )
                or None,
            )
        )
    surface.non_interactive_accepts = kept
    surface.boundary_sites.extend(promoted)
    surface.boundary_sites.sort(key=lambda site: site.line)
    return promoted


@dataclass(frozen=True)
class FileSelect:
    """What a SELECT says about how a file is read: organization, access
    mode and its keys (uppercased; None/empty when not given)."""

    organization: str | None
    access_mode: str | None
    record_key: str | None
    alternate_keys: tuple[str, ...]
    relative_key: str | None

    @property
    def keyed(self) -> bool:
        """An indexed (KSDS) or relative (RRDS) file a READ without NEXT or
        PREVIOUS reads by key: its access is RANDOM or DYNAMIC."""
        return self.organization in ("INDEXED", "RELATIVE") and (
            self.access_mode in ("RANDOM", "DYNAMIC")
        )


def file_selects(program: CobolProgram) -> dict[str, FileSelect]:
    """Every SELECT of the program, by uppercased file name."""
    selects: dict[str, FileSelect] = {}
    environment = program.get_division("ENVIRONMENT")
    if environment is None:
        return selects
    io_section = environment.get_section_by_name("INPUT-OUTPUT")
    if not isinstance(io_section, CobolSection):
        return selects
    file_control = io_section.get_paragraph_by_name("FILE-CONTROL")
    if file_control is None:
        return selects

    def upper(value: object) -> str | None:
        return str(value).upper() if value else None

    for statement in file_control.statements:
        if not isinstance(statement, SelectStatement) or not statement.file_name:
            continue
        alternates = tuple(
            str(entry.get("key")).upper()
            for entry in getattr(statement, "alternate_keys", None) or []
            if isinstance(entry, dict) and entry.get("key")
        )
        selects[statement.file_name.upper()] = FileSelect(
            organization=upper(getattr(statement, "organization", None)),
            access_mode=upper(getattr(statement, "access_mode", None)),
            record_key=upper(getattr(statement, "record_key", None)),
            alternate_keys=alternates,
            relative_key=upper(getattr(statement, "relative_key", None)),
        )
    return selects


def read_form_of(statement: object, selects: dict[str, FileSelect]) -> str:
    """The access form of one READ: `NEXT` (READ NEXT, or any READ of a
    file read sequentially), `PREVIOUS`, `KEY` (a random READ of an
    indexed or relative file by its record or relative key) or `KEY
    <name>` (`READ ... KEY IS <alternate key>`)."""
    mode = str(getattr(statement, "access_mode", None) or "").upper()
    if mode in ("NEXT", "PREVIOUS"):
        return mode
    file_name = str(getattr(statement, "file_name", None) or "").upper()
    select = selects.get(file_name)
    key_name = str(getattr(statement, "key_name", None) or "").upper()
    if select is None or not select.keyed:
        return "NEXT"
    if key_name and key_name != select.record_key:
        return f"KEY {key_name}"
    return "KEY"


def open_modes_of(statement: object) -> dict[str, str]:
    """The mode each file of an OPEN is opened in (`OPEN INPUT A OUTPUT B`
    -> `{"A": "INPUT", "B": "OUTPUT"}`), by uppercased file name."""
    per_file = getattr(statement, "file_modes", None) or {}
    modes = {str(name).upper(): str(mode).upper() for name, mode in per_file.items()}
    default = str(getattr(statement, "open_mode", None) or "").upper()
    for name in getattr(statement, "file_names", None) or []:
        if name and default:
            modes.setdefault(str(name).upper(), default)
    return modes


def analyze_file_status_fields(program: CobolProgram) -> dict[str, str]:
    """Uppercased file name -> its declared `FILE STATUS IS <field>` name
    (qualified, `FS-CODE OF CUST-STAT`, when the clause qualifies it), read from the ENVIRONMENT DIVISION's FILE-CONTROL SELECT statements. A
    file whose SELECT entry has no FILE STATUS clause has no entry -- there
    is no WORKING-STORAGE field to default or target with FILE-STATUS IS
    sugar (see docs/2026-07-20-before-blocks-and-file-status-design.md).

    Every record (01) declared under such a file's FD maps to the same
    field, keyed by its own uppercased name: a WRITE/REWRITE site and its
    MOCK key on the record, not the file, and a mocked WRITE/REWRITE must
    set the status like the real statement does (issue #221). COBOL file
    names and data names share one namespace, so the keys cannot clash."""
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
            # `FILE STATUS IS FS-CODE OF CUST-STAT`: keep the qualifiers, or
            # every generated MOVE to a status field declared under several
            # groups (one copybook, many files) is ambiguous (issue #266).
            qualifiers = getattr(statement, "file_status_qualifiers", None) or []
            fields[statement.file_name.upper()] = " OF ".join(
                [statement.file_status, *qualifiers]
            )
    for record, file_name in _fd_records(program):
        status = fields.get(file_name)
        if status and record not in fields:
            fields[record] = status
    return fields


def _fd_records(program: CobolProgram) -> list[tuple[str, str]]:
    """(uppercased record name, uppercased FD file name) for every 01
    declared under an FD/SD."""
    data = program.get_division("DATA")
    if data is None:
        return []
    records: list[tuple[str, str]] = []
    for section in getattr(data, "sections", data.children):
        for item in getattr(section, "children", []):
            if getattr(item, "level", None) != 1:
                continue
            metadata = getattr(item, "_metadata", None) or {}
            file_name = str(metadata.get("fd_file_name") or "").upper()
            name = str(getattr(item, "name", "") or "").upper()
            if file_name and name and name != "FILLER":
                records.append((name, file_name))
    return records


def _all_paragraphs(procedure_division: CobolDivision) -> list[CobolParagraph]:
    """Mirrors CoverageAnalyzer._analyze_paragraphs's traversal pattern."""
    paragraphs = list(procedure_division.paragraphs)
    for section in procedure_division._sections.values():
        paragraphs.extend(section.paragraphs)
    return paragraphs
