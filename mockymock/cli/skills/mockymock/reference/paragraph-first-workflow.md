# Paragraph first, whole program second

The order a mockymock suite gets built in, and what to tell the
developer at each step. `SKILL.md` has the short version; this is the
loop in full.

The loop itself is the same whatever mode you're in (`mockymock skills
mode`); the mode decides how much of it comes back to the developer.
This file is written in `guided` terms -- the default. In `hands-on`,
every command below waits for a yes first. In `hands-off`, the
"stop and say so" steps become written entries in the final report
instead, and the run continues. `reference/modes.md` has the detail.

## Why this order

A `TESTCASE` drives exactly one `PERFORM` target. That makes two very
different kinds of test available:

- `PERFORM 2000-POST-PAYMENT` -- one paragraph, its own boundaries
  mocked. If it fails, the paragraph or its mocks are wrong. Nothing
  else can be.
- `PERFORM 0000-MAIN` -- the program's entry paragraph, driving the whole
  `PERFORM` chain with every boundary in it mocked. If it fails, any
  paragraph in the chain could be responsible.

So: get every paragraph green on its own first, then add the end-to-end
cases. The paragraph pass is where bugs get *located*; the whole-program
pass is where ordering, carried state, and total call counts get
*checked*. Running the second pass first means debugging the program and
your own mocks simultaneously, with nothing proven to stand on.

A whole-program case usually runs a loop, and the loop usually calls the
same routine more than once for different reasons (IMS `CBLTDLI` for a
priming GHN, a DLET and the next GHN; `MQGET`; a DB2 access module).
Don't settle for the empty-input path because one `MOCK CALL` body can
only give one answer: use `MOCK CALL "X" ROWS ( ... ) TERMINAL ( ... )`
(see `cut-dsl.md`), one row per call in order, so the case runs one or
two real iterations and `TERMINAL` ends the loop. Pair it with `VERIFY
CALL "X" WAS CALLED <n> TIMES`.

## 1. Build the checklist

```bash
mockymock analyze program-flow PROGRAM.cbl
```

JSON, and the fields that matter here:

- `nodes[].name` -- every paragraph. This is the checklist, in source
  order.
- `entry_points` -- the paragraph the whole-program pass will `PERFORM`
  (usually one, e.g. `["0000-MAIN"]`).
- `edges` -- who `PERFORM`s whom. Tells you which paragraphs are leaves
  (start there) and what the end-to-end chain will actually execute.
- `unreachable_nodes` -- paragraphs nothing performs. Worth naming to the
  developer before writing tests for them: it's usually dead code, and
  that's a finding in itself.

Share this as a plan before writing anything:

```
CLAIMSEG has 3 paragraphs. 0000-MAIN is the entry point and performs
1000-RETRIEVE-CLAIM then 2000-POST-PAYMENT.

