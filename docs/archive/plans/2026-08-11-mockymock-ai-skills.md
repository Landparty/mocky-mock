# mockymock AI Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship two Claude Code skills for mockymock — a repo-local skill orienting contributors into `.okf/`, and a packaged end-user skill (installed via a new `mockymock skills install` CLI subcommand) teaching an AI assistant to write and run `.cut` test files.

**Architecture:** The contributor skill is a single committed markdown file with no code. The end-user skill is markdown content packaged as data under the existing `mockymock.cli` package (so it survives `uv tool install`), copied to disk by a new `mockymock/cli/skills_cmd.py` module and wired into `mockymock/cli/main.py`'s existing `_cmd_*`/argparse dispatch pattern.

**Tech Stack:** Python 3.11+, argparse, pytest (existing toolchain — no new dependencies).

## Global Constraints

- No new runtime dependencies (no PyYAML etc.) — frontmatter is `name:`/`description:` on their own lines, simple enough to check with plain string ops in tests.
- Every `_cmd_*` in `mockymock/cli/main.py` defers its non-stdlib/heavy imports into its own function body; `build_parser()` must stay free of them. Follow this for `_cmd_skills_install` too, for consistency with every other subcommand.
- Fail-closed: `mockymock skills install` must refuse to overwrite an existing target unless `--force` is given.
- Design doc: `docs/superpowers/specs/2026-08-11-mockymock-ai-skills-design.md` — read it for full rationale; this plan implements it (including the post-approval packaging fix nesting the skill under `mockymock.cli` rather than a new top-level `mockymock.skills` package).

---

### Task 1: Contributor skill (`.claude/skills/mockymock-dev/`)

**Files:**
- Create: `.claude/skills/mockymock-dev/SKILL.md`
- Test: `tests/unit/test_contributor_skill.py`

**Interfaces:**
- Consumes: nothing (first task, no dependencies on other tasks).
- Produces: nothing later tasks depend on — this is a standalone content file.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_contributor_skill.py
"""The contributor-facing Claude Code skill (.claude/skills/mockymock-dev/)
is auto-discovered by Claude Code from its frontmatter -- a malformed or
missing frontmatter field silently breaks discovery with no import error
to catch it, so pin the shape here."""

from pathlib import Path

SKILL_PATH = (
    Path(__file__).resolve().parents[2] / ".claude" / "skills" / "mockymock-dev" / "SKILL.md"
)


def test_contributor_skill_file_exists():
    assert SKILL_PATH.is_file()


def test_contributor_skill_has_required_frontmatter():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    frontmatter = text[4:end]
    assert "name: mockymock-dev" in frontmatter
    assert "description:" in frontmatter


def test_contributor_skill_points_at_the_okf_index():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert ".okf/index.md" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_contributor_skill.py -v`
Expected: FAIL — `SKILL_PATH.is_file()` is `False` (file doesn't exist yet).

- [ ] **Step 3: Write the skill file**

```markdown
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_contributor_skill.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/mockymock-dev/SKILL.md tests/unit/test_contributor_skill.py
git commit -m "Add mockymock-dev contributor skill routing into .okf/"
```

---

### Task 2: End-user skill content (`mockymock/cli/skills/mockymock/`)

**Files:**
- Create: `mockymock/cli/skills/mockymock/SKILL.md`
- Create: `mockymock/cli/skills/mockymock/reference/cut-dsl.md`
- Create: `mockymock/cli/skills/mockymock/reference/cli-flags.md`
- Test: `tests/unit/test_mockymock_skill_content.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: a directory at `mockymock/cli/skills/mockymock/` containing `SKILL.md` and `reference/{cut-dsl,cli-flags}.md` — Task 3's `skills_cmd.py` copies this exact directory (`SOURCE_DIR`), and Task 4's CLI tests assert these exact three files land at the install target.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mockymock_skill_content.py
"""The packaged end-user skill (mockymock/cli/skills/mockymock/) ships as
package data and is copied out by `mockymock skills install`. Pin its
shape here so a future edit can't silently drop a file that
`mockymock.cli.skills_cmd.SOURCE_DIR` (Task 3) and the packaging
declaration in pyproject.toml both assume exists."""

from pathlib import Path

SKILL_DIR = (
    Path(__file__).resolve().parents[2] / "mockymock" / "cli" / "skills" / "mockymock"
)


def test_skill_md_exists_with_required_frontmatter():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    frontmatter = text[4:end]
    assert "name: mockymock" in frontmatter
    assert "description:" in frontmatter


def test_skill_md_points_at_both_reference_files():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "reference/cut-dsl.md" in text
    assert "reference/cli-flags.md" in text


def test_reference_files_exist_and_are_non_empty():
    for name in ("cut-dsl.md", "cli-flags.md"):
        path = SKILL_DIR / "reference" / name
        assert path.is_file()
        assert len(path.read_text(encoding="utf-8")) > 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_mockymock_skill_content.py -v`
Expected: FAIL — `SKILL_DIR / "SKILL.md"` doesn't exist yet (`FileNotFoundError`).

- [ ] **Step 3: Write `SKILL.md`**

```markdown
---
name: mockymock
description: Use when writing or running .cut test files for mockymock (a COBOL unit-test framework that mocks CALL/file-I-O/EXEC SQL·CICS·DLI/ACCEPT boundaries and runs the real program under GnuCOBOL), or when a mockymock run fails or refuses and the reason needs interpreting.
---

