"""Helpers shared by more than one `mockymock` subcommand: argument
and config resolution (`_resolve_program_and_cut`, `_apply_config_to_args`),
report-file writing, the console notes generate/run/debug/export all
print, and the driver-insertion splice (`_insert_driver*`) that puts the
generated test driver into a copy of the program under test."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from mockymock.analysis.flow_targets import ORIGINAL_ENTRY_PARAGRAPH
from mockymock.splicer.headers import (
    is_data_division,
    is_procedure_division,
    is_working_storage,
)

if TYPE_CHECKING:
    from mockymock.cli.config import MockymockConfig


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
        # --extra-copybook-path adds to whichever list won instead of
        # replacing it, so an editor can pass directories it found on its
        # own (zapp.yml, another extension's settings) without dropping
        # the project's cobol.yml / mockymock.toml list (vscode#130).
        extra = getattr(args, "extra_copybook_path", None) or []
        resolved = resolved + [path for path in extra if path not in resolved]
        if program_path is not None:
            from mockymock.cli.discovery import effective_copybook_paths

            resolved = effective_copybook_paths(program_path, resolved)
        from mockymock.cli.discovery import with_system_copybooks

        resolved = with_system_copybooks(_with_copybook_aliases(resolved, config))
        args.copybook_path = resolved
    if hasattr(args, "seed"):
        args.seed = resolve(args.seed, config.seed)


def _with_copybook_aliases(paths: list[str], config: MockymockConfig) -> list[str]:
    """`paths` plus, last, the staging directory that gives each copybook
    the search cannot match as written (`gttlbi0a.copy` for member
    GTTLBI0A) the name it does try -- see cli/copybook_aliases.py. Last,
    so a file that already matches anywhere in `paths` still wins."""
    from mockymock.cli.copybook_aliases import (
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
    from mockymock.cli.discovery import default_suite_path

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
    from mockymock.cli.checks import cases_asserting_nothing

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
    from mockymock.cli.checks import source_line_relabeler

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
    from mockymock.cli.discovery import find_suites

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
    lines = comment_out_comment_entries(lines)
    if getattr(artifact, "call_frame", False):
        lines = mark_recursive(lines)
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
        is_working_storage(lines, index)
        for index in range(_first_procedure_index(lines))
    )
    seen_data_division = False
    entry_check_at: int | None = None
    after_declaratives: bool | None = None
    header_open = False
    header_ws = False

    for index, line in enumerate(lines):
        if index == entry_check_at and _starts_unnamed_code(lines, index):
            # Statements straight after the PROCEDURE DIVISION header, with
            # no paragraph name of their own, would otherwise read as more
            # sentences of the last UT-TESTCASE paragraph -- the main line
            # (and its STOP RUN) ran after the last case and SUMMARY never
            # printed (issue #264). A header makes them a paragraph nothing
            # performs.
            extend([f"       {_ORIGINAL_ENTRY_PARAGRAPH}."])
        if not inserted_ws and not has_ws:
            if is_data_division(lines, index):
                seen_data_division = True
            elif (
                seen_data_division and _AFTER_WS_SECTION_RE.match(line)
            ) or is_procedure_division(lines, index):
                if not seen_data_division:
                    extend(["       DATA DIVISION."])
                extend(["       WORKING-STORAGE SECTION."])
                extend(ws_lines)
                inserted_ws = True
        result.append(line)
        if not inserted_ws and is_working_storage(lines, index):
            header_ws = True
        if header_ws and not inserted_ws and _ends_sentence(line):
            # After the header's period: `WORKING-STORAGE` / `SECTION.`
            # split over lines (see splicer.headers).
            extend(ws_lines)
            inserted_ws = True
        if not inserted_proc and is_procedure_division(lines, index):
            # Also a header whose words sit on separate lines
            # (`PROCEDURE` / `DIVISION` / `.`, NIST NC113M): missing it left
            # the program running its own main line outside every case.
            header_open = True
        if header_open and not inserted_proc and _ends_sentence(line):
            if after_declaratives is None:
                after_declaratives = _opens_declaratives(lines, index + 1)
            if after_declaratives and not _END_DECLARATIVES_RE.search(
                line.split("*>", 1)[0]
            ):
                # DECLARATIVES must open the PROCEDURE DIVISION: the driver
                # goes after `END DECLARATIVES.` (2026-11-03).
                continue
            # After the header's period, not its first line: a header
            # wrapped onto later lines (`PROCEDURE DIVISION` / `USING
            # LK-A.`) had the driver spliced into it (cobc: syntax error).
            extend([""])
            extend(artifact.procedure_lines)
            inserted_proc = True
            entry_check_at = index + 1
    if inserted_proc:
        _insert_end_of_program_trap(
            result, inserted, program_end=getattr(artifact, "program_end", False)
        )
    return result, inserted


_PROGRAM_ID_RE = re.compile(
    r'(PROGRAM-ID\s*\.\s*)("[^"]*"|\'[^\']*\'|[A-Z0-9][A-Z0-9_-]*)(\s*\.)',
    re.IGNORECASE,
)


_PROGRAM_ID_NAME_LINE_RE = re.compile(
    r'^(\s*)("[^"]*"|\'[^\']*\'|[A-Z0-9][A-Z0-9_-]*)(\s*\.)', re.IGNORECASE
)


def mark_recursive(lines: list[str]) -> list[str]:
    """`lines` with the first PROGRAM-ID marked `IS RECURSIVE`: a
    call-frame driver CALLs the program's own entry for every case
    (`driver.call_frame_lines`), and a program that is not RECURSIVE may
    not be CALLed while it runs. An INITIAL or already RECURSIVE program
    is left as it is."""
    result = list(lines)
    for index, line in enumerate(lines):
        code = line.split("*>", 1)[0]
        if "PROGRAM-ID" not in code.upper():
            continue
        if re.search(r"\b(RECURSIVE|INITIAL)\b", code, re.IGNORECASE):
            return result
        if _PROGRAM_ID_RE.search(line):
            result[index] = _PROGRAM_ID_RE.sub(r"\1\2 IS RECURSIVE\3", line, count=1)
            return result
        # `PROGRAM-ID.` with the name on a line of its own (NIST IC222A).
        for after in range(index + 1, min(index + 4, len(lines))):
            following = lines[after].split("*>", 1)[0]
            if not following.strip():
                continue
            if re.search(r"\b(RECURSIVE|INITIAL)\b", following, re.IGNORECASE):
                return result
            result[after] = _PROGRAM_ID_NAME_LINE_RE.sub(
                r"\1\2 IS RECURSIVE\3", lines[after], count=1
            )
            return result
        return result
    return result


_DECLARATIVES_RE = re.compile(r"^\s*DECLARATIVES\s*\.", re.IGNORECASE)


_END_DECLARATIVES_RE = re.compile(r"\bEND\s+DECLARATIVES\s*\.", re.IGNORECASE)


def _opens_declaratives(lines: list[str], start: int) -> bool:
    """Whether the first code line at or after `start` is `DECLARATIVES.`."""
    for line in lines[start:]:
        code = line.split("*>", 1)[0]
        if not code.strip() or (
            len(line) > 6 and line[6] in "*/" and not line[:6].strip()
        ):
            continue
        return _DECLARATIVES_RE.match(code) is not None
    return False


#: An IDENTIFICATION DIVISION paragraph whose body is a comment-entry.
_COMMENT_ENTRY_RE = re.compile(
    r"^(\s*)(AUTHOR|INSTALLATION|DATE-WRITTEN|DATE-COMPILED|SECURITY|REMARKS)" r"\s*\.",
    re.IGNORECASE,
)


def comment_out_comment_entries(lines: list[str]) -> list[str]:
    """`lines` with the continuation lines of every comment-entry (`AUTHOR.`
    / `INSTALLATION.` / ... followed by free text in Area B, NIST SG101A's
    `FEDERAL COMPILER TESTING CENTER.`) turned into `*>` comments, line for
    line. A fixed-format compiler ends a comment-entry at the next Area A
    word; in the free-form source mockymock compiles, cobc read the text
    as code. A continuation line is one indented deeper than its header,
    up to the first that is not; only the IDENTIFICATION DIVISION (before
    the first other DIVISION header) is looked at."""
    result = list(lines)
    header_indent: int | None = None
    for index, line in enumerate(lines):
        code = line.split("*>", 1)[0]
        if not code.strip():
            continue
        indent = len(code) - len(code.lstrip())
        if header_indent is not None and indent > header_indent:
            # Division headers too: NIST OBNC1M writes a whole program in
            # Area B of its SECURITY paragraph.
            if len(line) > 6 and line[6] in "*/" and not line[:6].strip():
                continue  # a fixed-format comment line already
            result[index] = "      *> " + line.strip()
            continue
        if re.search(r"\b(ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", code, re.I):
            break
        header_indent = None
        match = _COMMENT_ENTRY_RE.match(code)
        if match is not None:
            header_indent = len(match.group(1))
    return result


def _ends_sentence(line: str) -> bool:
    """Whether `line`'s code (before a `*>` comment) holds a period that
    ends a sentence."""
    return re.search(r"\.(?=\s|$)", line.split("*>", 1)[0]) is not None


def _insert_end_of_program_trap(
    result: list[str], inserted: set[int], program_end: bool = False
) -> None:
    """Put `driver.end_of_program_trap_lines()` after the program's last
    line of code: before its `END PROGRAM`, or at the end of the source.
    `inserted` is renumbered for the lines it pushes down. With
    `program_end` (`DriverArtifact.program_end`), the `UT-PROGRAM-END`
    paragraph a main-line case runs THRU goes first, so it ends the
    program's own last SECTION rather than the trap's."""
    from mockymock.splicer.driver import end_of_program_lines_for

    start = _first_procedure_index(result)
    at = len(result)
    for index in range(start, len(result)):
        # The end of this program's PROCEDURE DIVISION: its END PROGRAM, or
        # the first program nested in it (2026-11-03, NIST IC2xx).
        if _END_PROGRAM_RE.match(result[index]) or _ID_DIVISION_RE.match(result[index]):
            at = index
            break
    trap = end_of_program_lines_for(program_end)
    # A program may end on a sentence with no period (cobc accepts that at
    # the end of the source); the trap's header would then read as more of
    # that statement. Close it -- only then, as a redundant period warns.
    for line in reversed(result[start + 1 : at]):
        code = line.split("*>", 1)[0].rstrip()
        fixed_comment = len(line) > 6 and line[6] in "*/"
        if code.strip() and not fixed_comment and not code.lstrip().startswith("*"):
            if not code.endswith("."):
                trap = ["           ."] + trap
            break
    shifted = {i + len(trap) if i >= at else i for i in inserted}
    inserted.clear()
    inserted.update(shifted)
    inserted.update(range(at, at + len(trap)))
    result[at:at] = trap


#: The paragraph header `_insert_driver_with_origins` gives a PROCEDURE
#: DIVISION main line that has no paragraph name of its own; the parsed
#: program carries the same name (`name_unnamed_main_line`, #385).
_ORIGINAL_ENTRY_PARAGRAPH = ORIGINAL_ENTRY_PARAGRAPH


#: A paragraph or SECTION header: one word (or `<word> SECTION`) and a
#: period, optionally followed by the paragraph's first sentence.
_PROCEDURE_HEADER_RE = re.compile(
    r"^\s*(?P<name>[A-Z0-9][A-Z0-9-]*)(?:\s+SECTION(?:\s+\d+)?)?\s*\.(?:\s|$)",
    re.IGNORECASE,
)


#: One-word statements that look like a header: `EXIT.`, `GOBACK.`, ...
_HEADER_LOOKALIKE_VERBS = frozenset(
    {"CONTINUE", "EJECT", "EXIT", "GOBACK", "SKIP1", "SKIP2", "SKIP3"}
)


def _starts_unnamed_code(lines: list[str], index: int) -> bool:
    """Whether the first code line from `index` on (the line after the
    PROCEDURE DIVISION header) is a statement rather than a paragraph or
    SECTION header, DECLARATIVES, or END PROGRAM. A header missed here
    only costs an empty extra paragraph; a statement missed would run
    inside the last test case, so the check leans towards inserting.
    False when the header line itself had no period (a USING list still
    running onto the next lines: inserting there would split it)."""
    header = lines[index - 1].split("*>", 1)[0]
    if "." not in header:
        return False
    for line in lines[index:]:
        text = line.split("*>", 1)[0].strip()
        if not text:
            continue
        upper = text.upper()
        if upper.startswith(("DECLARATIVES", "END PROGRAM")):
            return False
        m = _PROCEDURE_HEADER_RE.match(text)
        return m is None or m.group("name").upper() in _HEADER_LOOKALIKE_VERBS
    return False


# Any whitespace may separate a header's two words (`PROCEDURE  DIVISION`,
# a tab): literal single-space checks missed them while cobc, cobolparser
# and the `has_ws` check accepted them, so the driver's fields or
# paragraphs were never inserted (issue #305).
_END_PROGRAM_RE = re.compile(r"^\s*END\s+PROGRAM\b", re.IGNORECASE)


_ID_DIVISION_RE = re.compile(r"^\s*(IDENTIFICATION|ID)\s+DIVISION\b", re.IGNORECASE)


#: DATA DIVISION sections that must come AFTER WORKING-STORAGE -- including a
#: LINKAGE SECTION header `splicer.linkage.neutralize` commented out, whose
#: items then belong to whatever section precedes them.
_AFTER_WS_SECTION_RE = re.compile(
    r"^\s*(?:\*>\s*)?(?:LOCAL-STORAGE|LINKAGE|COMMUNICATION|REPORT|SCREEN)"
    r"\s+SECTION\b",
    re.IGNORECASE,
)


def _first_procedure_index(lines: list[str]) -> int:
    for index in range(len(lines)):
        if is_procedure_division(lines, index):
            return index
    return len(lines)
