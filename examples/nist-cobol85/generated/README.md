# NIST CCVS85 sample for generated suites

A sample of the public-domain NIST COBOL-85 validation suite, used to check
the path LegacyLens "Create tests" takes for every program of a load module:
the runner's `tests` job scaffolds the suite (`mockymock generate
--scenarios all`), fills its expected values from a run (`mockymock run
--record-expectations`) and plays it; "Run tests" then plays the recorded
suite again. `tests/integration/test_nist_generated_suites.py` runs that for
each program here and holds it to `expected.json`: a green program must
pass every case on creation and on replay, a refused one must stay refused
with the same codes.

The programs are cobol-parser's `examples/cobol/` entries after NIST's
EXEC85 step (X-cards substituted, optional-code lines dropped), done by
`python scripts/nist_cobol85.py expand` with the values GnuCOBOL's own
`tests/cobol85` uses. Expanded, each one runs under plain `cobc -x` and
reports `NO TEST(S) FAILED`.

| Program | Module | Why it is here | Expected |
|---|---|---|---|
| IC102A | inter-program (called) | LINKAGE entry, its own `THRU CALL-EXIT-001` | green, 1 case |
| IF401M | intrinsic functions | | green, 1 |
| IX106A | indexed I/O | had 48 cases, 46 identical to one of the other two | green, 2 |
| IX301M | indexed I/O | key-only READ rows made empty `WHEN`s cobc rejected | green, 2 |
| IX401M | indexed I/O | entry is not `OPEN-FILES` | green, 4 |
| NC113M | nucleus (margins) | `PROCEDURE` / `DIVISION` / `.` on three lines | green, 1, whole main line |
| OBSQ1A | obsolete sequential | | green, 1, whole main line |
| RL101A | relative I/O | | green, 3, whole main line |
| RL301M | relative I/O | | green, 6 |
| SG302M | segmentation | | green, 1 |
| SM301M | source text (COPY) | `COPY KSM31` | green, 1 |
| SQ107A | sequential I/O | | green, 8, whole main line |
| ST110A | sort | | green, 1 |
| NC101A | nucleus | the CCVS boilerplate most programs share; all 93 tests in one case | green, 1, whole main line |
| DB101A | debugging | | refused: `UNSUPPORTED_ALTER`, `UNSUPPORTED_DECLARATIVES` |
| IC222A | inter-program | nested programs | refused: `UNSUPPORTED_NESTED_PROGRAM` |

A case marked "whole main line" PERFORMs `OPEN-FILES THRU` the program's
last paragraph (`expected.json`'s `perform`), and the STOP RUN the program
falls into at the end returns to the test instead of ending the run.

## Whole suite, 2026-11-03 (GnuCOBOL 3.1.2, native toolchain)

```bash
python scripts/nist_cobol85.py expand ../cobol-parser/examples/cobol /tmp/nist
python scripts/nist_cobol85.py check /tmp/nist --out /tmp/nist-results --jobs 4
```

459 programs, about 9 minutes on 4 cores:

- **292 green** (870 cases): every generated case passed on creation and
  again on replay, with the same result. 266 of them run the whole main line
  (230 `PERFORM OPEN-FILES THRU CCVS-999999`); 11 still PERFORM
  `OPEN-FILES` alone, where generate keeps the bare PERFORM (the rules are
  in `.okf/dsl.md`).
- **159 refused** before anything compiled, so nothing ran unmocked:
  DECLARATIVES (88), a terminator layout still unsupported (26), ALTER (15),
  `UNSUPPORTED_PERFORM_THRU` (15), nested programs (12), parse warnings
  (11, mostly the communication module), SORT/MERGE forms (9), and a few
  others.
- **8 fail**, none of them a wrong generated expectation:
  - NC174A, NC211A and ST115A do not compile under `-std=mvs` even with
    plain `cobc` (switch conditions, `NOTHING` and `CHAR` as data names).
  - SQ109M, SQ110M and SQ210M never finish: the main line now reaches a
    loop that does not end under GnuCOBOL (plain `cobc` on SQ109M writes
    gigabytes of output too). SQ109M and SQ110M were green before only
    because their cases stopped after `OPEN-FILES`.
  - IX102A and IC114A loop waiting for a READ to report INVALID KEY / end
    of file that the generated default mock never gives.

Before 2026-11-02, a generated case PERFORMed `OPEN-FILES` alone and
returned at its end, so 73 of the 114 suites green then exercised only that
paragraph, and 344 programs were refused over the CCVS boilerplate
(`PERFORM END-ROUTINE THRU END-ROUTINE-13. CLOSE PRINT-FILE.` on one line,
and a `STOP RUN` reached only by falling into it).
