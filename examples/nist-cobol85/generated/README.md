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
| DB101A | debugging | ALTER, DECLARATIVES | green, 1, whole main line |
| IC222A | inter-program | nested programs | green, 5, whole main line |
| IC203A | inter-program | CANCEL of a program it never CALLs | green, 15, whole main line |
| NC302M | nucleus | `STOP "literal"` | green, 1 |

A case marked "whole main line" PERFORMs `OPEN-FILES THRU` the program's
last paragraph (`expected.json`'s `perform`), and the STOP RUN the program
falls into at the end returns to the test instead of ending the run.

## Whole suite, 2026-11-03 (GnuCOBOL 3.1.2, native toolchain)

```bash
python scripts/nist_cobol85.py expand ../cobol-parser/examples/cobol /tmp/nist
python scripts/nist_cobol85.py check /tmp/nist --out /tmp/nist-results --jobs 4
```

459 programs, about 10 minutes on 6 cores:

- **420 green**: every generated case passed on creation and again on
  replay, with the same result. Earlier the same day 292 were green and
  159 refused; mockymock now supports what those refusals were about:
  DECLARATIVES (USE AFTER EXCEPTION procedures run after a mocked file
  statement), STOP RUN/GOBACK reached where no EXIT verb fits (the case
  returns through a call frame), SORT/MERGE mixing a file with an INPUT
  or OUTPUT procedure, THRU ranges ending on a SECTION, ALTER, nested and
  stacked programs, CANCEL, and `STOP "literal"`.
- **25 refused** before anything compiled, so nothing ran unmocked:
  - the communication module (9 CM programs, plus DB205A and DB304M):
    GnuCOBOL does not implement the COMMUNICATION SECTION;
  - a WRITE's AT END-OF-PAGE or a nested READ with no END-READ whose
    clause cannot be re-run after a mock (SQ201M, SQ208M, SQ209M, SQ401M,
    RL401M, EXEC85);
  - a paragraph name defined in two SECTIONs (IX218A, NC102A, NC208A,
    OBNC2M);
  - a THRU range that ends before it starts (DB105A, NC102A, SG202A);
  - DB104A (a mock target inside a nested statement) and NC303M (an ALTER
    of a paragraph that is not one GO TO).
- **14 fail**, none of them a wrong generated expectation:
  - NC174A and NC211A do not compile with plain `cobc` either (switch
    conditions, `NOTHING` as a data name).
  - ST115A, ST137A, ST139A, ST140A, ST144A and ST147A name a data item
    `CHAR`, which GnuCOBOL's IBM dialect (`-std=mvs`) reserves. Plain
    `cobc` with its default dialect compiles them.
  - SQ109M and SQ110M loop forever under plain `cobc` too (the optional
    X-card lines EXEC85 drops leave their WRITE loop with no end).
  - NC401M and SQ210M finish under plain `cobc` but time out under the
    generated mocks; not looked into yet.
  - IX102A and IC114A loop waiting for a READ to report INVALID KEY / end
    of file that the generated default mock never gives.

Before 2026-11-02, a generated case PERFORMed `OPEN-FILES` alone and
returned at its end, so 73 of the 114 suites green then exercised only that
paragraph, and 344 programs were refused over the CCVS boilerplate
(`PERFORM END-ROUTINE THRU END-ROUTINE-13. CLOSE PRINT-FILE.` on one line,
and a `STOP RUN` reached only by falling into it).
