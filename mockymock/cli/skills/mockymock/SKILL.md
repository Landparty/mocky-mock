---
name: mockymock
description: Use when writing or running .cut test files for mockymock (a COBOL unit-test framework that mocks CALL/file-I-O/EXEC SQL·CICS·DLI/ACCEPT boundaries and runs the real program under GnuCOBOL), when a mockymock run fails or refuses and the reason needs interpreting, or when the developer asks to change how hands-on or hands-off the assistant should be while building a suite.
---

<!--
Maintainer note: this is a curated duplicate of docs/options-reference.md
in the mocky-mock repo, adapted for agent consumption. A .cut directive or
CLI flag change should be reflected in reference/cut-dsl.md and
reference/cli-flags.md here too, and an AI-mode change (mockymock/cli/
ai_mode.py) in reference/modes.md. A FixtureBundle schema change
(docs/fixture-bundle-schema.md in cobol-parser) should be reflected in
reference/scenario-generation.md.
-->

# mockymock: COBOL unit testing

mockymock mocks a COBOL program's external boundaries (subprogram `CALL`s
including MQ, file I/O, `EXEC SQL`/`CICS`/`DLI`, console `ACCEPT`),
compiles the instrumented copy with real GnuCOBOL inside Docker, runs it,
and reports pass/fail. Use it to write and run `.cut` test files against
`.cbl` programs.

## How to build a suite: one paragraph at a time, then the whole program

Work in two passes, and always tell the developer which one you're in:

1. **Paragraph pass** -- one `TESTCASE` per PROCEDURE DIVISION paragraph,
   each `PERFORM`ing that paragraph alone. Drive them green **one at a
   time**: fill in one paragraph's mocks, run that single case, get it
   passing, then move to the next. A case this small can only fail for
   one reason, so a failure points straight at the paragraph you just
   touched.
2. **Whole-program pass** -- once every paragraph has a green case, add
   end-to-end cases that `PERFORM` the program's entry paragraph (e.g.
   `PERFORM 0000-MAIN`), driving the real `PERFORM` chain with every
   boundary in it mocked at once. These catch what paragraph-level cases
   structurally can't: ordering, state carried between paragraphs, and
   boundaries that fire a different number of times across the whole run.

Don't invert the order. A whole-program case that fails first can be
failing because of any paragraph in the chain, and you'll be debugging
the program and your own mocks at the same time.
`examples/claimseg/CLAIMSEG.cut` in the mocky-mock repo is exactly this
shape: four paragraph cases, then `"0000-MAIN runs end-to-end via its
real entry point"`.

The full loop -- how to pick the next paragraph, what to do with a
paragraph that has no boundaries, and when a paragraph is done enough to
move on -- is in `reference/paragraph-first-workflow.md`.

## Modes: how much to check in while you do it

How closely the developer wants to be involved is a per-project setting,
not a guess. Read it once at the start of a session, before the first
command:

```bash
mockymock skills mode      # also on `mockymock doctor`'s "AI assistant mode" line
```

| Mode | What it changes |
|---|---|
| `hands-on` | Propose first, wait for a yes before each change. Read-only commands (`analyze`, `fixtures`, `collect`, `lint`, `explain`, `doctor`) are free; anything that writes a file or runs the program waits. |
| `guided` | **(default)** Narrate every step, decide the small things yourself, stop at the checkpoints listed below. |
| `hands-off` | Run the whole workflow and report once at the end. Decide what `guided` would ask about, write down what you decided, park what won't go green, don't stall. |

The workflow below is the same in all three -- the mode only changes how
many of its decisions come back to the developer. If the developer says
"just run the whole thing" mid-session, honor it, and offer `mockymock
skills mode --set hands-off` to make it stick for next time.

**The floor holds in every mode, `hands-off` included**: never edit the
`.cbl` under test, never overwrite a `.cut` containing cases you didn't
write this session, never turn a suspected program bug into a passing
assertion, never act outside the mockymock loop (git, installs) on the
developer's behalf. Hands-off means *don't interrupt* -- not *decide
anything*. An unanswerable question becomes a written open item, not a
silent assumption.

`reference/modes.md` has each mode in full, with a worked exchange for
`hands-on` and the shape of a `hands-off` final report.

## Keep the developer in the loop

This section is the `guided` contract -- the default, and the baseline
the other two modes adjust (`hands-on` adds a wait before each step;
`hands-off` folds all of it into one report at the end).

They can't see your reasoning. They may not have written this COBOL, and
may never have run mockymock. Narrate, in this shape:

- **Before each command** -- one sentence: what you're about to run, on
  which paragraph, and what you expect to learn.
