"""GO-TO-exit and terminator plan construction.

Split out of the former monolithic `refusal.py` (2026-08-26 audit): this
module turns a reachability analysis (see `_reachability.py`) into the
concrete splice plans the splicer consumes -- `GotoExitPlan` (a GO TO safe
to replace with `EXIT PARAGRAPH` in place) and `TerminatorPlan` (a
STOP RUN/GOBACK safe to neutralize, plus the intermediate PERFORM chain
that needs early-exit instrumentation). Both plan finders can themselves
produce `RefusalReason`s for shapes they find unsafe to plan for -- see
`_types.py` for why `RefusalReason` lives outside `_gates.py`.

See `.okf/analysis.md` for the full refusal-package overview and
docs/2026-08-17-goto-exit-paragraph-simplification-design.md /
docs/2026-07-08-goback-stop-run-support-design.md /
docs/2026-07-10-section-scoped-terminator-support-design.md /
docs/2026-07-10-goto-fallthrough-terminator-hazard-design.md for the
design history behind these two plan shapes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cobolparser.models.statements.control import GoStatement, PerformStatement

from mockymock.analysis.cics_handle import raised_conditions
from mockymock.analysis.declaratives import declarative_paragraphs
from mockymock.analysis.mock_surface import (
    BoundarySite,
    MockSurface,
    _all_paragraphs,
    _nested_statement_lists,
    is_terminator_site,
)
from mockymock.analysis.sql_whenever import (
    whenever_can_fire,
    whenever_lines,
)
from mockymock.dsl.model import MockTestSuite
from mockymock.splicer.source_map import (
    collect_boundaries,
    nested_statement_span,
    statement_span,
    statement_top_level_problem,
)

from ._reachability import (
    _closed_perform_ranges,
    _expand_thru_range,
    _falls_through,
    _fallthrough_safe_sections,
    _find_sort_merge_statements,
    _find_statements_of_type,
    _find_xml_parse_statements,
    _go_statement_raw_targets,
    _go_statement_target,
    _go_statements_with_nesting,
    _go_to_fallthrough_targets,
    _go_to_targets,
    _is_exit_only_paragraph,
    _paragraph_safe_section_map,
    _plain_perform_edges_from,
    _plain_perform_statements,
    _reachable_paragraphs,
    _safe_section_entry_points,
    _section_member_modes,
    _source_ordered_paragraphs,
)
from ._types import _UNANNOTATED, RefusalReason


@dataclass
class TerminatorPlan:
    """One physical STOP RUN(RUN-form)/GOBACK statement found safe to
    neutralize, plus every intermediate PERFORM statement (deduped across
    the whole suite by identity) that needs the early-exit flag-check
    inserted after it for this terminator's propagation to correctly
    reach the test driver. Empty `chain_performs` means the terminator
    sits directly in a test's own PERFORM target -- no intermediate
    instrumentation needed. `exit_kind` is "PARAGRAPH" (the default) or
    "SECTION" for the one SECTION-scoped shape
    docs/2026-07-10-section-scoped-terminator-support-design.md supports
    -- a terminator in a SECTION's first paragraph, entered exclusively
    via PERFORM <section-name>. "PROGRAM" (2026-11-02) is a terminator
    that ends the main line of a case PERFORMing THRU the program's last
    paragraph: it becomes `GO TO UT-PROGRAM-END` (`PROGRAM_END_PARAGRAPH`),
    never runs inside a PERFORM of the program's own, and needs no chain.
    See docs/2026-07-08-goback-stop-run-support-design.md and
    docs/2026-07-10-section-scoped-terminator-support-design.md."""

    site: BoundarySite
    chain_performs: list = field(default_factory=list)
    exit_kind: str = "PARAGRAPH"
    # id(perform) -> the validated `nested_statement_span` of each chain
    # PERFORM nested in an IF/EVALUATE branch or an inline PERFORM body
    # (issue #337): the chain check is inserted after the span's end, i.e.
    # right after the PERFORM inside its own branch. A top-level chain
    # PERFORM has no entry here and keeps its `statement_span`.
    chain_spans: dict[int, tuple[int, int]] = field(default_factory=dict)
    # id(perform) -> "SECTION" for each chain PERFORM held by a SECTION's
    # first paragraph entered via PERFORM <section-name> (issue #338): its
    # check must leave the whole section, as the terminator's own
    # `exit_kind` does, or control falls into the section's next
    # paragraph. Absent means "PARAGRAPH".
    chain_exit_kinds: dict[int, str] = field(default_factory=dict)
    # The operand of `STOP RUN RETURNING n` / `GOBACK RETURNING n` (issue
    # #219): the neutralization MOVEs it to RETURN-CODE before setting the
    # early-exit flag, since removing the statement removes the phrase too.
    return_code: str | None = None
    # EXEC CICS RETURN/XCTL/ABEND only (issue #215): the RESP(field) the
    # command names, or None. With RESP, a failed command returns control
    # to the next statement, so the early exit is taken only while the
    # field holds NORMAL (0) -- the splicer presets it to 0 before the mock
    # body, as a successful command would, and the body may override it.
    resp_field: str | None = None
    # Out-of-line `PERFORM <name> UNTIL` loops on the chain (also in
    # `chain_performs`, which gives each its check): the splicer prefixes
    # each UNTIL with `UT-EARLY-EXIT = "Y" OR`, or the loop would go round
    # again after the early exit (`_reachability._is_loop_perform`).
    loop_performs: list = field(default_factory=list)

    @property
    def is_cics(self) -> bool:
        return self.site.category is not None


# A RETURNING/GIVING operand the neutralization can MOVE to RETURN-CODE
# verbatim: a signed or unsigned integer literal, or one data name.
_RETURN_CODE_OPERAND_RE = re.compile(r"^(?:[+-]?\d+|[A-Z0-9][A-Z0-9-]*)$", re.I)


_RESP_FIELD_RE = re.compile(r"\bRESP\s*\(\s*([A-Z0-9][A-Z0-9-]*)\s*\)", re.I)
_RESP_OPTION_RE = re.compile(r"\bRESP\s*\(", re.I)
_NOHANDLE_RE = re.compile(r"\bNOHANDLE\b", re.I)


def _cics_resp_field(statement) -> tuple[str | None, str | None]:
    """(field, problem) for an EXEC CICS terminator's RESP option: the
    single data name in `RESP(field)`, `EIBRESP` for a NOHANDLE command
    without RESP, (None, None) when there is neither, or a problem when
    RESP names something this can't test against 0."""
    text = str(getattr(statement, "cics_text", "") or "")
    match = _RESP_FIELD_RE.search(text)
    if match is not None:
        return match.group(1).upper(), None
    if _RESP_OPTION_RE.search(text):
        return None, (
            "has a RESP option mockymock can't read back as a single data "
            "name, so it can't tell a failed command (which returns "
            "control) from a successful one (which ends the program)"
        )
    if _NOHANDLE_RE.search(text):
        # NOHANDLE returns control on a failed command just as RESP does,
        # with the condition in EIBRESP (issue #301).
        return "EIBRESP", None
    return None, None


def _terminator_name(site) -> str:
    """How a refusal names the terminator: its label, or `EXEC CICS
    RETURN` (etc.) for a CICS one, whose label is just "CICS"."""
    if site.category is None:
        return site.label
    return f"EXEC CICS {str(site.statement.cics_command).upper()}"