<!--
Maintainer note: this is a curated duplicate of docs/options-reference.md
in the mocky-mock repo, adapted for agent consumption. A .cut directive or
CLI flag change there should be reflected in reference/cut-dsl.md and
reference/cli-flags.md here too.
-->

# mockymock: COBOL unit testing

mockymock mocks a COBOL program's external boundaries (subprogram `CALL`s
including MQ, file I/O, `EXEC SQL`/`CICS`/`DLI`, console `ACCEPT`),
compiles the instrumented copy with real GnuCOBOL inside Docker, runs it,
and reports pass/fail. Use it to write and run `.cut` test files against
`.cbl` programs.

## Workflow

1. **Scaffold a starting point** instead of writing a `.cut` file by hand:
   ```bash
   mockymock generate PROGRAM.cbl                                       # placeholder mocks, one TESTCASE per paragraph
   mockymock generate PROGRAM.cbl --with-data --seed 7 --scenarios all  # real generated data + EXPECT/VERIFY per scenario
   ```
   `generate` also prints every boundary it could **not** mock (an
   unidentifiable dynamic `CALL`, an unspliceable nested site) -- a test
   case that reaches one of those will be refused by `run` until you
   resolve it.

2. **Fill in / edit mocks** using the `.cut` DSL -- see
   `reference/cut-dsl.md` for the full directive reference. The shape:
   ```
   TESTSUITE "<name>"

   TESTCASE "<name>"
       MOCK <category> <key>
           <COBOL statements, e.g. MOVE 5 TO INV-QTY>
       END-MOCK
       PERFORM <paragraph>
       EXPECT <data-name> TO BE <value>
       VERIFY <category> <key> WAS PERFORMED <n> TIMES
   ```

3. **Check for problems without Docker** while iterating:
   ```bash
   mockymock lint PROGRAM.cbl --cut PROGRAM.cut
   ```
   Prints every refusal `run` would print, with zero Docker dependency --
   use this as the fast inner loop while writing a `.cut` file.

4. **Run it for real** (needs a running Docker daemon; `mockymock setup`
   warms it up ahead of time, but `run` does this automatically):
   ```bash
   mockymock run PROGRAM.cbl --cut PROGRAM.cut
   ```

5. **When a run fails or refuses**, read the printed reason literally --
   mockymock is deliberately fail-closed (a refusal names exactly what it
   couldn't soundly rewrite, e.g. `GO TO` into a mock target, `ALTER`, a
   parse warning) rather than silently skipping or mis-mocking. See
   `reference/cli-flags.md`'s `run`/`debug` sections for `--trace`
   (replay one case's execution path plus the mock timeline in order),
   `--record-expectations` (turn `*> STUB EXPECT <name>` comments into
   real assertions filled in from the actual run), and `--verbose`
   (print the instrumented source path on a compile failure).

## Full reference

- `reference/cut-dsl.md` -- every `.cut` directive: `MOCK`/`END-MOCK`
  categories, `ROWS` cursor sugar, `EXPECT`, `VERIFY`, `FILE-STATUS IS`,
  `BEFORE-ALL`/`BEFORE-EACH`, `PROVIDER`/`HEADER`/`ROW`, `*> STUB EXPECT`.
- `reference/cli-flags.md` -- every subcommand and flag: `setup`,
  `generate`, `fixtures`, `run`, `debug`, `lint`, `mutate`, `collect`,
  `dashboard`, `export`, `analyze`.
```

- [ ] **Step 4: Write `reference/cut-dsl.md`**

```markdown
# The `.cut` file: directive reference

The `.cut` file is a small DSL, not YAML/JSON/TOML -- it's how you tell
mockymock which boundaries to mock, what data to move in first, which
paragraph to run, and what to assert afterward.

## Top-level shape

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
  `END-BEFORE` (case-insensitive, optional trailing period -- `end-mock.`
  is fine).
- Lines starting with `*>` are comments outside a `MOCK` body; inside a
  body they pass through as ordinary COBOL comments.

## `TESTSUITE "<name>"`

One per file. The suite's display name.

## `TESTCASE "<name>" [TAGS "<tag>" ...] [USING PROVIDER <name>]`

One test case. Options:

- `TAGS "<tag>" ["<tag>" ...]` -- attaches selection tags, used by
  `run --tag` and shown in `collect`'s output. Purely for selection; no
  runtime effect.
- `USING PROVIDER <name>` -- binds this case as a template that gets
  expanded once per row of the named `PROVIDER` block (see below).

## `MOCK <category> <key> ... END-MOCK`

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

### `ROWS` -- multi-row cursor sugar (`SQL` and `READ` only)

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
  flag set by the program's own `AT END` clause (not the file status),
  put that flag's `MOVE` here too, or the loop will never terminate.
- `SQL`'s exhausted branch is fixed (`SQLCODE = 100`, DB2's "not found"
  code) and needs no `TERMINAL` group.
- `ROWS` is only valid on `SQL` and `READ`; using it elsewhere is a parse
  error.

