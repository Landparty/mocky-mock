"""Static side of `USE REAL CALL` (load-module integration tests).

A suite stays one compiled binary entered through one program. `USE REAL
CALL "X" FROM "x.cbl"` adds program X to that binary: X's source is
instrumented with the same suite's mocks (its own files, SQL, CICS, DLI,
outside CALLs) and linked in, and the entry program's `CALL "X"` runs it
for real. See docs/2026-11-01-real-call-integration-design.md.

This module does everything that needs no toolchain, so `lint` and `run`
agree on it:

* `collect_real_specs` -- which programs are real, from which file; a
  key named with two different files, or a file that does not exist, is
  refused.
* `prepare_real_program` -- read, expand copybooks, parse and analyze
  one real program, and check that its PROGRAM-ID is the CALL key.
* `check_real_program` -- the fail-closed gate. A real program is entered
  at the top of its PROCEDURE DIVISION and may run any of its code, so
  every boundary site in it must be answered, in every test case that
  makes it real, by a MOCK (or another USE REAL CALL). No reachability
  narrowing: over-asking for a mock is safe, running an unmocked boundary
  is not.
* `suite_view` -- the suite as one program sees it: each case keeps only
  the directives that match a site of that program, so the per-program
  checks (unmatched mocks, unknown data names) judge each directive
  against the program it is meant for.

Nothing here edits source; `splicer.real_programs` turns a prepared real
program into the instrumented copy that is compiled.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from mockymock._lines import SourceEncodingError, read_utf8_source, split_source_lines
from mockymock.analysis.refusal import (
    RefusalReason,
    directive_matches_site,
    matching_directives,
)
from mockymock.analysis.refusal._types import (
    _UNMOCKED_CODES,
    _UNMOCKED_FILE_OP_CODE,
    _UNSUPPORTED_SITE_CODES,
)
from mockymock.dsl.model import (
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
)

if TYPE_CHECKING:
    from mockymock.analysis.mock_surface import BoundarySite, MockSurface


@dataclass
class RealSpec:
    """One `USE REAL CALL` program: the CALL key and its resolved source."""

    key: str
    source: Path
    line: int  # .cut line of the first USE REAL naming it


@dataclass
class PreparedReal:
    """One real program, analyzed and ready to splice."""

    spec: RealSpec
    program_id: str
    ast: object
    lines: list[str]
    surface: MockSurface
    file_status_fields: dict[str, str]
    warnings: list[str] = field(default_factory=list)


def real_directives(suite: MockTestSuite) -> list[MockDirective]:
    """Every USE REAL CALL directive in the suite, first appearance order,
    each object once."""
    seen: dict[int, MockDirective] = {}
    for directive in [
        *(d for case in suite.test_cases for d in case.mocks),
        *suite.before_all_mocks,
    ]:
        if directive.is_real:
            seen.setdefault(id(directive), directive)
    return list(seen.values())


def collect_real_specs(
    suite: MockTestSuite, cut_path: Path
) -> tuple[list[RealSpec], list[RefusalReason]]:
    """The real programs a suite links in, by CALL key (case-insensitive,
    as a program name is), each resolved against the `.cut` file's folder."""
    specs: dict[str, RealSpec] = {}
    reasons: list[RefusalReason] = []
    for directive in real_directives(suite):
        assert directive.real_source is not None
        path = Path(directive.real_source)
        if not path.is_absolute():
            path = cut_path.parent / path
        path = path.resolve()
        name = directive.key.upper()
        known = specs.get(name)
        if known is not None:
            if known.source != path:
                reasons.append(
                    RefusalReason(
                        code="CONFLICTING_REAL_SOURCE",
                        message=(
                            f".cut line {directive.real_line}: USE REAL CALL "
                            f'"{directive.key}" names {directive.real_source}, '
                            f"but line {known.line} already linked {known.source} "
                            f"for it -- one binary can hold one program "
                            f"{name}"
                        ),
                    )
                )
            continue
        if not path.is_file():
            reasons.append(
                RefusalReason(
                    code="REAL_SOURCE_NOT_FOUND",
                    message=(
                        f".cut line {directive.real_line}: USE REAL CALL "
                        f'"{directive.key}" FROM "{directive.real_source}": '
                        f"no such file ({path})"
                    ),
                )
            )
            continue
        specs[name] = RealSpec(directive.key, path, directive.real_line)
    return list(specs.values()), reasons


