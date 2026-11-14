---
type: Module
title: Coverage Reporting
description: GnuCOBOL --coverage/gcov instrumentation wired into `mockymock run`, reporting per-line coverage of the ORIGINAL .cbl (with the instrumented copy as a labelled secondary figure) and gating CI on it via --coverage-fail-under.
tags: [coverage, gcov, cli, runtime]
timestamp: 2026-11-14T12:00:00Z
---
# Overview

`mockymock run --coverage` proves which lines of the program actually ran
during a suite. Two numbers exist and only one of them is worth reading:
the ORIGINAL `.cbl`'s own coverage (via `map_coverage_to_original`) is what
the report leads with, and the instrumented sandbox copy's number -- which differs because it counts
mockymock's own injected dispatch/driver lines, and is often LOWER, since
every never-taken mock dispatch branch counts as uncovered (ACCTPRG 86.60%
vs 80.89%) -- is printed once below it, labelled with the actual direction
(until 2026-09-28 it always said "higher"). Until 2026-09-04 the
console line reported only the instrumented figure while the meaningful one
existed solely inside `--coverage-json`, so the number most people read was
the less useful one. It adds no new instrumentation
engine — GnuCOBOL's own `cobc --coverage` flag builds on gcc's gcov
machinery (`cobc` transpiles COBOL to C), and `-fgen-c-line-directives`
(auto-enabled by `--coverage`) keeps gcov's line attribution pointed at
the real COBOL source lines rather than the generated C.

```
runtime/docker_toolchain.py
  compile_source(path, coverage=True)  -- adds --coverage to the cobc invocation
  run_binary(binary)                    -- unchanged; writes <name>.gcda on normal exit
  run_gcov(path)                        -- docker exec ... gcov <name>.gcda, reads back <name>.cbl.gcov

report/coverage.py
  parse_gcov(gcov_text) -> CoverageReport   -- per-line hit counts -> totals + uncovered lines
                                               (`#####` and `=====` both count as executable, never hit)
                                               (a blank, `*>` comment, EJECT / SKIPn / TITLE line is never
                                               executable, whatever gcov counts on it: ORUBR's blank line and
                                               EJECT after the spliced GOBACK read `#####`)
  map_coverage_to_original(...)             -- instrumented lines -> ORIGINAL .cbl lines
  summarize_original(mapped, original)      -> OriginalCoverage (totals + uncovered, with text)
  format_coverage_console(report, name, original=, program_name=)
                                            -- ORIGINAL number leads; instrumented labelled below

cli/commands/run.py: _cmd_run
  --coverage / --coverage-out / --coverage-fail-under wiring. Only parse_gcov runs
  inside the sandbox (the .gcda/.gcov files die with it); the remap and the console
  formatting happen after it, since the headline number comes from the remap.
```

`--coverage-out PATH` implies `--coverage`, same as `--coverage-json PATH`
and `--coverage-fail-under PERCENT` below (fixed 2026-08-10, audit finding F12 — only the JSON flag carried the
implication in code even though docs/options-reference.md already
documented both; `--coverage-out` alone used to silently produce nothing
instead of running gcov).

# Data Model

```python
@dataclass
class UncoveredLine:
    line_number: int
    text: str

@dataclass
class CoverageReport:
    total_executable: int
    total_covered: int
    uncovered_lines: list[UncoveredLine]

    @property
    def percentage(self) -> float: ...  # 100.0 when total_executable == 0

@dataclass
class OriginalCoverage:            # summarize_original(mapped, original_lines)
    total_executable: int          # mapped lines only -- a lower bound (see Gotchas)
    total_covered: int
    uncovered_lines: list[UncoveredLine]   # ORIGINAL line numbers + cols 8-72 text

    @property
    def percentage(self) -> float: ...  # the number the console report leads with