## `MOVE <value> TO <target>`

Sets up working-storage before the test runs, evaluated in file order (a
later `MOVE` to the same target wins, same as COBOL):

```
MOVE 100 TO WS-ORDER-QTY
MOVE "ACTIVE" TO WS-STATUS
```

## `PERFORM <paragraph> [THRU|THROUGH <paragraph>]`

The entry point for the test case -- exactly one per `TESTCASE`:

```
PERFORM MAIN-PROCESS
PERFORM VALIDATE-INPUT THRU VALIDATE-INPUT-EXIT
```

## `EXPECT <data-name> TO BE <value>`

An assertion checked after `PERFORM` returns:

```
EXPECT WS-TOTAL-QTY TO BE 10
EXPECT WS-TABLE(1, 2) TO BE "Y"
```

Subscripts (`FIELD(1, 2)` or `FIELD(1:5)` reference modification) are
supported for both the data-name and the `MOVE` target above; qualified
names (`FIELD OF RECORD`) are not.

## `VERIFY [<category>] <key> WAS CALLED|PERFORMED <expectation>`

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

## `FILE-STATUS IS <mnemonic-or-"code">`

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
own body automatically, whether or not `FILE-STATUS IS` is used -- you
only need this directive to signal something *other* than success.

```
MOCK OPEN INV-FILE
    FILE-STATUS IS FILE-NOT-FOUND
END-MOCK
```

## `BEFORE-ALL` / `BEFORE-EACH ... END-BEFORE`

Shared `MOCK` directives, declared once and applied to every `TESTCASE` in
the suite -- useful when most cases need the same boundary mocked the
same way, with only a few needing to override it. Precedence on a
collision is `TESTCASE`'s own mock > `BEFORE-EACH` > `BEFORE-ALL`. The
two blocks differ *only* in that precedence -- there's no timing
difference despite the xUnit-style names.

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

## `PROVIDER <name>` / `HEADER` / `ROW` -- parameterized test cases

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

## `*> STUB EXPECT <data-name> [-- <note>]`

Not new grammar -- an ordinary `*>` comment convention. Write it where a
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
```

- [ ] **Step 5: Write `reference/cli-flags.md`**

```markdown
# mockymock CLI: subcommand and flag reference

`mockymock <subcommand> [options]`. Twelve subcommands: `setup`,
`generate`, `fixtures`, `run`, `debug`, `lint`, `mutate`, `collect`,
`dashboard`, `export`, `analyze`, `skills`. Running `mockymock` with no
subcommand prints help and exits 1.

Only `run` and `setup` need a running Docker daemon (COBOL is compiled
and executed inside a GnuCOBOL container). Everything else is pure
parse-and-analyze.

## `mockymock setup`

```bash
mockymock setup
```

No options. Builds the GnuCOBOL Docker image (if needed) and starts the
`mockymock-cobc` container, then prints the compiler version. Optional in
normal use -- `mockymock run` does this automatically -- but useful as a
fast up-front check or CI warm-up so the first real `run` isn't the one
paying for the image build.

## `mockymock generate`

```bash
mockymock generate <program.cbl> [options]
```

Scaffolds a starter `.cut` file by statically analyzing which boundaries
each paragraph touches. Never touches Docker.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file to scaffold from. |
| `-o`, `--output PATH` | `<program>.cut` | Where to write the generated `.cut` file. |
| `--copybook-path DIR` (repeatable) | none | A directory to search for `COPY`-referenced copybooks. |
| `--with-data` | off | Data-driven mode: one `TESTCASE` per scenario, with real generated mock data and `EXPECT`/`VERIFY` assertions, instead of placeholder bodies. |
| `--fixtures PATH` | none | Use an already-generated fixture bundle JSON file instead of generating one on the fly. Implies `--with-data`. Mutually exclusive with `--rows`. |
| `--seed N` | random | Integer seed for reproducible generated data (`--with-data` only). |
| `--scenarios {happy,branches,all}` | `happy` | `happy` = one "everything succeeds" scenario. `branches` = one scenario per reachable branch arm. `all` = branches plus fixed families (empty input, error status, boundary values). `--with-data` only. |
| `--rows N` | generator default | Rows to generate per data table (`--rows 0` is honored, e.g. to force an immediate-EOF scenario). Mutually exclusive with `--fixtures`. |
| `--placeholder CATEGORY:KEY` (repeatable) | none | Downgrade one boundary's generated mock body back to a plain placeholder, e.g. `--placeholder READ:INV-FILE`. |

Examples:

```bash
mockymock generate ORDRPROC.cbl
mockymock generate ORDRPROC.cbl -o tests/ORDRPROC.cut --copybook-path copybooks/
mockymock generate ORDRPROC.cbl --with-data --seed 7 --scenarios branches
mockymock generate ORDRPROC.cbl --with-data --rows 5 --placeholder READ:ORDER-FILE
mockymock fixtures ORDRPROC.cbl --seed 7 --scenarios all > bundle.json
mockymock generate ORDRPROC.cbl --fixtures bundle.json
```

After scaffolding, `generate` also prints a list of any boundaries it
could **not** mock -- this doesn't block the scaffold, but `run` will
refuse a test case reaching one of those sites until you resolve it.

