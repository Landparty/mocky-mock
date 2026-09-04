# mockymock — Mutation Testing (`mockymock mutate`)

Date: 2026-07-29
Status: v1 implemented (this doc); site-discovery hardened 2026-09-04
(see "Column discipline" below); coverage filtering, per-case targeting,
and mutant schemata deferred

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
- `mockymock/mutation/runner.py` — baseline gate + serial kill loop:
  patch one line → the same static-check/splice/compile/run sequence
  `_cmd_run` performs → classify.
- `mockymock/mutation/report.py` — outcome model, console + JSON.
- CLI: `mockymock mutate <prog> --cut <file> [--copybook-path DIR ...]
  [--list] [--timeout S] [--json-report PATH] [--fail-under PCT]`.

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
| `survived` | suite green — the interesting ones, listed with a diff | yes |
| `stillborn` | refusal or compile error on the mutated program | **no** — says nothing about the suite |

Score = (killed + timeouts) / (killed + timeouts + survived).

### Baseline gate

The unmutated program must run green first (`run_mutation` refuses
otherwise): against a red baseline every verdict is noise. Same
fail-closed posture as the refusal gate.

## Deferred (in value order)

1. **Coverage filtering** — reuse the existing gcov path to mutate only
   covered lines: an uncovered-line mutant is a guaranteed survivor that
   coverage already reported. The biggest cost lever on real programs.
2. **Per-case targeting + early exit** — per-case coverage says which
   cases execute the mutated line; compile only those (each mutant
   recompiles anyway, so narrowing is free) and stop at the first kill.
3. **Parallel workers** — sandboxes are already isolated under
   `WORK_ROOT`; the VS Code extension's `maxParallelRuns` establishes
   the concurrent-compiles pattern.
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
- Serial v1 wall-clock is fine for fixture/demo scale (~0.7 s/mutant)
  and linear in program size beyond it — the deferred items above are
  the answer, and `--fail-under` should gate changed code, not whole
  legacy programs, until then.
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