def prepare_real_program(
    spec: RealSpec, copybook_paths: list[str] | None
) -> tuple[PreparedReal | None, list[RefusalReason]]:
    """Parse and analyze one real program. Its LINKAGE SECTION is left as
    it is: the program is CALLed with real arguments, not PERFORMed."""
    from cobolparser import parse_cobol
    from cobolparser.preprocess import (
        expand_copybooks,
        normalize_fixed_format,
        strip_compiler_directives,
    )

    from mockymock.analysis.flow_targets import normalize_flow_targets
    from mockymock.analysis.mock_surface import analyze, analyze_file_status_fields
    from mockymock.analysis.refusal import check_nested_exec, check_whole_program
    from mockymock.debugging_lines import activate_debugging_lines
    from mockymock.splicer.cics_resp import expand_dfhresp
    from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

    where = f'real program "{spec.key}" ({spec.source.name})'

    def refused(code: str, message: str) -> tuple[None, list[RefusalReason]]:
        return None, [RefusalReason(code=code, message=f"{where}: {message}")]

    try:
        raw = read_utf8_source(spec.source)
    except SourceEncodingError as exc:
        return refused(code="REAL_SOURCE_UNREADABLE", message=str(exc))
    if copybook_paths:
        try:
            raw = expand_copybooks(raw, copybook_paths=copybook_paths).expanded_source
        except Exception as exc:  # noqa: BLE001 -- surfaced verbatim
            return refused(
                code="REAL_SOURCE_UNREADABLE",
                message=f"copybook expansion failed: {exc}",
            )
    raw = activate_debugging_lines(raw)
    result = parse_cobol(raw, filename=spec.source.name)
    if not result.success or result.ast is None:
        detail = "; ".join(str(error) for error in result.errors[:3])
        return refused(code="PARSE_ERROR", message=f"does not parse: {detail}")
    whole = check_whole_program(result)
    if whole:
        return None, [
            RefusalReason(code=r.code, message=f"{where}: {r.message}") for r in whole
        ]
    normalize_flow_targets(result.ast)
    program_id = str(getattr(result.ast, "program_name", "") or "")
    if program_id.upper() != spec.key.upper():
        return refused(
            code="REAL_PROGRAM_ID_MISMATCH",
            message=f"its PROGRAM-ID is {program_id or '(none)'}, not {spec.key} -- "
            f"the CALL would not reach it; point FROM at the source of "
            f"{spec.key}",
        )
    lines = split_source_lines(
        normalize_fixed_format(split_source_lines(strip_compiler_directives(raw)))
    )
    lines, _ = expand_dfhresp(lines)
    surface = analyze(result.ast)
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    nested = check_nested_exec(surface)
    if nested:
        return None, [
            RefusalReason(code=r.code, message=f"{where}: {r.message}") for r in nested
        ]
    prepared = PreparedReal(
        spec=spec,
        program_id=program_id,
        ast=result.ast,
        lines=lines,
        surface=surface,
        file_status_fields=analyze_file_status_fields(result.ast),
    )
    for number, text in enumerate(lines, start=1):
        if _STOP_RUN_RE.search(_code(text)):
            prepared.warnings.append(
                f"warning (REAL_PROGRAM_STOP_RUN): {where} line {number}: "
                f"STOP RUN ends the whole test binary if a test reaches it "
                f"-- the case is then reported as crashed"
            )
    return prepared, []


_STOP_RUN_RE = re.compile(r"(?<![\w-])STOP\s+RUN(?![\w-])", re.IGNORECASE)


def _code(line: str) -> str:
    """`line` without a `*>` comment or quoted literal text."""
    line = re.sub(r"\"[^\"]*\"|'[^']*'", '""', line)
    return line.split("*>", 1)[0]


def active_cases(suite: MockTestSuite, key: str) -> list[tuple[int, MockTestCase]]:
    """(index, case) of every test case whose mocks make `key` real."""
    name = key.upper()
    return [
        (index, case)
        for index, case in enumerate(suite.test_cases)
        if any(d.is_real and d.key.upper() == name for d in case.mocks)
    ]


def check_real_program(
    prepared: PreparedReal, suite: MockTestSuite
) -> list[RefusalReason]:
    """Every boundary of the real program must be answered in every case
    that makes it real. See the module docstring for why there is no
    reachability narrowing."""
    from mockymock.dsl.generator import directive_snippet

    where = f'real program "{prepared.spec.key}"'
    reasons: list[RefusalReason] = []
    reported: set[tuple[str, int]] = set()
    for _, case in active_cases(suite, prepared.spec.key):
        for site in prepared.surface.boundary_sites:
            matches = matching_directives(case.mocks, site)
            if site.category is None:
                # CANCEL, STOP RUN, GOBACK, EXIT PROGRAM run as written in a
                # real program (STOP RUN is warned about in prepare); the
                # rest has no mock category, so the program cannot run.
                if site.label in _RUNS_AS_WRITTEN:
                    continue
                if (site.label, site.line) not in reported:
                    reported.add((site.label, site.line))
                    if site.label in _UNSUPPORTED_SITE_CODES:
                        code = _UNSUPPORTED_SITE_CODES[site.label][0]
                    elif site.label == "dynamic CALL":
                        code = "DYNAMIC_CALL"
                    else:
                        code = "UNSUPPORTED_SORT_MERGE"
                    reasons.append(
                        RefusalReason(
                            code=code,
                            message=(
                                f"{where} line {site.line} (paragraph "
                                f"'{site.paragraph_name}'): {site.label} has no "
                                f"mock category, so the program cannot run in "
                                f"a test"
                            ),
                        )
                    )
                continue
            if len(matches) > 1:
                reasons.append(
                    RefusalReason(
                        code="AMBIGUOUS_MOCK",
                        message=(
                            f"TESTCASE {case.name!r}: {where} line {site.line} "
                            f"is matched by " + ", ".join(d.describe() for d in matches)
                        ),
                    )
                )
                continue
            if not matches:
                snippet = directive_snippet(
                    site, prepared.surface, prepared.file_status_fields
                )
                code = _UNMOCKED_CODES.get(site.category, _UNMOCKED_FILE_OP_CODE)
                reasons.append(
                    RefusalReason(
                        code=code,
                        message=(
                            f"TESTCASE {case.name!r} runs the {where}, but "
                            f"its {site.label} at line {site.line} (paragraph "
                            f"'{site.paragraph_name}') is not mocked -- a real "
                            f"program runs only with every boundary it has "
                            f"answered"
                        ),
                        suggested_fix=snippet,
                    )
                )
                continue
            if site.nested and site.span is None:
                reasons.append(
                    RefusalReason(
                        code="UNSUPPORTED_NESTED_MOCK_TARGET",
                        message=(
                            f"{where} line {site.line}: the {site.label} is "
                            f"nested where it cannot be spliced"
                            + (
                                f" ({site.unspliceable_reason})"
                                if site.unspliceable_reason
                                else ""
                            )
                        ),
                    )
                )
            elif not site.nested and site.unspliceable_reason:
                reasons.append(
                    RefusalReason(
                        code="UNSUPPORTED_MOCK_TARGET_LAYOUT",
                        message=(
                            f"{where} line {site.line}: the {site.label} "
                            f"{site.unspliceable_reason} -- put the statement "
                            f"on its own line(s)"
                        ),
                    )
                )
    return _dedupe(reasons)


