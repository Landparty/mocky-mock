# REGNAVG — subscripted tables, REDEFINES, DIVIDE ROUNDED, and `--trace`

A small regional-sales program: `1000-CALCULATE-REGION-1-AVERAGE` and
`2000-CALCULATE-REGION-2-AVERAGE` each sum three months of sales for their
own region into a two-dimensional `OCCURS` table, divide to get that
region's average, and call a notification subprogram when the average
clears a threshold. Two paragraphs, not one loop over both regions, is a
deliberate choice — see "Why three cases, and why two paragraphs" below.
It exists to prove four features that, until now, were only proven by
unit/integration tests, never by a worked example.

| Feature | Demonstrated by |
|---------|-----------------|
| Subscripted `.cut` `MOVE`/`EXPECT` targets | `WS-MONTH-AMT(1, 1)` (comma+space), `WS-MONTH-AMT(2 1)` (space-separated), `WS-MONTH-AMT(1,3)` (no-space) — all three forms `_SUBSCRIPTED_NAME` accepts, used across both `MOVE` and `EXPECT` |
| `REDEFINES` data items | `WS-REGION-AVG-DISPLAY`/`WS-REGION-AVG-NUMERIC` both `REDEFINES WS-REGION-AVG` (two siblings aliasing one field, the same shape as the regression fixture in `tests/unit/test_reset.py`) |
| `DIVIDE ... GIVING ... ROUNDED` | Region 2: `50.00 + 50.00 + 51.10 = 151.10`, `/ 3 = 50.3666...` — `ROUNDED` must give `50.37`, not the truncated `50.36` |
| `run --trace` | See below — a real captured trace of the region-1 case, including which mock fired |

## Why three cases, and why two paragraphs

Each `TESTSUITE` compiles to a single binary; every case runs in it, and
WORKING-STORAGE resets between cases rather than starting a fresh process.
Proving that reset actually covers `WS-REGION-AVG-TABLE` (a group with no
`VALUE` clause of its own, `OCCURS`-of-`REDEFINES-group`) needs a case
whose own execution can't have produced the value being checked — otherwise
a passing `EXPECT` is ambiguous between "reset worked" and "this run's own
arithmetic happened to write the same thing." That's why the program is
split into **two paragraphs, one per region**, instead of one paragraph
looping over both: each test case `PERFORM`s only one region's paragraph,
so the *other* region's average is never touched by that run at all.

- **Case 1** `PERFORM`s region 1 only; region 2's average — read through
  both `REDEFINES` siblings — is checked at `0`, its clean starting value.
- **Case 2** `PERFORM`s region 2 only (and needs `ROUNDED`); region 1's
  average, `100.00` from case 1, is checked back at `0` — and case 2's own
  execution path never touches region 1's slot, so this is only possible
  if reset actually ran between cases.
- **Case 3** `PERFORM`s region 1 again with new data, never touching
  region 2; region 2's average — `50.37` from case 2 — is checked back at
  `0`. This is the load-bearing proof for the `REDEFINES` group
  specifically, locked down by
  `tests/integration/test_regnavg_example.py::test_regnavg_fails_when_a_stale_redefines_value_is_asserted`,
  which asserts case 2's leftover value on purpose and confirms it
  actually fails:

  ```
  [FAIL] a third case's fresh region 1 data doesn't inherit an earlier case's region 2 average
         expected WS-REGION-AVG-DISPLAY(2) = "0005037", got 0000000
  ```

The rounding assertion is load-bearing too
(`test_regnavg_fails_when_rounded_expectation_is_truncated`): swapping
`EXPECT WS-REGION-AVG(2) TO BE 50.37` for the truncated `50.36` fails
against real GnuCOBOL —

```
[FAIL] region 2 rounds up to 50.37, not truncated to 50.36
       expected WS-REGION-AVG(2) = 50.36, got 00050.37
```

## Two cobolparser gaps this example works around, verified against the exact pinned commit

`DIVIDE`s in the `.cbl` target an unsubscripted scratch field
(`WS-REGION-AVG-SCRATCH`), then `MOVE` it into the table cell, rather than
`DIVIDE ... GIVING WS-REGION-AVG(1) ROUNDED` directly. Not stylistic —
verified in an isolated venv pinned to the exact commit
`pyproject.toml`/`ci.yml` pin (`4db8394`, "consume `ROUNDED` after
`DIVIDE`/`MULTIPLY` `GIVING`"): a **subscripted** `GIVING` target still
warns `PARSE_WARNING` there. Subscript support for arithmetic `GIVING`
targets lands two commits later, `4917576` ("fix silent data loss in ...
arithmetic clauses") — not yet adopted by this repo's pin. Using an
unsubscripted scratch field sidesteps it entirely while still exercising
`ROUNDED` for real.

`CALL "LOGALERT"` likewise never takes the average as an argument
(`CALL "LOGALERT" USING WS-ALERT-STATUS` only). Confirmed the same way: a
`CALL ... USING` argument that's a subscripted table element isn't parsed
outside a `PERFORM VARYING` body, at every cobolparser commit tested —
this one is a separate, still-open gap, unrelated to the `ROUNDED` fix.

Every claim above was checked against a throwaway venv built with
`pip install --no-deps "git+file:///../cobol-parser@4db8394..."` (not the
sibling checkout's `HEAD`, which had already raced two commits ahead) —
`lint`/`run`/`--trace` output in this README was captured from that same
pinned environment.

## `CALL "LOGALERT"` is reachable in every case, not just the ones that fire it

The `CALL` sits inside `IF WS-REGION-AVG-SCRATCH > WS-THRESHOLD`, but
mockymock's reachability check is static: the `CALL` is reachable from
each case's `PERFORM` target regardless of whether that case's data
actually trips the threshold, so every case needs a `MOCK CALL "LOGALERT"`
or it refuses `UNMOCKED_CALL`. Declared once in `BEFORE-EACH` here since
all three cases want the identical mock body; only region 1's average
(`100.00`) clears the `75.00` threshold, so `VERIFY` differs per case
(`WAS CALLED ONCE` vs `WAS CALLED NEVER`) even though the mock itself
doesn't.

## Debugging with `--trace`

```bash
mockymock run examples/regnavg/REGNAVG.cbl --cut examples/regnavg/REGNAVG.cut \
    --case "region 1 divides evenly and clears the alert threshold" --trace
```

Real output (captured against GnuCOBOL in the `mockymock-cobc` container,
from the pinned-commit environment described above):

```
Execution trace for case: region 1 divides evenly and clears the alert threshold
  mocks fired, in order:
    1. CALL LOGALERT
  statements executed: 16
    line     45  paragraph  1000-CALCULATE-REGION-1-AVERAGE
    line     46             MOVE
    line     47             PERFORM
    line     48             UNTIL
    line     49             ADD
    line     47             VARYING
    line     48             UNTIL
    line     49             ADD
    line     47             VARYING
    line     48             UNTIL
    line     49             ADD
    line     47             VARYING
    line     48             UNTIL
    line     51             DIVIDE
    line     53             MOVE
    line     54             IF
```

Note what's *missing*: the `CALL "LOGALERT"` line itself never appears in
the statement path — it's spliced away and replaced with generated
dispatch code, which the same original-line remap used by
`--coverage-json` deliberately excludes. The mock-fired list above it is
what tells you it ran.

## Run it

```bash
mockymock run examples/regnavg/REGNAVG.cbl --cut examples/regnavg/REGNAVG.cut
```
