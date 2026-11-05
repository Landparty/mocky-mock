---
name: cobol-test
description: Use when someone wants a COBOL program tested end to end ("test this program", "add unit tests for ORDRPROC", "is this change safe", "build a regression suite", "how well is this program tested"). Understands the program with cobol-parser, builds and runs a mockymock suite under GnuCOBOL with assertions grounded in the program's business rules, and finishes with an HTML report of every step and what each test proves.
---

<!--
Maintainer note: this skill orchestrates; it does not re-teach. The .cut
DSL, CLI flags and the paragraph-first loop live in the `mockymock` skill
(same package, installed alongside), and cobol-parser's analyzers in the
`cobol-analysis` skill. Change those there. What lives here: the order of
the whole job, the INTENT/CHARACTERIZATION labelling contract
(mockymock/analysis/assertion_labels.py), the verification levels
(mockymock/report/test_report.py) and the journal + report hand-off
(mockymock/report/journal.py). Keep reference/ in step with those modules.
-->

# Testing a COBOL program, start to finish

You are building evidence, not just a green test run. The person reading
your result needs to know three things: which behavior is pinned down, how
strongly, and what looked wrong. Everything below serves those three.

Two sibling skills do the detailed work, and you should lean on them:

- **`mockymock`** -- the `.cut` DSL, every CLI flag, the paragraph-first
  loop, modes, refusals. Follow it exactly for steps 4 to 6.
- **`cobol-analysis`** -- which cobol-parser subcommand answers which
  question. Use it in step 2 instead of reading thousands of lines by eye.

## The contract (holds in every mode, hands-off included)

1. **The run decides pass/fail.** Never say a test passes without a
   `mockymock run` result that says so. No Docker means no run: say that
   plainly and continue with the static steps.
2. **Never edit the program under test.** A wrong-looking result is a
   finding to report, with the expected and the actual value.
3. **Every assertion says where its value came from.** Put a label comment
   directly above each group of EXPECT/VERIFY lines:
   - `*> INTENT: BR-004 orders over 1000.00 get 5% off (ORDRPROC.cbl:212)`
     when the value follows from a business rule, a spec, or the developer.
   - `*> CHARACTERIZATION: <why>` when the value is what the program did on
     a run. `run --record-expectations` writes this label for you.
   Never relabel one as the other, and never turn a failing INTENT
   assertion into a CHARACTERIZATION one to get green. That is exactly the
   bug the suite exists to catch. `reference/intent-assertions.md` has the
   rules and examples.
4. **Never claim more proof than you have.** Each test ends at a
   verification level, L0 to L3 (`reference/verification-levels.md`).
   Quote the level the report computed; do not round up.
5. **Record what you decide.** After each step, one `mockymock journal`
   line (below). The final report shows them as a timeline, and it is how
   a reviewer sees *why* the suite looks the way it does.

Read the mode once before starting (`mockymock skills mode`); it changes
how often you check in, never the contract. The `mockymock` skill's
`reference/modes.md` defines the three modes.

## Journal every step

```bash
mockymock journal --cut PROGRAM.cut --step plan \
  --summary "7 paragraphs, 4 business rules; starting with 2000-CALC-DISCOUNT" \
  --decision "Skipping 9000-OLD-REPORT: program-flow lists it unreachable"
```

`--status ok|warn|fail|skipped|info`, `--command "<what you ran>"`. The
journal is `.mockymock/PROGRAM.journal.jsonl` next to the `.cut`,
append-only. Several steps at once take one call: write them as JSON lines
(`{"step": ..., "summary": ..., "decision": ...}`) and pass
`--from steps.jsonl` (or `--from -` for stdin).

## Workflow

### 1. Ground check

```bash
mockymock skills mode
mockymock doctor            # Docker + GnuCOBOL toolchain, config, copybooks
```

Toolchain not ready: say so in one line, run `mockymock setup` only if the
developer agrees (or the mode is hands-off and they asked for a full run),
otherwise continue with the static-only loop (`lint`, no `run`).

### 2. Understand the program

```bash
mockymock analyze program-flow PROGRAM.cbl      # paragraphs, entry point, unreachable
mockymock analyze business-rules PROGRAM.cbl    # decisions, validations, calculations
mockymock analyze complexity PROGRAM.cbl        # where the risk concentrates
mockymock analyze lint PROGRAM.cbl --format text
```

(Each is the cobol-parser subcommand of the same name. `business-rules`,
`complexity` and `lint` need a recent cobol-parser; if one is missing, say
so and derive the rules from the IF/EVALUATE/COMPUTE statements that
program-flow lists per paragraph.)

Summarize for the developer in plain language: what the program reads,
decides and writes, its entry point, and any unreachable paragraph (dead
code is a finding, not a test target).

### 3. Plan

