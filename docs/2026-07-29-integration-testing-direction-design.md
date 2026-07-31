# mockymock — Integration Testing Direction (`REAL` Boundaries)

Date: 2026-07-29
Status: proposed (direction notes — no phase is committed to yet)

## Motivation

mockymock is deliberately a *unit* framework: the refusal gate
(`analysis/refusal.py`) fails closed on every reachable boundary site
that has no matching `MOCK` — `UNMOCKED_CALL`, `UNMOCKED_FILE_OP`,
`UNMOCKED_SQL`, `UNMOCKED_CICS`, `UNMOCKED_DLI`,
`UNMOCKED_CONSOLE_ACCEPT`. That rule is what makes a green run
trustworthy: nothing escapes to reality by accident.

But it also caps what the framework can test. A program that is correct
in isolation can still be wrong *in combination*: a caller and its real
subprogram disagreeing on a LINKAGE layout, a writer producing records
its downstream reader can't parse, a cursor loop whose logic only breaks
against real multi-row state. Users who outgrow the unit layer today
have nowhere to go but back to the mainframe.

The direction proposed here: evolve the gate's rule from **"every
reachable boundary must be mocked"** to **"every reachable boundary must
be mocked *or explicitly declared real*"** — still fail-closed, nothing
implicit — and let each boundary class graduate to "declarable as real"
one phase at a time, cheapest and most valuable first.

Almost all of the hard infrastructure already exists: the Docker
GnuCOBOL toolchain and per-run sandbox model (`.okf/runtime.md`), the
splicer's dispatch/tally machinery, the `__MOCKYMOCK__` stdout protocol
and JUnit/JSON reporting, `TAGS`-based selection, and the DAP debugger.
Each phase below is mostly a new declaration surface in the `.cut` DSL
plus a relaxation in the refusal gate — not a new execution model.

## Phasing (value-per-effort order)

| Phase | Boundary | Mechanism | New execution machinery |
|-------|----------|-----------|-------------------------|
| 1 | Subprogram `CALL` | Compile the real `.cbl` as a module, link in-container | ~none (cobc module compile + `COB_LIBRARY_PATH`) |
| 2 | File I/O | Stage fixture files into the sandbox; golden-file assertions on outputs | file staging + diff reporting |
| 3 | Spies | Real boundary + existing tally instrumentation (`VERIFY` keeps working) | splice-shape variant only |
| 4 | SQL | Stateful mocks backed by in-memory SQLite (not real ESQL) | harness-side SQL state engine |
| 5 | Job streams | `JOBSTEP` chains: N programs through one shared sandbox | new runner loop + protocol extension |

### Phase 1 — real subprogram CALLs (component integration)

The single biggest step, and the cheapest. GnuCOBOL makes the real
thing easy: compile the collaborator as a module (`cobc -m`) alongside
the instrumented program under test, and the dynamic CALL resolves to
it at runtime via `COB_LIBRARY_PATH` pointed at the sandbox dir — all
inside the existing `mockymock-cobc` container, no image change.

Declaration is explicit, per test case (or hoisted into
`BEFORE-EACH`/`BEFORE-ALL` like `MOCK` directives are today):

```
TESTCASE "order flow with real discount module"
    USE REAL CALL "DISCRATE" FROM "src/discrate.cbl"
    MOVE 100.00 TO WS-ORDER-AMT
    PERFORM PROCESS-ORDER
    EXPECT WS-FINAL-AMT TO BE 90.00
```

- `USE REAL CALL "LIT"` covers a static CALL by literal;
  `USE REAL CALL WS-PGM` would mirror the bare-identifier dynamic-CALL
  form, resolved against the same value set `DynamicCallAnalyzer`
  already computes.
- `FROM <path>` resolves relative to the `.cut` file. The file must
  exist at check time (a `cli/checks.py`-layer error, before any Docker
  work), and its PROGRAM-ID should be verified (via cobolparser) to
  match the declared key — a mismatch is exactly the silent-wrong-module
  failure this framework exists to prevent.
