"""Collects and applies every splice for a suite: mocked boundary sites of
all categories get their EVALUATE dispatch block, and unmocked EXEC
SQL/CICS/DLI sites get a trap stub program-wide (GnuCOBOL cannot compile a
raw EXEC block, so reachability is not enough for those).

All spans are computed up front from the original (pre-splice)
boundaries/statement locations, then applied to `lines` in descending
start-line order. Applying bottom-up keeps every not-yet-applied span's
line numbers valid: `comment_and_replace` returns a list that has grown by
`len(replacement)` lines, which would silently shift every later
(higher-line-number) span if splices were applied top-down instead --
verified concretely during Task 14 review: a second top-down splice landed
one line short and commented out the following paragraph's header instead
of its CALL statement.

Nested sites ARE spliced here, at the span `annotate_nested_sites`
validated for them (site.span); the refusal gate guarantees any nested
site that still needs a splice carries one (UNSUPPORTED_NESTED_MOCK_TARGET
/ NESTED_EXEC refuse the unspliceable ones first), and this module raises
if that invariant is violated. Top-level sites get the parallel guard:
`annotate_nested_sites` stamps an `unspliceable_reason` on any top-level
site that does not own its source line(s) (sibling code on the statement's
line -- e.g. a one-line paragraph `P1. CALL "X".` -- would be silently
deleted by the whole-line splice), the gate refuses those
(UNSUPPORTED_MOCK_TARGET_LAYOUT / UNSPLICEABLE_EXEC), and this module
raises if one still arrives. An unmocked nested non-EXEC site is left in
place as before (plain COBOL; if it was reachable the refusal gate already
fired).

Statements are deduped by id(): several BoundarySite entries can reference
one physical statement only via distinct sites in the same paragraph list,
but one statement must get exactly one splice.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence

from mockymock.analysis.clause_bodies import (
    LiftedClause,
    lift_clause_bodies,
    scan_words,
)
from mockymock.analysis.declaratives import MODE_CODES, USE_GUARD
from mockymock.analysis.flow_mocks import FlowMockPlan
from mockymock.analysis.mock_surface import ANSWERED_LABELS, BoundarySite, MockSurface
from mockymock.analysis.refusal import (
    GotoExitPlan,
    TerminatorPlan,
    directive_matches_site,
)
from mockymock.analysis.sql_whenever import whenever_check_lines
from mockymock.dsl.model import EXEC_CATEGORIES, MockCategory, MockTestSuite
from mockymock.splicer.behaviour import cursor_host_variables
from mockymock.splicer.cics_resp import EIB_RESP_NAMES
from mockymock.splicer.file_keys import rewrite_foreign_record_keys
from mockymock.splicer.injector import (
    build_chain_check,
    build_cics_terminator_exit,
    build_exec_trap,
    build_flow_dispatch,
    build_goto_exit_replacement,
    build_site_dispatch,
    build_terminator_neutralization,
    build_unmocked_trap,
    prefix_loop_conditions,
)
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.source_map import boundary_parents, statement_span
from mockymock.splicer.stub_writer import comment_and_replace, insert_lines_after


def _code_text(line: str) -> str:
    """`line` with any `*>` comment (outside a quoted literal) cut off:
    what the compiler actually reads on it."""
    quote: str | None = None
    for index, char in enumerate(line):
        if quote is not None:
            if char == quote:
                quote = None  # a doubled quote just re-enters on the next char
        elif char in "'\"":
            quote = char
        elif line.startswith("*>", index):
            return line[:index]
    return line


def _span_ends_sentence(lines: list[str], start: int, end: int) -> bool:
    """True when the last code on lines [start, end] (1-indexed, inclusive)
    ends with a period, i.e. the replaced statement closed its sentence.

    Judged on code only: `CALL "X". *> note` ends its sentence even though
    the line ends in comment text, and a trailing full-line `*>` comment
    inside the span is not the statement's last line. Reading the raw line
    instead dropped the period from the replacement, leaving an
    unterminated sentence that ran into the next paragraph header."""
    for index in range(end, start - 1, -1):
        code = _code_text(lines[index - 1]).rstrip()
        if code.strip():
            return code.endswith(".")
    return False


#: A reference to SQLSTATE as a COBOL word (not RETURNED_SQLSTATE).
_SQLSTATE_RE = re.compile(r"(?<![\w-])SQLSTATE(?![\w-])", re.IGNORECASE)


def splice_program(
    lines: list[str],
    boundaries: list[int],
    surface: MockSurface,
    suite: MockTestSuite,
    registry: TallyRegistry,
    terminator_plans: Sequence[TerminatorPlan] = (),
    flow_plans: Sequence[FlowMockPlan] = (),
    file_status_fields: dict[str, str] | None = None,
    trace: bool = False,
    goto_exit_plans: Sequence[GotoExitPlan] = (),
    column_offset: int = 0,
    fallthrough_traps: frozenset[int] | set[int] = frozenset(),
    behaviour: bool = False,
) -> list[str]:
    """`fallthrough_traps` (`StaticCheckResult.fallthrough_traps`, issue
    #351): ids of unmocked boundary statements a case reaches only by GO
    TO fall-through. Each is replaced by `build_unmocked_trap` instead of
    being left to run for real.

    `column_offset` is how many columns every line of `lines` has been
    shifted right of the normalized source the AST's columns index --
    `export` splices lines with the 7-column sequence area restored
    (issue #325); the only column-sensitive step, the clause-body lift,
    needs it.

    A SELECT whose RECORD KEY is declared outside the file's FD record
    (CardDemo's CBEXPORT) is made compilable first
    (`splicer.file_keys`): the file is mocked, so its key is never used."""
    lines = rewrite_foreign_record_keys(lines, surface)
    last_line = len(lines)
    # EIBRESP / EIBRESP2 exist only when the program has an EIB (declared,
    # or synthesized because it references one); every CICS mock resets
    # them only then (issue #320).
    program_words = {word.strip(",;()") for _, _, word in scan_words("\n".join(lines))}
    eib_resp_names = tuple(n for n in EIB_RESP_NAMES if n in program_words)
    spans: list[tuple[int, int, list[str]]] = []
    sqlstate = any(_SQLSTATE_RE.search(line) for line in lines)
    # A mocked SQL / DL/I statement reports success first (SQLCODE 0,
    # DIBSTAT blank) when the program has those fields: an SQLCA (INCLUDE
    # SQLCA, or its own copy), a DIB (declared, or synthesized because the
    # program references DIBSTAT).
    sqlcode = bool({"SQLCA", "SQLCODE"} & program_words)
    dibstat = "DIBSTAT" in program_words
    # Baselines: a mocked `OPEN cursor` also records the cursor's DECLARE
    # host variables (splicer.behaviour).
    cursor_hosts = cursor_host_variables(lines) if behaviour else None
    # EXEC CICS RETURN/XCTL/ABEND plans (issue #215): the site keeps its
    # ordinary dispatch below, wrapped with the early exit.
    cics_terminators = {
        id(plan.site.statement): plan for plan in terminator_plans if plan.is_cics
    }

    # Pass 1: which sites get a splice, and how.
    kinds: dict[int, tuple[BoundarySite, str]] = {}
    for site in surface.boundary_sites:
        if site.category is None or id(site.statement) in kinds:
            continue
        mocked = any(
            directive_matches_site(directive, site)
            for case in suite.test_cases
            for directive in case.mocks
        )
        if mocked:
            kinds[id(site.statement)] = (site, "mock")
        elif site.category in EXEC_CATEGORIES:
            # Unmocked EXEC still has to go: cobc cannot compile it. The
            # refusal gate refuses any test case that can reach it (PERFORM
            # and GO TO edges, section PERFORMs, and SEARCH/EVALUATE bodies
            # are all modeled; DECLARATIVES and ALTER refuse the whole
            # program), so the trap only fires if reachability analysis and
            # reality disagree -- and then it fails loudly.
            kinds[id(site.statement)] = (site, "exec")
        elif id(site.statement) in fallthrough_traps:
            kinds[id(site.statement)] = (site, "trap")
        # Unmocked non-EXEC sites are plain COBOL: leave them alone. (If
        # one were reachable, the refusal gate already fired.)

    # A site nested in the clause body of another site that is spliced too
    # (`READ ... NOT AT END CALL "X"` with both mocked) is not spliced in
    # place: the enclosing splice comments its lines out. A mock of the
    # enclosing statement re-runs its clause bodies from a lifted copy, and
    # the nested site is spliced into that copy instead; a trap removes it
    # with the rest of the statement.
    parents = boundary_parents(surface)
    inner: dict[int, list[BoundarySite]] = {}
    enclosed: set[int] = set()
    for key, (site, _) in kinds.items():
        parent = parents.get(key)
        while parent is not None and id(parent.statement) not in kinds:
            parent = parents.get(id(parent.statement))
        if parent is None:
            continue
        enclosed.add(key)
        if kinds[id(parent.statement)][1] == "mock":
            inner.setdefault(id(parent.statement), []).append(site)

    def site_span(site: BoundarySite) -> tuple[int, int]:
        if site.nested:
            if site.span is None:
                raise ValueError(
                    f"nested {site.label} site at line {site.line} reached "
                    f"the splicer without a validated span -- the refusal "
                    f"gate (UNSUPPORTED_NESTED_MOCK_TARGET / NESTED_EXEC) "
                    f"should have refused it"
                )
            return site.span
        if site.unspliceable_reason:
            raise ValueError(
                f"top-level {site.label} site at line {site.line} "
                f"reached the splicer although it "
                f"{site.unspliceable_reason} -- the refusal gate "
                f"(UNSUPPORTED_MOCK_TARGET_LAYOUT / UNSPLICEABLE_EXEC) "
                f"should have refused it; splicing would delete the "
                f"sibling code sharing its line"
            )
        return statement_span(site.statement, boundaries, last_line, lines)

    def site_replacement(site: BoundarySite, kind: str) -> list[str]:
        """The site's replacement block, with every site nested in its
        clause bodies already spliced into the lifted copy -- but neither
        its span's clause-header lead nor a sentence period."""
        if kind == "exec":
            return build_exec_trap(site.label, site.line)
        if kind == "trap":
            return build_unmocked_trap(site.label, site.line)
        start, end = site_span(site)
        own = _without_lead(lines[start - 1 : end], site.span_lead, column_offset)
        lifted = lift_clause_bodies(site.statement, lines, column_offset)
        for child in inner.get(id(site.statement), []):
            if lifted is None:
                raise ValueError(
                    f"{child.label} site at line {child.line} is nested in "
                    f"the clause body of the mocked {site.label} at line "
                    f"{site.line}, whose clause bodies cannot be lifted -- "
                    f"the refusal gate (UNLIFTABLE_CLAUSE_BODY) should have "
                    f"refused it"
                )
            lifted = _splice_into_lifted(
                lifted,
                site_span(child),
                site_replacement(child, kinds[id(child.statement)][1]),
                child,
            )
        lifted, use_before, use_after = _with_use_procedures(
            site, surface, lifted, file_status_fields or {}
        )
        replacement = build_site_dispatch(
            site,
            suite,
            registry,
            file_status_fields,
            trace=trace,
            statement_text=" ".join(own),
            layout=surface.data_layout,
            # A nested site with clauses of its own reaches here only with
            # a span bounded by its own scope terminator (#258), so its
            # bodies lift exactly like a top-level site's.
            lifted_clauses=lifted,
            sqlstate=sqlstate,
            sqlcode=sqlcode,
            dibstat=dibstat,
            passthrough=(_statement_lines(own, 1, len(own)) if site.opt_in else None),
            eib_resp_names=eib_resp_names,
            real_statement=_statement_lines(own, 1, len(own)),
            behaviour=behaviour,
            cursor_hosts=cursor_hosts,
        )
        replacement = use_before + replacement + use_after
        if site.sort_procedure is not None:
            # A mixed-form SORT/MERGE: the mock answers its file side, and
            # its procedure runs on the other side, as the SORT runs it.
            side, first, thru = site.sort_procedure
            perform = f"           PERFORM {first}" + (f" THRU {thru}" if thru else "")
            if side == "INPUT":
                replacement = [perform] + replacement
            else:
                replacement = replacement + [perform]
        # What the DB2 precompiler puts after the statement for every
        # `EXEC SQL WHENEVER ... GO TO` above it (issue #195).
        return replacement + [
            f"           {line}" for line in whenever_check_lines(site.whenever_checks)
        ]

    for key, (site, kind) in kinds.items():
        if key in enclosed:
            continue
        start, end = site_span(site)
        replacement = site_replacement(site, kind)
        cics_plan = cics_terminators.get(key)
        if cics_plan is not None:
            prefix, suffix = build_cics_terminator_exit(
                cics_plan.exit_kind, cics_plan.resp_field
            )
            replacement = prefix + replacement + suffix
        replacement = _with_lead(lines, start, site, replacement, column_offset)
        # If the replaced statement carried its sentence's terminating
        # period (i.e. it was the last statement of the sentence /
        # paragraph), the replacement block must terminate the sentence too
        # -- otherwise the unterminated sentence runs into the next
        # paragraph header and cobc rejects it.
        if _span_ends_sentence(lines, start, end):
            replacement = replacement[:-1] + [replacement[-1] + "."]
        spans.append((start, end, replacement))

    # `EXEC SQL WHENEVER` declarations (issue #195): their effect is the
    # checks appended to each SQL dispatch above; the statement itself has
    # no runtime behavior, and cobc cannot compile it. check_nested_exec
    # refuses one with no safe span before any splicing.
    for site in surface.whenever_sites:
        if site.nested:
            if site.span is None:
                raise ValueError(
                    f"nested EXEC SQL WHENEVER at line {site.line} reached "
                    f"the splicer without a validated span -- the refusal "
                    f"gate (NESTED_EXEC) should have refused it"
                )
            start, end = site.span
        else:
            if site.unspliceable_reason:
                raise ValueError(
                    f"EXEC SQL WHENEVER at line {site.line} reached the "
                    f"splicer although it {site.unspliceable_reason} -- the "
                    f"refusal gate (UNSPLICEABLE_EXEC) should have refused it"
                )
            start, end = statement_span(site.statement, boundaries, last_line, lines)
        replacement = ["           CONTINUE"]
        if _span_ends_sentence(lines, start, end):
            replacement = replacement[:-1] + [replacement[-1] + "."]
        replacement = _with_lead(lines, start, site, replacement, column_offset)
        spans.append((start, end, replacement))

    # STOP <literal> (waits for the operator) and a screen DISPLAY (would
    # switch GnuCOBOL to screen mode): under a test the console answers at
    # once, CONTINUE. A nested one, or one with no safe span, is refused by
    # the gate when a case reaches it, and left as written otherwise.
    for site in surface.boundary_sites:
        if site.label not in ANSWERED_LABELS or site.nested or site.unspliceable_reason:
            continue
        start, end = statement_span(site.statement, boundaries, last_line, lines)
        replacement = ["           CONTINUE"]
        if _span_ends_sentence(lines, start, end):
            replacement = replacement[:-1] + [replacement[-1] + "."]
        replacement = _with_lead(lines, start, site, replacement, column_offset)
        spans.append((start, end, replacement))

    # Terminator neutralization: replace the STOP RUN/GOBACK statement's
    # own span, exactly like any other boundary replacement above.
    seen_terminator_ids: set[int] = set()
    for plan in terminator_plans:
        site = plan.site
        if plan.is_cics or id(site.statement) in seen_terminator_ids:
            continue
        seen_terminator_ids.add(id(site.statement))
        replacement = build_terminator_neutralization(plan.exit_kind, plan.return_code)
        if site.nested:
            if site.span is None:
                raise ValueError(
                    f"nested {site.label} site at line {site.line} reached "
                    f"the splicer without a validated span -- "
                    f"check_terminator_layout (UNSUPPORTED_TERMINATOR_LAYOUT) "
                    f"should have refused it"
                )
            start, end = site.span
        else:
            if site.unspliceable_reason:
                raise ValueError(
                    f"top-level {site.label} site at line {site.line} "
                    f"reached the splicer although it "
                    f"{site.unspliceable_reason} -- "
                    f"check_terminator_layout (UNSUPPORTED_TERMINATOR_LAYOUT) "
                    f"should have refused it"
                )
            start, end = statement_span(site.statement, boundaries, last_line, lines)
        if _span_ends_sentence(lines, start, end):
            replacement = replacement[:-1] + [replacement[-1] + "."]
        replacement = _with_lead(lines, start, site, replacement, column_offset)
        spans.append((start, end, replacement))

    # GO-TO-to-EXIT-PARAGRAPH splices (docs/2026-08-17-goto-exit-paragraph-
    # simplification-design.md, STATUS: not yet verified against real
    # GnuCOBOL): replace the GO TO statement's own span. `plan.span` is
    # precomputed by find_goto_exit_plans -- a top-level GO TO's span via
    # statement_span, a nested one's (inside an IF/EVALUATE branch) via
    # nested_statement_span -- and must be used as-is here, NOT
    # recomputed with statement_span directly: statement_span alone does
    # not know about block words like END-IF and can silently swallow one
    # when the GO TO is nested (see nested_statement_span's docstring).
    seen_goto_ids: set[int] = set()
    for goto_plan in goto_exit_plans:
        if id(goto_plan.statement) in seen_goto_ids:
            continue
        seen_goto_ids.add(id(goto_plan.statement))
        if goto_plan.span is None:
            raise ValueError(
                f"GO TO in paragraph '{goto_plan.paragraph_name}' reached "
                f"the splicer without a precomputed span -- "
                f"find_goto_exit_plans should never return a plan with "
                f"span=None"
            )
        start, end = goto_plan.span
        replacement = build_goto_exit_replacement(goto_plan.exit_kind)
        if _span_ends_sentence(lines, start, end):
            replacement = replacement[:-1] + [replacement[-1] + "."]
        spans.append((start, end, replacement))

    # Flow-mock header splices (MOCK PARAGRAPH/SECTION): replace ONLY the
    # header line with header + EVALUATE dispatch + relocated real header.
    # The original body lines never move, so every span computed above (a
    # boundary dispatch or terminator inside that body) stays valid --
    # bottom-up application shifts already-applied replacements down as one
    # block when this lower-line splice grows the file. Deliberately
    # OUTSIDE the trailing-period propagation the other replacements get:
    # the header line always ends with "." and the replacement is already
    # sentence-complete (its own EVALUATE period plus the new header's) --
    # propagating would emit a doubled period after the real header.
    for flow_plan in flow_plans:
        spans.append(
            (
                flow_plan.header_line,
                flow_plan.header_line,
                build_flow_dispatch(flow_plan, suite, registry, trace=trace),
            )
        )

    # Chain-check insertion: every intermediate PERFORM statement across
    # every plan, deduped by identity (several plans can share the same
    # PERFORM edge -- e.g. two terminators reached through one common
    # wrapper paragraph). Represented as insert-only operations and merged
    # with `spans` into ONE combined, position-sorted bottom-up pass below
    # -- see the note on ordering for why a separate second pass is unsafe.
    seen_perform_ids: set[int] = set()
    insertions: list[tuple[int, list[str]]] = []
    for plan in terminator_plans:
        for perform in plan.chain_performs:
            if id(perform) in seen_perform_ids:
                continue
            seen_perform_ids.add(id(perform))
            # A PERFORM nested in an IF/EVALUATE branch or inline PERFORM
            # body has a precomputed nested span (issue #337):
            # statement_span would end at the next TOP-LEVEL statement, past
            # the enclosing END-IF/END-PERFORM.
            nested_span = plan.chain_spans.get(id(perform))
            if nested_span is not None:
                start, end = nested_span
            else:
                start, end = statement_span(perform, boundaries, last_line, lines)
            chain_check = build_chain_check(
                plan.chain_exit_kinds.get(id(perform), "PARAGRAPH")
            )
            # If the PERFORM this follows ended its own sentence with a
            # period, the inserted IF/END-IF block is itself a brand-new,
            # unterminated sentence -- give it its own closing period, or
            # an unterminated END-IF runs straight into the next paragraph/
            # SECTION header and cobc rejects it. Unlike the `spans`
            # (replace) path above, `insert_lines_after` never touches the
            # original PERFORM line, so there's no period to "move" here --
            # the PERFORM's own sentence is already correctly terminated;
            # only the newly-inserted block needs one of its own.
            if _span_ends_sentence(lines, start, end):
                chain_check = chain_check[:-1] + [chain_check[-1] + "."]
            insertions.append((end, chain_check))

    # Loop PERFORMs on a chain get their UNTIL extended in place first: the
    # line count does not change, so every span and insertion point above
    # stays valid.
    seen_loop_ids: set[int] = set()
    for plan in terminator_plans:
        for perform in plan.loop_performs:
            if id(perform) in seen_loop_ids:
                continue
            seen_loop_ids.add(id(perform))
            nested_span = plan.chain_spans.get(id(perform))
            if nested_span is not None:
                start, end = nested_span
            else:
                start, end = statement_span(perform, boundaries, last_line, lines)
            lines = prefix_loop_conditions(lines, start, end)

    ops: list[tuple[int, str, int, int, list[str]]] = [
        (start, "replace", start, end, replacement) for start, end, replacement in spans
    ] + [
        (line_number, "insert", line_number, line_number, new_lines)
        for line_number, new_lines in insertions
    ]
    for _, kind, start, end, replacement in sorted(
        ops, key=lambda o: o[0], reverse=True
    ):
        if kind == "replace":
            lines = comment_and_replace(lines, start, end, replacement)
        else:
            lines = insert_lines_after(lines, start, replacement)
    return lines


#: The file statements a USE AFTER EXCEPTION procedure follows.
_USE_CATEGORIES = frozenset(
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


def _with_use_procedures(
    site: BoundarySite,
    surface: MockSurface,
    lifted: tuple[LiftedClause, ...] | None,
    file_status_fields: dict[str, str],
) -> tuple[tuple[LiftedClause, ...] | None, list[str], list[str]]:
    """What a mocked file statement adds for the program's USE AFTER
    EXCEPTION procedures (`analysis.declaratives`): (its lifted clauses
    with one more that PERFORMs the applicable USE section on an exception
    outcome, lines to put before the dispatch, lines to put after it).

    The added clause comes last in the clause `EVALUATE TRUE`, so an AT
    END / INVALID KEY phrase of the statement handles its own condition
    first, as at run time. An OPEN records each file's open mode first
    (`UseProcedures.mode_field`). A statement naming several files (`OPEN
    INPUT A OUTPUT B`, `CLOSE A B`) checks each file's own FILE STATUS
    field after the dispatch instead: one outcome cannot speak for both."""
    uses = surface.use_procedures
    if (
        uses is None
        or site.category not in _USE_CATEGORIES
        or site.paragraph_name in uses.declarative_names
    ):
        return lifted, [], []
    files = list(dict.fromkeys(uses.file_of(key) for key in site.keys))
    modes = site.open_modes or {}
    before = [
        f'           MOVE "{MODE_CODES[modes[name]]}" TO {mode_field}'
        for name in files
        if (mode_field := uses.mode_field(name)) is not None
        and modes.get(name) in MODE_CODES
    ]
    after: list[str] = []
    if len(files) == 1:
        body = uses.perform_lines(files[0], modes.get(files[0]))
        if body:
            lifted = (
                *(lifted or ()),
                LiftedClause("use_procedure", USE_GUARD, tuple(body)),
            )
        return lifted, before, after
    for name in files:
        status = file_status_fields.get(name)
        body = uses.perform_lines(name, modes.get(name))
        if status and body:
            after.append(
                f'           IF {status} NOT = SPACES AND {status}(1:1) NOT = "0"'
            )
            after.extend(f"               {line}" for line in body)
            after.append("           END-IF")
    return lifted, before, after


def _with_lead(
    lines: list[str],
    start: int,
    site: BoundarySite,
    replacement: list[str],
    column_offset: int,
) -> list[str]:
    """`replacement` behind the code the site's span opens with
    (`BoundarySite.span_lead`): a clause header (`AT END CALL "X"`) or, at
    the top level, statements that close their sentence (`PERFORM A.
    CLOSE F.`). That code stays as written, on a line of its own."""
    if not site.span_lead:
        return replacement
    lead_width = column_offset + len(site.span_lead)
    return [lines[start - 1][:lead_width].rstrip(), *replacement]


def _statement_lines(lines: list[str], start: int, end: int) -> list[str]:
    """The statement on `lines[start - 1 : end]`, one entry per source line
    with its indentation and any sentence-ending period dropped -- the real
    statement an opt-in site's dispatch runs for cases that do not mock it
    (`build_site_dispatch`'s `passthrough`). The period goes because the
    replacement block gets its own when the span ended the sentence."""
    text = [line.strip() for line in lines[start - 1 : end] if line.strip()]
    if text and text[-1].endswith("."):
        text[-1] = text[-1][:-1].rstrip()
    return [line for line in text if line]


def _without_lead(
    span_lines: list[str], lead: str | None, column_offset: int = 0
) -> list[str]:
    """`span_lines` with the clause header a span opens with
    (`BoundarySite.span_lead`, measured on the normalized source, which
    `span_lines` sits `column_offset` columns right of) blanked out of its
    first line."""
    if not lead or not span_lines:
        return list(span_lines)
    width = column_offset + len(lead)
    return [" " * width + span_lines[0][width:], *span_lines[1:]]


def _splice_into_lifted(
    lifted: tuple[LiftedClause, ...],
    span: tuple[int, int],
    replacement: list[str],
    site: BoundarySite,
) -> tuple[LiftedClause, ...]:
    """`lifted` with the lines of `span` -- a site nested in one of its
    clause bodies -- replaced by `replacement` in the body that holds them.
    The span was validated against the source (`annotate_nested_sites`):
    it opens with the site's own line, ends before the next statement,
    clause header or scope word, and the lift copied those lines verbatim
    (`LiftedClause.source_line_numbers`), less the clause header and any
    sentence period, which stay the enclosing statement's."""
    start, end = span
    result = list(lifted)
    for index, clause in enumerate(lifted):
        numbers = clause.source_line_numbers
        if start not in numbers:
            continue
        keep = [k for k, number in enumerate(numbers) if not start <= number <= end]
        first = numbers.index(start)
        before = [k for k in keep if k < first]
        after = [k for k in keep if k > first]
        result[index] = dataclasses.replace(
            clause,
            source_lines=(
                *(clause.source_lines[k] for k in before),
                *replacement,
                *(clause.source_lines[k] for k in after),
            ),
            source_line_numbers=(
                *(numbers[k] for k in before),
                *(0 for _ in replacement),
                *(numbers[k] for k in after),
            ),
        )
        return tuple(result)
    raise ValueError(
        f"{site.label} site at line {site.line} is nested in a clause body "
        f"the lift did not copy its line {start} from"
    )
