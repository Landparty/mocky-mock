"""Builds the EVALUATE UT-CURRENT-CASE dispatch block spliced over one
mocked boundary site -- necessary because all TESTCASEs in a suite share
one compiled binary and therefore one physical copy of each mocked
statement (see Global Constraints: one binary per TESTSUITE).

Dispatch is built per SITE, not per mock key: different test cases may
match the same statement through different keys (case 1 mocks
`OPEN IN-FILE`, case 2 mocks `OPEN OUT-FILE`, both matching the one
`OPEN INPUT IN-FILE OUTPUT OUT-FILE` statement), so the tally increment
lives inside each case's WHEN branch, crediting that case's own directive.

Also builds the trap stub spliced over *unmocked* EXEC SQL/CICS/DLI sites:
those must be commented out program-wide regardless of reachability (cobc
cannot compile raw EXEC blocks), and if control somehow reaches one the
trap records a failure instead of silently doing nothing.
"""

from __future__ import annotations

import re

from cobolparser.models.statements.call import CallStatement

from mockymock.analysis.cics_handle import label_in_state
from mockymock.analysis.clause_bodies import (
    OUTCOME_FIELD,
    LiftedClause,
    clause_guard_lines,
)
from mockymock.analysis.mock_surface import BoundarySite
from mockymock.analysis.refusal import directive_matches_site
from mockymock.dsl.model import (
    FILE_STATUS_CATEGORIES,
    SEQUENCED_CALL_CATEGORIES,
    SUITE_PHASE_ID,
    MockCategory,
    MockTestSuite,
)
from mockymock.splicer.io_copy import DataLayout, from_move, into_move
from mockymock.splicer.naming import TallyRegistry, assign

#: One token of a CALL statement's text: a (possibly X/N/G/Z/NX/U-prefixed)
#: quoted literal with doubled quotes inside, a parenthesis, a period, or a
#: word/numeric literal.
_CALL_TOKEN_RE = re.compile(
    r"""(?P<lit>(?:NX|[XNGZU])?(?:"(?:[^"]|"")*"|'(?:[^']|'')*'))"""
    r"|(?P<punct>[().,;])"
    r"|(?P<word>[^\s().,;\"']+)",
    re.IGNORECASE,
)
_PERIOD_DECIMAL_RE = re.compile(r"^([+-]?\d*)\.(\d+)$")
_USING_END_WORDS = frozenset(
    {"RETURNING", "GIVING", "ON", "NOT", "EXCEPTION", "OVERFLOW", "END-CALL"}
)
_PASSING_WORDS = frozenset({"BY", "REFERENCE", "CONTENT", "VALUE"})
_QUALIFIERS = frozenset({"OF", "IN"})
_ADDRESS_WORDS = frozenset({"ADDRESS", "LENGTH"})


def _literal_inner(token: str) -> str:
    """The value cobolparser reports for a quoted literal token: prefix and
    quotes removed, doubled quotes collapsed."""
    start = token.index(token[-1])
    quote = token[-1]
    return token[start + 1 : -1].replace(quote * 2, quote)


def _operand_key(text: str) -> str:
    """An operand's text for comparison with cobolparser's name for it,
    which spaces out subscripts differently (`WS-ENT ( WS-I )`, `WS-I ( 1
    : 1 )`): whitespace and subscript commas dropped, uppercased."""
    return re.sub(r"[\s,]+", "", text.upper())