## `mockymock fixtures`

```bash
mockymock fixtures <program.cbl> [options]
```

Prints a fixture bundle (generated mock data, scenarios, expectations) as
JSON on stdout -- the same generation `generate --with-data` uses
internally. **stdout is always exactly the JSON document**; every
diagnostic goes to stderr, so `mockymock fixtures ... | jq .` is always
safe on success.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--scenarios {happy,branches,all}` | `happy` | Same meaning as `generate --scenarios`. |
| `--seed N` | random | Same meaning as `generate --seed`. |
| `--rows N` | generator default | Same meaning as `generate --rows`. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |

```bash
mockymock fixtures ORDRPROC.cbl --seed 7 --scenarios all --rows 10 > bundle.json
```

## `mockymock run`

```bash
mockymock run <program.cbl> --cut <program.cut> [options]
```

The full pipeline and the command you'll use most: parse, statically check
the `.cut` file, splice in the mocks, compile with real GnuCOBOL inside
Docker, execute, and report pass/fail.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--cut PATH` | required | The `.cut` test file to run against `program`. |
| `--junit-xml PATH` | none | Write a JUnit XML report there. |
| `--json-report PATH` | none | Write a machine-readable run report (per-case status, `.cut` line numbers, expected vs. actual, tags). |
| `--case NAME` (repeatable) | all cases | Run only the named `TESTCASE`(s). Unions with `--tag`. |
| `--tag TAG` (repeatable) | all cases | Run only `TESTCASE`s carrying this tag. Unions with `--case`. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |
| `--keep-sandbox` | off | Don't delete the temporary sandbox directory; print its path. |
| `--verbose` | off | On a compile failure, print the path to the instrumented source. |
| `--coverage` | off | Compile with `--coverage`/`gcov` and report per-line coverage, remapped onto your original line numbers. |
| `--coverage-out PATH` | none | Write the full coverage report to a file. Implies `--coverage`. |
| `--coverage-json PATH` | none | Write machine-readable coverage, mapped onto the original `.cbl`'s line numbers. Implies `--coverage`. |
| `--trace` | off | Replay one test case's execution path plus the mock timeline, in order. **Requires exactly one `--case` and no `--tag`.** |
| `--trace-json PATH` | none | Write a machine-readable execution trace. Implies `--trace`. |
| `--record-expectations` | off | For every `*> STUB EXPECT <name>` comment, capture the value the program actually produced and rewrite it into a real `EXPECT`, in place. Never overwrites a hand-written `EXPECT`. Never changes the run's exit code. |

Examples:

```bash
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --junit-xml results.xml --tag happy-path
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --case "rejects negative quantity" --trace --trace-json trace.json
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --coverage-json coverage.json
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --verbose --keep-sandbox
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --record-expectations
```

`run` exits 0 only if every selected test case passed *and* the compiled
binary itself exited 0 -- a crash after the summary line still fails the
run.

## `mockymock debug`

```bash
mockymock debug <program.cbl> --cut <program.cut> --case <name> --dap-stdio [options]
```

Starts an interactive Debug Adapter Protocol (DAP) session for one test
case -- breakpoints, stepping, read-only variable inspection against your
*original* `.cbl` source. Meant to be launched by an editor (the mocky-mock
VS Code extension does this automatically), not typed by hand -- there is
no useful plain-terminal mode; the command refuses without `--dap-stdio`.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--cut PATH` | required | The `.cut` test file. |
| `--case NAME` | required, exactly one | The single test case to debug. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |
| `--dap-stdio` | required | Run the DAP adapter over stdio. |

## `mockymock lint`

```bash
mockymock lint <program.cbl> --cut <program.cut> [options]
```

Runs every static check `run` would run, before compiling anything, with
zero Docker dependency. Good for a fast inner loop, pre-commit hooks, and
CI lanes without a daemon.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--cut PATH` | required | The `.cut` test file. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |

Prints `mockymock lint: no problems found.` and exits 0 if clean, or one
`mockymock lint: <problem>` line per problem plus a count, exiting 1.

## `mockymock mutate`

```bash
mockymock mutate <program.cbl> --cut <program.cut> [options]
```

