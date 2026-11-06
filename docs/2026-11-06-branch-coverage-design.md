# Paragraph and branch coverage of a suite run: design

Date: 2026-11-06. Code: `mockymock/report/branch_coverage.py`, `mockymock run --branch-coverage FILE`.


**Question it answers:** which paragraphs and which branches of each program did the recorded integration tests actually run, per program and per application?

**How it is measured (mocky-mock).** `mockymock run --branch-coverage FILE` compiles the suite with GnuCOBOL's statement trace (`-ftraceall`, the same trace `run --trace` uses) and reads the whole trace of every case, instead of gcov. The trace works on every GnuCOBOL 3.x (gcov needs `cobc --coverage`, which 3.1 lacks), and it records the *order* statements ran in, which is what tells an IF's false outcome apart from its true one.

* **Paragraphs:** every paragraph of the program (from the cobol-parser AST) and whether the trace entered it.
* **Branches:** for every `IF`, a true and a false outcome; for every `EVALUATE`, one outcome per `WHEN` group, `WHEN OTHER`, or "no WHEN matched" when there is no OTHER. An outcome is covered when the statement traced right after the IF (after the EVALUATE's WHEN tests) is the first statement of that branch. A branch with no statement of its own (an empty ELSE, a `WHEN` whose body is only `NEXT SENTENCE`) is decided by elimination when it can be, and listed as not measurable otherwise. Nothing is guessed.
* **Statements:** statement lines run / statement lines in the program.
* Real subprograms linked into a load-module suite (`USE REAL CALL`) are measured too, each under its own program id. Line numbers are the original file's (copybook lines name the copybook).

The JSON (`version: 1`) lists each program's totals and every paragraph and branch outcome with its line and hit count, so it can be merged across suites.

**Backend.** The runner adds `--branch-coverage` to every suite of a tests job and posts the document with the suite's result. The backend keeps it on the job (`OracleJob.result`), then:

* `GET /load-modules/{id}/integration-tests/coverage`: the latest finished tests run of the module, merged per program across its suites (union of covered outcomes, hits summed).
* `GET /applications/{id}/test-coverage`: the same over every load module of the application, plus the programs of the application that no test reaches at all (shown as 0%, not left out).

**Frontend.** A "Coverage" tab in the load-module "Integration tests" dialog (per program: paragraphs, branches, statements, with the not-covered paragraphs and branches listed by line), and a "Test coverage" tab on the application page (one row per program, sortable, programs without tests flagged).


## Implementation notes

* `branch_coverage.program_points(ast, lines)` walks the PROCEDURE DIVISION of the cobol-parser AST: every paragraph, every statement line, every `IF` (first statement of THEN and of ELSE) and every `EVALUATE` (first statement of each WHEN group and of OTHER).
* The trace is the one `run --trace` reads (`COB_TRACE_FORMAT '%P|%S|%L'`); `TraceEntry.program` (the `%P` field) splits a load-module trace per program.
* Lines go instrumented -> normalized (`coverage.build_normalized_line_map`) -> original (`build_normalized_to_original_map` or the expansion's source map), so a branch is reported at its line in the file the user edits.
* A branch is *not measurable* (listed, never counted either way) when two statements of the same kind share a line, or when THEN and ELSE (or two WHEN bodies) start on the same line: the trace cannot tell them apart.
* The document (`version: 1`): `cutFile`, `casesRun`, `programs[]` with `programId`, `programFile`, `paragraphs`, `branches`, `statements`, each `{total, covered, items[]}`; branch items carry `line`, `kind` (IF / EVALUATE), `outcomes[{label, hits, line}]` and `notMeasurable`.
* The LegacyLens runner passes `--branch-coverage` on every tests-job run and reports the document as the suite's `coverage`.

## Limits

Coverage is of what the suite ran. A branch can be reached and still be wrong; mutation testing (`mockymock mutate`) is the check for that.
