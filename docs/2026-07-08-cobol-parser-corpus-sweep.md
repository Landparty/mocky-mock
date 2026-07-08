# Sweeping the cobol-parser example folder through mockymock

*2026-07-08*

## What this is

The sibling **cobol-parser** project ships a large example corpus under
`examples/cobol/`: the public-domain **NIST COBOL-85 validation suite**
(459 `.CBL` programs) plus 24 real-world IBM/GnuCOBOL programs under
`examples/cobol/shamrice/`. This is a ready-made, unmodified, real-world
COBOL corpus, so it is a good stress test for mockymock end to end:
`generate` a starter `.cut`, then `run` it (splice → compile with GnuCOBOL
in the `mockymock-cobc` container → execute → assert).

This note records what happened, the taxonomy of what blocks a clean mock,
and the curated set of programs that now pass end to end (committed under
`examples/nist-cobol85/`). Numbers are from GnuCOBOL 3.2.0 in the container
and cobol-parser at the commit vendored alongside this sweep.

## Headline

- **NIST (459 programs).** `mockymock generate` produces a `.cut` for
  **187**; of those, **155** contain at least one mockable boundary. Run
  through the full GnuCOBOL pipeline with their *auto-generated* scaffold,
  **2** pass, **150** are refused, **3** fail to build/run.
- **shamrice (24 programs).** **20** are refused at `generate` because
  cobol-parser drops AST content on the extended constructs these programs
  use; the remaining 4 have no mockable boundary (3) or hit SORT/MERGE at
  run (1).
- **Curated result.** Four NIST programs, hand-finished into passing
  end-to-end examples (5 test cases total), live in
  `examples/nist-cobol85/` with an integration test
  (`tests/integration/test_nist_cobol85_examples.py`). All compile and run
  for real under GnuCOBOL.

The low clean-pass rate is *not* a mockymock defect — every refusal is a
loud, correct fail-closed. The corpus is simply hostile to boundary mocking
for the reasons below, and the auto-scaffold is a starter, not a finished
test.

## NIST `generate` outcomes (459 programs)

| Outcome | Count |
|---------|------:|
| `.cut` generated (has ≥1 mockable boundary) | 155 |
| `.cut` generated (no mockable boundary — empty scaffold) | 32 |
| refused `PARSE_WARNING` | 222 |
| refused `UNSUPPORTED_DECLARATIVES` | 38 |
| refused `UNSUPPORTED_ALTER` | 4 |
| refused `UNRESOLVED_COPYBOOK` | 4 |
| parse error / other | 4 |

## NIST full-pipeline outcomes (the 155 with boundaries, auto-scaffold)

| Outcome | Count | Notes |
|---------|------:|-------|
| **PASS** | 2 | `IC117M`, `OBIC1A` — isolated CALL paragraphs, no print fall-through |
| refused `UNMOCKED_FILE_OP` | 141 | CCVS print fall-through (see below) |
| refused `UNSUPPORTED_SORT_MERGE` | 6 | |
| refused `UNMOCKED_CALL` / `UNMOCKED_CANCEL` | 2 | scaffold missed a reachable CALL/CANCEL |
| refused `UNSUPPORTED_MOCK_TARGET_LAYOUT` | 1 | |
| FAIL / build error | 3 | `IC109A`, `IC110A`, `SQ303M` |

## Root causes (the useful part)

### 1. `PARSE_WARNING` — cobol-parser drops AST content (dominant blocker)

222 of 459 NIST programs and 20 of 24 shamrice programs are refused before
mockymock does anything, because cobol-parser emits a parse warning that it
skipped tokens ("Unparsed tokens starting at 'X' … content dropped from the
AST"). mockymock **fail-closes** on this: splicing an AST that is missing
program behavior would silently drop that behavior from the test.

The constructs that trip it, counted across the shamrice corpus:

| Trigger token | Count | Construct |
|---------------|------:|-----------|
| `SPACE` / `SPACES` | 56 | figurative constant as a `DISPLAY` operand (`DISPLAY SPACE`) |
| `AT` | 32 | screen positioning (`DISPLAY … AT LINE … COLUMN`, `ACCEPT … AT`) |
| `WITH` | 13 | `DISPLAY/ACCEPT … WITH NO ADVANCING` and friends |
| `(` | 6 | expression/subscript in an unsupported clause |
| `LINE` | 4 | screen positioning |
| `SECURE`,`TIMEOUT`,`AUTO-SKIP`,`NO-ECHO`,`UPPER` | 1 each | extended `ACCEPT` clauses |
| `INITIATE`,`TERMINATE` | 1 each | Report Writer |

This is a **cobol-parser coverage gap**, not a mockymock one; it is written
up on the cobol-parser side in `reports/cobol-parser-example-parse-gaps.md`.
It caps how much of a real-world GnuCOBOL corpus mockymock can reach today.

### 2. CCVS print fall-through — why the auto-scaffold gets refused

Every NIST program *is* the CCVS85 self-checking harness: it OPENs a
`PRINT-FILE`, runs its feature tests, and WRITEs a formatted pass/fail
report, and paragraphs **fall through** into that reporting machinery.
`mockymock generate` emits one test case per paragraph mocking only that
paragraph's own boundaries — so a CALL-test paragraph that falls through
into the shared `WRT-LN` / `PRINT-DETAIL` paragraphs reaches a `WRITE` the
test case does not mock, and the run is correctly refused with
`UNMOCKED_FILE_OP`. This accounts for 141 of the 150 refusals.

The fix is per-program hand-finishing, and it is exactly what the curated
examples show:

- **Bound the entry** with `PERFORM <first> THRU <last>` so reachability
  stops before the harness's `CLOSE PRINT-FILE` (which, un-mocked and with
  the file never opened, aborts at runtime with `file not open
  (status = 42)`).
- **Mock every boundary that is still reachable**, including the shared
  report `WRITE` when the range reaches it (as `IC101A` does).

### 3. Structural refusals (correct, and worth knowing)

- **`DECLARATIVES` (38)** and **`ALTER` (4)** are refused program-wide by
  design — USE procedures and runtime GO-TO rewriting can't be modeled as
  boundaries.
- **`SORT`/`MERGE` (6)** are refused — they are algorithms plus an
  INPUT/OUTPUT PROCEDURE contract, not a boundary.
- **Line-shared statements** are not mockable: NIST writes
  `PERFORM END-ROUTINE THRU END-ROUTINE-13. CLOSE PRINT-FILE.` on one line,
  so that `CLOSE` is never offered as a boundary.

### 4. Subprograms compiled as a main (`IC109A`, `IC110A`)

These declare `PROCEDURE DIVISION USING …` — they are *called* subprograms,
not mains. mockymock builds the program under test with `cobc -x` (an
executable), and GnuCOBOL rejects that: *"executable program requested but
PROCEDURE/ENTRY has USING clause."* A program with a `USING` procedure
header can only be the *target* of a mocked CALL, not the top-level program
under test. Worth a clearer up-front refusal in mockymock rather than a raw
`cobc` error surfaced as a build failure — noted as a follow-up.

## Reproducing

`generate` is parse-only (no Docker); the full pipeline needs the
`mockymock-cobc` container (`mockymock setup`). The measurement harness used
here is the same shape as `scripts/corpus_sweep.py`, pointed at
`../cobol-parser/examples/cobol`.
