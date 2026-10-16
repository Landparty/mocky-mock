"""Shared static-check pipeline for `mockymock run` and `mockymock lint`.

Extracted from `_cmd_run` per docs/2026-07-18-cut-lint-command-design.md so
the two commands can never disagree about what counts as a refusal. Every
check here is pure static analysis over the parsed AST and the `.cut`
model -- this module must never import `mockymock.runtime.docker_toolchain`
(that structural guarantee is what makes `lint` Docker-free).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from mockymock._lines import (
    SourceEncodingError,
    read_utf8_source,
    split_source_lines,
)
from mockymock.debugging_lines import activate_debugging_lines

if TYPE_CHECKING:
    from cobolparser import ParseResult

    from mockymock.analysis.cics_eib import CicsEibPlan
    from mockymock.analysis.linkage import AddressOfSite, LinkagePlan
    from mockymock.analysis.mock_surface import MockSurface
    from mockymock.analysis.refusal import RefusalReason
    from mockymock.dsl.model import MockTestSuite
    from mockymock.splicer.captures import CapturePlan
    from mockymock.splicer.snapshot import StateSnapshot
    from mockymock.splicer.source_map import ScopeMap


@dataclass
class StaticCheckResult:
    """Everything the check phase learned. `problems` holds pre-formatted,
    unprefixed lines ("refused (CODE): ..." or raw indented parse-error
    lines) in print order; the artifact fields are populated only when the
    pipeline got far enough to produce them, so a clean result carries
    everything `_cmd_run` needs to proceed straight to splicing."""

    problems: list[str] = field(default_factory=list)
    parse_result: ParseResult | None = None
    surface: MockSurface | None = None
    suite: MockTestSuite | None = None
    lines: list[str] | None = None  # normalized + linkage-neutralized
    scope_map: ScopeMap | None = None
    linkage: LinkagePlan | None = None
    # `SET ADDRESS OF <folded LINKAGE item>` receiving-side occurrences already
    # rewritten in `lines`; non-empty means the driver must also declare the
    # scratch pointer they were redirected to (see splicer.linkage).
    linkage_address_of: list[AddressOfSite] = field(default_factory=list)
    cics_eib: CicsEibPlan | None = None
    file_status_fields: dict[str, str] | None = None
    # Synthesized `CAPTURE ARG ... INTO UT-CAP-...` targets: the driver must
    # declare each one and reset it between cases (see splicer.captures).
    captures: list[CapturePlan] = field(default_factory=list)
    # Transparency lines for checks that deliberately did NOT refuse: a
    # paragraph-scoped parse warning / unresolved COPY waived because no
    # selected test case can execute its paragraph (the COPY additionally
    # commented out of `lines`). Callers should print these with their own
    # command prefix -- silently proceeding past a warning, or silently
    # editing source a .cut author didn't write, would both be surprises.
    notes: list[str] = field(default_factory=list)
    # Pre-formatted, unprefixed "warning (CODE): ..." lines for things that
    # pass every check but cannot behave as in production (issue #288).
    # lint counts them alongside its NO_ASSERTION warnings; run prints them.
    warnings: list[str] = field(default_factory=list)
    # Raw check_test_case() output per TESTCASE, keyed by the case's
    # index in `suite.test_cases` (not its name: duplicate TESTCASE names
    # are legal, and a name key would hand the last case's reasons to
    # every namesake). Not just the pre-formatted strings already folded
    # into `problems` -- lets a caller like `generate --fill` act on
    # `RefusalReason.suggested_fix` directly instead of re-running the
    # same reachability analysis a second time. Only cases with at least
    # one reason appear as a key.
    unmocked_reasons: dict[int, list[RefusalReason]] = field(default_factory=dict)
    # Save/restore of the state BEFORE-ALL leaves behind (splicer.snapshot);
    # None unless the suite has BEFORE-ALL steps. Every splice-and-compile
    # pipeline passes it to build_driver.
    snapshot: StateSnapshot | None = None

    @property
    def ok(self) -> bool:
        return not self.problems


def extra_working_storage(checked: StaticCheckResult) -> list[str] | None:
    """Every WORKING-STORAGE line the instrumented program needs on top of
    `driver.build_driver`'s own bookkeeping fields, in one place so all four
    splice-and-compile pipelines (`run`, `debug`, `export`, mutation) stay in
    step: the synthesized CICS EIB block, and the scratch pointer that
    `splicer.linkage.redirect_address_of`'s rewritten `SET ADDRESS OF`
    statements assign into.

    Also the synthesized `CAPTURE ARG ... INTO UT-CAP-...` targets, which
    exist so a `.cut` (hand-written or scaffolded) can assert on what a
    mocked CALL actually received without the author first having to find
    or add a spare field of a compatible type.

    `None` (not `[]`) when there is nothing to add, matching what
    `build_driver` treats as "no extra lines".
    """
    from mockymock.splicer import cics_eib
    from mockymock.splicer.captures import capture_working_storage_lines
    from mockymock.splicer.linkage import (
        extra_working_storage_lines,
        rebinding_working_storage_lines,
    )
    from mockymock.splicer.reset import index_working_storage_lines

    lines: list[str] = []
    if checked.cics_eib is not None:
        lines.extend(cics_eib.working_storage_lines(checked.cics_eib))
    lines.extend(extra_working_storage_lines(checked.linkage_address_of))
    if checked.linkage is not None:
        lines.extend(rebinding_working_storage_lines(checked.linkage.rebindings))
    lines.extend(capture_working_storage_lines(checked.captures))
    lines.extend(index_working_storage_lines(_index_names(checked)))
    return lines or None


def extra_reset_lines_for(checked: StaticCheckResult) -> list[str]:
    """Reset lines the synthesized capture targets need between test cases,
    and the save/restore of every INDEXED BY index (issue #189). Kept
    beside `extra_working_storage` so the declaration and the reset can
    never be added in one pipeline and forgotten in another -- the suite
    compiles to ONE binary, so a capture left unreset would let a case that
    never reached its CALL assert against the previous case's value."""
    from mockymock.splicer.captures import capture_reset_lines
    from mockymock.splicer.reset import index_reset_lines

    return capture_reset_lines(checked.captures) + index_reset_lines(
        _index_names(checked)
    )


def _synthesized_groups(cics_eib, transformed: list[str]) -> list[str]:
    """The groups mockymock splices in after parsing that this program gets:
    the CICS EIB and DL/I DIB blocks (`splicer.cics_eib`) and the generated
    SQLCA (`splicer.sqlca`, present in the transformed text). The
    BEFORE-ALL snapshot must cover them (issue #225)."""
    from mockymock.splicer.sqlca import sqlca_reset_lines

    groups: list[str] = []
    if cics_eib is not None and cics_eib.referenced_names:
        groups.append("DFHEIBLK")
    if cics_eib is not None and cics_eib.dib_names:
        groups.append("DLIDIB")
    if sqlca_reset_lines(transformed):
        groups.append("SQLCA")
    return groups


def _index_names(checked: StaticCheckResult) -> list[str]:
    from mockymock.splicer.reset import index_names

    if checked.parse_result is None or checked.parse_result.ast is None:
        return []
    return index_names(checked.parse_result.ast)


NO_ASSERTION = "NO_ASSERTION"


def no_assertion_warnings(suite: MockTestSuite) -> list[str]:
    """One pre-formatted, unprefixed warning line per TESTCASE with no
    EXPECT and no VERIFY. Warnings, not problems: such a case is valid and
    passes whenever its PERFORM runs, so lint flags it without failing
    (like PHPUnit's "risky" status) and `run` marks its result the same
    way. The `.cut line N` wording is what lets an editor place the
    diagnostic on the TESTCASE header. PROVIDER rows expand to cases that
    share one header line, so each line is reported once."""
    warnings: list[str] = []
    seen_lines: set[int] = set()
    for case in suite.test_cases:
        if case.assertion_count:
            continue
        if case.line:
            if case.line in seen_lines:
                continue
            seen_lines.add(case.line)
        where = f".cut line {case.line}: " if case.line else ""
        warnings.append(
            f'warning ({NO_ASSERTION}): {where}TESTCASE "{case.name}" asserts '
            f"nothing -- it passes whenever its PERFORM runs. Add an EXPECT "
            f"on what it writes or a VERIFY on what it calls"
        )
    return warnings


def filter_suite_cases(
    suite: MockTestSuite,
    case_names: list[str] | None,
    tag_names: list[str] | None,
) -> list[str]:
    """Filter `suite.test_cases` in place to the selection `--case`/`--tag`
    describe (a case is kept if it matches any requested name or carries any
    requested tag). Returns problem lines for selections that match nothing;
    an empty return means the filter applied cleanly (or no filter was
    given)."""
    problems: list[str] = []
    if not case_names and not tag_names:
        return problems

    available = {case.name for case in suite.test_cases}
    for name in case_names or []:
        if name not in available:
            listing = ", ".join(repr(c.name) for c in suite.test_cases)
            problems.append(
                f"no TESTCASE named {name!r} in this suite " f"(available: {listing})"
            )
    available_tags = {tag for case in suite.test_cases for tag in case.tags}
    # Tags select a subset as a union, so `--tag a --tag b` on a suite with
    # only `a` is a selection, not a typo; refuse only when no requested
    # tag is carried at all (issue #254).
    if tag_names and not available_tags & set(tag_names):
        listing = ", ".join(sorted(repr(t) for t in available_tags)) or "none"
        for tag in tag_names:
            problems.append(
                f"no TESTCASE carries tag {tag!r} (tags in this suite: {listing})"
            )
    if problems:
        return problems

    wanted_names = set(case_names or [])
    wanted_tags = set(tag_names or [])
    suite.test_cases = [
        case
        for case in suite.test_cases
        if case.name in wanted_names or (wanted_tags & set(case.tags))
    ]
    return problems


def run_static_checks(
    source_path: Path,
    cut_path: Path,
    copybook_paths: list[str] | None,
    case_names: list[str] | None = None,
    tag_names: list[str] | None = None,
    preserve_compiler_directives: bool = False,
) -> StaticCheckResult:
    """Faithful transcription of `_cmd_run`'s pre-toolchain check sequence,
    including its short-circuit behavior: each numbered stage stops the
    pipeline if it finds problems, except the final per-test-case stage,
    which accumulates across every case before returning."""
    from cobolparser import parse_cobol
    from cobolparser.preprocess import (
        CopybookNotFoundError,
        expand_copybooks,
        normalize_fixed_format,
        strip_compiler_directives,
    )

    from mockymock.analysis.cics_eib import cics_eib_plan
    from mockymock.analysis.cut_names import check_cut_data_names
    from mockymock.analysis.flow_mocks import check_flow_mocks
    from mockymock.analysis.flow_targets import normalize_flow_targets
    from mockymock.analysis.linkage import (
        address_of_sites,
        linkage_plan,
        omitted_argument_tests,
        omitted_argument_warnings,
        rebindable_sites,
    )
    from mockymock.analysis.mock_surface import analyze, analyze_file_status_fields
    from mockymock.analysis.refusal import (
        CICS_MACRO_PLACEHOLDER,
        check_cics_eib_layout_scoped,
        check_expansion_warnings,
        check_linkage_layout,
        check_nested_exec,
        check_source_format,
        check_terminator_layout,
        check_test_case,
        check_unresolved_copybooks_scoped,
        check_whole_program_scoped,
        neutralized_goto_targets,
        resolve_scoped_refusals,
        union_executed_paragraphs,
    )
    from mockymock.cli.discovery import copybook_not_found_hint
    from mockymock.dsl.parser import CutParseError, parse_cut
    from mockymock.splicer.captures import plan_captures
    from mockymock.splicer.cics_resp import expand_dfhresp, expansion_note
    from mockymock.splicer.linkage import (
        mark_based,
        neutralize,
        redirect_address_of,
    )
    from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map
    from mockymock.splicer.sqlca import transform_data_division_exec
    from mockymock.splicer.stub_writer import comment_and_replace, replace_columns

    out = StaticCheckResult()

    # 1. Read source; expand copybooks and check expansion warnings.
    try:
        raw_source = read_utf8_source(source_path)
    except SourceEncodingError as exc:
        out.problems.append(str(exc))
        return out
    program_source = raw_source
    if copybook_paths:
        # cobolparser genuinely raises for realistic inputs (a copybook
        # that COPYs itself, an oversized/deeply-nested chain, a
        # mis-encoded file) -- CircularReferenceError, NestingDepthError,
        # TotalExpansionSizeExceededError, EncodingError. Shared by
        # run/lint/debug/export/mutate: an unhandled traceback here
        # reached six different subcommands (audit finding F6). Mirrors
        # _cmd_fixtures's existing broad catch for the same call.
        try:
            expansion = expand_copybooks(raw_source, copybook_paths=copybook_paths)
        except CopybookNotFoundError as exc:
            out.problems.append(f"copybook expansion failed: {exc}")
            out.problems.append(copybook_not_found_hint())
            return out
        except Exception as exc:  # noqa: BLE001 -- surfaced verbatim to the caller
            out.problems.append(f"copybook expansion failed: {exc}")
            return out
        expansion_reasons = check_expansion_warnings(expansion)
        if expansion_reasons:
            out.problems.extend(
                f"refused ({r.code}): {r.message}" for r in expansion_reasons
            )
            return out
        raw_source = expansion.expanded_source

    # 2. Parse; whole-program refusals (hard errors + dropped-statement
    # warnings). The PARSE_ERROR reason only carries a count, so the
    # individual errors follow as indented lines, matching `run`'s output.
    # Warnings provably confined to one paragraph's own body are held back
    # (scoped_warnings) for the reachability-union gate in step 4b.
    # WITH DEBUGGING MODE: D lines are code, as the compiler reads them.
    raw_source = activate_debugging_lines(raw_source)
    parse_result = parse_cobol(raw_source, filename=source_path.name)
    normalize_flow_targets(parse_result.ast)
    out.parse_result = parse_result
    # Free-format source parses, but is column-chopped by everything below
    # (issue #210). Checked once the parse succeeded, so unparseable text
    # still reports PARSE_ERROR with its detail lines rather than a
    # format guess; decided on the program's own text, before expansion.
    if parse_result.success:
        format_reasons = check_source_format(program_source)
        if format_reasons:
            out.problems.extend(
                f"refused ({r.code}): {r.message}" for r in format_reasons
            )
            return out
    whole_program_reasons, scoped_warnings = check_whole_program_scoped(
        parse_result, raw_source
    )
    if whole_program_reasons:
        out.problems.extend(
            f"refused ({r.code}): {r.message}" for r in whole_program_reasons
        )
        if not parse_result.success:
            out.problems.extend(f"  {error}" for error in parse_result.errors)
        return out

    # 3. Unresolved copybooks -- same split: a COPY provably confined to
    # one paragraph's own body (with a verified own-lines span) is held
    # back for step 4b; everything else refuses now.
    copybook_reasons, scoped_copies = check_unresolved_copybooks_scoped(
        raw_source, parse_result.ast
    )
    if copybook_reasons:
        out.problems.extend(
            f"refused ({r.code}): {r.message}" for r in copybook_reasons
        )
        return out

    # 4. Parse the .cut file; apply any --case/--tag selection immediately so
    # every later per-case check sees only the cases that will actually run.
    try:
        suite = parse_cut(read_utf8_source(cut_path))
    except CutParseError as exc:
        out.problems.append(f"invalid .cut file {cut_path}: {exc}")
        return out
    except SourceEncodingError as exc:
        out.problems.append(str(exc))
        return out
    # The unselected cases still count towards whether a BEFORE-EACH/
    # BEFORE-ALL mock is reached at all (step 8's sweep, issue #250).
    all_cases = list(suite.test_cases)
    selection_problems = filter_suite_cases(suite, case_names, tag_names)
    if selection_problems:
        out.problems.extend(selection_problems)
        return out
    out.suite = suite

    # 4b. Paragraph-scoped refusals held back by steps 2-3: refuse each one
    # whose paragraph the union of every SELECTED case's reachable set (GO
    # TO fall-through closed; None = "trust nothing", refuse all) says
    # could execute; waive the rest with a transparency note each. A
    # waived COPY's verified span is commented out of `lines` in step 5 --
    # cobc cannot compile an unresolvable COPY, unreachable or not.
    # Steps 4b and 5b both resolve against this, and it runs a full
    # reachability BFS per selected test case -- compute it at most once,
    # and only if some refusal was actually held back.
    executed_computed = False
    executed: set[str] | None = None

    def executed_paragraphs() -> set[str] | None:
        nonlocal executed_computed, executed
        if not executed_computed:
            executed = union_executed_paragraphs(parse_result.ast, suite)
            executed_computed = True
        return executed

    scoped = scoped_warnings + scoped_copies
    if scoped:
        scoped_reasons = resolve_scoped_refusals(scoped, executed_paragraphs())
        if scoped_reasons:
            out.problems.extend(
                f"refused ({r.code}): {r.message}" for r in scoped_reasons
            )
            return out
        out.notes.extend(item.waiver_note for item in scoped)

    # 5. Surface analysis, normalization, linkage layout + neutralization.
    surface = analyze(parse_result.ast)
    out.surface = surface
    out.file_status_fields = analyze_file_status_fields(parse_result.ast)
    # PROCESS/CBL precompiler directives (IBM mainframe compiler-directing
    # statements preceding IDENTIFICATION DIVISION) parse fine as far as
    # cobolparser is concerned -- CobolParser.parse() blanks them out for its
    # own AST -- but `lines` here is what the splicer edits and what
    # eventually gets written as the instrumented source for GnuCOBOL to
    # compile. Left in place, they survive into that file verbatim and cobc
    # can reject options/syntax it doesn't recognize. Strip them the same way
    # before normalizing so they never reach the toolchain -- unless the
    # caller (mockymock export) wants them preserved for a real IBM compile
    # instead, which needs them exactly where GnuCOBOL can't tolerate them.
    if preserve_compiler_directives:
        lines = split_source_lines(
            normalize_fixed_format(split_source_lines(raw_source))
        )
    else:
        lines = split_source_lines(
            normalize_fixed_format(
                split_source_lines(strip_compiler_directives(raw_source))
            )
        )

    # Waived unresolved-COPY statements (step 4b) get commented out here:
    # comment-only, so no line number shifts for anything downstream, same
    # guarantee as the linkage neutralization below.
    for item in scoped_copies:
        if item.blank_span is not None:
            start, end = item.blank_span
            lines = comment_and_replace(lines, start, end, [])

    linkage_reasons = check_linkage_layout(parse_result.ast, lines)
    if linkage_reasons:
        out.problems.extend(f"refused ({r.code}): {r.message}" for r in linkage_reasons)
        return out
    linkage = linkage_plan(parse_result.ast)
    out.linkage = linkage
    if linkage is not None:
        # Comment-only, so it never shifts any line number the rest of the
        # pipeline derives from the AST's locations -- safe to always apply
        # before returning `lines`.
        lines = neutralize(lines, parse_result.ast, linkage)
        # Folding those items into WORKING-STORAGE gives them real storage,
        # which is exactly what makes `SET ADDRESS OF` on them illegal
        # afterwards -- redirect each receiving-side occurrence into a scratch
        # pointer. Width-preserving column edits, so like `neutralize` this
        # shifts nothing the rest of the pipeline depends on. Anything
        # unclassifiable already refused above via `check_linkage_layout`.
        address_of, _ = address_of_sites(lines, linkage)
        # A rebind to an address the program itself takes keeps its real
        # meaning: the item is made BASED over its own backing storage
        # instead (issue #226). Every other site -- above all a pointer a
        # mocked CALL fills in, NULL in a test run -- is still redirected.
        rebindable = rebindable_sites(lines, address_of)
        lines, linkage.rebindings = mark_based(lines, linkage, rebindable)
        rebound = {r.item_name for r in linkage.rebindings}
        kept = [site for site in rebindable if site.item_name.upper() in rebound]
        address_of = [site for site in address_of if site not in kept]
        out.linkage_address_of = address_of
        if address_of:
            lines = redirect_address_of(lines, address_of)
        # The fold gives every parameter storage, and the driver PERFORMs
        # rather than CALLs, so an omitted-argument test the selected cases
        # reach can never be true -- say so instead of letting that branch
        # go silently untested (issue #288).
        out.warnings.extend(
            omitted_argument_warnings(
                parse_result.ast,
                omitted_argument_tests(lines, linkage, rebound),
                executed_paragraphs(),
            )
        )

    # 5b. CICS implicit-linkage guardrails (DFHRESP/DFHVALUE macro calls,
    # an undeclared DFHCOMMAREA) -- independent of the LINKAGE guardrails
    # above, additive not exclusive-or. See
    # docs/2026-08-27-cics-eib-linkage-support-design.md.
    # A DFHRESP/DFHVALUE call confined to a paragraph no selected test
    # case can execute is held back and resolved against the same
    # reachability union step 4b uses; when waived it is rewritten in
    # place (width-preserving), because cobc has no CICS translator and
    # could not compile the unexpanded macro even in dead code.
    # DFHRESP(<condition>) is expanded to its EIBRESP number first, exactly
    # as the CICS translator would (width-preserving, so nothing moves);
    # only what that leaves behind -- DFHVALUE, an unknown condition, a
    # call split across lines -- reaches the macro guardrail below.
    lines, resp_expansions = expand_dfhresp(lines)
    if resp_expansions:
        out.notes.append(expansion_note(resp_expansions))
    cics_eib_reasons, cics_macro_scoped = check_cics_eib_layout_scoped(
        parse_result.ast, lines
    )
    if cics_macro_scoped:
        macro_reasons = resolve_scoped_refusals(
            cics_macro_scoped, executed_paragraphs()
        )
        if macro_reasons:
            cics_eib_reasons.extend(macro_reasons)
        else:
            for item in cics_macro_scoped:
                assert item.neutralize_span is not None
                macro_line, start_column, end_column = item.neutralize_span
                lines = replace_columns(
                    lines,
                    macro_line,
                    start_column,
                    end_column,
                    CICS_MACRO_PLACEHOLDER,
                )
                out.notes.append(item.waiver_note)
    if cics_eib_reasons:
        out.problems.extend(
            f"refused ({r.code}): {r.message}" for r in cics_eib_reasons
        )
        return out
    # The .cut's own text counts too: whatever it names is spliced into the
    # same build (issue #269). Full-line comments are not spliced.
    suite_lines = [
        line
        for line in read_utf8_source(cut_path).splitlines()
        if not line.lstrip().startswith("*>")
    ]
    out.cics_eib = cics_eib_plan(parse_result.ast, lines, suite_lines)
    out.lines = lines

    # 6. Nested-site annotation (must precede any nested-site check), then
    # nested-EXEC refusals.
    scope_map = collect_scope_map(parse_result.ast, lines)
    out.scope_map = scope_map
    annotate_nested_sites(surface, scope_map, lines)
    nested_exec_reasons = check_nested_exec(surface)
    if nested_exec_reasons:
        out.problems.extend(
            f"refused ({r.code}): {r.message}" for r in nested_exec_reasons
        )
        return out

    # 7. DATA DIVISION EXEC SQL pre-check (check-only: the transformed lines
    # are discarded -- the real transform runs after splicing).
    transformed, data_exec_reasons = transform_data_division_exec(
        lines, copybook_paths=copybook_paths
    )
    if data_exec_reasons:
        out.problems.extend(
            f"refused ({r.code}): {r.message}" for r in data_exec_reasons
        )
        return out

    # 7b. Every data-name the .cut writes into the driver must exist in the
    # program, or cobc rejects it at a line of a deleted sandbox copy
    # (issue #204). Checked against the transformed text, so a generated
    # SQLCA and EXEC SQL INCLUDE members count. Cumulative with step 8.
    out.problems.extend(
        f"refused ({r.code}): {r.message}"
        for r in check_cut_data_names(
            suite,
            transformed,
            getattr(parse_result.ast, "program_name", None),
            parse_result.ast,
        )
    )

    # 8. Per-test-case checks, then flow-mock (MOCK PARAGRAPH/SECTION) and
    # terminator layout -- accumulated across all cases rather than
    # short-circuiting, matching `run`'s behavior. The neutralized-GO-TO
    # set is computed over the same (ast, scope_map, lines) every splicing
    # command feeds find_goto_exit_plans, so the reachable set each case
    # is gated on agrees with the program that actually compiles -- a
    # "GO TO <own-exit-label>" spliced into EXIT PARAGRAPH no longer
    # cascades fall-through reachability past its exit label.
    neutralized_goto = neutralized_goto_targets(parse_result.ast, scope_map, lines)
    # BEFORE-ALL/BEFORE-EACH mocks are defaults shared by every case: each
    # needs to be reached by SOME test case or hook step, not by all of
    # them (refused after the loops below).
    shared_mocks = suite.before_each_mocks + suite.before_all_mocks
    shared_ids = frozenset(id(d) for d in shared_mocks)
    matched_ids: set[int] = set()
    for case_index, case in enumerate(suite.test_cases):
        case_reasons = check_test_case(
            surface,
            parse_result.ast,
            case,
            out.file_status_fields,
            neutralized_goto=neutralized_goto,
            shared=shared_ids,
            matched_out=matched_ids,
        )
        for r in case_reasons:
            out.problems.append(f"refused ({r.code}): {r.message}")
            if r.suggested_fix:
                out.problems.append("    Add to this TESTCASE:")
                out.problems.extend(
                    f"    {line}" for line in r.suggested_fix.splitlines()
                )
        if case_reasons:
            out.unmocked_reasons[case_index] = case_reasons
    # A hook PERFORM enters the program exactly like a TESTCASE's own
    # PERFORM, so it is gated the same way -- with the mocks in force while
    # it runs (docs/2026-10-10-suite-hooks-design.md). An EACH hook is
    # checked once per test case; identical problems are reported once.
    seen_hook_problems: set[str] = set()
    for check in suite.hook_checks():
        for r in check_test_case(
            surface,
            parse_result.ast,
            check.case,
            out.file_status_fields,
            neutralized_goto=neutralized_goto,
            # Every mock in force is a default here, the case's own
            # included: whether a case's mock is unmatched is decided by
            # that case's own check above, and a shared one by the sweep
            # below -- a hook PERFORM that doesn't reach it proves nothing.
            shared=shared_ids | {id(d) for d in check.case.mocks},
            matched_out=matched_ids,
        ):
            where = (
                check.hook
                if check.for_case is None
                else (f"{check.hook} (TESTCASE {check.for_case.name!r})")
            )
            problem = (
                f"refused ({r.code}): {where} PERFORM {check.step.target}: {r.message}"
            )
            key = f"{check.hook}|{check.step.line}|{r.code}|{r.suggested_fix}"
            if key in seen_hook_problems:
                continue
            seen_hook_problems.add(key)
            out.problems.append(problem)
            if r.suggested_fix:
                block = "BEFORE-ALL" if check.for_case is None else "BEFORE-EACH"
                out.problems.append(f"    Add to {block}:")
                out.problems.extend(
                    f"    {line}" for line in r.suggested_fix.splitlines()
                )
    # Whether a shared mock is reached is a property of the whole suite, not
    # of a --case/--tag selection: a mock only an unselected case reaches
    # just never fires in this run (issue #250). Only their matches are
    # wanted here -- an unselected case's own refusals are not this run's.
    unselected = [c for c in all_cases if not any(c is s for s in suite.test_cases)]
    if unselected and any(id(d) not in matched_ids for d in shared_mocks):
        for case in unselected:
            check_test_case(
                surface,
                parse_result.ast,
                case,
                out.file_status_fields,
                neutralized_goto=neutralized_goto,
                shared=shared_ids,
                matched_out=matched_ids,
            )
    for directive in shared_mocks:
        if id(directive) not in matched_ids:
            block = (
                "BEFORE-EACH"
                if any(directive is d for d in suite.before_each_mocks)
                else "BEFORE-ALL"
            )
            out.problems.append(
                f"refused (UNMATCHED_MOCK): {block} MOCK {directive.describe()} "
                f"is not reached by any test case or hook step"
            )
    out.problems.extend(
        f"refused ({r.code}): {r.message}"
        for r in check_flow_mocks(parse_result.ast, suite, lines)
    )
    out.problems.extend(
        f"refused ({r.code}): {r.message}"
        for r in check_terminator_layout(
            surface, parse_result.ast, suite, scope_map, lines
        )
    )
    # 9. Synthesized CAPTURE targets. Fail closed: an argument whose layout
    # cannot be mirrored exactly would otherwise reach the compiler as a
    # missing declaration, or (worse) as a field whose type silently
    # disagrees with the value moved into it.
    out.captures, capture_problems = plan_captures(
        parse_result.ast, suite, surface, lines
    )
    out.problems.extend(
        f"refused (UNRESOLVED_CAPTURE_TARGET): {problem}"
        for problem in capture_problems
    )
    # 10. BEFORE-ALL state handover: every item it may change must be
    # restorable exactly at the start of each test case, or the suite is
    # refused -- a partially restored state is a silently wrong test.
    if suite.before_all_steps:
        from mockymock.splicer.snapshot import plan_snapshot

        out.snapshot, snapshot_problems = plan_snapshot(
            parse_result.ast,
            out.linkage.linkage_items if out.linkage is not None else None,
            _synthesized_groups(out.cics_eib, transformed),
            (
                [r.item_name for r in out.linkage.rebindings]
                if out.linkage is not None
                else None
            ),
        )
        out.problems.extend(
            f"refused (UNSAVABLE_BEFORE_ALL_STATE): {problem}"
            for problem in snapshot_problems
        )
    return out