def _terminator_return_code(statement) -> tuple[str | None, str | None]:
    """(operand, problem) for a terminator's RETURNING/GIVING phrase:
    cobolparser keeps it as `StopStatement.returning` /
    `GobackStatement.returning_value`. (None, None) when there is none;
    a problem when the operand is not one this neutralization can copy to
    RETURN-CODE as written."""
    operand = getattr(statement, "returning", None) or getattr(
        statement, "returning_value", None
    )
    if operand is None:
        return None, None
    text = str(operand).strip()
    if not _RETURN_CODE_OPERAND_RE.match(text):
        return None, (
            f"has a RETURNING operand ({text!r}) mockymock can't copy to "
            f"RETURN-CODE when it neutralizes the statement -- use an "
            f"integer literal or a single data name"
        )
    return text, None


@dataclass
class GotoExitPlan:
    """One physical GO TO statement found safe to splice directly into
    EXIT PARAGRAPH at its own call site, because its target is a
    paragraph whose entire body is a no-op EXIT statement -- see
    docs/2026-08-17-goto-exit-paragraph-simplification-design.md.
    STATUS: implemented, not yet verified against real GnuCOBOL (no
    Docker daemon was available when this was written) -- see that
    design doc's Status note before trusting this in production.

    `exit_kind` is always "PARAGRAPH" today: find_goto_exit_plans only
    accepts a top-level enclosing paragraph (SECTION-scoped enclosing
    paragraphs are declined -- see that function's docstring for why).
    Kept as a field, matching TerminatorPlan's shape, in case SECTION
    support is added later.

    Unlike TerminatorPlan, this never carries chain_performs: the
    replacement ends the SAME paragraph the GO TO already lived in, so
    there is nothing to propagate through an intermediate PERFORM chain
    -- no UT-EARLY-EXIT flag is involved at all.

    `span` is precomputed by find_goto_exit_plans (never None on a
    returned plan -- a plan whose span could not be validated is not
    returned at all): a top-level GO TO's span comes from `statement_span`,
    a nested one's from `nested_statement_span`. Precomputing it here,
    once, at the same place the safety checks run, means the splicer
    never has to re-derive nested-vs-top-level span logic itself -- see
    `nested_statement_span`'s docstring for the bug this avoids."""

    statement: GoStatement
    paragraph_name: str
    exit_kind: str = "PARAGRAPH"
    span: tuple[int, int] | None = None


def _in_program_range_ends(procedure) -> dict[str, int]:
    """Paragraph name -> line of one in-program PERFORM (any form, at
    any nesting depth), SORT/MERGE INPUT/OUTPUT PROCEDURE or XML PARSE
    PROCESSING PROCEDURE whose range ENDS at that paragraph: `PERFORM A`
    ends at A, `PERFORM A THRU B` at B. A GO TO out of such a paragraph
    leaves that range (issue #213)."""
    ends: dict[str, int] = {}
    for paragraph in _all_paragraphs(procedure):
        statements = paragraph.statements
        for statement in _find_statements_of_type(statements, PerformStatement):
            end = statement.thru_paragraph or statement.target_paragraph
            if end:
                ends.setdefault(end, statement.location.line)
        for statement in _find_sort_merge_statements(statements):
            for start_attr, thru_attr in (
                ("input_procedure", "input_procedure_thru"),
                ("output_procedure", "output_procedure_thru"),
            ):
                end = getattr(statement, thru_attr, None) or getattr(
                    statement, start_attr, None
                )
                if end:
                    ends.setdefault(end, statement.location.line)
        for statement in _find_xml_parse_statements(statements):
            end = getattr(statement, "processing_procedure_thru", None) or getattr(
                statement, "processing_procedure", None
            )
            if end:
                ends.setdefault(end, statement.location.line)
    return ends