```

## Original-source remapping (`map_coverage_to_original`)

`CoverageReport.covered_lines` (instrumented line numbers with nonzero hits)
plus `map_coverage_to_original(report, instrumented_lines, normalized_lines,
original_lines)` -> `list[MappedLineCoverage(line, covered)]` remap coverage
onto the ORIGINAL `.cbl`. Two difflib.SequenceMatcher alignments compose:
instrumented -> normalized (splicer keeps untouched lines verbatim and in
order) and normalized -> original (via a fixed-format column-8-72/comment-
drop extraction mirroring `normalize_fixed_format`). Unmappable lines
(driver code, splicer insertions, continuation merges) are excluded —
deliberately: the view answers "which of MY lines ran". A statement the
splicer *replaced* (a mocked boundary, a neutralized GOBACK / STOP RUN)
is one of MY lines, though (issue #297): `build_original_line_map` aligns
its commented-out copy (`stub_writer.comment_and_replace`'s
`"      *> "` prefix stripped) and maps every indented line of the
replacement block after it to the statement's first original line, so
the statement is covered exactly when its replacement ran (an untaken
CALL-only branch used to read 100%). The same map feeds `run --trace`.
Lines rewritten in place (DFHRESP expansion, ADDRESS OF redirect) still
drop out. `format_coverage_json` serializes both the instrumented totals and
this mapped view; `run --coverage-json PATH` (implies `--coverage`) writes
it.

## `--coverage-fail-under PERCENT` (CI gate)

The `run` counterpart of `mutate --fail-under`, added 2026-09-04: without
it, mutation score could be CI-gated and coverage could not. It implies
`--coverage`, is judged against the ORIGINAL program's percentage (gating
on the instrumented one would move the threshold whenever mockymock's own
injected line count changed -- which says nothing about the program under
test), and is folded into `_cmd_run`'s single final exit-code decision
rather than returned on early, so `--trace` output still prints. A failed
`gcov` pass **fails** the gate: "no number" must never read as "good
enough".

# Gotchas

**The two percentages are not interchangeable, and only one is about your
program.** `CoverageReport.percentage` measures the instrumented sandbox
copy; `OriginalCoverage.percentage` measures the user's own `.cbl`. Any
new consumer (a report, a gate, an editor integration) wants the second.
Both are in `--coverage-json` under `instrumented`/`original`, each with
its own `percentage` key.

**Original-line remapping is best-effort by construction, and fails
safe.** Lines with no counterpart -- the splicer's own insertions,
boundary-line replacements, continuation merges -- are simply absent from
the mapped view, so they neither count as covered nor as uncovered. That
makes `OriginalCoverage.total_executable` a lower bound on the program's
executable lines, not a claim about all of them.

**The instrumented number is still structurally deflated (v1 note, kept
because it explains the second figure).** Mock-body splicing and the generated
test-driver code shift every line number after the `WORKING-STORAGE
SECTION`/`PROCEDURE DIVISION` insertion points, and boundary splicing can
replace one line with a multi-line mock body anywhere in the file.
Remapping back to original line numbers needs a line-provenance map
threaded through the whole splicer (`orchestrator.py`, `driver.py`,
`linkage.py`, `sqlca.py`) — named as a v2 follow-up in
`docs/2026-07-17-coverage-reporting-design.md`, not built.

**A fully-branch-covering suite still won't read near 100% (structural,
not a suite-authoring gap).** The splicer emits one shared `EVALUATE
UT-CURRENT-CASE` dispatch per boundary site with a `WHEN "<case-id>"`
branch for *every* test case in the suite that mocks the same key — not
only cases whose `PERFORM` target reaches that exact site. Those other
cases' branches are structurally dead there. Confirmed on `DEPTIMSM`'s
20-case suite (every real branch, including the full `0000-MAIN-PROCESS`
entry point, exercised): still 75.90% (693/913), the rest being this
cross product, the driver's own dead `FAIL` branches, and the terminator-
neutralization transform's defensive `IF UT-EARLY-EXIT = "Y" EXIT
PARAGRAPH END-IF` guards (dead whenever the guarded paragraph has no
nested terminator of its own). Don't read a number well under 100% as a
weak suite without checking which of these it is.

**`.gcda` is only written on normal process exit.** A binary killed by
`run_binary`'s timeout `SIGKILL` never reaches the C runtime's coverage-
dump `atexit` handler, so `run_gcov` checks for the file up front and
returns a clean "no coverage data produced" result instead of a confusing
gcov error about a missing file.

**`docker exec -w <path>` needs a real absolute *container* path, and
works fine via `subprocess.run` (see `runtime.md`'s existing note on
`run_binary`'s use of the same flag) — an ad hoc `docker exec -w
/work/...` typed directly at a Git Bash prompt fails with "Cwd must be an
absolute path" due to Git Bash's own MSYS argument path-mangling, not a
real Docker limitation. Don't mistake that shell artifact for a reason to
avoid `-w` in the actual Python implementation.

# Second consumer: `mockymock mutate`'s coverage gate

`map_coverage_to_original` is no longer only a reporting view. Since
2026-09-04 `mutation/runner.py` compiles the *baseline* with
`--coverage`, remaps it the same way, and classifies any mutant on a
provably unexecuted ORIGINAL line as `survived` without building it (see
[cli](cli.md), `mockymock mutate`). The remap's deliberate exclusions are
load-bearing there: a line the map omits is **unknown**, never
"uncovered", and is always built. Widening what the remap claims to know
would turn a reporting inaccuracy into a wrong mutation verdict.

# See Also

- [runtime](runtime.md) — the Docker toolchain `compile_source`/`run_gcov` extend
- [report](report.md) — `report/coverage.py` follows the same Docker-free
  parsing/formatting split as `report/results.py`/`report/formatters.py`
- [cli](cli.md) — `run`'s `--coverage`/`--coverage-out`/`--coverage-fail-under` flags

# Branch coverage: `run --branch-coverage FILE` (2026-11-06)

`report/branch_coverage.py`, independent of gcov: the suite is compiled
with the trace (`-ftraceall`, as `--trace`) and the whole trace of every
case is read. `program_points(ast, lines)` lists paragraphs, statement
lines, IFs and EVALUATEs from the AST; `measure` walks the trace (split per
program by `TraceEntry.program`) and credits an outcome when the next
mapped statement is that branch's first statement (elimination for empty
branches; shared-line cases are `notMeasurable`, never guessed). Lines are
remapped with `build_normalized_line_map` + `build_normalized_to_original_map`
(the old `build_original_line_map`, split in two). Real subprograms of a
load-module suite are measured under their own program id. JSON version 1:
`programs[]` with `paragraphs`, `branches`, `statements`. Design:
[docs/2026-11-06-branch-coverage-design.md](../docs/2026-11-06-branch-coverage-design.md).

**Unreachable points (2026-11-07).** `report/unreachable.classify(ast,
points, suite)` (called by `_write_branch_coverage` for the program under
test) asks cobol-parser's `InputDependenceAnalyzer` (guarded import: 3.7+)
which decisions no input can change, then `report.unreachable(taken,
executed_lines)` for the outcomes the run never took and everything behind
them. `program_report(..., unreachable=)` adds `unreachable` reasons and
counts and `unreachableScope` (`full`, or `static` with `unreachableNote`
when a case starts elsewhere than the entry paragraph or mocks a
paragraph / section, or when a run does not start from VALUE-clause storage: a case PERFORMs program paragraphs more than once, or a BEFORE-ALL / AFTER-ALL PERFORMs one (`reused_storage`, #446): then only code nothing reaches is claimed). An outcome the run took is never reported unreachable. Setup
`MOVE` targets, and the receiving fields of every MOCK body statement
(`mock_body_targets`, a safe superset; #471), are passed as `extra_inputs`. Tests:
`tests/unit/test_unreachable.py`.

