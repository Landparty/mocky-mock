# mockymock — MVP Design Spec

**Status:** Draft, brainstormed — not yet implemented. `mocky-mock/` has no code and is not yet a git repository.
**Date:** 2026-06-30

## 1. Problem

`cobolparser` can statically analyze a COBOL program and scaffold `.cut`-shaped
test skeletons (`CoverageAnalyzer` → `TestPlanGenerator` → `CobolCheckGenerator`),
but it cannot execute a program or verify its behavior — it has zero runtime
dependencies by design. There is no way today to actually run a COBOL program
under test, mock its external dependencies, and assert on the result.

`mockymock` is a new, separate repo that closes that gap: given a COBOL
program and a `.cut` test file, it generates an instrumented copy of the
program with mocked boundaries spliced in, compiles it with GnuCOBOL, runs
it, and reports pass/fail.

It deliberately does **not** reimplement cobol-check's Java engine or shell
out to it. It is a native Python tool whose only external dependency is
GnuCOBOL itself.

## 2. Scope: MVP

**In scope:**
- Mocking **static `CALL "LITERAL"` statements only** — the call target is
  known at parse time.
- One compiled binary per `TESTSUITE`, with multiple `TESTCASE`s dispatched
  via a generated `EVALUATE` on a "current case" flag.
- Working-storage reset between test cases (see §5.4) so cases don't leak
  state into each other.
- Copybook expansion via `cobolparser`'s existing `expand_copybooks()`.
- `.cut` file authoring assisted by auto-generated starter scaffolding from
  static analysis (you edit from there; this is not a from-scratch-only DSL).
- GnuCOBOL bootstrapped by the CLI itself (`mockymock setup`), not a
  separately documented manual install step.
- Standalone developer CLI. No backend/API integration in MVP.

**Explicitly out of scope for v1** (see §16 for what each becomes later):
- File I/O mocking (`MOCK <file> ON OPEN/READ/WRITE/...`). The splicing
  engine is built generically enough to add this without a rewrite, but no
  file-statement category is wired up in v1.
- DISPLAY mocking/capture. DISPLAY output passes straight through to stdout,
  uncontrolled and unasserted.
- EXEC SQL / EXEC CICS / EXEC DLI — no mocking support of any kind.
- Dynamic `CALL identifier` (target resolved at runtime via a data-name).
- Backend/frontend integration.
- One-binary-per-`TESTCASE` (rejected in favor of one-per-`TESTSUITE`).

## 3. Architecture Overview

```
mocky-mock/  (sibling repo to cobol-parser/, depends on it via editable install)
  cobolparser AST + analyzers  ──▶  mock surface (what's mockable)
                                          │
  .cut file ──▶ DSL parser ──▶ MockTestSuite
                                          │
            mock surface + MockTestSuite + source text
                                          │
                                          ▼
                                  splicing engine
                                          │
                                          ▼
                          instrumented COBOL source (temp sandbox)
                                          │
                                          ▼
                                  cobc -x  (compile)
                                          │
                                          ▼
                              run binary, capture stdout/exit
                                          │
                                          ▼
                          parse PASS/FAIL lines → TestSuiteResult
```

`cobolparser` stays a pure parser; it is a dependency of `mockymock`, never
the reverse.

## 4. Repository Layout

