"""mockymock CLI entry point."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

from mockymock import __version__
from mockymock._lines import read_utf8_source, split_source_lines


def _cmd_setup(args: argparse.Namespace) -> int:
    from mockymock.runtime import docker_toolchain

    try:
        docker_toolchain.ensure_toolchain(force_rebuild=args.rebuild)
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
    from cobolparser.preprocess import CopybookNotFoundError, expand_copybooks

    from mockymock.analysis.flow_targets import normalize_flow_targets
    from mockymock.analysis.refusal import (
        check_expansion_warnings,
        check_unresolved_copybooks,
        check_whole_program,
    )
    from mockymock.cli.discovery import copybook_not_found_hint

    source_path = Path(args.program)
    if not source_path.is_file():
        print(f"mockymock fixtures: no such file: {source_path}", file=sys.stderr)
        return 1

    if not _check_rows_non_negative("fixtures", args.rows):
        return 1

    _apply_config_to_args(args, source_path)

    # Mirrors _cmd_generate's order: expand copybooks (if any --copybook-path
    # was given) before the parse gate below, so the gate sees the same
    # source generate_with_scenarios_from_file will eventually parse itself
    # -- gating on the raw, unexpanded source would let an unresolvable COPY
    # slide past as a no-op (cobolparser tolerates unexpanded COPY under
    # FAIL_FAST) instead of being refused here. generate_with_scenarios_from_file
    # still re-expands and re-parses internally; that duplicate work is the
    # price of a correctness gate rather than one that just happens to work.
    raw_source = read_utf8_source(source_path)
    if args.copybook_path:
        try:
            expansion = expand_copybooks(raw_source, copybook_paths=args.copybook_path)
        except CopybookNotFoundError as exc:
            print(f"mockymock fixtures: {exc}", file=sys.stderr)
            print(copybook_not_found_hint(), file=sys.stderr)
            return 1
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
    normalize_flow_targets(result.ast)
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
    except CopybookNotFoundError as exc:
        print(f"mockymock fixtures: {exc}", file=sys.stderr)
        print(copybook_not_found_hint(), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 -- surfaced verbatim to the caller
        print(f"mockymock fixtures: {exc}", file=sys.stderr)
        return 1
    print(bundle.to_json())
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    from mockymock.web import server

    port = server.DEFAULT_PORT if args.port is None else args.port
    try:
        server.serve(
            port=port,
            open_browser=not args.no_browser,
            reports_root=(
                Path(args.reports_dir).expanduser() if args.reports_dir else None
            ),
        )
    except OSError as exc:
        # Almost always "address already in use" -- a second dashboard, or
        # something else on the port. Actionable message, not a traceback.
        print(f"mockymock dashboard: could not serve on {server.HOST}:{port}: {exc}")
        return 1
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    from mockymock.cli.doctor import (
        format_doctor_json,
        format_doctor_text,
        gather_full_status,
    )

    report = gather_full_status()
    if args.json:
        import json

        print(json.dumps(format_doctor_json(report), indent=2))
    else:
        print(format_doctor_text(report))
    return 0 if report.ready else 1


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


def _layout(args: argparse.Namespace):
    """The project layout (tests folder, source root) for this invocation,
    from the config file main() loaded. See cli/discovery.py."""
    from mockymock.cli.discovery import project_layout

    return project_layout(getattr(args, "_config", None))


def _resolve_program_and_cut(
    command: str, args: argparse.Namespace
) -> tuple[Path, Path] | None:
    """Resolve exactly one (program, .cut) pair for a command that has
    both a `program` positional and a `--cut` flag, filling in whichever
    one is missing from its sibling by same-stem convention (see
    mockymock/cli/discovery.py and docs/2026-09-15-cli-ergonomics-design.md).
    An explicit value for either always wins. Prints a clean, actionable
    error and returns None on any failure -- callers just `return 1`."""
    from mockymock.cli.discovery import (
        DiscoveryError,
        resolve_cut_path,
        resolve_program_path,
    )

    program_arg = getattr(args, "program", None)
    cut_arg = getattr(args, "cut", None)
    if program_arg is None and cut_arg is None:
        print(
            f"{command}: pass a program (and/or --cut) -- give at least "
            f"one so the other can be inferred from its sibling file"
        )
        return None
    try:
        if program_arg is None:
            assert cut_arg is not None  # the both-None case returned above
            cut_path = Path(cut_arg)
            source_path = resolve_program_path(None, cut_path, _layout(args))
        elif cut_arg is None:
            source_path = Path(program_arg)
            cut_path = resolve_cut_path(None, source_path, _layout(args))
        else:
            source_path = Path(program_arg)
            cut_path = Path(cut_arg)
    except DiscoveryError as exc:
        print(f"{command}: {exc}")
        return None
    if not _check_input_files(command, source_path, cut_path):
        return None
    return source_path, cut_path


def _apply_config_to_args(
    args: argparse.Namespace, program_path: Path | None = None
) -> None:
    """Merge the project config file (mockymock.toml or pyproject.toml's
    [tool.mockymock], see mockymock/cli/config.py) into `args` for
    whichever of copybook_path/seed this subcommand's subparser defined.
    An explicit CLI flag always wins; this only fills in a value the
    flag left at its argparse-level default (None, or an empty list for
    --copybook-path's `action="append"`). Safe to call unconditionally
    from any _cmd_* -- an attribute this command doesn't have is simply
    skipped via hasattr.

    When `program_path` is given, the resolved copybook_path list is
    further extended with the conventional default directories (the
    program's own `copybooks/` subdirectory, then its own directory) via
    `discovery.effective_copybook_paths` -- see
    docs/2026-09-15-copybook-discovery-defaults-design.md. Every _cmd_*
    that has both `copybook_path` and a resolved `program_path` passes it
    here; `_cmd_fixtures`/`_cmd_generate` are the only two with
    copybook_path but no early single-pair resolution step, so they pass
    `source_path` explicitly at their own call sites.

    --timeout is deliberately not config-overridable: run/mutate each
    give it a real argparse-level default (30/15) that
    test_run_timeout_defaults_to_30_seconds and its mutate counterpart
    pin directly off build_parser() output, before any config file is
    ever loaded -- overriding it here would need a sentinel default that
    breaks telling 'the user passed --timeout 30' apart from 'nobody
    passed --timeout at all', which isn't worth it for one flag most
    projects won't want to fix project-wide anyway."""
    from mockymock.cli.config import MockymockConfig, resolve, resolve_copybook_paths

    config: MockymockConfig = getattr(args, "_config", None) or MockymockConfig()
    if hasattr(args, "copybook_path"):
        resolved = resolve_copybook_paths(args.copybook_path, config)
        if program_path is not None:
            from mockymock.cli.discovery import effective_copybook_paths

            resolved = effective_copybook_paths(program_path, resolved)
        args.copybook_path = resolved
    if hasattr(args, "seed"):
        args.seed = resolve(args.seed, config.seed)


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
    args: argparse.Namespace,
    command: str,
    suite_name: str,
    reason: str,
    *,
    cut_suite=None,
    cut_file: Path | None = None,
    program_file: Path | None = None,
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
    rather than a bespoke report shape only this path would exercise.

    `cut_suite`/`cut_file`/`program_file`, when known, go into the JSON
    report so an editor can still place the failure (issue #204): without
    them `cutFile`, `programFile` and the suite line were all null."""
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
            format_json_report(
                build_json_report(
                    suite_result,
                    cut_suite=cut_suite,
                    cut_file=str(cut_file) if cut_file is not None else None,
                    program_file=(
                        str(program_file) if program_file is not None else None
                    ),
                )
            ),
        )


def _default_output(args: argparse.Namespace, source_path: Path) -> Path:
    """-o/--output when given; else the layout's place for a new suite
    (`<tests>/<folder>/PROG[.<name>].cut`, see discovery.default_suite_path).
    The folders are created here so the write that follows can't fail on
    a missing tests/ subfolder."""
    if args.output:
        return Path(args.output)
    from mockymock.cli.discovery import default_suite_path

    output = default_suite_path(source_path, _layout(args), getattr(args, "name", None))
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _cmd_suites(args: argparse.Namespace) -> int:
    """`mockymock suites [PROGRAM] [--name NAME] [--json]`: which program
    every suite tests (and by which lookup rule), or with PROGRAM, that
    program's suites plus where a new one would go. Docker-free and
    parse-free; the VS Code extension pairs files with this rather than
    its own copy of the rules. See cli/discovery.py."""
    import json

    from mockymock.cli.discovery import (
        DiscoveryError,
        default_suite_path,
        discover_cut_files,
        find_suites,
        resolve_program,
    )

    layout = _layout(args)
    payload: dict = {
        "version": 1,
        "root": str(layout.root),
        "testsDir": str(layout.tests_dir),
        "sourceRoot": str(layout.source_root),
    }
    if args.program is not None:
        program = Path(args.program)
        if not program.is_file():
            message = f"mockymock suites: no such file: {program}"
            print(json.dumps({**payload, "error": message}) if args.json else message)
            return 1
        suites = find_suites(program, layout)
        new_path = default_suite_path(program, layout, args.name)
        payload.update(
            program=str(program.resolve()),
            suites=[str(p.resolve()) for p in suites],
            newSuitePath=str(new_path.resolve()),
        )
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            for suite in suites:
                print(suite)
            if not suites:
                print(f"mockymock suites: {program} has no suites yet")
            print(f"mockymock suites: a new suite would go to {new_path}")
        return 0

    rows: list[dict[str, str | None]] = []
    for cut in discover_cut_files(layout.root):
        try:
            program, rule = resolve_program(cut, layout)
            rows.append(
                {
                    "cut": str(cut.resolve()),
                    "program": str(program.resolve()),
                    "rule": rule,
                }
            )
        except DiscoveryError as exc:
            rows.append({"cut": str(cut.resolve()), "program": None, "error": str(exc)})
    payload["suites"] = rows
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for row in rows:
            if row["program"]:
                print(f"{row['cut']} -> {row['program']} ({row['rule']})")
            else:
                print(f"{row['cut']} -> ? ({row['error']})")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    """`mockymock init PROG.cbl`: compose the existing `generate
    --with-data` + `run --record-expectations` path into one command, so
    a first scaffold has real, golden-recorded assertions instead of
    empty mock bodies -- and degrade honestly (no Docker attempt, a
    clear next step) when Docker isn't set up yet. See
    docs/2026-09-15-init-command-design.md.

    Reentrant rather than a deep refactor of `_cmd_generate`/`_cmd_run`'s
    internals: builds real argv lists and parses them with this same
    module's own `build_parser()`, so every flag `generate --with-data`/
    `run --record-expectations` would need gets argparse's own correct
    default -- never a hand-built Namespace that could silently miss an
    attribute those large functions read. This is a deliberate departure
    from the design doc's proposed 'refactor into a plain function
    returning a result object' approach: lower risk for the same
    external behavior, since neither _cmd_generate nor _cmd_run's
    existing code changes at all."""
    from mockymock.cli.doctor import gather_full_status

    source_path = Path(args.program)
    if not _check_input_files("mockymock init", source_path):
        return 1

    output_path = _default_output(args, source_path)
    if source_path.suffix.lower() == ".cut" or output_path.resolve() == (
        source_path.resolve()
    ):
        # `mockymock init X.cut` would otherwise be told X.cut "already
        # exists, pass --force" -- and --force would then parse the .cut
        # as COBOL and overwrite it with the result.
        print(
            f"mockymock init: {source_path} is the .cut file, not the COBOL "
            f"program -- pass the program (e.g. "
            f"{source_path.with_suffix('.cbl')})"
        )
        return 1
    if output_path.exists() and not args.force:
        print(
            f"mockymock init: {output_path} already exists -- pass --force "
            f"to overwrite it, or --output to write somewhere else"
        )
        return 1

    config = getattr(args, "_config", None)
    copybook_paths = args.copybook_path or []

    generate_argv = [
        "generate",
        str(source_path),
        "--output",
        str(output_path),
        "--with-data",
        "--scenarios",
        args.scenarios,
    ]
    if args.force:
        # Already gated above with init's own message; generate refuses
        # an existing output without it.
        generate_argv.append("--force")
    if args.seed is not None:
        generate_argv += ["--seed", str(args.seed)]
    for path in copybook_paths:
        generate_argv += ["--copybook-path", path]

    print(f"mockymock init: scaffolding {output_path} from {source_path} (--with-data)")
    generate_args = build_parser().parse_args(generate_argv)
    generate_args._config = config
    exit_code = _cmd_generate(generate_args)
    if exit_code != 0:
        return exit_code

    if args.scenarios != "happy":
        print(
            "Note: branch-targeted scenarios are not yet verified to reach "
            "their named arm -- see "
            "docs/2026-09-04-scenario-branch-verification.md. Confirm with "
            "'mockymock run ... --trace' for anything security- or "
            "correctness-critical."
        )

    report = gather_full_status()
    if not report.ready:
        print(
            "mockymock init: Docker isn't available, so I generated a "
            "suite with real test data but could not run it to record "
            f"expected values. Run 'mockymock run {source_path} --cut "
            f"{output_path} --record-expectations' once Docker is set up "
            "(see 'mockymock doctor')."
        )
        return 0

    run_argv = [
        "run",
        str(source_path),
        "--cut",
        str(output_path),
        "--record-expectations",
    ]
    for path in copybook_paths:
        run_argv += ["--copybook-path", path]

    print(f"mockymock init: running {output_path} to record expected values")
    run_args = build_parser().parse_args(run_argv)
    run_args._config = config
    run_exit_code = _cmd_run(run_args)
    if run_exit_code == 0:
        print(
            f"mockymock init: next, run 'mockymock run {source_path} "
            f"--cut {output_path}'"
        )
    else:
        print(
            f"mockymock init: {output_path} was written, but recording its "
            f"expected values failed (see above) -- fix that, then run "
            f"'mockymock run {source_path} --cut {output_path} "
            f"--record-expectations'"
        )
    return run_exit_code


def _reindent_snippet(snippet: str, indent_unit: str) -> str:
    """Re-render a `directive_snippet()` block (always emitted with a
    hardcoded 4-space unit: MOCK/END-MOCK at 4, body at 8) using
    `indent_unit` instead, preserving relative depth. Used by `--fill` so
    an inserted block matches the target file's own indentation rather
    than always assuming 4 spaces."""
    out_lines = []
    for line in snippet.splitlines():
        stripped = line.lstrip(" ")
        depth = (len(line) - len(stripped)) // 4
        out_lines.append(f"{indent_unit * depth}{stripped}")
    return "\n".join(out_lines)


def _fill_cut_file(source_path: Path, cut_path: Path, args: argparse.Namespace) -> int:
    """`mockymock generate --fill CUT_FILE`: insert only the missing MOCK
    blocks CUT_FILE's own test cases need (from the same UNMOCKED_*
    analysis `lint` runs), writing back to CUT_FILE in place. Every
    existing directive, EXPECT, VERIFY, and comment is preserved
    byte-for-byte -- this is a text insertion at known line numbers, not
    a re-serialization of the parsed model (which would risk
    reformatting hand-written directives). An existing MOCK block is
    never edited even if its body is empty or wrong -- filling in a gap
    is safe to automate, rewriting authored logic is not.

    Reuses `checks.run_static_checks`'s own `check_test_case` pass (via
    its `unmocked_reasons`, docs/2026-09-15-actionable-refusals-and-fill-design.md)
    rather than re-running reachability analysis independently, so
    `--fill` and `lint` can never disagree about what's missing."""
    from mockymock.cli.checks import run_static_checks
    from mockymock.dsl.parser import (
        _END_MOCK_RE,
        _MOCK_BARE_RE,
        _MOCK_QUOTED_RE,
        _PERFORM_RE,
    )

    if not _check_input_files("mockymock generate", cut_path):
        return 1

    checked = run_static_checks(source_path, cut_path, args.copybook_path)
    if checked.suite is None:
        for problem in checked.problems:
            if problem.startswith("  "):
                print(problem)
            else:
                print(f"mockymock generate: {problem}")
        return 1

    suite = checked.suite
    # Untranslated newlines: read_text() turns CRLF into LF, which made the
    # CRLF check below dead and rewrote a CRLF .cut as LF on POSIX; the
    # write below uses newline="" so Windows does not turn "\r\n" into
    # "\r\r\n" (or an LF file into CRLF) either.
    original_text = read_utf8_source(cut_path, keep_newlines=True)
    newline = "\r\n" if "\r\n" in original_text else "\n"
    raw_lines = original_text.splitlines()

    indent = "    "
    for raw in raw_lines:
        stripped = raw.lstrip(" ")
        if stripped.upper().startswith("MOCK "):
            indent = raw[: len(raw) - len(stripped)]
            break

    case_starts = sorted({case.line for case in suite.test_cases if case.line})

    def _case_end(case_line: int) -> int:
        later = [ln for ln in case_starts if ln > case_line]
        return (min(later) - 1) if later else len(raw_lines)

    def _perform_line(case_line: int, end_line: int) -> int | None:
        """The case's own PERFORM line: the first PERFORM in its range
        that is *not* inside a MOCK ... END-MOCK body (a mock body is
        verbatim COBOL and may itself PERFORM a paragraph; anchoring on
        that would splice the new block into the middle of another
        mock's body)."""
        in_mock_body = False
        for line_no in range(max(case_line, 1), end_line + 1):
            if line_no > len(raw_lines):
                break
            text = raw_lines[line_no - 1].strip()
            if in_mock_body:
                if _END_MOCK_RE.match(text):
                    in_mock_body = False
                continue
            if _MOCK_QUOTED_RE.match(text) or _MOCK_BARE_RE.match(text):
                in_mock_body = True
                continue
            if _PERFORM_RE.match(text):
                return line_no
        return None

    inserted_headers: list[tuple[int, str]] = []
    per_line_inserts: dict[int, list[str]] = {}
    filled_cases = 0
    added_blocks = 0
    warnings: list[str] = []
    # (anchor line, header, block length) per inserted block.
    inserted_blocks: list[tuple[int, str, int]] = []
    # Cases whose PERFORM line could not be found, with the headers they
    # needed: a PROVIDER-expanded case's own range (its ROW line) holds
    # no PERFORM, but the block inserted for the shared template covers
    # every row -- so such a case is only a problem when nothing did.
    unlocated: list[tuple[str, list[str]]] = []

    for case_index, case in enumerate(suite.test_cases):
        reasons = checked.unmocked_reasons.get(case_index, [])
        fixable = [r for r in reasons if r.suggested_fix]
        for r in reasons:
            if not r.suggested_fix:
                warnings.append(f"TESTCASE {case.name!r}: {r.code}: {r.message}")
        if not fixable:
            continue
        end_line = _case_end(case.line) if case.line else len(raw_lines)
        perform_line_no = _perform_line(case.line, end_line) if case.line else None
        if perform_line_no is None:
            unlocated.append(
                (
                    case.name,
                    [
                        _reindent_snippet(r.suggested_fix, indent)
                        .splitlines()[0]
                        .strip()
                        for r in fixable
                        if r.suggested_fix is not None
                    ],
                )
            )
            continue
        new_lines: list[str] = []
        # One block per distinct directive, not per site: two reachable
        # READs of the same file produce two UNMOCKED_READ reasons with
        # the same header, and the parser rejects a duplicate MOCK.
        seen_headers: set[str] = {
            _header_line(raw_lines[ln - 1])
            for ln in range(max(case.line, 1), end_line + 1)
            if ln <= len(raw_lines)
        }
        for r in fixable:
            assert r.suggested_fix is not None  # `fixable` was filtered on this
            snippet = _reindent_snippet(r.suggested_fix, indent)
            header = snippet.splitlines()[0].strip()
            if header in seen_headers:
                continue
            seen_headers.add(header)
            block_lines = snippet.splitlines()
            new_lines.extend(block_lines)
            inserted_blocks.append((perform_line_no, header, len(block_lines)))
            added_blocks += 1
        if not new_lines:
            continue
        per_line_inserts.setdefault(perform_line_no, []).extend(new_lines)
        filled_cases += 1

    if per_line_inserts:
        result_lines: list[str] = []
        # Report each inserted block at the line it lands on in the
        # written file, not the pre-insertion line it was anchored to.
        final_line_of: dict[int, int] = {}
        for line_no, raw in enumerate(raw_lines, start=1):
            if line_no in per_line_inserts:
                final_line_of[line_no] = len(result_lines) + 1
                result_lines.extend(per_line_inserts[line_no])
            result_lines.append(raw)
        new_text = newline.join(result_lines)
        if original_text.endswith(("\n", "\r\n")):
            new_text += newline
        cut_path.write_text(new_text, encoding="utf-8", newline="")
        offset_within_anchor: dict[int, int] = {}
        for anchor, header, block_len in inserted_blocks:
            start = final_line_of[anchor] + offset_within_anchor.get(anchor, 0)
            inserted_headers.append((start, header))
            offset_within_anchor[anchor] = (
                offset_within_anchor.get(anchor, 0) + block_len
            )

    covered = {header for _, header, _ in inserted_blocks}
    for case_name, headers in unlocated:
        if all(header in covered for header in headers):
            continue
        warnings.append(
            f"TESTCASE {case_name!r}: could not locate its PERFORM line "
            f"to insert a fix before -- skipped"
        )

    print(
        f"mockymock generate --fill: added {added_blocks} mock block(s) "
        f"across {filled_cases} test case(s)"
    )
    for line_no, header in inserted_headers:
        print(f"{cut_path}:{line_no}: {header}")
    for warning in warnings:
        print(f"mockymock generate: {warning}")

    # Everything `lint` would still refuse that no MOCK block can fix
    # (a flow-mock target that doesn't exist, a terminator layout, an
    # UNMOCKED_* reason with no mechanical fix): print it and fail, so
    # `--fill` exiting 0 means the next `lint` exits 0 too.
    # Only the per-TESTCASE UNMOCKED_* lines `--fill` read from
    # `unmocked_reasons` count as handled: a hook PERFORM's refusal reads
    # the same way ("refused (UNMOCKED_...)") but nothing here inserts
    # into BEFORE-EACH/BEFORE-ALL, so matching on the prefix exited 0 with
    # nothing filled and the next lint failed again (issue #208).
    filled = {
        f"refused ({r.code}): {r.message}"
        for reasons in checked.unmocked_reasons.values()
        for r in reasons
        if r.code.startswith("UNMOCKED_")
    }
    remaining = [
        problem
        for problem in checked.problems
        if not problem.startswith("  ") and problem not in filled
    ]
    for problem in remaining:
        print(f"mockymock generate: {problem}")
    if remaining or warnings:
        return 1
    return 0


def _header_line(raw: str) -> str:
    """A `.cut` line normalized the way `--fill` compares MOCK headers:
    stripped, so an existing `MOCK READ INV-FILE` (any indentation) is
    recognized as already present."""
    return raw.strip()


def _cmd_generate(args: argparse.Namespace) -> int:
    from cobolparser import parse_cobol
    from cobolparser.preprocess import (
        CopybookNotFoundError,
        expand_copybooks,
        normalize_fixed_format,
        strip_compiler_directives,
    )

    from mockymock.analysis.cics_eib import cics_eib_plan
    from mockymock.analysis.flow_targets import normalize_flow_targets
    from mockymock.analysis.linkage import address_of_sites, linkage_plan
    from mockymock.analysis.mock_surface import analyze
    from mockymock.analysis.refusal import (
        check_cics_eib_layout,
        check_expansion_warnings,
        check_linkage_layout,
        check_source_format,
        check_unresolved_copybooks,
        check_whole_program,
    )
    from mockymock.cli.discovery import copybook_not_found_hint
    from mockymock.dsl.fixture_bundle import (
        FixtureBundle,
        UnsupportedBundleVersionError,
        load_fixture_bundle,
        load_fixture_bundle_file,
    )
    from mockymock.dsl.generator import ProgramContext, scaffold_cut
    from mockymock.splicer.cics_resp import expand_dfhresp, expansion_note
    from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

    source_path = Path(args.program)
    if not _check_input_files("mockymock generate", source_path):
        return 1

    if args.fill is not None:
        conflicting = [
            flag
            for flag, value in (
                ("-o/--output", args.output),
                ("--with-data", args.with_data),
                ("--fixtures", args.fixtures),
            )
            if value
        ]
        if conflicting:
            print(
                f"mockymock generate: --fill is not valid together with "
                f"{', '.join(conflicting)} -- --fill always writes back to "
                f"the file it read"
            )
            return 1
        _apply_config_to_args(args, source_path)
        return _fill_cut_file(source_path, Path(args.fill), args)

    # The default path is the program's existing sibling PROG.cut when
    # there is one, so writing unconditionally replaced a hand-written
    # suite with a bare scaffold (issue #201). Refuse like `init` does,
    # an explicit -o included, before any parsing.
    existing = _default_output(args, source_path)
    if existing.exists() and not args.force:
        print(
            f"mockymock generate: {existing} already exists -- pass --force "
            f"to overwrite it, -o/--output to write somewhere else, or "
            f"--fill {existing} to add only its missing mocks"
        )
        return 1

    if not _check_rows_non_negative("generate", args.rows):
        return 1

    if args.per_paragraph and (args.with_data or args.fixtures):
        print(
            "mockymock generate: --per-paragraph is not valid together with "
            "--with-data or --fixtures -- those build one case per scenario",
            file=sys.stderr,
        )
        return 1

    _apply_config_to_args(args, source_path)

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
    elif not args.per_paragraph:
        # One case per scenario is the default (--with-data only makes it
        # explicit). When it was NOT asked for explicitly, a generator
        # failure degrades to the per-paragraph scaffold with a note instead
        # of failing the command: an editor's "new test suite" button
        # should still produce a suite on a program the generator can't
        # handle. An explicit --with-data keeps the hard failure.
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
            # cobol-parser wraps the not-found error in a ProgramLayoutError;
            # the actionable hint applies to the cause just the same.
            if isinstance(exc, CopybookNotFoundError) or isinstance(
                exc.__cause__, CopybookNotFoundError
            ):
                print(copybook_not_found_hint())
                return 1
            if args.with_data:
                return 1
            print(
                "mockymock generate: falling back to one test case per "
                "paragraph (--per-paragraph)"
            )

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

    raw_source = read_utf8_source(source_path)
    program_source = raw_source
    if args.copybook_path:
        # See _cmd_fixtures's identical guard on the same call for why
        # this can raise on realistic inputs (audit finding F6).
        try:
            expansion = expand_copybooks(raw_source, copybook_paths=args.copybook_path)
        except CopybookNotFoundError as exc:
            print(f"mockymock generate: {exc}")
            print(copybook_not_found_hint())
            return 1
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
    normalize_flow_targets(result.ast)
    if not result.success:
        print(f"mockymock generate: {len(result.errors)} parse error(s):")
        for error in result.errors:
            print(f"  {error}")
        return 1

    # See run_static_checks: free-format source is column-chopped below.
    format_reasons = check_source_format(program_source)
    for reason in format_reasons:
        print(f"mockymock generate: refused ({reason.code}): {reason.message}")
    if format_reasons:
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
    lines = split_source_lines(
        normalize_fixed_format(
            split_source_lines(strip_compiler_directives(raw_source))
        )
    )

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

    # Same translator-exact DFHRESP expansion `run_static_checks` applies.
    lines, resp_expansions = expand_dfhresp(lines)
    if resp_expansions:
        print(f"mockymock generate: {expansion_note(resp_expansions)}")
    cics_eib_reasons = check_cics_eib_layout(result.ast, lines)
    for reason in cics_eib_reasons:
        print(f"mockymock generate: refused ({reason.code}): {reason.message}")
    if cics_eib_reasons:
        return 1
    cics_eib = cics_eib_plan(result.ast, lines)
    if cics_eib is not None:
        _print_cics_eib_synthesis("generate", cics_eib, applied=False)

    if (
        bundle is not None
        and not bundle.scenarios
        and not (args.with_data or args.fixtures)
    ):
        # Implicit scenario mode: degrade like a generator failure does.
        print(
            "mockymock generate: the fixture bundle has zero scenarios -- "
            "falling back to one test case per paragraph (--per-paragraph)"
        )
        bundle = None
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
    program_name = result.ast.program_name
    # The same normalized lines + statement-start boundaries the splicer's
    # own `statement_span` uses (so a generated MOCK READ's exhaustion
    # branch can carry the program's own AT END imperative verbatim -- the
    # exact text the splice is about to delete), plus the CAPTURE ARG lines
    # each CALL boundary can safely be scaffolded with.
    program_context = ProgramContext.build(result.ast, lines, surface)
    cut_text = scaffold_cut(
        program_name,
        surface,
        bundle,
        frozenset(placeholder_pairs),
        program_context,
    )

    if bundle is not None and not (args.with_data or args.fixtures):
        if "TESTCASE " not in cut_text:
            # Implicit scenario mode produced nothing to run (e.g. the
            # program's entry point has no boundary to mock): the
            # per-paragraph scaffold is the more useful default here, and
            # matches what plain `generate` wrote before scenarios became
            # the default.
            print(
                "mockymock generate: no scenario could be scaffolded as a "
                "test case -- falling back to one test case per paragraph "
                "(--per-paragraph)"
            )
            bundle = None
            cut_text = scaffold_cut(
                program_name,
                surface,
                None,
                frozenset(placeholder_pairs),
                program_context,
            )

    output_path = _default_output(args, source_path)
    # Unlike run's auxiliary report flags, this file IS the deliverable:
    # a failed write is a failed command (same convention as export).
    if not _write_report_file("generate", "-o/--output", str(output_path), cut_text):
        return 1
    case_count = cut_text.count("TESTCASE ")
    print(f"mockymock generate: wrote {case_count} test case(s) -> {output_path}")
    if case_count == 0 and bundle is not None:
        # The bundle had scenarios (zero is refused above) yet none became
        # a TESTCASE; the empty suite would run as "0 run, 0 failed" and
        # exit 1, so report it here, where it was made (issue #150). A
        # plain `generate` on a program with no boundary to mock writes
        # an empty suite on purpose and still exits 0.
        print(
            "mockymock generate: no scenario could be scaffolded as a test "
            "case -- the file holds an empty TESTSUITE",
            file=sys.stderr,
        )
        return 1
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
    blocks = [
        (block, kind, names)
        for block, kind, names in (
            ("DFHEIBLK", "CICS", plan.referenced_names),
            ("DLIDIB", "DL/I", getattr(plan, "dib_names", [])),
        )
        if names
    ]
    for block, kind, names in blocks:
        listed = ", ".join(names)
        if applied:
            action = (
                f"synthesized a 01 {block} WORKING-STORAGE group "
                f"(referenced: {listed})"
            )
        else:
            action = (
                f"a later `run` will synthesize a 01 {block} WORKING-STORAGE "
                f"group (referenced: {listed})"
            )
        field_kind = "EIB" if block == "DFHEIBLK" else "DIB"
        print(
            f"mockymock {command}: {action} -- no {kind} translator runs in "
            f"this pipeline, so this program's undeclared {field_kind} field "
            f"references get real, addressable storage instead"
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


def _per_pair_report_path(base: str, cut_path: Path, test_root: Path) -> str:
    """Insert the .cut file's path (relative to `test_root`, separators
    folded to '-') before the extension: 'report.xml' + 'ORDRPROC.cut'
    -> 'report-ORDRPROC.xml'; 'svc1/ORDRPROC.cut' -> 'report-svc1-
    ORDRPROC.xml'. Used so directory-mode output files don't have every
    discovered pair overwrite the same single file -- the relative path,
    not just the stem, because two suites with the same stem in
    different directories (a monorepo's svc1/PROG.cut and svc2/PROG.cut)
    are exactly the case a per-pair name exists to keep apart."""
    base_path = Path(base)
    try:
        relative = cut_path.relative_to(test_root)
    except ValueError:
        try:
            relative = cut_path.resolve().relative_to(test_root.resolve())
        except ValueError:
            relative = Path(cut_path.name)
    tag = "-".join(relative.with_suffix("").parts)
    return str(base_path.with_name(f"{base_path.stem}-{tag}{base_path.suffix}"))


def _report_tag_root(cut_files: list[Path], test_root: Path) -> Path:
    """What `_per_pair_report_path` names each suite's report relative to:
    the test root when every suite lies under it (directory mode), else
    the deepest folder holding all of them. `run PROG.cbl` with several
    suites gets them from `find_suites` -- a sibling `src/pay/PROG.cut`
    beside `tests/pay/PROG.cut`, or suites in different folders that name
    PROG with a PROGRAM line -- which need not lie under the test root;
    naming those by file name alone gave two of them one report file, and
    the second suite's report silently replaced the first's."""

    def under(path: Path) -> bool:
        try:
            path.relative_to(test_root)
            return True
        except ValueError:
            return False

    if all(under(path) for path in cut_files):
        return test_root
    return Path(os.path.commonpath([str(p.resolve().parent) for p in cut_files]))


# Every `run` flag naming an output file: each gets a per-pair name in
# directory mode, or the second suite silently overwrites the first's.
_RUN_OUTPUT_PATH_FLAGS = (
    "junit_xml",
    "json_report",
    "coverage_json",
    "coverage_out",
    "trace_json",
)


def _several_suites(args: argparse.Namespace) -> list[Path] | None:
    """For `run`/`lint PROG.cbl` with no --cut: the program's suites when it
    has more than one (each then runs in turn, like the directory-wide
    mode), else None so the ordinary single-pair path handles it --
    including its error when there are none."""
    if args.program is None or args.cut is not None:
        return None
    from mockymock.cli.discovery import find_suites

    program = Path(args.program)
    if not program.is_file():
        return None
    suites = find_suites(program, _layout(args))
    return suites if len(suites) > 1 else None


def _run_directory(
    args: argparse.Namespace, cut_files: list[Path] | None = None
) -> int:
    """`mockymock run` with neither a program nor --cut given: discover
    every .cut file under the test root (the config file's own
    test_root, default '.') and run each against its sibling program.
    Reuses _cmd_run's own single-pair code path unchanged, via a shallow
    copy of args with program/cut filled in, rather than a parallel
    implementation -- so a plain `mockymock run PROG.cbl --cut PROG.cut`
    invocation is completely untouched by this function ever existing.
    See docs/2026-09-15-cli-ergonomics-design.md."""
    import copy

    from mockymock.cli.discovery import (
        DiscoveryError,
        discover_cut_files,
        resolve_program_path,
    )

    config = getattr(args, "_config", None)
    test_root = Path((config.test_root if config else None) or ".")
    layout = _layout(args)
    if cut_files is None:
        cut_files = discover_cut_files(test_root)
    if not cut_files:
        print(f"mockymock run: no .cut files found under {test_root}")
        return 1

    exit_code = 0
    ran = 0
    unresolved: list[str] = []
    tag_root = _report_tag_root(cut_files, test_root)
    for cut_path in cut_files:
        try:
            program_path = resolve_program_path(None, cut_path, layout)
        except DiscoveryError as exc:
            unresolved.append(str(exc))
            continue
        ran += 1
        sub_args = copy.copy(args)
        sub_args.program = str(program_path)
        sub_args.cut = str(cut_path)
        for flag in _RUN_OUTPUT_PATH_FLAGS:
            if getattr(args, flag, None):
                setattr(
                    sub_args,
                    flag,
                    _per_pair_report_path(getattr(args, flag), cut_path, tag_root),
                )
        print(f"== {cut_path} ==")
        exit_code = _cmd_run(sub_args) or exit_code

    for reason in unresolved:
        print(f"mockymock run: {reason}")
    print(
        f"mockymock run: {ran} suite(s) run, {len(unresolved)} .cut file(s) "
        f"skipped (no program found)"
    )
    if ran == 0:
        return 1
    return exit_code


def _cmd_run(args: argparse.Namespace) -> int:
    import json

    from mockymock.analysis.flow_mocks import find_flow_mock_plans
    from mockymock.analysis.refusal import find_goto_exit_plans, find_terminator_plans
    from mockymock.analysis.stub_expectations import scan_stub_expectations
    from mockymock.cli.checks import (
        extra_reset_lines_for,
        extra_working_storage,
        run_static_checks,
    )
    from mockymock.report.coverage import (
        build_original_line_map,
        format_coverage_console,
        format_coverage_json,
        map_coverage_to_original,
        parse_gcov,
        summarize_original,
    )
    from mockymock.report.formatters import format_console, format_junit_xml
    from mockymock.report.json_report import (
        build_json_report,
        format_json_report,
        not_run_case_names,
        risky_case_ids,
    )
    from mockymock.report.record_rewrite import (
        address_fields,
        build_recording_report,
        field_pictures,
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
    from mockymock.splicer.sqlca import sqlca_reset_lines, transform_data_division_exec

    # Directory-wide mode: no program, no --cut -- discover every .cut
    # file under the test root and run each against its sibling program.
    # See docs/2026-09-15-cli-ergonomics-design.md.
    if args.program is None and args.cut is None:
        return _run_directory(args)
    if (several := _several_suites(args)) is not None:
        return _run_directory(args, several)

    # Input existence is the one check that runs even before anything else:
    # a typo'd path must fail in milliseconds with no traceback.
    pair = _resolve_program_and_cut("mockymock run", args)
    if pair is None:
        return 1
    source_path, cut_path = pair

    _apply_config_to_args(args, source_path)

    # Asking for the coverage JSON, or a coverage report file, is asking
    # for coverage.
    if args.coverage_json:
        args.coverage = True
    if args.coverage_out:
        args.coverage = True
    # ... and so is asking for the coverage gate: --coverage-fail-under is
    # the `run` counterpart of `mutate --fail-under`, so it must be usable
    # on its own in a CI lane without also remembering --coverage.
    if args.coverage_fail_under is not None:
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
            cut_suite=checked.suite,
            cut_file=cut_path,
            program_file=source_path,
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

    reset_lines = reset_move_lines(result.ast) + sqlca_reset_lines(lines)
    if linkage is not None:
        # LINKAGE items `neutralize` folded into WORKING-STORAGE live under
        # the LINKAGE section in `result.ast` still (the transform edited
        # text, not the AST), so `reset_move_lines`'s WORKING-STORAGE walk
        # never sees them -- add their reset lines explicitly.
        reset_lines = reset_lines + extra_reset_lines(linkage)
    if cics_eib_plan_ is not None:
        reset_lines = reset_lines + cics_eib.reset_lines(cics_eib_plan_)
    reset_lines = reset_lines + extra_reset_lines_for(checked)

    # --record-expectations: scan the raw .cut text (not the parsed suite --
    # a "*> STUB EXPECT" line is an ordinary comment to parse_cut) against
    # the POST-filter `suite` (--case/--tag already applied by
    # run_static_checks) so a stub's case_index always means what
    # build_driver means by it. See
    # docs/2026-08-04-record-expectations-design.md.
    # Untranslated newlines, like `generate --fill`: the rewrite below
    # must keep a CRLF .cut CRLF (issue #199), so it is written back with
    # newline="" and rewrite_cut_text joins with the file's own newline.
    cut_text = read_utf8_source(cut_path, keep_newlines=True)
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
        snapshot=checked.snapshot,
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
            _write_failure_reports(
                args,
                "run",
                suite.name,
                compiled.stderr,
                cut_suite=suite,
                cut_file=cut_path,
                program_file=source_path,
            )
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
            instrumented_name = instrumented_path.name
            if args.coverage:
                gcov_result = docker_toolchain.run_gcov(instrumented_path)
                if gcov_result.success:
                    # Only the raw gcov parse happens inside the sandbox
                    # (the .gcov file dies with it); the console text is
                    # formatted below, once the original-.cbl remap the
                    # headline number comes from has been computed.
                    coverage_report = parse_gcov(gcov_result.gcov_text)
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
    not_run = not_run_case_names(suite_result, suite)
    # Under --record-expectations the run exists to fill in the missing
    # assertions, so labelling its cases risky would only be noise.
    risky = [] if stub_scan is not None else risky_case_ids(suite_result, suite)
    print(
        format_console(
            suite_result, crash_detail=crash_detail, not_run=not_run, risky=risky
        )
    )
    if executed.stderr:
        print("mockymock run: binary stderr:")
        print(executed.stderr.rstrip("\n"))

    if stub_scan is not None:
        # Best-effort and cumulative, never gating the run's own exit code
        # (see the design doc's "Best-effort, cumulative reporting" and
        # "Never overwrite a hand-edited EXPECT" sections): every stub the
        # scanner found ends up in exactly one of recorded/skipped, and the
        # file is only ever touched when at least one stub was recorded.
        pictures = field_pictures(result.ast, checked.captures)
        recording = build_recording_report(
            stub_scan, suite_result, address_fields(result.ast), pictures
        )
        rewritten = rewrite_cut_text(cut_text, recording, pictures)
        if rewritten is not None:
            cut_path.write_text(rewritten, encoding="utf-8", newline="")
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
            format_junit_xml(suite_result, crash_detail=crash_detail, not_run=not_run),
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

    # The original-.cbl remap is what BOTH the console headline and the
    # --coverage-fail-under gate read, so it is computed once here for
    # every --coverage run -- not only when --coverage-json asked for it,
    # as it was when the instrumented number was the only one printed.
    original_coverage = None
    if coverage_report is not None:
        original_source_lines = split_source_lines(read_utf8_source(source_path))
        mapped = map_coverage_to_original(
            coverage_report,
            instrumented,
            normalized_lines,
            original_source_lines,
        )
        original_coverage = summarize_original(mapped, original_source_lines)
        coverage_text = format_coverage_console(
            coverage_report,
            instrumented_name,
            original=original_coverage,
            program_name=source_path.name,
        )
        if args.coverage_json:
            _write_report_file(
                "run",
                "--coverage-json",
                args.coverage_json,
                format_coverage_json(
                    coverage_report,
                    mapped,
                    program_file=str(source_path),
                    instrumented_name=instrumented_name,
                ),
            )
    elif args.coverage_json:
        print(
            "mockymock run: coverage JSON not written -- the gcov pass "
            "failed (see the coverage error above)"
        )

    if coverage_text is not None:
        print(coverage_text)
        if args.coverage_out:
            _write_report_file(
                "run", "--coverage-out", args.coverage_out, coverage_text + "\n"
            )

    # The coverage gate is the `run` counterpart of `mutate --fail-under`,
    # and is judged against the ORIGINAL program's coverage -- gating on
    # the instrumented number would make the threshold move whenever
    # mockymock's own injected line count changed, which says nothing about
    # the program under test. A failed gcov pass fails the gate rather than
    # passing it silently: "no number" must never read as "good enough".
    # Recorded, not returned on, so --trace still prints below: the gate is
    # folded into this command's single final exit-code decision instead.
    coverage_gate_failed = False
    if args.coverage_fail_under is not None:
        if original_coverage is None:
            print(
                f"mockymock run: coverage gate failed -- no coverage was "
                f"measured (the gcov pass failed; see above), so "
                f"--coverage-fail-under {args.coverage_fail_under} cannot "
                f"be satisfied"
            )
            coverage_gate_failed = True
        elif original_coverage.percentage < args.coverage_fail_under:
            print(
                f"mockymock run: coverage {original_coverage.percentage:.2f}% "
                f"is below --coverage-fail-under {args.coverage_fail_under}"
            )
            coverage_gate_failed = True

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
                    split_source_lines(read_utf8_source(source_path)),
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
    # line, or the timeout killed a straggler). A tripped
    # --coverage-fail-under gate fails the command the same way, so a green
    # suite under an unmet coverage floor still exits nonzero in CI.
    if coverage_gate_failed:
        return 1
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
    from mockymock.cli.checks import (
        extra_reset_lines_for,
        extra_working_storage,
        run_static_checks,
    )
    from mockymock.debug.adapter import DapAdapter, DebugSession
    from mockymock.debug.call_stack import ParagraphIndex, build_generated_c_line_map
    from mockymock.debug.gdb_session import GdbSession
    from mockymock.debug.line_map import LineMap
    from mockymock.debug.variable_map import (
        buffer_layouts,
        declared_data_names,
        parse_local_header,
        unavailable_names,
    )
    from mockymock.runtime import docker_toolchain
    from mockymock.runtime.sandbox import sandbox_dir_maybe_kept
    from mockymock.splicer import cics_eib
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.linkage import extra_reset_lines
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.reset import reset_move_lines
    from mockymock.splicer.source_map import collect_boundaries
    from mockymock.splicer.sqlca import sqlca_reset_lines, transform_data_division_exec

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

    pair = _resolve_program_and_cut("mockymock debug", args)
    if pair is None:
        return 1
    source_path, cut_path = pair
    _apply_config_to_args(args, source_path)

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

    reset_lines = reset_move_lines(result.ast) + sqlca_reset_lines(lines)
    if linkage is not None:
        reset_lines = reset_lines + extra_reset_lines(linkage)
    if cics_eib_plan_ is not None:
        reset_lines = reset_lines + cics_eib.reset_lines(cics_eib_plan_)
    reset_lines = reset_lines + extra_reset_lines_for(checked)
    artifact = build_driver(
        suite,
        reset_lines,
        registry,
        extra_working_storage_lines=extra_working_storage(checked),
        snapshot=checked.snapshot,
    )
    instrumented = _insert_driver(lines, artifact)

    original_lines = split_source_lines(read_utf8_source(source_path))

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
                original_file=str(source_path),
                buffer_layouts=buffer_layouts(result.ast),
                unavailable=tuple(
                    unavailable_names(declared_data_names(result.ast), variable_table)
                ),
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

    pair = _resolve_program_and_cut("mockymock mutate", args)
    if pair is None:
        return 1
    source_path, cut_path = pair
    _apply_config_to_args(args, source_path)

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
        mutants = generate_mutants(split_source_lines(read_utf8_source(source_path)))
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
        if outcome.score_below(args.fail_under):
            shown = "n/a" if score is None else f"{score * 100:.1f}%"
            print(
                f"mockymock mutate: mutation score {shown} is below "
                f"--fail-under {args.fail_under}"
            )
            return 1
    return 0


def _lint_directory(
    args: argparse.Namespace, cut_files: list[Path] | None = None
) -> int:
    """`mockymock lint` with neither a program nor --cut given: discover
    every .cut file under the test root and lint each against its
    sibling program. See _run_directory's docstring -- same approach,
    reusing _cmd_lint's own single-pair path unchanged."""
    import copy

    from mockymock.cli.discovery import (
        DiscoveryError,
        discover_cut_files,
        resolve_program_path,
    )

    config = getattr(args, "_config", None)
    test_root = Path((config.test_root if config else None) or ".")
    layout = _layout(args)
    if cut_files is None:
        cut_files = discover_cut_files(test_root)
    if not cut_files:
        print(f"mockymock lint: no .cut files found under {test_root}")
        return 1

    exit_code = 0
    ran = 0
    unresolved: list[str] = []
    for cut_path in cut_files:
        try:
            program_path = resolve_program_path(None, cut_path, layout)
        except DiscoveryError as exc:
            unresolved.append(str(exc))
            continue
        ran += 1
        sub_args = copy.copy(args)
        sub_args.program = str(program_path)
        sub_args.cut = str(cut_path)
        print(f"== {cut_path} ==")
        exit_code = _cmd_lint(sub_args) or exit_code

    for reason in unresolved:
        print(f"mockymock lint: {reason}")
    print(
        f"mockymock lint: {ran} suite(s) checked, {len(unresolved)} .cut "
        f"file(s) skipped (no program found)"
    )
    if ran == 0:
        return 1
    return exit_code


def _cmd_lint(args: argparse.Namespace) -> int:
    """Run every static refusal check with zero Docker dependency. This
    function must never import mockymock.runtime.docker_toolchain -- that
    structural guarantee (not just documentation) is what makes `lint`
    usable in editors, pre-commit hooks, and CI lanes with no daemon."""
    from mockymock.cli.checks import no_assertion_warnings, run_static_checks

    if args.program is None and args.cut is None:
        return _lint_directory(args)
    if (several := _several_suites(args)) is not None:
        return _lint_directory(args, several)

    pair = _resolve_program_and_cut("mockymock lint", args)
    if pair is None:
        return 1
    source_path, cut_path = pair
    _apply_config_to_args(args, source_path)
    result = run_static_checks(source_path, cut_path, args.copybook_path)
    for note in result.notes:
        print(f"mockymock lint: {note}")
    for problem in result.problems:
        if problem.startswith("  "):
            print(problem)
        else:
            print(f"mockymock lint: {problem}")
    suite = result.suite
    if suite is None:
        # A refusal stopped the checks before they parsed the .cut file;
        # the warning is .cut-only, so it doesn't need the program.
        from mockymock.dsl.parser import parse_cut

        try:
            suite = parse_cut(read_utf8_source(cut_path))
        except Exception:  # noqa: BLE001 -- already reported as a problem
            suite = None
    warnings = no_assertion_warnings(suite) if suite is not None else []
    for warning in warnings:
        print(f"mockymock lint: {warning}")
    if warnings:
        print(f"mockymock lint: {len(warnings)} warning(s).")
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
    from mockymock.cli.checks import (
        extra_reset_lines_for,
        extra_working_storage,
        run_static_checks,
    )
    from mockymock.cli.mainframe_export import (
        SourceAttribution,
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
    from mockymock.splicer.sqlca import sqlca_reset_lines, transform_data_division_exec

    pair = _resolve_program_and_cut("mockymock export", args)
    if pair is None:
        return 1
    source_path, cut_path = pair
    _apply_config_to_args(args, source_path)

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

    reset_lines = reset_move_lines(result.ast) + sqlca_reset_lines(lines)
    if linkage is not None:
        reset_lines = reset_lines + extra_reset_lines(linkage)
    if cics_eib_plan_ is not None:
        reset_lines = reset_lines + cics_eib.reset_lines(cics_eib_plan_)
    reset_lines = reset_lines + extra_reset_lines_for(checked)
    artifact = build_driver(
        suite,
        reset_lines,
        registry,
        extra_working_storage_lines=extra_working_storage(checked),
        snapshot=checked.snapshot,
    )
    instrumented, driver_line_indices = _insert_driver_with_origins(lines, artifact)

    instrumented, overflow_problems = fit_within_columns(
        instrumented,
        attribution=SourceAttribution(
            driver_line_indices=driver_line_indices,
            cut_path=str(cut_path),
            cut_text=cut_path.read_text(encoding="utf-8", errors="replace"),
            program_path=str(source_path),
            program_text=source_path.read_text(encoding="utf-8", errors="replace"),
        ),
    )
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


def _collect_boundaries(
    source_path: Path, copybook_paths: list[str] | None
) -> list[dict]:
    """Every genuinely mockable boundary site in `source_path` (category
    is not None), whole-program -- NOT reachability-filtered by any one
    TESTCASE's PERFORM target, since this feeds editor completion for
    "every key this program could ever need mocked," not one particular
    test case's own reachable set (that's what `lint`'s refusal gate is
    for). Sites are returned in source order. See
    docs/2026-09-15-cut-editor-intelligence-design.md."""
    from cobolparser import parse_cobol
    from cobolparser.preprocess import expand_copybooks

    from mockymock.analysis.flow_targets import normalize_flow_targets
    from mockymock.analysis.mock_surface import analyze
    from mockymock.dsl.generator import directive_snippet

    raw_source = read_utf8_source(source_path)
    # `line` is shown against the .cbl the user has open, but sites are
    # numbered in the EXPANDED source: every COPY above a site shifted it
    # by the copybook's length (a 4-line WORKING-STORAGE copybook put a
    # line-9 CALL at "line 12"). Map back through cobol-parser's source map
    # where the installed release fills one in (1.8.x returns it empty,
    # and the expanded numbering is then kept as before).
    origin_line: dict[int, int] = {}
    if copybook_paths:
        expansion = expand_copybooks(
            raw_source, copybook_paths=copybook_paths, preserve_source_locations=True
        )
        raw_source = expansion.expanded_source
        origin_line = _main_file_lines(expansion.source_location_map or {})

    result = parse_cobol(raw_source, filename=source_path.name)
    normalize_flow_targets(result.ast)
    if result.errors or result.ast is None:
        raise ValueError(
            "; ".join(str(error) for error in result.errors) or "parse failed"
        )

    surface = analyze(result.ast)
    boundaries = []
    for site in surface.boundary_sites:
        if site.category is None:
            continue
        # `directive` is the exact MOCK header a scaffold would write for
        # this site (quoted key for CALL/MQ/SQL/CICS/DLI, the shortest
        # unique text prefix for SQL/CICS/DLI whose `key` is null) -- so
        # a consumer inserts what the DSL parses rather than re-deriving
        # the quoting rules. None when the scaffold itself would skip it.
        snippet = directive_snippet(site, surface)
        boundaries.append(
            {
                "category": site.category.value,
                "key": site.keys[0] if site.keys else None,
                "keys": list(site.keys),
                "directive": snippet.splitlines()[0].strip() if snippet else None,
                "label": site.label,
                "paragraph": site.paragraph_name,
                "line": origin_line.get(site.line, site.line),
                "matchText": site.match_text,
            }
        )
    return sorted(boundaries, key=lambda b: b["line"])


def _main_file_lines(source_map: dict[int, tuple[str, int]]) -> dict[int, int]:
    """Expanded line -> line of the program file itself, from a
    `CopybookExpansion.source_location_map` (`<main>` entries are the
    program's own lines). A line that came from a copybook maps to the
    COPY statement that pulled it in: the first program line after the
    last one emitted before it."""
    mapping: dict[int, int] = {}
    last_main = 0
    for expanded in sorted(source_map):
        origin_file, origin = source_map[expanded]
        if origin_file == "<main>":
            last_main = origin
            mapping[expanded] = origin
        else:
            mapping[expanded] = last_main + 1
    return mapping


def _cmd_explain(args: argparse.Namespace) -> int:
    """`mockymock explain <CODE>`: print (or list) the catalogued
    explanation for a refusal code, so `.cut` authors and editor
    tooltips get one shared source of truth instead of re-deriving what
    a code means from the message text alone. See
    docs/2026-09-15-cut-editor-intelligence-design.md."""
    import json

    from mockymock.analysis.refusal import REFUSAL_EXPLANATIONS

    if args.code is None or args.list:
        codes = sorted(REFUSAL_EXPLANATIONS)
        if args.json:
            print(json.dumps({"version": 1, "codes": codes}, indent=2))
        else:
            print(f"{len(codes)} catalogued refusal code(s):")
            for code in codes:
                print(f"  {code}")
        return 0

    code = args.code.upper()
    explanation = REFUSAL_EXPLANATIONS.get(code)
    if explanation is None:
        if args.json:
            print(
                json.dumps(
                    {
                        "version": 1,
                        "code": code,
                        "error": "not catalogued",
                        "knownCodes": sorted(REFUSAL_EXPLANATIONS),
                    },
                    indent=2,
                )
            )
        else:
            print(f"mockymock explain: {code!r} is not a catalogued refusal code.")
            print("Run 'mockymock explain --list' to see every code this covers.")
        return 1

    if args.json:
        print(
            json.dumps(
                {"version": 1, "code": code, "explanation": explanation}, indent=2
            )
        )
    else:
        print(code)
        print(f"  {explanation}")
        print("  See .okf/analysis.md's refusal table for the full picture.")
    return 0


def _cmd_collect(args: argparse.Namespace) -> int:
    """Authoritative test discovery for editor integrations: parse a .cut
    file (no .cbl, no Docker, no toolchain) and report its suite/cases with
    line numbers and tags. --json emits the machine-readable form the VS
    Code extension consumes; the default is a human-readable listing.

    --boundaries (2026-09-15) additionally reports every mockable boundary
    site in the paired program -- see docs/2026-09-15-cut-editor-intelligence-design.md.
    Requires --json and a program argument (no human-readable form is
    planned for it)."""
    import json

    from mockymock.dsl.parser import CutParseError, parse_cut

    if args.boundaries and not args.json:
        print("mockymock collect: --boundaries requires --json")
        return 1
    if args.boundaries and not args.program:
        print("mockymock collect: --boundaries requires a program argument")
        return 1

    cut_path = Path(args.cut)
    check_paths = [cut_path]
    program_path = Path(args.program) if args.program else None
    if program_path is not None:
        check_paths.append(program_path)
    if not _check_input_files("mockymock collect", *check_paths):
        return 1
    try:
        suite = parse_cut(read_utf8_source(cut_path))
    except CutParseError as exc:
        if args.json:
            print(json.dumps({"version": 1, "error": str(exc)}, indent=2))
        else:
            print(f"mockymock collect: invalid .cut file {cut_path}: {exc}")
        return 1

    boundaries = None
    if args.boundaries:
        assert program_path is not None  # checked above
        # Same copybook lookup lint/run use (config file + the program's
        # copybooks/ folder): without it a site inside a copybook vanished
        # from the list and completion offered nothing for it (issue #200).
        _apply_config_to_args(args, program_path)
        try:
            boundaries = _collect_boundaries(program_path, args.copybook_path)
        except Exception as exc:  # noqa: BLE001 -- surfaced verbatim to the caller
            print(json.dumps({"version": 1, "error": str(exc)}, indent=2))
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
        if boundaries is not None:
            payload["boundaries"] = boundaries
        print(json.dumps(payload, indent=2))
    else:
        print(f"TESTSUITE {suite.name!r} (line {suite.line})")
        for case in suite.test_cases:
            tag_note = f"  [tags: {', '.join(case.tags)}]" if case.tags else ""
            print(f"  TESTCASE {case.name!r} (line {case.line}){tag_note}")
        print(f"{len(suite.test_cases)} test case(s)")
    return 0


def _cmd_skills_install(args: argparse.Namespace) -> int:
    """Copy the packaged agent skills (mockymock, cobol-analysis,
    cobol-test) into the skills directory of Claude Code and/or GitHub
    Copilot (--target; skills_cmd.resolve_target names the directories),
    under the home directory or, with --project, the current one. Pure file copy -- no Docker, no config. Fail-closed
    across the set: if any target exists and --force is absent, nothing is
    written, so a half-installed set never mixes old and new copies."""
    from mockymock.cli.skills_cmd import (
        SKILL_NAMES,
        TARGET_LABELS,
        TARGETS,
        SkillTargetExistsError,
        install_skill,
        resolve_target,
    )

    names = args.skill or list(SKILL_NAMES)
    unknown = [n for n in names if n not in SKILL_NAMES]
    if unknown:
        print(
            f"mockymock skills install: unknown skill(s) {', '.join(unknown)} "
            f"(expected: {', '.join(SKILL_NAMES)})"
        )
        return 1
    assistants = list(TARGETS) if args.target == "all" else [args.target]
    targets = [
        (name, resolve_target(args.project, name, assistant))
        for assistant in assistants
        for name in names
    ]
    if not args.force:
        occupied = [t for _, t in targets if t.exists() or t.is_symlink()]
        if occupied:
            for target in occupied:
                print(
                    f"mockymock skills install: {target} already exists; "
                    f"use --force to overwrite"
                )
            return 1
    for name, target in targets:
        try:
            install_skill(target, force=args.force, name=name)
        except SkillTargetExistsError as exc:
            print(f"mockymock skills install: {exc}")
            return 1
        print(f"mockymock skills install: installed -> {target}")
    tools = " / ".join(TARGET_LABELS[a] for a in assistants)
    print(
        f"mockymock skills install: start a new {tools} session to pick up "
        "the skills; ask it to test a COBOL program to start with cobol-test."
    )
    return 0


def _cmd_skills_plugin(args: argparse.Namespace) -> int:
    """Write the cobol-testing Claude Code plugin as a local marketplace
    (no clone, no network), for `/plugin marketplace add <dir>`."""
    from mockymock import __version__
    from mockymock.cli.skills_cmd import (
        LOCAL_MARKETPLACE_NAME,
        PLUGIN_NAME,
        PluginTargetError,
        default_plugin_dir,
        export_plugin,
    )

    target = (
        Path(args.directory).expanduser() if args.directory else default_plugin_dir()
    )
    target = target.resolve()
    try:
        plugin_dir = export_plugin(target, version=__version__, force=args.force)
    except PluginTargetError as exc:
        print(f"mockymock skills plugin: {exc}")
        return 1
    print(f"mockymock skills plugin: wrote {PLUGIN_NAME} {__version__} -> {target}")
    print("mockymock skills plugin: in Claude Code, run:")
    print(f"  /plugin marketplace add {target}")
    print(f"  /plugin install {PLUGIN_NAME}@{LOCAL_MARKETPLACE_NAME}")
    print(
        "mockymock skills plugin: or load it for one session with "
        f"`claude --plugin-dir {plugin_dir}`. Re-run with --force after "
        "upgrading mockymock, then `/plugin marketplace update "
        f"{LOCAL_MARKETPLACE_NAME}`."
    )
    return 0


def _cmd_skills_mode(args: argparse.Namespace) -> int:
    """Read back (or set) the project's AI assistant mode -- how much the
    packaged skill checks in with the developer while it builds a suite.
    Loads the config file itself rather than using `args._config`: `skills`
    is one of the subcommands `main()` deliberately lets run with a
    malformed config (it defines neither `copybook_path` nor `seed`), and
    this is the one `skills` leaf that actually reads it, so it reports
    the parse error itself the same way `doctor` does."""
    from mockymock.cli.ai_mode import (
        ModeError,
        format_mode_json,
        format_mode_report,
        resolve_mode,
        validate,
        write_mode,
    )
    from mockymock.cli.config import ConfigError, load_config

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"mockymock skills mode: {exc}")
        return 1

    if args.set is not None:
        try:
            # Validated before the write so a typo'd mode names the valid
            # set instead of landing in the file for the next `run` to
            # reject. `choices=` would do this in argparse, but that needs
            # MODES imported at parser-build time -- see the deferred-import
            # rule in .okf/cli.md's Gotchas.
            validate(args.set)
            written = write_mode(args.set, config)
        except ModeError as exc:
            print(f"mockymock skills mode: {exc}")
            return 1
        config = load_config()
        print(f"mockymock skills mode: {args.set} -> {written}")

    resolved = resolve_mode(config)
    if args.json:
        import json

        print(json.dumps(format_mode_json(resolved), indent=2))
    else:
        print(format_mode_report(resolved))
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    """Join every check mockymock and cobol-parser can make on one
    program/.cut pair into a single report -- the steps taken, a
    verification level per test case, and the findings -- written as JSON
    and/or a self-contained HTML page. See report/test_report.py."""
    import json

    from mockymock.report.html_report import render_html
    from mockymock.report.journal import default_journal_path
    from mockymock.report.test_report import ReportOptions, build_report

    pair = _resolve_program_and_cut("mockymock report", args)
    if pair is None:
        return 1
    source_path, cut_path = pair
    _apply_config_to_args(args, source_path)
    if args.mutation_threshold < 0 or args.mutation_threshold > 100:
        print("mockymock report: --mutation-threshold must be between 0 and 100")
        return 1
    journal = Path(args.journal) if args.journal else default_journal_path(cut_path)
    options = ReportOptions(
        program=source_path,
        cut=cut_path,
        copybook_paths=list(args.copybook_path or []),
        run_json=Path(args.run_json) if args.run_json else None,
        coverage_json=Path(args.coverage_json) if args.coverage_json else None,
        mutation_json=Path(args.mutation_json) if args.mutation_json else None,
        journal=journal,
        execute=args.execute,
        mutate=args.mutate,
        scenarios=args.scenarios,
        seed=args.seed,
        timeout=args.timeout,
        mutation_threshold=args.mutation_threshold,
    )
    report = build_report(options)
    html_path = (
        Path(args.output)
        if args.output
        else source_path.with_name(f"{source_path.stem}.report.html")
    )
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_html(report), encoding="utf-8")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    for step in report["steps"]:
        print(
            f"mockymock report: [{step['status']:>7}] {step['title']}: {step['summary']}"
        )
    summary = report["summary"]
    findings = summary["findings"]
    print(
        f"mockymock report: {findings['high']} high, {findings['medium']} medium, "
        f"{findings['low']} low finding(s)"
    )
    print(f"mockymock report: wrote {html_path}")
    if args.json:
        print(f"mockymock report: wrote {args.json}")
    return 1 if summary["failed"] or summary["levels"].get("none") else 0


def _cmd_journal(args: argparse.Namespace) -> int:
    """Append one entry to a suite's assistant journal (report/journal.py),
    which `mockymock report` shows as a timeline."""
    from mockymock.report.journal import (
        JournalError,
        append_entry,
        default_journal_path,
    )

    if args.file:
        path = Path(args.file)
    elif args.cut:
        path = default_journal_path(Path(args.cut))
    else:
        print("mockymock journal: pass --cut (journal next to it) or --file")
        return 1
    try:
        append_entry(
            path,
            step=args.step,
            summary=args.summary,
            status=args.status,
            command=args.command_text,
            decision=args.decision,
        )
    except JournalError as exc:
        print(f"mockymock journal: {exc}")
        return 1
    print(f"mockymock journal: appended to {path}")
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
    return _insert_driver_with_origins(lines, artifact)[0]


def _insert_driver_with_origins(
    lines: list[str], artifact
) -> tuple[list[str], set[int]]:
    """`_insert_driver`, plus the 0-based indices of the lines it inserted.

    `export` needs those indices to say truthfully where an over-long line
    came from: mockymock's own generated driver (notably the
    WORKING-STORAGE reset, which re-serializes a long VALUE clause onto one
    line) is a routine overflow source, and it is not something any `.cut`
    edit can fix. Knowing the exact inserted range is what keeps that
    attribution a fact rather than a guess."""
    result: list[str] = []
    inserted: set[int] = set()
    inserted_ws = False
    inserted_proc = False

    def extend(new_lines) -> None:
        for new_line in new_lines:
            inserted.add(len(result))
            result.append(new_line)

    ws_lines = [f"       {ws_line}" for ws_line in artifact.working_storage_lines]
    # A program with no WORKING-STORAGE SECTION of its own (a subprogram
    # with only a LINKAGE or LOCAL-STORAGE SECTION, or no DATA DIVISION at
    # all) still needs the driver's fields declared -- without them every
    # UT-CURRENT-CASE / UT-FAIL-COUNT / tally reference is undefined and
    # the instrumented program cannot compile. Such a section is then
    # synthesized where WORKING-STORAGE belongs: before the first section
    # that must follow it, or before the PROCEDURE DIVISION.
    has_ws = any(
        _WS_HEADER_RE.match(line) for line in lines[: _first_procedure_index(lines)]
    )
    seen_data_division = False

    for line in lines:
        upper = line.strip().upper()
        if not inserted_ws and not has_ws:
            if upper.startswith("DATA DIVISION"):
                seen_data_division = True
            elif (
                seen_data_division and _AFTER_WS_SECTION_RE.match(line)
            ) or upper.startswith("PROCEDURE DIVISION"):
                if not seen_data_division:
                    extend(["       DATA DIVISION."])
                extend(["       WORKING-STORAGE SECTION."])
                extend(ws_lines)
                inserted_ws = True
        result.append(line)
        if not inserted_ws and upper.startswith("WORKING-STORAGE SECTION"):
            extend(ws_lines)
            inserted_ws = True
        if not inserted_proc and upper.startswith("PROCEDURE DIVISION"):
            extend([""])
            extend(artifact.procedure_lines)
            inserted_proc = True
    return result, inserted


_WS_HEADER_RE = re.compile(r"^\s*WORKING-STORAGE\s+SECTION\b", re.IGNORECASE)
#: DATA DIVISION sections that must come AFTER WORKING-STORAGE -- including a
#: LINKAGE SECTION header `splicer.linkage.neutralize` commented out, whose
#: items then belong to whatever section precedes them.
_AFTER_WS_SECTION_RE = re.compile(
    r"^\s*(?:\*>\s*)?(?:LOCAL-STORAGE|LINKAGE|COMMUNICATION|REPORT|SCREEN)"
    r"\s+SECTION\b",
    re.IGNORECASE,
)


def _first_procedure_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if line.strip().upper().startswith("PROCEDURE DIVISION"):
            return index
    return len(lines)


# argparse has no native notion of subcommand groups, so this is a
# formatted epilog block rather than a real grouping structure --
# purely presentational, and updated by hand whenever a subcommand is
# added or removed. See docs/2026-09-15-cli-ergonomics-design.md.
_COMMAND_GROUPS_EPILOG = """\
commands, grouped by how often you'll reach for them:

  Everyday:
    init       one command from a program to a .cut file with real assertions
    run        splice, compile, run, and assert a program against a .cut file
    generate   scaffold a starter .cut file from a COBOL program
    lint       static checks only, no Docker
    collect    list a .cut file's suite and test cases
    suites     which program each .cut suite tests, no Docker

  Diagnosing a failure:
    debug      interactive Debug Adapter Protocol session
    analyze    run a cobol-parser analyzer and print its report
    dashboard  local status page for Docker/GnuCOBOL readiness
    doctor     one-shot terminal readiness report

  Reporting:
    report     one HTML/JSON report: every step, a proof level per test
    journal    record an assistant's step for the report's timeline

  Advanced:
    mutate     mutation-test a program against its .cut suite
    export     write mainframe-ready instrumented source
    fixtures   print a FixtureBundle as JSON for editor integrations
    skills     manage the packaged agent skills (Claude Code, GitHub Copilot)
    setup      build the GnuCOBOL image and start the toolchain container

Run 'mockymock <command> --help' for a command's own options.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mockymock",
        epilog=_COMMAND_GROUPS_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")

    setup_parser = subparsers.add_parser(
        "setup",
        help="Build the GnuCOBOL image and start the mockymock-cobc container",
        description=(
            "Build the GnuCOBOL image (from this package's Dockerfile) if "
            "it isn't already built or is stale, then start the long-lived "
            "mockymock-cobc container every other command compiles and runs "
            "against. Safe to re-run: a current image/container is left "
            "alone. See 'mockymock doctor' to check readiness without "
            "building or starting anything."
        ),
    )
    setup_parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force a fresh image build even if a current one is cached",
    )
    setup_parser.set_defaults(func=_cmd_setup)

    init_parser = subparsers.add_parser(
        "init",
        help=(
            "One command from a COBOL program to a .cut file with real, "
            "golden-recorded assertions"
        ),
        description=(
            "Composes 'generate --with-data' + 'run --record-expectations' "
            "into one step, so a first scaffold has real generated data "
            "and recorded expected values instead of empty mock bodies. "
            "Degrades to a plain data-driven scaffold (no run attempted) "
            "with a clear next step when Docker isn't set up yet. See "
            "docs/2026-09-15-init-command-design.md."
        ),
    )
    init_parser.add_argument("program")
    init_parser.add_argument(
        "-o",
        "--output",
        help="Where to write the .cut file (default: tests/<folder>/<program>.cut)",
    )
    init_parser.add_argument(
        "--name",
        help="Name a second suite for the program: writes <program>.<NAME>.cut",
    )
    init_parser.add_argument(
        "--seed", type=int, help="Seed for the fixture bundle's random data generation"
    )
    init_parser.add_argument(
        "--scenarios",
        choices=["happy", "branches", "all"],
        default="happy",
        help="Scenario strategy for the fixture bundle (default happy)",
    )
    init_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output .cut file if it already exists",
    )
    init_parser.set_defaults(func=_cmd_init)

    suites_parser = subparsers.add_parser(
        "suites",
        help="List which program each .cut suite tests (no Docker)",
        description=(
            "Pair every .cut suite under the project with its program, "
            "or with PROGRAM, list that program's suites and where a new "
            "one would go. A suite names its program with a PROGRAM line, "
            "or by file name: PROG.cut / PROG.<topic>.cut beside the "
            "program, or under tests/ mirroring the program's folder."
        ),
    )
    suites_parser.add_argument("program", nargs="?")
    suites_parser.add_argument(
        "--name", help="With PROGRAM: report the path for <program>.<NAME>.cut"
    )
    suites_parser.add_argument(
        "--json", action="store_true", help="Machine-readable output"
    )
    suites_parser.set_defaults(func=_cmd_suites)

    generate_parser = subparsers.add_parser(
        "generate", help="Scaffold a starter .cut file from a COBOL program"
    )
    generate_parser.add_argument("program")
    generate_parser.add_argument(
        "-o",
        "--output",
        help=(
            "Where to write the .cut file (default: tests/<folder>/<program>.cut, "
            "mirroring the program's folder; beside the program when it "
            "already has a <program>.cut there)"
        ),
    )
    generate_parser.add_argument(
        "--name",
        help="Name a second suite for the program: writes <program>.<NAME>.cut",
    )
    generate_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output .cut file if it already exists",
    )
    generate_parser.add_argument(
        "--fill",
        metavar="CUT_FILE",
        help=(
            "Insert only the missing MOCK blocks an existing .cut file's "
            "test cases need (from the same UNMOCKED_* analysis 'lint' "
            "runs), writing back to CUT_FILE in place. Every existing "
            "directive, EXPECT, VERIFY, and comment is left untouched -- "
            "an existing MOCK block is never edited even if its body is "
            "empty or wrong. Mutually exclusive with -o/--output, "
            "--with-data, and --fixtures. See "
            "docs/2026-09-15-actionable-refusals-and-fill-design.md"
        ),
    )
    generate_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    generate_parser.add_argument(
        "--with-data",
        action="store_true",
        help=(
            "Data-driven mode, the default: one TESTCASE per scenario from "
            "a cobol-parser fixture bundle, mock bodies built from its own "
            "generated data. Passing it explicitly makes a generator "
            "failure fatal instead of falling back to --per-paragraph. "
            "Calls cobol-parser's Python API directly unless --fixtures is "
            "also given. See "
            "docs/plans/2026-08-02-program-data-generation-implementation.md's "
            "Phase 8"
        ),
    )
    generate_parser.add_argument(
        "--per-paragraph",
        action="store_true",
        help=(
            "One TESTCASE per paragraph that touches a boundary, with "
            "placeholder mock bodies, instead of one per scenario. Useful "
            "for isolating a leaf paragraph. Not valid with --with-data or "
            "--fixtures"
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
    run_parser.add_argument(
        "program",
        nargs="?",
        help=(
            "COBOL source file. Omit to infer it from --cut's sibling "
            "file (same directory, same stem); omit both program and "
            "--cut to discover and run every .cut file under the "
            "current directory (or the config file's test_root)"
        ),
    )
    run_parser.add_argument(
        "--cut",
        help="Test file. Omit to infer it from program's sibling .cut file",
    )
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
            "coverage after the run (gcov-based). The headline figure is "
            "the ORIGINAL .cbl's own coverage; the instrumented sandbox "
            "copy's higher number is reported below it for reference -- "
            "see docs/2026-07-17-coverage-reporting-design.md"
        ),
    )
    run_parser.add_argument(
        "--coverage-out",
        help="Write the full coverage report (percentage + uncovered lines) to this file",
    )
    run_parser.add_argument(
        "--coverage-fail-under",
        type=float,
        metavar="PERCENT",
        help=(
            "Exit nonzero when the ORIGINAL .cbl's line coverage is below "
            "this percentage -- the `run` counterpart of `mutate "
            "--fail-under`, so coverage can be CI-gated the same way. "
            "Implies --coverage"
        ),
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
            "otherwise hang until this limit kills it -- give a "
            'retrieve-and-loop CALL a sequence instead, MOCK CALL "X" '
            "ROWS ( ... ) TERMINAL ( ... ), so later calls end the loop "
            "(mirrors mutate's own --timeout)"
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
    debug_parser.add_argument(
        "program", nargs="?", help="Omit to infer from --cut's sibling file"
    )
    debug_parser.add_argument(
        "--cut", help="Omit to infer from program's sibling .cut file"
    )
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
    lint_parser.add_argument(
        "program",
        nargs="?",
        help=(
            "Omit to infer from --cut's sibling file; omit both to "
            "discover and lint every .cut file under the current "
            "directory (or the config file's test_root)"
        ),
    )
    lint_parser.add_argument(
        "--cut", help="Omit to infer from program's sibling .cut file"
    )
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
    mutate_parser.add_argument(
        "program", nargs="?", help="Omit to infer from --cut's sibling file"
    )
    mutate_parser.add_argument(
        "--cut", help="Omit to infer from program's sibling .cut file"
    )
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
    collect_parser.add_argument(
        "program",
        nargs="?",
        help="Required only with --boundaries",
    )
    collect_parser.add_argument("--cut", required=True)
    collect_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human listing",
    )
    collect_parser.add_argument(
        "--boundaries",
        action="store_true",
        help=(
            "Also report every mockable boundary site in program "
            "(category, key, paragraph, line) -- for editor completion. "
            "Requires --json and program. See "
            "docs/2026-09-15-cut-editor-intelligence-design.md"
        ),
    )
    collect_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable; --boundaries only)",
    )
    collect_parser.set_defaults(func=_cmd_collect)

    explain_parser = subparsers.add_parser(
        "explain",
        help="Print the catalogued explanation for a refusal code",
        description=(
            "One shared source of truth for what a refusal code means, "
            "backing both this CLI and the mocky-mock-vscode extension's "
            "hover. See docs/2026-09-15-cut-editor-intelligence-design.md."
        ),
    )
    explain_parser.add_argument(
        "code", nargs="?", help="A refusal code, e.g. UNSUPPORTED_DECLARATIVES"
    )
    explain_parser.add_argument(
        "--list",
        action="store_true",
        help="List every catalogued code instead of explaining one",
    )
    explain_parser.add_argument(
        "--json", action="store_true", help="Machine-readable output"
    )
    explain_parser.set_defaults(func=_cmd_explain)

    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help=(
            "Serve a local web page showing whether Docker and the "
            "GnuCOBOL toolchain are up (read-only; does not build or start "
            "anything), the 'mockymock report' test results found under "
            "the current directory, and whether the cobol-testing skills "
            "are installed for Claude Code and GitHub Copilot (with a button to install them)"
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
    dashboard_parser.add_argument(
        "--reports-dir",
        default=None,
        help=(
            "Where to look for 'mockymock report' HTML pages "
            "(*.report.html; default: the current directory)"
        ),
    )
    dashboard_parser.set_defaults(func=_cmd_dashboard)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help=(
            "Terminal-native readiness report (Docker/GnuCOBOL toolchain, "
            "cobol-parser, config file) -- read-only, never builds or "
            "starts anything"
        ),
        description=(
            "Reuses the same read-only probe 'mockymock dashboard' serves "
            "over HTTP, plus two checks of its own: whether cobol-parser "
            "is importable, and which project config file (if any) this "
            "invocation would load. Exits 0 when everything checked is "
            "ready, 1 otherwise. Never mutates anything -- suggests "
            "'mockymock setup', never runs it."
        ),
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output for scripting",
    )
    doctor_parser.set_defaults(func=_cmd_doctor)

    report_parser = subparsers.add_parser(
        "report",
        help=(
            "Write one HTML (and optional JSON) report for a program and its "
            ".cut suite: every analysis step, a verification level per test "
            "case, and the findings"
        ),
    )
    report_parser.add_argument(
        "program", nargs="?", help="Omit to infer from --cut's sibling file"
    )
    report_parser.add_argument(
        "--cut", help="Omit to infer from program's sibling .cut file"
    )
    report_parser.add_argument(
        "-o",
        "--output",
        help="HTML report path (default: <program>.report.html next to the program)",
    )
    report_parser.add_argument("--json", help="Also write the report as JSON here")
    report_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    report_parser.add_argument(
        "--execute",
        action="store_true",
        help="Run the suite (with coverage) now; needs Docker",
    )
    report_parser.add_argument(
        "--mutate",
        action="store_true",
        help="Run mutation testing now; needs Docker and takes longer",
    )
    report_parser.add_argument(
        "--run-json", help="Read results from an earlier 'run --json-report'"
    )
    report_parser.add_argument(
        "--coverage-json", help="Read coverage from an earlier 'run --coverage-json'"
    )
    report_parser.add_argument(
        "--mutation-json", help="Read an earlier 'mutate --json-report'"
    )
    report_parser.add_argument(
        "--journal",
        help="Assistant journal to include (default: <cut>.journal.jsonl if present)",
    )
    report_parser.add_argument(
        "--scenarios",
        default="branches",
        choices=["happy", "branches", "all", "none"],
        help="happy, branches, all, or none: how to measure reachable branch arms (default: branches)",
    )
    report_parser.add_argument("--seed", type=int, help="Seed for fixture generation")
    report_parser.add_argument(
        "--timeout", type=int, help="Per-run timeout in seconds passed to 'run'"
    )
    report_parser.add_argument(
        "--mutation-threshold",
        type=float,
        default=80.0,
        help="Mutation score (percent) a suite needs for its cases to reach L2 (default: 80)",
    )
    report_parser.set_defaults(func=_cmd_report)

    journal_parser = subparsers.add_parser(
        "journal",
        help="Append one assistant step to a suite's journal for 'mockymock report'",
    )
    journal_parser.add_argument(
        "--cut", help="The suite; the journal is <cut>.journal.jsonl next to it"
    )
    journal_parser.add_argument("--file", help="Explicit journal path instead")
    journal_parser.add_argument("--step", required=True, help="Step name, e.g. plan")
    journal_parser.add_argument(
        "--summary", required=True, help="What was done and what came of it"
    )
    journal_parser.add_argument(
        "--status",
        default="ok",
        help="ok, warn, fail, skipped, or info (default: ok)",
    )
    journal_parser.add_argument(
        "--command",
        dest="command_text",
        help="The command that was run, if any",
    )
    journal_parser.add_argument("--decision", help="A decision taken, and why")
    journal_parser.set_defaults(func=_cmd_journal)

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
    export_parser.add_argument(
        "program", nargs="?", help="Omit to infer from --cut's sibling file"
    )
    export_parser.add_argument(
        "--cut", help="Omit to infer from program's sibling .cut file"
    )
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
        "skills",
        help="Manage the packaged agent skills (Claude Code, GitHub Copilot)",
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
            "Install the packaged agent skills (mockymock, cobol-analysis, "
            "cobol-test) so a Claude Code or GitHub Copilot session can use them"
        ),
    )
    skills_install_parser.add_argument(
        "--project",
        action="store_true",
        help=(
            "Install into the current directory (./.claude/skills/<name>, "
            "or ./.github/skills/<name> for copilot) instead of the home "
            "directory"
        ),
    )
    skills_install_parser.add_argument(
        "--target",
        default="claude",
        # Literal rather than skills_cmd.TARGETS: see the deferred-import
        # rule; test_cli_skills.py pins the two together.
        choices=["claude", "copilot", "all"],
        help=(
            "Which assistant to install for: claude (~/.claude/skills, the "
            "default), copilot (GitHub Copilot: ~/.copilot/skills) or all"
        ),
    )
    skills_install_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing install at the target path",
    )
    skills_install_parser.add_argument(
        "--skill",
        action="append",
        help=(
            "Install only this skill (repeatable): mockymock, cobol-analysis "
            "or cobol-test. Default: all three"
        ),
    )
    skills_install_parser.set_defaults(func=_cmd_skills_install)

    skills_plugin_parser = skills_subparsers.add_parser(
        "plugin",
        help=(
            "Write the cobol-testing Claude Code plugin as a local "
            "marketplace, for `/plugin marketplace add <dir>` without GitHub"
        ),
    )
    skills_plugin_parser.add_argument(
        "directory",
        nargs="?",
        help="Where to write it (default: ~/.mockymock/claude-plugin)",
    )
    skills_plugin_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an earlier export in that directory",
    )
    skills_plugin_parser.set_defaults(func=_cmd_skills_plugin)

    skills_mode_parser = skills_subparsers.add_parser(
        "mode",
        help=(
            "Show (or set) how much the AI assistant checks in while it "
            "builds a suite"
        ),
    )
    skills_mode_parser.add_argument(
        "--set",
        metavar="MODE",
        default=None,
        # Not `choices=MODES`: that would need mockymock.cli.ai_mode
        # imported at parser-build time, and build_parser() runs on every
        # invocation including --help/--version. The valid set is spelled
        # out here instead and validated in _cmd_skills_mode;
        # tests/unit/test_cli_skills.py pins this text against MODES so the
        # two can't drift.
        help=(
            "Persist the mode to mockymock.toml: hands-on (propose first, "
            "wait for a yes), guided (narrate every step, stop at the "
            "checkpoints; the default), hands-off (run the whole workflow, "
            "report once at the end)"
        ),
    )
    skills_mode_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the active mode and every mode's contract as JSON",
    )
    skills_mode_parser.set_defaults(func=_cmd_skills_mode)

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

    from mockymock.cli.config import ConfigError, load_config

    try:
        args._config = load_config()
    except ConfigError as exc:
        args._config = None
        # Only a subcommand that would actually read the config fails on
        # a malformed one. `collect`/`setup`/`dashboard`/... run on with
        # defaults, and `doctor` re-loads it itself to report the error
        # as a WARN check (that is the situation it exists to explain).
        consumes_config = (
            hasattr(args, "copybook_path") or hasattr(args, "seed")
        ) and args.func is not _cmd_doctor
        if consumes_config:
            if args.func is _cmd_collect and getattr(args, "json", False):
                import json

                # `collect --json` promises machine-readable stdout on
                # every failure (the VS Code extension parses it).
                print(json.dumps({"version": 1, "error": str(exc)}, indent=2))
            elif args.func is _cmd_fixtures:
                # `fixtures` keeps stdout JSON-only; errors go to stderr.
                print(str(exc), file=sys.stderr)
            else:
                print(str(exc))
            return 1

    from mockymock._lines import SourceEncodingError

    try:
        return args.func(args)
    except SourceEncodingError as exc:
        # A non-UTF-8 .cbl/.cut: one clean line in each command's own
        # error convention instead of a UnicodeDecodeError traceback.
        _print_command_error(args, str(exc))
        return 1


def _print_command_error(args: argparse.Namespace, message: str) -> None:
    """Print a fatal error the way `main`'s config-error path does:
    `collect --json` as a JSON error object on stdout (the VS Code
    extension parses it), `fixtures` on stderr (its stdout is JSON-only),
    everything else as a plain `mockymock <command>:` line on stdout."""
    if args.func is _cmd_collect and getattr(args, "json", False):
        import json

        print(json.dumps({"version": 1, "error": message}, indent=2))
    elif args.func is _cmd_fixtures:
        print(f"mockymock fixtures: {message}", file=sys.stderr)
    else:
        print(f"mockymock {args.command}: {message}")


if __name__ == "__main__":
    sys.exit(main())