- **After it** -- the result in plain language: name the paragraphs,
  boundaries, and data-names involved, not just counts ("`GU` retrieval
  in `1000-RETRIEVE-CLAIM` now returns a 250.00 claim", not "1 mock
  added"). Never paste a raw fixture bundle or JSON blob at them;
  summarize it.
- **Then, where things stand** -- "3 of 7 paragraphs green", which
  paragraph is next, and anything you parked. A short checklist beats
  prose.
- **Stop and ask** before: overwriting a `.cut` file that already has
  hand-written cases, choosing a `--scenarios` mode, moving from the
  paragraph pass to the whole-program pass, or parking a failing
  paragraph to come back to later. In `hands-on`, every command joins
  that list; in `hands-off`, only the floor above does -- decide the
  rest, and record each decision in the final report.
- **On a refusal or failure** -- name the code, say what it means in one
  line (`mockymock explain <CODE>` is the catalogue), and give the
  concrete fix. An `UNMOCKED_*` refusal prints a ready-to-paste
  `Add to this TESTCASE:` block; show it rather than paraphrasing it.

A status report after one loop iteration looks like this:

```
Paragraph 2 of 5 -- 2000-POST-PAYMENT (inserts the DL/I payment segment)
  ran:  mockymock run CLAIMSEG.cbl --cut CLAIMSEG.cut \
          --case "2000-POST-PAYMENT inserts a payment segment for a found claim"
  PASS: WS-PAYMENT-POSTED flips to "Y", ISRT fired exactly once
  next: 3000-WRITE-AUDIT (writes the audit record) -- say the word if
        you'd rather jump straight to the end-to-end case
```

## Workflow

### 0. Check the ground (once per program)

```bash
mockymock skills mode                             # hands-on / guided / hands-off -- how much to check in
mockymock doctor                                  # Docker, toolchain, config, mode, in one screen
mockymock analyze program-flow PROGRAM.cbl        # every paragraph, the entry point, who PERFORMs what
mockymock fixtures PROGRAM.cbl --scenarios all    # what's mockable (no .cut yet)
mockymock collect PROGRAM.cbl --cut PROGRAM.cut --json --boundaries   # ... or, with a .cut already
```

`program-flow`'s paragraph list is your checklist for the paragraph
pass -- share it as the plan before you write anything. From the
`fixtures` bundle, explain in plain language what's mockable (which
`CALL`s/files/SQL/`ACCEPT`, and each one's direction) before generating;
`reference/scenario-generation.md` says exactly which fields to read and
how to phrase it. Only `setup`, `run`, `init`, `debug`, and `mutate`
need Docker -- the paragraph pass's `lint` loop works without it.

### 1. Scaffold once

```bash
mockymock generate PROGRAM.cbl     # one TESTCASE per paragraph, placeholder mocks
```

Cases come out named `"<PARAGRAPH> boundaries: <categories>"`, each
mocking every boundary reachable from that paragraph.

- Paragraphs with **no** boundary get no case at all. Compare against the
  `program-flow` list, name the ones that were skipped, and hand-write a
  `PERFORM` + `EXPECT` case for each -- they're often the pure-computation
  paragraphs most worth testing.
- `generate` **refuses to overwrite** an existing `.cut` without
  `--force` (don't pass it on the developer's behalf). Run it once, at
  the start. After that, use `mockymock generate PROGRAM.cbl --fill
  PROGRAM.cut`, which inserts only the missing `MOCK` blocks and never
  edits a line you wrote.
- `mockymock init PROGRAM.cbl` is the data-first alternative (`generate
  --with-data` plus `run --record-expectations` in one step): real
  generated data and recorded expected values instead of empty bodies. It
  refuses to overwrite an existing `.cut` without `--force`, and needs
  Docker for the recording half.

### 2. Paragraph pass -- one paragraph at a time

For each paragraph, in PROCEDURE DIVISION order:

```bash
mockymock lint PROGRAM.cbl --cut PROGRAM.cut                 # fast, no Docker
mockymock run PROGRAM.cbl --cut PROGRAM.cut --case "<that one case>"
```

a. Fill that case's mock bodies with behavior the paragraph will actually
   see (see `reference/cut-dsl.md` for every directive).
b. `lint` until clean -- it prints every refusal `run` would, with no
   Docker dependency, so it's the fast inner loop.
c. `run --case "<name>"` -- **only that case**. The suite still compiles as
   one binary, but you get one paragraph's verdict, unmixed.
d. Make it assert something real: `EXPECT` on the fields the paragraph
   writes, `VERIFY` on the boundaries it should (or shouldn't) hit.
   `run --record-expectations` fills in `*> STUB EXPECT` comments from
   an actual run; `run --case "<name>" --trace` replays that one case's
   path plus its mock timeline when the result surprises you.
e. Report the verdict and what's next, then move on. Don't start the next
   paragraph while this one is red.

`reference/paragraph-first-workflow.md` covers the loop in full,
including what to do with a paragraph that won't go green.

### 3. Whole-program pass

Once every paragraph is green, add end-to-end cases. Write each one by
hand -- `TESTCASE "<program> runs end-to-end via its real entry point"`,
`PERFORM <entry paragraph>` -- then let `--fill` insert the mocks for
every boundary in the chain:

```bash
mockymock generate PROGRAM.cbl --fill PROGRAM.cut    # add the MOCK blocks the new case needs
mockymock run PROGRAM.cbl --cut PROGRAM.cut          # whole suite now
```

Assert on the program's *end state*, and `VERIFY` call counts across the
whole chain -- that's the part paragraph cases can't check. A
`GOBACK`/`STOP RUN` reached through a plain `PERFORM` chain from the
entry paragraph is neutralized rather than fatal; a layout that can't be
neutralized soundly refuses with `UNSUPPORTED_TERMINATOR_LAYOUT`, which
`mockymock explain` will spell out.

For broader data-driven coverage, generate scenario cases into a
*separate* file and copy across the ones you want -- never over the file
you've been editing:

```bash
mockymock generate PROGRAM.cbl --with-data --seed 7 --scenarios <mode> -o scenarios.cut
```

Recommend `<mode>` from the program's own `scenario_coverage.total_arms`
(`reference/scenario-generation.md` section 2 has the three-way
reasoning) and confirm it with the developer rather than defaulting
silently.

### 4. Prove the suite is worth something

```bash
mockymock run PROGRAM.cbl --cut PROGRAM.cut --coverage    # which lines the suite actually reaches
mockymock mutate PROGRAM.cbl --cut PROGRAM.cut            # which changes it would actually catch
```

A surviving mutant is a missing assertion -- report it as such ("nothing
fails if the discount rate is never applied"), and offer to fix it.

To hand the result over, `mockymock report PROGRAM.cbl --cut PROGRAM.cut
--execute --mutate` runs both and writes one HTML page of every step,
finding and test case. For testing a whole program end to end (plan from
business rules, INTENT vs CHARACTERIZATION assertions, verification
levels), follow the `cobol-test` skill, which drives this one.

### 5. When a run fails or refuses

Read the printed reason literally: mockymock is deliberately fail-closed,
so a refusal names exactly what it couldn't soundly rewrite (`GO TO` into
a mock target, `ALTER`, a parse warning) rather than silently skipping or
mis-mocking. `mockymock explain <CODE>` gives the catalogued explanation
for any refusal code (`--list` for all of them). `run --verbose` prints
the instrumented source path on a compile failure; `--keep-sandbox` keeps
the evidence. Translate the code for the developer instead of forwarding
it raw.

## Load-module suites: real subprograms

Once the entry program's unit suite is green, a load-module suite runs it
with its in-module subprograms for real: `USE REAL CALL "PAYCALC" FROM
"PAYCALC.cbl"` links the subprogram instead of mocking the CALL, and the
suite's MOCKs answer the subprogram's own files, SQL, CICS and outside
CALLs (a mock body names the data of the program its statement is in).
Scaffold one with `mockymock generate MAIN.cbl --real SUB.cbl`, then
`run --record-expectations`. Every boundary of a real program must be
mocked in every case that makes it real; `lint` names each missing one.
Example: `examples/paymod/`.

## Full reference

- `reference/modes.md` -- `hands-on` / `guided` / `hands-off` in full:
  what each one decides for itself, what it always asks about, and how to
  switch.
- `reference/paragraph-first-workflow.md` -- the paragraph-at-a-time loop
  and the whole-program pass it graduates into, plus what to report at
  each step.
- `reference/cut-dsl.md` -- every `.cut` directive: `MOCK`/`END-MOCK`
  categories, `ROWS` (one response per call: SQL/READ/RETURN/CALL/MQ/DLI), `EXPECT`, `VERIFY`, `FILE-STATUS IS`,
  the `BEFORE-ALL`/`BEFORE-EACH`/`AFTER-EACH`/`AFTER-ALL` suite hooks,
  `PROVIDER`/`HEADER`/`ROW`, `*> STUB EXPECT`.
- `reference/cli-flags.md` -- every subcommand and flag: `setup`, `init`,
  `generate`, `fixtures`, `run`, `debug`, `lint`, `mutate`, `suites`,
  `collect`, `explain`, `dashboard`, `doctor`, `export`, `analyze`,
  `skills`, `report`, `journal`, `clean`.
- `reference/scenario-generation.md` -- how to read a `mockymock
  fixtures` bundle (boundary inventory, branch-arm coverage, unresolved
  gaps), how to recommend a `--scenarios` mode, and how to phrase a
  generation read-back.
