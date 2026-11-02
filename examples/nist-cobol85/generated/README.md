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
| IC102A | inter-program (called) | LINKAGE entry | green, 1 case |
| IF401M | intrinsic functions | | green, 1 |
| IX106A | indexed I/O | had 48 cases, 46 identical to one of the other two | green, 2 |
| IX301M | indexed I/O | key-only READ rows made empty `WHEN`s cobc rejected | green, 2 |
| IX401M | indexed I/O | entry is not `OPEN-FILES` | green, 4 |
| NC113M | nucleus (margins) | `PROCEDURE` / `DIVISION` / `.` on three lines | green, 1 |
| OBSQ1A | obsolete sequential | | green, 1 |
| RL101A | relative I/O | | green, 2 |
| RL301M | relative I/O | | green, 6 |
| SG302M | segmentation | | green, 1 |
| SM301M | source text (COPY) | `COPY KSM31` | green, 1 |
| SQ107A | sequential I/O | | green, 1 |
| ST110A | sort | | green, 1 |
| NC101A | nucleus | the CCVS boilerplate most programs share | refused: `UNSUPPORTED_MOCK_TARGET_LAYOUT`, `UNSUPPORTED_TERMINATOR_LAYOUT` |
| DB101A | debugging | | refused: `UNSUPPORTED_ALTER`, `UNSUPPORTED_DECLARATIVES` |
| IC222A | inter-program | nested programs | refused: `UNSUPPORTED_NESTED_PROGRAM` |

## Whole suite, 2026-11-02 (GnuCOBOL 3.1.2, native toolchain)

```bash
python scripts/nist_cobol85.py expand ../cobol-parser/examples/cobol /tmp/nist
python scripts/nist_cobol85.py check /tmp/nist --out /tmp/nist-results --jobs 4
```

459 programs, about 4 minutes on 4 cores:

- **114 green** (160 cases): every generated case passed on creation and
  again on replay, with the same result.
- **344 refused** before anything compiled, so nothing ran unmocked. Most of
  these come from the CCVS boilerplate every NIST program carries:
  `PERFORM END-ROUTINE THRU END-ROUTINE-13. CLOSE PRINT-FILE.` puts the
  mocked CLOSE on a line it shares with another statement
  (`UNSUPPORTED_MOCK_TARGET_LAYOUT`, 197 programs), and `STOP RUN` in
  `TERMINATE-CCVS` is only ever reached by falling into it
  (`UNSUPPORTED_TERMINATOR_LAYOUT`, 218). Then DECLARATIVES (88), ALTER
  (15), `UNSUPPORTED_PERFORM_THRU` (15), nested programs (12), parse
  warnings (11, mostly the communication module), SORT/MERGE forms (9).
- **1 does not compile** under `-std=mvs`: ST115A uses `CHAR` as a data
  name, a reserved word in the IBM dialect mockymock compiles with.

What a green suite covers is limited: the NIST main line starts in
`OPEN-FILES`, which falls through and `GO TO`s on into every test, while a
generated case PERFORMs its entry paragraph alone and returns at its end.
73 of the 114 green suites exercise only `OPEN-FILES`. Before 2026-11-02
they held 690 cases, most of them that same case again under branch names
it never took; generate now leaves those out and says so in a `*> NOTE:` at
the top of the suite.