```
mocky-mock/
├── .claude/
├── .githooks/
├── .github/workflows/ci.yml       # installs GnuCOBOL on the runner before tests
├── CLAUDE.md
├── README.md
├── docs/
│   └── 2026-06-30-mockymock-mvp-design.md   (this file)
├── interface-contract.md          # exactly which cobolparser APIs this consumes
├── pyproject.toml                 # depends on cobolparser (editable install)
├── mockymock/
│   ├── cli/
│   │   └── main.py                # `mockymock setup|generate|run`
│   ├── analysis/
│   │   └── mock_surface.py        # composes IOLogger + DynamicCallAnalyzer into
│   │                               #   a "mockable boundary points" report.
│   │                               #   v1 only surfaces STATIC CALL sites;
│   │                               #   file/EXEC sites are detected but marked
│   │                               #   unsupported, not silently dropped.
│   ├── dsl/
│   │   ├── model.py                # MockTestSuite/MockTestCase/MockCallDirective/
│   │   │                           #   VerifyDirective — extensible by statement
│   │   │                           #   category (only CALL implemented in v1)
│   │   ├── parser.py                # parses .cut files: TESTSUITE/TESTCASE/MOVE/
│   │   │                           #   PERFORM/EXPECT/MOCK CALL/END-MOCK/VERIFY
│   │   └── generator.py             # auto-scaffolds a starter .cut from mock_surface
│   ├── splicer/                    # category-agnostic by design (see §5.1)
│   │   ├── source_map.py            # AST SourceLocation -> exact line ranges
│   │   ├── stub_writer.py           # comments out targeted statements in place
│   │   ├── injector.py              # splices MOCK bodies in, EVALUATE-dispatched
│   │   │                           #   across test cases, adds VERIFY tallies
│   │   ├── reset.py                 # generates UT-RESET-WORKING-STORAGE (§5.4)
│   │   └── driver.py                # generates TESTSUITE/TESTCASE driver paragraphs
│   ├── runtime/
│   │   ├── gnucobol_bootstrap.py    # `mockymock setup`: detect/install cobc (§8)
│   │   ├── compiler.py              # wraps `cobc -x`, surfaces compile errors
│   │   ├── executor.py              # runs the binary in a temp sandbox
│   │   └── sandbox.py               # per-run temp dir + cleanup
│   └── report/
│       ├── results.py               # TestResult/TestSuiteResult
│       └── formatters.py            # console + JUnit XML
├── examples/
│   └── ordrproc/                   # ORDRPROC.cbl + ORDRPROC.cut worked example
├── tests/
│   ├── unit/                       # splicer/dsl/analysis — no cobc required
│   └── integration/                # actually compiles+runs; skipped if cobc missing
└── scripts/
    └── doctor.py                   # `mockymock setup` implementation detail
```

The `splicer/` package is written against an abstract "statement category"
concept (a category knows how to: identify its statements via the mock
surface, comment them out, and accept a mock body) so that file-IO becomes a
second category later without touching `stub_writer.py`/`injector.py`. CALL
is the only category registered in v1.

## 5. How Mocking Works

### 5.1 The general mechanism

For each statement the mock surface flags as mockable and a `.cut` file
actually mocks:

1. The statement is commented out in the instrumented copy, in place, as a
   positional anchor (mirrors how cobol-check does this for its own
   CALL/file mocks — verified against its source, not assumed).
2. The corresponding `MOCK ... END-MOCK` body is spliced in at that position.
3. A tally counter increments inside the injected body, for `VERIFY`.

### 5.2 Worked example

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDRPROC.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  ORD-AMOUNT          PIC 9(5)V99.
       01  WS-DISCOUNT-PCT     PIC 9V99.
       01  WS-NET-AMOUNT       PIC 9(5)V99.

       PROCEDURE DIVISION.
       PROCESS-ORDER.
           CALL "DISCRATE" USING ORD-AMOUNT WS-DISCOUNT-PCT
           COMPUTE WS-NET-AMOUNT =
               ORD-AMOUNT - (ORD-AMOUNT * WS-DISCOUNT-PCT).
```

```cobol
*> ORDRPROC.cut
       TESTSUITE "ORDRPROC discount calculation"

       TESTCASE "10% discount reduces net amount correctly"
           MOCK CALL "DISCRATE"
               MOVE 0.10 TO WS-DISCOUNT-PCT
           END-MOCK
           MOVE 100.00 TO ORD-AMOUNT
           PERFORM PROCESS-ORDER
           EXPECT WS-NET-AMOUNT TO BE 90.00
           VERIFY "DISCRATE" WAS CALLED ONCE

       TESTCASE "Zero discount leaves amount unchanged"
           MOCK CALL "DISCRATE"
               MOVE 0.00 TO WS-DISCOUNT-PCT
           END-MOCK
           MOVE 50.00 TO ORD-AMOUNT
           PERFORM PROCESS-ORDER
           EXPECT WS-NET-AMOUNT TO BE 50.00