def _call_using_literals(statement_text: str, names: list[str]) -> list[str | None]:
    """Per USING operand of the CALL in `statement_text`, the operand's own
    literal token verbatim (quotes, prefix and all) when it is a quoted
    literal, else None.

    cobolparser reports a literal argument by its value with the quotes
    stripped (`CALL "X" USING BY CONTENT "ABC"` -> name `ABC`), which is
    indistinguishable from a data-name -- so a `CAPTURE ARG` of it emitted
    `MOVE ABC TO target`: a compile error, or worse a silent MOVE of an
    unrelated item that happens to be called ABC. The text is re-scanned
    here and trusted only when it agrees with the parser operand for
    operand (`names`); any disagreement yields all-None, i.e. today's
    behavior, never a guess."""
    none: list[str | None] = [None] * len(names)
    tokens = list(_CALL_TOKEN_RE.finditer(statement_text))
    words = [m.group(0) for m in tokens]
    upper = [w.upper() for w in words]
    if "USING" not in upper:
        return none
    i = upper.index("USING") + 1
    operands: list[tuple[str, bool]] = []  # (text, is_literal)
    while i < len(tokens):
        tok, word = tokens[i], upper[i]
        if tok.group("punct") in (".", ";", ","):
            if tok.group("punct") == ".":
                break
            i += 1
            continue
        if tok.group("punct"):
            return none  # a parenthesis not after an operand: unmodelled
        if word in _USING_END_WORDS:
            break
        if word in _PASSING_WORDS:
            i += 1
            continue
        if tok.group("lit"):
            operands.append((words[i], True))
            i += 1
            continue
        text = words[i]
        if word in _ADDRESS_WORDS and i + 2 < len(tokens) and upper[i + 1] == "OF":
            text = f"{words[i]} OF {words[i + 2]}"
            i += 3
        else:
            i += 1
        while i + 1 < len(tokens) and upper[i] in _QUALIFIERS:
            text = f"{text} {words[i]} {words[i + 1]}"
            i += 2
        # A subscript and/or reference modification belongs to the operand
        # (`WS-ENT(WS-I)`, `WS-A(1:2)`): consume each balanced group. This
        # scan used to give up on any parenthesis, so a literal next to a
        # subscripted operand was captured as a data-name (issue #291).
        while i < len(tokens) and tokens[i].group("punct") == "(":
            depth = 0
            while i < len(tokens):
                punct = tokens[i].group("punct")
                depth += punct == "("
                depth -= punct == ")"
                text = f"{text} {words[i]}"
                i += 1
                if depth == 0:
                    break
            if depth:
                return none  # unbalanced: not a shape this scan models
        operands.append((text, False))
    if len(operands) != len(names):
        return none
    result: list[str | None] = []
    for (text, is_literal), name in zip(operands, names, strict=True):
        if is_literal:
            if _literal_inner(text) != name:
                return none
            result.append(text)
        else:
            if _operand_key(text) != _operand_key(name):
                return none
            result.append(None)
    return result


def build_rows_block(
    tally_name: str,
    rows: list[list[tuple[str, str]]],
    *,
    row_suffix_moves: list[str],
    exhausted_moves: list[str],
    row_prefix_moves: list[str] | None = None,
) -> list[str]:
    """EVALUATE block for a MOCK SQL/READ/RETURN ... ROWS directive: row
    N's MOVEs fire once `tally_name` (already incremented by the caller
    before this runs, so the first call sees tally == 1) reaches N,
    followed by `row_suffix_moves` (already-formed MOVE lines appended
    after every row -- `[]` for SQL rows (see `row_prefix_moves`) and for
    READ/RETURN rows, whose implicit default-success MOVE, when one
    exists, already precedes the whole block, see build_site_dispatch);
    once rows are exhausted, `exhausted_moves` fires instead (SQL:
    `["MOVE 100 TO SQLCODE"]`, DB2's real "not found" code; READ/RETURN:
    the resolved end-of-data signal -- either the mock's own TERMINAL
    group or, for READ only, a default `MOVE "10" TO <status field>` --
    RETURN is never in FILE_STATUS_CATEGORIES, so its TERMINAL group is
    the only source; CALL/DYNCALL/DLI: their mandatory TERMINAL group,
    with `[]` row suffixes).

    `row_prefix_moves` fire before each row's own MOVEs: an implicit
    default the row may override (SQL's `MOVE 0 TO SQLCODE`, so a row
    giving `SQLCODE = -305` keeps it), where a suffix would overwrite it."""
    lines = ["EVALUATE TRUE"]
    for index, row in enumerate(rows, start=1):
        lines.append(f"    WHEN {tally_name} = {index}")
        for move in row_prefix_moves or []:
            lines.append(f"        {move}")
        for field, value in row:
            lines.append(f"        {assign(value, field)}")
        for move in row_suffix_moves:
            lines.append(f"        {move}")
    lines.append("    WHEN OTHER")
    for move in exhausted_moves:
        lines.append(f"        {move}")
    lines.append("END-EVALUATE")
    return lines


