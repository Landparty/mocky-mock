# mockymock

**mockymock** is a unit-test framework for COBOL. Point it at a `.cbl`
program and a `.cut` test file, and it mocks the program's external
boundaries — subprogram `CALL`s (including MQ), file I/O
(`OPEN`/`READ`/`WRITE`/...), `EXEC SQL`, `EXEC CICS`, `EXEC DLI`, and
console `ACCEPT` — compiles the instrumented copy with real GnuCOBOL,
runs it, and reports pass/fail. No mainframe, CICS region, or DB2
instance required.

It exists because static analysis alone can tell you what a COBOL
program *might* do, but not whether it actually behaves correctly.
mockymock closes that gap by compiling and running the real program,
with only its external calls and I/O swapped out for something you
control.

The original concept — mocking a COBOL program's boundaries to unit-test
it in isolation — was taken from [cobol-check](https://github.com/openmainframeproject/cobol-check).
mockymock is a total rebuild from scratch, not a fork or port: different
language (Python, not Java), different architecture (source-to-source
splicing plus a containerized GnuCOBOL toolchain, not cobol-check's own
approach), and a different boundary model (file I/O, `EXEC SQL`/`CICS`/`DLI`,
dynamic `CALL`, internal flow targets). Only the general idea carried
over.

For deep internals (DSL grammar, splicer, runtime, refusal rules), see
the [OKF knowledge bundle](.okf/index.md) — start there before making
non-trivial changes.

## Installation

### As a CLI tool

Two one-time prerequisites, then a single install command.

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
2. Authenticate git/uv to GitHub — both `samdion1994/mocky-mock` and its
   `cobolparser` dependency are private repos. Run `gh auth setup-git`
   (with the [GitHub CLI](https://cli.github.com/)), or set up an SSH
   key/PAT with `repo` read access, first. This is the single most
   common install failure, on every OS.

```bash
uv tool install git+https://github.com/samdion1994/mocky-mock.git
```

Upgrade with `uv tool upgrade mockymock`; remove with
`uv tool uninstall mockymock`.

`mockymock run`/`mockymock setup` also need a running Docker daemon
(Docker Desktop on Windows/macOS) — COBOL is compiled and executed
inside a GnuCOBOL container, so nothing else needs installing on the
host.

### Contributing (local dev setup)

```bash
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
pip install --no-deps -e .   # skips the pinned-git cobolparser dep,
                              # which would conflict with the editable
                              # sibling checkout requirements-dev.txt installed
mockymock setup           # builds the GnuCOBOL image, starts mockymock-cobc
python -m pytest tests/unit -v
```

`tests/integration/` additionally needs the Docker daemon reachable and
is skipped automatically if it isn't.

## Example & usage

A `.cut` file mocks a program's boundaries and asserts on the result:

```
TESTSUITE "INVUPDT all boundary categories"

TESTCASE "totals two records then updates and notifies"
    MOCK OPEN INV-FILE
    END-MOCK
    MOCK READ INV-FILE
        IF UT-READ-INV-FILE-TALLY > 2
            MOVE "Y" TO WS-EOF
        ELSE
            MOVE 5 TO INV-QTY
        END-IF
    END-MOCK
    MOCK SQL "UPDATE INVENTORY"
        MOVE 0 TO SQLCODE
    END-MOCK
    PERFORM MAIN-PROCESS
    EXPECT WS-TOTAL-QTY TO BE 10
    VERIFY READ INV-FILE WAS PERFORMED 3 TIMES
```

Run it:

```bash
mockymock generate ORDRPROC.cbl                   # scaffold a starter .cut
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut      # compile, run, report
mockymock lint ORDRPROC.cbl --cut ORDRPROC.cut     # static checks only, no Docker
```

The full DSL — `MOCK CALL`/`PARAGRAPH`/`SECTION`, `VERIFY`, `PROVIDER`
data tables, `BEFORE-EACH`, `FILE-STATUS IS`, the SQL `ROWS` cursor
sugar — is documented in [`.okf/dsl.md`](.okf/dsl.md).

### Worked examples

Each pairs a `.cbl` with a `.cut` and its own README. Start with
[`examples/ordrproc/`](examples/ordrproc/) (one static `CALL`) or
[`examples/invupdt/`](examples/invupdt/) (every boundary category); the
rest each add one distinctive feature.

| Example | Demonstrates |
|---------|--------------|
| [`examples/ordrproc/`](examples/ordrproc/) | Smallest possible teaching example: one static `CALL` |
| [`examples/invupdt/`](examples/invupdt/) | Every boundary category in one program (file I/O, `EXEC SQL`, MQ, `ACCEPT`), tally-driven EOF |
| [`examples/custinq/`](examples/custinq/) | `EXEC CICS` (`READ`/`RETURN`), `GOBACK` neutralization |
| [`examples/claimseg/`](examples/claimseg/) | Raw `EXEC DLI` (`GU`/`ISRT`) |
| [`examples/raterte/`](examples/raterte/) | Dynamic `CALL` through an identifier, one mock covering multiple runtime targets |
| [`examples/flowmock/`](examples/flowmock/) | Internal flow-target mocks (`MOCK PARAGRAPH` / `MOCK SECTION`) |
| [`examples/taxfile/`](examples/taxfile/) | `BEFORE-EACH` shared mocks with per-case overrides, `FILE-STATUS IS` |
| [`examples/custprog/`](examples/custprog/) | `MOCK SQL ... ROWS` cursor-fetch sugar, DCLGEN-style copybook includes |
| [`examples/statelkup/`](examples/statelkup/) | `PROVIDER`/`HEADER`/`ROW` parameterized test cases |
| [`examples/regnavg/`](examples/regnavg/) | 2-D `OCCURS` tables, `REDEFINES`, `DIVIDE ... GIVING ... ROUNDED`, `run --trace` |
| [`examples/real-world/`](examples/real-world/) | Four business-flavored programs (IMS DL/I, IMS MPP, MQ) plus `--coverage` |
| [`examples/nist-cobol85/`](examples/nist-cobol85/) | Static `CALL` against real, unmodified NIST COBOL-85 validation-suite programs |

### Beyond pass/fail

- `mockymock run --coverage` — line coverage via GnuCOBOL/gcov ([design](docs/2026-07-17-coverage-reporting-design.md))
- `mockymock run --trace` — replay one test case's execution path and mock timeline ([design](docs/2026-07-21-debug-trace-design.md))
- `mockymock debug --dap-stdio` — a real [Debug Adapter Protocol](https://microsoft.github.io/debug-adapter-protocol/) session: breakpoints, stepping, and variable inspection on your original `.cbl` ([design](docs/2026-07-22-dap-debugger-design.md))
- `mockymock collect --cut ORDRPROC.cut [--json]` — list a suite's cases with line numbers and tags, no Docker needed
- `mockymock dashboard` — a local status page (loopback only) showing at a glance whether Docker and the GnuCOBOL toolchain are up; read-only, it never builds or starts anything ([details](.okf/dashboard.md))

## Design goals

- **Run the real thing.** No reimplementation of COBOL semantics —
  GnuCOBOL compiles and executes the actual program inside Docker, so
  behavior matches a real COBOL runtime, not an approximation of one.
- **Fail closed, never silently wrong.** Anything the splicer can't
  soundly rewrite (a `GO TO` into a mock target, `ALTER`, a statement
  sharing a line with other code, a parse that produced a warning) is
  refused with a named error instead of being silently skipped or
  mis-mocked.
- **COBOL-shaped ergonomics.** Mocks, tallies, and file statuses are
  addressed by COBOL names — paragraphs, sections, files, records,
  `FILE-STATUS IS SUCCESS` — so the `.cut` DSL reads like the program
  it's testing, not like generated plumbing.
- **Minimal host footprint.** Only `uv` and Docker are required; COBOL
  compilation and execution are fully containerized and sandboxed
  (`--network none`, dropped capabilities, memory/PID limits), so it's
  safe to run untrusted `.cbl` and mock bodies, identically on Windows,
  macOS, and Linux.

## Credits

mockymock is written and maintained by [Samuel Dion](https://github.com/samdion1994).

It's built on:

- [cobol-check](https://github.com/openmainframeproject/cobol-check) —
  origin of the general concept (unit-testing COBOL by mocking its
  boundaries). mockymock shares no code or architecture with it; it was
  rebuilt from scratch.
- [GnuCOBOL](https://sourceforge.net/projects/gnucobol/) — the COBOL
  compiler and runtime every test actually executes on.
- [cobolparser](https://github.com/Landparty/cobol-parser) — the COBOL →
  AST library that mockymock's analysis and splicer are built on.
- [uv](https://docs.astral.sh/uv/) — packaging and installation.
- The [Debug Adapter Protocol](https://microsoft.github.io/debug-adapter-protocol/) —
  the wire protocol behind the interactive debugger.

mockymock is proprietary software: free to use for personal, educational,
or internal business purposes and free to share as-is, but it may not be
sold, sublicensed, or bundled into any product or service that is sold.
See the [LICENSE](LICENSE) (an end-user license agreement, not an OSI
open-source license) for the full terms.
