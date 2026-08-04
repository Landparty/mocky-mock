---
type: Module
title: CLI
description: argparse entry point (setup, generate, run, debug, mutate, lint, collect, dashboard, export) that orchestrates the splicer, GnuCOBOL runtime, and report formatters.
tags: [cli, entrypoint]
timestamp: 2026-08-04T00:00:00Z
---

# Overview

`mockymock/cli/main.py` is the single argparse-based entry point (`prog="mockymock"`,
`--version` from `mockymock.__version__`). It defines nine subcommands —
`setup`, `generate`, `run`, `debug`, `mutate`, `lint`, `collect`, `dashboard`, `export` — each wired via `set_defaults(func=...)` and
dispatched from `main()`. All heavy imports (`cobolparser`, `mockymock.analysis`,
`mockymock.splicer`, `mockymock.runtime`, `mockymock.dsl`, `mockymock.report`,
`mockymock.debug`, `mockymock.web`) are
deferred into each `_cmd_*` function body rather than imported at module top —
so `mockymock --version` / `--help` stay fast and don't require Docker or a
parser install to resolve.

```
mockymock setup     -> runtime.docker_toolchain only (build image, start container)
mockymock generate  -> parse -> analysis.mock_surface -> dsl.generator  (no Docker)
mockymock run       -> cli.checks (static) -> splicer -> runtime -> report
mockymock debug     -> cli.checks (static) -> splicer -> runtime (debug=True) -> debug.adapter (DAP over stdio)
mockymock mutate    -> mutation.operators (no Docker with --list) -> mutation.runner (per-mutant: cli.checks -> splicer -> runtime) -> mutation.report
mockymock lint      -> cli.checks only  (no Docker, structural guarantee)
mockymock collect   -> dsl.parser only  (no Docker, no .cbl needed)
mockymock dashboard -> web.server (loopback HTTP) -> runtime.status.probe()  (read-only Docker)
mockymock export    -> cli.checks (static) -> splicer -> cli.mainframe_export (no Docker)
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

## `mockymock run <program> --cut PATH [--junit-xml PATH] [--json-report PATH] [--case NAME ...] [--tag TAG ...] [--copybook-path DIR ...] [--keep-sandbox] [--verbose] [--coverage] [--coverage-out PATH] [--coverage-json PATH] [--trace] [--trace-json PATH] [--record-expectations]`

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
- `--trace` / `--trace-json PATH` — replay ONE test case's execution: the
  path it took through the original `.cbl` plus the mocks that fired in
  order. `--trace-json` implies `--trace` (the same relationship
  `--coverage-json` has to `--coverage`). **Refuses unless exactly one
  `--case` is selected and no `--tag`** — the suite runs as a single
  binary and the trace file is a separate stream from stdout carrying no
  case markers, so an unscoped trace cannot be attributed to one case.
  That refusal fires before `run_static_checks` and before
  `ensure_toolchain()`. Composes two channels: the executed path from
  GnuCOBOL's trace file, and the mock timeline from stdout — see
  [report](report.md) and docs/2026-07-21-debug-trace-design.md.
- `--record-expectations` — golden/characterization mode: run the suite,
  capture the real runtime value behind every `*> STUB EXPECT <name>`
  comment in the `.cut` file (see [dsl](dsl.md)), and rewrite the file in
  place with those stubs turned into real `EXPECT` lines. Best-effort and
  cumulative (a `recorded N, skipped M` summary prints, with a reason per
  skip); never touches a line that isn't a stub comment (a hand-written or
  previously-recorded `EXPECT` is never overwritten -- structurally, not by
  a tracked flag); never rewrites the file at all if nothing was recorded;
  does not change the run's exit code. Composes freely with
  `--case`/`--tag` (only stubs inside a selected case can record anything)
  and with every other flag above. See [analysis](analysis.md),
  [splicer](splicer.md), [report](report.md), and
  docs/2026-08-04-record-expectations-design.md for the full design.
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
10. `analyze_file_status_fields(result.ast)` -> `file_status_fields` (an
    ENVIRONMENT DIVISION FILE-CONTROL walk, separate from `analyze()`),
    then `check_test_case(surface, result.ast, case, file_status_fields)`
    for every case in the suite — any refusal sets `refused = True`; all
    cases are checked before exiting (so a user sees every problem in one
    run), then exit 1 if any fired. See [analysis](analysis.md).
11. `collect_boundaries(result.ast)`, `TallyRegistry(suite)`,
    `find_terminator_plans(...)`, `find_flow_mock_plans(...)`,
    `splice_program(lines, boundaries, surface, suite, registry,
    terminator_plans, flow_plans, file_status_fields)` — the actual source
    rewrite (`file_status_fields` flows through to
    `injector.build_site_dispatch`'s default-success/override status MOVE,
    see [splicer](splicer.md)). Then `transform_data_division_exec(lines)`
    runs for real (its output is kept this time).
12. `reset_move_lines(result.ast)` + `build_driver(suite, reset_lines,
    registry, record_targets)` build the test-driver artifact
    (WORKING-STORAGE fields + PROCEDURE DIVISION statements for the
    harness). `--record-expectations` only: immediately before this call,
    `cut_path.read_text()` + `analysis.stub_expectations.scan_stub_expectations(cut_text,
    suite)` scan for `*> STUB EXPECT` comments against the POST-filter
    `suite` (`--case`/`--tag` already applied above), grouped into
    `record_targets: dict[case_index, list[data_name]]` and passed through
    here -- omitted (`{}`) entirely when the flag isn't set, so ordinary
    `run` is unaffected. See [analysis](analysis.md), [splicer](splicer.md),
    and docs/2026-08-04-record-expectations-design.md.
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
    `--junit-xml` if given. `--record-expectations` only: right after the
    stderr print, `record_rewrite.build_recording_report(stub_scan,
    suite_result)` then `rewrite_cut_text(cut_text, recording)` -- if the
    result isn't `None` (something was actually recorded), it's written
    back to `cut_path` and a `recorded N, skipped M` summary (with a
    reason per skip) is printed. See [report](report.md).
18. Exit 0 only if `suite_result.all_passed` **and** `executed.exit_code
    == 0` — a nonzero binary exit after the SUMMARY line still fails the
    run. **Unaffected by `--record-expectations`** — recording outcomes
    never change this; see the design doc's "Best-effort, cumulative
    reporting" section for why.

## `mockymock debug <program> --cut PATH --case NAME --dap-stdio [--copybook-path DIR ...]`

Starts an interactive Debug Adapter Protocol (DAP) session for a single
test case — breakpoints, stepping, a synthesized COBOL call stack, and
read-only variable inspection. See
docs/2026-07-22-dap-debugger-design.md and
docs/superpowers/plans/2026-07-22-dap-debugger-cli.md for the full design
and empirical basis (both were verified against a real container, not
just planned).

Unlike `run`'s trace/coverage flags, this is a real subcommand: a DAP
server is a fundamentally different, long-running mode, not "the same
pipeline plus an artifact." `--dap-stdio` is required — there is no
useful human-facing terminal mode for a DAP session, so `_cmd_debug`
refuses with a message pointing at the VS Code extension if it's absent.
Exactly one `--case` is required (same structural reason as `--trace`:
the suite compiles and runs as one binary, one execution stream).

`_cmd_debug` runs the same static-checks → splice pipeline as `_cmd_run`
(with `trace=False` always), then diverges: instead of `run_binary`, it
compiles with `compile_source(debug=True)` (`-g`) inside a `launch_session`
closure and hands that closure to a `DapAdapter`
(`mockymock/debug/adapter.py`) that speaks DAP JSON over stdio until the
client disconnects. The sandbox stays alive for the whole session (a
long-lived conversation), torn down only once `adapter.run()` returns.

`mockymock/debug/` modules, each independently unit-tested against real
captured MI transcripts and end-to-end tested against a live container
(`tests/integration/test_debug.py`):

- `gdb_session.py` — owns the long-lived `docker exec -i gdb
  --interpreter=mi2` subprocess; parses MI records (including treating any
  untagged line as the debuggee's own stdout); breakpoints; run/continue/
  step with the coalescing loop one COBOL statement's marker/body `#line`
  pair requires; `resolve_address` (temporary breakpoint insert/delete) for
  resolving a raw code address. `step`'s coalescing predicate requires
  being back in the instrumented `.cbl` file AND (when an
  `is_visible_line` callable is given, as `adapter.py` always does) the
  stopped line having an original-source counterpart — otherwise it keeps
  coalescing through splicer-inserted mock/driver statements (MOCK DLI
  bodies, test-case dispatch, tally/VERIFY checks), which live in the same
  instrumented file but have no original-line mapping. Without this, `next`
  could stop on one of those, and since the DAP layer can't show a line for
  it, the position displayed in the client froze across repeated Step Over
  clicks — indistinguishable from an infinite loop even though the program
  was progressing normally (see `log.md`).
