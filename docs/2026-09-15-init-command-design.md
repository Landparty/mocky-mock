# `mockymock init`: a first scaffold that asserts something (2026-09-15)

## Problem

The default path to a first test suite is `mockymock generate PROG.cbl`,
which emits one `TESTCASE` per paragraph with empty `MOCK ... END-MOCK`
bodies and no `EXPECT`/`VERIFY` at all (confirmed by scaffolding
`examples/invupdt/INVUPDT.cbl` with plain `generate`: every case is
`MOCK <verb> <key> \n END-MOCK \n PERFORM <paragraph>`, nothing else). A
suite like that passes trivially and proves nothing.

The tool already has a path that produces a suite with real assertions:

1. `generate --with-data --seed N` -- uses cobol-parser's
   `ProgramFixtureGenerator` to fill mock bodies with generated data and
   emit `*> STUB EXPECT <name>` comments (`README.md`'s own example
   command, `mockymock/dsl/generator.py`'s bundle-driven path).
2. `run --record-expectations` -- runs the suite for real and turns every
   stub comment into a real `EXPECT` line holding the value the program
   actually produced (`docs/2026-08-04-record-expectations-design.md`).

That path needs Docker (`run` always does), two separate commands, and
knowledge that step 2 exists at all -- it's documented under "Beyond
pass/fail" in the README, not presented as *the* onboarding path. A new
user who runs plain `generate` (the one command every doc example leads
with) gets the empty-assertion version and has no signal that a better
one exists two commands away.

## Goals

- One command takes a `.cbl` (and nothing else the user must already
  know to ask for) to a `.cut` file with real, golden-recorded
  assertions, when Docker is available.
- The same command degrades gracefully -- and says so -- when Docker
  isn't set up yet, rather than failing opaquely.
- Existing `generate`/`run --record-expectations` are unchanged; `init`
  is additive sugar over them, not a replacement.

## Non-goals

- `init` does not change what `--with-data`/`--record-expectations`
  themselves do -- it is purely a composition of two existing, tested
  code paths. No new fixture-generation or recording logic.
- `init` never overwrites an existing `.cut` file for the same program
  without `--force` (symmetry with `generate`'s own existing-file
  handling, wherever that's enforced today).

## Design

### Command shape

```
mockymock init PROG.cbl [--seed N] [--scenarios happy|branches|all]
                         [--copybook-path DIR]... [--force] [-o OUT.cut]
```

Defaults: `--seed` unset (generator's own default), `--scenarios happy`
(matches `generate --with-data`'s own default), output path
`<program-stem>.cut` next to the program (matches `generate`'s existing
default-output convention).

### Behavior

1. Run `doctor`'s environment probe first (see
   `2026-09-15-doctor-command-design.md`) -- cheap, read-only, no Docker
   mutation. Branch on the result:
   - **Docker not reachable at all**: fall back to plain
     `generate --with-data` (real generated mock data, `*> STUB EXPECT`
     comments left as-is, no `run` attempted) and print exactly why:
     `mockymock init: Docker isn't available, so I generated a suite with
     real test data but could not run it to record expected values. Run
     'mockymock run PROG.cbl --cut PROG.cut --record-expectations' once
     Docker is set up (see 'mockymock doctor').` This is still strictly
     better than plain `generate` today (real data beats empty bodies)
     and never silently pretends to have done the recording step.
   - **Docker reachable**: proceed to step 2.
2. Call the existing `generate --with-data` code path
   (`_cmd_generate` internals, factored so `init` can call the same
   function rather than shelling out to itself) to produce the initial
   `.cut` file at the resolved output path.
3. Call the existing `run --record-expectations` code path
   (`_cmd_run` internals, same factoring approach) against the file just
   written.
4. Print one combined summary: how many test cases were generated, how
   many stub expectations were recorded vs. skipped (reusing
   `record_rewrite.py`'s own summary counts --
   `docs/2026-08-04-record-expectations-design.md`'s "recorded/skipped
   counts" contract), and the next suggested command
   (`mockymock run PROG.cbl --cut PROG.cut` to re-run the now-fixed suite).
5. If `run --record-expectations` itself fails outright (compile error,
   refusal) rather than merely leaving some stubs unrecorded, `init`
   still leaves the `generate --with-data` output on disk (a suite with
   real data is still useful even if the record step failed) and surfaces
   the run failure's own error text unmodified, so the user gets the same
   diagnostic they'd get from running the two commands by hand.

### Relationship to scenario branch verification

`--scenarios branches|all` inherits the same honesty caveat already
documented in `docs/2026-09-04-scenario-branch-verification.md`: a
`branches`/`all` suite recorded through `init` proves the program ran,
not that each scenario reached its named arm, until that separate design
lands. `init`'s summary prints one line surfacing this for
`--scenarios` values other than `happy`:

```
Note: branch-targeted scenarios are not yet verified to reach their
named arm -- see docs/2026-09-04-scenario-branch-verification.md.
Confirm with 'mockymock run --trace' for anything security- or
correctness-critical.
```

This keeps `init` from overselling a suite it did not fully verify
itself, consistent with the "fail closed, never silently wrong" design
goal in the README.

## Implementation steps

1. Refactor `_cmd_generate`'s `--with-data` body and `_cmd_run`'s
   `--record-expectations` body each into a plain function returning a
   small result object (`GenerateResult`, `RecordResult`) rather than
   only printing and returning an exit code -- needed so `_cmd_init` can
   call both and combine their output instead of shelling out to a
   subprocess (shelling out would double the Docker/parse work and lose
   Python-level error detail). This refactor should not change either
   existing command's own behavior or tests.
2. `mockymock/cli/main.py`: add `_cmd_init`, wired to a new `init`
   subparser with the flags above; call the doctor probe (or the shared
   `runtime.status` probe it wraps, whichever lands first between the two
   designs -- see `2026-09-15-doctor-command-design.md`'s Implementation
   steps for the shared dependency) to branch on Docker availability.
3. Add `init` to the "Everyday" group in the grouped help epilog from
   `2026-09-15-cli-ergonomics-design.md`.
4. README: replace the current lead example
   (`mockymock generate ORDRPROC.cbl` alone) with `mockymock init
   ORDRPROC.cbl` as the very first command shown, keeping `generate`
   documented immediately after for users who want the bare scaffold
   (hand-authoring workflow, `CAPTURE ARG` cases the scaffold can't emit,
   per `examples/ordrproc/README.md`'s own note that `CAPTURE` is
   hand-authoring only).
5. `docs/options-reference.md`, `.okf/cli.md`: document `init`.
6. `.okf/log.md`: dated entry.

## Testing plan

- Unit: `_cmd_init`'s Docker-unavailable branch (mock the doctor probe
  down) -- asserts a `.cut` file was written via `--with-data` and no
  attempt was made to invoke the runtime, plus the exact fallback message.
- Integration (Docker-gated): `mockymock init` on
  `examples/ordrproc/ORDRPROC.cbl` in a tmp dir end-to-end -- assert the
  resulting `.cut` has real `EXPECT` lines (not `*> STUB EXPECT`
  comments) and that re-running `mockymock run` against it passes.
- Integration: `init --scenarios branches` prints the branch-verification
  caveat line; `init` (default `happy`) does not.
- Integration: `init` without `--force` on a program that already has a
  same-named `.cut` file refuses with the same message `generate` already
  gives in that situation (reuse, not reimplement, that check).

## Backward compatibility

Fully additive: a new subcommand, built entirely from refactored (not
behaviorally changed) internals of two existing commands. `generate` and
`run --record-expectations` keep their exact current CLI surface and
behavior; `init` is presented as the recommended entry point but changes
nothing about how the tool works when invoked the old way.