```

Instrumented copy that `cobc -x` actually compiles:

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDRPROC.
      *> GENERATED by mockymock — do not hand-edit.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  ORD-AMOUNT          PIC 9(5)V99.
       01  WS-DISCOUNT-PCT     PIC 9V99.
       01  WS-NET-AMOUNT       PIC 9(5)V99.

      *> --- mockymock bookkeeping ---
       01  UT-CURRENT-CASE        PIC X(3).
       01  UT-DISCRATE-TALLY      PIC 9(4) VALUE 0.
       01  UT-FAIL-COUNT          PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.

       UT-TESTSUITE-ORDRPROC-DISCOUNT.
           DISPLAY "__MOCKYMOCK__ TESTSUITE: ORDRPROC discount calculation"
           PERFORM UT-TESTCASE-001
           PERFORM UT-TESTCASE-002
           DISPLAY "__MOCKYMOCK__ TESTS RUN: 2  FAILURES: " UT-FAIL-COUNT
           STOP RUN.

       UT-RESET-WORKING-STORAGE.
      *>     one MOVE per top-level WORKING-STORAGE item, see §5.4
           MOVE 0.00 TO ORD-AMOUNT
           MOVE 0.00 TO WS-DISCOUNT-PCT
           MOVE 0.00 TO WS-NET-AMOUNT.

       UT-TESTCASE-001.
           PERFORM UT-RESET-WORKING-STORAGE
           MOVE "001" TO UT-CURRENT-CASE
           MOVE 0 TO UT-DISCRATE-TALLY
           MOVE 100.00 TO ORD-AMOUNT

           PERFORM PROCESS-ORDER

           IF WS-NET-AMOUNT NOT = 90.00
               DISPLAY "__MOCKYMOCK__ FAIL: case 001"
               ADD 1 TO UT-FAIL-COUNT
           ELSE
               DISPLAY "__MOCKYMOCK__ PASS: case 001"
           END-IF
           IF UT-DISCRATE-TALLY NOT = 1
               DISPLAY "__MOCKYMOCK__ FAIL: case 001 VERIFY DISCRATE"
               ADD 1 TO UT-FAIL-COUNT
           END-IF.

       UT-TESTCASE-002.
           PERFORM UT-RESET-WORKING-STORAGE
           MOVE "002" TO UT-CURRENT-CASE
           MOVE 50.00 TO ORD-AMOUNT

           PERFORM PROCESS-ORDER

           IF WS-NET-AMOUNT NOT = 50.00
               DISPLAY "__MOCKYMOCK__ FAIL: case 002"
               ADD 1 TO UT-FAIL-COUNT
           ELSE
               DISPLAY "__MOCKYMOCK__ PASS: case 002"
           END-IF.

       PROCESS-ORDER.
      *>     CALL "DISCRATE" USING ORD-AMOUNT WS-DISCOUNT-PCT   <- stubbed
           ADD 1 TO UT-DISCRATE-TALLY
           EVALUATE UT-CURRENT-CASE
               WHEN "001"
                   MOVE 0.10 TO WS-DISCOUNT-PCT
               WHEN "002"
                   MOVE 0.00 TO WS-DISCOUNT-PCT
               WHEN OTHER
                   DISPLAY "__MOCKYMOCK__ ERROR: DISCRATE called "
                       "from unmocked test case " UT-CURRENT-CASE
           END-EVALUATE
           COMPUTE WS-NET-AMOUNT =
               ORD-AMOUNT - (ORD-AMOUNT * WS-DISCOUNT-PCT).
```

### 5.3 Multi-test-case dispatch

Because every `TESTCASE` in a suite shares one compiled binary, a statement
mocked differently by two test cases needs all of those mocks merged into one
`EVALUATE UT-CURRENT-CASE` block at that splice site, keyed by a flag each
`UT-TESTCASE-*` paragraph sets before it runs. This is `injector.py`'s core
job and the main reason "one binary per suite" costs more in codegen
complexity than "one binary per case" would have.

### 5.4 Working-storage reset between test cases

This is mandatory, not optional, given §5.3's shared-binary model: without
it, case 002 starts with whatever case 001 left in `WORKING-STORAGE`, and
results become order-dependent.

`reset.py` walks the program's `WORKING-STORAGE` `CobolDataItem` tree (one
level deep — group items reset via their elementary children) and emits a
`UT-RESET-WORKING-STORAGE` paragraph that `MOVE`s each item back to its
declared `VALUE` clause, or to COBOL's conventional type default (`ZERO` for
numeric, `SPACES` for alphanumeric) if no `VALUE` clause exists. Every
`UT-TESTCASE-*` paragraph calls this first, before its own setup `MOVE`s.

This is a deliberate divergence from "truly undefined" COBOL memory in
exchange for deterministic, order-independent tests. A program whose logic
depends on reading genuinely uninitialized storage (rare, and arguably
already a bug) won't be faithfully reproduced — acceptable for v1.

### 5.5 Static vs. dynamic CALL

`mock_surface.py` classifies every CALL site as STATIC (`CALL "LITERAL"`) or
DYNAMIC (`CALL identifier`, target resolved at runtime — already detected by
`DynamicCallAnalyzer`). v1 only matches `MOCK CALL "X"` against STATIC sites.

