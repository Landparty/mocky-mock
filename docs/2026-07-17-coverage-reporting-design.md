# mockymock — Coverage Reporting Design

Date: 2026-07-17
Status: approved, not yet implemented

## Motivation

mockymock's own 2026-07-06 readiness audit (Finding 10) flags that nothing
tells a `.cut` author which lines/paragraphs a suite actually exercised —
gaps in a hand-written suite are invisible. Separately, only 3 of the 17
real-world programs in the sibling `legacy-application/cobol/` corpus
(`ACCTPRG`, `DEPTMQP`, `DEPTMQC`) have ever been proven to actually compile
and run end-to-end through mockymock; the other 14 are only known to pass
`mockymock generate`'s parse-and-analyze stage (`docs/corpus-sweep-report.md`,
2026-07-17 re-sweep), which is not the same as a real Docker/GnuCOBOL
compile+execute.

This doc scopes the first piece of closing both gaps: a **coverage
reporting feature** — the mechanism to measure and report line coverage —
proven end-to-end on a couple of real-world programs. Extending it across
the rest of the corpus is explicitly out of scope for this doc and left as
a follow-up once this mechanism exists and is trusted.

## Key finding from a spike (done before this doc was written)

GnuCOBOL transpiles COBOL to C and links with libcob; its `cobc` compiler
has a **native `--coverage` flag** ("instrument generated binaries for
coverage") built on gcc's own `-fprofile-arcs -ftest-coverage`/gcov
machinery, and `-fgen-c-line-directives` (auto-enabled by `--coverage`)
keeps the generated C's line directives pointed at the original COBOL
source. Concretely verified this session, using the existing
`mockymock-cobc` Docker image (gcc/gcov already present, no new
dependencies needed):

```
cobc --coverage -free -x <program>.cbl -o <binary>
<binary>                    # writes <program>.gcda next to the .gcno
gcov <program>.gcda          # produces <program>.cbl.gcov
```

`<program>.cbl.gcov` is a real per-COBOL-line report: executed lines show a
hit count, non-executable lines (declarations, comments, blank lines) show
`-`, and unexecuted executable lines show `#####`. Example, run against a
freshly-generated `DEPTIMSM.cut` (leaf-paragraph-only suite):

```
       1*:    8:       01  UT-CURRENT-CASE        PIC X(9).
        -:   12:01  WS-COMMON-FIELDS.
    #####:  390:0000-MAIN-PROCESS.
    #####:  391:    PERFORM 1000-INITIALIZE
```

`gcov`'s own stdout also reports the aggregate directly (`Lines
executed:73.21% of 418`), so the summary percentage needs no separate
computation.

Because one `.cut` file compiles to **one binary that runs every
`TESTCASE` in the suite in a single process**, one `gcov` pass after
execution already gives the coverage **aggregated across the whole
suite**, not per-test-case — exactly the JaCoCo/JUnit-suite-level notion of
coverage this feature is meant to approximate. No merging of multiple
runs is needed.

## What "100%" means here (per user decision)

Some code is structurally unreachable through mockymock by design —
`SORT`/`MERGE`/`RELEASE`/`RETURN`, `DECLARATIVES`, `ALTER`, and paragraphs
behind a `GO TO`-reachable or otherwise-unsupported terminator are refused
outright (`docs/2026-07-06-real-world-readiness-audit.md`, Finding 3 and
5). This feature reports the **actual achieved percentage plus the
concrete list of uncovered lines**, so gaps are visible and explainable —
it does not gate on or promise literal 100% for every program. A program
whose suite reaches, say, 91% with the remaining 9% explained (dead
defensive code, a refused construct) is the success shape, not a failure.

## Scope decisions (asked and answered before this doc)

1. **This round builds the coverage mechanism and proves it on 1-2
   programs; it does not attempt to raise coverage across the full
   17-program corpus.** That is explicit follow-up work once this is
   proven and trusted.
2. **v1 reports line numbers against the *instrumented* source**, i.e.
   after mock-body splicing, tally-counter insertion, and the
   WORKING-STORAGE/driver-procedure insertions `_insert_driver` performs —
   the same file `--verbose`/`--keep-sandbox` already expose today — not
   remapped back to the original `.cbl`'s line numbers. Remapping requires
   threading a line-provenance map through the whole splicer
   (`orchestrator.py`, `driver.py`, `linkage.py`, `sqlca.py`), since a
   single mocked boundary site can replace one line with a multi-line mock
   body anywhere in the file. That's real, separate work, named here as a
   v2 follow-up, not built now.
3. **Output**: a console summary (percentage + covered/total executable
   line counts) plus the list of uncovered line numbers and their source
   text, mirroring the existing pass/fail report style. An optional
   `--coverage-out PATH` writes the fuller per-line report to a file for
   later inspection/CI archiving, mirroring how `--junit-xml` already
   works.

## Design

### CLI

New flag on the existing `run` subcommand (not a new subcommand — it's the
same splice/compile/execute pipeline `run` already has, just with an extra
compile flag and a post-execution step):

```
mockymock run <program.cbl> --cut <suite.cut> --coverage [--coverage-out PATH]
```

### `runtime/docker_toolchain.py`

- `compile_source(source_path, coverage: bool = False)` — passes
  `--coverage` to `cobc` when set. No other flag changes needed (confirmed
  in the spike: `-fgen-c-line-directives` is auto-enabled by `--coverage`,
  so no `-g` needed alongside it).
- New `run_gcov(source_path: Path) -> GcovRunResult` — runs
  `docker exec <container> sh -c "cd <dir> && gcov <name>.gcda"` (the `sh -c
  cd` form, not `docker exec -w`, since `-w` requires an absolute
  *container* path and the existing helpers build sandbox dirs relative to
  the bind mount — confirmed during the spike that `-w` alone errored with
  "Cwd must be an absolute path" on this Windows/Docker Desktop setup),
  then reads back `<name>.cbl.gcov`'s text content before the sandbox is
  cleaned up. Returns raw gcov stdout + the `.gcov` file text, or an
  explicit "no coverage data" result if the `.gcda` file doesn't exist
  (see Error handling below).

### New `mockymock/report/coverage.py`

- `parse_gcov(gcov_file_text: str) -> CoverageReport` — parses the
  `<count|"-"|"#####">:<line>:<text>` format into per-line records; a
  dataclass with `total_executable`, `total_covered`, `percentage`,
  `uncovered_lines: list[tuple[int, str]]`.
- `format_coverage_console(report: CoverageReport) -> str` — percentage
  summary + uncovered-line listing (line number + trimmed source text),
  same style as `format_console` in `report/formatters.py`.

### `cli/main.py` (`_cmd_run`)

- When `--coverage` is passed: `compile_source(..., coverage=True)`.
- After `run_binary` succeeds (or even on a non-timeout nonzero exit —
  GOBACK/STOP RUN still flush gcov data via the normal C `atexit` path,
  only a SIGKILLed timeout does not), call `run_gcov`, parse it, print the
  console summary, and write `--coverage-out` if given.
- This must happen **inside** the `with sandbox_dir_maybe_kept(...)` block,
  before cleanup — the `.gcda`/`.gcov` files live in the same tmp dir that
  gets deleted unless kept.

## Error handling

- **Docker/gcov unavailable**: `gcov` is already present in the
  `mockymock-cobc` image (confirmed: Debian's `gcc` package includes it) —
  no new image/Dockerfile change needed. If `docker exec ... gcov` itself
  fails, print a clear `mockymock run: coverage: gcov failed: <stderr>` and
  continue reporting the normal pass/fail result (coverage is additive,
  never blocks the pass/fail exit code).
- **No `.gcda` produced** (binary killed by the timeout's SIGKILL before
  its `atexit` gcov-dump handler ran): detect the missing file and print
  `mockymock run: coverage: no coverage data produced (binary did not exit
  normally)` instead of a confusing parse failure.
- **`--coverage` without `--coverage-out`**: fine, console-only.
- **Compile failure**: unaffected — coverage instrumentation only matters
  post-compile-success; the existing compile-failure return path is
  unchanged.

## Testing

- **Unit** (`tests/unit/test_coverage.py`): feed `parse_gcov` canned
  `.gcov`-format text — a mix of `-`/numeric/`#####` lines, edge cases
  (zero executable lines, a file with no `#####` at all = 100%, malformed
  line ignored rather than crashing) — assert the computed percentage and
  uncovered-line list.
- **Integration** (`tests/integration/`, Docker-gated like the rest of the
  suite): two real end-to-end proofs, matching the "1-2 programs" scope
  decision:
  1. **`DEPTIMSM`** (new — not previously an `examples/` entry): commit it
     as `examples/real-world/DEPTIMSM/` with a `.cut` suite extended beyond
     today's `generate`-scaffolded leaf-paragraph-only version to include a
     case that drives the real `0000-MAIN-PROCESS` entry point to
     `GOBACK` (safe here: `GOBACK` is the paragraph's own last statement,
     zero-hop from the test's own `PERFORM` target, independent of what the
     intermediate `PERFORM ... UNTIL` loop's body does). Run with
     `--coverage`, assert a coverage percentage is reported, and pin the
     achieved number with a documented explanation of whatever remains
     uncovered.
  2. **`ACCTPRG`** (already committed, already has a mature suite covering
     both individual paragraphs and one whole-program run) — run its
     *existing*, unmodified `.cut` with `--coverage` as a sanity check that
     the feature composes with a suite nobody wrote with coverage in mind,
     and record the number. No suite changes expected here; this proves
     the tool works against pre-existing suites, not just purpose-built
     ones.
  3. A small Docker-gated test asserting the timeout/no-`.gcda` path
     produces the graceful message rather than a crash (reuse whatever
     fixture already exercises the timeout behavior, if one exists, or add
     a minimal infinite-loop fixture).

## Out of scope (named follow-ups, not built here)

- Remapping instrumented-source line numbers back to the original `.cbl`
  (v2, needs splicer-wide line-provenance tracking).
- Raising coverage across the other 15 corpus programs (14 real-world
  programs beyond `ACCTPRG`/`DEPTMQP`/`DEPTMQC`, plus deepening those
  three's own suites) — explicit follow-up once this mechanism is proven.
- A coverage threshold/gate (e.g. "fail the run if below N%", JaCoCo-style)
  — easy to add later since the percentage is already computed, but not
  requested for this pass.
- lcov/gcovr/HTML report generation — the plain per-line console/file
  report is the v1 deliverable; a richer viewable report is a natural but
  separate enhancement.
