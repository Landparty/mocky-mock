"""Control-flow reachability primitives used by the refusal gates and plan
finders.

Split out of the former monolithic `refusal.py` (2026-08-26 audit): this
module is the self-contained BFS over PerformStatement AND GoStatement
targets (see `_reachable_paragraphs`) plus its supporting GO TO
fall-through and section-safety helpers, kept separate from `_gates.py`'s
policy checks and `_plans.py`'s terminator/GO-TO-exit plan construction so
each concern is independently testable.

Reachability is a self-contained BFS over PerformStatement AND GoStatement
targets within the same program -- not cobolparser's ProgramFlowAnalyzer --
because that keeps this module's correctness checkable against the same
small set of verified attributes (CobolParagraph.statements,
CobolParagraph.location.line, PerformStatement.target_paragraph,
PerformStatement.thru_paragraph, GoStatement.target_paragraphs) the rest
of mockymock already depends on. A CALL is a leaf: it is never traversed
into, since the called program's source isn't part of this compilation
unit.

Flow-edge model (fail closed):
- PERFORM <paragraph> pushes the paragraph; PERFORM <section> pushes every
  paragraph of that section (a performed section executes all of them by
  fall-through).
- GO TO pushes every target -- a computed `GO TO A B C DEPENDING ON X`
  carries all of its targets in GoStatement.target_paragraphs. Targets may
  be paragraphs or sections. The BFS additionally closes over GO TO
  fall-through (2026-08-12 bug review): every reached GO TO target is
  walked forward through source order via `_falls_through`, and each
  paragraph reachable by falling off one's end is fed back into the BFS to
  a fixpoint -- without this, a boundary in a fallen-into paragraph passed
  every mock gate and then executed unmocked at runtime. (The same hazard
  for `find_terminator_plans` was already guarded: `_go_to_fallthrough_targets`
  walks source order forward from every GO TO target, via `_falls_through`,
  to find every paragraph reachable only by falling off the end of one --
  the same EXIT PARAGRAPH hazard spike #4 found for a direct GO TO target,
  since a paragraph reached this way was never PERFORMed either.)
- Any PERFORM/GO TO target that resolves to neither a paragraph nor a
  section is an UNKNOWN_PARAGRAPH-adjacent shape, surfaced by the callers
  of `_reachable_paragraphs` (see `_gates.py`).

See `.okf/analysis.md` for the full refusal-package overview.
"""

from __future__ import annotations

from cobolparser.models.program import CobolParagraph
from cobolparser.models.statements.control import (
    GoStatement,
    PerformStatement,
    StopStatement,
)
from cobolparser.models.statements.misc import (
    ExitStatement,
    GobackStatement,
    MergeStatement,
    SortStatement,
)

from mockymock.analysis.mock_surface import (
    _BOUNDARY_STATEMENT_TYPES,
    _XML_JSON_TYPES,
    XML_PROCESSING_PROCEDURE_RE,
    _all_paragraphs,
    _nested_statement_lists,
)

from ._types import RefusalReason


def _find_statements_of_type(
    statements: list, statement_type: type | tuple[type, ...]
) -> list:
    """Recursively collect statements of `statement_type`, including ones
    nested inside IF/EVALUATE/SEARCH branches, inline PERFORM bodies, and
    IO clause bodies -- reusing mock_surface.py's `_nested_statement_lists`
    rather than reimplementing nested-statement detection."""
    found = []
    for statement in statements:
        if isinstance(statement, statement_type):
            found.append(statement)
        for nested in _nested_statement_lists(statement):
            found.extend(_find_statements_of_type(nested, statement_type))
    return found


def _find_flow_statements(statements: list) -> list:
    """Recursively collect every PerformStatement and GoStatement in
    `statements`, including ones nested inside IF/EVALUATE/SEARCH branches,
    inline PERFORM bodies, and IO clause bodies (AT END, INVALID KEY, etc.)
    -- reusing mock_surface.py's `_nested_statement_lists` rather than
    reimplementing nested-statement detection.
    """
    return _find_statements_of_type(statements, (PerformStatement, GoStatement))


def _find_xml_parse_statements(statements: list) -> list:
    """Recursively collect every XML PARSE statement in `statements`.
    `XML PARSE doc PROCESSING PROCEDURE p [THRU q]` performs `p` (or the
    range) once per XML event -- an implicit PERFORM edge with no
    PerformStatement behind it, exactly like a SORT/MERGE's INPUT/OUTPUT
    PROCEDURE, and modeled the same way in `_reachable_paragraphs`."""
    if not _XML_JSON_TYPES:
        return []
    return [
        statement
        for statement in _find_statements_of_type(statements, _XML_JSON_TYPES)
        if getattr(statement, "action", None) == "PARSE"
    ]


def _find_sort_merge_statements(statements: list) -> list:
    """Recursively collect every SortStatement/MergeStatement in
    `statements`, same traversal as `_find_flow_statements`. A
    SORT/MERGE's INPUT/OUTPUT PROCEDURE names are an implicit PERFORM
    edge the reachability BFS must follow even though the AST node isn't
    a PerformStatement -- otherwise a RELEASE/RETURN (or any other
    boundary statement) reachable only through one of those paragraphs is
    invisible to the fail-closed gate, the same hazard class the GO TO
    fall-through / PERFORM-section / SEARCH-WHEN reachability fixes
    closed for other constructs (see the module docstring's "2026-07-07
    reachability-hole remediation" and .okf/analysis.md)."""
    return _find_statements_of_type(statements, (SortStatement, MergeStatement))


def _source_ordered_paragraphs(procedure) -> list | None:
    """All paragraphs sorted by location.line, or None when the sorted
    line sequence is not strictly increasing -- the runtime check behind
    the source-order guarantee THRU range expansion depends on. Verified
    to hold for plain and sectioned programs; a parser regression trips
    the None path and every expansion refuses fail-closed."""
    paragraphs = sorted(_all_paragraphs(procedure), key=lambda p: p.location.line)
    lines = [p.location.line for p in paragraphs]
    if any(later <= earlier for earlier, later in zip(lines, lines[1:], strict=False)):
        return None
    return paragraphs