def dispatch_entries(suite: MockTestSuite) -> list[tuple[str, list]]:
    """(UT-CURRENT-CASE value, mocks in force) for every WHEN branch a
    dispatch block may need: one per test case, plus the suite phase
    (BEFORE-ALL/AFTER-ALL steps, answered by BEFORE-ALL's mocks) when the
    suite has one -- see docs/2026-10-10-suite-hooks-design.md."""
    entries: list[tuple[str, list]] = [
        (f"{index:03d}", case.mocks)
        for index, case in enumerate(suite.test_cases, start=1)
    ]
    if suite.has_suite_phase:
        entries.append((SUITE_PHASE_ID, suite.before_all_mocks))
    return entries


def build_site_dispatch(
    site: BoundarySite,
    suite: MockTestSuite,
    registry: TallyRegistry,
    file_status_fields: dict[str, str] | None = None,
    trace: bool = False,
    statement_text: str = "",
    layout: DataLayout | None = None,
    lifted_clauses: tuple[LiftedClause, ...] | None = None,
    sqlstate: bool = False,
) -> list[str]:
    """EVALUATE block replacing one mocked boundary statement.

    `sqlstate` (issue #313): the program references SQLSTATE, so a `MOCK
    SQL ... ROWS` row also reports `"00000"` and its exhaustion `"02000"`
    -- a cursor loop ended by `UNTIL SQLSTATE = '02000'` never ended on
    SQLCODE alone. Off when the program never names SQLSTATE: its own
    SQLCA copy may not declare one.

    `lifted_clauses` (issue #209, `analysis.clause_bodies`): the replaced
    statement's own AT END / NOT AT END / INVALID KEY / NOT INVALID KEY /
    ON EXCEPTION / NOT ON EXCEPTION bodies. When given, every matching
    case's branch records the mocked outcome in `UT-MOCK-STATUS` -- "00"
    first, "10" once a ROWS mock is exhausted, and the file's own FILE
    STATUS field's value last when it declares one -- and an `EVALUATE`
    after the dispatch runs the clause that outcome selects, exactly as
    the real statement would have. The mock body may set `UT-MOCK-STATUS`
    itself (`"10"`, `"23"`, `"EX"` for a CALL's ON EXCEPTION) for a file
    with no FILE STATUS field or a CALL. An unmocked case's trap leaves it
    at SPACES, which selects no clause.

    `READ ... INTO` / `RETURN ... INTO` and `WRITE`/`REWRITE`/`RELEASE ...
    FROM` keep their implicit MOVE (`splicer.io_copy`, issue #149): the FROM
    item is moved to the record before the body runs, and the record to
    the INTO item after each row (or after the body) -- unless the mock
    writes the INTO item itself.

    For a file-op directive in FILE_STATUS_CATEGORIES whose file declares
    a FILE STATUS field (`file_status_fields`), the branch always starts
    with an implicit `MOVE "00"` (default success) before the directive's
    own body; an explicit FILE-STATUS IS (`directive.file_status`) follows
    it and therefore wins, same as any hand-written MOVE the author adds
    after it -- see docs/2026-07-20-before-blocks-and-file-status-design.md.

    A directive with CAPTURE ARG <n> INTO <target> entries (CALL/DYNCALL
    only) emits one `MOVE <real using-parameter name> TO <target>` line
    per entry, resolved against this exact site's own
    CallStatement.using_parameters -- before directive.body_lines, so a
    capture always reflects the value the real caller passed, never
    something an earlier body line might otherwise have overwritten it
    with. See docs/2026-08-11-argument-capture-design.md.

    A `MOCK READ ... ROWS` or `MOCK RETURN ... ROWS` directive's exhaustion
    (`WHEN OTHER`) branch follows the SAME implicit-default-then-explicit-
    override ordering as the FILE-STATUS default-success MOVE above: when
    the file declares a status field it always starts with the implicit
    `MOVE "10" TO <status field>` (COBOL's real end-of-file code), and the
    directive's own `TERMINAL ( ... )` group's MOVEs -- when present --
    are appended right after, so an author's own MOVE to that same field
    naturally wins by coming later in the same WHEN branch, exactly like a
    hand-written MOVE would. A TERMINAL group that never mentions the
    status field no longer leaves it stuck at whatever the default-success
    `MOVE "00"` set on the call that triggered this WHEN OTHER path -- it
    gets the correct "10" instead. If the file has no status field, only
    the TERMINAL group's own MOVEs fire (there is no field to default) --
    this is always true for RETURN (not in FILE_STATUS_CATEGORIES, see
    dsl/model.py), so a `MOCK RETURN ... ROWS` needs its own TERMINAL
    group unconditionally. If NEITHER a status field nor a TERMINAL group
    is available this raises ValueError rather than emit a READ/RETURN
    loop with no way to terminate -- every production call site gates on
    `refusal.check_test_case` (UNRESOLVED_FILE_STATUS_TARGET) first, using
    this same `file_status_fields` dict, so that should be unreachable in
    practice.
    """
    file_status_fields = file_status_fields or {}
    lines = []
    if lifted_clauses:
        lines.append(f"           MOVE SPACES TO {OUTCOME_FIELD}")
    lines.append("           EVALUATE UT-CURRENT-CASE")

    for case_id, mocks in dispatch_entries(suite):
        matches = [d for d in mocks if directive_matches_site(d, site)]
        if len(matches) > 1:
            raise ValueError(
                f"site at line {site.line} matched by multiple directives of "
                f"test case {case_id} -- refusal gate should have caught this "
                f"(AMBIGUOUS_MOCK)"
            )
        if not matches:
            continue
        directive = matches[0]
        tally_name = registry.name(directive.category, directive.key)
        lines.append(f'               WHEN "{case_id}"')
        lines.append(f"                   ADD 1 TO {tally_name}")
        if trace:
            # Mock firing ORDER cannot be recovered from the GnuCOBOL trace
            # file: this dispatch block is splicer-inserted, and the trace's
            # instrumented->original line remap drops inserted lines by
            # design (that exclusion is what makes it mean "which of MY
            # lines ran"). Emitting on the __MOCKYMOCK__ stdout channel
            # instead places each firing between the driver's CASE
            # START/END markers, so per-case attribution comes for free.
            #
            # site.label alone is only a coarse verb ("OPEN", "CALL"), which
            # renders two OPENs of different files indistinguishable in the
            # timeline. directive.key is what the author actually wrote in
            # the .cut, so the pair names the firing unambiguously and
            # points straight back at the directive that caused it.
            lines.append(
                f'                   DISPLAY "__MOCKYMOCK__ MOCK: '
                f'{site.label} {directive.key}"'
            )
        if lifted_clauses:
            lines.append(f'                   MOVE "00" TO {OUTCOME_FIELD}')
        if directive.category in FILE_STATUS_CATEGORIES:
            # A statement naming several files (`OPEN INPUT A OUTPUT B`,
            # `CLOSE A B`) is one site matched by ONE directive (a second
            # would be AMBIGUOUS_MOCK), so the default success must cover
            # every file it names -- defaulting only the directive's own
            # file left the other file's status at its reset value, and a
            # program checking both statuses took its failure branch.
            default_fields = dict.fromkeys(
                field
                for field in (
                    file_status_fields.get(key.upper())
                    for key in [directive.key, *site.keys]
                )
                if field
            )
            for default_field in default_fields:
                lines.append(f'                   MOVE "00" TO {default_field}')
            status_field = file_status_fields.get(directive.key.upper())
            if status_field and directive.file_status is not None:
                lines.append(
                    f'                   MOVE "{directive.file_status}" '
                    f"TO {status_field}"
                )
        if directive.captures:
            if not isinstance(site.statement, CallStatement):
                raise ValueError(
                    f"MOCK {directive.describe()} has CAPTURE ARG entries "
                    f"but the site at line {site.line} is not a CALL "
                    f"statement -- refusal gate should have caught this "
                    f"(CAPTURE_ARG_OUT_OF_RANGE)"
                )
            using = site.statement.using_parameters
            # A literal argument must be moved as that literal, not as the
            # quote-stripped name cobolparser reports -- see
            # `_call_using_literals`. `statement_text` is the site's own
            # spliced span.
            literals = _call_using_literals(
                statement_text, [str(param.name) for param in using]
            )
            for capture_index, target in directive.captures:
                if capture_index > len(using):
                    raise ValueError(
                        f"MOCK {directive.describe()} CAPTURE ARG "
                        f"{capture_index} exceeds {len(using)} USING "
                        f"parameter(s) at line {site.line} -- refusal "
                        f"gate should have caught this "
                        f"(CAPTURE_ARG_OUT_OF_RANGE)"
                    )
                source = literals[capture_index - 1] or using[capture_index - 1].name
                # cobol-parser reports `USING 1,25` as `1.25` whatever the
                # program's DECIMAL-POINT; under DECIMAL-POINT IS COMMA the
                # period form is a sentence end (issue #230). The site's own
                # text says which spelling the program uses.
                comma_form = _PERIOD_DECIMAL_RE.sub(r"\1,\2", str(source))
                if comma_form != source and comma_form in statement_text:
                    source = comma_form
                lines.append(f"                   MOVE {source} TO {target}")
        copy_from = from_move(site.statement)
        if copy_from is not None:
            lines.append(f"                   {copy_from}")
        copy_into = into_move(
            site.statement,
            layout,
            [
                *directive.body_lines,
                *(name for row in directive.rows or [] for name, _ in row),
                *(name for name, _ in directive.terminal_row or []),
            ],
            file_status_fields.get(directive.key.upper()),
        )
        if directive.rows is not None and directive.category in (
            MockCategory.READ,
            MockCategory.RETURN,
        ):
            status_field = file_status_fields.get(directive.key.upper())
            if directive.terminal_row is None and status_field is None:
                raise ValueError(
                    "refusal gate should have caught this "
                    "(UNRESOLVED_FILE_STATUS_TARGET)"
                )
            # Implicit default first, explicit override after -- same
            # ordering principle as the FILE-STATUS default-success MOVE
            # above (lines ~118-124). Without the default here, a TERMINAL
            # group that sets an EOF flag but never mentions the status
            # field would leave that field at whatever "00" the
            # default-success MOVE set on the call that triggered this
            # WHEN OTHER path -- an EOF flag/status-field inconsistency a
            # program checking both would see.
            exhausted_moves: list[str] = []
            if lifted_clauses:
                exhausted_moves.append(f'MOVE "10" TO {OUTCOME_FIELD}')
            if status_field is not None:
                exhausted_moves.append(f'MOVE "10" TO {status_field}')
            if directive.terminal_row is not None:
                exhausted_moves.extend(
                    assign(value, field) for field, value in directive.terminal_row
                )
            lines.extend(
                f"                   {body}"
                for body in build_rows_block(
                    tally_name,
                    directive.rows,
                    row_suffix_moves=[copy_into] if copy_into else [],
                    exhausted_moves=exhausted_moves,
                )
            )
        elif (
            directive.rows is not None
            and directive.category in SEQUENCED_CALL_CATEGORIES
        ):
            # Per-invocation sequencing: row N answers this key's Nth call
            # in the case (the tally counts every site the key matches),
            # TERMINAL answers every call after the last row. There is no
            # implicit end-of-data value to default to, so the parser makes
            # TERMINAL mandatory -- reaching here without one is a bug.
            if directive.terminal_row is None:
                raise ValueError(
                    f"MOCK {directive.describe()} ROWS has no TERMINAL "
                    f"group -- the parser should have rejected it"
                )
            lines.extend(
                f"                   {body}"
                for body in build_rows_block(
                    tally_name,
                    directive.rows,
                    row_suffix_moves=[],
                    exhausted_moves=[
                        assign(value, field) for field, value in directive.terminal_row
                    ],
                )
            )
        elif directive.rows is not None:
            lines.extend(
                f"                   {body}"
                for body in build_rows_block(
                    tally_name,
                    directive.rows,
                    # Before the row's own MOVEs, not after: a row that
                    # sets SQLCODE itself (an error mid-cursor) must win.
                    row_prefix_moves=["MOVE 0 TO SQLCODE"]
                    + (['MOVE "00000" TO SQLSTATE'] if sqlstate else []),
                    row_suffix_moves=[],
                    exhausted_moves=["MOVE 100 TO SQLCODE"]
                    + (['MOVE "02000" TO SQLSTATE'] if sqlstate else []),
                )
            )
        else:
            lines.extend(f"                   {body}" for body in directive.body_lines)
            if copy_into is not None:
                lines.append(f"                   {copy_into}")
            if directive.cics_condition:
                # `CONDITION IS X`: the command raised X, so control goes
                # where EXEC CICS HANDLE CONDITION sent it (issue #268); an
                # IGNOREd condition does nothing. A condition no handler
                # covers was refused by lint (UNSUPPORTED_CICS_CONDITION).
                label, _ = label_in_state(
                    site.cics_handle_state, directive.cics_condition
                )
                if label:
                    lines.append(f"                   GO TO {label}")
        if lifted_clauses:
            outcome_status = file_status_fields.get(directive.key.upper())
            if outcome_status and directive.category in FILE_STATUS_CATEGORIES:
                lines.append(
                    f"                   MOVE {outcome_status} TO {OUTCOME_FIELD}"
                )

    lines.append("               WHEN OTHER")
    lines.append(
        f'                   DISPLAY "__MOCKYMOCK__ ERROR: {site.label} '
        f'boundary (line {site.line}) reached "'
    )
    lines.append('                       "from unmocked test case " UT-CURRENT-CASE')
    lines.append("                   ADD 1 TO UT-FAIL-COUNT")
    lines.append("           END-EVALUATE")
    if lifted_clauses:
        lines.extend(
            f"           {line}" for line in clause_guard_lines(lifted_clauses)
        )
    return lines


