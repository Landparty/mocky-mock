---
name: cobol-test
description: Use when someone wants a COBOL program tested end to end ("test this program", "add unit tests for ORDRPROC", "is this change safe", "build a regression suite", "how well is this program tested", "test PAYMAIN with the real PAYCALC"). Takes the program, then any subprograms to run for real instead of mocking their CALL (`/cobol-test PAYMAIN.cbl PAYCALC.cbl DATECHK.cbl`). Understands the program with cobol-parser, builds and runs a mockymock suite under GnuCOBOL with assertions grounded in the program's business rules, and finishes with an HTML report of every step and what each test proves.
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

## What you were given

```
/cobol-test PROGRAM.cbl [SUBPROGRAM.cbl ...]
```

The first program is the one under test. **Every program after it is a
subprogram whose CALLs run for real** instead of being mocked: the
developer wants the caller and those callees tested together (a
load-module suite). The same holds when they say it in words ("test
PAYMAIN with the real PAYCALC"). With one program, everything below runs
as written and every CALL is mocked.

With subprograms, check each one before you plan:

- It exists, and `mockymock analyze program-flow PROGRAM.cbl` shows a
  CALL to its PROGRAM-ID (by literal, or a dynamic CALL whose candidates
  include it). A file nothing calls is a mistake to raise, not a link to
  add.
- It is COBOL. A CALL to anything else stays a MOCK.
- List every program the chain needs: a CALL to a program not on the
  list stays mocked, inside a subprogram as well.

Then the job gains one suite. Each step below says what changes; the
short version is:

| | Unit suite `PROGRAM.cut` | Load-module suite `PROGRAM.module.cut` |
|---|---|---|
| CALLs to the listed subprograms | mocked | `USE REAL CALL "SUB" FROM "SUB.cbl"` |
| Their files, SQL, CICS, outside CALLs | n/a | mocked in the suite (a mock body names the subprogram's own data) |
| Proves | each paragraph of PROGRAM | caller and callee agree: LINKAGE layout, return codes, units |
| `mutate`, `report --mutate` | yes | no (`run` and `lint` only, so far) |

Build the unit suite first and get it green; the load-module suite comes
after it, in step 6.

## The contract (holds in every mode, hands-off included)

1. **The run decides pass/fail.** Never say a test passes without a
   `mockymock run` result that says so. No toolchain (neither Docker nor
   a native GnuCOBOL, `mockymock doctor` says which) means no run: say
   that plainly and continue with the static steps.
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
journal is `.mockymock/<suite>.journal.jsonl` next to the `.cut`,
append-only, one per suite: the load-module suite's steps go to
`--cut PROGRAM.module.cut`, or its report shows an empty journal.

`PROGRAM.cut` in this skill stands for the suite's real path. New suites
usually go under `tests/`, mirroring the program's folder; before the
first one exists, `mockymock suites PROGRAM.cbl` says where it will be
(and `--name module` where the load-module suite will be). Use that path
in every `--cut`, from the first journal line on. Several steps at once take one call: write them as JSON lines
(`{"step": ..., "summary": ..., "decision": ...}`) and pass
`--from steps.jsonl` (or `--from -` for stdin).

## Workflow

### 1. Ground check

```bash
mockymock skills mode
mockymock doctor            # toolchain (Docker or native GnuCOBOL), config, copybooks
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

With subprograms, run `program-flow` and `business-rules` on each of them
too, and note what PROGRAM passes in each CALL and what it does with what
comes back (a return code, an output field).

### 3. Plan

Build one checklist, in PROCEDURE DIVISION order: every reachable paragraph,
and under each, the business rules it holds (rule id, line, one-line
meaning). Each rule arm is a test you owe: a decision with THEN/ELSE needs
both arms, a validation needs an accepted and a rejected input, a
calculation needs a value worked out by hand from the formula. Share the
plan before writing anything (guided/hands-on), and journal it.

With subprograms, add a second list for the load-module suite: each rule
of a subprogram that PROGRAM's inputs can reach, and each value PROGRAM
reads back from a CALL (the return code it tests, the field it uses).
Those are the cases only the real callee can prove. `business-rules`
leaves out what it calls technical rules (`technical_rules_excluded`),
such as a subprogram's `IF SQLCODE NOT = 0 ... MOVE 8 TO LK-RC`; when such
a rule writes a LINKAGE field PROGRAM reads, it belongs on the list
(`program-flow` lists every decision). Rule ids restart in each program,
so cite a subprogram's rule with its program: `*> INTENT: PAYCALC:BR-001
...` (and PROGRAM's own with a bare id).

### 4. Scaffold

Follow the `mockymock` skill: `mockymock init PROGRAM.cbl` (data-first,
needs a toolchain for its recording half) or `mockymock generate PROGRAM.cbl`,
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

With subprograms, this is where they run for real. Scaffold the
load-module suite beside the unit suite, one `--real` per subprogram:

```bash
mockymock generate PROGRAM.cbl --name module --seed 1 \
  --real SUB1.cbl --real SUB2.cbl     # -> PROGRAM.module.cut, beside PROGRAM.cut
mockymock lint PROGRAM.module.cut     # names every boundary still unmocked
```

`generate` turns each listed CALL into `USE REAL CALL ... FROM` and puts a
placeholder MOCK in BEFORE-EACH for every boundary inside the
subprograms. The scaffold is data-driven (one case with generated rows),
and a placeholder mock only sets a status: a `MOCK SQL` inside the
subprogram returns SQLCODE 0 and no data, so everything computed from it
is zero. **Fill those mocks before you run anything**, with the data each
case needs (a mock body names the subprogram's own data items), then
write the INTENT cases from the second list in step 3: inputs that reach
the subprogram's rule, the value worked out from that rule, asserted
where PROGRAM shows it. Only then run, and record only what no rule
decides:

```bash
mockymock run PROGRAM.cbl --cut PROGRAM.module.cut                  # INTENT cases
mockymock run PROGRAM.cbl --cut PROGRAM.module.cut --record-expectations
```
`VERIFY CALL "SUB" WAS CALLED n TIMES` still counts real calls. A case
that fails here but passes in the unit suite is the finding this suite
exists for: the mock in the unit suite says something the real callee
does not (a LINKAGE layout, a return code, a unit). Report it with both
sides, and fix the unit suite's mock only once the developer confirms
which side is right.

### 7. Prove the suite, then report

```bash
mockymock report PROGRAM.cbl --cut PROGRAM.cut --execute --mutate
# writes .mockymock/PROGRAM.report.html next to the .cut
```

`--execute` runs the suite with coverage, `--mutate` runs mutation testing
(slower; skip it while iterating and pass it for the final report). Without
a toolchain, pass neither: the report still covers every static step (including
the program analysis) and says what it could not run. If you already ran
`mockymock run` (whole suite) and `mockymock mutate` on this exact program
and suite, `--execute --mutate` reuse their saved results instead of
running them again; `--rerun` forces a fresh run.

`--execute` measures coverage only on a GnuCOBOL with `--coverage`
(3.2). On 3.1 (`cobc --version`) it quietly reuses a saved run with no
coverage, and with `--rerun` it fails. Run the suite yourself instead,
`mockymock run PROGRAM.cbl --cut PROGRAM.cut --json-report run.json`,
then `mockymock mutate ... --json-report mutation.json`, and pass them
with `report --run-json run.json --mutation-json mutation.json`. Say in
the hand-over that line coverage was not measured and why.
`mockymock clean` removes the `.mockymock/` reports and saved results
(journals are kept): that includes the HTML you hand over, so leave it to
the developer.

With subprograms, also report the load-module suite. `mutate` refuses a
suite with `USE REAL CALL`, so run it and pass the result:

```bash
mockymock run PROGRAM.cbl --cut PROGRAM.module.cut --json-report module-run.json
mockymock report PROGRAM.cbl --cut PROGRAM.module.cut --run-json module-run.json
# writes .mockymock/PROGRAM.module.report.html
```

Mutation score and line coverage come from the unit suite's report; say
so in the hand-over. The load-module report analyses PROGRAM only: its
rules, paragraphs and dialect checks leave the subprograms out, and it
matches INTENT labels against PROGRAM's rule ids. Say in the hand-over
which subprogram rules the module suite asserts, from your own step-3
list.

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

With subprograms, add one line for the load-module suite: how many cases,
which subprograms ran for real, any disagreement between a unit-suite mock
and the real callee, and the second report's path.

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
