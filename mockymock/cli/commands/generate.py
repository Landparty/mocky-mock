"""`mockymock generate`: scaffold (or `--fill`) a .cut file for a program."""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from pathlib import Path

from mockymock._lines import SourceEncodingError, read_utf8_source, split_source_lines
from mockymock.cli._common import (
    _apply_config_to_args,
    _check_input_files,
    _check_rows_non_negative,
    _default_output,
    _print_cics_eib_synthesis,
    _print_linkage_neutralization,
    _report_unsupported_boundaries,
    _warn_asserting_nothing,
    _write_report_file,
)
from mockymock.debugging_lines import activate_debugging_lines


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
    from mockymock.dsl.parser import (
        _END_MOCK_RE,
        _MOCK_BARE_RE,
        _MOCK_QUOTED_RE,
        _PERFORM_RE,
    )
    from mockymock.engine.checks import run_static_checks

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
    from mockymock.dsl.fixture_bundle import (
        FixtureBundle,
        UnsupportedBundleVersionError,
        load_fixture_bundle,
        load_fixture_bundle_file,
    )
    from mockymock.dsl.generator import ProgramContext, scaffold_cut
    from mockymock.project.discovery import copybook_not_found_hint
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
        from mockymock.dsl.call_arguments import fill_call_arguments
        from mockymock.dsl.entry_parameters import (
            add_entry_parameters,
            fixture_generator,
        )

        try:
            # A subprogram's USING parameters are its interface (#275): the
            # scaffold sets them and stubs what the program hands back.
            generator = fixture_generator(args.rows)
            cp_bundle = generator.generate_with_scenarios_from_file(
                str(source_path),
                mode=args.scenarios,
                seed=args.seed,
                copybook_paths=args.copybook_path,
            )
            bundle_data = add_entry_parameters(
                cp_bundle.to_dict(), str(source_path), args.copybook_path
            )
            # A CALL argument the layout index cannot hold (a 05-level
            # group, one table element) gets its fields from the DATA
            # DIVISION instead of no value at all.
            bundle_data, filled_arguments = fill_call_arguments(
                bundle_data, str(source_path), args.copybook_path
            )
            for line in filled_arguments:
                print(f"mockymock generate: note: {line}", file=sys.stderr)
            bundle = load_fixture_bundle(bundle_data)
        except Exception as exc:
            print(f"mockymock generate: fixture bundle generation failed: {exc}")
            # cobol-parser wraps the not-found error in a ProgramLayoutError;
            # the actionable hint applies to the cause just the same.
            if isinstance(exc, CopybookNotFoundError) or isinstance(
                exc.__cause__, CopybookNotFoundError
            ):
                print(copybook_not_found_hint(exc))
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
    source_location_map: dict[int, tuple[str, int]] = {}
    if args.copybook_path:
        # See _cmd_fixtures's identical guard on the same call for why
        # this can raise on realistic inputs (audit finding F6).
        try:
            expansion = expand_copybooks(
                raw_source,
                copybook_paths=args.copybook_path,
                preserve_source_locations=True,
            )
        except CopybookNotFoundError as exc:
            print(f"mockymock generate: {exc}")
            print(copybook_not_found_hint(exc))
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
        source_location_map = dict(expansion.source_location_map or {})
    raw_source = activate_debugging_lines(raw_source)
    result = parse_cobol(raw_source, filename=source_path.name)
    normalize_flow_targets(result.ast)
    if not result.success or result.ast is None:
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

    # See mockymock/engine/checks.py::run_static_checks for why PROCESS/CBL
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
    if bundle is not None and "THRU" in cut_text:
        cut_text = _main_line_or_bare(
            source_path,
            output_path,
            args,
            cut_text,
            lambda: scaffold_cut(
                program_name,
                surface,
                bundle,
                frozenset(placeholder_pairs),
                dataclasses.replace(program_context, main_line=False, _main_line={}),
            ),
        )
    case_count = cut_text.count("TESTCASE ")
    if case_count == 0 and bundle is None:
        # A suite with no TESTCASE runs as "0 run, 0 failed" and fails;
        # writing it and exiting 0 read as success (issue #275).
        print(
            f"mockymock generate: no test case to write -- no paragraph of "
            f"{source_path} touches a boundary to mock, so {output_path} was "
            f"not written. Write a TESTCASE by hand (PERFORM the paragraph, "
            f"EXPECT what it computes), or try --scenarios"
        )
        return 1
    if args.real:
        linked = _link_real_programs(args, cut_text, output_path)
        if linked is None:
            return 1
        cut_text = linked
    if (
        bundle is not None
        and getattr(args, "scenarios", None) == "all"
        and not getattr(args, "real_files", False)
        and not args.per_paragraph
    ):
        # A program that writes a file and reads it back (NIST's SQ / ST
        # programs) checks its own records: one case with the file real
        # runs those checks against what it wrote.
        from mockymock.dsl.real_file_suite import plan_real_files, round_trip_case

        try:
            plans, _notes = plan_real_files(result.ast, surface, self_built=True)
        except Exception:  # noqa: BLE001 - an extra case, never a failed generate
            plans = []
        cut_text = round_trip_case(cut_text, plans)
        if not args.real:
            from mockymock.dsl.real_file_suite import real_calls_case

            calls, callee_mocks = _sibling_subprograms(
                source_path, surface, program_name, args, output_path
            )
            cut_text = real_calls_case(cut_text, calls, callee_mocks)
        case_count = cut_text.count("TESTCASE ")
    if getattr(args, "real_files", False):
        from mockymock.dsl.real_file_suite import make_real_file_suite, plan_real_files

        if args.per_paragraph:
            print(
                "mockymock generate: --real-files needs scenario cases (each "
                "runs the program from its entry, OPENs included); drop "
                "--per-paragraph"
            )
            return 2
        plans, file_notes = plan_real_files(result.ast, surface)
        cut_text, data_files, more_notes = make_real_file_suite(
            cut_text,
            plans,
            str(program_name or source_path.stem),
            output_path,
            seed=args.seed or 0,
        )
        for note in [*file_notes, *more_notes]:
            print(f"mockymock generate: --real-files: {note}")
        for data_path, content in data_files.items():
            try:
                data_path.parent.mkdir(parents=True, exist_ok=True)
                data_path.write_bytes(content)
            except OSError as exc:
                print(f"mockymock generate: cannot write {data_path}: {exc}")
                return 1
    # Unlike run's auxiliary report flags, this file IS the deliverable:
    # a failed write is a failed command (same convention as export).
    if not _write_report_file("generate", "-o/--output", str(output_path), cut_text):
        return 1
    print(f"mockymock generate: wrote {case_count} test case(s) -> {output_path}")
    _warn_asserting_nothing("generate", cut_text, stubs_count=True)
    _note_pending_stubs("generate", cut_text)
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
    _report_unsupported_boundaries(surface, "generate", source_location_map)
    if bundle is None:
        # --per-paragraph writes one case per paragraph as a starting point
        # to prune, some of which are expected to be refused.
        return 0
    return _refuse_unusable_scaffold(source_path, output_path, args)


