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

from mockymock.analysis.mock_surface import BoundarySite
from mockymock.analysis.refusal import directive_matches_site
from mockymock.dsl.model import FILE_STATUS_CATEGORIES, MockCategory, MockTestSuite
from mockymock.splicer.naming import TallyRegistry

#: One token of a CALL statement's text: a (possibly X/N/G/Z/NX/U-prefixed)
#: quoted literal with doubled quotes inside, a parenthesis, a period, or a
#: word/numeric literal.
_CALL_TOKEN_RE = re.compile(
    r"""(?P<lit>(?:NX|[XNGZU])?(?:"(?:[^"]|"")*"|'(?:[^']|'')*'))"""
    r"|(?P<punct>[().,;])"
    r"|(?P<word>[^\s().,;\"']+)",
    re.IGNORECASE,
)
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
            return none  # a subscript/parenthesis this scan does not model
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
            if " ".join(text.upper().split()) != " ".join(name.upper().split()):
                return none
            result.append(None)
    return result


def build_rows_block(
    tally_name: str,
    rows: list[list[tuple[str, str]]],
    *,
    row_suffix_moves: list[str],
    exhausted_moves: list[str],
) -> list[str]:
    """EVALUATE block for a MOCK SQL/READ/RETURN ... ROWS directive: row
    N's MOVEs fire once `tally_name` (already incremented by the caller
    before this runs, so the first call sees tally == 1) reaches N,
    followed by `row_suffix_moves` (already-formed MOVE lines appended
    after every row -- `["MOVE 0 TO SQLCODE"]` for SQL rows; `[]` for
    READ/RETURN rows, whose implicit default-success MOVE, when one
    exists, already precedes the whole block, see build_site_dispatch);
    once rows are exhausted, `exhausted_moves` fires instead (SQL:
    `["MOVE 100 TO SQLCODE"]`, DB2's real "not found" code; READ/RETURN:
    the resolved end-of-data signal -- either the mock's own TERMINAL
    group or, for READ only, a default `MOVE "10" TO <status field>` --
    RETURN is never in FILE_STATUS_CATEGORIES, so its TERMINAL group is
    the only source)."""
    lines = ["EVALUATE TRUE"]
    for index, row in enumerate(rows, start=1):
        lines.append(f"    WHEN {tally_name} = {index}")
        for field, value in row:
            lines.append(f"        MOVE {value} TO {field}")
        for move in row_suffix_moves:
            lines.append(f"        {move}")
    lines.append("    WHEN OTHER")
    for move in exhausted_moves:
        lines.append(f"        {move}")
    lines.append("END-EVALUATE")
    return lines


def build_site_dispatch(
    site: BoundarySite,
    suite: MockTestSuite,
    registry: TallyRegistry,
    file_status_fields: dict[str, str] | None = None,
    trace: bool = False,
    statement_text: str = "",
) -> list[str]:
    """EVALUATE block replacing one mocked boundary statement.

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
    lines = ["           EVALUATE UT-CURRENT-CASE"]

    for index, case in enumerate(suite.test_cases, start=1):
        matches = [d for d in case.mocks if directive_matches_site(d, site)]
        if len(matches) > 1:
            raise ValueError(
                f"site at line {site.line} matched by multiple directives of "
                f"test case {index} -- refusal gate should have caught this "
                f"(AMBIGUOUS_MOCK)"
            )
        if not matches:
            continue
        directive = matches[0]
        tally_name = registry.name(directive.category, directive.key)
        lines.append(f'               WHEN "{index:03d}"')
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
        if directive.category in FILE_STATUS_CATEGORIES:
            status_field = file_status_fields.get(directive.key.upper())
            if status_field:
                lines.append(f'                   MOVE "00" TO {status_field}')
                if directive.file_status is not None:
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
                lines.append(f"                   MOVE {source} TO {target}")
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
            if status_field is not None:
                exhausted_moves.append(f'MOVE "10" TO {status_field}')
            if directive.terminal_row is not None:
                exhausted_moves.extend(
                    f"MOVE {value} TO {field}"
                    for field, value in directive.terminal_row
                )
            lines.extend(
                f"                   {body}"
                for body in build_rows_block(
                    tally_name,
                    directive.rows,
                    row_suffix_moves=[],
                    exhausted_moves=exhausted_moves,
                )
            )
        elif directive.rows is not None:
            lines.extend(
                f"                   {body}"
                for body in build_rows_block(
                    tally_name,
                    directive.rows,
                    row_suffix_moves=["MOVE 0 TO SQLCODE"],
                    exhausted_moves=["MOVE 100 TO SQLCODE"],
                )
            )
        else:
            lines.extend(f"                   {body}" for body in directive.body_lines)

    lines.append("               WHEN OTHER")
    lines.append(
        f'                   DISPLAY "__MOCKYMOCK__ ERROR: {site.label} '
        f'boundary (line {site.line}) reached "'
    )
    lines.append('                       "from unmocked test case " UT-CURRENT-CASE')
    lines.append("                   ADD 1 TO UT-FAIL-COUNT")
    lines.append("           END-EVALUATE")
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
    for index, case in enumerate(suite.test_cases, start=1):
        matches = [
            d for d in case.mocks if d.category is plan.category and d.key == plan.key
        ]
        if not matches:
            continue
        directive = matches[0]
        tally_name = registry.name(directive.category, directive.key)
        lines.append(f'               WHEN "{index:03d}"')
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


def build_terminator_neutralization(exit_kind: str = "PARAGRAPH") -> list[str]:
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
    dispatch is needed here."""
    return [
        '           MOVE "Y" TO UT-EARLY-EXIT',
        f"           EXIT {exit_kind}",
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
