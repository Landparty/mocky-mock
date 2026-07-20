---
type: Module
title: CLI
description: argparse entry point (setup, generate, run, lint, collect) that orchestrates the splicer, GnuCOBOL runtime, and report formatters.
tags: [cli, entrypoint]
timestamp: 2026-07-07T00:00:00Z
---

# Overview

`mockymock/cli/main.py` is the single argparse-based entry point (`prog="mockymock"`,
`--version` from `mockymock.__version__`). It defines five subcommands —
`setup`, `generate`, `run`, `lint`, `collect` — each wired via `set_defaults(func=...)` and
dispatched from `main()`. All heavy imports (`cobolparser`, `mockymock.analysis`,
`mockymock.splicer`, `mockymock.runtime`, `mockymock.dsl`, `mockymock.report`) are
deferred into each `_cmd_*` function body rather than imported at module top —
so `mockymock --version` / `--help` stay fast and don't require Docker or a
parser install to resolve.

```
mockymock setup     -> runtime.docker_toolchain only (build image, start container)
mockymock generate  -> parse -> analysis.mock_surface -> dsl.generator  (no Docker)
mockymock run       -> cli.checks (static) -> splicer -> runtime -> report
mockymock lint      -> cli.checks only  (no Docker, structural guarantee)
mockymock collect   -> dsl.parser only  (no Docker, no .cbl needed)
```

If no subcommand is given, `main()` prints help and returns 1 (`args` has no
`func` attribute).

# Subcommands

## `mockymock setup`

No arguments. Orchestrates only `mockymock.runtime.docker_toolchain`:

1. `docker_toolchain.ensure_toolchain()` — builds the GnuCOBOL image and starts
   the `mockymock-cobc` container if not already running.
2. `docker_toolchain.cobc_version()` — printed for confirmation.

On `DockerNotAvailableError`, prints `mockymock setup: <exc>` and exits 1.
Optional in normal workflows: `mockymock run` calls `ensure_toolchain()` itself,
so `setup` exists mainly for a fast up-front check / CI warm-up.

## `mockymock generate <program> [-o/--output PATH] [--copybook-path DIR ...]`

Scaffolds a starter `.cut` test file from a COBOL program. Does **not** touch
Docker/GnuCOBOL — pure parse-and-analyze.

Flow (`_cmd_generate`):

1. Check `program` exists (`_check_input_files` -- clean `no such file`
   message, exit 1, no traceback), then read it; if `--copybook-path`
   given (repeatable), run
   `expand_copybooks` first and use the expanded source from then on.
   `check_expansion_warnings(expansion)` refuses (EXPANSION_WARNING, exit 1)
   on a lossy copybook decode before the corrupted text is ever parsed.
2. `parse_cobol(raw_source, filename=...)` — on parse failure, print each error
   and exit 1 (never reaches analysis). On a successful parse,
   `check_whole_program(result)` still refuses (PARSE_WARNING, exit 1) if
   `ParseResult.warnings` reports dropped statements — a scaffold built from
   an incomplete AST would silently miss boundaries.
3. `check_unresolved_copybooks(raw_source)` — a **refusal** check run even
   though the program parsed; any reason printed as
   `mockymock generate: refused (<code>): <message>` and exit 1.
4. `analyze(result.ast)` -> `mock_surface` (the boundary-site inventory).
5. `normalize_fixed_format` the source, then `annotate_nested_sites` +
   `collect_scope_map` to mark which nested boundary statements are
   spliceable — this must run before `scaffold_cut` so the generated `.cut`
   only proposes cases that `run` will actually accept.
6. `scaffold_cut(program_name, surface)` builds the `.cut` text; written to
   `--output` or `<program>.cut` (suffix-swapped) by default.
7. Prints a `wrote N test case(s) -> path` summary, then
   `_report_unsupported_boundaries(surface)`.

`_report_unsupported_boundaries` is the only non-trivial logic in this module:
it walks `surface.boundary_sites` and names every site that stays unmockable —
either `site.category is None` (uncategorized boundary, e.g. SORT/MERGE
family or an identifier-less dynamic CALL) or `site.nested and site.span is
None` (a nested site the splicer couldn't isolate, printed with
`site.unspliceable_reason`). This list is purely informational at `generate`
time — the scaffold is emitted regardless — but it documents exactly which
test cases `run` will later refuse if a case's PERFORM reaches one of these
sites. Comment in the source explicitly frames this as "so the scaffold is
never mistaken for complete coverage of the program's outputs."

## `mockymock run <program> --cut PATH [--junit-xml PATH] [--json-report PATH] [--case NAME ...] [--tag TAG ...] [--copybook-path DIR ...] [--keep-sandbox] [--verbose] [--coverage] [--coverage-out PATH] [--coverage-json PATH]`