# Shown when a nested site reaches a check before annotate_nested_sites ran
# (or was skipped): treat it as unspliceable rather than assume it is safe.
def find_goto_exit_plans(
    program, scope_map, lines: list[str]
) -> tuple[list[GotoExitPlan], list[str]]:
    """Whole-program, unconditional on any test case -- like NESTED_EXEC's
    reasoning, but "plan or silently skip" rather than "plan or refusal":
    declining this optimization is always safe, the program compiles and
    runs exactly as it does today, so an ineligible candidate is reported
    as an informational note, never a RefusalReason that would block the
    run. See
    docs/2026-08-17-goto-exit-paragraph-simplification-design.md.
    STATUS: implemented, not yet verified against real GnuCOBOL.

    Consumers beyond the splicer itself go through
    `neutralized_goto_targets` (the fully-neutralized target names):
    `find_terminator_plans`' hazard-set narrowing, and -- since
    2026-08-25 -- `check_test_case`/`_reachable_paragraphs`' reachable
    set, so the mock gates stop demanding mocks for the fall-through
    cascade a spliced-away GO TO can no longer trigger. Any soundness
    condition added or relaxed here therefore changes what those gates
    waive, not just what the splicer rewrites.

    A GO TO qualifies only when ALL of:
    - it names a single, unconditional target (`_go_statement_target`)
      that is an exit-only paragraph (`_is_exit_only_paragraph`);
    - no OTHER GoStatement anywhere in the program -- including a
      computed or multi-target one `_go_statement_target` can't resolve
      -- could ALSO land on that same paragraph (`_go_statement_raw_
      targets`): a computed `GO TO` naming the exit-only paragraph as one
      of several possible targets is invisible to the per-site checks
      below but is exactly as much of a real `GO TO` edge into it as the
      resolvable one, so its mere existence disqualifies the whole
      target;
    - a validated replacement span exists for the statement
      (`statement_top_level_problem`/`statement_span` for a top-level GO
      TO, `nested_statement_span` for one nested inside an
      IF/EVALUATE branch -- see that function's docstring for the bug
      this distinction exists to avoid) and it is not nested inside
      another boundary statement's own clause body;
    - its enclosing paragraph is itself safe to issue `EXIT PARAGRAPH`
      from -- top-level (`top_level_names`), not in `_go_to_targets`, not
      in `_go_to_fallthrough_targets` (the same preconditions
      `find_terminator_plans` enforces on a terminator's own paragraph);
    - the exit-only paragraph is the IMMEDIATE NEXT paragraph after the
      enclosing paragraph in source order, with nothing else between them
      (`_source_ordered_paragraphs`) other than a phantom "." paragraph --
      cobolparser's empty-artifact node for a bare "." line sitting before
      the next paragraph's header, tolerated the same way `_expand_thru_range`
      already tolerates it elsewhere in this file (`immediately_follows`).
      This is the one THRU-elision-safe shape the design doc describes:
      without it, a `PERFORM ... THRU <exit-paragraph>` range (declared by a
      `.cut` test, OR written in-program) covering real intermediate
      paragraphs would have its early-exit semantics silently changed by
      this splice -- the original `GO TO` skips those paragraphs entirely,
      but `EXIT PARAGRAPH` only ends the enclosing paragraph, so the THRU
      range's own fall-through would then run them on the early-exit path
      where it never did before. Confirmed empirically against this exact
      shape before this check existed (see the PR review that added it).
    - no in-program PERFORM (or SORT/MERGE/XML PARSE procedure) range
      ENDS at the enclosing paragraph (`_in_program_range_ends`, issue
      #213): under `PERFORM <enclosing>` with no `THRU <exit-paragraph>`,
      the original GO TO jumps OUT of the PERFORM range and control never
      returns to the caller -- the classic forgotten-THRU bug. Rewriting
      it into a clean return would certify behaviour the real program
      does not have, so the GO TO is left alone and its edge stays
      visible to the gates. A `.cut`/hook PERFORM of the enclosing
      paragraph without THRU is deliberately NOT a disqualifier: that is
      the THRU-elision convenience the design doc describes, and without
      the rewrite the GO TO would run off the end of the test driver.

    SECTION-scoped enclosing paragraphs are NOT supported (unlike
    `find_terminator_plans`, which handles the one narrow safe-section-
    entry shape via `EXIT SECTION`): both a cleanup paragraph following
    the exit-only paragraph inside the same section (which `EXIT SECTION`
    would skip, where the original fall-through ran it) and
    `find_terminator_plans`' own "shape 3" gap (a `.cut` test's
    `perform_target` naming the section's first paragraph directly,
    bypassing `PERFORM <section-name>` -- a shape that function itself
    treats as unverified) would need suite-case context this whole-
    program function does not have. Deferred rather than half-solved;
    an enclosing paragraph that is a SECTION member is declined with a
    note, exactly like any other non-top-level enclosing paragraph.

    All-or-nothing per target paragraph: `_go_to_targets`/
    `_go_to_fallthrough_targets` are whole-program properties, so
    neutralizing some but not all GO TOs naming one exit-only paragraph
    would leave that paragraph exactly as hazardous as before. If every
    GO TO naming a given exit-only paragraph qualifies, all are
    neutralized together; if even one fails (including a computed/multi-
    target GO TO that merely NAMES it, never itself a "site"), none of
    that paragraph's GO TOs are touched and a note explains why.

    `_safe_section_entry_points`'s own internal `_go_to_targets` check is
    deliberately NOT narrowed by any OTHER goto-exit plan already found --
    composing two neutralizations to unlock a section entry is real
    additional complexity with no corpus example needing it; at worst
    this costs an extra declined optimization, never unsoundness.

    The fixpoint loop below is a narrower, unrelated thing: it re-narrows
    THIS function's own `_go_to_targets`/`_go_to_fallthrough_targets` by
    targets THIS function has already confirmed, within a single call --
    it never touches `_safe_section_entry_points`. Back-to-back
    validation-style paragraphs (`2211-VALIDER-MNT` /
    `2211-EXIT`, immediately followed by `2212-VALIDER-...` / `2212-EXIT`,
    and so on) chain: neutralizing `2211-EXIT` drops it out of
    `_go_to_targets`, which is exactly what un-marks `2212-VALIDER-...` as
    a `_go_to_fallthrough_targets` hazard (it was only hazardous because
    `2211-EXIT`, a bare-EXIT paragraph, falls through into it) -- which is
    what lets `2212-EXIT` neutralize in turn, and so on transitively
    through however many such paragraphs sit back-to-back. A single static
    pass over the RAW, whole-program `_go_to_targets`/
    `_go_to_fallthrough_targets` sees every paragraph on that chain as
    hazardous from the very first paragraph's still-live GO TO and
    declines the entire chain at once. So this evaluates every candidate
    target repeatedly, each round narrowing `_go_to_targets` (and, through
    it, `_go_to_fallthrough_targets`) by every target CONFIRMED in an
    EARLIER round -- mirroring the narrowing `find_terminator_plans` and
    `_reachable_paragraphs` already apply using this function's own FINAL
    output -- until a round confirms nothing new. Monotonic and therefore
    terminates: confirmed targets are never revisited, and each round
    either confirms at least one new target or the loop stops."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return [], []

    paragraphs = _all_paragraphs(procedure)
    exit_only_names = {
        p.paragraph_name for p in paragraphs if _is_exit_only_paragraph(p)
    }
    if not exit_only_names:
        return [], []

    top_level_names = {p.paragraph_name for p in procedure.paragraphs}
    range_ends = _in_program_range_ends(procedure)
    base_go_to_targets = _go_to_targets(program)
    boundaries = collect_boundaries(program)
    last_line = len(lines)
    ordered = _source_ordered_paragraphs(procedure) or []
    index_by_name = {p.paragraph_name: i for i, p in enumerate(ordered)}

    def immediately_follows(enclosing_name: str, target_name: str) -> bool:
        enclosing_idx = index_by_name.get(enclosing_name)
        target_idx = index_by_name.get(target_name)
        if enclosing_idx is None or target_idx is None:
            return False
        if target_idx <= enclosing_idx:
            return False
        # A phantom "." paragraph (cobolparser's empty-artifact node for a
        # bare "." line sitting before the next paragraph's header) is not
        # real code standing between enclosing and target -- it rides along
        # the same way _expand_thru_range already tolerates it elsewhere in
        # this file, rather than disqualifying an otherwise textually
        # adjacent exit-only paragraph.
        return all(
            ordered[i].paragraph_name == "."
            for i in range(enclosing_idx + 1, target_idx)
        )

    by_target: dict[str, list[tuple[GoStatement, str, bool, bool]]] = {}
    disqualified_by_computed_goto: set[str] = set()
    for paragraph in paragraphs:
        for statement, nested, in_boundary in _go_statements_with_nesting(
            paragraph.statements
        ):
            target = _go_statement_target(statement)
            if target is not None and target in exit_only_names:
                by_target.setdefault(target, []).append(
                    (statement, paragraph.paragraph_name, nested, in_boundary)
                )
                continue
            if target is None:
                # A computed or multi-target GO TO: every name it could
                # possibly reach is a standing GO TO edge into that
                # paragraph, regardless of whether this per-site loop
                # can ever resolve it to a single safe target.
                disqualified_by_computed_goto.update(
                    name
                    for name in _go_statement_raw_targets(statement)
                    if name in exit_only_names
                )

    plans: list[GotoExitPlan] = []
    notes: list[str] = []
    for target_name in sorted(disqualified_by_computed_goto & by_target.keys()):
        sites = by_target.pop(target_name)
        notes.append(
            f"GO TO {target_name} left as-is at {len(sites)} site(s) -- "
            f"also named by a computed or multi-target GO TO elsewhere in "
            f"the program, which cannot be safely excluded on a per-site "
            f"basis"
        )

    confirmed: set[str] = set()
    remaining = dict(by_target)
    last_problems: dict[str, list[str]] = {}
    while remaining:
        go_to_targets = base_go_to_targets - confirmed
        go_to_fallthrough = _go_to_fallthrough_targets(program, go_to_targets)
        newly_confirmed: list[str] = []

        for target_name, sites in sorted(remaining.items()):
            problems: list[str] = []
            computed: list[tuple[GoStatement, str, str, tuple[int, int]]] = []
            for statement, enclosing, nested, in_boundary in sites:
                if enclosing in go_to_targets:
                    problems.append(
                        f"line {statement.location.line}: enclosing paragraph "
                        f"'{enclosing}' is itself a GO TO target elsewhere in "
                        f"the program"
                    )
                    continue
                if enclosing in go_to_fallthrough:
                    problems.append(
                        f"line {statement.location.line}: enclosing paragraph "
                        f"'{enclosing}' is reached only by falling through "
                        f"past a GO TO target elsewhere in the program"
                    )
                    continue
                if enclosing not in top_level_names:
                    problems.append(
                        f"line {statement.location.line}: enclosing paragraph "
                        f"'{enclosing}' belongs to a SECTION -- SECTION-scoped "
                        f"enclosing paragraphs are not yet supported"
                    )
                    continue
                if not immediately_follows(enclosing, target_name):
                    problems.append(
                        f"line {statement.location.line}: '{target_name}' is "
                        f"not the paragraph immediately following enclosing "
                        f"paragraph '{enclosing}' in source order -- a "
                        f"PERFORM ... THRU range ending at '{target_name}' "
                        f"could cover real paragraphs between them, whose "
                        f"early-exit-path behavior this splice would change"
                    )
                    continue
                if enclosing in range_ends:
                    problems.append(
                        f"line {statement.location.line}: the PERFORM at line "
                        f"{range_ends[enclosing]} ends its range at enclosing "
                        f"paragraph '{enclosing}', not at '{target_name}' -- "
                        f"the GO TO leaves that PERFORM's range for real, "
                        f"so it is not an early return there"
                    )
                    continue
                if in_boundary:
                    problems.append(
                        f"line {statement.location.line}: nested inside another "
                        f"boundary statement's clause body -- a mock of the "
                        f"enclosing statement re-runs it from a lifted body "
                        f"this plan does not rewrite"
                    )
                    continue

                if nested:
                    # Never true for a GoStatement in practice (it has no
                    # clause bodies of its own), checked anyway for the same
                    # reason _nested_site_span checks it: defense in depth
                    # against a future statement-model change.
                    if _nested_statement_lists(statement):
                        problems.append(
                            f"line {statement.location.line}: has conditional "
                            f"clause bodies of its own"
                        )
                        continue
                    span, reason = nested_statement_span(statement, scope_map, lines)
                    if span is None:
                        problems.append(f"line {statement.location.line}: {reason}")
                        continue
                else:
                    line_problem = statement_top_level_problem(
                        statement, scope_map, lines
                    )
                    if line_problem is not None:
                        problems.append(
                            f"line {statement.location.line}: the GO TO "
                            f"statement {line_problem}"
                        )
                        continue
                    span = statement_span(statement, boundaries, last_line, lines)

                computed.append((statement, enclosing, "PARAGRAPH", span))

            last_problems[target_name] = problems
            if problems:
                continue

            for statement, enclosing, exit_kind, span in computed:
                plans.append(
                    GotoExitPlan(
                        statement=statement,
                        paragraph_name=enclosing,
                        exit_kind=exit_kind,
                        span=span,
                    )
                )
            newly_confirmed.append(target_name)

        if not newly_confirmed:
            break
        for target_name in newly_confirmed:
            del remaining[target_name]
            confirmed.add(target_name)

    for target_name, sites in sorted(remaining.items()):
        problems = last_problems[target_name]
        notes.append(
            f"GO TO {target_name} left as-is at {len(sites)} site(s) -- "
            f"not all are safe to splice into EXIT PARAGRAPH "
            f"automatically: " + "; ".join(problems)
        )

    return plans, notes


def neutralized_goto_targets(program, scope_map, lines: list[str]) -> frozenset[str]:
    """The exit-only paragraph names every GO TO of which is covered by a
    GotoExitPlan -- i.e. the targets `find_goto_exit_plans` fully
    neutralizes (all-or-nothing per target, so a name appears here only
    when EVERY GO TO naming it gets spliced into EXIT PARAGRAPH). The
    shared narrowing set for every consumer that must agree with what the
    splicer actually compiles: `find_terminator_plans`' hazard sets and
    `_reachable_paragraphs`/`check_test_case`'s reachable-set walk
    (2026-08-25 -- before that, the reachability BFS still modeled the
    spliced-away GO TO as a live edge, so the "GO TO <own-exit-label>"
    idiom's bare-EXIT landing pad cascaded fall-through reachability
    through the entire rest of the program, demanding mocks for
    boundaries the compiled test can never execute)."""
    plans, _notes = find_goto_exit_plans(program, scope_map, lines)
    return frozenset(
        target
        for target in (_go_statement_target(plan.statement) for plan in plans)
        if target is not None
    )


def find_terminator_plans(
    surface: MockSurface,
    program,
    suite: MockTestSuite,
    scope_map,
    lines: list[str],
) -> tuple[list[TerminatorPlan], list[RefusalReason]]:
    """For every STOP RUN(RUN-form)/GOBACK reachable from at least one test
    case, decide whether it is safely neutralizable and return either a
    TerminatorPlan or an UNSUPPORTED_TERMINATOR_LAYOUT RefusalReason --
    never both for the same physical statement. Sites unreachable from
    every test case are omitted entirely (left untouched, like any other
    unmocked boundary).

    Safe means: the terminator's enclosing paragraph is a top-level
    paragraph -- or a SECTION member entered one way only
    (`_section_member_modes`: inside a `PERFORM <section-name>` range, or
    only ever PERFORMed by its own name, counting every case's own
    perform_target; see docs/2026-10-27-section-member-terminators-design.md)
    -- is reachable from the test's own
    perform_target via `_plain_perform_edges_from` (a chain of nothing but
    plain, unconditional, top-level PERFORM statements), and no paragraph
    anywhere on that whole restricted-reachable chain -- not just the
    terminator's own paragraph, but every paragraph the case's
    over-inclusive chain_performs instrumentation would touch, including
    the perform_target itself -- is ever a GO TO target anywhere in the
    program, or is missing from `top_level_names` (a dead-end BFS target
    that turned out to be a SECTION name rather than a real paragraph, e.g.
    `PERFORM some-section`). The terminator's own statement must also own
    its line/have a validated span (`site.span`/`site.unspliceable_reason`,
    populated by a broadened `annotate_nested_sites` call the caller must
    have already made), and every intermediate PERFORM on the case's
    restricted-reachable chain must also own its own line
    (`statement_top_level_problem`, checked once per case since the same
    chain_performs set is a candidate for every terminator that case
    reaches -- the design doc describes a per-terminator backward walk,
    but this implementation computes one forward, whole-case reachable
    set instead and reuses it for every terminator that case finds,
    which is why the GO-TO/SECTION checks below are also computed over
    the whole chain rather than just the terminator's own paragraph: any
    terminator sharing this case's chain_performs would be instrumented
    with the same hazardous paragraph regardless of whether it sits on
    that specific terminator's own ancestor path -- noted by the
    2026-07-09 final branch review: this over-inclusiveness is fail-SAFE
    (it can only ever cause an extra, unnecessary refusal of a terminator
    that would actually have been fine, never miss an unsafe one), but it
    is a real usability cliff on large paragraphs -- a GO-TO target or
    SECTION member anywhere in the case's reachable set refuses every
    terminator that case finds, even ones with no path through the
    hazardous paragraph at all. If this bites in practice, narrowing to
    the terminator's actual ancestor path is the fix, not loosening the
    check). Once ANY test case
    finds a given terminator unsafe, it is
    refused permanently -- fail-closed, regardless of what other test
    cases' paths say. `scope_map`/`lines` must be the same
    `collect_scope_map(program, lines)` result and normalized lines the
    caller already computed for `annotate_nested_sites`."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return [], []

    top_level_names = {p.paragraph_name for p in procedure.paragraphs}
    # A paragraph fully covered by a GotoExitPlan (every GO TO naming it
    # gets spliced into EXIT PARAGRAPH/SECTION at its own call site) is no
    # longer entered via GO TO at all once splicing runs -- narrow
    # go_to_targets before deriving go_to_fallthrough from it, so a
    # terminator chain whose only obstacle was this exact idiom
    # (docs/2026-08-17-goto-exit-paragraph-simplification-design.md)
    # qualifies for neutralization here too. _safe_section_entry_points'
    # own internal go_to_targets check is deliberately left un-narrowed --
    # see find_goto_exit_plans' docstring.
    neutralized_goto = neutralized_goto_targets(program, scope_map, lines)
    safe_section_entries = _safe_section_entry_points(program)
    # How each SECTION member is entered, across the whole program and
    # every case's own PERFORM target: a member running inside a `PERFORM
    # <section-name>` range leaves with EXIT SECTION, one only ever
    # PERFORMed by its own name with EXIT PARAGRAPH; one entered both ways
    # has no mode and is refused (2026-10-27; before, only a section's
    # first paragraph, entered via its section name, was supported).
    section_names = {name for name in getattr(procedure, "_sections", {}) if name}
    case_entries = {
        name
        for case in suite.analysis_cases()
        for name in (case.perform_target, case.perform_thru)
        if name
    }
    member_why_not: dict[str, str] = {}
    main_line_sections: set[str] = set()
    member_modes = _section_member_modes(
        program,
        paragraph_entries=case_entries - section_names,
        section_entries=case_entries & section_names,
        why_not=member_why_not,
        main_line_sections=main_line_sections,
    )
    # Every section's nameless main line is paragraph '' (a phantom "."
    # node is "."): which section a terminator there sits in comes from
    # the statement itself, never from that shared name.
    main_line_owner: dict[int, str] = {}
    for section_name, section in procedure._sections.items():
        if not section_name:
            continue
        for paragraph in section.paragraphs:
            if (paragraph.paragraph_name or "").strip("."):
                continue
            for statement in _find_statements_of_type(paragraph.statements, object):
                main_line_owner[id(statement)] = section_name

    def no_mode_reason(name: str) -> str:
        return member_why_not.get(
            name, "it is not entered one single way the analysis can verify"
        )

    member_names = {
        paragraph.paragraph_name
        for section in procedure._sections.values()
        for paragraph in section.paragraphs
    }
    # A chain PERFORM held in a member running in section mode must end
    # with EXIT SECTION too (issue #338).
    section_chain_performs = {
        id(perform)
        for section in procedure._sections.values()
        for paragraph in section.paragraphs
        if member_modes.get(paragraph.paragraph_name) == "SECTION"
        for perform, _nested, _in_boundary in _plain_perform_statements(
            paragraph.statements, include_loops=True
        )
    }
    # The GO TO fall-through hazard map is per case: a walk stops at the
    # end of a section entered only via `PERFORM <section-name>` -- unless
    # the case's own entry point names one of its members directly -- the
    # same stop `_reachable_paragraphs` applies (issue #259).
    section_members: dict[str, list[str]] = {}
    for section_name, section in getattr(procedure, "_sections", {}).items():
        if section_name:
            section_members.setdefault(
                section_name, [p.paragraph_name for p in section.paragraphs]
            )
    safe_sections = _fallthrough_safe_sections(program)
    # An `EXEC SQL WHENEVER ... GO TO` target is a GO TO target only for a
    # case whose mocks can make the WHENEVER fire (issue #244): a success-
    # path case never takes the jump, so the handler's own terminator is
    # not its hazard. Each hazard-set variant is computed once.
    # Likewise a CICS HANDLE CONDITION label, for the conditions the case's
    # mocks raise (issue #268).
    target_sets: dict[tuple[bool, frozenset[str]], set[str]] = {}
    fallthrough_cache: dict[
        tuple[bool, frozenset[str], tuple[str, str | None]], dict[str, str]
    ] = {}
    ordered = _source_ordered_paragraphs(procedure)
    paragraph_names = {p.paragraph_name for p in _all_paragraphs(procedure)}

    def hazards(
        include_whenever: bool,
        conditions: frozenset[str],
        target: str,
        thru: str | None,
    ) -> tuple[set[str], dict[str, str]]:
        entry = frozenset(name for name in (target, thru) if name)
        if (include_whenever, conditions) not in target_sets:
            target_sets[(include_whenever, conditions)] = (
                _go_to_targets(
                    program,
                    include_whenever=include_whenever,
                    cics_conditions=conditions,
                )
                - neutralized_goto
            )
        targets = target_sets[(include_whenever, conditions)]
        key = (include_whenever, conditions, (target, thru))
        if key not in fallthrough_cache:
            # A GO TO to the end of a closed `PERFORM X THRU X-EXIT` range
            # returns from that PERFORM; it never falls past X-EXIT.
            closed = _closed_perform_ranges(
                program,
                ordered,
                section_members,
                driver_range=(
                    (target, thru or target) if target in paragraph_names else None
                ),
                exclude_seeds=entry,
            )
            fallthrough_cache[key] = _go_to_fallthrough_targets(
                program,
                targets,
                _paragraph_safe_section_map(section_members, safe_sections, entry),
                closed,
            )
        return targets, fallthrough_cache[key]

    whenever_only = _go_to_targets(program) - _go_to_targets(
        program, include_whenever=False
    )
    whenever_line = whenever_lines(program) if whenever_only else {}
    terminator_sites = {
        id(s.statement): s for s in surface.boundary_sites if is_terminator_site(s)
    }

    plans_by_statement: dict[int, TerminatorPlan] = {}
    reasons: list[RefusalReason] = []
    refused_statement_ids: set[int] = set()

    from mockymock.analysis.flow_mocks import resolved_flow_targets

    reach_cache: dict[tuple[str, str | None], set[str]] = {}
    # A case PERFORMing THRU the program's last paragraph runs the main line
    # to the end of the program: a STOP RUN/GOBACK it only falls or jumps
    # into (never PERFORMs) ends it with `GO TO UT-PROGRAM-END`.
    last_paragraph = program_last_paragraph(program)
    perform_entered: dict[str, str] | None = None

    # Hook PERFORM steps reach terminators exactly like a test case's own
    # PERFORM does (suite hooks), so they need plans/refusals too.
    for case in suite.analysis_cases():
        # A terminator inside a paragraph/section this case flow-mocks
        # (MOCK PARAGRAPH/SECTION) is unreachable for this case -- the mock
        # dispatch replaces the body -- so it must not demand a plan or a
        # refusal on this case's account. Other cases still evaluate it.
        mocked_paragraphs, mocked_sections = resolved_flow_targets(program, case)
        mocked_flow_names = mocked_paragraphs | mocked_sections
        can_fire = whenever_can_fire(program, case.mocks)
        conditions = raised_conditions(case.mocks)
        go_to_targets, go_to_fallthrough = hazards(
            can_fire, conditions, case.perform_target, case.perform_thru
        )
        reachable, _ = _reachable_paragraphs(
            program,
            case.perform_target,
            case.perform_thru,
            skip_traversal=mocked_flow_names,
            neutralized_goto=neutralized_goto,
            follow_whenever=can_fire,
            cics_conditions=conditions,
        )
        reachable -= mocked_flow_names
        entered_sections: set[str] = set()
        loop_performs: list[PerformStatement] = []
        safe_names, chain_performs = _plain_perform_edges_from(
            program,
            case.perform_target,
            safe_section_entries,
            member_modes,
            main_line_sections=main_line_sections,
            entered_sections=entered_sections,
            loop_edges=loop_performs,
        )
        # Where the case can ALSO get to through a PERFORM the chain does
        # not follow (THRU, TIMES, one inside a CALL's ON EXCEPTION, a
        # SORT/MERGE/XML PARSE procedure): a terminator there returns into
        # that PERFORM with no check after it, and the run goes on.
        unchecked_reach = _unchecked_perform_reach(
            program,
            reachable,
            {id(perform) for perform, _nested in chain_performs},
            reach_cache,
        )
        chain_section_names = safe_names - (top_level_names | member_modes.keys())
        chain_go_to_names = safe_names & go_to_targets
        chain_fallthrough_names = safe_names & go_to_fallthrough.keys()

        chain_problem: str | None = None
        chain_spans: dict[int, tuple[int, int]] = {}
        for perform, nested in chain_performs:
            if nested:
                # The check must land right after the PERFORM inside its own
                # IF/EVALUATE branch or inline PERFORM body (issue #337):
                # after the enclosing END-IF/END-PERFORM, the rest of the
                # branch would still run and an inline loop keep iterating.
                span, line_problem = nested_statement_span(perform, scope_map, lines)
                if span is not None:
                    chain_spans[id(perform)] = span
                    continue
                chain_problem = (
                    f"an intermediate PERFORM {perform.target_paragraph} at "
                    f"line {perform.location.line} is nested inside a "
                    f"conditional/loop body and {line_problem} -- the "
                    f"early-exit check can't be placed right after it "
                    f"inside its branch"
                )
                break
            line_problem = statement_top_level_problem(perform, scope_map, lines)
            if line_problem is not None:
                chain_problem = (
                    f"an intermediate PERFORM {perform.target_paragraph} at "
                    f"line {perform.location.line} {line_problem} -- "
                    f"inserting the early-exit check after it would corrupt "
                    f"sibling code sharing its line"
                )
                break

        if chain_problem is None:
            chain_problem = _thru_tail_problem(program, case)

        qualified_keys: list[int] = []

        for site in surface.sites_in(reachable):
            key = id(site.statement)
            if key not in terminator_sites or key in refused_statement_ids:
                continue

            paragraph_name = site.paragraph_name
            existing = plans_by_statement.get(key)
            owner = main_line_owner.get(key)
            problem = None
            if owner is not None and owner not in entered_sections:
                problem = (
                    f"is in the main line of SECTION '{owner}', which this "
                    f"test's chain of plain PERFORM statements from "
                    f"'{case.perform_target}' never enters with "
                    f"`PERFORM {owner}` -- it is reached another way (a GO "
                    f"TO, a conditional or looping PERFORM, or falling "
                    f"through), so no EXIT SECTION is known to return "
                    f"correctly from it"
                )
            elif (
                paragraph_name not in top_level_names
                and paragraph_name not in member_modes
            ):
                problem = (
                    f"is inside SECTION member '{paragraph_name}', and "
                    f"{no_mode_reason(paragraph_name)} -- no single EXIT "
                    f"PARAGRAPH/SECTION is known to return correctly from it"
                )
            elif paragraph_name in go_to_targets and paragraph_name in whenever_only:
                problem = (
                    f"is unsafe to test automatically: paragraph "
                    f"'{paragraph_name}' is the GO TO target of the EXEC SQL "
                    f"WHENEVER at line {whenever_line.get(paragraph_name, 0)}, "
                    f"and this test case's SQL mocks can set SQLCODE so that "
                    f"it fires -- a paragraph entered via GO TO can't "
                    f"reliably use EXIT PARAGRAPH to signal an early exit "
                    f"back to its caller. A case whose SQL mocks only "
                    f"`MOVE 0 TO SQLCODE` (no IF/EVALUATE, no ROWS when "
                    f"NOT FOUND is active, no WHENEVER SQLWARNING) never "
                    f"takes the jump and is not refused for it"
                )
            elif paragraph_name in go_to_targets:
                problem = (
                    f"is unsafe to test automatically: paragraph "
                    f"'{paragraph_name}' is itself a GO TO target "
                    f"somewhere in this program, and a paragraph that can "
                    f"be entered via GO TO can't reliably use EXIT "
                    f"PARAGRAPH to signal an early exit back to its "
                    f"caller -- mockymock refuses rather than risk "
                    f"generating a test that silently runs further than "
                    f"it should. To make this testable, replace the "
                    f"`GO TO {paragraph_name}` with structured PERFORM/"
                    f"EXIT PARAGRAPH logic (e.g. if it exists purely as "
                    f"an early exit, an `EXIT PARAGRAPH` in its place "
                    f"usually removes the need for the jump entirely)"
                )
            elif paragraph_name in go_to_fallthrough:
                problem = (
                    f"is unsafe to test automatically: control reaches it "
                    f"by falling through past the end of paragraph "
                    f"'{go_to_fallthrough[paragraph_name]}', which is a GO "
                    f"TO target elsewhere in this program -- code entered "
                    f"via GO TO never goes through PERFORM, so mockymock "
                    f"can't insert an early-exit check here that would "
                    f"correctly return to the right caller. Fixing the "
                    f"`GO TO {go_to_fallthrough[paragraph_name]}` (e.g. "
                    f"replacing it with `EXIT PARAGRAPH` if it exists "
                    f"purely as an early exit) would remove this hazard"
                )
            elif paragraph_name not in safe_names:
                problem = (
                    f"is reachable from '{case.perform_target}' but not via "
                    f"a chain of plain, unconditional, top-level PERFORM "
                    f"statements -- this is the only shape this feature can "
                    f"safely neutralize today"
                )
            elif paragraph_name in unchecked_reach:
                problem = (
                    f"is also reached through {unchecked_reach[paragraph_name]}"
                    f", which runs on after the early exit returns into it "
                    f"(nothing stops a PERFORM ... THRU, VARYING or TIMES, "
                    f"or an implicit PERFORM, at the early exit), so the "
                    f"test would carry on past the point where the real "
                    f"program stops"
                )
            elif chain_section_names:
                bad_name = sorted(chain_section_names)[0]
                if bad_name in member_names:
                    what = (
                        f"a SECTION member, and {no_mode_reason(bad_name)} "
                        f"-- no single EXIT "
                        f"PARAGRAPH/SECTION is known to return correctly "
                        f"from it"
                    )
                elif bad_name in section_names:
                    what = (
                        "a SECTION whose PERFORM range runs a member that "
                        "cannot carry the early-exit check (it is entered "
                        "another way too, or holds a PERFORM with no mode)"
                    )
                else:
                    what = "not a paragraph or SECTION of this program"
                problem = (
                    f"is only reachable through this test's own early-exit "
                    f"propagation chain by way of '{bad_name}', {what}"
                )
            elif chain_go_to_names:
                # paragraph_name can't be a member here: the preceding elif
                # already excluded it from go_to_targets, and chain_go_to_names
                # is a subset of go_to_targets.
                bad_name = sorted(chain_go_to_names)[0]
                problem = (
                    f"is unsafe to test automatically: propagating this "
                    f"early exit back to the test would require passing "
                    f"through paragraph '{bad_name}', which is itself a "
                    f"GO TO target somewhere in this program -- mockymock "
                    f"can't safely instrument a paragraph that can be "
                    f"entered other than via PERFORM. To make this "
                    f"testable, replace the `GO TO {bad_name}` with "
                    f"structured PERFORM/EXIT PARAGRAPH logic (e.g. if it "
                    f"exists purely as an early exit, an `EXIT PARAGRAPH` "
                    f"in its place usually removes the need for the jump "
                    f"entirely)"
                )
            elif chain_fallthrough_names:
                bad_name = sorted(chain_fallthrough_names)[0]
                problem = (
                    f"is unsafe to test automatically: propagating this "
                    f"early exit back to the test would require passing "
                    f"through paragraph '{bad_name}', which is reached by "
                    f"falling through past the end of paragraph "
                    f"'{go_to_fallthrough[bad_name]}' -- a GO TO target "
                    f"elsewhere in this program -- rather than via "
                    f"PERFORM. mockymock can't safely instrument a "
                    f"paragraph reached this way. Fixing the "
                    f"`GO TO {go_to_fallthrough[bad_name]}` (e.g. "
                    f"replacing it with `EXIT PARAGRAPH` if it exists "
                    f"purely as an early exit) would remove this hazard"
                )
            elif site.nested and site.span is None:
                problem = (
                    f"is nested inside a conditional/loop body and cannot "
                    f"be safely spliced: "
                    f"{site.unspliceable_reason or _UNANNOTATED}"
                )
            elif not site.nested and site.unspliceable_reason:
                problem = (
                    f"{site.unspliceable_reason} -- splicing it would "
                    f"corrupt sibling code sharing its line(s)"
                )
            elif chain_problem is not None:
                problem = chain_problem
            else:
                problem = (
                    _terminator_return_code(site.statement)[1]
                    or _cics_resp_field(site.statement)[1]
                )

            if problem is not None and case.perform_thru == last_paragraph:
                # The case runs the main line to the end of the program
                # (2026-11-02): a terminator it only falls or jumps into,
                # never PERFORMs, can end it with GO TO UT-PROGRAM-END.
                if perform_entered is None:
                    perform_entered = _perform_frame_reach(program, reach_cache)
                end_problem = _main_line_end_problem(
                    site, perform_entered, declarative_paragraphs(program)
                )
                if end_problem is None and existing is None:
                    plans_by_statement[key] = TerminatorPlan(
                        site=terminator_sites[key],
                        exit_kind="PROGRAM",
                        return_code=_terminator_return_code(site.statement)[0],
                    )
                    continue
                if (
                    end_problem is None
                    and existing is not None
                    and existing.exit_kind == "PROGRAM"
                ):
                    continue
                problem += (
                    f"; nor can it end the main line PERFORM "
                    f"{case.perform_target} THRU {case.perform_thru} runs: it "
                    + (
                        end_problem
                        or "also ends another test case's PERFORM with EXIT "
                        "PARAGRAPH, and one statement cannot end both ways"
                    )
                )
            elif (
                problem is None
                and existing is not None
                and existing.exit_kind == "PROGRAM"
            ):
                problem = (
                    "ends the main line of a test case that PERFORMs THRU "
                    "the program's last paragraph, and this test case "
                    "needs it to end its own PERFORM with EXIT PARAGRAPH "
                    "instead -- one statement cannot end both ways"
                )
            if problem is not None:
                reasons.append(
                    RefusalReason(
                        code="UNSUPPORTED_TERMINATOR_LAYOUT",
                        message=(
                            f"{_terminator_name(site)} at line {site.line} (paragraph "
                            f"'{paragraph_name}') {problem}"
                        ),
                    )
                )
                refused_statement_ids.add(key)
                plans_by_statement.pop(key, None)
                continue

            if key not in plans_by_statement:
                exit_kind = member_modes.get(paragraph_name, "PARAGRAPH")
                plans_by_statement[key] = TerminatorPlan(
                    site=terminator_sites[key],
                    exit_kind=exit_kind,
                    return_code=_terminator_return_code(site.statement)[0],
                    resp_field=_cics_resp_field(site.statement)[0],
                )
            qualified_keys.append(key)

        for key in qualified_keys:
            plan = plans_by_statement[key]
            existing_ids = {id(p) for p in plan.chain_performs}
            for perform, _nested in chain_performs:
                if id(perform) not in existing_ids:
                    plan.chain_performs.append(perform)
                    existing_ids.add(id(perform))
            plan.chain_spans.update(chain_spans)
            loop_ids = {id(perform) for perform in plan.loop_performs}
            for perform in loop_performs:
                if id(perform) not in loop_ids:
                    plan.loop_performs.append(perform)
                    loop_ids.add(id(perform))
            for perform, _nested in chain_performs:
                if id(perform) in section_chain_performs:
                    plan.chain_exit_kinds[id(perform)] = "SECTION"

    return list(plans_by_statement.values()), reasons


