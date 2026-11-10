"""Helpers shared by more than one `mockymock` subcommand: argument
and config resolution (`_resolve_program_and_cut`, `_apply_config_to_args`),
report-file writing, and the console notes generate/run/debug/export all
print. The driver-insertion splice lives in `splicer.insertion`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mockymock.project.config import MockymockConfig


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
    from the config file main() loaded. See project/discovery.py."""
    from mockymock.project.discovery import project_layout

    return project_layout(getattr(args, "_config", None))


def _resolve_program_and_cut(
    command: str, args: argparse.Namespace
) -> tuple[Path, Path] | None:
    """Resolve exactly one (program, .cut) pair for a command that has
    both a `program` positional and a `--cut` flag, filling in whichever
    one is missing from its sibling by same-stem convention (see
    mockymock/project/discovery.py and docs/2026-09-15-cli-ergonomics-design.md).
    An explicit value for either always wins. Prints a clean, actionable
    error and returns None on any failure -- callers just `return 1`."""
    from mockymock.project.discovery import (
        DiscoveryError,
        resolve_cut_path,
        resolve_program_path,
    )

    program_arg = getattr(args, "program", None)
    cut_arg = getattr(args, "cut", None)
    if program_arg and program_arg.lower().endswith(".cut") and cut_arg is None:
        # `mockymock mutate PROG.cut`: the suite in the program's place, as
        # `run` already accepts. Take it as --cut and infer the program,
        # rather than "no .cut file found for PROG.cut".
        cut_arg, program_arg = program_arg, None
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
    [tool.mockymock], see mockymock/project/config.py) into `args` for
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
    from mockymock.project.config import (
        MockymockConfig,
        resolve,
        resolve_copybook_paths,
    )

    config: MockymockConfig = getattr(args, "_config", None) or MockymockConfig()
    if hasattr(args, "copybook_path"):
        resolved = resolve_copybook_paths(args.copybook_path, config)
        # --extra-copybook-path adds to whichever list won instead of
        # replacing it, so an editor can pass directories it found on its
        # own (zapp.yml, another extension's settings) without dropping
        # the project's cobol.yml / mockymock.toml list (vscode#130).
        extra = getattr(args, "extra_copybook_path", None) or []
        resolved = resolved + [path for path in extra if path not in resolved]
        if program_path is not None:
            from mockymock.project.discovery import effective_copybook_paths

            resolved = effective_copybook_paths(program_path, resolved)
        from mockymock.project.discovery import with_system_copybooks

        resolved = with_system_copybooks(_with_copybook_aliases(resolved, config))
        args.copybook_path = resolved
    if hasattr(args, "seed"):
        args.seed = resolve(args.seed, config.seed)