The full pipeline: parse, analyze, refuse-or-splice, compile in Docker, run,
report. This is the only subcommand requiring the GnuCOBOL container.

Since the lint extraction (docs/2026-07-18-cut-lint-command-design.md), every
pre-toolchain check (steps 2-10 below) lives in
`mockymock/cli/checks.py::run_static_checks` and runs **before**
`ensure_toolchain()` — a bad `.cut`/`.cbl` fails fast with the real problem
even when Docker is down. `run` and `lint` share this function so they can
never disagree about what refuses.

Flags beyond the pipeline inputs:

- `--junit-xml PATH` — write `format_junit_xml(...)` there after a run that
  reaches execution (refusals/compile failures exit earlier and write no
  XML). Each `<testcase>` carries `classname="<suite name>"`.
- `--json-report PATH` — write `report.json_report`'s machine-readable run
  report: per-case status (`passed`/`failed`/`crashed`/`not_run`), `.cut`
  line numbers for cases and failing EXPECT/VERIFY directives,
  expected/actual split into fields, tags. Built for editor integrations
  (the VS Code extension).
- `--case NAME` (repeatable) / `--tag TAG` (repeatable) — run only the named
  or tagged TESTCASEs (union when both given). Selection happens in
  `run_static_checks` before any per-case refusal check, so a refused
  sibling case no longer blocks running a clean one. An unknown name/tag is
  a static problem listing what is available. The suite still runs as ONE
  compile + binary — just with only the selected cases spliced in.
- `--coverage-json PATH` (implies `--coverage`) — write machine-readable
  coverage remapped onto the ORIGINAL `.cbl`'s line numbers via
  `report.coverage.map_coverage_to_original` (difflib alignment
  instrumented -> normalized -> original; splicer-inserted lines are
  excluded, so it answers "which of MY lines ran").
- `--keep-sandbox` — never delete the sandbox directory; its path is
  printed at the start of the run for inspection.
- `--verbose` — on compile failure, print the path to the instrumented
  source. Implementation detail: this also forces sandbox retention through
  the context manager (the printed path must still exist when the user
  reads it), but the CLI explicitly removes the sandbox afterwards when the
  run got past compilation, so plain `--verbose` leaves no cruft on
  success.