- Refusal gate: a `(CALL, key)` site covered by `USE REAL` is satisfied
  the same way a `MOCK` satisfies it today. Declaring *both* a `MOCK`
  and `USE REAL` for one key in one case is a parse-time error (mirrors
  the duplicate-`MOCK` rule).
- The real collaborator's *own* boundaries (its SQL, its file I/O) are
  initially out of scope: phase 1 requires the linked module to be
  self-contained, enforced by running `mock_surface` over the
  collaborator source and refusing (new code, e.g.
  `REAL_MODULE_HAS_BOUNDARIES`) if it has reachable external sites.
  Recursive mocking inside real modules is a later, separate design.

### Phase 2 — real file I/O (fixture + golden files)

The classic batch-COBOL integration shape: real records in, real
records out. GnuCOBOL does real sequential/indexed I/O natively, and
the per-run sandbox (`runtime/sandbox.py`, always under `WORK_ROOT`)
already gives every run an isolated working directory the binary
executes in.

```
TESTCASE "end-to-end report run"
    USE REAL FILE INV-FILE FROM "fixtures/inventory-10-records.dat"
    USE REAL FILE RPT-FILE
    PERFORM MAIN-PROCESS
    EXPECT-FILE RPT-FILE MATCHES "expected/report.dat"
```

- `USE REAL FILE <select-name> [FROM <fixture>]` satisfies every file-op
  site (OPEN/READ/.../CLOSE) on that SELECT's file, the same grouping
  `mock_surface` already uses for `UNMOCKED_FILE_OP`. `FROM` stages a
  copy of the fixture into the sandbox before the run; without `FROM`
  the file starts absent (for output-only files, or for testing the
  35/FILE-NOT-FOUND path *for real*).
- The SELECT's ASSIGN target is rewritten (splice-time) to a
  sandbox-relative path, so nothing ever touches the host filesystem
  outside the sandbox — same containment rule the runtime already
  enforces.
- `EXPECT-FILE <select-name> MATCHES <path>` is a *harness-side*
  assertion, evaluated after the binary exits, byte-comparing the
  sandbox output against the golden file. Failure detail (first
  differing record/offset, actual vs expected excerpt) flows into the
  existing per-case failure reporting and JUnit/JSON output. It does
  not need the `__MOCKYMOCK__` stdout protocol at all — which also
  means it composes with per-case isolation only if each case gets its
  own staged copies; fixture staging must therefore be per-case (reset
  alongside the existing WORKING-STORAGE reset), not per-suite.
- Indexed/relative files raise a fidelity question (GnuCOBOL's ISAM
  format is not VSAM) — fine for logic testing, documented as a
  non-goal for byte-level VSAM compatibility.

### Phase 3 — spies (`VERIFY` on real boundaries)

Once a boundary can be real, keep interaction assertions working on it:
`VERIFY "DISCRATE" WAS CALLED ONCE` should count invocations even when
the CALL is real. Mock = replace + tally; **spy = pass through +
tally**. The splicer's `TallyRegistry` fields and increment sites are
unchanged — the dispatch block's body just performs the original
statement instead of the mock body. This is a splice-shape variant,
not new machinery, and it applies identically to phase-1 CALLs and
phase-2 file ops. No new DSL: a `VERIFY` whose key is covered by
`USE REAL` implies the spy splice.

### Phase 4 — SQL: stateful SQLite-backed mocks (not real ESQL)

True DB2 integration is out of reach off-mainframe, and wiring
GnuCOBOL's ODBC/ESQL path to a containerized database is a large lift
for uncertain fidelity. The pragmatic middle ground: keep `MOCK SQL`
as the declaration surface, but let a suite declare tables/rows once
and have SELECT/FETCH/UPDATE/DELETE mocks operate against an in-memory
SQLite database the *harness* manages between case setup and
assertions. Multi-statement logic (cursor loops, read-modify-write)
then behaves realistically without the author scripting every
interaction. This deserves its own design doc when its turn comes —
listed here only so the phasing shows where it sits (after files,
before job streams) and *why real ESQL was rejected*.

