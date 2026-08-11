---
name: mockymock-dev
description: Use when making changes to mockymock's own source (CLI, DSL parser, splicer, analysis, runtime, report, debug adapter) -- orients into the .okf/ knowledge bundle and names the load-bearing invariants that don't show up from reading one file in isolation.
---

# mockymock contributor orientation

mockymock's own knowledge lives in `.okf/`, not in this file. Read
[`.okf/index.md`](../../../.okf/index.md) before any non-trivial change --
it links to every module's own doc (DSL, analysis, splicer, runtime,
report, CLI, testing, coverage, dashboard, publishing). This file is a
router plus a list of gotchas worth knowing before you start, not a
replacement for those docs.

## Module map (entry -> pipeline)

`mockymock/cli/main.py` is the single argparse entry point. Every
subcommand defers its heavy imports into its own `_cmd_*` function body --
`mockymock --version`/`--help` must stay fast and Docker-free. The
pipeline most subcommands share:

```
parse (cobolparser) -> analyze (mock_surface: CALL/file-I-O/EXEC SQL·CICS·DLI/ACCEPT)
   -> splice (dsl.parser's parsed .cut + boundary sites -> instrumented COBOL)
   -> runtime (Docker-only GnuCOBOL compile/run)
   -> report (__MOCKYMOCK__ stdout protocol -> console/JUnit/JSON)
```

See `.okf/dsl.md`, `.okf/analysis.md`, `.okf/splicer.md`,
`.okf/runtime.md`, `.okf/report.md`, `.okf/cli.md` for each stage.

## Gotchas that don't show up from reading one file

- **`build_parser()` may not import a `_cmd_*` body's dependencies.** It
  runs on every invocation including `--help`. `mockymock dashboard`
  regressed this once (importing `web.server` for a port default pulled
  in `docker_toolchain`); `test_cli_dashboard.py`'s
  `test_building_the_parser_does_not_import_the_docker_toolchain` pins it.
- **`annotate_nested_sites` must run before anything inspects
  `surface.boundary_sites` for nested spliceability** -- in both
  `generate` and `run`. An unannotated nested site looks unspliceable by
  construction; calling this late produces false refusals.
- **`transform_data_division_exec` is called twice in `_cmd_run`**: once
  to precheck `SQLCA` refusal reasons (return value discarded), once for
  real after splicing (splicing shifts line numbers/spans the first call
  would otherwise have invalidated). Collapsing this into one call
  silently breaks splice-target alignment.
- **Refusal checks are cumulative within one gate, fail-fast between
  gates.** `check_test_case` loops every test case before exiting, so a
  user sees every problem in one run; but the command exits at the first
  *gate* (parse -> unresolved-copybook -> nested-exec -> ... ->
  check_test_case) that fires, so later gates never run.
- **Docker-dependent tests are opt-in, not opt-out.**
  `tests/integration/` needs a reachable Docker daemon and is skipped
  automatically when one isn't available; `tests/unit/` never touches
  Docker. Run `python -m pytest tests/unit -v` for a fast inner loop.
- **`mockymock lint` is a structural guarantee, not just a convention** --
  `_cmd_lint` must never import `mockymock.runtime.docker_toolchain`,
  tested by `tests/unit/test_checks.py`. `run`/`lint` share
  `run_static_checks` specifically so they can never disagree about what
  refuses.

## Before you start

1. Read `.okf/index.md`, then the specific module doc(s) for what you're
   touching.
2. Check `.okf/testing.md` for how the two test tiers are organized and
   `docs/` for the design doc of the feature you're extending (most
   non-trivial features have one, named
   `docs/YYYY-MM-DD-<topic>-design.md`).
3. After the change, update the matching `.okf/` concept file(s) (refresh
   body + `timestamp`) and append a dated entry to `.okf/log.md`.
