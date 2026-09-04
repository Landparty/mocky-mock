# mockymock — Mutation Testing (`mockymock mutate`)

Date: 2026-07-29
Status: v1 implemented (this doc); site-discovery hardened and the
coverage gate + parallel workers built 2026-09-04 (see "Column
discipline" and "Cost levers" below); per-case targeting and mutant
schemata deferred

## Motivation

Coverage answers "did this line run"; it cannot answer the question a
modernization team actually has about its characterization-test safety
net: **"if this line were wrong, would a test fail?"** Mutation testing
answers it directly — mutate one statement, re-run the suite, check
whether anything noticed — and the fixture demo makes the gap concrete:
`debug_spike.cut` (no `EXPECT`s) executes every line of its program yet
scores **0%** (10/10 mutants survive), while `mutation_target.cut` (one
real assertion) scores 83.3%.

Mutation testing never took hold in COBOL — not because COBOL is hard to
mutate, but because a mutation tester is meaningless without an automated
suite to kill mutants with, and until mockymock that harness didn't
exist off-mainframe. The ingredients are all already in this repo:

- a **source rewriter with location data** (the splicer does far more
  invasive line-level surgery than a one-line mutation),
- a **fast isolated compile/run loop** (the warm `mockymock-cobc`
  container: ~0.7 s per full splice/compile/run cycle for the spike
  fixtures),
- a **reliable verdict** (`__MOCKYMOCK__` per-case PASS/FAIL), which is
  **deterministic by construction** because every external boundary is
  mocked — no flaky-kill noise, the classic mutation-testing plague on
  code with real I/O.

## v1 scope (implemented)

- `mockymock/mutation/operators.py` — pure, Docker-free mutant
  generation over the ORIGINAL source lines (so every report line points
  at a line the user can open).
- `mockymock/mutation/runner.py` — baseline gate + kill loop: patch one
  line → the same static-check/splice/compile/run sequence `_cmd_run`
  performs → classify. Serial by default; see "Cost levers" below for the
  coverage gate and `--jobs`.
- `mockymock/mutation/report.py` — outcome model, console + JSON.
- CLI: `mockymock mutate <prog> --cut <file> [--copybook-path DIR ...]
  [--list] [--timeout S] [--jobs N] [--no-coverage-gate]
  [--json-report PATH] [--fail-under PCT]`.

### Operators

| id | mutation | example |
|----|----------|---------|
| `rel-swap` | `>` ↔ `>=`, `<` ↔ `<=` on `IF`/`UNTIL`/`WHEN` lines | `UNTIL WS-I > 4` → `>= 4` |
| `boundary-literal` | integer after a relational symbol, +1 | `> 4` → `> 5` |
| `arith-verb-swap` | `ADD..TO` ↔ `SUBTRACT..FROM`, `MULTIPLY..BY` ↔ `DIVIDE..INTO` (preposition rewritten with the verb — a bare verb swap is a syntax error) | `ADD 2 TO X` → `SUBTRACT 2 FROM X` |
| `move-literal` | `MOVE <int> TO`, +1 | `MOVE 0 TO X` → `MOVE 1 TO X` |
| `stmt-delete` | whole simple statement → `CONTINUE` (indent + trailing period preserved) | `MOVE 0 TO X.` → `CONTINUE.` |

### Site-discovery rules (precision over recall)

A missed site is one blind spot; a false site is a stillborn compile per
mutant — so every rule fails toward *not* mutating:

- Only lines after `PROCEDURE DIVISION`; comment lines (fixed-format
  column-7 `*`/`/`, free-form `*>`) skipped; matches inside quoted
  literals or after an inline `*>` rejected; nothing past column 72.
- **Boundary statements are never mutated** (`CALL`/`CANCEL`/`ENTRY`/
  `EXEC`/file ops/`ACCEPT`): the splicer replaces them with mock
  dispatch, so mutating them tests the harness, not the program.
- **Terminators are never mutated** (`STOP`/`GOBACK`/`EXIT` lines): the
  terminator plans rewrite those regions (the same constraint the debug
  spike fixture documents).
- `stmt-delete` refuses scope-carrying lines (`IF`/`ELSE`/`EVALUATE`/
  `WHEN`/`PERFORM`/`END-*`): deleting those restructures, not deletes.
- Relational swaps require an `IF`/`UNTIL`/`WHEN` on the line, so `=` in
  `COMPUTE` and `>` in `DISPLAY` literals are never touched.
- Fixed-format continuation lines (indicator `-`) are skipped: their text
  is a fragment of the previous line's statement, so neither word-level
  matching nor the deletion rules hold on it.
- `PROCEDURE DIVISION` state resets at `END PROGRAM` / a following
  `IDENTIFICATION DIVISION`, so a second program's DATA DIVISION in the
  same file is not mutated as if it were procedural code.
- `stmt-delete` additionally requires the statement to provably *end on
  its own line* — a trailing period, or a next code line that opens
  something new (a statement verb, an unrelated scope terminator, a
  paragraph/section/division header). A line trailing off in a
  preposition (`MOVE WS-A TO`) is refused whatever follows it, since its
  operand line is indistinguishable from a paragraph header. Deleting the
  head of a multi-line statement strands its own tail — `CONTINUE`
  followed by `WS-TOTAL / WS-COUNT`, or by an `END-ADD` that binds to the
  very verb just deleted.

### Column discipline (2026-09-04)

Every rewrite happens *within columns 1-72*, with the identification area
(columns 73-80) re-pinned at column 73 rather than carried along by the
edit. `normalize_fixed_format` slices columns 8-72 and discards the rest,
so on traditional 80-column source both directions of drift are silent
stillborns:

| direction | example | what breaks |
|-----------|---------|-------------|
| grows | `ADD..TO` → `SUBTRACT..FROM` (+7) | the statement's own tail falls off the end of column 72 |
| shrinks | `SUBTRACT..FROM` → `ADD..TO` (−7), `>=` → `>` (−1) | `NC1014.2` slides back into the program text and becomes code |

`_rewrite_code` reclaims the columns a longer verb needs by collapsing
interior runs of two or more spaces — never the indent that decides Area A
vs Area B for the statement's first word, never inside a quoted literal —
and refuses the mutant when the line cannot give them up (which still
recovers 287 of the 671 overflowing sites).

Measured over a 542-file corpus (vendored NIST CCVS85, shamrice, this
repo's fixtures), **2,165 of 17,689 mutants — 12.2% — were defective**:
1,775 shifted the identification area, 671 overflowed column 72, 135 were
multi-line deletion heads, and 102 came from `\b` matching a verb inside a
hyphenated identifier (the same class as audit finding F8, which never
reached the arithmetic patterns). Running each mutant through the very
`normalize_fixed_format` the pipeline feeds `cobc` puts a verified floor
under that: **1,580 of them (8.9% of the whole population) compiled
something other than what their own report line described** — 546 with
identification text leaked into the program, 1,209 with the statement's
tail cut off. Afterwards: zero corrupted mutants, 621 sites no longer
offered at all, and the Docker-gated integration fixture's pinned mutant
population unchanged (its lines are short and single-statement).

v1 discovery is text-level with these guards. AST-driven discovery via
cobolparser statement nodes (exact spans, keyword forms like `GREATER
THAN`, `COMPUTE` operator swaps through the M12 expression trees) is the
v2 upgrade path — the operator interface (`Mutant` = line + replacement
text) does not change.

### Classification

| status | meaning | scored? |
|--------|---------|---------|
| `killed` | any case failed, crashed, or the binary exited nonzero | yes |
| `timeout` | no exit within `--timeout` (default 15 s) — a mutated loop condition that spins is a kill: a hang would be noticed | yes (as a kill) |
| `survived` | suite green, or the baseline's coverage proved the line never runs (`ran: false`) — the interesting ones, listed with a diff | yes |
| `stillborn` | refusal or compile error on the mutated program | **no** — says nothing about the suite |

Score = (killed + timeouts) / (killed + timeouts + survived).

### Baseline gate

The unmutated program must run green first (`run_mutation` refuses
otherwise): against a red baseline every verdict is noise. Same
fail-closed posture as the refusal gate.

## Cost levers (2026-09-04)

Two of the deferred items below are now built. Both remove or spread
work; neither changes a verdict.

### Coverage gate (was deferred item 1) — on by default

The baseline is compiled with `--coverage` and its gcov output remapped
onto the ORIGINAL source by `report.coverage.map_coverage_to_original`.
Any mutant whose line that map says was **never executed** is classified
`survived` from the baseline's evidence alone, with no splice, compile or
run of its own. This is exact, not heuristic: a line no test case reaches
cannot change what any test case observes.

Three rules keep it safe:

- **Absent means unknown, never uncovered.** The remap deliberately omits
  lines it cannot place (driver insertions, boundary replacements,
  continuation merges). Those are always built.
- **A coverage build must never be why a green suite reads red.**
  `--coverage` is a different compile and a slower binary than the one
  `run` performs, so a baseline that fails *at the compile step*, or times
  out, is re-run plain before it is believed. A refusal-gate stop (before
  any compiler runs) and a genuinely failing suite are not re-run —
  gcov instrumentation does not change what the COBOL computes, and
  doubling the wait on a red suite would help nobody. `SuiteRun.phase`
  ("checks" / "compile" / "run") is what makes that distinction possible.
- **Nothing goes silent.** A gcov pass that produces nothing appends a
  note, printed like every other `mockymock mutate:` note, and the run
  builds everything.

Gated survivors are scored exactly like built ones — the score is the
same number either way. They carry `ran: false` in the JSON report,
`not_compiled` in `totals`, and print as `uncovered` rather than
`SURVIVED` in the live stream, because a verdict reached from coverage
should not read as a mutant that was built and beat the suite.
`--no-coverage-gate` builds everything.

The one thing given up: a gated mutant is never compiled, so one that
*would* have been stillborn is reported as a survivor instead. After the
2026-09-04 operator work (see "Column discipline") stillborns are rare,
and on an uncovered line "your suite would not notice" is true regardless.

### Parallel workers (was deferred item 3) — `--jobs N`, default 1

Each mutant already runs in its own sandbox under `WORK_ROOT`, and the
per-mutant static-check pass is CPU-bound *pure Python* — so the pool is
processes, not threads. Results are consumed in submission order
(`pool.map`), which keeps the report, the live progress stream and the
notes union byte-identical to a serial run whatever order the workers
finish in. The source is handed to each worker once through the pool
initializer rather than pickled per task.

Measured on a synthetic 3,610-line program (4 cores, the Docker-free half
of the pipeline — `run_static_checks`, 0.38 s per mutant warm): **1.93×
at `--jobs 2`, 3.90× at `--jobs 4`.** For scale, that program generates
3,600 mutants, so its static-check cost alone is ~23 minutes serial before
a single `cobc` runs.

**Why the default is 1.** The ceiling is not the core count: the shared
`mockymock-cobc` container runs under `--memory 1g`, and every concurrent
`cobc` draws from that one budget. An OOM-killed compile comes back as a
compile failure, which the loop would record as `stillborn` — a wrong
verdict, quietly. Until that failure mode is distinguishable, opting in
per machine beats guessing on the user's behalf.

## Still deferred (in value order)

1. **Per-case targeting + early exit** — per-case coverage says which
   cases execute the mutated line; compile only those (each mutant
   recompiles anyway, so narrowing is free) and stop at the first kill.
2. **Resource-failure detection** — an OOM-killed or otherwise
   infrastructure-failed compile is currently indistinguishable from a
   mutant that genuinely does not build, which is what keeps `--jobs`
   opt-in. `SuiteRun.phase` is the hook.
3. **Shared static-check work.** Profiled on the same 3,610-line program:
   `run_static_checks` lexes the source *three* times per pass
   (`parse_cobol`, `check_unresolved_copybooks_scoped`, and
   `collect_scope_map`), and the recursive `_find_statements_of_type`
   walk accounts for ~23% of a pass on its own. Both are shared with
   `run`/`lint`/`debug`/`export`, so a fix pays for itself far beyond
   `mutate` — and both are inside the fail-closed refusal package, which
   is why neither was touched here.
4. **Mutant schemata** — compile many mutants into ONE binary behind
   `IF UT-MUTANT-ID = n` dispatch, selected at runtime, amortizing the
   compile (the dominant cost). Low-risk here precisely because
   guarded-dispatch injection is the pattern the splicer already
   implements for mocks.
5. **More operators** — `=` ↔ `NOT =`, `AND` ↔ `OR`, 88-level `VALUE`s,
   `ROUNDED`/`ON SIZE ERROR` removal, `WHEN OTHER` deletion.
6. **Diff-scoped runs** — mutate only paragraphs touched since a given
   ref, for a CI gate proportional to the change.

## Known limitations

- **Equivalent mutants** survive forever and no tool solves this; the
  integration fixture deliberately pins one (`stmt-delete` of
  `MOVE 0 TO WS-TOTAL` is masked by `VALUE 0` + the driver's
  WORKING-STORAGE reset) so the behavior is documented, honest triage
  output rather than a surprise. Mitigation is a high-signal operator
  set, not detection.
- Wall-clock is fine for fixture/demo scale (~0.7 s/mutant) and linear in
  program size beyond it. The coverage gate and `--jobs` (above) are the
  two levers built so far; until per-case targeting and schemata land,
  `--fail-under` should still gate changed code rather than whole legacy
  programs.
- Text-level discovery skips keyword relational forms (`GREATER THAN`)
  and multi-line conditions — blind spots, never false mutants.
- `stmt-delete` on a line holding more than one statement
  (`MOVE X TO Y. ADD 1 TO Z.`) still deletes both: an over-strong mutant
  that compiles and is very likely killed, so it inflates the score rather
  than the stillborn count. AST-driven discovery (v2) is the real fix.
- `stillborn` still lumps a refusal-gate rejection in with a compile
  error. A `stmt-delete` can genuinely change what the refusal gate sees
  (a dynamic CALL target that is no longer resolvable, say), and that is
  a harness limit, not an operator-precision failure. Splitting the two
  means adding a status the VS Code extension's `mutationReport.ts` also
  has to learn.

## Testing

- `tests/unit/test_mutation_operators.py` — site discovery, exclusion
  rules, exact rewrite text, and a pin of the integration fixture's
  full mutant population (so the Docker test's expectations stay
  explainable).
- `tests/unit/test_mutation_speed.py` — the coverage gate (uncovered ->
  survivor without a build, unmappable -> always built, gate off, gated
  survivors still scored, the plain-baseline re-run and exactly when it
  fires) and the worker pool (mutant-ordered results/progress/notes, no
  pool below two workers or two mutants, the in-worker call path, initarg
  and result picklability, a broken pool reported not raised).
- `tests/integration/test_mutation.py` (Docker-gated) — the kill loop
  end-to-end against real GnuCOBOL: every mutant of
  `mutation_target.cbl` classified exactly as predicted (5 killed, 1
  equivalent survivor, score 5/6), and the red-baseline refusal.

## Alternatives considered

- **Mutating the instrumented (post-splice) source** — rejected: report
  lines would point at generated code, and mutants could land inside
  mock dispatch. Mutating the original keeps every verdict expressible
  in the user's own source.
- **Skipping the per-mutant static re-check** (parse once, splice N
  times) — rejected for v1: a mutant can change what the refusal gate
  sees (e.g. reachability), and re-running the same pipeline `run` uses
  guarantees a mutant verdict never diverges from what `mockymock run`
  would say about that program. Revisit only with schemata.
- **Counting stillborns against the score** — rejected: they measure
  operator precision, not suite quality; they are reported separately
  so operator regressions stay visible.