_SOURCE_SUFFIXES = (".cbl", ".CBL", ".cob", ".COB", ".cobol")


def _sibling_subprograms(
    source_path: Path,
    surface: object,
    program_name: str | None,
    args: argparse.Namespace,
    output_path: Path,
) -> tuple[dict[str, str], list[str]]:
    """The programs `source_path` CALLs statically (transitively) whose
    source sits next to it (`<NAME>.cbl`, `.cob`, ... in its folder) and
    that can be linked for real: (name -> path relative to the `.cut`,
    placeholder MOCK blocks for the boundaries of those programs), for
    `real_calls_case`."""
    from mockymock.analysis.real_programs import (
        PreparedReal,
        RealSpec,
        prepare_real_program,
    )
    from mockymock.dsl.generator import directive_snippet
    from mockymock.dsl.model import MockCategory

    found: dict[str, str] = {}
    prepared_all: list[PreparedReal] = []
    own = (program_name or source_path.stem).upper()
    todo = [surface]
    while todo:
        current = todo.pop()
        for site in getattr(current, "boundary_sites", []):
            if site.category is not MockCategory.CALL or getattr(site, "is_mq", False):
                continue
            name = str(site.keys[0] if site.keys else "").strip().upper()
            if not name or name == own or name in found:
                continue
            candidates = [
                source_path.parent / f"{stem}{suffix}"
                for stem in dict.fromkeys((name, name.lower()))
                for suffix in _SOURCE_SUFFIXES
            ]
            path = next((c for c in candidates if c.is_file()), None)
            if path is None:
                continue
            try:
                prepared, _reasons = prepare_real_program(
                    RealSpec(name, path.resolve(), 0), args.copybook_path
                )
            except Exception:  # noqa: BLE001 - an extra case, never a failed generate
                prepared = None
            if prepared is None:
                continue
            found[name] = Path(
                os.path.relpath(path.resolve(), output_path.resolve().parent)
            ).as_posix()
            prepared_all.append(prepared)
            todo.append(prepared.surface)
    # A program the entry CALLs that a real program CALLs too would be
    # spliced in the real one from the other cases' MOCK (with CAPTURE
    # targets only the entry declares): no real-calls case then.
    entry_calls = {
        str(site.keys[0]).strip().upper()
        for site in getattr(surface, "boundary_sites", [])
        if site.category is MockCategory.CALL and site.keys
    }
    for prepared in prepared_all:
        for site in prepared.surface.boundary_sites:
            if (
                site.category is MockCategory.CALL
                and site.keys
                and str(site.keys[0]).strip().upper() in entry_calls
            ):
                return {}, []
    mocks: list[str] = []
    for prepared in prepared_all:
        for site in prepared.surface.boundary_sites:
            if site.category is None or (
                site.category is MockCategory.CALL
                and any(key.upper() in found for key in site.keys)
            ):
                continue
            snippet = directive_snippet(
                site,
                prepared.surface,
                prepared.file_status_fields,
            )
            if snippet is not None:
                mocks.append(snippet)
    return found, mocks