Build one checklist, in PROCEDURE DIVISION order: every reachable paragraph,
and under each, the business rules it holds (rule id, line, one-line
meaning). Each rule arm is a test you owe: a decision with THEN/ELSE needs
both arms, a validation needs an accepted and a rejected input, a
calculation needs a value worked out by hand from the formula. Share the
plan before writing anything (guided/hands-on), and journal it.

### 4. Scaffold

Follow the `mockymock` skill: `mockymock init PROGRAM.cbl` (data-first,
needs Docker for its recording half) or `mockymock generate PROGRAM.cbl`,
then `generate --fill` from then on. For the paragraph pass, `generate`
needs `--per-paragraph` (plain `generate` writes one data-driven case per
scenario instead). Never re-run `generate` over a file you have edited.

Read what came out. Recorded values arrive labelled CHARACTERIZATION; they
are a starting point, not the answer.

### 5. Write the intent cases

For each rule arm on the plan:

- Set the inputs that select the arm. When the arm's data comes through a
  boundary, `mockymock fixtures PROGRAM.cbl --scenarios branches` names a
  value that reaches it (`scenario_coverage`), or tells you why none can.
- Work out the expected value **from the rule**, not from a run: apply the
  formula, follow the decision table. Show your arithmetic in the label
  when it is not obvious.
- Label it `*> INTENT: <rule id> <meaning> (<file>:<line>)`.

Then drive each case green one paragraph at a time with the mockymock
loop (`lint`, `run --case`, `run --case ... --trace`). When an INTENT
assertion fails, stop on it: check your inputs and mocks with `--trace`
first, and if the program really computes something else, report it as a
suspected bug (paragraph, rule, expected, actual) and leave the assertion
as it is. In hands-off, park it and keep going. Once you are sure it is
the program, move that case, assertion unchanged, into
`PROGRAM.known-bugs.cut` (the `mockymock` skill's paragraph-first
workflow, "Where a confirmed program bug lives"): the main suite has to be
green for mutation testing in step 7, and the red suite is the finding.

### 6. Whole program

The end-to-end pass from the `mockymock` skill: PERFORM the entry
paragraph with every boundary mocked; assert end state and total call
counts.

### 7. Prove the suite, then report

```bash
mockymock report PROGRAM.cbl --cut PROGRAM.cut --execute --mutate
# writes .mockymock/PROGRAM.report.html next to the .cut
```

`--execute` runs the suite with coverage, `--mutate` runs mutation testing
(slower; skip it while iterating and pass it for the final report). Without
Docker, pass neither: the report still covers every static step (including
the program analysis) and says what it could not run. If you already ran
`mockymock run` (whole suite) and `mockymock mutate` on this exact program
and suite, `--execute --mutate` reuse their saved results instead of
running them again; `--rerun` forces a fresh run.

`--execute` needs a GnuCOBOL that supports `--coverage` (3.2). On an older
one (`cobc --version` says 3.1) it cannot run: run the suite yourself
with `mockymock run PROGRAM.cbl --cut PROGRAM.cut --json-report run.json`,
then `mockymock mutate ... --json-report mutation.json`, and pass them
with `report --run-json run.json --mutation-json mutation.json`. Say in
the hand-over that line coverage was not measured and why. `mockymock clean` removes
the `.mockymock/` reports and saved results when you are done (journals are
kept).

Act on what it finds before you hand over, within the mode's limits:
a surviving mutant is a missing assertion (add it), "no test reaches X" is
a missing case, a rule without an intent assertion is a gap in step 5.
The report's Program analysis section (health grade, call graph coloured
by test reach, complexity, lint, data flow) says where to look next: an
untested paragraph with high complexity is the next case to write, and a
lint error in a paragraph a test reaches is worth an assertion.
Re-run the report after fixing. `reference/report.md` explains each
section and finding category.

### 8. Hand over

Lead with what the developer must act on, then the evidence:

```
ORDRPROC: 9 tests, 9 pass under GnuCOBOL. 7 at L3, 2 at L2 (they reach a
COMPUTE with division, which IBM COBOL may round differently).
Suspected bug: BR-004 says orders over 1000.00 get 5% off; the program
gives it from 1000.00 (line 212 uses >=). Assertion left failing.
Mutation score 91% (1 survivor at line 230: nothing checks the audit count).
Program health B (debt 18/100); 3000-RECONCILE has complexity 14 and no test.
Report: .mockymock/ORDRPROC.report.html
```

Attach or link the HTML report. Never paste raw JSON at the developer.

## Reference

- `reference/intent-assertions.md` -- the label contract, examples, and
  how to derive expected values from each rule kind.
- `reference/verification-levels.md` -- L0 to L4, what each needs, and
  how to move a test up a level.
- `reference/report.md` -- `mockymock report` and `mockymock journal`:
  flags, every section of the HTML page, every finding category and what
  to do about it.
- `mockymock` skill -- `.cut` DSL, CLI flags, modes, paragraph-first loop.
- `cobol-analysis` skill -- which cobol-parser subcommand answers what.