Plan: a case for 1000-RETRIEVE-CLAIM, then one for 2000-POST-PAYMENT,
then an end-to-end case through 0000-MAIN. Starting with
1000-RETRIEVE-CLAIM -- it only touches the DL/I GU retrieval.
```

## 2. Scaffold once

```bash
mockymock generate PROGRAM.cbl --per-paragraph
```

(Plain `generate` is the data-driven mode: one case per scenario through
the entry point. `--per-paragraph` is the paragraph pass.)

One `TESTCASE` per paragraph **that touches at least one boundary**,
named `"<PARAGRAPH> boundaries: <categories>"`, each with placeholder
mock bodies and every boundary reachable from that paragraph already
mocked (an unmocked reachable boundary is a refusal, not a warning -- see
`UNMOCKED_*` in `mockymock explain --list`).

Two things to say out loud after this:

- **Which paragraphs got no case.** A paragraph with no boundary never
  appears in the scaffold. Those need a hand-written case -- `PERFORM
  <paragraph>` plus `MOVE`s to set up its inputs and `EXPECT`s on what it
  computes -- and they're frequently the paragraphs whose logic matters
  most.
- **Which boundaries could not be mocked at all.** `generate` prints
  them (an unidentifiable dynamic `CALL`, an unspliceable nested site).
  Name them by paragraph, not as a count: any test case reaching one will
  be refused by `run` until it's resolved.

Never re-run plain `generate` over a `.cut` you've started editing -- it
overwrites the output path silently. To add mocks to a file in progress:

```bash
mockymock generate PROGRAM.cbl --fill PROGRAM.cut
```

`--fill` inserts only the `MOCK` blocks the file's existing cases are
missing, from the same analysis `lint` uses. Existing directives,
`EXPECT`s, `VERIFY`s, and comments are preserved byte for byte, and an
existing `MOCK` block is never edited even if its body is empty.

## 3. The loop, one paragraph at a time

For each paragraph on the checklist:

**a. Say which paragraph you're on and what it does.** One sentence,
from the COBOL: what it reads, what it computes, what it writes.

**b. Fill in that one case's mock bodies.** Give each boundary behavior
the paragraph will actually see -- a realistic record, a status code, a
`RETURN-CODE`. Leave the other cases alone.

**c. Lint.**

```bash
mockymock lint PROGRAM.cbl --cut PROGRAM.cut
```

No Docker, no compile -- the fast inner loop. Every refusal `run` would
raise shows up here first, and an `UNMOCKED_*` one comes with a
ready-to-paste `Add to this TESTCASE:` block (the same text `--fill`
would insert).

**d. Run that case alone.**

```bash
mockymock run PROGRAM.cbl --cut PROGRAM.cut --case "<the one case's name>"
```

`--case` takes the exact `TESTCASE` name and is repeatable; the suite
still compiles as one binary, but only the selected cases are spliced in,
so the verdict is about this paragraph and nothing else.

**e. Make it assert something real.** A case that only proves the
paragraph doesn't crash is worth little:

- `EXPECT <data-name> TO BE <value>` on each field the paragraph writes.
- `VERIFY <category> <key> WAS CALLED ONCE` / `WAS PERFORMED NEVER` on
  the boundaries it should and shouldn't reach. The `NEVER` form is how
  you pin a branch that *didn't* run -- a boundary inside a skipped `IF`
  still needs its `MOCK` (static reachability), so `NEVER` is the
  assertion that says it stayed skipped.
- `run --record-expectations` turns every `*> STUB EXPECT <name>` comment
  into a real `EXPECT` filled in from an actual run. It never overwrites
  a hand-written `EXPECT` and never changes the exit code. Recorded
  values are *characterization*, not intent -- read them back to the
  developer and ask whether each is actually correct.

**f. Report and move on.**

```
Paragraph 1 of 3 -- 1000-RETRIEVE-CLAIM (DL/I GU on CLAIM-SEG)
  mocked: GU returns a 250.00 claim with a blank status
  PASS: WS-CLAIM-FOUND = "Y", WS-CLAIM-AMOUNT = 250.00, GU called once
  next: 2000-POST-PAYMENT (inserts the payment segment)
```

Don't start the next paragraph while this one is red.

### A paragraph is done when

- it has at least one passing case,
- every field it writes is covered by an `EXPECT`,
- every boundary it touches is covered by a `VERIFY`, and
- a branch worth separating has its own case (a found/not-found pair, an
  error status, an empty read) rather than one case doing everything.

### When a paragraph won't go green

In order, and say which one you're doing:

1. `mockymock run ... --case "<name>" --trace` -- replays that one case's
   executed path and the mocks that fired, in order. `--trace` requires
   exactly one `--case`. This is the fastest way to see a mock that never
   fired or a branch that went the other way.
2. `mockymock explain <CODE>` for any refusal code -- the catalogued
   meaning, rather than your paraphrase of the message.
3. `--verbose` (prints the instrumented source path on a compile failure)
   and `--keep-sandbox` (keeps the sandbox for inspection) when the
   failure is in the compile rather than the assertions.
4. If it's the program that looks wrong rather than the test, **stop and
   say so**. Name the paragraph, the value you expected, the value you
   got, and ask whether to keep the assertion (documenting a bug) or
   match the current behavior. Don't quietly rewrite the assertion to
   whatever the program produced.
5. If the developer wants to move on, park it explicitly -- say it's
   parked and why, and keep it on the checklist as red. Never drop it
   silently. In `hands-off` there's nobody to ask: park it yourself,
   after the same trace/explain loop, with the expected and actual
   values written down, and go on to the next paragraph. A parked
   paragraph is a reported finding, never a quietly relaxed assertion.
6. **Where a confirmed program bug lives**: move the case that shows it,
   with its assertion unchanged, into a second suite of the same program,
   `PROG.known-bugs.cut` beside the main one (mockymock pairs
   `PROG.<topic>.cut` with `PROG.cbl` by name; elsewhere, give it a
   `PROGRAM` line). The main suite then stays green, which `mutate` and `report`
   need (mutation compares against a passing baseline), and the bug suite
   stays red until the program is fixed, which is the point. Say both in
   the report.

## 4. Graduating to the whole program

Only once every paragraph on the checklist is green (or explicitly
parked). Say that you're switching passes, and why now -- and in
`guided`/`hands-on`, ask before you do; in `hands-off`, just switch and
note it in the final report.

Write the case by hand and let `--fill` do the mocks:

```
TESTCASE "0000-MAIN runs end-to-end via its real entry point"
    PERFORM 0000-MAIN
    EXPECT WS-CLAIM-FOUND TO BE "Y"
    EXPECT WS-PAYMENT-POSTED TO BE "Y"
