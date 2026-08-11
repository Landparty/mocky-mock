# mockymock options reference

This is a complete, practical reference for every option mockymock exposes:
every CLI subcommand and flag, and every directive in the `.cut` test-file
DSL (which is, in effect, the other half of mockymock's "options" — it's how
you configure what a test case mocks and asserts).

For internals (how each flag is implemented) see the [OKF bundle](../.okf/index.md),
in particular [`.okf/cli.md`](../.okf/cli.md) and [`.okf/dsl.md`](../.okf/dsl.md).
This document only covers *usage*.

## Contents

- [How mockymock is invoked](#how-mockymock-is-invoked)
- [CLI subcommands](#cli-subcommands)
  - [`setup`](#mockymock-setup)
  - [`generate`](#mockymock-generate)
  - [`fixtures`](#mockymock-fixtures)
  - [`run`](#mockymock-run)
  - [`debug`](#mockymock-debug)
  - [`lint`](#mockymock-lint)
  - [`mutate`](#mockymock-mutate)
  - [`collect`](#mockymock-collect)
  - [`dashboard`](#mockymock-dashboard)
  - [`export`](#mockymock-export)
  - [`analyze`](#mockymock-analyze)
  - [`skills install`](#mockymock-skills-install)
- [The `.cut` file: directives and options](#the-cut-file-directives-and-options)
- [Environment variables](#environment-variables)
- [Options quick-reference table](#options-quick-reference-table)

## How mockymock is invoked

```bash
mockymock <subcommand> [options]
mockymock --version
```

There are twelve subcommands: `setup`, `generate`, `fixtures`, `run`,
`debug`, `lint`, `mutate`, `collect`, `dashboard`, `export`, `analyze`,
`skills`.
Running `mockymock` with no subcommand prints help and exits with status 1.

A repeatable flag (noted below as "repeatable") can be passed more than
once: `--copybook-path a/ --copybook-path b/` searches both directories.

`mockymock run` and `mockymock setup` are the only subcommands that need a
running Docker daemon — COBOL is compiled and executed inside a GnuCOBOL
container. Every other subcommand is pure parse-and-analyze and needs
nothing beyond Python.

## CLI subcommands

### `mockymock setup`

```bash
mockymock setup
```

No options. Builds the GnuCOBOL Docker image (if needed) and starts the
`mockymock-cobc` container, then prints the compiler version as
confirmation. Optional in normal use — `mockymock run` does this
automatically on first use — but useful as a fast up-front check or a CI
warm-up step so the first real `run` isn't the one paying for the image
build.

### `mockymock generate`

```bash
mockymock generate <program.cbl> [options]
```

Scaffolds a starter `.cut` file from a COBOL program by statically
analyzing which boundaries (`CALL`, file I/O, `EXEC SQL`/`CICS`/`DLI`,
`ACCEPT`) each paragraph touches. Never touches Docker.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file to scaffold from. |
| `-o`, `--output PATH` | `<program>.cut` | Where to write the generated `.cut` file. |
| `--copybook-path DIR` (repeatable) | none | A directory to search for `COPY`-referenced copybooks. Pass one per directory. |
| `--with-data` | off | Data-driven mode: generate one `TESTCASE` per scenario, complete with real generated mock data and `EXPECT`/`VERIFY` assertions, using cobol-parser's fixture generator. Without this flag, `generate` scaffolds one `TESTCASE` per paragraph with placeholder mock bodies you fill in by hand. |
| `--fixtures PATH` | none | Use an already-generated fixture bundle JSON file (e.g. from `mockymock fixtures > bundle.json`) instead of generating one on the fly. Implies `--with-data`. Mutually exclusive with `--rows` (that bundle's row count is already fixed). |
| `--seed N` | random | Integer seed for reproducible generated data. Same program + same seed + same `--scenarios` = byte-identical output. Only meaningful with `--with-data` (ignored, and unnecessary, with `--fixtures`, since the bundle's data is already generated). |
| `--scenarios {happy,branches,all}` | `happy` | Which scenario set to generate. `happy` produces exactly one "everything succeeds" scenario. `branches` adds one scenario per reachable, satisfiable IF/EVALUATE/SEARCH branch arm. `all` additionally adds fixed families (empty input, error status, boundary values). Only meaningful with `--with-data`. |
| `--rows N` | generator default | How many data rows to generate per data table (e.g. how many `READ` records a sequential-read loop gets). Must be `>= 0`; `--rows 0` is honored (useful for forcing an immediate-EOF scenario). Mutually exclusive with `--fixtures`. |
| `--placeholder CATEGORY:KEY` (repeatable) | none | Downgrade one specific boundary's generated mock body back to an ordinary placeholder instead of bundle-seeded data — e.g. `--placeholder READ:INV-FILE`. The category is case-insensitive on input (upper-cased internally); the key must match the fixture's own key exactly. A pair that matches nothing prints a warning but does not fail the command. Only meaningful with `--with-data`/`--fixtures`. |

Examples:

```bash
# Plain scaffold: one TESTCASE per paragraph, placeholder bodies to fill in
mockymock generate ORDRPROC.cbl

# Custom output path, with copybooks resolved from two directories
mockymock generate ORDRPROC.cbl -o tests/ORDRPROC.cut \
    --copybook-path copybooks/ --copybook-path shared-copybooks/

# Data-driven: one TESTCASE per branch, real generated data, reproducible seed
mockymock generate ORDRPROC.cbl --with-data --seed 7 --scenarios branches

# Data-driven with an explicit row count, downgrading one boundary to a plain placeholder
mockymock generate ORDRPROC.cbl --with-data --rows 5 \
    --placeholder READ:ORDER-FILE

# Reuse a fixture bundle generated earlier (keeps its row counts and seed)
mockymock fixtures ORDRPROC.cbl --seed 7 --scenarios all > bundle.json
mockymock generate ORDRPROC.cbl --fixtures bundle.json
```

After scaffolding, `generate` also prints a list of any boundaries it
could **not** mock (e.g. an unidentifiable dynamic `CALL`) — this doesn't
block the scaffold, but `run` will refuse a test case that reaches one of
those sites until you resolve it by hand.

### `mockymock fixtures`

```bash
mockymock fixtures <program.cbl> [options]
```

Prints a cobol-parser fixture bundle (generated mock data, scenarios,
expectations) as JSON on stdout — the same generation `generate --with-data`
uses internally, exposed standalone for editor integrations or for piping
into `generate --fixtures`. **stdout is always exactly the JSON document**;
every diagnostic (including a "file not found" error) goes to stderr, so
`mockymock fixtures ... | jq .` is always safe on success.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--scenarios {happy,branches,all}` | `happy` | Same meaning as `generate --scenarios`. |
| `--seed N` | random | Same meaning as `generate --seed`. |
| `--rows N` | generator default | Same meaning as `generate --rows`. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |

Example:

```bash
mockymock fixtures ORDRPROC.cbl --seed 7 --scenarios all --rows 10 > bundle.json
```

### `mockymock run`

```bash
mockymock run <program.cbl> --cut <program.cut> [options]
```

The full pipeline and the command you'll use most: parse the program,
statically check the `.cut` file for problems, splice in the mocks,
compile with real GnuCOBOL inside Docker, execute, and report pass/fail.
This is the only subcommand other than `setup` that requires Docker.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--cut PATH` | required | The `.cut` test file to run against `program`. |
| `--junit-xml PATH` | none | Write a JUnit XML report there — for CI systems that consume that format. |
| `--json-report PATH` | none | Write a machine-readable run report: per-case status (`passed`/`failed`/`crashed`/`not_run`), `.cut` line numbers, expected vs. actual values, and tags. |
| `--case NAME` (repeatable) | all cases | Run only the named `TESTCASE`(s). Combines with `--tag` as a union (a case matching either selector runs). An unknown name is reported as a static problem before anything compiles. |
| `--tag TAG` (repeatable) | all cases | Run only `TESTCASE`s carrying this tag (see [`TAGS`](#the-cut-file-directives-and-options) below). Combines with `--case` as a union. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |
| `--keep-sandbox` | off | Don't delete the temporary sandbox directory after the run; its path is printed so you can inspect the instrumented source and binary. |
| `--verbose` | off | On a compile failure, print the path to the instrumented source (and keep the sandbox around so that path is still valid when you go look). |
| `--coverage` | off | Compile with GnuCOBOL's `--coverage` flag and report per-line coverage (via `gcov`), remapped onto your original line numbers. |
| `--coverage-out PATH` | none | Write the full coverage report (percentage plus every uncovered line) to a file. Implies `--coverage`. |
| `--coverage-json PATH` | none | Write a machine-readable coverage report to a file, mapped onto the original `.cbl`'s line numbers. Implies `--coverage`. |
| `--trace` | off | Replay one test case's execution: the statement path it actually took through the program, plus the mock timeline, in order. **Requires exactly one `--case` and no `--tag`** — a suite compiles and runs as a single binary, so a trace can only be attributed to one selected case. |
| `--trace-json PATH` | none | Write a machine-readable execution trace to a file. Implies `--trace` (and the same one-case requirement). |
| `--record-expectations` | off | Golden/characterization mode. For every `*> STUB EXPECT <name>` comment in the `.cut` file (see below), capture the value the program actually produced at runtime and rewrite that line into a real `EXPECT <name> TO BE <value>` line, in place. Never overwrites a hand-written `EXPECT`. Best-effort: prints a `recorded N, skipped M` summary and never changes the run's exit code. |

Examples:

```bash
# Basic run
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut

# CI-friendly: JUnit output, only the "happy path" and "error handling" tags
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut \
    --junit-xml results.xml --tag happy-path --tag error-handling

# One named case with a full execution trace
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut \
    --case "rejects negative quantity" --trace --trace-json trace.json

# Line coverage, machine-readable, mapped back to ORDRPROC.cbl's own lines
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --coverage-json coverage.json

# Debug a compile failure without deleting the evidence
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --verbose --keep-sandbox

# Fill in every "*> STUB EXPECT" placeholder with real captured values
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --record-expectations
```

`run` exits 0 only if every selected test case passed *and* the compiled
binary itself exited 0 — a crash after the summary line still fails the
run.

### `mockymock debug`

```bash
mockymock debug <program.cbl> --cut <program.cut> --case <name> --dap-stdio [options]
```

Starts an interactive [Debug Adapter Protocol](https://microsoft.github.io/debug-adapter-protocol/)
(DAP) session for one test case — breakpoints, stepping, and read-only
variable inspection against your *original* `.cbl` source. This is meant
to be launched by an editor (the mockymock VS Code extension does this
automatically), not typed by hand in a terminal — there is no useful
plain-terminal mode.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--cut PATH` | required | The `.cut` test file. |
| `--case NAME` | required, exactly one | The single test case to debug. A suite runs as one binary/one execution stream, so exactly one case must be selected. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |
| `--dap-stdio` | required | Run the DAP adapter over stdio. This flag is effectively mandatory — the command refuses (and points you at the VS Code extension) if it's missing. |

Example (as an editor would invoke it):

```bash
mockymock debug ORDRPROC.cbl --cut ORDRPROC.cut --case "rejects negative quantity" --dap-stdio
```

### `mockymock lint`

```bash
mockymock lint <program.cbl> --cut <program.cut> [options]
```

Runs every static check `run` would run — before compiling anything —
with zero Docker dependency. Good for pre-commit hooks and CI lanes that
don't have (or don't want to pay for) a Docker daemon.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--cut PATH` | required | The `.cut` test file. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |

Prints `mockymock lint: no problems found.` and exits 0 if the `.cut` file
is clean, or one `mockymock lint: <problem>` line per problem plus a count,
exiting 1.

```bash
mockymock lint ORDRPROC.cbl --cut ORDRPROC.cut
```

### `mockymock mutate`

```bash
mockymock mutate <program.cbl> --cut <program.cut> [options]
```

Mutation testing: measures how good your `.cut` suite actually is by
patching small changes into the program (flipping a comparison operator,
changing a constant, etc.) and checking whether your test suite notices
(a "killed" mutant) or doesn't ("survived" — a gap in your assertions).

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--cut PATH` | required | The `.cut` test file. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |
| `--list` | off | Only list the mutants that would be generated, and exit. Pure static analysis, no Docker needed. |
| `--timeout SECONDS` | `15` | Per-mutant execution timeout. A mutant run that exceeds this counts as killed (an infinite loop is itself a detectable difference). |
| `--json-report PATH` | none | Write the full machine-readable mutation report (every mutant, its outcome, and a diff for survivors). |
| `--fail-under PERCENT` | none | Exit 1 if the mutation score falls below this percentage — useful as a CI quality gate. |

Examples:

```bash
# See what would be mutated, no Docker required
mockymock mutate ORDRPROC.cbl --cut ORDRPROC.cut --list

# Full run with a CI quality gate at 80%
mockymock mutate ORDRPROC.cbl --cut ORDRPROC.cut \
    --fail-under 80 --json-report mutation-report.json --timeout 30
```

Mock bodies and terminator statements are never mutated — mutating them
would test the mocking harness itself, not your program.

### `mockymock collect`

```bash
mockymock collect --cut <program.cut> [options]
```

Lists a suite's test cases with their `.cut` line numbers and tags. Parses
only the `.cut` file — no `.cbl`, no Docker. Built for editor test
discovery and quick suite inspection.

| Option | Default | Description |
|---|---|---|
| `--cut PATH` | required | The `.cut` test file. |
| `--json` | off | Emit machine-readable JSON (`{"version": 1, "cutFile": ..., "suite": {...}, "cases": [...]}`) instead of a human-readable listing. |

```bash
mockymock collect --cut ORDRPROC.cut
mockymock collect --cut ORDRPROC.cut --json
```

### `mockymock dashboard`

```bash
mockymock dashboard [options]
```

Serves a local, read-only status page (loopback-only — always
`127.0.0.1`, not configurable) showing whether Docker and the GnuCOBOL
toolchain are up. It never builds or starts anything itself; it only
reports status. Runs until you press Ctrl-C.

| Option | Default | Description |
|---|---|---|
| `--port N` | `8765` | TCP port to serve on. Pass `0` to let the OS pick a free port. |
| `--no-browser` | off | Don't automatically open a browser window on start. |

```bash
mockymock dashboard
mockymock dashboard --port 0 --no-browser
```

### `mockymock export`

```bash
mockymock export <program.cbl> --cut <program.cut> [options]
```

Writes the instrumented (mocked) source to a file, adjusted for
compilation on a real fixed-format (z/OS) COBOL compiler instead of
GnuCOBOL — useful for validating that the computational core of your
program compiles cleanly on the target mainframe compiler. It does not
compile or run anything itself, and needs no Docker. The output includes a
disclaimer header noting this is a mock-only build (every boundary is
either mocked or fails loudly; no real I/O executes).

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--cut PATH` | required | The `.cut` test file (defines which boundaries get mocked into the export). |
| `-o`, `--output PATH` | `<program-stem>.mainframe.cbl` | Where to write the exported source. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |
| `--case NAME` (repeatable) | all cases | Include only the named `TESTCASE`(s)' mocks in the export. Unions with `--tag`. |
| `--tag TAG` (repeatable) | all cases | Include only tagged `TESTCASE`s' mocks. Unions with `--case`. |

```bash
mockymock export ORDRPROC.cbl --cut ORDRPROC.cut -o ORDRPROC.mainframe.cbl
```

If a generated line still doesn't fit within column 72 after adjustment,
`export` refuses rather than writing an invalid fixed-format file.

### `mockymock analyze`

```bash
mockymock analyze [cobol-parser-args...]
```

A pass-through to the underlying [cobol-parser](https://github.com/Landparty/cobol-parser)
CLI's own analysis subcommands (`dead-code`, `program-flow`, `io-sequence`,
`move-type-check`, `linkage-check`, `language-env`, `ims-dli`, `analyze`
itself). Everything after `mockymock analyze` is forwarded verbatim.

```bash
mockymock analyze dead-code ORDRPROC.cbl --compact
mockymock analyze program-flow ORDRPROC.cbl
```

Those flags belong to cobol-parser, not mockymock — see cobol-parser's own
CLI documentation for the full list.

### `mockymock skills install`

```bash
mockymock skills install [--project] [--force]
```

Installs the packaged Claude Code skill (`SKILL.md` plus `reference/`
files teaching an AI assistant to scaffold, edit, and run `.cut` files)
so a Claude Code session can use it.

| Option | Default | Description |
|---|---|---|
| `--project` | off | Install into `./.claude/skills/mockymock` instead of `~/.claude/skills/mockymock`. |
| `--force` | off | Overwrite an existing install at the target path. Without it, an existing target refuses the install so local edits are never silently clobbered. |

```bash
mockymock skills install
mockymock skills install --project --force
```

## The `.cut` file: directives and options

The `.cut` file is a small DSL, not YAML/JSON/TOML — it's the other place
you "configure" mockymock: which boundaries to mock, what data to move in
first, which paragraph to run, and what to assert afterward. Full grammar
in [`.okf/dsl.md`](../.okf/dsl.md); this section is the practical
cheat-sheet.

### Top-level shape

```
TESTSUITE "<name>"

[ PROVIDER <name>
      HEADER <col>, ...
      ROW <value>, ... ]*

[ BEFORE-ALL
      MOCK ... END-MOCK
  END-BEFORE ]

[ BEFORE-EACH
      MOCK ... END-MOCK
  END-BEFORE ]

TESTCASE "<name>" [ TAGS "<tag>" ... ] [ USING PROVIDER <name> ]
    [ MOCK <category> <key> ... END-MOCK ]*
    [ MOVE <value> TO <target> ]*
    PERFORM <paragraph> [ THRU|THROUGH <paragraph> ]
    [ EXPECT <data-name> TO BE <value> ]*
    [ VERIFY [<category>] <key> WAS CALLED|PERFORMED <expectation> ]*
```

Rules that matter in practice:

- Exactly one `TESTSUITE` per file, at most one `BEFORE-ALL` and one
  `BEFORE-EACH`, exactly one `PERFORM` per `TESTCASE`.
- Every keyword is case-sensitive uppercase, **except** `END-MOCK`/
  `END-BEFORE` (case-insensitive, optional trailing period — `end-mock.`
  is fine).
- Lines starting with `*>` are comments outside a `MOCK` body; inside a
  body they pass through as ordinary COBOL comments.

### `TESTSUITE "<name>"`

One per file. The suite's display name.

### `TESTCASE "<name>" [TAGS "<tag>" ...] [USING PROVIDER <name>]`

One test case. Options:

- `TAGS "<tag>" ["<tag>" ...]` — attaches selection tags, used by
  `run --tag` and shown in `collect`'s output. Purely for selection; no
  runtime effect.
- `USING PROVIDER <name>` — binds this case as a template that gets
  expanded once per row of the named `PROVIDER` block (see below).

### `MOCK <category> <key> ... END-MOCK`

Declares what happens when the program reaches one boundary. Two key
syntaxes, split by category:

| Category | Key syntax | Example |
|---|---|---|
| `CALL` (static) | quoted literal | `MOCK CALL "DISCRATE"` |
| `CALL` (dynamic, called through a variable) | bare identifier | `MOCK CALL WS-PGM-NAME` |
| `MQ` (sugar for `CALL`) | quoted literal | `MOCK MQ "MQPUT"` |
| `SQL`, `CICS`, `DLI` | quoted literal (prefix of the statement text) | `MOCK SQL "UPDATE INVENTORY"` |
| `OPEN`, `CLOSE`, `READ`, `WRITE`, `REWRITE`, `DELETE`, `START`, `UNLOCK` | bare file/record name | `MOCK OPEN INV-FILE`, `MOCK WRITE RPT-REC` |
| `ACCEPT` | bare data-name | `MOCK ACCEPT WS-CONFIRM` |
| `PARAGRAPH`, `SECTION` | bare paragraph/section name | `MOCK PARAGRAPH CALC-TOTALS` |

The body between `MOCK` and `END-MOCK` is free-form COBOL, spliced in
verbatim when that boundary is reached (typically `MOVE` statements
setting return codes, SQLCODE, or output fields):

```
MOCK CALL "DISCRATE"
    MOVE 0.15 TO WS-DISCOUNT-RATE
END-MOCK
```

`PARAGRAPH`/`SECTION` mocks replace the whole body of that paragraph or
section, letting you isolate a caller from its own collaborators.

#### `ROWS` — multi-row cursor sugar (`SQL` and `READ` only)

For a `SQL` cursor `FETCH` loop or a sequential `READ` loop that should
return a fixed sequence of rows and then signal exhaustion:

```
MOCK SQL "FETCH CUST_CURSOR" ROWS
    ( CUST-NAME = "ALICE", CUST-BAL = 100.00 )
    ( CUST-NAME = "BOB",   CUST-BAL = 250.50 )
END-MOCK
```

```
MOCK READ INV-FILE ROWS
    ( INV-QTY = 5 )
    ( INV-QTY = 12 )
    TERMINAL ( WS-EOF = "Y" )
END-MOCK
```

- Each `( FIELD = value, ... )` group is one row, returned in order on
  successive calls.
- `TERMINAL ( FIELD = value, ... )` (`READ` only, optional, at most one)
  sets the fields for the rows-exhausted branch. If your loop guard is a
  flag set by the program's own `AT END` clause (not the file status), put
  that flag's `MOVE` here too, or the loop will never terminate.
- `SQL`'s exhausted branch is fixed (`SQLCODE = 100`, DB2's "not found"
  code) and needs no `TERMINAL` group.
- `ROWS` is only valid on `SQL` and `READ`; using it elsewhere is a parse
  error.

### `MOVE <value> TO <target>`

Sets up working-storage before the test runs, evaluated in file order (a
later `MOVE` to the same target wins, same as COBOL):

```
MOVE 100 TO WS-ORDER-QTY
MOVE "ACTIVE" TO WS-STATUS
```

### `PERFORM <paragraph> [THRU|THROUGH <paragraph>]`

The entry point for the test case — exactly one per `TESTCASE`:

```
PERFORM MAIN-PROCESS
PERFORM VALIDATE-INPUT THRU VALIDATE-INPUT-EXIT
```

### `EXPECT <data-name> TO BE <value>`

An assertion checked after `PERFORM` returns:

```
EXPECT WS-TOTAL-QTY TO BE 10
EXPECT WS-TABLE(1, 2) TO BE "Y"
```

Subscripts (`FIELD(1, 2)` or `FIELD(1:5)` reference modification) are
supported for both the data-name and the `MOVE` target above; qualified
names (`FIELD OF RECORD`) are not.

### `VERIFY [<category>] <key> WAS CALLED|PERFORMED <expectation>`

Asserts how many times a boundary was reached. `CALLED` and `PERFORMED`
are interchangeable. `<expectation>` is one of:

| Expectation | Meaning |
|---|---|
| `ONCE` | Exactly one call. |
| `NEVER` | Zero calls. |
| `AT LEAST ONCE` | One or more calls. |
| `<n> TIMES` | Exactly `n` calls. |

```
VERIFY READ INV-FILE WAS PERFORMED 3 TIMES
VERIFY WRITE RPT-REC WAS PERFORMED NEVER
VERIFY CALL "DISCRATE" WAS CALLED ONCE
```

A bare `VERIFY "X" WAS CALLED ...` with no category keyword defaults to
`CALL` (kept for backward compatibility).

### `FILE-STATUS IS <mnemonic-or-"code">`

Usable once, inside a `MOCK OPEN|CLOSE|READ|DELETE|START|UNLOCK` body
(not `WRITE`/`REWRITE`). Sets the file-status field mockymock generates
for that file.

| Mnemonic | File status code |
|---|---|
| `SUCCESS` | `00` |
| `END-OF-FILE` | `10` |
| `DUPLICATE-KEY` | `22` |
| `RECORD-NOT-FOUND` | `23` |
| `FILE-NOT-FOUND` | `35` |
| `ALREADY-OPEN` | `41` |
| `NOT-OPEN` | `42` |
| `NO-CURRENT-RECORD` | `43` |

A quoted two-character code also always works, e.g. `FILE-STATUS IS "92"`.
Every eligible category gets an implicit `MOVE "00"` (success) before its
own body automatically, whether or not `FILE-STATUS IS` is used — you
only need this directive to signal something *other* than success.

```
MOCK OPEN INV-FILE
    FILE-STATUS IS FILE-NOT-FOUND
END-MOCK
```

### `BEFORE-ALL` / `BEFORE-EACH ... END-BEFORE`

Shared `MOCK` directives, declared once and applied to every `TESTCASE` in
the suite — useful when most cases need the same boundary mocked the same
way, with only a few needing to override it. Precedence on a collision is
`TESTCASE`'s own mock > `BEFORE-EACH` > `BEFORE-ALL`. The two blocks
differ *only* in that precedence — there's no timing difference despite
the xUnit-style names.

```
BEFORE-EACH
    MOCK OPEN INV-FILE
    END-MOCK
END-BEFORE

TESTCASE "override for one case"
    MOCK OPEN INV-FILE
        FILE-STATUS IS FILE-NOT-FOUND
    END-MOCK
    ...
```

### `PROVIDER <name>` / `HEADER` / `ROW` — parameterized test cases

Runs the same `TESTCASE` body once per row of a data table, substituting
`{ColumnName}` placeholders into that case's `MOVE` and `EXPECT` values
only (mock bodies, `PERFORM` target, and `VERIFY` stay identical across
every row):

```
PROVIDER StateCodes
    HEADER State, ExpectedRegion
    ROW "NY", "NORTHEAST"
    ROW "CA", "WEST"
    ROW "TX", "SOUTH"

TESTCASE "region lookup" USING PROVIDER StateCodes
    MOVE "{State}" TO WS-STATE-CODE
    PERFORM LOOKUP-REGION
    EXPECT WS-REGION TO BE "{ExpectedRegion}"
```

This expands into three ordinary test cases, named
`"region lookup [row 1: NY]"`, etc. `PROVIDER` must be declared before any
`TESTCASE` that references it.

### `*> STUB EXPECT <data-name> [-- <note>]`

Not new grammar — an ordinary `*>` comment convention. Write it where a
real `EXPECT` would go, for a field whose correct value you don't know
yet:

```
TESTCASE "computes total"
    MOCK READ INV-FILE
        MOVE 5 TO INV-QTY
    END-MOCK
    PERFORM MAIN-PROCESS
    *> STUB EXPECT WS-TOTAL-QTY -- computed in CALC-TOTALS
```

Run `mockymock run ... --record-expectations` to turn every such stub into
a real `EXPECT <name> TO BE <value>` line, filled in with the value the
program actually produced.

## Environment variables

None. mockymock reads no environment variables of its own — everything is
controlled through CLI flags and the `.cut` DSL. (Docker itself, invoked
as a subprocess by `run`/`setup`/`debug`/`mutate`, honors its own standard
variables like `DOCKER_HOST`, but mockymock never reads or forwards them.)

## Options quick-reference table

| Subcommand | Needs Docker? | Key options |
|---|---|---|
| `setup` | yes | *(none)* |
| `generate` | no | `-o`, `--copybook-path`, `--with-data`, `--fixtures`, `--seed`, `--scenarios`, `--rows`, `--placeholder` |
| `fixtures` | no | `--scenarios`, `--seed`, `--rows`, `--copybook-path` |
| `run` | yes | `--cut`, `--junit-xml`, `--json-report`, `--case`, `--tag`, `--copybook-path`, `--keep-sandbox`, `--verbose`, `--coverage[-out\|-json]`, `--trace[-json]`, `--record-expectations` |
| `debug` | yes | `--cut`, `--case`, `--copybook-path`, `--dap-stdio` |
| `lint` | no | `--cut`, `--copybook-path` |
| `mutate` | yes (unless `--list`) | `--cut`, `--copybook-path`, `--list`, `--timeout`, `--json-report`, `--fail-under` |
| `collect` | no | `--cut`, `--json` |
| `dashboard` | read-only probe | `--port`, `--no-browser` |
| `export` | no | `--cut`, `-o`, `--copybook-path`, `--case`, `--tag` |
| `analyze` | no | *(forwarded to cobol-parser)* |
| `skills install` | no | `--project`, `--force` |
