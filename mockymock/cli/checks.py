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
) -> StaticCheckResult:
    """Faithful transcription of `_cmd_run`'s pre-toolchain check sequence,
    including its short-circuit behavior: each numbered stage stops the
    pipeline if it finds problems, except the final per-test-case stage,
    which accumulates across every case before returning."""
    from cobolparser import parse_cobol
    from cobolparser.preprocess import expand_copybooks, normalize_fixed_format

    from mockymock.analysis.linkage import linkage_plan
    from mockymock.analysis.mock_surface import analyze
    from mockymock.analysis.refusal import (
        check_expansion_warnings,
        check_linkage_layout,
        check_nested_exec,
        check_terminator_layout,
        check_test_case,
        check_unresolved_copybooks,
        check_whole_program,
    )
    from mockymock.dsl.parser import CutParseError, parse_cut
    from mockymock.splicer.linkage import neutralize
    from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map
    from mockymock.splicer.sqlca import transform_data_division_exec

    out = StaticCheckResult()

    # 1. Read source; expand copybooks and check expansion warnings.
    raw_source = source_path.read_text()
    if copybook_paths:
        expansion = expand_copybooks(raw_source, copybook_paths=copybook_paths)
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
    parse_result = parse_cobol(raw_source, filename=source_path.name)
    out.parse_result = parse_result
    whole_program_reasons = check_whole_program(parse_result)
    if whole_program_reasons:
        out.problems.extend(
            f"refused ({r.code}): {r.message}" for r in whole_program_reasons
        )
        if not parse_result.success:
            out.problems.extend(f"  {error}" for error in parse_result.errors)
        return out

    # 3. Unresolved copybooks.
    copybook_reasons = check_unresolved_copybooks(raw_source)
    if copybook_reasons:
        out.problems.extend(
            f"refused ({r.code}): {r.message}" for r in copybook_reasons
        )
        return out

    # 4. Parse the .cut file; apply any --case/--tag selection immediately so
    # every later per-case check sees only the cases that will actually run.
    try:
        suite = parse_cut(cut_path.read_text())
    except CutParseError as exc:
        out.problems.append(f"invalid .cut file {cut_path}: {exc}")
        return out
    selection_problems = filter_suite_cases(suite, case_names, tag_names)
    if selection_problems:
        out.problems.extend(selection_problems)
        return out
    out.suite = suite

    # 5. Surface analysis, normalization, linkage layout + neutralization.
    surface = analyze(parse_result.ast)
    out.surface = surface
    lines = normalize_fixed_format(raw_source.splitlines()).splitlines()

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

    # 8. Per-test-case checks, then terminator layout -- accumulated across
    # all cases rather than short-circuiting, matching `run`'s behavior.
    for case in suite.test_cases:
        out.problems.extend(
            f"refused ({r.code}): {r.message}"
            for r in check_test_case(surface, parse_result.ast, case)
        )
    out.problems.extend(
        f"refused ({r.code}): {r.message}"
        for r in check_terminator_layout(
            surface, parse_result.ast, suite, scope_map, lines
        )
    )
    return out
