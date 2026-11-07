# mockymock: real subprogram CALLs (`USE REAL CALL`)

Date: 2026-11-01
Status: implemented. This is phase 1 of
[2026-07-29-integration-testing-direction-design.md](archive/2026-07-29-integration-testing-direction-design.md),
with one change to that plan: the real program's own boundaries are mocked
by the suite instead of being refused.

## Why

LegacyLens now resolves load modules: an entry program and every
subprogram it reaches through static and dynamic CALLs. A unit suite mocks
each of those CALLs, so it never runs the caller and the callee together.
A caller and its subprogram can then disagree on a LINKAGE layout, a
return code or a unit of measure, and every unit suite still passes.

A load-module suite runs the entry program and its in-module subprograms
for real. It still mocks everything that leaves the module: CALLs to
programs outside it, files, DB2, CICS, IMS and MQ, including those inside
the subprograms.

## The DSL

```
TESTSUITE "PAYMAIN load module"

BEFORE-EACH
    USE REAL CALL "PAYCALC" FROM "PAYCALC.cbl"
    MOCK CALL "DATEUTL"
        MOVE "20261101" TO WS-RUN-DATE
    END-MOCK
END-BEFORE

TESTCASE "prices two employees through the real PAYCALC"
    MOCK READ EMP-FILE ROWS
        (EMP-ID = "E00001", EMP-HOURS = 40, EMP-GRADE = "A1")
    END-MOCK
    MOCK SQL "SELECT HOURLY_RATE"        *> a statement inside PAYCALC
        MOVE 0 TO SQLCODE
        MOVE 20.00 TO WS-RATE            *> PAYCALC's own data item
    END-MOCK
    PERFORM 0000-MAIN
    EXPECT WS-TOTAL-PAY TO BE 800.00
    VERIFY CALL "PAYCALC" WAS CALLED ONCE
```

- `USE REAL CALL "X" FROM "<path>"` is allowed wherever a `MOCK` is:
  in a TESTCASE, BEFORE-EACH or BEFORE-ALL. The path is relative to the
  `.cut` file. It is a `MockDirective` of category CALL with
  `real_source` set, so precedence is unchanged (TESTCASE over BEFORE-EACH
  over BEFORE-ALL), and a `MOCK CALL "X"` in one case overrides a shared
  `USE REAL CALL "X"`. A MOCK and a USE REAL of the same key in one block
  is the usual duplicate error.
- A static CALL by literal runs a real program. Since 2026-11-02 a
  dynamic `CALL WS-PGM` does too, when the identifier holds a real
  program's name; any other value goes to its `MOCK CALL WS-PGM`
  (docs/2026-11-02-real-dynamic-call-design.md).
- A MOCK in the suite answers the matching site in any program of the
  binary. Its body runs in that program, so it names that program's data
  (`WS-RATE` above is PAYCALC's).
- `VERIFY CALL "X"` counts real calls: the dispatch adds to the tally,
  then runs the CALL as written (a spy).

## How it runs

One suite is still one binary, entered through one program.

1. **Static checks** (`analysis/real_programs.py`, step 7a of
   `cli/checks.py`; `lint` and `run` share them):
   - every `FROM` file exists, and one program is named with one file;
   - the file parses and its PROGRAM-ID is the CALL key
     (`REAL_PROGRAM_ID_MISMATCH`), so a wrong file can't be linked
     without anyone noticing;
   - **every** boundary site of the real program must be answered in
     **every** case that makes it real (`UNMOCKED_*`, with the snippet to
     add). There is no reachability narrowing: the program is entered at
     the top of its PROCEDURE DIVISION, and asking for a mock it might not
     need is safe, while running an unmocked boundary is not. `GOBACK`,
     `EXIT PROGRAM` and `CANCEL` run as written. A `STOP RUN` is a warning
     (`REAL_PROGRAM_STOP_RUN`), because it ends the whole test binary if a
     case reaches it;
   - the data names in the mocks that answer the real program are checked
     against that program (`UNKNOWN_DATA_NAME ... of PAYCALC`);
   - the entry program's own checks see the suite without the directives
     that answer only real-program sites, and without their VERIFYs
     (`entry_program_view`). Otherwise they would be reported as unmatched
     mocks of the entry program.
2. **Codegen** (`splicer/real_programs.py`):
   - each real program is spliced with the same suite and registry
     (`splice_program`), and its DATA DIVISION EXEC SQL is transformed;
   - the driver's `UT-CURRENT-CASE`, `UT-FAIL-COUNT`, `UT-EARLY-EXIT` and
     every tally become `EXTERNAL` items, declared identically in every
     program (`share_driver_state`). Their `VALUE` clauses move into the
     suite paragraph's first statements, since EXTERNAL items take none;
   - `UT-MOCK-STATUS` stays local to each program. If it were shared, a
     real program's mocks would overwrite the caller's outcome while the
     caller's CALL is still inside its dispatch;
   - the WORKING-STORAGE reset gains `CANCEL "X"` per real program, so each
     case starts the subprogram from its VALUE clauses;
   - the entry program's `CALL "X"` dispatch, for a case where X is real,
     adds to the tally and runs the original statement (`real_statement`
     in `build_site_dispatch`). The statement's own ON EXCEPTION clauses
     run as part of it, and `UT-MOCK-STATUS` stays at SPACES, so the
     lifted-clause guard selects nothing.
3. **Compile**: `compile_source(main, extra_sources=[real_X.cbl, ...])`
   runs `cobc -x main.cbl real_X.cbl ...`, the same flags on both
   toolchains. A literal CALL resolves to the program linked into the
   executable, and `CANCEL` resets it.

## `generate --real`

`mockymock generate PAYMAIN.cbl --real PAYCALC.cbl` scaffolds the entry
program as usual (data-driven by default), then `dsl/module_suite.py`:

- drops each `MOCK CALL "PAYCALC"` block, and the lines naming the CAPTURE
  targets it declared, and writes `USE REAL CALL "PAYCALC" FROM "..."`
  into BEFORE-EACH;
- adds a placeholder MOCK (the same `directive_snippet` the refusal fix
  text uses) for every boundary of each real program to BEFORE-EACH, so
  the scaffold passes the gate as written. A CALL from one real program to
  another becomes a USE REAL CALL as well.

Then `run --record-expectations` fills the `STUB EXPECT` lines from a first
run, as for any scaffold.

## Not supported yet

- `debug`, `export` and `mutate` refuse a suite with USE REAL CALL
  (`REAL_CALL_UNSUPPORTED`). They compile one program.
- `--coverage` and `--trace` cover the entry program only.
- No `IN PROGRAM` qualifier: a MOCK whose key matches sites in two
  programs answers both.
- CICS EIB synthesis and `CAPTURE ... INTO` a synthesized `UT-CAP-` field
  are applied to the entry program only.
- Real files (`USE REAL FILE`), SQLite-backed SQL and job-step chains are
  phases 2, 4 and 5 of the direction document.

## Tests

`tests/unit/test_real_call.py` covers the grammar, the specs, the gate,
the views, the shared state, the dispatch and `generate --real`.
`tests/integration/test_real_call.py` covers the worked example
(`examples/paymod/`), a LINKAGE layout mismatch caught as a failure, a
fresh subprogram per case, and a `generate --real` scaffold that runs.
