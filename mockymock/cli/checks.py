"""Shared static-check pipeline for `mockymock run` and `mockymock lint`.

Extracted from `_cmd_run` per docs/2026-07-18-cut-lint-command-design.md so
the two commands can never disagree about what counts as a refusal. Every
check here is pure static analysis over the parsed AST and the `.cut`
model -- this module must never import `mockymock.runtime.docker_toolchain`
(that structural guarantee is what makes `lint` Docker-free).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mockymock._lines import (
    SourceEncodingError,
    read_utf8_source,
    split_cut_lines,
    split_source_lines,
)
from mockymock.debugging_lines import activate_debugging_lines

if TYPE_CHECKING:
    from cobolparser import ParseResult

    from mockymock.analysis.cics_eib import CicsEibPlan
    from mockymock.analysis.linkage import AddressOfSite, LinkagePlan
    from mockymock.analysis.mock_surface import MockSurface
    from mockymock.analysis.real_programs import PreparedReal
    from mockymock.analysis.refusal import RefusalReason
    from mockymock.dsl.model import MockTestSuite
    from mockymock.splicer.captures import CapturePlan
    from mockymock.splicer.snapshot import StateSnapshot
    from mockymock.splicer.source_map import ScopeMap


#: What `debug`, `export` and `mutate` say about a suite with USE REAL CALL:
#: only `run` and `lint` link real programs so far.
REAL_CALL_UNSUPPORTED = (
    "this suite has USE REAL CALL programs, which only `run` and `lint` "
    "support so far -- debug, export and mutate a unit suite of the entry "
    "program instead"
)


@dataclass
class StaticCheckResult:
    """Everything the check phase learned. `problems` holds pre-formatted,
    unprefixed lines ("refused (CODE): ..." or raw indented parse-error
    lines) in print order; the artifact fields are populated only when the
    pipeline got far enough to produce them, so a clean result carries
    everything `_cmd_run` needs to proceed straight to splicing."""

    problems: list[str] = field(default_factory=list)
    # Expanded line -> (file, line), "<main>" for the program itself; empty
    # without copybook expansion (issue #241).
    source_location_map: dict[int, tuple[str, int]] = field(default_factory=dict)
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
    # LINKAGE items whose `SET ADDRESS OF` `run` keeps as a real rebind
    # (BASED, issue #226) but `model_rebinds=False` redirected instead
    # (export: IBM COBOL has no BASED clause, issue #321).
    unmodelled_rebinds: list[str] = field(default_factory=list)
    cics_eib: CicsEibPlan | None = None
    # USE REAL FILE (expand_real_files): each real file's SELECT line in
    # `lines` and what comparing it needs.
    real_file_selects: dict[str, int] = field(default_factory=dict)
    real_file_layouts: dict[str, Any] = field(default_factory=dict)
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
    # Ids of unmocked boundary statements some case reaches only by GO TO
    # fall-through (issue #351): not refused, but every splicing pipeline
    # replaces each with a trap that fails the case reaching it.
    fallthrough_traps: set[int] = field(default_factory=set)
    # `USE REAL CALL` programs, analyzed (analysis.real_programs): every
    # splice-and-compile pipeline instruments and links each one.
    real_programs: list[PreparedReal] = field(default_factory=list)

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
    lines.extend(
        f"01  {mode_field}  PIC X VALUE SPACE."
        for _, mode_field in _open_mode_fields(checked)
    )
    return lines or None


def _open_mode_fields(checked: StaticCheckResult) -> list[tuple[str, str]]:
    """(file, field) for the open modes the spliced OPENs record for the
    program's USE AFTER EXCEPTION procedures (`analysis.declaratives`)."""
    uses = checked.surface.use_procedures if checked.surface is not None else None
    return uses.mode_fields() if uses is not None else []