If the paragraph a `TESTCASE` performs (directly or transitively) contains a
dynamic CALL, `mockymock generate`/`run` refuses with a named line reference,
the same fail-closed posture as parse errors and EXEC blocks (§10). Mocking
dynamic CALL targets is deferred to v2.

## 6. The `.cut` DSL (v1 grammar)

```
TESTSUITE "<name>"

TESTCASE "<name>"
    [ MOCK CALL "<program-literal>"
          <COBOL statements>
      END-MOCK ]*
    [ MOVE <value> TO <data-name> ]*
    PERFORM <paragraph-name>
    [ EXPECT <data-name> TO BE <value> ]*
    [ VERIFY "<program-literal>" WAS CALLED [ONCE | AT LEAST ONCE | N TIMES | NEVER] ]*
```

No `MOCK <file>`, no `MOCK CICS/SQL/DLI`, no `EXPECT DISPLAY-OUTPUT` in v1.
File extension: `.cut`.

## 7. Compile & Execution Pipeline

1. `mockymock generate <program.cbl>` → parses via `cobolparser`, expands
   copybooks via `expand_copybooks()`, runs `mock_surface.py`, writes a
   starter `<program>.cut` with one `MOCK CALL`/`TESTCASE` stub per static
   CALL site found.
2. `mockymock run <program.cbl> --cut <program.cut>` → parses `.cut`,
   refuses early if any blocking condition applies (§10), splices, writes
   the instrumented source to a temp sandbox directory.
3. `cobc -x <instrumented>.cbl -o <binary>` (dialect flags TBD — tracked as
   an implementation task, not re-litigated here; target is whatever
   GnuCOBOL flag set most closely matches IBM Enterprise COBOL semantics).
4. Run `<binary>` in the sandbox dir, capture stdout and exit code.
5. `report/results.py` parses `__MOCKYMOCK__`-prefixed lines into a
   `TestSuiteResult`; `formatters.py` prints console output and writes
   JUnit XML.

## 8. GnuCOBOL Bootstrap

`mockymock setup` (also run implicitly on first `mockymock run` if `cobc` is
not found on PATH):

1. Detect OS (Windows/macOS/Linux) and check for `cobc` on PATH.
2. If missing, drive the platform's package manager (`choco`/`winget` on
   Windows, `brew` on macOS, `apt`/`yum` on Linux) to install GnuCOBOL, or
   fall back to a documented known-good installer if no package manager is
   available.
3. Verify the installed `cobc` version and report it.

This keeps `pip install mockymock` as the only required step for the Python
side, while GnuCOBOL itself is acquired through the OS's normal channels
rather than vendored inside the package. Exact per-OS install commands are
an implementation detail to fill in when this is built, not specified here.

## 9. Copybook Handling

`mockymock` calls `cobolparser`'s existing `expand_copybooks()` /
`parse_cobol_with_expansion()` before doing anything else, and splices the
**expanded** source. `COPY` statements are never seen by `cobc` directly;
mockymock owns expansion end-to-end so it doesn't need to pass copybook
search paths through to the GnuCOBOL invocation.

## 10. Refusal Conditions

Two different granularities apply here, and they're deliberately different:

**Whole-program refusal** (the file can't be instrumented at all):
- `cobolparser` reports parse errors (`ParseResult.success` is false). A
  partial/unreliable AST isn't a safe basis for splicing anywhere in the
  file, and best-effort partial splicing was explicitly ruled out (§2).

**Per-`TESTCASE` refusal**, scoped to the statements reachable from that
case's `PERFORM` target — computed via `cobolparser`'s existing
`ProgramFlowAnalyzer` PERFORM/fall-through edges (transitively, through
other paragraphs in the same program; a `CALL` is a leaf, never traversed
into, since the called program's source isn't part of this compilation
unit):
- The reachable call graph contains a dynamic CALL (§5.5).
- The reachable call graph contains file I/O (`OPEN`/`READ`/`WRITE`/
  `REWRITE`/`DELETE`/`CLOSE`). v1 doesn't mock file I/O, so an unmocked file
  statement reached by a test would attempt real I/O against whatever the
  `ASSIGN` clause names inside the sandbox — undefined and almost certainly
  broken, since no real file is there. Refusing is safer than letting that
  run.
- The reachable call graph contains `EXEC SQL`/`EXEC CICS`/`EXEC DLI`.
- A `.cut` file's `MOCK CALL "X"` doesn't match any static CALL site
  reachable from that case's `PERFORM` target.

Per-`TESTCASE` (not whole-program) scoping for the last three matters in
practice: a realistic COBOL program almost always mixes CALL, file I/O, and
sometimes CICS/SQL across different paragraphs. Whole-program gating on any
one of those would make most real programs entirely untestable in v1, even
for the purely-computational paragraphs that don't touch them. Each test
case is judged only by what its own `PERFORM` target actually reaches.

## 11. Output Capture & Reporting

Framework PASS/FAIL/ERROR lines are prefixed `__MOCKYMOCK__` on stdout so
`report/results.py` can separate them from the program's own (unmocked,
passthrough) DISPLAY output, which shares the same stream. This is a
stopgap specific to "DISPLAY isn't mocked in v1" (§2) — if DISPLAY mocking
is added later, framework output and program output can be fully separated
instead of multiplexed-and-filtered.