Flow (`_cmd_run`), in strict order (each step's ordering is load-bearing):

0. `_check_input_files("mockymock run", program, cut)` — both paths must
   exist; each missing one prints a clean `mockymock run: no such file:`
   line and the command exits 1 **before** `ensure_toolchain()` runs, so a
   typo'd path never pays for (or tracebacks after) a multi-minute image
   build.
1. `docker_toolchain.ensure_toolchain()` — brings the container up if needed
   (so `mockymock setup` is optional before `run`); also recreates the
   container when its image tag is stale (see [runtime](runtime.md)).
   `DockerNotAvailableError` -> print and exit 1.
2. Read `program`, apply `--copybook-path` expansion same as `generate`.
   `check_expansion_warnings(expansion)` refuses (EXPANSION_WARNING, exit 1)
   on a lossy copybook decode before the corrupted text is ever parsed.
3. `parse_cobol` -> `check_whole_program(result)` refusals (PARSE_ERROR on
   a failed parse, PARSE_WARNING per `ParseResult.warnings` entry — dropped
   statements on an otherwise "clean" parse) are printed and any of them
   exits 1.
4. `check_unresolved_copybooks(raw_source)` — same refusal gate as `generate`.
5. Parse the `.cut` file: `parse_cut(cut_path.read_text())` -> `suite`.
   `CutParseError` is caught and printed as
   `mockymock run: invalid .cut file <path>: <line-numbered message>`,
   exit 1 — never a raw traceback.
6. `analyze(result.ast)` -> `surface`; normalize source to `lines`.
7. **`annotate_nested_sites` must run before any refusal check or splice looks
   at nested sites** (explicit comment in source) — unannotated nested sites
   are treated as refused by construction, so annotating late would produce
   false refusals.
8. `check_nested_exec(surface)` refusal gate.
9. `transform_data_division_exec(lines)` is called here **only to pre-check**
   refusal reasons (`SQLCA` synthesis issues) — the returned transformed lines
   are discarded (`_, data_exec_reasons = ...`). The actual transform is
   re-run *after* splicing, because it inserts/removes lines, which would
   otherwise shift the AST-derived statement spans the splicer depends on.
   This double-call-with-discard is the key non-obvious sequencing trap in
   this file.
10. `check_test_case(surface, result.ast, case)` for every case in the suite —
    any refusal sets `refused = True`; all cases are checked before exiting
    (so a user sees every problem in one run), then exit 1 if any fired.
11. `collect_boundaries(result.ast)`, `TallyRegistry(suite)`,
    `splice_program(lines, boundaries, surface, suite, registry)` — the actual
    source rewrite. Then `transform_data_division_exec(lines)` runs for real
    (its output is kept this time).
12. `reset_move_lines(result.ast)` + `build_driver(suite, reset_lines,
    registry)` build the test-driver artifact (WORKING-STORAGE fields +
    PROCEDURE DIVISION statements for the harness).
13. `_insert_driver(lines, artifact)` splices the driver in: WORKING-STORAGE
    additions go immediately after the `WORKING-STORAGE SECTION` header line;
    procedure lines go immediately after `PROCEDURE DIVISION` (matched via
    `line.strip().upper().startswith(...)`, first occurrence only — both
    insertions are one-shot via `inserted_ws`/`inserted_proc` flags).
14. Write the instrumented source into a fresh `sandbox_dir(root=docker_toolchain.WORK_ROOT)`
    as `<program-stem>.cbl` (LF newlines forced via `newline="\n"`).
15. `docker_toolchain.compile_source(...)` — on failure, print stderr and exit 1.
16. `docker_toolchain.run_binary(compiled.binary_path)` — executes inside the
    container.
17. `parse_stdout(executed.stdout)` -> `suite_result`. The binary's exit
    code is translated into `crash_detail` evidence for the formatters:
    exit 124 (TIMEOUT_EXIT_CODE) -> `"binary timed out (exit 124); see
    stderr below"`; any other nonzero exit -> `"binary exited with code
    <n>"`; exit 0 -> `None` (the formatters then fall back to the STOP RUN
    hypothesis for crashed cases — a reached STOP RUN exits 0).
    `format_console(suite_result, crash_detail=...)` is printed always;
    then, if `executed.stderr` is non-empty, it is printed under a
    `mockymock run: binary stderr:` header — this is how run_binary's
    exit-124 infinite-loop hint and libcob runtime aborts reach the user.
    `format_junit_xml(suite_result, crash_detail=...)` is written to
    `--junit-xml` if given.
18. Exit 0 only if `suite_result.all_passed` **and** `executed.exit_code
    == 0` — a nonzero binary exit after the SUMMARY line still fails the
    run.

## `mockymock lint <program> --cut PATH [--copybook-path DIR ...]`

Runs `run_static_checks` and nothing else: every refusal `run` would print,
with zero Docker dependency. `_cmd_lint` never imports
`mockymock.runtime.docker_toolchain` (structural guarantee, tested by
`tests/unit/test_checks.py`). Output: one `mockymock lint: <problem>` line
per problem plus a `N problem(s) found.` summary, exit 1; or
`mockymock lint: no problems found.`, exit 0. Built for editors (the VS Code
extension publishes these as diagnostics), pre-commit hooks, and CI lanes
without a daemon.

## `mockymock collect --cut PATH [--json]`

Parses the `.cut` file only (no `.cbl`, no Docker) and lists the suite and
test cases with 1-based line numbers and tags. `--json` emits the
machine-readable form (`{"version": 1, "cutFile", "suite": {name, line},
"cases": [{name, line, tags}]}`) the VS Code extension uses for
authoritative test discovery; a `CutParseError` yields `{"version": 1,
"error": "..."}` and exit 1.

# Gotchas

**`transform_data_division_exec` is called twice, and the first call's return value is intentionally thrown away** (`_cmd_run`, step 9 vs 11). The first pass exists purely to surface `EXEC SQL INCLUDE SQLCA` refusal reasons *before* any splicing happens; running the real transform that early would shift line numbers/spans that `splice_program` and the boundary/nested-site analysis depend on. Any future edit that tries to "simplify" this into one call will silently break splice-target alignment.

**Refusal checks are cumulative, not fail-fast, within a single gate.** `check_test_case` loops over every test case and only returns/exits after checking all of them, so users get every refusal reason in one invocation. But *between* gates (`check_whole_program` -> parse success -> `check_unresolved_copybooks` -> `check_nested_exec` -> `transform_data_division_exec` precheck -> `check_test_case`), the command exits at the first gate that fires — later gates never run if an earlier one refuses.

**`annotate_nested_sites` ordering is load-bearing in both `generate` and `run`.** It must run before anything inspects `surface.boundary_sites` for nested spliceability (`_report_unsupported_boundaries` in `generate`; every refusal check and `splice_program` in `run`). An unannotated nested site is indistinguishable from an unspliceable one, so calling this late produces false-positive refusals.

**`_insert_driver` matches section/division headers by exact-prefix string match on the stripped, uppercased line** (`WORKING-STORAGE SECTION`, `PROCEDURE DIVISION`) and inserts only at the first match. A program with unusual formatting where these headers aren't isolated on their own line (unlikely post `normalize_fixed_format`, but not structurally prevented) would silently fail to get the driver inserted.

# See Also

- [runtime](runtime.md)
- [report](report.md)
- [dsl](dsl.md)
- [coverage](coverage.md)
