"""`mockymock lint`: static checks of a .cut file (or a directory of them)."""

from __future__ import annotations

import argparse
from pathlib import Path

from mockymock._lines import read_utf8_source
from mockymock.cli._common import (
    _apply_config_to_args,
    _layout,
    _report_broken_claims,
    _resolve_program_and_cut,
    _several_suites,
)


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
        read_program_line,
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
    broken_claims = 0
    # --case/--tag over several suites: each suite is linted for the selected
    # cases it has, a suite with none is skipped, and only a name or tag no
    # suite has is an error.
    case_names = list(getattr(args, "case", None) or [])
    tag_names = list(getattr(args, "tag", None) or [])
    selecting = bool(case_names or tag_names)
    matched_cases: set[str] = set()
    matched_tags: set[str] = set()
    not_selected = 0
    for cut_path in cut_files:
        try:
            program_path = resolve_program_path(None, cut_path, layout)
        except DiscoveryError as exc:
            unresolved.append(str(exc))
            if read_program_line(cut_path) is not None:
                broken_claims += 1
            continue
        sub_args = copy.copy(args)
        if selecting:
            selection = _lint_selection_in_suite(cut_path, case_names, tag_names)
            if selection is not None:
                cases, tags = selection
                if not cases and not tags:
                    not_selected += 1
                    continue
                sub_args.case, sub_args.tag = cases or None, tags or None
                matched_cases.update(cases)
                matched_tags.update(tags)
            else:
                matched_cases.update(case_names)
                matched_tags.update(tag_names)
        ran += 1
        sub_args.program = str(program_path)
        sub_args.cut = str(cut_path)
        print(f"== {cut_path} ==")
        exit_code = _cmd_lint(sub_args) or exit_code

    for reason in unresolved:
        print(f"mockymock lint: {reason}")
    missing = [
        f"no TESTCASE named {name!r} in any suite"
        for name in case_names
        if name not in matched_cases
    ] + [
        f"no TESTCASE carries tag {tag!r} in any suite"
        for tag in tag_names
        if tag not in matched_tags
    ]
    for problem in missing:
        print(f"mockymock lint: {problem}")
    skipped_note = (
        f", {not_selected} suite(s) without a selected TESTCASE skipped"
        if not_selected
        else ""
    )
    print(
        f"mockymock lint: {ran} suite(s) checked, {len(unresolved)} .cut "
        f"file(s) skipped (no program found){skipped_note}"
    )
    if ran == 0 or missing or _report_broken_claims("lint", broken_claims):
        return 1
    return exit_code


def _lint_selection_in_suite(
    cut_path: Path, case_names: list[str], tag_names: list[str]
) -> tuple[list[str], list[str]] | None:
    """The `--case` names and `--tag`s that `cut_path`'s suite has; None
    when the suite can't be read or parsed (its own lint then says why)."""
    from mockymock.dsl.parser import CutParseError, parse_cut

    try:
        suite = parse_cut(read_utf8_source(cut_path))
    except (OSError, UnicodeDecodeError, CutParseError):
        return None
    names = {case.name for case in suite.test_cases}
    tags = {tag for case in suite.test_cases for tag in case.tags}
    return (
        [name for name in case_names if name in names],
        [tag for tag in tag_names if tag in tags],
    )


def _cmd_lint(args: argparse.Namespace) -> int:
    """Run every static refusal check with zero Docker dependency. This
    function must never import mockymock.runtime.docker_toolchain -- that
    structural guarantee (not just documentation) is what makes `lint`
    usable in editors, pre-commit hooks, and CI lanes with no daemon."""
    from mockymock.analysis.assertion_labels import orphan_label_warnings
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
    # --case/--tag scope the per-case refusals to the selection, exactly as
    # `debug --case` and `run --case` do, so a refusal in one TESTCASE no
    # longer fails a lint of another (issue: vscode#95's debug preflight).
    result = run_static_checks(
        source_path,
        cut_path,
        args.copybook_path,
        case_names=getattr(args, "case", None),
        tag_names=getattr(args, "tag", None),
    )
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
    warnings = list(result.warnings)
    try:
        lint_cut_text: str | None = read_utf8_source(cut_path)
    except (OSError, UnicodeDecodeError):
        lint_cut_text = None
    warnings += no_assertion_warnings(suite, lint_cut_text) if suite is not None else []
    try:
        warnings += orphan_label_warnings(read_utf8_source(cut_path))
    except (OSError, UnicodeDecodeError):
        pass  # an unreadable .cut is already reported as a problem
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