### Phase 5 — job streams (much later)

Batch COBOL's real integration unit is the job step chain: PGM1 writes
a file, PGM2 reads it. A `JOBSTEP` construct running N programs in
sequence through one shared sandbox would cover it — but it breaks the
"one compiled binary per suite" model (today's stdout protocol is one
PASS/FAIL line per compiled TESTCASE) and needs its own runner loop.
Explicitly not designed here; recorded so the earlier phases don't
paint it out (nothing in phases 1–4 assumes single-program runs
beyond what the runtime already assumes today).

## Cross-cutting rules (all phases)

- **Fail-closed survives.** "Real" is always an explicit per-case
  declaration. The gate's question changes from "is every reachable
  site mocked?" to "is every reachable site *covered* (mocked or
  declared real)?" — an uncovered site refuses exactly as today.
- **Layer separation.** Integration cases are slower (module compiles,
  file staging). Existing `TAGS` + `--tag` selection already provides
  the unit/integration split in CI (`--tag unit` fast lane); no new
  selection concept is needed, just a documented convention.
- **Determinism is preserved** through phase 4: real subprograms,
  fixture files, and harness-managed SQLite are as reproducible inside
  the container as mocks are. Only genuinely external state (real
  DB/MQ) threatens repeatability, and it stays mocked.
- **The DAP debugger carries over for free** — and improves: stepping
  *into* a real linked collaborator becomes possible, which the unit
  layer cannot offer.
- **Reporting shape is unchanged** (per-case PASS/FAIL, JUnit/JSON);
  phase 2 adds a new failure *detail* kind (file diff), not a new
  result kind.

## Testing (per phase, sketched for phase 1)

- **Unit**: `USE REAL` grammar (quoted/bare forms, `FROM` required for
  CALL, duplicate mock+real conflict, undeclared-path error), refusal
  gate coverage semantics (real satisfies, uncovered still refuses,
  self-containment check on the collaborator), PROGRAM-ID mismatch
  detection.
- **Integration** (Docker-gated, same skip pattern as today): a two-
  program example under `examples/` — caller + real collaborator —
  proving a green run end-to-end, a LINKAGE-layout disagreement caught
  as a real failure, and `VERIFY ... WAS CALLED` counting through the
  spy splice once phase 3 lands.

## Docs to update as phases land

- `.okf/dsl.md` (grammar), `.okf/analysis.md` (gate rule change),
  `.okf/runtime.md` (module compile / fixture staging), `.okf/cli.md`,
  `README.md`, and a dedicated dated design doc per phase before its
  implementation (this document is direction, not a substitute for
  those).

## Alternatives considered

- **Implicit real-by-default** (anything unmocked just runs for real) —
  rejected outright: silently linking whatever happens to be on the
  path, or touching real files, is the exact class of accident the
  refusal gate exists to prevent. Explicit declaration or refusal;
  no third state.
- **A separate `mockymock integrate` command / separate DSL** —
  rejected: the value is *mixing* per case (mock SQL, real CALL, real
  files in one test). One DSL, one gate, one report.
- **Real ESQL via ODBC + containerized DB for phase 4** — rejected for
  now: heavy toolchain addition (precompiler, driver, DB container
  lifecycle) for fidelity that still isn't DB2; the SQLite-backed
  stateful mock covers the actual testing need (multi-statement SQL
  logic) at a fraction of the surface.
- **Mocking recursively inside real collaborators in phase 1** —
  deferred: doubles the splicer's scope (instrumenting N sources per
  suite) before the simple self-contained case has proven the demand.
  The self-containment refusal keeps this honest rather than silent.