Mutation testing: measures how good a `.cut` suite actually is by
patching small changes into the program and checking whether the suite
notices ("killed") or doesn't ("survived" -- a gap in the assertions).

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--cut PATH` | required | The `.cut` test file. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |
| `--list` | off | Only list the mutants that would be generated, no Docker needed. |
| `--timeout SECONDS` | `15` | Per-mutant execution timeout; a mutant that exceeds it counts as killed. |
| `--json-report PATH` | none | Write the full machine-readable mutation report. |
| `--fail-under PERCENT` | none | Exit 1 if the mutation score is below this percentage. |

Mock bodies and terminator statements are never mutated.

## `mockymock collect`

```bash
mockymock collect --cut <program.cut> [options]
```

Lists a suite's test cases with `.cut` line numbers and tags. Parses only
the `.cut` file -- no `.cbl`, no Docker.

| Option | Default | Description |
|---|---|---|
| `--cut PATH` | required | The `.cut` test file. |
| `--json` | off | Emit machine-readable JSON instead of a human-readable listing. |

## `mockymock dashboard`

```bash
mockymock dashboard [options]
```

Serves a local, read-only, loopback-only status page showing whether
Docker and the GnuCOBOL toolchain are up. Never builds or starts
anything; runs until Ctrl-C.

| Option | Default | Description |
|---|---|---|
| `--port N` | `8765` | TCP port to serve on; `0` picks a free one. |
| `--no-browser` | off | Don't automatically open a browser window. |

## `mockymock export`

```bash
mockymock export <program.cbl> --cut <program.cut> [options]
```

Writes the instrumented (mocked) source to a file, adjusted for a real
fixed-format (z/OS) COBOL compile instead of GnuCOBOL -- validates that
the computational core compiles cleanly on the target mainframe compiler.
No Docker needed. Includes a disclaimer header noting this is a mock-only
build (every boundary is mocked or fails loudly; no real I/O executes).

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--cut PATH` | required | Defines which boundaries get mocked into the export. |
| `-o`, `--output PATH` | `<program-stem>.mainframe.cbl` | Where to write the exported source. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |
| `--case NAME` (repeatable) | all cases | Include only the named `TESTCASE`(s)' mocks. Unions with `--tag`. |
| `--tag TAG` (repeatable) | all cases | Include only tagged `TESTCASE`s' mocks. Unions with `--case`. |

If a generated line doesn't fit within column 72 after adjustment,
`export` refuses rather than writing an invalid fixed-format file.

## `mockymock analyze`

```bash
mockymock analyze [cobol-parser-args...]
```

A pass-through to the underlying cobol-parser CLI's own analysis
subcommands (`dead-code`, `program-flow`, `io-sequence`, `move-type-check`,
`linkage-check`, `language-env`, `ims-dli`, `analyze`). Everything after
`mockymock analyze` is forwarded verbatim -- those flags belong to
cobol-parser, not mockymock.

```bash
mockymock analyze dead-code ORDRPROC.cbl --compact
mockymock analyze program-flow ORDRPROC.cbl
```

## `mockymock skills install`

```bash
mockymock skills install [--project] [--force]
```

Installs this skill's own files (`SKILL.md` plus `reference/`) so a
Claude Code session picks it up. Defaults to `~/.claude/skills/mockymock`
(global -- works across every COBOL repo tested with mockymock); pass
`--project` to install into `./.claude/skills/mockymock` instead, so a
team can commit it for shared use. Refuses to overwrite an existing
install unless `--force` is given.

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
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_mockymock_skill_content.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add mockymock/cli/skills/mockymock/ tests/unit/test_mockymock_skill_content.py
git commit -m "Add packaged mockymock end-user skill content"
```

---

### Task 3: `skills_cmd.py` — copy/refuse logic + package-data declaration

**Files:**
- Create: `mockymock/cli/skills_cmd.py`
- Modify: `pyproject.toml`
- Test: `tests/unit/test_skills_cmd.py`

**Interfaces:**
- Consumes: `mockymock/cli/skills/mockymock/` from Task 2 (`SOURCE_DIR` points at it; must contain `SKILL.md` and `reference/{cut-dsl,cli-flags}.md`).
- Produces: `SOURCE_DIR: Path`, `class SkillTargetExistsError(Exception)` (has a `.target: Path` attribute), `resolve_target(project: bool) -> Path`, `install_skill(target: Path, *, force: bool = False) -> None` — Task 4's `_cmd_skills_install` imports all four names from `mockymock.cli.skills_cmd`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_skills_cmd.py
"""Tests for mockymock.cli.skills_cmd -- the copy-out logic behind
`mockymock skills install`, kept separate from cli/main.py so that
module's _cmd_skills_install can defer-import it like every other
subcommand's dependencies."""

from pathlib import Path

import pytest

from mockymock.cli.skills_cmd import (
    SkillTargetExistsError,
    install_skill,
    resolve_target,
)


def test_resolve_target_project_uses_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert resolve_target(project=True) == tmp_path / ".claude" / "skills" / "mockymock"


def test_resolve_target_global_uses_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert resolve_target(project=False) == tmp_path / ".claude" / "skills" / "mockymock"


def test_install_skill_copies_expected_files(tmp_path):
    target = tmp_path / "dest"
    install_skill(target)
    assert (target / "SKILL.md").is_file()
    assert (target / "reference" / "cut-dsl.md").is_file()
    assert (target / "reference" / "cli-flags.md").is_file()


def test_install_skill_refuses_existing_target_without_force(tmp_path):
    target = tmp_path / "dest"
    target.mkdir()
    (target / "stray.txt").write_text("local edit", encoding="utf-8")
    with pytest.raises(SkillTargetExistsError) as exc_info:
        install_skill(target)
    assert exc_info.value.target == target
    # Fail-closed: the existing directory must be left untouched.
    assert (target / "stray.txt").is_file()
    assert not (target / "SKILL.md").exists()


def test_install_skill_overwrites_with_force(tmp_path):
    target = tmp_path / "dest"
    target.mkdir()
    (target / "stray.txt").write_text("local edit", encoding="utf-8")
    install_skill(target, force=True)
    assert (target / "SKILL.md").is_file()
    assert not (target / "stray.txt").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_skills_cmd.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock.cli.skills_cmd'`.