- `line_map.py` — bidirectional original ↔ instrumented line mapping,
  built on `report/coverage.py`'s existing (one-directional)
  `build_original_line_map`.
- `variable_map.py` — COBOL name ↔ gdb expression, from the compiler's own
  `<name>.c.l.h` comment table (not gdb symbols, which don't exist for
  COBOL names, and not a byte-offset decoder). Decodes packed-decimal
  (COMP-3) and binary (COMP) values via GnuCOBOL's own `cob_field_attr`
  type/digits/scale, read live via MI.
- `call_stack.py` — synthesizes the COBOL paragraph/section call stack
  from GnuCOBOL's internal `frame_stack`, since gdb's own backtrace is
  always exactly one frame (`PERFORM` is a computed-goto, not a real C
  call). `frame_stack[0]` is a sentinel, not a real caller — see the
  design doc's Empirical basis for why.
- `adapter.py` — the DAP server: `Content-Length`-framed JSON over
  injectable streams, `initialize`/`launch`/`setBreakpoints`/
  `configurationDone`/`threads`/`stackTrace`/`scopes`/`variables`/
  `evaluate`/`continue`/`next`/`stepIn`/`stepOut`/`disconnect`. `evaluate`
  backs the client's Watch panel, hover-inspect, and Debug Console — all
  three send the same DAP request — but only resolves plain COBOL
  identifiers already in `variable_table` (the same lookup `variables`
  uses); arithmetic/member-access expressions fail cleanly, not silently.

