# Intent vs characterization: where an expected value comes from

A COBOL test is only as useful as the reason its expected value is right.
An assistant left alone writes the easiest passing test: run the program,
copy what it printed into an EXPECT. That suite passes today and will keep
passing if the program is wrong, because it asserts the bug. The label
contract makes the difference visible and countable.

## The labels

A label is a comment line directly above the assertions it covers:

```
TESTCASE "2000-CALC-DISCOUNT gives 5% over 1000.00"
    MOVE 1200.00 TO ORD-AMOUNT
    PERFORM 2000-CALC-DISCOUNT
    *> INTENT: BR-004 orders over 1000.00 get 5% off (ORDRPROC.cbl:212)
    *> 1200.00 - 5% = 1140.00
    EXPECT WS-NET-AMOUNT TO BE 1140.00
    EXPECT WS-DISCOUNT-PCT TO BE 0.05
    *> CHARACTERIZATION: audit counter, no rule says what it should be
    EXPECT WS-AUDIT-COUNT TO BE 1
```

- A label covers every EXPECT/VERIFY after it until the first blank line,
  the next label, the next TESTCASE, or any other directive. Plain comment
  lines in between (like the arithmetic above) do not end it.
- A label at the top of a test case (directly above its TESTCASE line, or
  before its MOCK blocks and setup) is the case's label: it covers every
  assertion in the case that has no label directly above it. Use it when
  one label is true of the whole case; label groups individually when they
  differ.
- A label that covers no assertion (one after the last assertion, a second
  label at the top of a case) is a lint warning,
  `ORPHAN_ASSERTION_LABEL`, and the report names its line.
- `*> INTENT:` -- the value follows from the program's intent: a business
  rule from `business-rules` (cite its id, `BR-004`), a spec, a copybook
  comment, or the developer's own words. If it fails, the program is the
  likelier culprit, and `mockymock report` files it as a **suspected bug**.
- `*> CHARACTERIZATION:` -- the value is what the program did. It pins
  current behavior (useful before a refactor) and proves nothing about
  correctness. `run --record-expectations` writes
  `*> CHARACTERIZATION: recorded by mockymock run --record-expectations`
  above everything it records.
- No label -- counted as unlabelled, and reported as a low finding.

Rule ids in an INTENT label (`BR-001`, any case) are matched against
`business-rules` output, so the report can show which rules have an
intent assertion and which do not.

## Deriving the expected value, per rule kind

`mockymock analyze business-rules PROGRAM.cbl` classifies each rule:

| Kind | What it gives you | Tests you owe |
|---|---|---|
| `decision` | One branch per IF/EVALUATE arm, each with its condition and actions | One case per arm. Pick inputs on each side of every boundary in the condition (`> 1000` → 1000.00 and 1000.01). |
| `validation` | A decision where an arm rejects (error literal, reject path, class test) | An accepted input and a rejected one; assert the error flag/message and that the downstream boundary was **not** reached (`VERIFY ... WAS CALLED NEVER`). |
| `calculation` | A normalized formula and its inputs/outputs | A value worked out by hand from the formula, written in the label. Include a rounding or truncation case when the target PICTURE has fewer decimals than the arithmetic produces. |

Level-88 names in a condition are spelled out in the rule's
`condition_names`; use the underlying value in your MOVE.

## When an INTENT assertion fails

1. `mockymock run ... --case "<name>" --trace`: did your inputs and mocks
   select the arm you meant? Most failures are test setup.
2. If the setup is right, the program disagrees with the rule. Do not edit
   the program and do not change the assertion. Report: paragraph, rule id
   and text, inputs, expected, actual, and the line that decides it.
3. Ask (guided/hands-on) whether to keep it failing as a documented bug or
   to switch it to a CHARACTERIZATION of current behavior with the bug
   written in the label. Hands-off: keep it failing and list it first in
   the hand-over.

## When there is no rule to cite

Not every field has a rule behind it (counters, timestamps, trace fields).
Label those CHARACTERIZATION and say why. An honest characterization is
better than an INTENT label nobody can trace to anything.