def build_flow_dispatch(
    plan, suite: MockTestSuite, registry: TallyRegistry, trace: bool = False
) -> list[str]:
    """Replacement for a flow-mocked paragraph/section HEADER line (MOCK
    PARAGRAPH/SECTION): re-emit the header, dispatch on UT-CURRENT-CASE --
    each mocking case gets its tally increment plus its mock body; every
    other case runs the real, relocated body via WHEN OTHER -- then open
    the relocated real paragraph/section (`plan.real_name`). Only the
    header line is replaced; the original body lines stay exactly where
    they were, now belonging to `plan.real_name`, so every other
    line-number-derived splice inside the body stays valid. Unlike
    build_site_dispatch, WHEN OTHER is NOT an error trap: an unmocked
    paragraph/section is ordinary code that must keep running for cases
    that don't mock it."""
    suffix = " SECTION" if plan.is_section else ""
    lines = [
        f"       {plan.key}{suffix}.",
        "           EVALUATE UT-CURRENT-CASE",
    ]
    for case_id, mocks in dispatch_entries(suite):
        matches = [
            d for d in mocks if d.category is plan.category and d.key == plan.key
        ]
        if not matches:
            continue
        directive = matches[0]
        tally_name = registry.name(directive.category, directive.key)
        lines.append(f'               WHEN "{case_id}"')
        lines.append(f"                   ADD 1 TO {tally_name}")
        if trace:
            # A MOCK PARAGRAPH/SECTION is a mock the author declared, so it
            # belongs in the firing timeline alongside boundary mocks --
            # omitting it would make the timeline quietly incomplete.
            lines.append(
                f'                   DISPLAY "__MOCKYMOCK__ MOCK: '
                f'{"SECTION" if plan.is_section else "PARAGRAPH"} {plan.key}"'
            )
        lines.extend(f"                   {body}" for body in directive.body_lines)
    lines.append("               WHEN OTHER")
    lines.append(f"                   PERFORM {plan.real_name}")
    lines.append("           END-EVALUATE.")
    lines.append(f"       {plan.real_name}{suffix}.")
    return lines


