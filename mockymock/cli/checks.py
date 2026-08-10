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

if TYPE_CHECKING:
    from cobolparser import ParseResult

    from mockymock.analysis.linkage import LinkagePlan
    from mockymock.analysis.mock_surface import MockSurface
    from mockymock.dsl.model import MockTestSuite
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
    file_status_fields: dict[str, str] | None = None
    # Transparency lines for checks that deliberately did NOT refuse: a
    # paragraph-scoped parse warning / unresolved COPY waived because no
    # selected test case can execute its paragraph (the COPY additionally
    # commented out of `lines`). Callers should print these with their own
    # command prefix -- silently proceeding past a warning, or silently
    # editing source a .cut author didn't write, would both be surprises.
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


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
    for tag in tag_names or []:
        if tag not in available_tags:
            listing = ", ".join(sorted(repr(t) for t in available_tags)) or "none"
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
        expand_copybooks,
        normalize_fixed_format,
        strip_compiler_directives,
    )

    from mockymock.analysis.flow_mocks import check_flow_mocks
    from mockymock.analysis.linkage import linkage_plan
    from mockymock.analysis.mock_surface import analyze, analyze_file_status_fields
    from mockymock.analysis.refusal import (
        check_expansion_warnings,
        check_linkage_layout,
        check_nested_exec,
        check_terminator_layout,
        check_test_case,
        check_unresolved_copybooks_scoped,
        check_whole_program_scoped,
        resolve_scoped_refusals,
        union_executed_paragraphs,
    )
    from mockymock.dsl.parser import CutParseError, parse_cut
    from mockymock.splicer.linkage import neutralize
    from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map
    from mockymock.splicer.sqlca import transform_data_division_exec
    from mockymock.splicer.stub_writer import comment_and_replace

    out = StaticCheckResult()

    # 1. Read source; expand copybooks and check expansion warnings.
    raw_source = source_path.read_text(encoding="utf-8")
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
    parse_result = parse_cobol(raw_source, filename=source_path.name)
    out.parse_result = parse_result
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
        suite = parse_cut(cut_path.read_text(encoding="utf-8"))
    except CutParseError as exc:
        out.problems.append(f"invalid .cut file {cut_path}: {exc}")
        return out
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
    scoped = scoped_warnings + scoped_copies
    if scoped:
        executed = union_executed_paragraphs(parse_result.ast, suite)
        scoped_reasons = resolve_scoped_refusals(scoped, executed)
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
        lines = normalize_fixed_format(raw_source.splitlines()).splitlines()
    else:
        lines = normalize_fixed_format(
            strip_compiler_directives(raw_source).splitlines()
        ).splitlines()

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
    _, data_exec_reasons = transform_data_division_exec(
        lines, copybook_paths=copybook_paths
    )
    if data_exec_reasons:
        out.problems.extend(
            f"refused ({r.code}): {r.message}" for r in data_exec_reasons
        )
        return out

    # 8. Per-test-case checks, then flow-mock (MOCK PARAGRAPH/SECTION) and
    # terminator layout -- accumulated across all cases rather than
    # short-circuiting, matching `run`'s behavior.
    for case in suite.test_cases:
        out.problems.extend(
            f"refused ({r.code}): {r.message}"
            for r in check_test_case(
                surface, parse_result.ast, case, out.file_status_fields
            )
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
    return out