_RUNS_AS_WRITTEN = frozenset({"CANCEL", "STOP RUN", "GOBACK", "EXIT PROGRAM"})


def _dedupe(reasons: list[RefusalReason]) -> list[RefusalReason]:
    seen: set[tuple[str, str]] = set()
    out: list[RefusalReason] = []
    for reason in reasons:
        if (reason.code, reason.message) in seen:
            continue
        seen.add((reason.code, reason.message))
        out.append(reason)
    return out


def matched_directive_ids(surface: MockSurface, suite: MockTestSuite) -> set[int]:
    """Ids of every directive that matches some site of `surface`, in any
    case (no reachability: whether it fires is the gate's business)."""
    sites: list[BoundarySite] = [
        s for s in surface.boundary_sites if s.category is not None
    ]
    return {
        id(directive)
        for directive in [
            *(d for case in suite.test_cases for d in case.mocks),
            *suite.before_all_mocks,
        ]
        if any(directive_matches_site(directive, site) for site in sites)
        or (
            # A dynamic CALL can reach any real program
            # (injector.real_dynamic_routes).
            directive.is_real
            and any(site.category is MockCategory.DYNCALL for site in sites)
        )
    }


def suite_view(suite: MockTestSuite, keep: set[int]) -> MockTestSuite:
    """`suite` with every directive whose id is not in `keep` dropped from
    each case's mocks and from the BEFORE blocks -- directive objects stay
    shared (identity matters to the BEFORE-* sweep)."""

    def kept(directives: list[MockDirective]) -> list[MockDirective]:
        return [d for d in directives if id(d) in keep]

    return dataclasses.replace(
        suite,
        test_cases=[
            dataclasses.replace(case, mocks=kept(case.mocks))
            for case in suite.test_cases
        ],
        before_each_mocks=kept(suite.before_each_mocks),
        before_all_mocks=kept(suite.before_all_mocks),
    )


def program_only_view(suite: MockTestSuite, keep: set[int]) -> MockTestSuite:
    """`suite_view` for a real program: only its own directives, and none of
    the entry program's setup MOVEs, EXPECTs, VERIFYs or hook steps (they
    name the entry program's data, not this one's)."""
    view = suite_view(suite, keep)
    return dataclasses.replace(
        view,
        test_cases=[
            dataclasses.replace(
                case,
                setup_moves=[],
                setup_move_lines=[],
                expectations=[],
                verifications=[],
            )
            for case in view.test_cases
        ],
        before_all_steps=[],
        before_each_steps=[],
        after_each_steps=[],
        after_all_steps=[],
    )


def entry_program_view(suite: MockTestSuite, elsewhere_only: set[int]) -> MockTestSuite:
    """`suite` as the entry program's own checks see it: without the
    directives that answer only sites of real programs, and without the
    VERIFYs of those directives (their tally is declared all the same: the
    registry is built from the whole suite)."""
    every = {
        id(d)
        for d in [
            *(d for case in suite.test_cases for d in case.mocks),
            *suite.before_all_mocks,
        ]
    }
    view = suite_view(suite, every - elsewhere_only)
    cases = []
    for full, case in zip(suite.test_cases, view.test_cases, strict=True):
        kept_keys = {(d.category, d.key) for d in case.mocks}
        dropped = {
            (d.category, d.key) for d in full.mocks if id(d) in elsewhere_only
        } - kept_keys
        cases.append(
            dataclasses.replace(
                case,
                verifications=[
                    v for v in case.verifications if (v.category, v.key) not in dropped
                ],
            )
        )
    return dataclasses.replace(view, test_cases=cases)