def _expand_thru_range(
    ordered,
    start: str,
    thru: str,
    origin: str,
    missing_code: str = "UNSUPPORTED_PERFORM_THRU",
) -> tuple[list[str], RefusalReason | None]:
    """Names of every paragraph in the source-order slice [start..thru]
    inclusive (phantom '.' members ride along; they are empty artifacts),
    or ([], reason) for a degenerate range: unverifiable order, missing
    endpoint, ambiguous endpoint name, or thru preceding start. Never
    best-effort -- cobolparser's flow analyzer degrades to [start, end]
    endpoints when a range is malformed, but the refusal gate must not."""
    if ordered is None:
        return [], RefusalReason(
            code="UNSUPPORTED_PERFORM_THRU",
            message=(
                f"{origin}: PERFORM {start} THRU {thru} cannot be "
                f"range-expanded -- paragraph source order could not be "
                f"verified (location lines are not strictly increasing)"
            ),
        )
    names = [p.paragraph_name for p in ordered]
    for endpoint in (start, thru):
        count = names.count(endpoint)
        if count == 0:
            return [], RefusalReason(
                code=missing_code,
                message=(
                    f"{origin}: PERFORM {start} THRU {thru} endpoint "
                    f"'{endpoint}' not found in PROCEDURE DIVISION"
                ),
            )
        if count > 1:
            return [], RefusalReason(
                code="UNSUPPORTED_PERFORM_THRU",
                message=(
                    f"{origin}: PERFORM {start} THRU {thru} endpoint "
                    f"'{endpoint}' names {count} paragraphs -- the range "
                    f"is ambiguous"
                ),
            )
    i, j = names.index(start), names.index(thru)
    if j < i:
        return [], RefusalReason(
            code="UNSUPPORTED_PERFORM_THRU",
            message=(
                f"{origin}: PERFORM {start} THRU {thru} is a backwards "
                f"range ('{thru}' precedes '{start}' in source order)"
            ),
        )
    return names[i : j + 1], None