Not yet verified (flagged in the design doc, not blocking v1): group
items, `OCCURS` tables, `REDEFINES` in `variable_map.py`; deeper
`PERFORM`/`PERFORM THRU`/`GO TO` control flow in `call_stack.py`.

## `mockymock mutate <program> --cut PATH [--copybook-path DIR ...] [--list] [--timeout S] [--json-report PATH] [--fail-under PCT]`

Mutation testing (see docs/2026-07-29-mutation-testing-design.md).
`--list` prints the generated mutants and exits — pure
`mutation.operators`, no Docker. A real run baseline-checks the suite
(red/empty baseline aborts with exit 1: every verdict would be noise),
then for each mutant patches one original line and re-runs the exact
`run` pipeline (static checks → splice → compile → run) in its own
sandbox, classifying `killed` / `survived` / `timeout` (counts as a
kill; default 15 s) / `stillborn` (refusal or compile error — excluded
from the score). Console output streams one line per mutant, then lists
survivors with a `-`/`+` diff and the score
(killed+timeouts over scored). `--json-report` writes the full
machine-readable outcome; `--fail-under` exits 1 below the given
percentage. Boundary statements (mocked) and terminators (rewritten by
terminator plans) are never mutated — mutating them would test the
harness, not the program.

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

## `mockymock dashboard [--port N] [--no-browser]`

Serves the static status page on `127.0.0.1` (host not configurable) until
Ctrl-C, opening a browser unless `--no-browser`. Unlike `setup`, it is
**read-only** — it calls `runtime.status.probe()`, never
`ensure_toolchain()`, so a polling page can't trigger image builds. A taken
port yields `mockymock dashboard: could not serve on ...` and exit 1. Full
details in [dashboard](dashboard.md).

