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

## Gotchas worth knowing before you start

Each of these is explained in full in `.okf/cli.md`'s own Gotchas section
(or the module doc named) -- read that before touching the code it
covers; this list exists so you know to look, not as a substitute.

- `build_parser()` must not import anything a `_cmd_*` body needs. See
  `.okf/cli.md`'s Gotchas section, first bullet.
- `annotate_nested_sites` ordering is load-bearing in both `generate` and
  `run`. See `.okf/cli.md`'s Gotchas section, third bullet, and
  `.okf/splicer.md`.
- `transform_data_division_exec` is deliberately called twice in
  `_cmd_run`. See `.okf/cli.md`'s Gotchas section, second bullet.
- Refusal checks are cumulative within one gate, fail-fast between gates.
  See `.okf/cli.md`'s Gotchas section, fourth bullet.
- `mockymock lint` never importing `docker_toolchain` is a structural
  guarantee, tested directly. See `.okf/cli.md`'s "`mockymock lint`"
  subsection.

## Before you start

1. Read `.okf/index.md`, then the specific module doc(s) for what you're
   touching.
2. Check `.okf/testing.md` for how the two test tiers are organized and
   `docs/` for the design doc of the feature you're extending (most
   non-trivial features have one, named
   `docs/YYYY-MM-DD-<topic>-design.md`).
3. After the change, update the matching `.okf/` concept file(s) (refresh
   body + `timestamp`) and append a dated entry to `.okf/log.md`.