- [ ] **Step 3: Write `mockymock/cli/skills_cmd.py`**

```python
"""Copies the packaged end-user Claude Code skill to a target directory.

mockymock ships mockymock/cli/skills/mockymock/ (a SKILL.md plus
reference/ files teaching an AI assistant how to scaffold and run .cut
tests) as package data under mockymock.cli -- setuptools only applies
package-data globs under an already-discovered package, and this
directory has no __init__.py of its own, so it rides along with
mockymock.cli the same way mockymock/runtime/docker/ and
mockymock/web/static/ ride along with their own parent packages. This
module is the implementation behind `mockymock skills install`; kept
separate from cli/main.py so that module's _cmd_skills_install can
defer-import it like every other subcommand's dependencies.
"""

from __future__ import annotations

import shutil
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parent / "skills" / "mockymock"


class SkillTargetExistsError(Exception):
    """Raised when the install target exists and --force wasn't given."""

    def __init__(self, target: Path) -> None:
        self.target = target
        super().__init__(f"{target} already exists; use --force to overwrite")


def resolve_target(project: bool) -> Path:
    """Where `mockymock skills install` writes to: the current directory's
    .claude/skills/mockymock for --project, else the user's home
    directory's -- the skill's content isn't project-specific, so a
    global install is the default and works across every COBOL repo
    tested with mockymock."""
    base = Path.cwd() if project else Path.home()
    return base / ".claude" / "skills" / "mockymock"


def install_skill(target: Path, *, force: bool = False) -> None:
    """Copy the packaged skill directory to `target`.

    Fail-closed: refuses (raises SkillTargetExistsError, leaving `target`
    untouched) if it already exists and `force` is False, so a user's
    local edits to a previously installed copy are never silently
    clobbered.
    """
    if target.exists() and not force:
        raise SkillTargetExistsError(target)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(SOURCE_DIR, target)
```

- [ ] **Step 4: Declare the package data in `pyproject.toml`**

Find this block:

```toml
[tool.setuptools.package-data]
# PEP 561: the code is fully annotated; py.typed makes the annotations
# visible to downstream mypy.
mockymock = ["py.typed"]
# Docker build context lives under the package (not repo-root docker/) so it
# ships in the wheel -- `mockymock setup` needs it under any install mode,
# including a bare `uv tool install` with no sibling checkout present.
"mockymock.runtime" = ["docker/Dockerfile"]
# Same reasoning for the dashboard's static assets: they live under the
# package and are resolved via Path(__file__), so they must be packaged
# explicitly or `mockymock dashboard` 404s under `uv tool install`.
"mockymock.web" = ["static/**/*"]
```

Replace with:

```toml
[tool.setuptools.package-data]
# PEP 561: the code is fully annotated; py.typed makes the annotations
# visible to downstream mypy.
mockymock = ["py.typed"]
# Docker build context lives under the package (not repo-root docker/) so it
# ships in the wheel -- `mockymock setup` needs it under any install mode,
# including a bare `uv tool install` with no sibling checkout present.
"mockymock.runtime" = ["docker/Dockerfile"]
# Same reasoning for the dashboard's static assets: they live under the
# package and are resolved via Path(__file__), so they must be packaged
# explicitly or `mockymock dashboard` 404s under `uv tool install`.
"mockymock.web" = ["static/**/*"]
# The packaged Claude Code skill `mockymock skills install` copies out;
# same "must be under a discovered package, resolved via Path(__file__)"
# reasoning as the two entries above.
"mockymock.cli" = ["skills/mockymock/SKILL.md", "skills/mockymock/reference/*.md"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_skills_cmd.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add mockymock/cli/skills_cmd.py pyproject.toml tests/unit/test_skills_cmd.py
git commit -m "Add mockymock.cli.skills_cmd: copy/refuse logic for the packaged skill"
```

---

### Task 4: Wire `mockymock skills install` into the CLI

**Files:**
- Modify: `mockymock/cli/main.py`
- Test: `tests/unit/test_cli_skills.py`

**Interfaces:**
- Consumes: `SkillTargetExistsError`, `install_skill`, `resolve_target` from `mockymock.cli.skills_cmd` (Task 3).
- Produces: `mockymock skills install` on the CLI — nothing later depends on this programmatically (last task).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli_skills.py
"""Tests for `mockymock skills install`'s CLI wiring."""

from pathlib import Path

from mockymock.cli.main import main