```

```bash
mockymock generate PROGRAM.cbl --fill PROGRAM.cut   # adds every MOCK the chain needs
mockymock run PROGRAM.cbl --cut PROGRAM.cut         # whole suite
```

What these cases are for -- assert on what a paragraph case *cannot* see:

- **End state**, after the whole chain, not after one paragraph.
- **Total call counts** across the run: `VERIFY DLI "GU" WAS CALLED
  ONCE`, `VERIFY CALL "DISCRATE" WAS PERFORMED 3 TIMES`. A boundary
  called once per paragraph case may be called five times end to end,
  and that number is where an accidental loop shows up.
- **Carried state**: a field one paragraph sets and a later one reads.
  Paragraph cases `MOVE` that field into place by hand; only the
  end-to-end case proves the program itself puts it there.
- **Order**, via `--trace` on the end-to-end case: the mock timeline is
  the execution order, in one list.

Mechanics worth knowing:

- The `PERFORM` target is `entry_points[0]` from `program-flow`. A
  `GOBACK`/`STOP RUN`/`EXIT PROGRAM` reached through a plain `PERFORM`
  chain from there is neutralized, not fatal; so is a mocked `EXEC CICS
  RETURN`/`XCTL`/`ABEND`, which runs its mock body and then ends the
  case (with `RESP(field)`, only while the field is still 0 -- set it in
  the mock to simulate a failed command) -- that's exactly what makes an end-to-end
  case possible at all. A layout mockymock can't neutralize soundly
  refuses with `UNSUPPORTED_TERMINATOR_LAYOUT` instead of guessing;
  `mockymock explain UNSUPPORTED_TERMINATOR_LAYOUT` has the detail, and
  the message itself usually names the safe rewrite.
- `PERFORM <first> THRU <last>` is available when a program's entry
  paragraph doesn't perform everything -- a straight-line PROCEDURE
  DIVISION with no driver paragraph, typically.
- Cover the interesting whole-program paths, not every combination:
  the happy path, then one per externally-visible failure mode (record
  not found, nonzero `RETURN-CODE`, an error file status).

For data-driven scenario coverage on top of that, generate into a
separate file and copy across the cases you want:

```bash
mockymock generate PROGRAM.cbl --with-data --seed 7 --scenarios branches -o scenarios.cut
```

Each scenario case is itself a whole-program case (it `PERFORM`s the
scenario's own entry paragraph) with generated data and
`EXPECT`/`VERIFY` lines. Recommend the mode from the program's own
`scenario_coverage` and confirm before generating -- see
`scenario-generation.md`.

## 5. Finish by testing the tests

```bash
mockymock run PROGRAM.cbl --cut PROGRAM.cut --coverage
mockymock mutate PROGRAM.cbl --cut PROGRAM.cut
```

Coverage says which lines the suite reached; mutation says which changes
it would have *caught*. Report a survivor as the missing assertion it is
-- "nothing in the suite fails if the discount is never applied to the
total" -- and offer to add the assertion that kills it.

## Worked example in the repo

`examples/claimseg/` is this workflow's output: `CLAIMSEG.cut` has two
cases for `1000-RETRIEVE-CLAIM` (found / not found), two for
`2000-POST-PAYMENT` (inserts / skips, the second `VERIFY`ing the insert
was `PERFORMED NEVER`), and then `"0000-MAIN runs end-to-end via its
real entry point"` driving the full chain with both DL/I boundaries
mocked and call counts verified.