#: The paragraph the splicer appends after a program's last paragraph when
#: a terminator ends the main line (`TerminatorPlan.exit_kind` "PROGRAM"):
#: the terminator becomes `GO TO` it, and a case PERFORMing THRU the
#: program's last paragraph PERFORMs THRU it instead, so reaching it
#: returns to the test.
PROGRAM_END_PARAGRAPH = "UT-PROGRAM-END"


def program_last_paragraph(program) -> str | None:
    """The name of the last paragraph of the PROCEDURE DIVISION in source
    order, or None when there is none (or the order cannot be trusted, or
    the last one is a nameless main line or a phantom)."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return None
    ordered = _source_ordered_paragraphs(procedure)
    if not ordered:
        return None
    name = str(ordered[-1].paragraph_name or "")
    if not name.strip("."):
        return None
    if sum(1 for p in ordered if p.paragraph_name == name) > 1:
        return None
    return name


def program_end_thru(program, terminator_plans) -> str | None:
    """The program's last paragraph when a plan ends the main line at
    `PROGRAM_END_PARAGRAPH`, else None: the driver then appends that
    paragraph after the program's last one and PERFORMs THRU it wherever a
    case names that last paragraph (`build_driver(program_end=...)`)."""
    if not any(plan.exit_kind == "PROGRAM" for plan in terminator_plans):
        return None
    return program_last_paragraph(program)


def _main_line_end_problem(
    site,
    perform_entered: dict[str, str],
    declarative_names: frozenset[str] | set[str] = frozenset(),
) -> str | None:
    """Why a terminator a case running THRU the program's last paragraph
    reaches cannot end that case with `GO TO UT-PROGRAM-END`, or None.

    The GO TO returns to the test only when the test's own PERFORM is the
    one active PERFORM at that moment: the terminator must never run
    inside a PERFORM of the program's own (any PERFORM, THRU range, SECTION
    PERFORM or SORT/MERGE/XML procedure that can reach its paragraph), or
    the jump would leave that PERFORM's range for good."""
    if site.category is not None:
        return "is an EXEC CICS command, not a STOP RUN/GOBACK"
    if site.paragraph_name in declarative_names:
        return (
            "is inside DECLARATIVES, which run under a PERFORM of their "
            "own and which no GO TO may leave"
        )
    if site.paragraph_name in perform_entered:
        return (
            f"is also reached through {perform_entered[site.paragraph_name]}, "
            f"so it can run inside a PERFORM of the program's own, which "
            f"a GO TO to the end of the program would leave for good"
        )
    if site.nested and site.span is None:
        return (
            f"is nested inside a conditional/loop body and cannot be "
            f"safely spliced: {site.unspliceable_reason or _UNANNOTATED}"
        )
    if not site.nested and site.unspliceable_reason:
        return (
            f"{site.unspliceable_reason} -- splicing it would corrupt "
            f"sibling code sharing its line(s)"
        )
    return _terminator_return_code(site.statement)[1]