def _link_real_programs(
    args: argparse.Namespace, cut_text: str, output_path: Path
) -> str | None:
    """`generate --real`: the scaffold rewritten into a load-module suite,
    or None (after printing why) when a subprogram cannot be linked."""
    from cobolparser import parse_cobol

    from mockymock.analysis.real_programs import RealSpec, prepare_real_program
    from mockymock.dsl.module_suite import RealLink, link_real_programs

    links: list[RealLink] = []
    for raw in args.real:
        path = Path(raw).resolve()
        if not path.is_file():
            print(f"mockymock generate: --real {raw}: no such file")
            return None
        try:
            text = read_utf8_source(path)
        except SourceEncodingError as exc:
            print(f"mockymock generate: --real {raw}: {exc}")
            return None
        name = getattr(parse_cobol(text, filename=path.name).ast, "program_name", "")
        if not name:
            print(f"mockymock generate: --real {raw}: no PROGRAM-ID found")
            return None
        prepared, reasons = prepare_real_program(
            RealSpec(str(name), path, 0), args.copybook_path
        )
        if prepared is None:
            for reason in reasons:
                print(f"mockymock generate: refused ({reason.code}): {reason.message}")
            return None
        links.append(RealLink(prepared))
    linked, notes = link_real_programs(cut_text, links, output_path.resolve())
    for note in notes:
        print(f"mockymock generate: {note}")
    return linked


def _note_pending_stubs(command: str, cut_text: str) -> None:
    """Name the cases that assert nothing yet but hold `*> STUB EXPECT`
    comments: `generate` leaves them out of its "asserts nothing" warning,
    while `lint` reports them as NO_ASSERTION until the stubs are recorded,
    so without this line the two counts disagree with no explanation."""
    from mockymock.dsl.parser import CutParseError, parse_cut
    from mockymock.engine.checks import stub_case_lines

    try:
        suite = parse_cut(cut_text)
    except CutParseError:
        return
    stubbed = stub_case_lines(cut_text, suite)
    pending: list[str] = []
    seen: set[int] = set()
    for case in suite.test_cases:
        if case.assertion_count or not case.line or case.line in seen:
            continue
        seen.add(case.line)
        if case.line in stubbed:
            pending.append(f'.cut line {case.line}: TESTCASE "{case.name}"')
    if not pending:
        return
    print(
        f"mockymock {command}: {len(pending)} test case(s) have no EXPECT yet, "
        "only `*> STUB EXPECT` comments; `mockymock lint` reports them as "
        "NO_ASSERTION until `mockymock run --record-expectations` turns the "
        "comments into EXPECTs:"
    )
    for label in pending:
        print(f"  {label}")


