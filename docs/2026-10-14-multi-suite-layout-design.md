# Several suites per program, suites under `tests/` (2026-10-14)

## Problem

A suite had to be `PROG.cut` in the same folder as `PROG.cbl`, so a
program had exactly one suite and tests could not live in their own
folder. Mainframe repos keep source in its own tree and want tests in
`tests/`, the way Maven, pytest and most ecosystems lay them out, and
they want more than one suite per program (happy path, error handling,
regressions).

## Design

A suite finds its program through one ordered lookup
(`mockymock/cli/discovery.py`, `resolve_program`). The first rule that
matches wins; an ambiguous match is an error naming every candidate.

1. **`PROGRAM "<path>"`** -- an optional line right after `TESTSUITE`,
   relative to the .cut file. Any file name works when it is present. A
   PROGRAM path that does not exist is an error, never a fall-through.
2. **Sibling** -- `<dir>/<base>.cbl` (or `.cob`, `.CBL`, `.COB`). The
   original rule; every existing suite keeps working.
3. **Mirror** -- a suite under the tests folder maps to the same relative
   folder under the source root: `tests/pay/PAYROLL.cut` ->
   `src/pay/PAYROLL.cbl`.
4. **Unique name** -- the only `<base>.cbl` under the source root.

`<base>` is the .cut file name up to its first dot, so `PAYROLL.cut` and
`PAYROLL.errors.cut` both belong to PAYROLL.

Layout (`ProjectLayout`): the root is the folder of the config file that
had the last word (else cwd). The tests folder is the config's
`test_root` when set, else `<root>/tests`. The source root is the new
`source_root` key, else `<root>/src` when that folder exists, else the
root. Both keys resolve against the file that
declares them and work in `cobol.yml`'s `mockymock:` section,
`mockymock.toml`, and `[tool.mockymock]`.

### Commands

- `generate` / `init` write to `<tests>/<folder>/PROG.cut` by default,
  mirroring the program's folder under the source root. They stay beside
  the program when it already has a `PROG.cut` there (that project uses
  the sibling layout) or lies outside the source root. `--name errors`
  writes `PROG.errors.cut`. `-o` still wins.
- `run PROG.cbl` / `lint PROG.cbl` with no `--cut` run every suite of the
  program when it has several. `debug`, `mutate`, `export` and `report`
  need one suite and say which `--cut` values exist.
- `mockymock suites [--json]` pairs every suite under the root with its
  program and the rule that matched (or the error). `mockymock suites
  PROG.cbl [--name N] --json` lists that program's suites and
  `newSuitePath`. Docker-free and parse-free; the VS Code extension pairs
  files with it instead of keeping its own copy of these rules.

## Backward compatibility

The sibling rule is step 2, with no deprecation. Every example under
`examples/` still pairs as a sibling. The only behavior change for an
existing project is where `generate`/`init` put a *new* suite for a
program that has none yet: `tests/...` instead of beside it.

## Not in this change

- Merging coverage across a program's suites, or scoring mutation testing
  against all of them together (`mutate` takes one `--cut`).
- Compiling a program once per run when several suites share it.
- A command that moves existing sibling suites into `tests/`.