def build_exec_trap(kind: str, line: int) -> list[str]:
    """Replacement for an EXEC site no test case mocks. It still has to be
    commented out for the program to compile at all; this trap makes an
    unexpected execution a loud failure instead of a silent no-op."""
    return [
        f'           DISPLAY "__MOCKYMOCK__ ERROR: unmocked EXEC {kind} '
        f'reached (line {line})"',
        "           ADD 1 TO UT-FAIL-COUNT",
    ]


def build_terminator_neutralization(
    exit_kind: str = "PARAGRAPH", return_code: str | None = None
) -> list[str]:
    """Replacement for a STOP RUN/GOBACK statement found safe to
    neutralize (see docs/2026-07-08-goback-stop-run-support-design.md):
    set the early-exit flag and return via EXIT PARAGRAPH/EXIT SECTION --
    never GO TO, since these are the only mechanisms verified to
    correctly resume the real PERFORM caller. `exit_kind` is
    `TerminatorPlan.exit_kind` -- "PARAGRAPH" (the default) for the
    ordinary case, or "SECTION" for the one SECTION-scoped shape
    docs/2026-07-10-section-scoped-terminator-support-design.md
    supports. Identical regardless of which test case is running --
    unlike build_site_dispatch, no per-case EVALUATE UT-CURRENT-CASE
    dispatch is needed here. `return_code` is `TerminatorPlan.return_code`,
    the operand of a `STOP RUN RETURNING n` / `GOBACK RETURNING n` the
    replacement would otherwise drop (issue #219): it is MOVEd to
    RETURN-CODE first, as the real statement would have set it."""
    lines = []
    if return_code is not None:
        lines.append(f"           MOVE {return_code} TO RETURN-CODE")
    return lines + [
        '           MOVE "Y" TO UT-EARLY-EXIT',
        f"           EXIT {exit_kind}",
    ]