def _refused_cases(source_path: Path, cut_path: Path, cut_text: str, args) -> int:
    """How many of `cut_text`'s test cases `lint` refuses (all of them on a
    whole-program refusal), checked through a scratch copy at `cut_path`'s
    location."""
    from mockymock.engine.checks import run_static_checks

    scratch = cut_path.with_name(f".{cut_path.name}.main-line-check")
    try:
        scratch.parent.mkdir(parents=True, exist_ok=True)
        scratch.write_text(cut_text, encoding="utf-8")
        checked = run_static_checks(source_path, scratch, args.copybook_path)
    finally:
        scratch.unlink(missing_ok=True)
    cases = len(checked.suite.test_cases) if checked.suite is not None else 0
    if checked.problems:
        return max(cases, 1)
    return len(checked.unmocked_reasons)


def _main_line_or_bare(
    source_path: Path, cut_path: Path, args, main_line: str, bare
) -> str:
    """`main_line` (cases PERFORMing THRU the program's last paragraph,
    `ProgramContext.main_line_thru`) unless `lint` refuses more of its
    cases than of `bare()`'s, the same scenarios with a bare PERFORM of
    the entry. Running the whole main line reaches more of the program,
    and with it statements no generated MOCK can replace (NIST IX217A: a
    WRITE INVALID KEY with no END-WRITE), where the shorter case ran."""
    refused = _refused_cases(source_path, cut_path, main_line, args)
    if refused == 0:
        return main_line
    alternative = bare()
    if _refused_cases(source_path, cut_path, alternative, args) < refused:
        print(
            "mockymock generate: note: running the whole main line (PERFORM "
            "THRU the last paragraph) would reach statements lint refuses -- "
            "the cases PERFORM their entry paragraph alone instead",
            file=sys.stderr,
        )
        return alternative
    return main_line


def _refuse_unusable_scaffold(source_path: Path, cut_path: Path, args) -> int:
    """Lint what `generate` just wrote and fail on any refusal no MOCK
    block can fix (issue #231): `generate` knows the PERFORM target of every
    case it writes, so a happy-path case whose entry point reaches an
    unsafe STOP RUN (UNSUPPORTED_TERMINATOR_LAYOUT) is known to be unusable
    here, not only at the next `lint`/`run`. Mirrors `--fill`'s own closing
    check; UNMOCKED_* refusals are left to `generate --fill`."""
    from mockymock.engine.checks import run_static_checks

    checked = run_static_checks(source_path, cut_path, args.copybook_path)
    per_case = {
        f"refused ({r.code}): {r.message}"
        for reasons in checked.unmocked_reasons.values()
        for r in reasons
    }
    remaining: list[str] = []
    cases = checked.suite.test_cases if checked.suite is not None else []
    for index, reasons in sorted(checked.unmocked_reasons.items()):
        case = cases[index] if index < len(cases) else None
        where = (
            f'.cut line {case.line}: TESTCASE "{case.name}" '
            if case is not None and case.line
            else ""
        )
        remaining.extend(
            f"{where}refused ({r.code}): {r.message}"
            for r in reasons
            # An UNMOCKED_* refusal with no suggested MOCK is one no MOCK
            # can fix (a site that cannot be spliced where it stands).
            if not (r.code.startswith("UNMOCKED_") and r.suggested_fix)
        )
    remaining.extend(
        problem
        for problem in checked.problems
        if not problem.startswith("  ") and problem not in per_case
    )
    if not remaining:
        return 0
    for problem in remaining:
        print(f"mockymock generate: {problem}")
    print(
        f"mockymock generate: {cut_path} was written, but `lint` refuses it "
        f"for the reason(s) above -- no MOCK block can fix them",
        file=sys.stderr,
    )
    return 1
