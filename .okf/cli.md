---
type: Module
title: CLI
description: argparse entry point (setup, generate, run) that orchestrates the splicer, GnuCOBOL runtime, and report formatters.
tags: [cli, entrypoint]
timestamp: 2026-07-06T00:00:00Z
---

# Overview

`mockymock/cli/main.py` is the single argparse-based entry point (`prog="mockymock"`,
`--version` from `mockymock.__version__`). It defines three subcommands —
`setup`, `generate`, `run` — each wired via `set_defaults(func=...)` and
dispatched from `main()`. All heavy imports (`cobolparser`, `mockymock.analysis`,
`mockymock.splicer`, `mockymock.runtime`, `mockymock.dsl`, `mockymock.report`) are
deferred into each `_cmd_*` function body rather than imported at module top —
so `mockymock --version` / `--help` stay fast and don't require Docker or a
parser install to resolve.

```
mockymock setup     -> runtime.docker_toolchain only (build image, start container)
mockymock generate  -> parse -> analysis.mock_surface -> dsl.generator  (no Docker)
mockymock run       -> parse -> analysis -> dsl.parser -> splicer -> runtime -> report
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

1. Read `program`; if `--copybook-path` given (repeatable), run
   `expand_copybooks` first and use the expanded source from then on.
2. `parse_cobol(raw_source, filename=...)` — on parse failure, print each error
   and exit 1 (never reaches analysis).
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

## `mockymock run <program> --cut PATH [--junit-xml PATH] [--copybook-path DIR ...]`

The full pipeline: parse, analyze, refuse-or-splice, compile in Docker, run,
report. This is the only subcommand requiring the GnuCOBOL container.

Flow (`_cmd_run`), in strict order (each step's ordering is load-bearing):

1. `docker_toolchain.ensure_toolchain()` — brings the container up if needed
   (so `mockymock setup` is optional before `run`). `DockerNotAvailableError`
   -> print and exit 1.
2. Read `program`, apply `--copybook-path` expansion same as `generate`.
3. `parse_cobol` -> `check_whole_program(result)` refusals are printed
   regardless of parse success, but if `result.success` is false the command
   exits 1 right after (parse errors take priority even over whole-program
   refusal messages already printed).
4. `check_unresolved_copybooks(raw_source)` — same refusal gate as `generate`.
5. Parse the `.cut` file: `parse_cut(Path(args.cut).read_text())` -> `suite`.
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
17. `parse_stdout(executed.stdout)` -> `suite_result`; `format_console(...)`
    printed always; `format_junit_xml(...)` written to `--junit-xml` if given.
18. Exit 0 only if `suite_result.all_passed`.

# Gotchas

**`transform_data_division_exec` is called twice, and the first call's return value is intentionally thrown away** (`_cmd_run`, step 9 vs 11). The first pass exists purely to surface `EXEC SQL INCLUDE SQLCA` refusal reasons *before* any splicing happens; running the real transform that early would shift line numbers/spans that `splice_program` and the boundary/nested-site analysis depend on. Any future edit that tries to "simplify" this into one call will silently break splice-target alignment.

**Refusal checks are cumulative, not fail-fast, within a single gate.** `check_test_case` loops over every test case and only returns/exits after checking all of them, so users get every refusal reason in one invocation. But *between* gates (`check_whole_program` -> parse success -> `check_unresolved_copybooks` -> `check_nested_exec` -> `transform_data_division_exec` precheck -> `check_test_case`), the command exits at the first gate that fires — later gates never run if an earlier one refuses.

**`annotate_nested_sites` ordering is load-bearing in both `generate` and `run`.** It must run before anything inspects `surface.boundary_sites` for nested spliceability (`_report_unsupported_boundaries` in `generate`; every refusal check and `splice_program` in `run`). An unannotated nested site is indistinguishable from an unspliceable one, so calling this late produces false-positive refusals.

**`_insert_driver` matches section/division headers by exact-prefix string match on the stripped, uppercased line** (`WORKING-STORAGE SECTION`, `PROCEDURE DIVISION`) and inserts only at the first match. A program with unusual formatting where these headers aren't isolated on their own line (unlikely post `normalize_fixed_format`, but not structurally prevented) would silently fail to get the driver inserted.

# See Also

- [runtime](runtime.md)
- [report](report.md)
- [dsl](dsl.md)
