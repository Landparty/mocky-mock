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

from mockymock.analysis.mock_surface import MockSurface
from mockymock.analysis.refusal import TerminatorPlan, directive_matches_site
from mockymock.dsl.model import EXEC_CATEGORIES, MockTestSuite
from mockymock.splicer.injector import (
    build_chain_check,
    build_exec_trap,
    build_site_dispatch,
    build_terminator_neutralization,
)
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.source_map import statement_span
from mockymock.splicer.stub_writer import comment_and_replace, insert_lines_after


def splice_program(
    lines: list[str],
    boundaries: list[int],
    surface: MockSurface,
    suite: MockTestSuite,
    registry: TallyRegistry,
    terminator_plans: Sequence[TerminatorPlan] = (),
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
        if mocked:
            replacement = build_site_dispatch(site, suite, registry)
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
        # If the replaced statement carried its sentence's terminating
        # period (i.e. it was the last statement of the sentence /
        # paragraph), the replacement block must terminate the sentence too
        # -- otherwise the unterminated sentence runs into the next
        # paragraph header and cobc rejects it.
        last_span_line = next(
            (lines[i - 1] for i in range(end, start - 1, -1) if lines[i - 1].strip()),
            "",
        )
        if last_span_line.rstrip().endswith("."):
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
        replacement = build_terminator_neutralization()
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
        last_span_line = next(
            (lines[i - 1] for i in range(end, start - 1, -1) if lines[i - 1].strip()),
            "",
        )
        if last_span_line.rstrip().endswith("."):
            replacement = replacement[:-1] + [replacement[-1] + "."]
        spans.append((start, end, replacement))

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
            _, end = statement_span(perform, boundaries, last_line, lines)
            insertions.append((end, build_chain_check()))

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