def _perform_edges(
    program, reachable: set[str] | None, checked_ids: set[int]
) -> list[tuple[str, str | None, str]]:
    """(start, thru, description) of every PERFORM-like edge held by a
    paragraph in `reachable` (every paragraph when None) other than the
    PERFORMs in `checked_ids`: out-of-line PERFORMs, SORT/MERGE INPUT/OUTPUT
    PROCEDUREs and XML PARSE PROCESSING PROCEDUREs."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return []
    edges: list[tuple[str, str | None, str]] = []
    for paragraph in _all_paragraphs(procedure):
        if reachable is not None and paragraph.paragraph_name not in reachable:
            continue
        for perform in _find_statements_of_type(paragraph.statements, PerformStatement):
            if id(perform) in checked_ids or not perform.target_paragraph:
                continue
            if perform.inline_statements:
                continue
            edges.append(
                (
                    perform.target_paragraph,
                    perform.thru_paragraph,
                    f"the PERFORM {perform.target_paragraph}"
                    + (
                        f" THRU {perform.thru_paragraph}"
                        if perform.thru_paragraph
                        else ""
                    )
                    + f" at line {perform.location.line}",
                )
            )
        for statement in _find_sort_merge_statements(paragraph.statements):
            for attr, thru_attr in (
                ("input_procedure", "input_procedure_thru"),
                ("output_procedure", "output_procedure_thru"),
            ):
                start = getattr(statement, attr, None)
                if start:
                    edges.append(
                        (
                            start,
                            getattr(statement, thru_attr, None),
                            f"the SORT/MERGE procedure {start} at line "
                            f"{statement.location.line}",
                        )
                    )
        for statement in _find_xml_parse_statements(paragraph.statements):
            start = getattr(statement, "processing_procedure", None)
            if start:
                edges.append(
                    (
                        start,
                        getattr(statement, "processing_procedure_thru", None),
                        f"the XML PARSE procedure {start} at line "
                        f"{statement.location.line}",
                    )
                )
    return edges


def _perform_frame_reach(
    program, cache: dict[tuple[str, str | None], set[str]]
) -> dict[str, str]:
    """paragraph name -> a PERFORM-like edge of the program (`_perform_edges`)
    whose PERFORM can still be active while that paragraph runs.

    From each edge's range (its paragraphs, or a SECTION's members), the
    walk follows every GO TO out of the range, and from each GO TO target
    the paragraphs control falls into (`_falls_through`); the range's own
    end returns from the PERFORM, so the walk does not fall past it. That
    is narrower than `_reachable_paragraphs`, whose fall-through closure
    falls past ANY paragraph that is a GO TO target somewhere, even where
    a PERFORM of it returns at its end: NIST's `PERFORM MOVE-WRITE-F1-32`
    of a paragraph the main line also GO TOs looked as if it reached the
    whole rest of the program. A program with EXEC SQL or EXEC CICS (a
    WHENEVER or HANDLE CONDITION is a GO TO no statement shows), a range
    that cannot be expanded, or a GO TO target that cannot be placed in
    source order falls back to `_reachable_paragraphs` (over-inclusive,
    never under)."""
    from cobolparser.models.sql_statements import ExecSQLStatement
    from cobolparser.parsers.statements.ibm_exec_statements import (
        ExecCicsStatement,
    )

    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return {}
    edges = _perform_edges(program, None, set())
    ordered = _source_ordered_paragraphs(procedure)
    paragraphs = _all_paragraphs(procedure)
    precise = ordered is not None and not any(
        _find_statements_of_type(p.statements, (ExecSQLStatement, ExecCicsStatement))
        for p in paragraphs
    )
    sequence = ordered or []
    names = [p.paragraph_name for p in sequence]
    index: dict[str, int] = {}
    for position, name in enumerate(names):
        if name in index:
            precise = False  # a duplicated name cannot be placed
        index[name] = position
    sections = {
        name: [p.paragraph_name for p in section.paragraphs]
        for name, section in getattr(procedure, "_sections", {}).items()
        if name
    }

    def resolve(name: str) -> list[int] | None:
        if name in sections:
            members = [index[m] for m in sections[name] if m in index]
            return members or None
        return [index[name]] if name in index else None

    def falls_from(position: int) -> list[int]:
        """`position` and the paragraphs control falls into after it."""
        chain = [position]
        while _falls_through(sequence[chain[-1]]) and chain[-1] + 1 < len(names):
            chain.append(chain[-1] + 1)
        return chain

    reach: dict[str, str] = {}
    for start, thru, what in edges:
        members = resolve(start) if precise else None
        if members is not None and thru:
            end = resolve(thru)
            members = (
                list(range(members[0], end[-1] + 1))
                if end is not None and end[-1] >= members[0]
                else None
            )
        found: set[str] | None = None
        if members is not None:
            in_range = set(members)
            seen = set(members)
            work = list(members)
            while work and found is None:
                paragraph = sequence[work.pop()]
                for go in _find_statements_of_type(paragraph.statements, GoStatement):
                    for target in _go_statement_raw_targets(go):
                        positions = resolve(target)
                        if positions is None:
                            found = set()  # unplaceable: fall back below
                            break
                        for position in positions[:1]:
                            if position in in_range:
                                continue
                            for reached in falls_from(position):
                                if reached not in seen:
                                    seen.add(reached)
                                    work.append(reached)
            if found is None:
                found = {names[position] for position in seen}
            else:
                found = None
        if found is None:
            key = (start, thru)
            if key not in cache:
                cache[key] = _reachable_paragraphs(program, start, thru)[0]
            found = cache[key]
        for name in found:
            reach.setdefault(name, what)
    return reach


def _unchecked_perform_reach(
    program,
    reachable: set[str],
    checked_ids: set[int],
    cache: dict[tuple[str, str | None], set[str]],
) -> dict[str, str]:
    """paragraph name -> a description of a PERFORM-like edge, among the
    paragraphs in `reachable`, that reaches it but is not one of
    `checked_ids` (the case's chain edges, each of which gets an early-exit
    check after it): a `PERFORM ... THRU`, a `PERFORM ... TIMES`, any
    PERFORM inside a CALL/file statement's clause body, or a SORT/MERGE
    INPUT/OUTPUT or XML PARSE PROCESSING PROCEDURE. Keyed by bare name like
    the rest of the planner, so it is over-inclusive for the nameless
    main lines, never under-inclusive."""
    reach: dict[str, str] = {}
    for start, thru, what in _perform_edges(program, reachable, checked_ids):
        key = (start, thru)
        if key not in cache:
            cache[key] = _reachable_paragraphs(program, start, thru)[0]
        for name in cache[key]:
            reach.setdefault(name, what)
    return reach


def _thru_tail_problem(program, case) -> str | None:
    """Why a terminator this case reaches can't be neutralized because of
    the case's own `PERFORM <target> THRU <thru>` (issue #211), or None.

    The neutralization ends the case's perform target with EXIT PARAGRAPH
    (directly, or through the chain checks). The driver's THRU range then
    carries on into the next paragraph of the range by fall-through, which
    the real program never reached. That is harmless only when every later
    paragraph of the range does nothing: an exit-only `X-EXIT. EXIT.`
    paragraph (the usual `PERFORM X THRU X-EXIT` idiom) or a phantom "."
    paragraph. Any other paragraph would run on the early-exit path, so
    the terminator is refused instead. A range that can't be expanded is
    refused too (the reachability gate reports why)."""
    thru = case.perform_thru
    if not thru or thru == case.perform_target:
        return None
    procedure = program.get_division("PROCEDURE")
    ordered = _source_ordered_paragraphs(procedure)
    members, reason = _expand_thru_range(
        ordered, case.perform_target, thru, "test case PERFORM"
    )
    if reason is not None:
        return (
            f"is reached through PERFORM {case.perform_target} THRU {thru}, "
            f"whose range cannot be expanded -- {reason.message}"
        )
    by_name = {p.paragraph_name: p for p in ordered or []}
    for name in members[1:]:
        paragraph = by_name.get(name)
        if name == "." or (
            paragraph is not None and _is_exit_only_paragraph(paragraph)
        ):
            continue
        return (
            f"is reached through PERFORM {case.perform_target} THRU {thru}: "
            f"once the terminator ends '{case.perform_target}', the THRU "
            f"range would fall through into '{name}', which the real "
            f"program never runs after the terminator -- PERFORM "
            f"{case.perform_target} on its own (or THRU an exit-only "
            f"paragraph right after it) to test this path"
        )
    return None