## 12. Fidelity Goal: What "Behaves Like Production" Means

The target is genuine behavioral parity, not a "looks plausible" check —
but that goal has two hard boundaries worth stating explicitly so it isn't
read as a guarantee it can't keep:

- **The program runs under GnuCOBOL, not IBM Enterprise COBOL.** Already
  researched: GnuCOBOL's COMP-3/rounding and other numeric edge-case
  behavior can diverge from a real mainframe runtime. "Behaves like
  production" means *the caller's logic is compiled and actually executed*
  against author-specified boundary values — a strictly stronger check than
  cobolparser's static analysis alone — not *byte-identical mainframe
  parity*.
- **A mocked CALL is, by definition, not the callee's production behavior.**
  Mocking `DISCRATE` tests `ORDRPROC` against an *assumed contract* for
  `DISCRATE`, not `DISCRATE`'s real implementation. This is the same
  trade-off any unit test with mocks makes; worth stating plainly rather
  than letting "behaves like production" imply end-to-end validation it
  doesn't provide.

## 13. Testing Strategy (for mockymock itself)

- `tests/unit/` — `splicer/`, `dsl/`, `analysis/` modules tested without
  GnuCOBOL (pure string/AST transformations, asserted against expected
  generated source text).
- `tests/integration/` — actually invokes `cobc`, compiles and runs
  generated programs, asserts on real `TestSuiteResult` output. Marked
  (e.g. `@pytest.mark.gnucobol`) and skipped if `cobc` isn't on PATH, so the
  unit suite stays runnable without the GnuCOBOL dependency.
- CI installs GnuCOBOL on the runner so the integration suite isn't
  permanently skipped there.

## 14. Naming & Packaging

- Package/CLI name: `mockymock`.
- Test file extension: `.cut`.
- `pyproject.toml` depends on `cobolparser` via editable install
  (`-e ../cobol-parser`), matching how `backend/` consumes the other
  workspace parser libraries.
- `interface-contract.md` documents exactly which `cobolparser`
  exports/analyzers `mockymock` relies on, mirroring the existing contract
  pattern between `cobolparser` and `backend`.

## 15. Product Integration Boundary

MVP is a standalone developer CLI. The design doesn't preclude
LegacyLens's `backend/` invoking `mockymock` later (e.g. a "run generated
tests" action surfaced in `frontend/`), but no API surface, sandboxing
model, or multi-tenant concern is designed or built for that in v1 — it's
an acknowledged future direction, not a requirement shaping MVP decisions.

## 16. Open Questions for v2+

These are intentionally deferred, not forgotten:

- File I/O mocking (`MOCK <file> ON OPEN/READ/WRITE/...`) — mechanism
  already researched (matches cobol-check's actual approach: hoist FD
  record layout into WORKING-STORAGE, comment out OPEN/READ/WRITE/REWRITE/
  DELETE/CLOSE, splice mocks the same way as CALL).
  - SEQUENTIAL/RELATIVE files are binary length-prefixed; INDEXED files are
    backed by an opaque ISAM library (BDB/VBISAM) — neither matters for
    this splicing approach since the real file is never touched, only the
    record area in memory.
- DISPLAY mocking/`EXPECT DISPLAY-OUTPUT` — needed for "every output" to be
  literally true; deferred because raw passthrough is acceptable for v1.
- EXEC SQL / EXEC CICS / EXEC DLI first-class `MOCK ... ON <action> ...`
  grammar (confirmed target architecture, three separate action
  vocabularies, real scope — not started in v1).
- Dynamic CALL mocking.
- One-binary-per-`TESTCASE` as an alternative if the `EVALUATE` dispatch
  merging in `injector.py` proves too complex or fragile in practice.
- Concrete `cobc` dialect flags for the "behaves like production" goal.
- Backend/frontend integration surface.