def extra_reset_lines_for(checked: StaticCheckResult) -> list[str]:
    """Reset lines the synthesized capture targets need between test cases,
    and the save/restore of every INDEXED BY index (issue #189). Kept
    beside `extra_working_storage` so the declaration and the reset can
    never be added in one pipeline and forgotten in another -- the suite
    compiles to ONE binary, so a capture left unreset would let a case that
    never reached its CALL assert against the previous case's value."""
    from mockymock.splicer.captures import capture_reset_lines
    from mockymock.splicer.reset import index_reset_lines

    return (
        capture_reset_lines(checked.captures)
        + index_reset_lines(_index_names(checked))
        # Every case starts with its files closed.
        + [
            f"MOVE SPACE TO {mode_field}"
            for _, mode_field in _open_mode_fields(checked)
        ]
        # Every case starts with the program's GO TOs as written.
        + list(checked.surface.alter_resets if checked.surface is not None else ())
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


def no_assertion_warnings(
    suite: MockTestSuite, cut_text: str | None = None
) -> list[str]:
    """One pre-formatted, unprefixed warning line per TESTCASE with no
    EXPECT and no VERIFY. Warnings, not problems: such a case is valid and
    passes whenever its PERFORM runs, so lint flags it without failing
    (like PHPUnit's "risky" status) and `run` marks its result the same
    way. The `.cut line N` wording is what lets an editor place the
    diagnostic on the TESTCASE header. PROVIDER rows expand to cases that
    share one header line, so each line is reported once.

    With `cut_text`, a case that still holds `*> STUB EXPECT` comments is
    told so: it is the same case `generate` leaves out of its "asserts
    nothing" count, and `run --record-expectations` is what fixes it."""
    warnings: list[str] = []
    seen_lines: set[int] = set()
    stubbed = stub_case_lines(cut_text, suite) if cut_text is not None else {}
    for case in suite.test_cases:
        if case.assertion_count:
            continue
        if case.line:
            if case.line in seen_lines:
                continue
            seen_lines.add(case.line)
        where = f".cut line {case.line}: " if case.line else ""
        stubs = stubbed.get(case.line, 0) if case.line else 0
        if stubs:
            warnings.append(
                f'warning ({NO_ASSERTION}): {where}TESTCASE "{case.name}" asserts '
                f"nothing yet -- its {stubs} `*> STUB EXPECT` comment(s) become "
                f"EXPECTs when you run `mockymock run --record-expectations`"
            )
            continue
        warnings.append(
            f'warning ({NO_ASSERTION}): {where}TESTCASE "{case.name}" asserts '
            f"nothing -- it passes whenever its PERFORM runs. Add an EXPECT "
            f"on what it writes or a VERIFY on what it calls"
        )
    return warnings


def stub_case_lines(cut_text: str, suite: MockTestSuite) -> dict[int, int]:
    """TESTCASE header line -> how many `*> STUB EXPECT` comments that
    case's block holds (cases with none are absent). The block runs from
    the header to the line before the next TESTCASE header."""
    lines = split_cut_lines(cut_text)
    starts = sorted({case.line for case in suite.test_cases if case.line})
    counts: dict[int, int] = {}
    for index, start in enumerate(starts):
        end = starts[index + 1] - 1 if index + 1 < len(starts) else len(lines)
        found = sum(1 for line in lines[start - 1 : end] if "*> STUB EXPECT" in line)
        if found:
            counts[start] = found
    return counts


def cases_asserting_nothing(cut_text: str, *, stubs_count: bool) -> list[str]:
    """`TESTCASE "X"` labels (with their .cut line) of every case in
    `cut_text` with no EXPECT and no VERIFY -- and, when `stubs_count`, no
    `*> STUB EXPECT` comment either, i.e. nothing `run
    --record-expectations` could turn into one. What `generate`/`init` warn
    about instead of reporting such a suite as done (issue #275). A suite
    that does not parse yields nothing here: lint reports that."""
    from mockymock.dsl.parser import CutParseError, parse_cut

    try:
        suite = parse_cut(cut_text)
    except CutParseError:
        return []
    stubbed = stub_case_lines(cut_text, suite)
    found: list[str] = []
    seen: set[int] = set()
    for case in suite.test_cases:
        if case.assertion_count or case.line in seen:
            continue
        if case.line:
            seen.add(case.line)
        if stubs_count and case.line and case.line in stubbed:
            continue
        where = f".cut line {case.line}: " if case.line else ""
        found.append(f'{where}TESTCASE "{case.name}"')
    return found


def filter_suite_cases(
    suite: MockTestSuite,
    case_names: list[str] | None,
    tag_names: list[str] | None,
    case_positions: list[int] | None = None,
) -> list[str]:
    """Filter `suite.test_cases` in place to the selection `--case`/`--tag`
    describe (a case is kept if it matches any requested name or carries any
    requested tag). Returns problem lines for selections that match nothing;
    an empty return means the filter applied cleanly (or no filter was
    given).

    `case_positions` is `run`'s own selection for rerunning the cases a
    crash kept from running: each TESTCASE's 1-based position in the
    suite, which, unlike its name, is unique, and unlike its line survives
    the `.cut` rewrite of `--record-expectations`. Selecting them by name
    reran a crashed case whose name a later case shares, and never ran the
    later one."""
    problems: list[str] = []
    if case_positions is not None:
        wanted_positions = set(case_positions)
        suite.test_cases = [
            case
            for position, case in enumerate(suite.test_cases, start=1)
            if position in wanted_positions
        ]
    if not case_names and not tag_names:
        return problems

    available = {case.name for case in suite.test_cases}
    for name in case_names or []:
        if name not in available:
            listing = ", ".join(repr(c.name) for c in suite.test_cases)
            problems.append(
                f"no TESTCASE named {name!r} in this suite (available: {listing})"
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


_SOURCE_LINE_RE = re.compile(r"(?<!\.cut )(?<![\w.-])line (\d+)\b")


def source_line_relabeler(
    source_map: dict[int, tuple[str, int]] | None,
) -> Callable[[str], str]:
    """A function rewriting every `line N` in a message (N a line of the
    copybook-expanded source) into the file the user has open: `line M`
    for a line of the program itself, `line M of CPY.CPY` for one a
    copybook brought in. Every COPY above a site shifted the reported
    line by the copybook's length (issue #241). `.cut line N` is left
    alone, and so is everything when there is no source map."""
    if not source_map:
        return lambda text: text

    def label(match: re.Match[str]) -> str:
        origin = source_map.get(int(match.group(1)))
        if origin is None:
            return match.group(0)
        origin_file, origin_line = origin
        if origin_file == "<main>":
            return f"line {origin_line}"
        return f"line {origin_line} of {Path(origin_file).name}"

    return lambda text: _SOURCE_LINE_RE.sub(label, text)


def run_static_checks(
    source_path: Path,
    cut_path: Path,
    copybook_paths: list[str] | None,
    case_names: list[str] | None = None,
    tag_names: list[str] | None = None,
    preserve_compiler_directives: bool = False,
    model_rebinds: bool = True,
    case_positions: list[int] | None = None,
) -> StaticCheckResult:
    """Faithful transcription of `_cmd_run`'s pre-toolchain check sequence,
    including its short-circuit behavior: each numbered stage stops the
    pipeline if it finds problems, except the final per-test-case stage,
    which accumulates across every case before returning.

    Refusal problems and notes name lines of the `.cbl` (or copybook) the
    user has open, not of the copybook-expanded source (issue #241)."""
    out = _run_static_checks(
        source_path,
        cut_path,
        copybook_paths,
        case_names,
        tag_names,
        preserve_compiler_directives,
        model_rebinds,
        case_positions,
    )
    relabel = source_line_relabeler(out.source_location_map)
    out.problems = [
        relabel(problem) if problem.startswith("refused (") else problem
        for problem in out.problems
    ]
    out.notes = [relabel(note) for note in out.notes]
    return out


def _run_static_checks(
    source_path: Path,
    cut_path: Path,
    copybook_paths: list[str] | None,
    case_names: list[str] | None,
    tag_names: list[str] | None,
    preserve_compiler_directives: bool,
    model_rebinds: bool = True,
    case_positions: list[int] | None = None,
) -> StaticCheckResult:
    from cobolparser import parse_cobol
    from cobolparser.preprocess import (
        CopybookNotFoundError,
        expand_copybooks,
        normalize_fixed_format,
        strip_compiler_directives,
    )

    from mockymock.analysis.cics_eib import cics_eib_plan
    from mockymock.analysis.cut_names import (
        check_cut_data_names,
        undeclared_program_names,
    )
    from mockymock.analysis.flow_mocks import check_flow_mocks
    from mockymock.analysis.flow_targets import normalize_flow_targets
    from mockymock.analysis.linkage import (
        address_of_sites,
        linkage_plan,
        omitted_argument_tests,
        omitted_argument_warnings,
        rebindable_sites,
    )
    from mockymock.analysis.mock_surface import (
        analyze,
        analyze_file_status_fields,
        promote_clock_accepts,
    )
    from mockymock.analysis.refusal import (
        CICS_MACRO_PLACEHOLDER,
        check_cics_eib_layout_scoped,
        check_clause_bodies,
        check_expansion_warnings,
        check_linkage_layout,
        check_mock_body_line_length,
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
            expansion = expand_copybooks(
                raw_source,
                copybook_paths=copybook_paths,
                preserve_source_locations=True,
            )
        except CopybookNotFoundError as exc:
            out.problems.append(f"copybook expansion failed: {exc}")
            out.problems.append(copybook_not_found_hint(exc))
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
        out.source_location_map = dict(expansion.source_location_map or {})

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
    if not suite.test_cases:
        # `run` would build, run nothing, and fail with only "0 run, 0
        # failed"; say why up front, in lint too (issue #275).
        out.problems.append(
            f"{cut_path} has no TESTCASE -- there is nothing to run. Add one, "
            f"or scaffold the suite with 'mockymock generate'"
        )
        return out
    # The unselected cases still count towards whether a BEFORE-EACH/
    # BEFORE-ALL mock is reached at all (step 8's sweep, issue #250).
    all_cases = list(suite.test_cases)
    selection_problems = filter_suite_cases(
        suite, case_names, tag_names, case_positions
    )
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
    if parse_result.ast is None:  # a failed parse refused in step 2
        out.problems.append(f"{source_path.name}: no AST to analyze")
        return out
    surface = analyze(parse_result.ast)
    # A clock ACCEPT (FROM DATE/TIME/DAY/DAY-OF-WEEK) is mockable only when
    # a MOCK names it (issue #240): an opt-in site, spliced only then.
    promote_clock_accepts(
        surface,
        [
            *(d for case in suite.test_cases for d in case.mocks),
            *suite.before_all_mocks,
        ],
    )
    out.surface = surface
    out.file_status_fields = analyze_file_status_fields(parse_result.ast)
    real_file_problems = expand_real_files(suite, surface, parse_result.ast, out)
    if real_file_problems:
        out.problems.extend(real_file_problems)
        return out
    # Items the between-case reset cannot put back carry one case's value
    # into the next (issue #333): say so rather than skip them silently.
    from mockymock.splicer.reset import unreset_items

    unreset = unreset_items(parse_result.ast)
    if unreset:
        out.notes.append(
            f"{len(unreset)} WORKING-STORAGE/LOCAL-STORAGE item(s) cannot be "
            f"reset between test cases and keep the previous case's value "
            f"({', '.join(unreset)}) -- a case may pass alone (--case) and "
            f"fail in the full suite; set them in the test case if it reads them"
        )
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
        if not model_rebinds:
            # `export` (issue #321): BASED and SET ADDRESS OF a
            # WORKING-STORAGE item are GnuCOBOL / Micro Focus only, so the
            # IBM-legal redirect is kept and the caller says what it costs.
            out.unmodelled_rebinds = sorted(
                {site.item_name.upper() for site in rebindable}
            )
            rebindable = []
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
        for line in split_cut_lines(read_utf8_source(cut_path))
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

    # 7a. USE REAL CALL programs (docs/2026-11-01-real-call-integration-
    # design.md): each is analyzed and gated on its own, and from here on
    # the entry program's checks see only the directives meant for it --
    # a MOCK that answers a site of a real program alone is not an
    # unmatched mock of this one, and its body names that program's data.
    if any(d.is_real for case in all_cases for d in case.mocks):
        suite = _check_real_programs(out, suite, surface, cut_path, copybook_paths)

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

    # 7c. A name the program uses and nothing declares (the program's own
    # bug, not the .cut's): cobc will reject the compile, so lint says so
    # first. A warning, not a refusal -- the xref cannot see every kind of
    # declaration.
    relabel = source_line_relabeler(out.source_location_map)
    for line, kind, word in undeclared_program_names(parse_result.ast, transformed):
        what = "paragraph or section" if kind == "procedure" else "data item"
        out.warnings.append(
            relabel(
                f"warning (UNDECLARED_NAME): line {line}: {word} is used as a "
                f"{what} but the program declares none -- cobc will reject "
                "the compile unless a copybook it could not see declares it"
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
    direct_ids: set[int] = set()
    fallthrough_warnings: list[RefusalReason] = []
    # A multi-call case's own mocks need to be reached by one of its calls,
    # not necessarily the last: its earlier PERFORMs are checked as hook
    # steps below, and its unreached mocks refused after them.
    stepped_ids = {
        id(d)
        for case in suite.test_cases
        if any(step.kind == "PERFORM" for step in case.steps)
        for d in case.mocks
        if id(d) not in shared_ids
    }
    for case_index, case in enumerate(suite.test_cases):
        own_shared = (
            shared_ids | {id(d) for d in case.mocks}
            if any(step.kind == "PERFORM" for step in case.steps)
            else shared_ids
        )
        case_reasons = check_test_case(
            surface,
            parse_result.ast,
            case,
            out.file_status_fields,
            neutralized_goto=neutralized_goto,
            shared=own_shared,
            matched_out=matched_ids,
            warnings_out=fallthrough_warnings,
            traps_out=out.fallthrough_traps,
            direct_matched_out=direct_ids,
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
            warnings_out=fallthrough_warnings,
            traps_out=out.fallthrough_traps,
            direct_matched_out=direct_ids,
        ):
            if check.for_case is None:
                where = check.hook
            elif check.hook == "TESTCASE":
                where = f"TESTCASE {check.for_case.name!r}"
            else:
                where = f"{check.hook} (TESTCASE {check.for_case.name!r})"
            problem = (
                f"refused ({r.code}): {where} PERFORM {check.step.target}: {r.message}"
            )
            key = f"{check.hook}|{check.step.line}|{r.code}|{r.suggested_fix}"
            if key in seen_hook_problems:
                continue
            seen_hook_problems.add(key)
            out.problems.append(problem)
            if r.suggested_fix:
                block = (
                    "BEFORE-ALL"
                    if check.for_case is None
                    else "this TESTCASE"
                    if check.hook == "TESTCASE"
                    else "BEFORE-EACH"
                )
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
                direct_matched_out=direct_ids,
            )
    # One warning per boundary, however many cases fall through to it.
    out.warnings.extend(
        dict.fromkeys(f"warning ({r.code}): {r.message}" for r in fallthrough_warnings)
    )
    for directive in shared_mocks:
        if id(directive) in matched_ids and id(directive) not in direct_ids:
            # Reached, but only by GO TO fall-through: an unmocked boundary
            # there is trapped now (FALLTHROUGH_BOUNDARY), so this default
            # mock no longer has to be declared (issue #351's follow-up).
            block = (
                "BEFORE-EACH"
                if any(directive is d for d in suite.before_each_mocks)
                else "BEFORE-ALL"
            )
            out.warnings.append(
                f"warning (FALLTHROUGH_ONLY_MOCK): {block} MOCK "
                f"{directive.describe()} is reached only by falling through "
                "from a GO TO target -- it can be removed; an unmocked "
                "boundary there is trapped and fails the case only if a test "
                "really reaches it"
            )
    for case in suite.test_cases:
        for directive in case.mocks:
            if directive.real_file is not None:
                continue
            if id(directive) in stepped_ids and id(directive) not in matched_ids:
                out.problems.append(
                    f"refused (UNMATCHED_MOCK): TESTCASE {case.name!r}: MOCK "
                    f"{directive.describe()} is not reached by any of its "
                    "PERFORMs"
                )
                stepped_ids.discard(id(directive))
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
    out.problems.extend(
        f"refused ({r.code}): {r.message}"
        for r in check_clause_bodies(surface, suite, lines)
    )
    out.problems.extend(
        f"refused ({r.code}): {r.message}" for r in check_mock_body_line_length(suite)
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


def _check_real_programs(
    out: StaticCheckResult,
    suite: MockTestSuite,
    surface: MockSurface,
    cut_path: Path,
    copybook_paths: list[str] | None,
) -> MockTestSuite:
    """Step 7a of `_run_static_checks`: prepare and gate every real program
    (problems and warnings go to `out`), and return the suite as the entry
    program's own checks must see it."""
    from mockymock.analysis.cut_names import check_cut_data_names
    from mockymock.analysis.real_programs import (
        check_real_program,
        collect_real_specs,
        entry_program_view,
        matched_directive_ids,
        prepare_real_program,
        program_only_view,
    )
    from mockymock.analysis.refusal import check_clause_bodies
    from mockymock.splicer.sqlca import transform_data_division_exec

    def refuse(reasons) -> None:
        for r in reasons:
            out.problems.append(f"refused ({r.code}): {r.message}")
            if r.suggested_fix:
                out.problems.append("    Add to this TESTCASE (or BEFORE-EACH):")
                out.problems.extend(
                    f"    {line}" for line in r.suggested_fix.splitlines()
                )

    specs, spec_reasons = collect_real_specs(suite, cut_path)
    refuse(spec_reasons)
    elsewhere: set[int] = set()
    for spec in specs:
        prepared, reasons = prepare_real_program(spec, copybook_paths)
        refuse(reasons)
        if prepared is None:
            continue
        out.real_programs.append(prepared)
        out.warnings.extend(prepared.warnings)
        refuse(check_real_program(prepared, suite))
        own = matched_directive_ids(prepared.surface, suite)
        elsewhere |= own
        view = program_only_view(suite, own)
        transformed, _ = transform_data_division_exec(
            prepared.lines, copybook_paths=copybook_paths
        )
        refuse(
            check_cut_data_names(view, transformed, prepared.program_id, prepared.ast)
        )
        refuse(check_clause_bodies(prepared.surface, view, prepared.lines))
    here = matched_directive_ids(surface, suite)
    return entry_program_view(suite, elsewhere - here)


def expand_real_files(
    suite: MockTestSuite, surface: MockSurface, ast: Any, out: StaticCheckResult
) -> list[str]:
    """Answer every file-op site of each case's `USE REAL FILE` files with
    a pass-through directive (`MockDirective.real_file`): the statement runs
    as written. Refuses a file the program does not declare, an indexed or
    relative file, a site a MOCK also answers, and a multi-file OPEN/CLOSE
    mixing a real file with a mocked one (the statement runs once, so it
    cannot be half real)."""
    from cobolparser.generators.data import ProgramLayoutIndex

    from mockymock.analysis.refusal._gates import matching_directives
    from mockymock.dsl.model import FILE_OP_CATEGORIES, MockDirective
    from mockymock.splicer.real_files import (
        REAL_ORGANIZATIONS,
        SELF_BUILT_ORGANIZATIONS,
        FileLayout,
    )

    wanted = {real.file for case in suite.test_cases for real in case.real_files}
    checked = {check.file for case in suite.test_cases for check in case.file_checks}
    problems: list[str] = []
    for case in suite.test_cases:
        real_names = {real.file for real in case.real_files}
        for check in case.file_checks:
            if check.file not in real_names:
                problems.append(
                    f"refused (FILE_CHECK_NOT_REAL): TESTCASE {case.name!r}: "
                    f"{check.kind} FILE {check.file} (.cut line {check.line}) "
                    f"needs USE REAL FILE {check.file} in the case or BEFORE-EACH"
                )
    if not wanted:
        return problems
    index = ProgramLayoutIndex.build(ast)
    selects: dict[str, int] = {}
    environment = getattr(ast, "environment_division", None)
    if environment is not None:
        for select in environment.find_all_by_type("SelectStatement"):
            name = str(getattr(select, "file_name", "") or "").upper()
            location = getattr(select, "location", None)
            if name and location is not None:
                selects.setdefault(name, location.line)
    record_names: dict[str, set[str]] = {}
    for file in sorted(wanted | checked):
        facts = index.file_facts(file)
        if facts is None or file not in selects:
            problems.append(
                f"refused (REAL_FILE_UNKNOWN): USE REAL FILE {file}: the "
                f"program has no SELECT/FD {file}"
            )
            continue
        organization = (facts.organization or "SEQUENTIAL").upper()
        if facts.record_type != "SD" and organization in SELF_BUILT_ORGANIZATIONS:
            staged = sorted(
                {
                    case.name
                    for case in suite.test_cases
                    for real in case.real_files
                    if real.file == file and real.source is not None
                }
            )
            if staged or file in checked:
                what = (
                    f"FROM data (TESTCASE {staged[0]!r})"
                    if staged
                    else "an EXPECT / SAVE FILE"
                )
                problems.append(
                    f"refused (REAL_FILE_ORGANIZATION): USE REAL FILE {file}: "
                    f"an {organization} file can be real only when the program "
                    f"builds it (GnuCOBOL's {organization.lower()} files are "
                    f"not VSAM images), so it takes no {what}; mock it instead"
                )
                continue
        elif facts.record_type == "SD" or organization not in REAL_ORGANIZATIONS:
            problems.append(
                f"refused (REAL_FILE_ORGANIZATION): USE REAL FILE {file}: "
                f"{organization if facts.record_type != 'SD' else 'a SORT work file'}"
                " cannot be real (GnuCOBOL's indexed and relative files are not "
                "VSAM images); mock it instead"
            )
            continue
        record_names[file] = {name.upper() for name in facts.record_names}
        out.real_file_layouts[file] = FileLayout(
            organization, file_record_length(index, file, facts.record_contains)
        )
    if problems:
        return problems
    out.real_file_selects = {file: selects[file] for file in wanted}
    sites = [s for s in surface.boundary_sites if s.category in FILE_OP_CATEGORIES]
    for case in suite.test_cases:
        if not case.real_files:
            continue
        own: list[MockDirective] = []
        for site in sites:
            keys = {key.upper() for key in site.keys}
            for real in case.real_files:
                names = {real.file} | record_names.get(real.file, set())
                hit = sorted(keys & names)
                if not hit:
                    continue
                key = real.file if real.file in keys else hit[0]
                mocked = [
                    d
                    for d in matching_directives(case.mocks, site)
                    if d.file_key.upper() in names
                ]
                if mocked:
                    problems.append(
                        f"refused (REAL_FILE_ALSO_MOCKED): TESTCASE {case.name!r}: "
                        f"{site.label} at line {site.line} is answered by both "
                        f"USE REAL FILE {real.file} and MOCK {mocked[0].describe()}"
                    )
                    continue
                if site.category is None:
                    continue
                if any(d.category is site.category and d.key == key for d in own):
                    continue
                own.append(
                    MockDirective(category=site.category, key=key, real_file=real.file)
                )
        case.mocks = [*case.mocks, *own]
        for site in sites:
            matches = matching_directives(case.mocks, site)
            if matches and len({d.real_file is None for d in matches}) > 1:
                problems.append(
                    f"refused (REAL_FILE_MIXED_STATEMENT): TESTCASE {case.name!r}: "
                    f"{site.label} at line {site.line} names a real file and a "
                    "mocked one; a statement runs once, so make every file it "
                    "names real, or none"
                )
    return problems


def file_record_length(index: Any, file: str, declared: int | None) -> int | None:
    """A fixed-length file's record length: its largest 01 (byte-complete,
    FILLER in), or its RECORD CONTAINS when larger. None when unknown."""
    from cobolparser.generators.data import (
        DataGeneratorOptions,
        flatten_record,
        record_length,
    )

    options = DataGeneratorOptions().for_record_image()
    lengths = [declared or 0]
    for record in index.records_for_file(file):
        try:
            lengths.append(record_length(flatten_record(record, options)))
        except Exception:  # noqa: BLE001 - only used to split records
            continue
    best = max(lengths)
    return best or None