def _reachable_paragraphs(
    program,
    start: str,
    thru: str | None = None,
    skip_traversal: frozenset[str] | set[str] = frozenset(),
    neutralized_goto: frozenset[str] | set[str] = frozenset(),
) -> tuple[set[str], list[RefusalReason]]:
    """Return (reachable paragraph/section names, flow refusals), computed
    in a single BFS pass over PerformStatement and GoStatement edges, plus
    the implicit PERFORM edge a SORT/MERGE's INPUT PROCEDURE/OUTPUT
    PROCEDURE names represent (2026-08-17, SORT/MERGE mocking) -- see
    `_find_sort_merge_statements`.

    `skip_traversal` holds paragraph/section names mocked as flow targets
    (MOCK PARAGRAPH/SECTION) by the test case under analysis: a name in it
    is still recorded as reached (so the directive counts as matched and
    UNKNOWN_PARAGRAPH still works), but its body is never traversed -- no
    statements walked, no section members expanded -- because the mock
    dispatch replaces that body for this case, making everything inside it
    (boundary statements, terminators, further PERFORM/GO TO edges)
    unreachable. Callers that feed the result to `MockSurface.sites_in`
    must subtract these names first.

    The BFS additionally closes over the GO TO fall-through hazard
    (2026-08-12 bug review): a reached GO TO target whose body does not
    provably divert control (`_falls_through`) continues -- by ordinary
    sequential execution, not a flow edge -- into the next paragraph in
    source order, which therefore executes real statements (boundary
    sites included) without any PERFORM/GO TO edge naming it. Before this
    closure, a CALL/file-op/ACCEPT in such a paragraph passed every gate
    unmocked and then executed for real at runtime. The closure is the
    same fixpoint `union_executed_paragraphs` already applies for
    warning-waiving, and it fails closed (refusal, never a silent skip)
    when source order is unverifiable or a GO TO target cannot be
    anchored in it.

    2026-08-26: the walk (`_walk_fallthrough_from`) no longer cascades
    past the LAST paragraph of a SECTION `_fallthrough_safe_sections`
    proves is entered only via `PERFORM <section-name>` anywhere in the
    program -- reaching that exact point is where GnuCOBOL's own implicit
    PERFORM return marker fires, regardless of whether it was reached by
    plain fall-through or by an internal GO TO. Without this, a program's
    "several paragraphs each `GO TO` a shared, section-scoped exit label"
    idiom -- the common multi-caller shape `find_goto_exit_plans`' own
    per-enclosing-paragraph adjacency check can't neutralize (see that
    function's docstring) -- made every paragraph physically after the
    section look hazardous, demanding mocks for boundaries the compiled
    program never actually reaches. `start`/`thru` (this call's OWN entry
    point) additionally exclude any section either one enters by naming a
    member paragraph directly, since that DSL-level bypass of `PERFORM
    <section-name>` is invisible to the whole-program AST scan
    `_fallthrough_safe_sections` runs -- see `_paragraph_safe_section_map`.
    This only ever SHRINKS the reachable set (declines to add paragraphs
    fall-through would have added before), so it can only reduce refusals,
    never a soundness regression on its own -- and never changes what
    `find_goto_exit_plans`/`find_terminator_plans` actually splice, since
    neither reads this function's narrowed fall-through map.

    A PERFORM ... THRU pushes every paragraph of its source-order range
    (fall-through executes them all); `thru` seeds the BFS with the test
    case's own driver-side range, whose missing endpoints are the .cut
    author's typo and use UNKNOWN_PARAGRAPH. A PERFORM or GO TO naming a
    SECTION pushes every paragraph of that section (a performed section
    executes all of them by fall-through). Any in-program PERFORM/GO TO
    target resolving to neither a paragraph nor a section refuses with
    UNRESOLVED_FLOW_TARGET -- fail closed, never a silent skip: an edge
    the model cannot resolve means the reachable set cannot be trusted.
    (The seed `start` is exempt: check_test_case turns an unresolvable
    driver-side target into UNKNOWN_PARAGRAPH.)

    `neutralized_goto` holds exit-only paragraph names every GO TO of
    which is covered by a GotoExitPlan (`neutralized_goto_targets`) --
    the splicer replaces each of those GO TOs with EXIT PARAGRAPH at its
    own call site, so in the program that actually compiles and runs,
    control NEVER transfers to such a paragraph via GO TO. Two effects,
    mirroring the narrowing find_terminator_plans already applied to its
    own hazard sets (2026-08-25): a single-target unconditional GO TO
    naming a neutralized paragraph is not a flow edge (its target is not
    pushed), and the neutralized names are subtracted from the GO TO
    fall-through closure's seed set -- which is what stops the
    "GO TO <own-exit-label>" idiom's bare-EXIT landing pad from
    cascading the walk through the entire rest of the program. Sound
    only because find_goto_exit_plans is all-or-nothing per target and
    disqualifies any target also named by a computed/multi-target GO TO:
    a name in this set is therefore never reachable through any GO TO
    shape this walk would otherwise have to model. Callers that do not
    splice (or predict a run that will not splice) must leave it empty."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set(), []
    ordered = _source_ordered_paragraphs(procedure)
    by_name: dict[str, CobolParagraph] = {}
    for paragraph in _all_paragraphs(procedure):
        by_name.setdefault(paragraph.paragraph_name, paragraph)
    section_members: dict[str, list[str]] = {}
    for section_name, section in getattr(procedure, "_sections", {}).items():
        if not section_name:
            continue
        section_members.setdefault(
            section_name, [p.paragraph_name for p in section.paragraphs]
        )

    reasons: list[RefusalReason] = []
    stack = [start]
    if thru is not None:
        if start in section_members or thru in section_members:
            # 2026-08-12 audit Finding 2: this seed used to be guarded by
            # `start in by_name` alone -- built from paragraphs only -- so
            # a section-named start silently skipped both the expansion
            # AND its fail-closed refusal, dropping `thru` entirely while
            # the spliced driver still emits the literal PERFORM ... THRU
            # (GnuCOBOL executes the full fall-through range). Refuse loud
            # instead of modeling less than the compiled driver runs.
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_PERFORM_THRU",
                    message=(
                        f"test case PERFORM: PERFORM {start} THRU {thru} "
                        f"names a SECTION as a range endpoint -- THRU "
                        f"range expansion is only modeled over paragraphs, "
                        f"so the reachable set cannot be trusted; PERFORM "
                        f"the section without THRU, or name the range's "
                        f"boundary paragraphs directly"
                    ),
                )
            )
        elif start in by_name:
            members, problem = _expand_thru_range(
                ordered,
                start,
                thru,
                "test case PERFORM",
                missing_code="UNKNOWN_PARAGRAPH",
            )
            if problem is not None:
                reasons.append(problem)
            stack.extend(members)
        # else: the seed itself is unresolvable -- check_test_case reports
        # it as UNKNOWN_PARAGRAPH and returns before reading thru_reasons.

    def push_target(target: str, origin: str, verb: str) -> None:
        if target in by_name or target in section_members:
            stack.append(target)
        else:
            reasons.append(
                RefusalReason(
                    code="UNRESOLVED_FLOW_TARGET",
                    message=(
                        f"paragraph '{origin}': {verb} target '{target}' is "
                        f"neither a paragraph nor a section of the PROCEDURE "
                        f"DIVISION -- the reachability analysis cannot "
                        f"resolve this control-flow edge, so the reachable "
                        f"set cannot be trusted"
                    ),
                )
            )

    seen: set[str] = set()
    go_to_targets = _go_to_targets(program) - set(neutralized_goto)
    index_by_name = (
        {p.paragraph_name: i for i, p in enumerate(ordered)} if ordered else {}
    )
    # Computed once, not per walk: the closure below is a fixpoint loop
    # over every reached GO TO target. See `_fallthrough_flags`.
    falls = _fallthrough_flags(ordered) if ordered else []
    # This call's own entry point(s): a section otherwise safe for the GO
    # TO fall-through closure below is excluded whenever `start`/`thru`
    # name one of its member paragraphs directly, bypassing `PERFORM
    # <section-name>` -- see _paragraph_safe_section_map's docstring.
    paragraph_safe_section = _paragraph_safe_section_map(
        section_members,
        _fallthrough_safe_sections(program),
        {start} | ({thru} if thru else set()),
    )
    # PERFORM ranges whose own end stops a walk that starts inside them
    # (see _closed_perform_ranges). `active_ranges` only ever shrinks: a
    # walk from OUTSIDE a range that falls into its first paragraph means
    # control can be inside it with no marker for it active, so the range
    # is dropped and every walk redone.
    active_ranges = _closed_perform_ranges(
        program,
        ordered,
        section_members,
        driver_range=(start, thru or start) if start in by_name else None,
        exclude_seeds={start} | ({thru} if thru else set()),
    )
    while True:
        while stack:
            name = stack.pop()
            if name in seen:
                continue
            if name in skip_traversal:
                # Flow-mocked for this case: reached, but its body is replaced
                # by the mock dispatch -- never walk into it.
                seen.add(name)
                continue
            if name not in by_name:
                if name in section_members:
                    # A performed/jumped-to section executes every one of its
                    # paragraphs by fall-through.
                    seen.add(name)
                    stack.extend(section_members[name])
                # else: only the driver-side seed can be unresolved here
                # (every in-program edge was resolvability-checked before
                # pushing); check_test_case reports it as UNKNOWN_PARAGRAPH.
                continue
            seen.add(name)
            for statement in _find_flow_statements(by_name[name].statements):
                if isinstance(statement, GoStatement):
                    single_target = _go_statement_target(statement)
                    if single_target is not None and single_target in neutralized_goto:
                        # Covered by a GotoExitPlan: the splicer replaces
                        # this exact GO TO with EXIT PARAGRAPH, so it is
                        # not a flow edge in the program that runs. (A
                        # computed/multi-target GO TO can never name a
                        # neutralized paragraph -- its mere existence
                        # disqualifies the target in find_goto_exit_plans.)
                        continue
                    targets = list(statement.target_paragraphs)
                    if not targets and statement.target_paragraph:
                        targets = [statement.target_paragraph]
                    if not targets:
                        reasons.append(
                            RefusalReason(
                                code="UNRESOLVED_FLOW_TARGET",
                                message=(
                                    f"paragraph '{name}' (line "
                                    f"{statement.location.line}) contains a "
                                    f"GO TO whose target(s) the parser did "
                                    f"not capture -- fail closed"
                                ),
                            )
                        )
                    for target in targets:
                        push_target(target, name, "GO TO")
                    continue
                if statement.target_paragraph:
                    push_target(statement.target_paragraph, name, "PERFORM")
                    if statement.thru_paragraph:
                        members, problem = _expand_thru_range(
                            ordered,
                            statement.target_paragraph,
                            statement.thru_paragraph,
                            f"paragraph '{name}'",
                        )
                        if problem is not None:
                            reasons.append(problem)
                        stack.extend(members)

            # A SORT/MERGE's INPUT PROCEDURE/OUTPUT PROCEDURE names an
            # implicit PERFORM edge no PerformStatement AST node
            # represents -- modeled unconditionally for any SORT/MERGE
            # with a procedure clause (both the now-mockable pure form
            # and the still-refused mixed form), so a RELEASE/RETURN
            # reachable only through one is never invisible to the gate.
            for statement in _find_sort_merge_statements(by_name[name].statements):
                for procedure_attr, thru_attr in (
                    ("input_procedure", "input_procedure_thru"),
                    ("output_procedure", "output_procedure_thru"),
                ):
                    procedure_target = getattr(statement, procedure_attr, None)
                    if procedure_target is None:
                        continue
                    push_target(procedure_target, name, statement.statement_type)
                    procedure_thru = getattr(statement, thru_attr, None)
                    if procedure_thru:
                        members, problem = _expand_thru_range(
                            ordered,
                            procedure_target,
                            procedure_thru,
                            f"paragraph '{name}'",
                        )
                        if problem is not None:
                            reasons.append(problem)
                        stack.extend(members)

            # XML PARSE ... PROCESSING PROCEDURE p [THRU q]: the same
            # implicit-PERFORM shape (2026-09-02). A cobol-parser that
            # keeps the clause as text without exposing
            # `processing_procedure` cannot be followed -- refuse rather
            # than silently drop the edge.
            for statement in _find_xml_parse_statements(by_name[name].statements):
                procedure_target = getattr(statement, "processing_procedure", None)
                if procedure_target is None:
                    clause_text = getattr(statement, "clause_text", None) or ""
                    if XML_PROCESSING_PROCEDURE_RE.search(clause_text):
                        reasons.append(
                            RefusalReason(
                                code="UNRESOLVED_FLOW_TARGET",
                                message=(
                                    f"paragraph '{name}' (line "
                                    f"{statement.location.line}) contains an "
                                    f"XML PARSE with a PROCESSING PROCEDURE "
                                    f"this cobol-parser release does not "
                                    f"expose structurally, so the paragraph it "
                                    f"performs cannot be followed by the "
                                    f"reachability gate"
                                ),
                            )
                        )
                    continue
                push_target(procedure_target, name, "XML PARSE")
                procedure_thru = getattr(statement, "processing_procedure_thru", None)
                if procedure_thru:
                    members, problem = _expand_thru_range(
                        ordered,
                        procedure_target,
                        procedure_thru,
                        f"paragraph '{name}'",
                    )
                    if problem is not None:
                        reasons.append(problem)
                    stack.extend(members)

        # GO TO fall-through closure (see docstring): every reached GO TO
        # target is walked forward through source order via _falls_through
        # -- the same conservative predicate _go_to_fallthrough_targets and
        # union_executed_paragraphs use -- and each paragraph reachable by
        # falling off one's end is fed back into the BFS, to a fixpoint.
        # `seen & go_to_targets` over-approximates (a paragraph both
        # PERFORMed here and GO-TO'd elsewhere still triggers the walk),
        # which is the fail-closed direction: at worst an extra required
        # mock, never a silently executing unmocked boundary.
        hazard_sources = seen & go_to_targets
        if not hazard_sources:
            break
        if ordered is None:
            reasons.append(
                RefusalReason(
                    code="UNRESOLVED_FLOW_TARGET",
                    message=(
                        "paragraph source order could not be verified, so "
                        "the GO TO fall-through walk cannot run -- the "
                        "reachable set cannot be trusted"
                    ),
                )
            )
            break
        anchor_failed = False
        additions: list[str] = []
        range_of = {
            member: members[-1]
            for members in active_ranges.values()
            for member in members
        }
        exposed: set[tuple[str, str]] = set()
        for name in sorted(hazard_sources):
            reached = _walk_fallthrough_from(
                name,
                ordered,
                index_by_name,
                section_members,
                paragraph_safe_section,
                falls=falls,
                range_of=range_of,
            )
            if reached:
                exposed.update(
                    key
                    for key, members in active_ranges.items()
                    if members[0] in reached and name not in members
                )
            if reached is None:
                # A GO TO target the walk cannot anchor (e.g. an empty
                # section): the closure is incomplete, fail closed.
                reasons.append(
                    RefusalReason(
                        code="UNRESOLVED_FLOW_TARGET",
                        message=(
                            f"GO TO target '{name}' cannot be anchored in "
                            f"source order for the fall-through walk -- the "
                            f"reachable set cannot be trusted"
                        ),
                    )
                )
                anchor_failed = True
                continue
            for fallen in reached:
                if fallen not in seen and fallen not in additions:
                    additions.append(fallen)
        if anchor_failed:
            break
        if exposed:
            # Walks stopped at an exposed range's end are no longer
            # trustworthy: drop it and walk everything again.
            for key in exposed:
                del active_ranges[key]
            stack.extend(additions)
            continue
        if not additions:
            break
        stack.extend(additions)
    return seen, reasons


def _go_to_targets(program) -> set[str]:
    """Every paragraph/section name that is EVER a GO TO target anywhere
    in the whole program, regardless of reachability from any one test
    case -- a categorical, whole-program exclusion list.

    A paragraph that could ever be entered via GO TO cannot safely use
    EXIT PARAGRAPH/EXIT SECTION for early-exit propagation: verified
    empirically (docs/2026-07-08-goback-stop-run-support-design.md, spike
    #4) that EXIT PARAGRAPH silently fails to return to the correct
    caller when the paragraph it's issued from was entered via GO TO
    rather than PERFORM -- execution just stops, no crash, no return,
    the caller's checks never run."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set()
    targets: set[str] = set()
    for paragraph in _all_paragraphs(procedure):
        for statement in _find_statements_of_type(paragraph.statements, GoStatement):
            targets.update(statement.target_paragraphs)
            if statement.target_paragraph:
                targets.add(statement.target_paragraph)
    return targets


def _safe_section_entry_points(program) -> dict[str, str]:
    """Maps each SECTION name whose first paragraph is safely enterable
    ONLY via `PERFORM <section-name>` to that first paragraph's name --
    the one shape docs/2026-07-08-goback-stop-run-support-design.md's
    spike #5 proved `EXIT SECTION` correctly neutralizes (see
    docs/2026-07-10-section-scoped-terminator-support-design.md).

    Safe means: the section has at least one paragraph; neither the
    section's own name nor its first paragraph's name is ever a GO TO
    target anywhere in the program (`_go_to_targets`); and the first
    paragraph's name is never itself named as a PERFORM target -- plain
    or THRU, conditional or not, top-level or nested -- anywhere in the
    whole program. That last check is deliberately maximally inclusive:
    any second way to enter that paragraph is a standing risk regardless
    of whether any one test's execution happens to take it, the same
    reasoning already applied to the GO TO exclusion above.

    A section failing any of these is simply absent from the returned
    map -- callers must treat that identically to any other unresolvable
    PERFORM target (the existing dead-end/refusal behavior)."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return {}

    go_to_targets = _go_to_targets(program)
    performed_names: set[str] = set()
    for paragraph in _all_paragraphs(procedure):
        for statement in _find_statements_of_type(
            paragraph.statements, PerformStatement
        ):
            if statement.target_paragraph:
                performed_names.add(statement.target_paragraph)
            if statement.thru_paragraph:
                performed_names.add(statement.thru_paragraph)

    safe_entries: dict[str, str] = {}
    for section_name, section in procedure._sections.items():
        if not section.paragraphs:
            continue
        first_name = section.paragraphs[0].paragraph_name
        if section_name in go_to_targets or first_name in go_to_targets:
            continue
        if first_name in performed_names:
            continue
        safe_entries[section_name] = first_name
    return safe_entries


def _falls_through(paragraph) -> bool:
    """True unless `paragraph`'s last top-level statement provably diverts
    control away -- GOBACK, STOP RUN (not STOP <literal>, which only
    pauses for operator input and resumes), a single-target GO TO (a
    computed GO TO ... DEPENDING ON is NOT included: GnuCOBOL falls
    through to the next statement when the subscript is out of range, so
    it is not a guaranteed unconditional transfer), or EXIT PARAGRAPH/
    SECTION/PROGRAM (a bare EXIT./EXIT PERFORM does not qualify -- the
    former is a no-op placeholder, the latter exits an in-line loop body,
    not the paragraph). Everything else -- no statements at all, or
    ending in MOVE/DISPLAY/PERFORM/IF/EVALUATE/... -- is conservatively
    assumed to fall through, matching this module's fail-closed posture
    elsewhere: no attempt is made to prove that every branch of a
    trailing IF/EVALUATE terminates. See
    docs/2026-07-10-goto-fallthrough-terminator-hazard-design.md."""
    statements = paragraph.statements
    if not statements:
        return True
    last = statements[-1]
    if isinstance(last, GobackStatement):
        return False
    if isinstance(last, StopStatement) and last.stop_type == "RUN":
        return False
    if isinstance(last, GoStatement) and last.depending_on_variable is None:
        return False
    if isinstance(last, ExitStatement) and last.exit_type in (
        "PARAGRAPH",
        "SECTION",
        "PROGRAM",
    ):
        return False
    return True


def _fallthrough_flags(ordered: list) -> list[bool]:
    """`_falls_through` evaluated once per paragraph, in source order.

    Every fall-through walk in this module re-asked the same question
    about the same paragraph objects: `_go_to_fallthrough_targets` walks
    forward from EVERY GO TO target, and both fall-through closures run
    inside a fixpoint loop, so a program using the shared-exit-label
    idiom (where no paragraph on the chain provably diverts, so every
    walk runs to end of file) evaluated it O(targets x paragraphs) times
    -- measured as 4.4M calls, the single largest cost of the static
    check pass on a 53k-line program. The predicate depends only on the
    paragraph's own last statement, so one pass over `ordered` answers
    every walk."""
    return [_falls_through(paragraph) for paragraph in ordered]


def _first_non_fallthrough(falls: list[bool]) -> list[int | None]:
    """For each index, the smallest index at or after it whose paragraph
    does NOT fall through, or None when none does -- i.e. exactly where a
    forward fall-through walk starting there stops. One backward pass,
    so a walk costs only the paragraphs it actually reports."""
    stops: list[int | None] = [None] * len(falls)
    nxt: int | None = None
    for i in range(len(falls) - 1, -1, -1):
        if not falls[i]:
            nxt = i
        stops[i] = nxt
    return stops


def _fallthrough_safe_sections(program) -> set[str]:
    """SECTION names whose LAST paragraph a GO TO fall-through walk may
    treat as a hard stop (see `_walk_fallthrough_from`): reaching that
    exact physical point -- by ordinary fall-through from an earlier
    member, or by an internal GO TO landing anywhere within the section
    -- is where GnuCOBOL's own `PERFORM <section-name>` implicit return
    marker fires (the same address-based "own exit label" mechanism this
    module already relies on elsewhere for a single paragraph's own
    trailing EXIT landing pad), so modeling fall-through as continuing
    PAST it into whatever source text physically follows is wrong --
    exactly the false cascade that made every paragraph after a
    program's "GO TO <shared-validation-exit-label>" idiom look
    hazardous, all the way to the end of the file (2026-08-26 fix: this
    idiom -- several paragraphs each doing `GO TO <shared-exit>` as an
    early bailout -- was already the whole reason `find_goto_exit_plans`
    exists, but that function's own adjacency precondition only ever
    matches ONE of the several enclosing paragraphs, so its all-or-
    nothing neutralization declines the target and every case that ever
    reaches it inherits the full un-neutralized cascade; this closes the
    gate side of that gap without touching what `find_goto_exit_plans`
    splices).

    Deliberately STRICTER than `_safe_section_entry_points` (which only
    proves the section's FIRST paragraph has no other entry point
    anywhere in the program): here EVERY member paragraph must be
    provably unreachable except from within the section itself -- never
    a GO TO target from OUTSIDE it, never named by a PERFORM (plain,
    THRU endpoint, or conditional/looping, at any nesting depth) from
    OUTSIDE it. A GO TO/PERFORM from ONE member to ANOTHER member of the
    SAME section does not disqualify anything -- that is precisely the
    "several validation paragraphs share one section-scoped exit label"
    idiom this fix exists for, and an internal helper PERFORM among a
    section's own paragraphs doesn't change how the section itself was
    entered. A section failing the outside-entry check for even one
    non-first member is exactly as unsafe for this optimization as one
    failing it for its first member: a `PERFORM <that-member>` reached
    from elsewhere would start executing mid-section, where the implicit
    return marker this optimization trusts is that OTHER PERFORM's own
    (much narrower) range, not this section's end -- continuing to treat
    the section's own end as a safe stop there would silently hide
    paragraphs that genuinely execute.

    Whole-program AST only: a `.cut` test case's own PERFORM target/thru
    (DSL content, not a COBOL statement) can still name a member
    paragraph directly and is invisible to this scan -- callers must
    additionally exclude a section whenever their own entry point(s) do
    that; see `_paragraph_safe_section_map`."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set()
    section_of: dict[str, str] = {}
    for section_name, section in getattr(procedure, "_sections", {}).items():
        if not section_name:
            continue
        for paragraph in section.paragraphs:
            section_of[paragraph.paragraph_name] = section_name

    external_go_to_targets: set[str] = set()
    external_performed_names: set[str] = set()
    for paragraph in _all_paragraphs(procedure):
        enclosing_section = section_of.get(paragraph.paragraph_name)
        for statement in _find_statements_of_type(
            paragraph.statements, PerformStatement
        ):
            for target in (statement.target_paragraph, statement.thru_paragraph):
                if target and section_of.get(target) != enclosing_section:
                    external_performed_names.add(target)
        for statement in _find_statements_of_type(paragraph.statements, GoStatement):
            targets = (
                list(statement.target_paragraphs) if statement.target_paragraphs else []
            )
            if not targets and statement.target_paragraph:
                targets = [statement.target_paragraph]
            for target in targets:
                if section_of.get(target) != enclosing_section:
                    external_go_to_targets.add(target)

    safe: set[str] = set()
    for section_name, section in getattr(procedure, "_sections", {}).items():
        if not section_name or not section.paragraphs:
            continue
        members = [p.paragraph_name for p in section.paragraphs]
        if section_name in external_go_to_targets:
            continue
        if any(member in external_go_to_targets for member in members):
            continue
        if any(member in external_performed_names for member in members):
            continue
        safe.add(section_name)
    return safe


def _paragraph_safe_section_map(
    section_members: dict[str, list[str]],
    safe_sections: set[str],
    exclude_seeds: frozenset[str] | set[str] = frozenset(),
) -> dict[str, str]:
    """member paragraph name -> owning SECTION name, for every member of
    a section in `safe_sections` (`_fallthrough_safe_sections`) -- EXCEPT
    a section that `exclude_seeds` (a caller's own PERFORM target/thru,
    or any other DSL-level entry point invisible to that whole-program
    scan) enters directly by naming one of its member paragraphs instead
    of the section itself: that bypasses the `PERFORM <section-name>`
    return-marker guarantee the optimization depends on, so the section
    is excluded entirely for this caller rather than risk hiding
    paragraphs that genuinely execute from mid-section onward."""
    excluded = {
        section
        for section, members in section_members.items()
        if section in safe_sections and any(seed in members for seed in exclude_seeds)
    }
    return {
        member: section
        for section, members in section_members.items()
        if section in safe_sections and section not in excluded
        for member in members
    }


def _closed_perform_ranges(
    program,
    ordered: list | None,
    section_members: dict[str, list[str]],
    driver_range: tuple[str, str] | None = None,
    exclude_seeds: frozenset[str] | set[str] = frozenset(),
) -> dict[tuple[str, str], list[str]]:
    """PERFORM ranges `(A, B)` whose end B a GO TO fall-through walk
    starting INSIDE the range may treat as a hard stop (see
    `_walk_fallthrough_from`'s `range_of`), mapped to their source-order
    member names.

    The CCVS / "PERFORM X THRU X-EXIT" idiom: `PERFORM BAIL-OUT THRU
    BAIL-OUT-EX` whose body does `GO TO BAIL-OUT-WRITE`, a member that
    falls through into BAIL-OUT-EX. At runtime GnuCOBOL's return marker
    for that PERFORM fires at the end of BAIL-OUT-EX, so continuing the
    walk past it into whatever physically follows (in NIST IC101A: the
    rest of the program, all the way to CLOSE-FILES / STOP RUN) demanded
    mocks for boundaries the compiled program never reaches -- the same
    false cascade `_fallthrough_safe_sections` removed for sections.

    A candidate is every paragraph-to-paragraph PERFORM in the program
    (`PERFORM A THRU B`, or plain `PERFORM A` as the range `(A, A)`) plus
    this call's own driver-side `driver_range`, if any. It is closed --
    i.e. control can only be inside it while a PERFORM of exactly that
    range is active -- when, anywhere in the program:

    * every PERFORM naming a member (target or THRU end, any nesting
      depth) is exactly `PERFORM A THRU B` (plain `PERFORM A` for `(A,
      A)`), and every SORT/MERGE/XML PARSE procedure names no member;
    * every GO TO naming a member sits in a member paragraph;
    * no PERFORM/GO TO/procedure clause names a SECTION holding a member
      (GO TO <section> would enter mid-range with no marker);
    * no `exclude_seeds` entry (a .cut entry point, invisible to this
      AST scan) names a member, unless the range IS `driver_range`.

    Entering the range by plain fall-through from the paragraph before
    A is the one route this scan cannot rule out; `_reachable_paragraphs`
    closes it dynamically (a walk from OUTSIDE a range that enters A
    drops that range and re-walks). Any flow reference this scan cannot
    read (a GO TO without captured targets, an XML PARSE procedure the
    parser keeps only as text) disables the optimization entirely --
    fail closed. Ranges are disjoint by construction (each one's own
    PERFORM names a member of any range overlapping it)."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None or ordered is None:
        return {}
    names = [p.paragraph_name for p in ordered]
    if len(set(names)) != len(names):
        return {}
    section_of: dict[str, str] = {}
    for section_name, members in section_members.items():
        for member in members:
            section_of[member] = section_name

    performs: list[tuple[str, str]] = []
    procedure_names: set[str] = set()
    go_tos: list[tuple[str, str]] = []  # (target, enclosing paragraph)
    for paragraph in _all_paragraphs(procedure):
        for statement in _find_statements_of_type(
            paragraph.statements, PerformStatement
        ):
            if statement.target_paragraph:
                performs.append(
                    (
                        statement.target_paragraph,
                        statement.thru_paragraph or statement.target_paragraph,
                    )
                )
            elif statement.thru_paragraph:
                return {}
        for statement in _find_statements_of_type(paragraph.statements, GoStatement):
            targets = list(statement.target_paragraphs)
            if not targets and statement.target_paragraph:
                targets = [statement.target_paragraph]
            if not targets:
                return {}
            go_tos.extend((t, paragraph.paragraph_name) for t in targets)
        for statement in _find_sort_merge_statements(paragraph.statements):
            for attr in (
                "input_procedure",
                "input_procedure_thru",
                "output_procedure",
                "output_procedure_thru",
            ):
                value = getattr(statement, attr, None)
                if value:
                    procedure_names.add(value)
        for statement in _find_xml_parse_statements(paragraph.statements):
            target = getattr(statement, "processing_procedure", None)
            if target is None:
                if XML_PROCESSING_PROCEDURE_RE.search(
                    getattr(statement, "clause_text", None) or ""
                ):
                    return {}
                continue
            procedure_names.add(target)
            thru = getattr(statement, "processing_procedure_thru", None)
            if thru:
                procedure_names.add(thru)

    referenced_sections = (
        {a for a, _ in performs}
        | {b for _, b in performs}
        | {t for t, _ in go_tos}
        | procedure_names
    ) & set(section_members)

    candidates = set(performs)
    if driver_range is not None:
        candidates.add(driver_range)
    closed: dict[tuple[str, str], list[str]] = {}
    for start, end in sorted(candidates):
        if start not in names or end not in names:
            continue
        i, j = names.index(start), names.index(end)
        if j < i:
            continue
        members = names[i : j + 1]
        member_set = set(members)
        if any(section_of.get(m) in referenced_sections for m in members):
            continue
        if any(
            (a in member_set or b in member_set) and (a, b) != (start, end)
            for a, b in performs
        ):
            continue
        if member_set & procedure_names:
            continue
        if any(t in member_set and where not in member_set for t, where in go_tos):
            continue
        if (start, end) != driver_range and member_set & set(exclude_seeds):
            continue
        closed[(start, end)] = members
    return closed


def _walk_fallthrough_from(
    name: str,
    ordered: list,
    index_by_name: dict[str, int],
    section_members: dict[str, list[str]],
    paragraph_safe_section: dict[str, str],
    falls: list[bool] | None = None,
    range_of: dict[str, str] | None = None,
) -> list[str] | None:
    """Every paragraph name reached, in source order, by walking forward
    from GO-TO-target `name` (a paragraph or section name) via
    `_falls_through` -- the shared walk `_reachable_paragraphs` and
    `union_executed_paragraphs` both apply (see module docstring: a
    paragraph reached this way carries the exact same EXIT PARAGRAPH
    hazard as one directly named by a GO TO). `name` unanchorable in
    `index_by_name`/`section_members` (e.g. an empty section) returns
    None -- callers must fail closed on that, same as before this helper
    existed.

    Stops at the first paragraph whose own last statement provably
    diverts control away (`_falls_through`), or -- the instant it would
    cross past -- the LAST paragraph of a SECTION `name` resolves into
    per `paragraph_safe_section` (see `_fallthrough_safe_sections`/
    `_paragraph_safe_section_map` for the soundness conditions that map
    already enforces).

    `falls` is `_fallthrough_flags(ordered)`; callers that walk repeatedly
    (both of this function's own call sites run inside a fixpoint loop)
    should compute it once and pass it in rather than pay for it per
    walk. Omitting it is equivalent, just slower.

    `range_of` maps each member of a closed PERFORM range
    (`_closed_perform_ranges`) to that range's end paragraph: a walk whose
    origin is a member also stops at that end, where the PERFORM's own
    return marker fires."""
    if falls is None:
        falls = _fallthrough_flags(ordered)
    start = index_by_name.get(name)
    anchor_name = name
    if start is None:
        members = section_members.get(name)
        if not members:
            return None
        start = index_by_name.get(members[0])
        if start is None:
            return None
        anchor_name = members[0]
    origin_section = paragraph_safe_section.get(anchor_name)
    stop_before = None
    if origin_section is not None:
        section_paragraphs = section_members.get(origin_section)
        if section_paragraphs:
            stop_before = section_paragraphs[-1]
    range_end = (range_of or {}).get(anchor_name)
    reached: list[str] = []
    cursor = start
    while falls[cursor] and cursor + 1 < len(ordered):
        here = ordered[cursor].paragraph_name
        if here in (stop_before, range_end):
            break
        cursor += 1
        reached.append(ordered[cursor].paragraph_name)
    return reached


def _go_to_fallthrough_targets(program, go_to_targets: set[str]) -> dict[str, str]:
    """Every paragraph reachable ONLY by falling through past a GO TO
    target's own end -- an unmodeled shape the reachability BFS does not
    represent as a flow edge (see the module docstring). Maps each such
    paragraph name to the GO-TO-target paragraph/section name whose
    fall-through chain reaches it, for diagnosable refusal messages.

    A paragraph entered this way carries the exact same EXIT PARAGRAPH
    hazard as a paragraph directly named by a GO TO (spike #4, docs/
    2026-07-08-goback-stop-run-support-design.md): the runtime frame-stack
    context at the point its code executes never went through a genuine
    PERFORM call, whether that paragraph is itself the GO TO target or was
    merely fallen into afterward.

    Conservative and fail-closed like the rest of this module: propagates
    through every paragraph after a GO TO target in source order until one
    is found whose own last top-level statement provably cannot fall
    through further (see _falls_through). A GO TO targeting a SECTION name
    is seeded from that section's first paragraph -- fall-through is
    transparent to SECTION boundaries, a header doesn't stop it; the
    section's own member paragraphs are covered by the walk since
    _source_ordered_paragraphs includes every paragraph regardless of
    section membership.

    Returns {} when _source_ordered_paragraphs can't establish a strict
    source order -- the same pre-existing blind spot that already limits
    other checks in this module (e.g. _expand_thru_range) to refusing only
    the specific reachability question they were asked, not every
    reachability question in the file."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return {}
    ordered = _source_ordered_paragraphs(procedure)
    if ordered is None:
        return {}
    index_by_name = {p.paragraph_name: i for i, p in enumerate(ordered)}
    section_members: dict[str, list[str]] = {}
    for section_name, section in getattr(procedure, "_sections", {}).items():
        if not section_name:
            continue
        section_members.setdefault(
            section_name, [p.paragraph_name for p in section.paragraphs]
        )

    falls = _fallthrough_flags(ordered)
    stops = _first_non_fallthrough(falls)
    last = len(ordered) - 1

    hazard: dict[str, str] = {}
    # Indices already recorded by an earlier walk. Two walks that both pass
    # through index k necessarily stop at the same index: the stop is
    # `stops[start]`, and there is no non-fall-through paragraph strictly
    # between two starts that both reach k. So hitting an already-recorded
    # index means the whole rest of this walk is already recorded too, and
    # the remaining `setdefault` calls would every one be a no-op -- which
    # is what lets the walk break there and keeps the total linear rather
    # than O(targets x paragraphs). Same keys, same first-writer-wins
    # values as the unconditional walk it replaces.
    recorded: set[int] = set()
    for name in go_to_targets:
        start = index_by_name.get(name)
        if start is None:
            members = section_members.get(name)
            if not members:
                continue
            start = index_by_name.get(members[0])
            if start is None:
                continue
        stop = stops[start]
        end = last if stop is None else stop
        for cursor in range(start + 1, end + 1):
            if cursor in recorded:
                break
            recorded.add(cursor)
            hazard.setdefault(ordered[cursor].paragraph_name, name)
    return hazard


def _plain_perform_statements(
    statements: list, nested: bool = False, in_boundary: bool = False
) -> list[tuple[PerformStatement, bool, bool]]:
    """Recursively collect every plain, unconditional, single-shot,
    out-of-line PerformStatement in `statements` -- thru_paragraph is
    None, target_paragraph set, perform_type == "SIMPLE" -- at ANY
    nesting depth, tagged with:

    - `nested`: False only for a direct member of the paragraph's own
      top-level `.statements` list (today's only supported shape); True
      at any depth >= 1 -- an IF/ELSE branch, an EVALUATE
      WHEN/WHEN OTHER branch, or an inline PERFORM ... END-PERFORM loop
      body (via _nested_statement_lists' then_statements/else_statements/
      when_clauses/inline_statements).
    - `in_boundary`: sticky -- True once recursion has entered another
      boundary statement's clause body (CALL's ON EXCEPTION, a file
      statement's AT END, ...). Mirrors mock_surface._walk_statements'
      identical child_in_boundary propagation: a PERFORM found there is
      never a valid chain edge, because splicing the enclosing boundary
      statement (when it's mocked) removes the PERFORM and any inserted
      check along with it -- the same structural reason a nested
      BoundarySite there is unsplicable.

    Every recursive call passes nested=True literally (not the parent's
    nested value), matching mock_surface._walk_statements' own pattern,
    so a PERFORM is marked nested at every depth >= 1 while a genuinely
    top-level one (the initial call, nested defaults to False) stays
    unmarked. See docs/2026-07-10-conditionally-nested-intermediate-perform-design.md.
    """
    found: list[tuple[PerformStatement, bool, bool]] = []
    for statement in statements:
        if (
            isinstance(statement, PerformStatement)
            and statement.thru_paragraph is None
            and statement.target_paragraph
            and statement.perform_type == "SIMPLE"
        ):
            found.append((statement, nested, in_boundary))
        child_in_boundary = in_boundary or isinstance(
            statement, _BOUNDARY_STATEMENT_TYPES
        )
        for nested_list in _nested_statement_lists(statement):
            found.extend(
                _plain_perform_statements(
                    nested_list, nested=True, in_boundary=child_in_boundary
                )
            )
    return found


def _plain_perform_edges_from(
    program, start: str, safe_section_entries: dict[str, str] | None = None
) -> tuple[set[str], list[tuple[PerformStatement, bool]]]:
    """BFS from `start` following plain (non-THRU), unconditional,
    single-shot PERFORM statements -- PerformStatement nodes with
    thru_paragraph is None and perform_type == "SIMPLE" -- at ANY nesting
    depth within a paragraph (top-level, or nested inside an IF/ELSE
    branch, an EVALUATE WHEN/WHEN OTHER branch, or an inline
    PERFORM ... END-PERFORM loop body). A PERFORM nested inside another
    boundary statement's clause body (CALL's ON EXCEPTION, a file
    statement's AT END, ...) is never followed -- see
    _plain_perform_statements.

    A PERFORM ... UNTIL/VARYING/TIMES (perform_type != "SIMPLE") is
    deliberately NOT followed and NOT added to the edge set, even though
    it also carries a `target_paragraph` with `thru_paragraph is None`:
    the early-exit mechanism sets a flag and does `EXIT PARAGRAPH`, which
    only ends the CURRENT iteration of the looped paragraph -- control
    returns to the loop construct, which re-checks its own unrelated
    UNTIL/VARYING/TIMES condition and may iterate again. A terminator
    reached from inside a loop's target would silently run extra
    unwanted iterations instead of stopping, which was proven empirically
    (a synthetic STOP RUN placed inside a looped paragraph kept iterating
    past it). Excluding the edge means such a terminator's paragraph never
    enters `seen`, so `find_terminator_plans` naturally refuses it via the
    existing "reachable but not via a plain chain" check -- no new
    refusal branch needed. (This is distinct from a PERFORM nested INSIDE
    an inline `PERFORM ... END-PERFORM` loop BODY, which IS followed --
    EXIT PARAGRAPH from inside an inline loop body correctly exits the
    whole enclosing paragraph, verified empirically 2026-07-10; the
    excluded case here is an OUT-OF-LINE PERFORM that IS itself a loop
    over a different paragraph.)

    `safe_section_entries` (from `_safe_section_entry_points`, or omitted
    for callers that don't care about SECTIONs -- e.g. this module's own
    dead-end regression test) resolves a PERFORM target that names one of
    its KEYS (a SECTION whose first paragraph is provably safely
    enterable only that way) to that first paragraph's name, continuing
    the BFS from that paragraph's own statements exactly like any other
    paragraph -- see
    docs/2026-07-10-section-scoped-terminator-support-design.md. This is
    the ONLY SECTION shape this restricted BFS ever resolves: a target
    name that is a SECTION but not a safe entry (or any other
    unresolvable name) still dead-ends exactly as before, its raw,
    unresolved name landing in `seen`. SECTION members that aren't a safe
    entry's first paragraph are still excluded entirely, same as before:
    this only looks up names in `procedure.paragraphs` (top-level
    paragraphs) and, when `safe_section_entries` resolves one, the
    specific first-paragraph names it names -- never any other section
    member -- so a chain that would need to pass through one of those
    (fall-through, or a direct PERFORM of a non-first section member)
    still naturally refuses via the existing "reachable but not via a
    plain chain" check.

    Returns (reachable paragraph names via this restricted edge set, the
    (PerformStatement, nested) pairs that ARE those edges) -- every one of
    those statements is a candidate for the early-exit flag-check
    instrumentation, `nested` telling the caller which validator/
    insertion-point computation applies. Deliberately NOT the same as
    `_reachable_paragraphs`: that function also follows GO TO and
    section/THRU fall-through edges, exactly the unsafe shapes this
    restricted variant must exclude."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set(), []
    safe_section_entries = safe_section_entries or {}
    by_name = {p.paragraph_name: p for p in procedure.paragraphs}
    section_member_by_name = {
        paragraph.paragraph_name: paragraph
        for section in procedure._sections.values()
        for paragraph in section.paragraphs
    }

    def resolve(name):
        if name in by_name:
            return name, by_name[name]
        first_name = safe_section_entries.get(name)
        if first_name is not None:
            return first_name, section_member_by_name.get(first_name)
        return name, None

    start_name, start_paragraph = resolve(start)
    seen = {start_name}
    resolved = {}
    stack = []
    if start_paragraph is not None:
        resolved[start_name] = start_paragraph
        stack.append(start_name)
    edges: list[tuple[PerformStatement, bool]] = []
    while stack:
        name = stack.pop()
        paragraph = resolved.get(name)
        if paragraph is None:
            continue
        for statement, nested, in_boundary in _plain_perform_statements(
            paragraph.statements
        ):
            if in_boundary:
                continue
            edges.append((statement, nested))
            target_name, target_paragraph = resolve(statement.target_paragraph)
            if target_name not in seen:
                seen.add(target_name)
                if target_paragraph is not None:
                    resolved[target_name] = target_paragraph
                    stack.append(target_name)
    return seen, edges


def _is_exit_only_paragraph(paragraph) -> bool:
    """True when `paragraph`'s entire body is one bare EXIT statement --
    an ExitStatement whose exit_type is none of PARAGRAPH/SECTION/PROGRAM,
    the same no-op-placeholder shape _falls_through's docstring already
    names (`MAIN-EXIT. EXIT.`, the idiomatic mainframe early-exit landing
    pad .okf/analysis.md calls out by name). Deliberately does NOT accept
    an empty (zero-statement) body -- narrower, harder-to-misclassify
    shape chosen deliberately for v1; see
    docs/2026-08-17-goto-exit-paragraph-simplification-design.md's "What
    counts as an exit-only paragraph"."""
    statements = paragraph.statements
    if len(statements) != 1:
        return False
    statement = statements[0]
    return isinstance(statement, ExitStatement) and statement.exit_type not in (
        "PARAGRAPH",
        "SECTION",
        "PROGRAM",
    )


def _go_statements_with_nesting(
    statements: list, nested: bool = False, in_boundary: bool = False
) -> list[tuple[GoStatement, bool, bool]]:
    """Recursively collect every GoStatement in `statements`, tagged with
    `nested` (False only for a direct top-level member of the paragraph's
    own .statements list) and `in_boundary` (sticky -- True once recursion
    has entered another boundary statement's clause body) -- the exact
    same propagation `_plain_perform_statements` applies to PerformStatement
    and `mock_surface._walk_statements` applies to boundary sites. Needed
    because a top-level GO TO's replacement span comes from
    `statement_span` (correct only when nothing between it and the next
    top-level statement has its own scope terminator), while a nested GO
    TO (inside an IF/EVALUATE branch) needs the validated
    `nested_statement_span` instead -- see that function's docstring for
    the bug this distinction exists to avoid."""
    found: list[tuple[GoStatement, bool, bool]] = []
    for statement in statements:
        if isinstance(statement, GoStatement):
            found.append((statement, nested, in_boundary))
        child_in_boundary = in_boundary or isinstance(
            statement, _BOUNDARY_STATEMENT_TYPES
        )
        for nested_list in _nested_statement_lists(statement):
            found.extend(
                _go_statements_with_nesting(
                    nested_list, nested=True, in_boundary=child_in_boundary
                )
            )
    return found


def _go_statement_target(statement: GoStatement) -> str | None:
    """The single, unconditional target name of `statement`, or None when
    it is computed (`depending_on_variable` is not None) or names more
    than one paragraph -- both excluded because neither resolves to
    "always this one paragraph," which GO-TO-to-EXIT-PARAGRAPH splicing
    requires. Mirrors `_reachable_paragraphs`' own target-list handling
    (`target_paragraphs` first, falling back to the singular
    `target_paragraph`)."""
    if statement.depending_on_variable is not None:
        return None
    targets = list(statement.target_paragraphs) if statement.target_paragraphs else []
    if not targets and statement.target_paragraph:
        targets = [statement.target_paragraph]
    if len(targets) != 1:
        return None
    return targets[0]


def _go_statement_raw_targets(statement: GoStatement) -> list[str]:
    """Every name `statement` could possibly transfer control to,
    regardless of whether `_go_statement_target` can resolve it to one
    safe target -- used only to find every paragraph a computed or
    multi-target GO TO could ever land on, for disqualification. Same
    `target_paragraphs`-first-fallback-to-`target_paragraph` shape
    `_go_statement_target`/`_reachable_paragraphs`/`_go_to_targets` all
    use, deliberately not routed through one shared helper here since
    this one intentionally ignores `depending_on_variable`."""
    targets = list(statement.target_paragraphs) if statement.target_paragraphs else []
    if not targets and statement.target_paragraph:
        targets = [statement.target_paragraph]
    return targets
