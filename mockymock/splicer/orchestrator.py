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

from collections.abc import Sequence

from mockymock.analysis.flow_mocks import FlowMockPlan
from mockymock.analysis.mock_surface import MockSurface
from mockymock.analysis.refusal import (
    GotoExitPlan,
    TerminatorPlan,
    directive_matches_site,
)
from mockymock.dsl.model import EXEC_CATEGORIES, MockTestSuite
from mockymock.splicer.injector import (
    build_chain_check,
    build_exec_trap,
    build_flow_dispatch,
    build_goto_exit_replacement,
    build_site_dispatch,
    build_terminator_neutralization,
)
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.source_map import statement_span
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
) -> list[str]:
    last_line = len(lines)
    spans: list[tuple[int, int, list[str]]] = []
    seen_statement_ids: set[int] = set()

    for site in surface.boundary_sites:
        if site.category is None:
            continue
        if id(site.statement) in seen_statement_ids:
            continue

        mocked = any(
            directive_matches_site(directive, site)
            for case in suite.test_cases
            for directive in case.mocks
        )
        replacement: list[str] | None
        if mocked:
            replacement = None  # built once the site's span is known
        elif site.category in EXEC_CATEGORIES:
            # Unmocked EXEC still has to go: cobc cannot compile it. The
            # refusal gate refuses any test case that can reach it (PERFORM
            # and GO TO edges, section PERFORMs, and SEARCH/EVALUATE bodies
            # are all modeled; DECLARATIVES and ALTER refuse the whole
            # program), so the trap only fires if reachability analysis and
            # reality disagree -- and then it fails loudly.
            replacement = build_exec_trap(site.label, site.line)
        else:
            # Unmocked non-EXEC sites are plain COBOL: leave them alone.
            # (If one were reachable, the refusal gate already fired.)
            continue

        seen_statement_ids.add(id(site.statement))
        if site.nested:
            if site.span is None:
                raise ValueError(
                    f"nested {site.label} site at line {site.line} reached "
                    f"the splicer without a validated span -- the refusal "
                    f"gate (UNSUPPORTED_NESTED_MOCK_TARGET / NESTED_EXEC) "
                    f"should have refused it"
                )
            start, end = site.span
        else:
            if site.unspliceable_reason:
                raise ValueError(
                    f"top-level {site.label} site at line {site.line} "
                    f"reached the splicer although it "
                    f"{site.unspliceable_reason} -- the refusal gate "
                    f"(UNSUPPORTED_MOCK_TARGET_LAYOUT / UNSPLICEABLE_EXEC) "
                    f"should have refused it; splicing would delete the "
                    f"sibling code sharing its line"
                )
            start, end = statement_span(site.statement, boundaries, last_line, lines)
        if replacement is None:
            replacement = build_site_dispatch(
                site,
                suite,
                registry,
                file_status_fields,
                trace=trace,
                statement_text=" ".join(lines[start - 1 : end]),
                layout=surface.data_layout,
            )
        # If the replaced statement carried its sentence's terminating
        # period (i.e. it was the last statement of the sentence /
        # paragraph), the replacement block must terminate the sentence too
        # -- otherwise the unterminated sentence runs into the next
        # paragraph header and cobc rejects it.
        if _span_ends_sentence(lines, start, end):
            replacement = replacement[:-1] + [replacement[-1] + "."]
        spans.append((start, end, replacement))

    # Terminator neutralization: replace the STOP RUN/GOBACK statement's
    # own span, exactly like any other boundary replacement above.
    seen_terminator_ids: set[int] = set()
    for plan in terminator_plans:
        site = plan.site
        if id(site.statement) in seen_terminator_ids:
            continue
        seen_terminator_ids.add(id(site.statement))
        replacement = build_terminator_neutralization(plan.exit_kind)
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
            start, end = statement_span(perform, boundaries, last_line, lines)
            chain_check = build_chain_check()
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