def _with_copybook_aliases(paths: list[str], config: MockymockConfig) -> list[str]:
    """`paths` plus, last, the staging directory that gives each copybook
    the search cannot match as written (`gttlbi0a.copy` for member
    GTTLBI0A) the name it does try -- see project/copybook_aliases.py. Last,
    so a file that already matches anywhere in `paths` still wins."""
    from mockymock.project.copybook_aliases import (
        DEFAULT_COPYBOOK_EXTENSIONS,
        stage_copybook_aliases,
    )

    extensions = config.copybook_extensions
    if extensions is None:
        extensions = DEFAULT_COPYBOOK_EXTENSIONS
    try:
        staged = stage_copybook_aliases(paths, config.copybook_aliases, extensions)
    except OSError as exc:
        # Aliasing is a convenience: a copylib that cannot be staged
        # leaves the search exactly as configured, and a member it would
        # have supplied still fails with the usual not-found hint.
        print(f"mockymock: could not stage copybook aliases: {exc}", file=sys.stderr)
        return paths
    if staged is None or str(staged) in paths:
        return paths
    return [*paths, str(staged)]


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
    whether a report file happened to be writable.

    A missing parent directory is created first, as pytest and maven do
    for `--junit-xml reports/junit.xml` in a fresh CI checkout, and a
    write that still fails is reported on stderr, not mixed into the
    test output on stdout (issue #257)."""
    try:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        print(
            f"mockymock {command}: could not write {flag} to {target}: {exc}",
            file=sys.stderr,
        )
        return False
    return True


def _save_result(
    command: str,
    cut_path: Path,
    program_path: Path,
    kind: str,
    content: str,
    args: argparse.Namespace,
    inputs: dict[str, object] | None = None,
) -> None:
    """Save a whole-suite run/coverage/mutation result in `.mockymock/` for
    `report --execute --mutate` to reuse (issue #352). Never fails the
    command: a read-only checkout only costs the reuse."""
    from mockymock.report.artifacts import save_result

    try:
        save_result(
            cut_path,
            program_path,
            kind,
            content,
            getattr(args, "copybook_path", None),
            inputs,
        )
    except OSError as exc:
        print(
            f"mockymock {command}: could not save the {kind} result for "
            f"'mockymock report' to reuse: {exc}",
            file=sys.stderr,
        )


def _default_output(args: argparse.Namespace, source_path: Path) -> Path:
    """-o/--output when given; else the layout's place for a new suite
    (`<tests>/<folder>/PROG[.<name>].cut`, see discovery.default_suite_path).
    The folders are created here so the write that follows can't fail on
    a missing tests/ subfolder."""
    if args.output:
        return Path(args.output)
    from mockymock.project.discovery import default_suite_path

    output = default_suite_path(source_path, _layout(args), getattr(args, "name", None))
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _distinct_case_count(cut_text: str) -> int:
    """How many cases `cut_text` holds, counted the way
    `cases_asserting_nothing` labels them (PROVIDER rows share their header
    line); 0 when the text does not parse."""
    from mockymock.dsl.parser import CutParseError, parse_cut

    try:
        suite = parse_cut(cut_text)
    except CutParseError:
        return 0
    return len({case.line or case.name for case in suite.test_cases})


def _warn_asserting_nothing(command: str, cut_text: str, *, stubs_count: bool) -> int:
    """Print one warning naming every case with nothing to assert (see
    `checks.cases_asserting_nothing`); returns how many there are."""
    from mockymock.engine.checks import cases_asserting_nothing

    empty = cases_asserting_nothing(cut_text, stubs_count=stubs_count)
    if not empty:
        return 0
    what = "no EXPECT, VERIFY or STUB EXPECT" if stubs_count else "no EXPECT or VERIFY"
    print(
        f"mockymock {command}: warning: {len(empty)} test case(s) assert "
        f"nothing ({what}), so they pass whatever the program does -- add an "
        f"EXPECT on what each one writes:"
    )
    for label in empty:
        print(f"  {label}")
    return len(empty)


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
    rebindings = getattr(plan, "rebindings", None) or []
    if applied and rebindings:
        names = ", ".join(r.item_name for r in rebindings)
        print(
            f"mockymock {command}: kept `SET ADDRESS OF` on {names} as a real "
            f"rebind (BASED, over its own storage at the start of each case) "
            f"-- every address it is set to is one the program itself takes"
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
                f"synthesized a 01 {block} WORKING-STORAGE group (referenced: {listed})"
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


def _report_unsupported_boundaries(
    surface, command: str = "generate", source_location_map=None
) -> None:
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
    This report covers the program, not one case: a `.cut` written later
    may reach a site through another PERFORM target. The cases `generate`
    writes itself are linted right after (`_refuse_unusable_scaffold`).

    `command` names the caller in the printed output -- `generate` (the
    default, and this function's original and still most common caller)
    or `export`, which shares the same `surface` inspection but must not
    print a `generate` prefix in its own console output.
    """
    from mockymock.analysis.mock_surface import _TERMINATOR_LABELS, is_answered_site

    findings: list[str] = []
    terminator_findings: list[str] = []
    for site in surface.boundary_sites:
        if is_answered_site(site):
            # Answered with CONTINUE by the splicer (issue #422).
            continue
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
    # Lines of the .cbl the user has open, not of the copybook-expanded
    # source (issue #241).
    from mockymock.engine.checks import source_line_relabeler

    relabel = source_line_relabeler(source_location_map)
    findings = [relabel(finding) for finding in findings]
    terminator_findings = [relabel(finding) for finding in terminator_findings]
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


def _several_suites(args: argparse.Namespace) -> list[Path] | None:
    """For `run`/`lint PROG.cbl` with no --cut: the program's suites when it
    has more than one (each then runs in turn, like the directory-wide
    mode), else None so the ordinary single-pair path handles it --
    including its error when there are none."""
    if args.program is None or args.cut is not None:
        return None
    from mockymock.project.discovery import find_suites

    program = Path(args.program)
    if not program.is_file():
        return None
    suites = find_suites(program, _layout(args))
    return suites if len(suites) > 1 else None


def _report_broken_claims(command: str, broken_claims: int) -> bool:
    """True (after saying so) when a skipped `.cut` declares a PROGRAM
    "..." line that no longer resolves (issue #303, option (b)): an
    explicit claim that is now broken is a renamed or moved program, and
    exiting 0 dropped its suite from a green CI build. A `.cut` whose
    program was only guessed from the folder is still just skipped."""
    if not broken_claims:
        return False
    print(
        f"mockymock {command}: {broken_claims} .cut file(s) name a PROGRAM "
        f"that does not exist -- failing"
    )
    return True