`--port`'s default is stored as `None` and resolved to
`web.server.DEFAULT_PORT` inside `_cmd_dashboard`, deliberately: reading
the constant at parser-build time would import `web.server` ->
`runtime.status` -> `runtime.docker_toolchain` (which reads the Dockerfile
at import to compute `IMAGE`) on every `mockymock --help`. See the Gotchas
below.

## `mockymock export <program> --cut PATH [-o/--output PATH] [--copybook-path DIR ...] [--case NAME ...] [--tag TAG ...]`

Writes the instrumented source to a file after running the same parse → static-checks → splice
pipeline as `run`, but without Docker or any GnuCOBOL step. The output is adjusted for compilation
under a real fixed-format (z/OS) COBOL compiler instead of GnuCOBOL-only: `PROCESS`/`CBL` directives
are preserved (where `run`/`lint` strip them), columns are restored to z/OS fixed-format discipline
(7-space prefix for Area A), and very-long generated `DISPLAY` statements that overflow column 72 are
wrapped into multiple lines. A provenance/disclaimer header is prepended, documenting that this is a
mock-only build (every boundary is either mocked or fails loudly; no real I/O executes) and listing
known GnuCOBOL-vs-IBM-COBOL gaps that a clean compile here does not rule out. Output path defaults
to `<program-stem>.mainframe.cbl` next to the input `.cbl`, matching `generate`'s suffix-swap convention.
If a line still exceeds column 72 after wrapping and column restoration -- most commonly, long `.cut`
MOCK body text (e.g. a `MOVE` statement) that `injector.py` re-indents past the limit when splicing it
in -- `export` refuses (`mockymock export: refused (COLUMN_OVERFLOW): ...`) and writes nothing.

Full design, including empirical validation of the wrapping algorithm and the three adjustments, lives in
[docs/2026-08-03-mainframe-export-command-design.md](../docs/2026-08-03-mainframe-export-command-design.md).

# Gotchas

**Nothing in `build_parser()` may import a `_cmd_*` body's dependencies.**
The deferred-import rule above is about `main()`'s hot path, but
`build_parser` runs on *every* invocation including `--help`/`--version`,
so an import there is strictly worse than one at module top would be for a
single command. `mockymock dashboard` regressed this once by importing
`web.server` for a port default;
`tests/unit/test_cli_dashboard.py::test_building_the_parser_does_not_import_the_docker_toolchain`
now pins it in a subprocess.

**`transform_data_division_exec` is called twice, and the first call's return value is intentionally thrown away** (`_cmd_run`, step 9 vs 11). The first pass exists purely to surface `EXEC SQL INCLUDE SQLCA` refusal reasons *before* any splicing happens; running the real transform that early would shift line numbers/spans that `splice_program` and the boundary/nested-site analysis depend on. Any future edit that tries to "simplify" this into one call will silently break splice-target alignment.

**Refusal checks are cumulative, not fail-fast, within a single gate.** `check_test_case` loops over every test case and only returns/exits after checking all of them, so users get every refusal reason in one invocation. But *between* gates (`check_whole_program` -> parse success -> `check_unresolved_copybooks` -> `check_nested_exec` -> `transform_data_division_exec` precheck -> `check_test_case`), the command exits at the first gate that fires — later gates never run if an earlier one refuses.

**`annotate_nested_sites` ordering is load-bearing in both `generate` and `run`.** It must run before anything inspects `surface.boundary_sites` for nested spliceability (`_report_unsupported_boundaries` in `generate`; every refusal check and `splice_program` in `run`). An unannotated nested site is indistinguishable from an unspliceable one, so calling this late produces false-positive refusals.

**`_insert_driver` matches section/division headers by exact-prefix string match on the stripped, uppercased line** (`WORKING-STORAGE SECTION`, `PROCEDURE DIVISION`) and inserts only at the first match. A program with unusual formatting where these headers aren't isolated on their own line (unlikely post `normalize_fixed_format`, but not structurally prevented) would silently fail to get the driver inserted.

# See Also

- [runtime](runtime.md)
- [report](report.md)
- [dsl](dsl.md)
- [coverage](coverage.md)
- [dashboard](dashboard.md)