def build_cics_terminator_exit(
    exit_kind: str = "PARAGRAPH", resp_field: str | None = None
) -> tuple[list[str], list[str]]:
    """(prefix, suffix) wrapped around an EXEC CICS RETURN/XCTL/ABEND
    site's own dispatch block when `refusal.find_terminator_plans` planned
    it (issue #215): the mock body runs, then the run under test ends the
    way a neutralized GOBACK does, instead of continuing past a command
    that never gives control back.

    `resp_field` is `TerminatorPlan.resp_field`. With RESP, a failed
    command DOES return control, so the prefix presets the field to 0
    (NORMAL, what a successful command leaves there -- the mock body may
    then set a failure code) and the exit is taken only while it is still
    0."""
    exit_lines = [
        '           MOVE "Y" TO UT-EARLY-EXIT',
        f"           EXIT {exit_kind}",
    ]
    if resp_field is None:
        return [], exit_lines
    return [f"           MOVE 0 TO {resp_field}"], [
        f"           IF {resp_field} = 0",
        *(f"    {line}" for line in exit_lines),
        "           END-IF",
    ]


def build_goto_exit_replacement(exit_kind: str = "PARAGRAPH") -> list[str]:
    """Replacement for a GO TO statement found safe to splice directly
    into EXIT PARAGRAPH/EXIT SECTION at its own call site (see
    docs/2026-08-17-goto-exit-paragraph-simplification-design.md and
    analysis.refusal.GotoExitPlan). Unlike
    build_terminator_neutralization, no UT-EARLY-EXIT flag is set here --
    this transform never propagates through an intermediate PERFORM
    chain, it always ends the SAME paragraph the GO TO already lived in.
    STATUS: implemented, not yet verified against real GnuCOBOL."""
    return [f"           EXIT {exit_kind}"]


def build_chain_check() -> list[str]:
    """Inserted immediately after an intermediate PERFORM statement lying
    on a safe chain toward a neutralized terminator: if the flag is set,
    stop this paragraph too instead of running whatever sibling code
    follows -- propagating the early exit one more level toward the test
    driver. Identical every time it's used; no parameters needed."""
    return [
        '           IF UT-EARLY-EXIT = "Y"',
        "               EXIT PARAGRAPH",
        "           END-IF",
    ]
