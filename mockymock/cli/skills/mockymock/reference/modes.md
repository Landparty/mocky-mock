# Modes: how closely the developer is watching

`SKILL.md` says *what* to do -- paragraph pass, then whole-program pass.
This file is the other axis: *how much you stop and check in while you
do it*.

Find out which mode you're in before you start, once per session:

```bash
mockymock skills mode
```

It prints the active mode, where it came from (a project config file, or
the built-in default), and the same contract this file describes.
`mockymock doctor` reports it too, on the `AI assistant mode` line -- so
if you're already running `doctor` in step 0, you have it.

`mockymock skills mode --json` is the machine-readable form, if you'd
rather parse it than read it.

## The three modes

| Mode | In one line |
|---|---|
| `hands-on` | Propose first, wait for a yes before each change. |
| `guided` | Narrate every step, stop at the checkpoints. **(default)** |
| `hands-off` | Run the whole workflow, report once at the end. |

They are a dial, not three unrelated behaviors: the same paragraph-first
workflow runs in all three, and what changes is how many of its decisions
you bring back to the developer.

### `hands-on`

The developer is at the keyboard and wants to see each step before it
happens. Typical when the COBOL is unfamiliar, the program is
production-critical, or they're learning mockymock by watching.

- **Before every command and every edit**: say what it is, which
  paragraph it's for, and what you expect to learn. Then wait.
- **Read-only commands are free.** `analyze`, `fixtures`, `collect`,
  `lint`, `explain`, `doctor` change nothing -- run them without asking.
  Everything that writes a file (`generate`, `init`, `run
  --record-expectations`, your own `.cut` edits) or executes the program
  (`run`, `debug`, `mutate`) waits for a yes.
- **Show the change, don't just describe it.** The actual `MOCK` block,
  the actual `EXPECT` line, the actual command line. They may want to
  type it themselves.
- **One paragraph at a time, and ask which one is next** rather than
  taking them in order.

A hands-on exchange looks like this:

```
Next: 2000-POST-PAYMENT (inserts the DL/I payment segment when a claim
was found). I'd like to run it on its own to see what the ISRT does with
an empty mock body:

    mockymock run CLAIMSEG.cbl --cut CLAIMSEG.cut \
      --case "2000-POST-PAYMENT boundaries: dli"

Go ahead?
```

### `guided` (the default)

The developer is around, following along, and doesn't want to approve
each command. This is what `SKILL.md`'s "Keep the developer in the loop"
section describes, and it's what a project with no `ai_mode` setting
gets.

- **Before each command**: one sentence -- what you're running, on which
  paragraph, what you expect.
- **After it**: the result in plain language, naming the paragraphs,
  boundaries, and data-names involved.
- **At the end of each loop iteration**: where things stand -- "3 of 7
  paragraphs green", what's next, what's parked.
- **Stop and ask** before: overwriting a `.cut` that already has
  hand-written cases, choosing a `--scenarios` mode, moving from the
  paragraph pass to the whole-program pass, and parking a failing
  paragraph to come back to later.
- Everything else -- mock bodies, `EXPECT`/`VERIFY` lines, which
  paragraph is next -- you decide and announce, rather than ask.

### `hands-off`

The developer has delegated the suite and stepped away. Nobody is
reading a running commentary, so don't write one -- but the *record*
still matters, because it's all they'll have when they come back.

- **Run the loop end to end**: scaffold, paragraph pass one paragraph at
  a time, whole-program pass, then `--coverage` and `mutate`. The order
  doesn't change; only the checkpoints do.
- **Decide the things `guided` would ask about**, and write down what
  you decided and why. Pick the `--scenarios` mode from the program's own
  `scenario_coverage.total_arms` (`scenario-generation.md` section 2) --
  say which you picked and what the arm count was.
- **Never stall.** A paragraph that won't go green after the
  `--trace`/`explain`/`--verbose` loop gets **parked in writing** and the
  run continues to the next one. A question nobody is there to answer is
  not a reason to stop three paragraphs in.
- **Report once, at the end**, and make it complete:

```
CLAIMSEG: 6 of 7 paragraphs green, end-to-end case green, suite runs in 4s.

  green    1000-RETRIEVE-CLAIM (2 cases: found / not found)
           2000-POST-PAYMENT (2 cases: inserts / skips)
           ... 
  parked   4000-REPRICE -- EXPECT WS-NET-DUE = 1250.00, actual 1180.00.
           The program applies the discount twice (lines 212 and 240).
           Left red rather than asserting 1180.00. Needs your call.
  decided  --scenarios branches (11 branch arms, 4 unresolved) rather
           than `all`, which would have produced 60+ cases.
  coverage 88% of PROCEDURE DIVISION lines; 2 mutants survived, both in
           4000-REPRICE (see parked, above).
```

The parked entry is the shape that matters: the expected value, the
actual value, what you think is wrong, and what you did *not* do about
it.

## The floor: what you ask about in every mode

A mode says how often you check in. It never says what you may destroy
or quietly decide. These four hold in `hands-off` exactly as they do in
`hands-on`:

1. **Never edit the `.cbl` program under test.** The suite is the
   deliverable; the program is the developer's.
2. **Never overwrite a `.cut` containing cases you didn't write this
   session.** `generate` and `mockymock init` both refuse an existing
   `.cut` without `--force`; don't reach for `--force` on the developer's
   behalf -- use `generate --fill <cut>` to add missing mocks to a file
   in progress, or `-o <new file>` to generate beside it.
3. **Never turn a suspected program bug into a passing assertion.** If
   the program produces 1180.00 and you expected 1250.00, that's a
   finding, not a value to paste into an `EXPECT`. In `hands-off` you
   don't stop for it -- but you don't guess either: park it, with both
   numbers, and leave the case red.
4. **Never act outside the mockymock loop on the developer's behalf** --
   git commits, pushes, deleting files, installing tooling.

Rule 3 is the one people get wrong when they hear "hands-off". Hands-off
means *don't interrupt*, not *decide anything*. An unanswerable question
becomes a written open item, not a silent assumption.

## Switching modes

The developer can say so in conversation ("just run the whole thing,
I'll read it later") -- honor it for the session, and offer to persist
it:

```bash
mockymock skills mode --set hands-off
```

That writes `ai_mode = "hands-off"` to the project's `mockymock.toml`
(creating it if there isn't one), so the next session starts in the same
mode without being told again. If the project configures mockymock
through `pyproject.toml`'s `[tool.mockymock]` instead, the command
refuses rather than writing a `mockymock.toml` that would shadow that
table -- it prints the one line to add, and the developer or you can add
it there.

Two things worth saying out loud when you switch:

- Moving **toward** `hands-off`: name what you'll now be deciding alone
  (the `--scenarios` mode, when to graduate to the whole-program pass,
  which paragraphs to park) so it isn't a surprise in the final report.
- Moving **toward** `hands-on`: pick up from the current paragraph
  rather than re-running what's already green.

A mode also isn't a commitment to silence. In `hands-off`, a refusal you
genuinely can't work around (`UNSUPPORTED_TERMINATOR_LAYOUT` on the
entry paragraph, say, which blocks the whole-program pass outright) is
worth surfacing when you hit it rather than at the end -- the run can't
produce what was asked for, and that's news.
