"""mockymock CLI entry point."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from mockymock import __version__


def _cmd_setup(args: argparse.Namespace) -> int:
    from mockymock.runtime import docker_toolchain

    try:
        docker_toolchain.ensure_toolchain()
        version = docker_toolchain.cobc_version()
    except docker_toolchain.DockerNotAvailableError as exc:
        print(f"mockymock setup: {exc}")
        return 1
    print(
        f"mockymock setup: container {docker_toolchain.CONTAINER} ready " f"({version})"
    )
    return 0


def _cmd_fixtures(args: argparse.Namespace) -> int:
    """Print a cobol-parser FixtureBundle as JSON for editor integrations
    (the VS Code tree view consumes this). Unlike every other subcommand,
    stdout must be EXACTLY the JSON document -- every diagnostic, including
    the plain "no such file" gate, goes to stderr instead of the
    `_check_input_files` convention the rest of this module uses.

    Runs the same three fail-closed static gates as `_cmd_generate` (minus
    the linkage-layout check, which only matters to the splicer that
    `generate`/`run` feed -- `fixtures` never splices): a lossy copybook
    decode (`check_expansion_warnings`), a clean-looking parse that still
    dropped content (`check_whole_program`'s PARSE_WARNING), and any
    unresolved COPY statement (`check_unresolved_copybooks`). Skipping
    these would let e.g. a COPY-bearing program with no --copybook-path
    silently exit 0 with an empty-fixtures bundle and a coverage summary
    claiming everything resolved -- exactly the input `generate` refuses
    with UNRESOLVED_COPYBOOK, so the two commands must agree."""
    from cobolparser import parse_cobol
    from cobolparser.generators import DataGeneratorOptions, ProgramFixtureGenerator
    from cobolparser.preprocess import expand_copybooks

    from mockymock.analysis.refusal import (
        check_expansion_warnings,
        check_unresolved_copybooks,
        check_whole_program,
    )

    source_path = Path(args.program)
    if not source_path.is_file():
        print(f"mockymock fixtures: no such file: {source_path}", file=sys.stderr)
        return 1

    if not _check_rows_non_negative("fixtures", args.rows):
        return 1

    # Mirrors _cmd_generate's order: expand copybooks (if any --copybook-path
    # was given) before the parse gate below, so the gate sees the same
    # source generate_with_scenarios_from_file will eventually parse itself
    # -- gating on the raw, unexpanded source would let an unresolvable COPY
    # slide past as a no-op (cobolparser tolerates unexpanded COPY under
    # FAIL_FAST) instead of being refused here. generate_with_scenarios_from_file
    # still re-expands and re-parses internally; that duplicate work is the
    # price of a correctness gate rather than one that just happens to work.
    raw_source = source_path.read_text(encoding="utf-8")
    if args.copybook_path:
        try:
            expansion = expand_copybooks(raw_source, copybook_paths=args.copybook_path)
        except Exception as exc:  # noqa: BLE001 -- surfaced verbatim to the caller
            print(f"mockymock fixtures: {exc}", file=sys.stderr)
            return 1
        expansion_reasons = check_expansion_warnings(expansion)
        for reason in expansion_reasons:
            print(
                f"mockymock fixtures: refused ({reason.code}): {reason.message}",
                file=sys.stderr,
            )
        if expansion_reasons:
            return 1
        raw_source = expansion.expanded_source

    # ProgramFixtureGenerator only raises when the AST comes back None
    # (missing file, unresolved copybook under strict_copybooks). A source
    # file that merely fails to parse (no recognizable COBOL division, bad
    # syntax) still yields a placeholder AST -- generate_with_scenarios_from_file
    # would happily return an empty bundle for it instead of failing, which
    # would look like a real (if boring) program to the VS Code tree view.
    # Parse the (possibly copybook-expanded) source once up front so that
    # case is refused like every other command.
    result = parse_cobol(raw_source, filename=source_path.name)
    if not result.success:
        print(
            f"mockymock fixtures: {len(result.errors)} parse error(s):", file=sys.stderr
        )
        for error in result.errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    # success=True is not enough: cobolparser reports dropped statements
    # (unsupported verbs, multi-program units, unparsed clause leftovers)
    # as warnings on an otherwise clean parse. A bundle built from an
    # incomplete AST would silently miss boundaries, so refuse -- same
    # check _cmd_generate runs on the same signal.
    warning_reasons = check_whole_program(result)
    for reason in warning_reasons:
        print(
            f"mockymock fixtures: refused ({reason.code}): {reason.message}",
            file=sys.stderr,
        )
    if warning_reasons:
        return 1

    copybook_reasons = check_unresolved_copybooks(raw_source)
    for reason in copybook_reasons:
        print(
            f"mockymock fixtures: refused ({reason.code}): {reason.message}",
            file=sys.stderr,
        )
    if copybook_reasons:
        return 1

    generator = (
        ProgramFixtureGenerator(DataGeneratorOptions(rows=args.rows))
        if args.rows is not None
        else ProgramFixtureGenerator()
    )
    try:
        bundle = generator.generate_with_scenarios_from_file(
            str(source_path),
            copybook_paths=args.copybook_path,
            mode=args.scenarios,
            seed=args.seed,
        )
    except Exception as exc:  # noqa: BLE001 -- surfaced verbatim to the caller
        print(f"mockymock fixtures: {exc}", file=sys.stderr)
        return 1
    print(bundle.to_json())
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    from mockymock.web import server

    port = server.DEFAULT_PORT if args.port is None else args.port
    try:
        server.serve(port=port, open_browser=not args.no_browser)
    except OSError as exc:
        # Almost always "address already in use" -- a second dashboard, or
        # something else on the port. Actionable message, not a traceback.
        print(f"mockymock dashboard: could not serve on {server.HOST}:{port}: {exc}")
        return 1
    return 0


def _check_input_files(command: str, *paths: Path) -> bool:
    """Print a clean error for every input path that doesn't exist. Runs
    before any toolchain/parse work so a typo'd path fails in milliseconds
    with no traceback -- never after a multi-minute image build."""
    ok = True
    for path in paths:
        if not path.is_file():
            print(f"{command}: no such file: {path}")
            ok = False
    return ok


def _check_rows_non_negative(command: str, rows: int | None) -> bool:
    """Flag-only validation for `--rows N`, shared by `fixtures` and
    `generate` (built together in this PR). `DataGeneratorOptions.
    __post_init__` (cobol-parser) already rejects a negative `rows` with
    `ValueError("rows must be non-negative")`, but that isn't good enough
    here on its own: `_cmd_fixtures` constructs `DataGeneratorOptions`
    outside any try/except (a negative value would crash with a raw
    traceback), and both commands would otherwise only discover the
    problem after every other flag-only check plus a full copybook
    expansion and parse of the source file. Checking here instead fails
    fast on a bad invocation -- same philosophy as `_check_input_files`,
    called at the same point (right after the input-file check, before
    any file parsing or generator construction)."""
    if rows is not None and rows < 0:
        print(f"mockymock {command}: --rows must be >= 0, got {rows}", file=sys.stderr)
        return False
    return True


def _write_report_file(command: str, flag: str, target: str, content: str) -> bool:
    """Write one of `run`'s optional --*-xml/--*-json/--*-out report files
    (or `export`'s --output). A bad parent directory (or any other
    OS-level write failure) used to escape as a raw traceback after an
    otherwise-successful run -- report it the same way
    `_check_input_files` reports a bad input path instead, and let the
    caller's own exit code stand on the actual outcome rather than on
    whether a report file happened to be writable."""
    try:
        Path(target).write_text(content, encoding="utf-8")
    except OSError as exc:
        print(f"mockymock {command}: could not write {flag} to {target}: {exc}")
        return False
    return True


def _write_failure_reports(
    args: argparse.Namespace, command: str, suite_name: str, reason: str
) -> None:
    """Write `run`'s --junit-xml/--json-report for an exit that never
    produced a TestSuiteResult at all -- a static refusal or a compile
    failure. Without this, those two exit paths returned 1 with nothing
    written, so a CI pipeline that always publishes whatever the configured
    report path holds (the common pattern) saw "no test results found"
    instead of a visible failure -- worse than a failing test, since it can
    read as "nothing ran" rather than "something failed" (carried-over open
    item from the 2026-08-10 framework audit). Reuses the ordinary
    formatters via one synthetic TestResult standing in for the whole run,
    rather than a bespoke report shape only this path would exercise."""
    if not args.junit_xml and not args.json_report:
        return

    from mockymock.report.formatters import format_junit_xml
    from mockymock.report.json_report import build_json_report, format_json_report
    from mockymock.report.results import TestResult, TestSuiteResult

    suite_result = TestSuiteResult(
        suite_name=suite_name,
        results=[
            TestResult(
                case_id="0",
                case_name=f"mockymock {command}",
                failure_reasons=[reason],
                ended=True,
            )
        ],
        tests_run=1,
        failures=1,
    )
    if args.junit_xml:
        _write_report_file(
            command, "--junit-xml", args.junit_xml, format_junit_xml(suite_result)
        )
    if args.json_report:
        _write_report_file(
            command,
            "--json-report",
            args.json_report,
            format_json_report(build_json_report(suite_result)),
        )


def _cmd_generate(args: argparse.Namespace) -> int:
    from cobolparser import parse_cobol
    from cobolparser.preprocess import (
        expand_copybooks,
        normalize_fixed_format,
        strip_compiler_directives,
    )

    from mockymock.analysis.cics_eib import cics_eib_plan
    from mockymock.analysis.linkage import address_of_sites, linkage_plan
    from mockymock.analysis.mock_surface import analyze
    from mockymock.analysis.refusal import (
        check_cics_eib_layout,
        check_expansion_warnings,
        check_linkage_layout,
        check_unresolved_copybooks,
        check_whole_program,
    )
    from mockymock.dsl.fixture_bundle import (
        FixtureBundle,
        UnsupportedBundleVersionError,
        load_fixture_bundle,
        load_fixture_bundle_file,
    )
    from mockymock.dsl.generator import scaffold_cut
    from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

    source_path = Path(args.program)
    if not _check_input_files("mockymock generate", source_path):
        return 1

    if not _check_rows_non_negative("generate", args.rows):
        return 1

    # Flag-only validation -- neither check needs the source file, so both
    # run before any parse/bundle work, same "fail fast on a bad
    # invocation" philosophy as _check_input_files above. Category is
    # uppercased for comparison (a bundle fixture's own `category` string
    # is always uppercase, e.g. "READ"/"SQL"); the key is left exactly as
    # given -- the bundle carries it case-sensitively.
    placeholder_pairs: list[tuple[str, str]] = []
    for value in args.placeholder:
        if ":" not in value:
            print(
                f"mockymock generate: --placeholder must be CATEGORY:KEY, "
                f"got {value!r}",
                file=sys.stderr,
            )
            return 1
        category, _, key = value.partition(":")
        placeholder_pairs.append((category.upper(), key))

    if args.rows is not None and args.fixtures:
        print(
            "mockymock generate: --rows is not valid together with "
            "--fixtures -- that bundle's row count is already baked in; "
            "use --rows with --with-data's self-generating path instead",
            file=sys.stderr,
        )
        return 1

    bundle: FixtureBundle | None = None
    if args.fixtures:
        fixtures_path = Path(args.fixtures)
        if not fixtures_path.is_file():
            print(f"mockymock generate: no such file: {fixtures_path}")
            return 1
        try:
            bundle = load_fixture_bundle_file(fixtures_path)
        except UnsupportedBundleVersionError as exc:
            print(f"mockymock generate: {exc}")
            return 1
        except Exception as exc:  # malformed JSON, missing required keys, ...
            print(f"mockymock generate: invalid fixture bundle {fixtures_path}: {exc}")
            return 1
    elif args.with_data:
        from cobolparser.generators import DataGeneratorOptions, ProgramFixtureGenerator

        try:
            generator = (
                ProgramFixtureGenerator(DataGeneratorOptions(rows=args.rows))
                if args.rows is not None
                else ProgramFixtureGenerator()
            )
            cp_bundle = generator.generate_with_scenarios_from_file(
                str(source_path),
                mode=args.scenarios,
                seed=args.seed,
                copybook_paths=args.copybook_path,
            )
            bundle = load_fixture_bundle(cp_bundle.to_dict())
        except Exception as exc:
            print(f"mockymock generate: fixture bundle generation failed: {exc}")
            return 1

    if placeholder_pairs:
        # Fail-loud: a --placeholder pair that never matches a bundle
        # fixture is reported rather than a silent no-op (deliberately
        # improves on the parked feature/generate-with-data branch's own
        # behavior -- see this repo's own unify-with-data plan, Task 4).
        bundle_fixture_keys = {
            (fixture.category, fixture.key)
            for scenario in (bundle.scenarios if bundle is not None else [])
            for fixture in scenario.fixtures
        }
        for category, key in placeholder_pairs:
            if (category, key) not in bundle_fixture_keys:
                print(
                    f"mockymock generate: warning: --placeholder "
                    f"{category}:{key} matched no fixture",
                    file=sys.stderr,
                )

    raw_source = source_path.read_text(encoding="utf-8")
    if args.copybook_path:
        # See _cmd_fixtures's identical guard on the same call for why
        # this can raise on realistic inputs (audit finding F6).
        try:
            expansion = expand_copybooks(raw_source, copybook_paths=args.copybook_path)
        except Exception as exc:  # noqa: BLE001 -- surfaced verbatim to the caller
            print(f"mockymock generate: {exc}")
            return 1
        expansion_reasons = check_expansion_warnings(expansion)
        for reason in expansion_reasons:
            print(f"mockymock generate: refused ({reason.code}): {reason.message}")
        if expansion_reasons:
            return 1
        raw_source = expansion.expanded_source
    result = parse_cobol(raw_source, filename=source_path.name)
    if not result.success:
        print(f"mockymock generate: {len(result.errors)} parse error(s):")
        for error in result.errors:
            print(f"  {error}")
        return 1

    # success=True is not enough: cobolparser reports dropped statements
    # (unsupported verbs, multi-program units, unparsed clause leftovers)
    # as warnings on an otherwise clean parse. A scaffold built from an
    # incomplete AST would silently miss boundaries, so refuse.
    warning_reasons = check_whole_program(result)
    for reason in warning_reasons:
        print(f"mockymock generate: refused ({reason.code}): {reason.message}")
    if warning_reasons:
        return 1

    copybook_reasons = check_unresolved_copybooks(raw_source)
    for reason in copybook_reasons:
        print(f"mockymock generate: refused ({reason.code}): {reason.message}")
    if copybook_reasons:
        return 1

    # See mockymock/cli/checks.py::run_static_checks for why PROCESS/CBL
    # precompiler directives must be stripped before normalizing here too.
    lines = normalize_fixed_format(
        strip_compiler_directives(raw_source).splitlines()
    ).splitlines()

    linkage_reasons = check_linkage_layout(result.ast, lines)
    for reason in linkage_reasons:
        print(f"mockymock generate: refused ({reason.code}): {reason.message}")
    if linkage_reasons:
        return 1
    linkage = linkage_plan(result.ast)
    if linkage is not None:
        preview_address_of, _ = address_of_sites(lines, linkage)
        _print_linkage_neutralization(
            "generate", linkage, applied=False, address_of=preview_address_of
        )

    cics_eib_reasons = check_cics_eib_layout(result.ast, lines)
    for reason in cics_eib_reasons:
        print(f"mockymock generate: refused ({reason.code}): {reason.message}")
    if cics_eib_reasons:
        return 1
    cics_eib = cics_eib_plan(result.ast, lines)
    if cics_eib is not None:
        _print_cics_eib_synthesis("generate", cics_eib, applied=False)

    if bundle is not None and not bundle.scenarios:
        # Possible with --scenarios branches|all on a program with no
        # branch arms and no fixed-family (empty-input/error-status/
        # boundary-values) matches -- there is genuinely nothing to
        # scaffold a TESTCASE from. --scenarios happy (the default)
        # always produces exactly one scenario, so this cannot happen
        # there.
        print(
            "mockymock generate: the fixture bundle has zero scenarios -- "
            "nothing to scaffold. Try --scenarios happy (the default), or "
            "check the program has any branch arms/fixed-family matches at "
            "all for --scenarios branches|all to target"
        )
        return 1

    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    cut_text = scaffold_cut(
        result.ast.program_name, surface, bundle, frozenset(placeholder_pairs)
    )

    output_path = Path(args.output) if args.output else source_path.with_suffix(".cut")
    # Unlike run's auxiliary report flags, this file IS the deliverable:
    # a failed write is a failed command (same convention as export).
    if not _write_report_file("generate", "-o/--output", str(output_path), cut_text):
        return 1
    case_count = cut_text.count("TESTCASE ")
    print(f"mockymock generate: wrote {case_count} test case(s) -> {output_path}")
    if bundle is not None:
        print(
            f"mockymock generate: data-driven from a fixture bundle "
            f"(seed={bundle.seed})"
        )
    _report_unsupported_boundaries(surface, "generate")
    return 0


def _print_linkage_neutralization(
    command: str, plan, applied: bool, address_of=()
) -> None:
    """Transparency for the LINKAGE neutralization transform: it never
    refuses (that's `check_linkage_layout`'s job) and edits source a `.cut`
    author didn't write, so say so rather than silently changing behavior.
    `applied` distinguishes `run` (the transform actually ran on this
    invocation) from `generate` (which never touches instrumented source --
    it only scaffolds a `.cut` from the AST -- so this only describes what
    a later `run` against this program will do). `plan.entry_statements` may
    be empty (2026-08-27 generalization, see
    docs/2026-08-27-cics-eib-linkage-support-design.md) -- e.g. a CICS
    program with its own `LINKAGE SECTION. 01 DFHCOMMAREA.` and no ENTRY at
    all -- in which case only the LINKAGE-folding half of the message
    applies. `address_of` carries the `SET ADDRESS OF <folded item>`
    occurrences redirected into a scratch pointer, which is a second,
    separately surprising edit and so gets its own sentence rather than
    being folded silently into the message above.
    See docs/2026-07-08-ims-linkage-support-design.md."""
    entry_names = ", ".join(
        repr(e.entry_name) for e in plan.entry_statements if e.entry_name
    )
    item_names = ", ".join(item.name for item in plan.linkage_items)
    if applied:
        entry_clause = (
            f"neutralized ENTRY statement(s) ({entry_names}) and "
            if entry_names
            else ""
        )
        action = (
            f"{entry_clause}folded LINKAGE SECTION into WORKING-STORAGE ({item_names})"
        )
    else:
        entry_clause = (
            f"neutralize ENTRY statement(s) ({entry_names}) and " if entry_names else ""
        )
        action = (
            f"a later `run` will {entry_clause}fold LINKAGE SECTION into "
            f"WORKING-STORAGE ({item_names})"
        )
    print(
        f"mockymock {command}: {action} -- the driver never binds LINKAGE "
        f"SECTION storage, so this program's default entry gets real, "
        f"addressable storage instead"
    )
    if address_of:
        targets = ", ".join(sorted({site.item_name for site in address_of}))
        verb = "redirected" if applied else "will redirect"
        print(
            f"mockymock {command}: {verb} {len(address_of)} "
            f"`SET ADDRESS OF` target(s) ({targets}) to a discarded scratch "
            f"pointer -- once folded into WORKING-STORAGE those items own "
            f"real storage, which GnuCOBOL will not let a program rebind"
        )


def _print_cics_eib_synthesis(command: str, plan, applied: bool) -> None:
    """Transparency for CICS EIB field synthesis: like linkage
    neutralization above, it never refuses (that's
    `check_cics_eib_layout`'s job) and adds WORKING-STORAGE a `.cut` author
    didn't write, so say so rather than silently changing behavior. See
    docs/2026-08-27-cics-eib-linkage-support-design.md."""
    names = ", ".join(plan.referenced_names)
    if applied:
        action = (
            f"synthesized a 01 DFHEIBLK WORKING-STORAGE group (referenced: {names})"
        )
    else:
        action = (
            f"a later `run` will synthesize a 01 DFHEIBLK WORKING-STORAGE "
            f"group (referenced: {names})"
        )
    print(
        f"mockymock {command}: {action} -- no CICS translator runs in this "
        f"pipeline, so this program's undeclared EIB field references get "
        f"real, addressable storage instead"
    )


def _report_unsupported_boundaries(surface, command: str = "generate") -> None:
    """Name every detected boundary point that stays unmockable (a SORT/
    MERGE mixing a USING/GIVING file with an INPUT/OUTPUT PROCEDURE on the
    other side -- a plain-file-form SORT/MERGE and a pure-procedure-form
    SORT are both mockable [the latter via its own RELEASE/RETURN] and
    never appear here, see mock_surface.py's `_is_plain_sort_merge`/
    `_is_pure_procedure_sort` -- identifier-less dynamic CALLs,
    unspliceable nested sites), so the scaffold is never mistaken for
    complete coverage of the program's outputs. Test cases whose PERFORM
    target reaches one of these are refused by `run`.

    STOP RUN/GOBACK sites are reported separately and more cautiously:
    unlike the other category=None labels, `run` does not always refuse a
    test case reaching one -- check_terminator_layout (see
    docs/2026-07-08-goback-stop-run-support-design.md) may find it safe.
    `generate` has no specific test case's PERFORM target to evaluate
    reachability against, so it cannot know which outcome a future `.cut`
    will get -- claiming "will be refused" here would be wrong as often as
    it's right.

    `command` names the caller in the printed output -- `generate` (the
    default, and this function's original and still most common caller)
    or `export`, which shares the same `surface` inspection but must not
    print a `generate` prefix in its own console output.
    """
    from mockymock.analysis.mock_surface import _TERMINATOR_LABELS

    findings: list[str] = []
    terminator_findings: list[str] = []
    for site in surface.boundary_sites:
        if site.category is None:
            if site.label in _TERMINATOR_LABELS:
                terminator_findings.append(
                    f"{site.label} in paragraph '{site.paragraph_name}' "
                    f"(line {site.line})"
                )
            else:
                findings.append(
                    f"{site.label} in paragraph '{site.paragraph_name}' "
                    f"(line {site.line})"
                )
        elif site.nested and site.span is None:
            findings.append(
                f"nested {site.label} in paragraph '{site.paragraph_name}' "
                f"(line {site.line}) -- {site.unspliceable_reason}"
            )
    if findings:
        print(
            f"mockymock {command}: {len(findings)} boundary point(s) detected "
            f"that are not mockable (test cases reaching them will be "
            f"refused):"
        )
        for finding in findings:
            print(f"  - {finding}")
    if terminator_findings:
        print(
            f"mockymock {command}: {len(terminator_findings)} STOP RUN/GOBACK "
            f"site(s) detected -- whether a test case reaching one is "
            f"refused depends on how it's reached; see "
            f"docs/2026-07-08-goback-stop-run-support-design.md:"
        )
        for finding in terminator_findings:
            print(f"  - {finding}")


def _cmd_run(args: argparse.Namespace) -> int:
    import json

    from mockymock.analysis.flow_mocks import find_flow_mock_plans
    from mockymock.analysis.refusal import find_goto_exit_plans, find_terminator_plans
    from mockymock.analysis.stub_expectations import scan_stub_expectations
    from mockymock.cli.checks import extra_working_storage, run_static_checks
    from mockymock.report.coverage import (
        build_original_line_map,
        format_coverage_console,
        format_coverage_json,
        map_coverage_to_original,
        parse_gcov,
    )
    from mockymock.report.formatters import format_console, format_junit_xml
    from mockymock.report.json_report import build_json_report, format_json_report
    from mockymock.report.record_rewrite import (
        build_recording_report,
        rewrite_cut_text,
    )
    from mockymock.report.results import parse_stdout
    from mockymock.report.trace import (
        format_trace_console,
        format_trace_json,
        parse_trace,
    )
    from mockymock.runtime import docker_toolchain
    from mockymock.runtime.executor import TIMEOUT_EXIT_CODE
    from mockymock.runtime.sandbox import sandbox_dir_maybe_kept
    from mockymock.splicer import cics_eib
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.linkage import extra_reset_lines
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.reset import reset_move_lines
    from mockymock.splicer.source_map import collect_boundaries
    from mockymock.splicer.sqlca import transform_data_division_exec

    # Input existence is the one check that runs even before anything else:
    # a typo'd path must fail in milliseconds with no traceback.
    source_path = Path(args.program)
    cut_path = Path(args.cut)
    if not _check_input_files("mockymock run", source_path, cut_path):
        return 1

    # Asking for the coverage JSON, or a coverage report file, is asking
    # for coverage.
    if args.coverage_json:
        args.coverage = True
    if args.coverage_out:
        args.coverage = True

    # Asking for the trace JSON is asking for the trace.
    if args.trace_json:
        args.trace = True
    if args.trace and (len(args.case or []) != 1 or args.tag):
        # The suite compiles and runs as ONE binary, and the trace file is a
        # separate stream from stdout with no shared timestamps -- so an
        # unscoped trace interleaves every case with nothing to segment it
        # by. Requiring a single case makes attribution true by
        # construction. See docs/2026-07-21-debug-trace-design.md.
        print(
            "mockymock run: --trace requires exactly one --case (and no "
            "--tag): the suite runs as a single binary, so an unscoped "
            "trace cannot be attributed to one case"
        )
        return 1

    # Static checks run BEFORE the toolchain comes up (see the lint design
    # doc): a bad .cut/.cbl fails fast with the real problem regardless of
    # Docker state, instead of paying a multi-minute image build (or a
    # misleading "Docker not available" error) first.
    checked = run_static_checks(
        source_path,
        cut_path,
        args.copybook_path,
        case_names=args.case,
        tag_names=args.tag,
    )
    for note in checked.notes:
        print(f"mockymock run: {note}")
    if checked.linkage is not None:
        _print_linkage_neutralization(
            "run",
            checked.linkage,
            applied=True,
            address_of=checked.linkage_address_of,
        )
    if checked.cics_eib is not None:
        _print_cics_eib_synthesis("run", checked.cics_eib, applied=True)
    if checked.problems:
        for problem in checked.problems:
            if problem.startswith("  "):
                print(problem)  # indented parse-error detail lines
            else:
                print(f"mockymock run: {problem}")
        _write_failure_reports(
            args,
            "run",
            checked.suite.name if checked.suite is not None else "",
            "\n".join(checked.problems),
        )
        return 1

    try:
        docker_toolchain.ensure_toolchain()
    except docker_toolchain.DockerNotAvailableError as exc:
        print(f"mockymock run: {exc}")
        return 1

    result = checked.parse_result
    suite = checked.suite
    surface = checked.surface
    lines = checked.lines
    scope_map = checked.scope_map
    linkage = checked.linkage
    cics_eib_plan_ = checked.cics_eib
    assert (
        result is not None
        and suite is not None
        and surface is not None
        and lines is not None
        and scope_map is not None
    )  # implied by checked.problems being empty
    # The original-coverage remap needs the pre-splice normalized lines;
    # splice_program mutates nothing, but keep our own copy to be explicit.
    normalized_lines = list(lines)

    boundaries = collect_boundaries(result.ast)
    registry = TallyRegistry(suite)
    terminator_plans, _ = find_terminator_plans(
        surface, result.ast, suite, scope_map, lines
    )
    goto_exit_plans, _ = find_goto_exit_plans(result.ast, scope_map, lines)
    flow_plans, _ = find_flow_mock_plans(result.ast, suite, lines)
    lines = splice_program(
        lines,
        boundaries,
        surface,
        suite,
        registry,
        terminator_plans,
        flow_plans,
        checked.file_status_fields,
        goto_exit_plans=goto_exit_plans,
        trace=args.trace,
    )
    lines, _ = transform_data_division_exec(lines, copybook_paths=args.copybook_path)

    reset_lines = reset_move_lines(result.ast)
    if linkage is not None:
        # LINKAGE items `neutralize` folded into WORKING-STORAGE live under
        # the LINKAGE section in `result.ast` still (the transform edited
        # text, not the AST), so `reset_move_lines`'s WORKING-STORAGE walk
        # never sees them -- add their reset lines explicitly.
        reset_lines = reset_lines + extra_reset_lines(linkage)
    if cics_eib_plan_ is not None:
        reset_lines = reset_lines + cics_eib.reset_lines(cics_eib_plan_)

    # --record-expectations: scan the raw .cut text (not the parsed suite --
    # a "*> STUB EXPECT" line is an ordinary comment to parse_cut) against
    # the POST-filter `suite` (--case/--tag already applied by
    # run_static_checks) so a stub's case_index always means what
    # build_driver means by it. See
    # docs/2026-08-04-record-expectations-design.md.
    cut_text = cut_path.read_text(encoding="utf-8")
    stub_scan = (
        scan_stub_expectations(cut_text, suite) if args.record_expectations else None
    )
    record_targets: dict[int, list[str]] = {}
    if stub_scan is not None:
        for stub in stub_scan.stubs:
            record_targets.setdefault(stub.case_index, []).append(stub.data_name)

    artifact = build_driver(
        suite,
        reset_lines,
        registry,
        record_targets=record_targets,
        extra_working_storage_lines=extra_working_storage(checked),
    )

    instrumented = _insert_driver(lines, artifact)

    # --verbose needs the sandbox retained too: the instrumented-source path
    # it prints on compile failure must still exist by the time the user
    # reads it, but plain --verbose (no --keep-sandbox) shouldn't leave
    # cruft behind after a run that actually succeeds -- see the explicit
    # cleanup below.
    with sandbox_dir_maybe_kept(
        root=docker_toolchain.WORK_ROOT, keep=args.keep_sandbox or args.verbose
    ) as tmp:
        if args.keep_sandbox:
            print(f"mockymock run: keeping sandbox {tmp}")

        instrumented_path = tmp / source_path.with_suffix(".cbl").name
        instrumented_path.write_text(
            "\n".join(instrumented) + "\n", encoding="utf-8", newline="\n"
        )

        compiled = docker_toolchain.compile_source(
            instrumented_path, coverage=args.coverage, trace=args.trace
        )
        if not compiled.success:
            print("mockymock run: compile failed:")
            print(compiled.stderr)
            if args.verbose or args.keep_sandbox:
                print(f"mockymock run: instrumented source at {instrumented_path}")
            # Deliberately no cleanup here even under plain --verbose: the
            # path just printed must still resolve after this function
            # returns, which is the whole point of printing it. Contrast
            # the try/finally below, guarding the run_binary/run_gcov
            # phase -- unlike a compile failure, an exception there prints
            # no path pointing at the sandbox, so leaving it behind would
            # just leak silently instead of helping anyone (audit finding
            # F10; a `return 1` from *this* branch used to be lumped in
            # with that same fix, which broke the documented, tested
            # --verbose-survives-a-compile-failure contract below).
            _write_failure_reports(args, "run", suite.name, compiled.stderr)
            return 1

        # try/finally, not just a statement after the `with`: plain --verbose
        # (no --keep-sandbox) asks sandbox_dir_maybe_kept to retain `tmp` for
        # this phase and relies on this cleanup running afterward. A bare
        # statement placed after the `with` block used to rely on this
        # phase never raising -- an exception from run_binary/run_gcov
        # skipped it and leaked the directory permanently, with no printed
        # path (unlike the compile-failure branch above) to tell anyone it
        # was there (audit finding F10).
        try:
            assert compiled.binary_path is not None  # implied by compiled.success
            trace_path = tmp / f"{instrumented_path.stem}.trace" if args.trace else None
            executed = docker_toolchain.run_binary(
                compiled.binary_path,
                timeout_seconds=args.timeout,
                trace_path=trace_path,
            )

            # Must be read while the sandbox still exists -- the context
            # manager removes it on exit unless --keep-sandbox was given.
            trace_text = ""
            if trace_path is not None and trace_path.exists():
                trace_text = trace_path.read_text(encoding="utf-8", errors="replace")

            coverage_text = None
            coverage_report = None
            if args.coverage:
                gcov_result = docker_toolchain.run_gcov(instrumented_path)
                if gcov_result.success:
                    coverage_report = parse_gcov(gcov_result.gcov_text)
                    coverage_text = format_coverage_console(
                        coverage_report, instrumented_path.name
                    )
                else:
                    coverage_text = (
                        f"mockymock run: coverage: {gcov_result.stderr.rstrip()}"
                    )
        finally:
            if args.verbose and not args.keep_sandbox:
                shutil.rmtree(tmp, ignore_errors=True)

    suite_result = parse_stdout(executed.stdout)

    # Real evidence about why the binary died beats the formatters'
    # default STOP-RUN hypothesis: a timeout (exit 124, with run_binary's
    # infinite-loop hint on stderr) and a runtime abort (nonzero exit,
    # libcob's message on stderr) are distinct failure modes and must not
    # both render as a generic crash.
    if executed.exit_code == TIMEOUT_EXIT_CODE:
        crash_detail = "binary timed out (exit 124); see stderr below"
    elif executed.exit_code != 0:
        crash_detail = f"binary exited with code {executed.exit_code}"
    else:
        crash_detail = None
    print(format_console(suite_result, crash_detail=crash_detail))
    if executed.stderr:
        print("mockymock run: binary stderr:")
        print(executed.stderr.rstrip("\n"))

    if stub_scan is not None:
        # Best-effort and cumulative, never gating the run's own exit code
        # (see the design doc's "Best-effort, cumulative reporting" and
        # "Never overwrite a hand-edited EXPECT" sections): every stub the
        # scanner found ends up in exactly one of recorded/skipped, and the
        # file is only ever touched when at least one stub was recorded.
        recording = build_recording_report(stub_scan, suite_result)
        rewritten = rewrite_cut_text(cut_text, recording)
        if rewritten is not None:
            cut_path.write_text(rewritten, encoding="utf-8", newline="\n")
        print(
            f"mockymock run: --record-expectations: recorded "
            f"{len(recording.recorded)}, skipped {len(recording.skipped)}"
        )
        for item in recording.recorded:
            print(
                f"  recorded {item.stub.data_name} (line {item.stub.line}) "
                f"= {item.value}"
            )
        for skip in recording.skipped:
            print(f"  skipped {skip.data_name} (line {skip.line}): {skip.reason}")
        if rewritten is not None:
            print(f"mockymock run: rewrote {cut_path}")

    if args.junit_xml:
        _write_report_file(
            "run",
            "--junit-xml",
            args.junit_xml,
            format_junit_xml(suite_result, crash_detail=crash_detail),
        )

    if args.json_report:
        _write_report_file(
            "run",
            "--json-report",
            args.json_report,
            format_json_report(
                build_json_report(
                    suite_result,
                    cut_suite=suite,
                    crash_detail=crash_detail,
                    cut_file=str(cut_path),
                    program_file=str(source_path),
                )
            ),
        )

    if args.coverage_json:
        if coverage_report is None:
            print(
                "mockymock run: coverage JSON not written -- the gcov pass "
                "failed (see the coverage error above)"
            )
        else:
            mapped = map_coverage_to_original(
                coverage_report,
                instrumented,
                normalized_lines,
                source_path.read_text(encoding="utf-8").splitlines(),
            )
            _write_report_file(
                "run",
                "--coverage-json",
                args.coverage_json,
                format_coverage_json(
                    coverage_report,
                    mapped,
                    program_file=str(source_path),
                    instrumented_name=instrumented_path.name,
                ),
            )

    if coverage_text is not None:
        print(coverage_text)
        if args.coverage_out:
            _write_report_file(
                "run", "--coverage-out", args.coverage_out, coverage_text + "\n"
            )

    if args.trace:
        if not trace_text:
            print(
                "mockymock run: no execution trace produced -- the binary "
                "wrote no trace file (it may have died before executing a "
                "single statement)"
            )
        else:
            # Exactly one case is selected (enforced above), so the whole
            # trace belongs to it -- no segmentation needed.
            selected = args.case[0]
            case_result = next(
                (r for r in suite_result.results if r.case_name == selected), None
            )
            model_case = next((c for c in suite.test_cases if c.name == selected), None)
            trace_json = format_trace_json(
                parse_trace(trace_text),
                build_original_line_map(
                    instrumented,
                    normalized_lines,
                    source_path.read_text(encoding="utf-8").splitlines(),
                ),
                case_result.mock_hits if case_result is not None else [],
                selected,
                model_case.line if model_case is not None else None,
                str(cut_path),
                str(source_path),
            )
            if args.trace_json:
                _write_report_file("run", "--trace-json", args.trace_json, trace_json)
            print(format_trace_console(json.loads(trace_json)))

    # A nonzero binary exit is a failed run even when every case that got
    # to print its markers passed (e.g. libcob aborted after the SUMMARY
    # line, or the timeout killed a straggler).
    return 0 if suite_result.all_passed and executed.exit_code == 0 else 1


def _cmd_debug(args: argparse.Namespace) -> int:
    """Splices and compiles exactly like `_cmd_run` (with `-g` instead of
    `--coverage`/`-ftraceall`), then instead of calling `run_binary` hands
    a `launch_session` closure to a `DapAdapter` and blocks driving the DAP
    protocol on stdio until the client disconnects. See
    docs/2026-07-22-dap-debugger-design.md and
    docs/superpowers/plans/2026-07-22-dap-debugger-cli.md."""
    import sys

    from mockymock.analysis.flow_mocks import find_flow_mock_plans
    from mockymock.analysis.refusal import find_goto_exit_plans, find_terminator_plans
    from mockymock.cli.checks import extra_working_storage, run_static_checks
    from mockymock.debug.adapter import DapAdapter, DebugSession
    from mockymock.debug.call_stack import ParagraphIndex, build_generated_c_line_map
    from mockymock.debug.gdb_session import GdbSession
    from mockymock.debug.line_map import LineMap
    from mockymock.debug.variable_map import parse_local_header
    from mockymock.runtime import docker_toolchain
    from mockymock.runtime.sandbox import sandbox_dir_maybe_kept
    from mockymock.splicer import cics_eib
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.linkage import extra_reset_lines
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.reset import reset_move_lines
    from mockymock.splicer.source_map import collect_boundaries
    from mockymock.splicer.sqlca import transform_data_division_exec

    # Unlike --trace's plain-text mode, there is no useful human-facing
    # equivalent of a DAP session at a terminal -- refuse rather than
    # half-start a session a human cannot drive (see design doc's CLI
    # surface section).
    if not args.dap_stdio:
        print(
            "mockymock debug: a DAP session has no useful terminal-attached "
            "mode; drive it from the mocky-mock VS Code extension, or pass "
            "--dap-stdio to speak the protocol directly"
        )
        return 1

    source_path = Path(args.program)
    cut_path = Path(args.cut)
    if not _check_input_files("mockymock debug", source_path, cut_path):
        return 1

    if len(args.case or []) != 1:
        print(
            "mockymock debug: requires exactly one --case: the suite runs "
            "as a single binary and one execution stream, so a debug "
            "session cannot be attributed to more than one case"
        )
        return 1

    checked = run_static_checks(
        source_path, cut_path, args.copybook_path, case_names=args.case
    )
    for note in checked.notes:
        print(f"mockymock debug: {note}")
    if checked.linkage is not None:
        _print_linkage_neutralization(
            "debug",
            checked.linkage,
            applied=True,
            address_of=checked.linkage_address_of,
        )
    if checked.cics_eib is not None:
        _print_cics_eib_synthesis("debug", checked.cics_eib, applied=True)
    if checked.problems:
        for problem in checked.problems:
            if problem.startswith("  "):
                print(problem)
            else:
                print(f"mockymock debug: {problem}")
        return 1

    try:
        docker_toolchain.ensure_toolchain()
    except docker_toolchain.DockerNotAvailableError as exc:
        print(f"mockymock debug: {exc}")
        return 1

    result = checked.parse_result
    suite = checked.suite
    surface = checked.surface
    lines = checked.lines
    scope_map = checked.scope_map
    linkage = checked.linkage
    cics_eib_plan_ = checked.cics_eib
    assert (
        result is not None
        and suite is not None
        and surface is not None
        and lines is not None
        and scope_map is not None
    )  # implied by checked.problems being empty
    normalized_lines = list(lines)

    boundaries = collect_boundaries(result.ast)
    registry = TallyRegistry(suite)
    terminator_plans, _ = find_terminator_plans(
        surface, result.ast, suite, scope_map, lines
    )
    goto_exit_plans, _ = find_goto_exit_plans(result.ast, scope_map, lines)
    flow_plans, _ = find_flow_mock_plans(result.ast, suite, lines)
    lines = splice_program(
        lines,
        boundaries,
        surface,
        suite,
        registry,
        terminator_plans,
        flow_plans,
        checked.file_status_fields,
        goto_exit_plans=goto_exit_plans,
        trace=False,
    )
    lines, _ = transform_data_division_exec(lines, copybook_paths=args.copybook_path)

    reset_lines = reset_move_lines(result.ast)
    if linkage is not None:
        reset_lines = reset_lines + extra_reset_lines(linkage)
    if cics_eib_plan_ is not None:
        reset_lines = reset_lines + cics_eib.reset_lines(cics_eib_plan_)
    artifact = build_driver(
        suite,
        reset_lines,
        registry,
        extra_working_storage_lines=extra_working_storage(checked),
    )
    instrumented = _insert_driver(lines, artifact)

    original_lines = source_path.read_text(encoding="utf-8").splitlines()

    # The sandbox stays alive for the entire DAP session (a long-lived
    # conversation, unlike run/trace/coverage's "compile, run, collect,
    # clean up" shape) -- it is only torn down once adapter.run() returns,
    # after the client disconnects.
    with sandbox_dir_maybe_kept(root=docker_toolchain.WORK_ROOT, keep=False) as tmp:
        instrumented_path = tmp / source_path.with_suffix(".cbl").name
        instrumented_path.write_text(
            "\n".join(instrumented) + "\n", encoding="utf-8", newline="\n"
        )

        def launch_session(_dap_arguments: dict) -> DebugSession:
            compiled = docker_toolchain.compile_source(instrumented_path, debug=True)
            if not compiled.success:
                raise RuntimeError(f"compile failed:\n{compiled.stderr}")
            assert compiled.binary_path is not None  # implied by compiled.success

            variable_table = parse_local_header(
                instrumented_path.with_suffix(".c.l.h").read_text(encoding="utf-8")
            )
            generated_c_lines = build_generated_c_line_map(
                instrumented_path.with_suffix(".c").read_text(encoding="utf-8")
            )
            line_map = LineMap.build(instrumented, normalized_lines, original_lines)
            paragraph_index = ParagraphIndex.build(result.ast)
            gdb = GdbSession(docker_toolchain.start_gdb_session(compiled.binary_path))
            return DebugSession(
                gdb=gdb,
                line_map=line_map,
                variable_table=variable_table,
                generated_c_lines=generated_c_lines,
                paragraph_index=paragraph_index,
                instrumented_file=instrumented_path.name,
            )

        adapter = DapAdapter(sys.stdin.buffer, sys.stdout.buffer, launch_session)
        adapter.run()

    return 0


def _cmd_mutate(args: argparse.Namespace) -> int:
    """Mutation-test a program/.cut pair: generate mutants, run the suite
    against each, and report which ones survived (see
    docs/2026-07-29-mutation-testing-design.md)."""
    import json

    from mockymock.mutation.operators import generate_mutants
    from mockymock.mutation.report import (
        MutantResult,
        format_console,
        to_json_dict,
    )
    from mockymock.mutation.runner import run_mutation

    source_path = Path(args.program)
    cut_path = Path(args.cut)
    if not _check_input_files("mockymock mutate", source_path, cut_path):
        return 1

    if args.list:
        # --list never runs anything, so flags that only mean something
        # for a real mutation run would be silently ignored -- refuse the
        # combination instead (2026-08-12 audit Finding 16). --timeout is
        # exempt only because argparse always materializes its default.
        ignored = [
            flag
            for flag, value in (
                ("--json-report", args.json_report),
                ("--fail-under", args.fail_under),
                ("--jobs", args.jobs if args.jobs != 1 else None),
                ("--no-coverage-gate", None if args.coverage_gate else True),
            )
            if value is not None
        ]
        if ignored:
            print(
                f"mockymock mutate: --list only lists mutants and would "
                f"ignore {', '.join(ignored)} -- drop --list to run the "
                f"mutation suite, or drop the other flag(s)"
            )
            return 1
        mutants = generate_mutants(source_path.read_text(encoding="utf-8").splitlines())
        for mutant in mutants:
            print(f"line {mutant.line} [{mutant.operator}] {mutant.description}")
        print(f"{len(mutants)} mutant(s)")
        return 0

    if args.jobs < 1:
        print(f"mockymock mutate: --jobs must be at least 1 (got {args.jobs})")
        return 1

    def on_progress(result: MutantResult) -> None:
        marker = {
            "killed": "killed   ",
            "survived": "SURVIVED ",
            "stillborn": "stillborn",
            "timeout": "timeout  ",
        }[result.status]
        if not result.ran:
            # Same verdict, different evidence: say so rather than letting
            # it read as a mutant that was built and beat the suite.
            marker = "uncovered"
        print(
            f"  {marker} line {result.mutant.line} "
            f"[{result.mutant.operator}] {result.mutant.description}"
        )

    problems, outcome, notes = run_mutation(
        source_path,
        cut_path,
        args.copybook_path,
        timeout_seconds=args.timeout,
        on_progress=on_progress,
        jobs=args.jobs,
        coverage_gate=args.coverage_gate,
    )
    for note in notes:
        print(f"mockymock mutate: {note}")
    if problems or outcome is None:
        for problem in problems:
            print(f"mockymock mutate: {problem}")
        return 1

    print(format_console(outcome))
    if args.json_report:
        # Same convention as run's report flags: an auxiliary report file
        # that can't be written is reported cleanly, and the exit code
        # stands on the mutation outcome itself.
        if _write_report_file(
            "mutate",
            "--json-report",
            args.json_report,
            json.dumps(to_json_dict(outcome), indent=2) + "\n",
        ):
            print(f"mockymock mutate: wrote JSON report -> {args.json_report}")

    score = outcome.score
    if args.fail_under is not None:
        if score is None or score * 100 < args.fail_under:
            shown = "n/a" if score is None else f"{score * 100:.1f}%"
            print(
                f"mockymock mutate: mutation score {shown} is below "
                f"--fail-under {args.fail_under}"
            )
            return 1
    return 0


def _cmd_lint(args: argparse.Namespace) -> int:
    """Run every static refusal check with zero Docker dependency. This
    function must never import mockymock.runtime.docker_toolchain -- that
    structural guarantee (not just documentation) is what makes `lint`
    usable in editors, pre-commit hooks, and CI lanes with no daemon."""
    from mockymock.cli.checks import run_static_checks

    source_path = Path(args.program)
    cut_path = Path(args.cut)
    if not _check_input_files("mockymock lint", source_path, cut_path):
        return 1
    result = run_static_checks(source_path, cut_path, args.copybook_path)
    for note in result.notes:
        print(f"mockymock lint: {note}")
    for problem in result.problems:
        if problem.startswith("  "):
            print(problem)
        else:
            print(f"mockymock lint: {problem}")
    if result.problems:
        problem_count = sum(1 for p in result.problems if not p.startswith("  "))
        print(f"mockymock lint: {problem_count} problem(s) found.")
        return 1
    print("mockymock lint: no problems found.")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    """Write the instrumented source to a file, adjusted for a real
    fixed-format COBOL compile (e.g. z/OS) instead of GnuCOBOL-only. See
    docs/2026-08-03-mainframe-export-command-design.md. Docker-free:
    identical pre-splice pipeline to `run` (via run_static_checks),
    stopping before compile_source/run_binary."""
    from mockymock.analysis.flow_mocks import find_flow_mock_plans
    from mockymock.analysis.refusal import find_goto_exit_plans, find_terminator_plans
    from mockymock.cli.checks import extra_working_storage, run_static_checks
    from mockymock.cli.mainframe_export import (
        build_provenance_header,
        fit_within_columns,
        insert_provenance_header,
        restore_fixed_format_columns,
    )
    from mockymock.splicer import cics_eib
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.linkage import extra_reset_lines
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.reset import reset_move_lines
    from mockymock.splicer.source_map import collect_boundaries
    from mockymock.splicer.sqlca import transform_data_division_exec

    source_path = Path(args.program)
    cut_path = Path(args.cut)
    if not _check_input_files("mockymock export", source_path, cut_path):
        return 1

    checked = run_static_checks(
        source_path,
        cut_path,
        args.copybook_path,
        case_names=args.case,
        tag_names=args.tag,
        preserve_compiler_directives=True,
    )
    for note in checked.notes:
        print(f"mockymock export: {note}")
    if checked.linkage is not None:
        _print_linkage_neutralization(
            "export",
            checked.linkage,
            applied=True,
            address_of=checked.linkage_address_of,
        )
    if checked.cics_eib is not None:
        _print_cics_eib_synthesis("export", checked.cics_eib, applied=True)
    if checked.problems:
        for problem in checked.problems:
            if problem.startswith("  "):
                print(problem)
            else:
                print(f"mockymock export: {problem}")
        return 1

    result = checked.parse_result
    suite = checked.suite
    surface = checked.surface
    lines = checked.lines
    scope_map = checked.scope_map
    linkage = checked.linkage
    cics_eib_plan_ = checked.cics_eib
    assert (
        result is not None
        and suite is not None
        and surface is not None
        and lines is not None
        and scope_map is not None
    )  # implied by checked.problems being empty

    # Restore the 7 columns normalize_fixed_format stripped BEFORE
    # splicing: collect_boundaries/splice_program are line-granular, never
    # column-position-sensitive (verified empirically during design), so
    # this uniform prefix is transparent to them and matches the column
    # convention splicer-generated lines already assume.
    lines = restore_fixed_format_columns(lines)

    boundaries = collect_boundaries(result.ast)
    registry = TallyRegistry(suite)
    terminator_plans, _ = find_terminator_plans(
        surface, result.ast, suite, scope_map, lines
    )
    goto_exit_plans, _ = find_goto_exit_plans(result.ast, scope_map, lines)
    flow_plans, _ = find_flow_mock_plans(result.ast, suite, lines)
    lines = splice_program(
        lines,
        boundaries,
        surface,
        suite,
        registry,
        terminator_plans,
        flow_plans,
        checked.file_status_fields,
        goto_exit_plans=goto_exit_plans,
        trace=False,
    )
    lines, _ = transform_data_division_exec(lines, copybook_paths=args.copybook_path)

    reset_lines = reset_move_lines(result.ast)
    if linkage is not None:
        reset_lines = reset_lines + extra_reset_lines(linkage)
    if cics_eib_plan_ is not None:
        reset_lines = reset_lines + cics_eib.reset_lines(cics_eib_plan_)
    artifact = build_driver(
        suite,
        reset_lines,
        registry,
        extra_working_storage_lines=extra_working_storage(checked),
    )
    instrumented = _insert_driver(lines, artifact)

    instrumented, overflow_problems = fit_within_columns(instrumented)
    if overflow_problems:
        for problem in overflow_problems:
            print(f"mockymock export: refused (COLUMN_OVERFLOW): {problem}")
        return 1

    header = build_provenance_header(str(source_path), str(cut_path))
    instrumented = insert_provenance_header(instrumented, header)

    output_path = (
        Path(args.output) if args.output else source_path.with_suffix(".mainframe.cbl")
    )
    if not _write_report_file(
        "export", "--output", str(output_path), "\n".join(instrumented) + "\n"
    ):
        return 1

    print(
        f"mockymock export: wrote mainframe-compilable source "
        f"({len(suite.test_cases)} test case(s)) -> {output_path}"
    )
    _report_unsupported_boundaries(surface, "export")
    return 0


def _cmd_collect(args: argparse.Namespace) -> int:
    """Authoritative test discovery for editor integrations: parse a .cut
    file (no .cbl, no Docker, no toolchain) and report its suite/cases with
    line numbers and tags. --json emits the machine-readable form the VS
    Code extension consumes; the default is a human-readable listing."""
    import json

    from mockymock.dsl.parser import CutParseError, parse_cut

    cut_path = Path(args.cut)
    if not _check_input_files("mockymock collect", cut_path):
        return 1
    try:
        suite = parse_cut(cut_path.read_text(encoding="utf-8"))
    except CutParseError as exc:
        if args.json:
            print(json.dumps({"version": 1, "error": str(exc)}, indent=2))
        else:
            print(f"mockymock collect: invalid .cut file {cut_path}: {exc}")
        return 1

    if args.json:
        payload = {
            "version": 1,
            "cutFile": str(cut_path),
            "suite": {"name": suite.name, "line": suite.line},
            "cases": [
                {"name": case.name, "line": case.line, "tags": list(case.tags)}
                for case in suite.test_cases
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(f"TESTSUITE {suite.name!r} (line {suite.line})")
        for case in suite.test_cases:
            tag_note = f"  [tags: {', '.join(case.tags)}]" if case.tags else ""
            print(f"  TESTCASE {case.name!r} (line {case.line}){tag_note}")
        print(f"{len(suite.test_cases)} test case(s)")
    return 0


def _cmd_skills_install(args: argparse.Namespace) -> int:
    """Copy the packaged Claude Code skill to ~/.claude/skills/mockymock
    (or ./.claude/skills/mockymock with --project). Pure file copy -- no
    Docker, no parsing -- so it's always available, same tier as
    lint/collect."""
    from mockymock.cli.skills_cmd import (
        SkillTargetExistsError,
        install_skill,
        resolve_target,
    )

    target = resolve_target(args.project)
    try:
        install_skill(target, force=args.force)
    except SkillTargetExistsError as exc:
        print(f"mockymock skills install: {exc}")
        return 1
    print(f"mockymock skills install: installed -> {target}")
    print(
        "mockymock skills install: restart Claude Code (or start a new "
        "session) to pick it up"
    )
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    # cobolparser.cli.parse.main() takes no argv parameter -- unlike this
    # module's own main(), it reads sys.argv[1:] directly. Patching it here
    # (restored in `finally`) is the standard idiom for delegating to an
    # argparse CLI that doesn't accept argv; safe in this single-threaded,
    # sequential-CLI context. The isinstance check (rather than `exc.code or
    # 0`) is required for mypy: SystemExit.code is typed `int | str | None`,
    # and this function's return type is `int`.
    from cobolparser.cli.parse import main as cobolparser_main

    saved_argv = sys.argv
    sys.argv = ["cobol-parser", *args.cobolparser_args]
    try:
        cobolparser_main()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    finally:
        sys.argv = saved_argv
    return 0


def _insert_driver(lines: list[str], artifact) -> list[str]:
    """Insert WORKING-STORAGE additions after that section's header, and
    procedure_lines right after the PROCEDURE DIVISION header."""
    result: list[str] = []
    inserted_ws = False
    inserted_proc = False
    for line in lines:
        result.append(line)
        upper = line.strip().upper()
        if not inserted_ws and upper.startswith("WORKING-STORAGE SECTION"):
            result.extend(
                f"       {ws_line}" for ws_line in artifact.working_storage_lines
            )
            inserted_ws = True
        if not inserted_proc and upper.startswith("PROCEDURE DIVISION"):
            result.append("")
            result.extend(artifact.procedure_lines)
            inserted_proc = True
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mockymock")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")

    setup_parser = subparsers.add_parser(
        "setup", help="Build the GnuCOBOL image and start the mockymock-cobc container"
    )
    setup_parser.set_defaults(func=_cmd_setup)

    generate_parser = subparsers.add_parser(
        "generate", help="Scaffold a starter .cut file from a COBOL program"
    )
    generate_parser.add_argument("program")
    generate_parser.add_argument("-o", "--output")
    generate_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    generate_parser.add_argument(
        "--with-data",
        action="store_true",
        help=(
            "Data-driven mode (Phase 8 of the gen-fixtures initiative): one "
            "TESTCASE per scenario from a cobol-parser fixture bundle, mock "
            "bodies built from its own generated data, instead of the "
            "placeholder scaffold. Calls cobol-parser's Python API directly "
            "unless --fixtures is also given. See "
            "docs/plans/2026-08-02-program-data-generation-implementation.md's "
            "Phase 8"
        ),
    )
    generate_parser.add_argument(
        "--fixtures",
        help=(
            "Consume a pre-generated fixture bundle JSON file (e.g. from "
            "cobol-parser's own 'gen-fixtures --format json') instead of "
            "calling cobol-parser's Python API. Implies --with-data"
        ),
    )
    generate_parser.add_argument(
        "--seed",
        type=int,
        help=(
            "Seed for the fixture bundle's random data generation "
            "(--with-data only, ignored with --fixtures). Omit to draw one; "
            "the bundle always reports which seed it used"
        ),
    )
    generate_parser.add_argument(
        "--scenarios",
        choices=["happy", "branches", "all"],
        default="happy",
        help=(
            "Scenario strategy for the fixture bundle (--with-data only, "
            "ignored with --fixtures): happy (one unconstrained scenario, "
            "default), branches (one scenario per reachable/satisfiable "
            "branch arm), all (branches + fixed empty-input/error-status/"
            "boundary-values families). Mirrors cobol-parser's own "
            "gen-fixtures --scenarios flag"
        ),
    )
    generate_parser.add_argument(
        "--rows",
        type=int,
        help=(
            "Rows to generate per data table on the --with-data "
            "self-generating path (generator default; invalid together "
            "with --fixtures, whose row count is already baked into the "
            "bundle). A scenario family that pins its own row count "
            "(e.g. --scenarios all's fixed 'empty input' family) ignores "
            "this and always generates zero rows for that scenario"
        ),
    )
    generate_parser.add_argument(
        "--placeholder",
        action="append",
        default=[],
        metavar="CATEGORY:KEY",
        help=(
            "Downgrade this boundary's mock body to its ordinary "
            "placeholder instead of bundle-seeded data (repeatable; the "
            "fixture stays mocked, just without generated data; valid "
            "with --with-data or --fixtures; an unmatched pair warns on "
            "stderr rather than silently doing nothing)"
        ),
    )
    generate_parser.set_defaults(func=_cmd_generate)

    fixtures_parser = subparsers.add_parser(
        "fixtures",
        help=(
            "Print a FixtureBundle (scenarios, mock data, expectations) as "
            "JSON for editor integrations"
        ),
    )
    fixtures_parser.add_argument("program")
    fixtures_parser.add_argument(
        "--scenarios",
        choices=["happy", "branches", "all"],
        default="happy",
        help="Which scenario set to generate (default happy)",
    )
    fixtures_parser.add_argument("--seed", type=int, help="Deterministic RNG seed")
    fixtures_parser.add_argument(
        "--rows",
        type=int,
        help=(
            "Rows to generate per data table (generator default). A "
            "scenario family that pins its own row count (e.g. "
            "--scenarios all's fixed 'empty input' family) ignores this "
            "and always generates zero rows for that scenario"
        ),
    )
    fixtures_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    fixtures_parser.set_defaults(func=_cmd_fixtures)

    run_parser = subparsers.add_parser(
        "run",
        help="Splice, compile, run, and assert a COBOL program against a .cut file",
    )
    run_parser.add_argument("program")
    run_parser.add_argument("--cut", required=True)
    run_parser.add_argument("--junit-xml")
    run_parser.add_argument(
        "--json-report",
        help=(
            "Write a machine-readable run report (per-case status, .cut "
            "line numbers, expected/actual per failure, tags) to this file"
        ),
    )
    run_parser.add_argument(
        "--case",
        action="append",
        help=(
            "Run only the TESTCASE with this exact name (repeatable; "
            "combines with --tag as a union). The suite still runs as one "
            "compile + binary, just with only the selected cases spliced in"
        ),
    )
    run_parser.add_argument(
        "--tag",
        action="append",
        help=(
            "Run only TESTCASEs carrying this tag (repeatable; combines "
            "with --case as a union)"
        ),
    )
    run_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    run_parser.add_argument(
        "--keep-sandbox",
        action="store_true",
        help="Do not delete the sandbox; print its path for inspection",
    )
    run_parser.add_argument(
        "--verbose",
        action="store_true",
        help="On compile failure, print the path to the instrumented source",
    )
    run_parser.add_argument(
        "--coverage",
        action="store_true",
        help=(
            "Compile with GnuCOBOL's --coverage flag and report per-line "
            "coverage after the run (gcov-based; reported against the "
            "instrumented source, not the original .cbl -- see "
            "docs/2026-07-17-coverage-reporting-design.md)"
        ),
    )
    run_parser.add_argument(
        "--coverage-out",
        help="Write the full coverage report (percentage + uncovered lines) to this file",
    )
    run_parser.add_argument(
        "--coverage-json",
        help=(
            "Write machine-readable coverage to this file, remapped onto "
            "the ORIGINAL .cbl's line numbers (splicer-inserted lines "
            "excluded). Implies --coverage"
        ),
    )
    run_parser.add_argument(
        "--trace",
        action="store_true",
        help=(
            "Trace the executed path through the program for a single test "
            "case and print it after the run, together with the mocks that "
            "fired in order. Requires exactly one --case"
        ),
    )
    run_parser.add_argument(
        "--trace-json",
        help=(
            "Write the machine-readable execution trace (executed path "
            "remapped onto the ORIGINAL .cbl's line numbers, plus the "
            "ordered mock timeline) to this file. Implies --trace"
        ),
    )
    run_parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help=(
            "Binary execution timeout in seconds (default 30); a mocked "
            "CALL that removes a loop's terminating condition can "
            "otherwise hang until this limit kills it (mirrors mutate's "
            "own --timeout)"
        ),
    )
    run_parser.add_argument(
        "--record-expectations",
        action="store_true",
        help=(
            "Golden/characterization mode: run the suite, capture the real "
            "runtime value behind every '*> STUB EXPECT <name>' comment in "
            "the .cut file, and rewrite the file in place with those stubs "
            "turned into real EXPECT lines. Best-effort and cumulative -- "
            "recorded/skipped counts are printed, with a reason for every "
            "skip. Never touches a line that isn't a stub comment (so a "
            "hand-written or previously-recorded EXPECT is never "
            "overwritten), and never rewrites the file at all if nothing "
            "was recorded. Does not change the run's exit code. See "
            "docs/2026-08-04-record-expectations-design.md"
        ),
    )
    run_parser.set_defaults(func=_cmd_run)

    debug_parser = subparsers.add_parser(
        "debug",
        help=(
            "Start an interactive Debug Adapter Protocol session for a "
            "single test case (breakpoints, stepping, variable inspection)"
        ),
    )
    debug_parser.add_argument("program")
    debug_parser.add_argument("--cut", required=True)
    debug_parser.add_argument(
        "--case",
        action="append",
        help="The single TESTCASE to debug (required, repeatable flag but exactly one value)",
    )
    debug_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    debug_parser.add_argument(
        "--dap-stdio",
        action="store_true",
        help="Run the DAP adapter on stdio (the mode the VS Code extension spawns)",
    )
    debug_parser.set_defaults(func=_cmd_debug)

    lint_parser = subparsers.add_parser(
        "lint",
        help=(
            "Run every static refusal check on a program + .cut pair "
            "without Docker (fast, editor/CI friendly)"
        ),
    )
    lint_parser.add_argument("program")
    lint_parser.add_argument("--cut", required=True)
    lint_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    lint_parser.set_defaults(func=_cmd_lint)

    mutate_parser = subparsers.add_parser(
        "mutate",
        help=(
            "Mutation-test a program against its .cut suite: mutate "
            "statements one at a time and report which mutants the tests "
            "fail to kill"
        ),
    )
    mutate_parser.add_argument("program")
    mutate_parser.add_argument("--cut", required=True)
    mutate_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    mutate_parser.add_argument(
        "--list",
        action="store_true",
        help="Only list the mutants that would be run (no Docker needed)",
    )
    mutate_parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help=(
            "Per-mutant run timeout in seconds (default 15); a mutant that "
            "exceeds it counts as killed -- a hang would be noticed too"
        ),
    )
    mutate_parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Run N mutants in parallel, each in its own sandbox and worker "
            "process (default 1). The useful ceiling is not the core count "
            "but the shared mockymock-cobc container's 1 GiB memory limit, "
            "which every concurrent cobc draws from at once -- raise this "
            "gradually and watch for compile failures on a large program"
        ),
    )
    mutate_parser.add_argument(
        "--no-coverage-gate",
        dest="coverage_gate",
        action="store_false",
        help=(
            "Build and run every mutant, including ones on lines the "
            "baseline proved the suite never executes. By default those are "
            "reported as survivors straight from the baseline's coverage, "
            "which is the same verdict for a fraction of the wall clock"
        ),
    )
    mutate_parser.add_argument(
        "--json-report",
        help="Write the full machine-readable mutation report to this file",
    )
    mutate_parser.add_argument(
        "--fail-under",
        type=float,
        help="Exit 1 if the mutation score (percent) is below this value",
    )
    mutate_parser.set_defaults(func=_cmd_mutate)

    collect_parser = subparsers.add_parser(
        "collect",
        help=(
            "List a .cut file's suite and test cases (names, line numbers, "
            "tags) without running anything"
        ),
    )
    collect_parser.add_argument("--cut", required=True)
    collect_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human listing",
    )
    collect_parser.set_defaults(func=_cmd_collect)

    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help=(
            "Serve a local web page showing whether Docker and the "
            "GnuCOBOL toolchain are up (read-only; does not build or start "
            "anything)"
        ),
    )
    dashboard_parser.add_argument(
        "--port",
        type=int,
        # Resolved in _cmd_dashboard rather than here: importing
        # web.server for its DEFAULT_PORT would pull runtime.docker_toolchain
        # (and its Dockerfile read) into every `mockymock --help`, breaking
        # this module's deferred-import rule. test_cli_dashboard.py pins the
        # literal below against web.server.DEFAULT_PORT.
        default=None,
        help="Port to serve on (default 8765; 0 picks a free one)",
    )
    dashboard_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open a browser window automatically",
    )
    dashboard_parser.set_defaults(func=_cmd_dashboard)

    analyze_parser = subparsers.add_parser(
        "analyze",
        help=(
            "Run a cobol-parser analyzer subcommand (dead-code, "
            "program-flow, io-sequence, move-type-check, linkage-check, "
            "language-env, ims-dli, analyze) and print its JSON report"
        ),
    )
    analyze_parser.add_argument(
        "cobolparser_args",
        nargs=argparse.REMAINDER,
        metavar="COBOL_PARSER_ARGS",
        help=(
            "Arguments forwarded verbatim to cobol-parser's own CLI, e.g. "
            "'dead-code PROGRAM.cbl --compact'"
        ),
    )
    analyze_parser.set_defaults(func=_cmd_analyze)

    export_parser = subparsers.add_parser(
        "export",
        help=(
            "Write the instrumented COBOL source to a file, adjusted for "
            "a real fixed-format COBOL compile (e.g. z/OS) instead of "
            "GnuCOBOL-only"
        ),
    )
    export_parser.add_argument("program")
    export_parser.add_argument("--cut", required=True)
    export_parser.add_argument("-o", "--output")
    export_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    export_parser.add_argument(
        "--case",
        action="append",
        help=(
            "Include only the TESTCASE with this exact name (repeatable; "
            "combines with --tag as a union)"
        ),
    )
    export_parser.add_argument(
        "--tag",
        action="append",
        help=(
            "Include only TESTCASEs carrying this tag (repeatable; "
            "combines with --case as a union)"
        ),
    )
    export_parser.set_defaults(func=_cmd_export)

    skills_parser = subparsers.add_parser(
        "skills", help="Manage the packaged Claude Code skill for mockymock"
    )
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command")

    # Bare `mockymock skills` (no subcommand) must print THIS parser's
    # usage, not fall through to main()'s top-level-help fallback -- the
    # user typed a valid subcommand and needs its own options, not all
    # twelve commands (2026-08-12 audit Finding 14).
    def _cmd_skills_help(args: argparse.Namespace) -> int:
        skills_parser.print_help()
        return 1

    skills_parser.set_defaults(func=_cmd_skills_help)
    skills_install_parser = skills_subparsers.add_parser(
        "install",
        help=(
            "Install the mockymock Claude Code skill (SKILL.md + "
            "reference/ files) so a Claude Code session can use it"
        ),
    )
    skills_install_parser.add_argument(
        "--project",
        action="store_true",
        help=(
            "Install into ./.claude/skills/mockymock instead of "
            "~/.claude/skills/mockymock"
        ),
    )
    skills_install_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing install at the target path",
    )
    skills_install_parser.set_defaults(func=_cmd_skills_install)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