def test_skills_install_writes_to_home_by_default(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    exit_code = main(["skills", "install"])
    assert exit_code == 0
    target = tmp_path / ".claude" / "skills" / "mockymock"
    assert (target / "SKILL.md").is_file()
    out = capsys.readouterr().out
    assert f"installed -> {target}" in out


def test_skills_install_project_flag_writes_to_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    exit_code = main(["skills", "install", "--project"])
    assert exit_code == 0
    assert (tmp_path / ".claude" / "skills" / "mockymock" / "SKILL.md").is_file()


def test_skills_install_refuses_existing_target(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    target = tmp_path / ".claude" / "skills" / "mockymock"
    target.mkdir(parents=True)
    exit_code = main(["skills", "install"])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "already exists" in out
    assert "use --force" in out


def test_skills_install_force_overwrites(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    target = tmp_path / ".claude" / "skills" / "mockymock"
    target.mkdir(parents=True)
    (target / "stray.txt").write_text("local edit", encoding="utf-8")
    exit_code = main(["skills", "install", "--force"])
    assert exit_code == 0
    assert (target / "SKILL.md").is_file()
    assert not (target / "stray.txt").exists()


def test_bare_skills_command_prints_help_and_exits_1(capsys):
    # No leaf subcommand given -- same "print help, exit 1" contract as a
    # bare `mockymock` with no subcommand at all (main.py's own fallback).
    exit_code = main(["skills"])
    assert exit_code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_cli_skills.py -v`
Expected: FAIL — argparse errors with `invalid choice: 'skills'` (no such subcommand yet).

- [ ] **Step 3: Add `_cmd_skills_install` to `mockymock/cli/main.py`**

Add this function near the other `_cmd_*` functions (e.g. directly after `_cmd_collect`, around line 1278):

```python
def _cmd_skills_install(args: argparse.Namespace) -> int:
    """Copy the packaged Claude Code skill to ~/.claude/skills/mockymock
    (or ./.claude/skills/mockymock with --project). Pure file copy -- no
    Docker, no parsing -- so it's always available, same tier as
    lint/collect."""
    from mockymock.cli.skills_cmd import (
        SkillTargetExistsError,
        install_skill,
        resolve_target,
    )

    target = resolve_target(args.project)
    try:
        install_skill(target, force=args.force)
    except SkillTargetExistsError as exc:
        print(f"mockymock skills install: {exc}")
        return 1
    print(f"mockymock skills install: installed -> {target}")
    print(
        "mockymock skills install: restart Claude Code (or start a new "
        "session) to pick it up"
    )
    return 0
```

- [ ] **Step 4: Wire the `skills`/`install` subparsers in `build_parser()`**

In `build_parser()`, add this block after the `export_parser` block and before `return parser` (i.e., right before line `return parser` at the end of the function, currently around line 1722):

```python
    skills_parser = subparsers.add_parser(
        "skills", help="Manage the packaged Claude Code skill for mockymock"
    )
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command")
    skills_install_parser = skills_subparsers.add_parser(
        "install",
        help=(
            "Install the mockymock Claude Code skill (SKILL.md + "
            "reference/ files) so a Claude Code session can use it"
        ),
    )
    skills_install_parser.add_argument(
        "--project",
        action="store_true",
        help=(
            "Install into ./.claude/skills/mockymock instead of "
            "~/.claude/skills/mockymock"
        ),
    )
    skills_install_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing install at the target path",
    )
    skills_install_parser.set_defaults(func=_cmd_skills_install)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_cli_skills.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Run the full unit suite**

Run: `python -m pytest tests/unit -v`
Expected: PASS — no regressions in `test_cli.py`, `test_cli_dashboard.py`, etc.

- [ ] **Step 7: Commit**

```bash
git add mockymock/cli/main.py tests/unit/test_cli_skills.py
git commit -m "Wire mockymock skills install into the CLI"
```

---

### Task 5: Docs — README, options-reference.md, `.okf/cli.md`, `.okf/log.md`

**Files:**
- Modify: `README.md`
- Modify: `docs/options-reference.md`
- Modify: `.okf/cli.md`
- Modify: `.okf/log.md`

**Interfaces:**
- Consumes: nothing (documentation only, no code dependency).
- Produces: nothing (terminal task).

- [ ] **Step 1: Add an "AI assistant skill" section to `README.md`**

In `README.md`, insert a new section immediately after the `## Installation` section's "Contributing (local dev setup)" subsection and before `## Example & usage` (i.e., after the closing of the code block ending in `mockymock setup` / `python -m pytest tests/unit -v` and its following sentence about `tests/integration/`, currently around line 69-70):

```markdown
## AI assistant skill

mockymock ships a [Claude Code](https://claude.com/claude-code) skill
teaching an AI assistant how to scaffold, edit, and run `.cut` test
files. Install it once:

```bash
mockymock skills install
```

This writes to `~/.claude/skills/mockymock` by default (works across
every COBOL repo you test with mockymock); pass `--project` to install
into the current repo's `.claude/skills/mockymock` instead, so a team can
commit it for shared use. See `mockymock skills install --help`.
```

- [ ] **Step 2: Add a `skills` entry to `docs/options-reference.md`**

In the `## Contents` list (around line 26), add a line after the `analyze` entry:

```markdown
  - [`analyze`](#mockymock-analyze)
  - [`skills install`](#mockymock-skills-install)
```

Update the "How mockymock is invoked" section (around line 38-39) — find:

```markdown
There are eleven subcommands: `setup`, `generate`, `fixtures`, `run`,
`debug`, `lint`, `mutate`, `collect`, `dashboard`, `export`, `analyze`.
```

Replace with:

```markdown
There are twelve subcommands: `setup`, `generate`, `fixtures`, `run`,
`debug`, `lint`, `mutate`, `collect`, `dashboard`, `export`, `analyze`,
`skills`.
```

Add a new subsection after `### mockymock analyze` (after its closing
example block, before `## The `.cut` file: directives and options`,
around line 373-374):

```markdown
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
```

Add a row to the "Options quick-reference table" (around line 653, after
the `analyze` row):

```markdown
| `skills install` | no | `--project`, `--force` |
```

- [ ] **Step 3: Add a `mockymock skills` subsection to `.okf/cli.md`**

In `.okf/cli.md`, update the module-overview flow diagram (around line 21-32) — find:

```
mockymock export     -> cli.checks (static) -> splicer -> cli.mainframe_export (no Docker)
```

Replace with (adding the new line immediately after it, before the closing ` ``` `):

```
mockymock export     -> cli.checks (static) -> splicer -> cli.mainframe_export (no Docker)
mockymock skills     -> skills_cmd (no Docker, no parsing -- a copytree)
```

Also update the introductory sentence (around line 11-13) — find:

```
`mockymock/cli/main.py` is the single argparse-based entry point (`prog="mockymock"`,
`--version` from `mockymock.__version__`). It defines ten subcommands —
`setup`, `generate`, `fixtures`, `run`, `debug`, `lint`, `mutate`, `collect`, `dashboard`, `export` — each wired via `set_defaults(func=...)` and
```

Replace with:

```
`mockymock/cli/main.py` is the single argparse-based entry point (`prog="mockymock"`,
`--version` from `mockymock.__version__`). It defines twelve subcommands —
`setup`, `generate`, `fixtures`, `run`, `debug`, `lint`, `mutate`, `collect`, `dashboard`, `export`, `analyze`, `skills` — each wired via `set_defaults(func=...)` and
```

Add a new `## mockymock skills install` subsection after the
`## `mockymock export`` subsection and before `# Gotchas` (around line
568-569):

```markdown
## `mockymock skills install [--project] [--force]`

Copies the packaged Claude Code skill
(`mockymock/cli/skills/mockymock/`) to
`~/.claude/skills/mockymock` (default) or `./.claude/skills/mockymock`
(`--project`). Implementation lives in `mockymock/cli/skills_cmd.py`,
imported lazily inside `_cmd_skills_install` for the same deferred-import
reason every other subcommand uses, even though nothing here is actually
heavy (`shutil`/`pathlib` only) -- consistency with the rest of this
module.

`resolve_target(project: bool) -> Path` picks the base directory
(`Path.cwd()` or `Path.home()`); `install_skill(target, force=False)`
refuses (`SkillTargetExistsError`, fail-closed) if `target` already
exists and `force` is `False`, so a user's local edits to a previously
installed copy are never silently clobbered. The skill content itself is
declared in `pyproject.toml`'s `[tool.setuptools.package-data]` under
`"mockymock.cli"` -- it has no `__init__.py` of its own, so it rides
along with the already-discovered `mockymock.cli` package the same way
`mockymock/runtime/docker/` and `mockymock/web/static/` ride along with
theirs.
```

- [ ] **Step 4: Append a dated entry to `.okf/log.md`**

Add a new entry at the top of `.okf/log.md`, immediately after its `# mocky-mock OKF Bundle — Update Log` header (before the existing `## 2026-08-10` entry):

```markdown
## 2026-08-11 — Add `mockymock skills install` and two Claude Code skills

Two Claude Code skills: `.claude/skills/mockymock-dev/` (repo-local,
routes contributors into this OKF bundle) and a packaged end-user skill
teaching an AI assistant to scaffold/edit/run `.cut` files, installed via
the new `mockymock skills install [--project] [--force]` subcommand
(`mockymock/cli/skills_cmd.py`). Skill content lives under
`mockymock/cli/skills/mockymock/` rather than a new top-level
`mockymock/skills/` package -- setuptools `package-data` only applies
under an already-discovered package (one with `__init__.py`), so it rides
along with `mockymock.cli` the same way the Dockerfile and dashboard
static assets ride along with `mockymock.runtime`/`mockymock.web`. See
`docs/superpowers/specs/2026-08-11-mockymock-ai-skills-design.md`.
```

- [ ] **Step 5: Run the full unit suite once more**

Run: `python -m pytest tests/unit -v`
Expected: PASS — documentation-only changes, no code paths affected.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/options-reference.md .okf/cli.md .okf/log.md
git commit -m "Document mockymock skills install (README, options-reference, OKF cli.md/log.md)"
```

---

## Self-Review Notes

- **Spec coverage:** contributor skill (Task 1) ✓, end-user skill content + progressive-disclosure reference files (Task 2) ✓, packaging fix nesting under `mockymock.cli` (Task 3) ✓, `mockymock skills install` with `--project`/`--force` and fail-closed overwrite behavior (Task 3+4) ✓, README/options-reference/`.okf/cli.md`/log.md updates (Task 5) ✓. Out-of-scope items from the design doc (uninstall/list, auto-install, plugin marketplace) are intentionally absent from every task.
- **Placeholder scan:** every step has full file contents or exact find/replace text; no "TBD"/"similar to Task N" left in.
- **Type consistency checked:** `resolve_target(project: bool) -> Path` and `install_skill(target: Path, *, force: bool = False) -> None` (Task 3) match their call sites in `_cmd_skills_install` (Task 4) and their test invocations (Task 3's and Task 4's test files) exactly. `SkillTargetExistsError.target` (set in `__init__`) matches `exc_info.value.target` in Task 3's test.
