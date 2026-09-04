# Verifying that a generated scenario reaches the branch it is named for

**Status:** gap documented, not implemented.
**Related:** cobol-parser's
`docs/plans/2026-09-04-cross-record-correlation-design.md` (the planner-side
half of the same problem).

## The gap

`mockymock generate --with-data --scenarios branches|all` emits one TESTCASE
per `PlannedScenario`, named for the branch arm the scenario targets --
`"210000-TRAITER: WHEN WS060-FICH-EXT-TYPE-P-BAL-F"`. Nothing in the generated
`.cut` asserts that running it actually reaches that arm.

Every `VERIFY` line the scaffold emits is boundary-keyed:

    VERIFY OPEN FICH-EXT-PRISE WAS CALLED 1 TIMES
    VERIFY READ FICH-EXT-PRISE WAS CALLED 4 TIMES

Those count *total invocations of a boundary*. They are identical whether the
program took the `'05'` arm, the `'09'` arm, or the OTHER arm, because each arm
reads the same file the same number of times. A scenario seeded with data that
cannot reach its own arm therefore passes.

That is not hypothetical. Three separate defects fixed on 2026-09-04 all
produced exactly this: a green test case exercising the wrong branch.

* Two were data-seeding bugs in cobol-parser's constraint extraction (a
  level-88 arm constrained by the union of its parent field's 88 values; a
  `WHEN OTHER` arm left unconstrained and therefore seeded from the very
  values it excludes). Both are fixed.
* The third is structural and is *not* fixed: `ScenarioPlanner` gates arms on
  CFG reachability, never on whether the scenario's own data drives execution
  into the arm. An arm reachable only through a correlation between two
  records still gets a scenario named for it.

All three had to be found by reading `mockymock run --trace` output and
checking which paragraphs were actually hit.

## The lever we already have

The `.cut` DSL is not limited to boundary-keyed verification. `PARAGRAPH` and
`SECTION` are full `MockCategory` members (`FLOW_CATEGORIES` in
`dsl/model.py`), and `VERIFY` accepts them like any other category:

    VERIFY PARAGRAPH 220000-TRAITER-P-BAL-F WAS PERFORMED 1 TIMES

That line turns "this scenario silently tests the wrong branch" into a hard
test failure. The scaffold simply never emits one.

## Proposed change

For a bundle-driven scenario that targets a branch arm, emit a
`VERIFY PARAGRAPH <target> WAS PERFORMED AT LEAST ONCE` alongside the
existing boundary VERIFYs.

Open questions, in the order they need answering:

1. **Where does the target paragraph name come from?** The bundle would have
   to carry it. cobol-parser's `ArmOutcome.parent_proc` already holds the
   paragraph *containing the branch*, which is the enclosing paragraph, not
   the arm's body target -- for `EVALUATE ... WHEN X PERFORM 220000-FOO` the
   useful name is `220000-FOO`, not the paragraph holding the EVALUATE.
   Deriving the arm's own target is planner-side work and means a new
   (additive) field on `Scenario`, which is a `bundle_version` question.
2. **Does the mocked run reach it at all?** A scenario `PERFORM`s the entry
   paragraph; if the arm's target sits behind a `PARAGRAPH` mock the same
   TESTCASE installs, the tally is a mock tally, not a real execution. The
   splicer's flow-mock dispatch already distinguishes these -- worth
   confirming before trusting the count.
3. **`AT LEAST ONCE` vs an exact count.** Exact counts are appealing but a
   loop-driven arm fires once per matching row, and the row count is the
   scenario's own `sequence` length -- knowable, but only if the expectation
   is derived from the same place tier-1 `call_count` expectations are
   (`program_fixtures`), not re-derived here. `AT LEAST ONCE` is the honest
   minimum and needs no new derivation. (It is also the only spelling the
   grammar has for this: `_validate_expectation` accepts `ONCE`, `NEVER`,
   `AT LEAST ONCE`, or `<n> TIMES` -- there is no `AT LEAST <n> TIMES`.)

Worth doing item 3 first as `AT LEAST ONCE`: it catches every failure of this
class, and it does not depend on resolving 1 and 2 perfectly.

## Interim guidance

Until this lands, treat a passing `--scenarios branches|all` run as evidence
that the program *ran*, not that each scenario exercised its named branch.
Confirm branch coverage with `mockymock run ... --trace` and read the actual
paragraph names, particularly for any arm whose reachability depends on more
than the current record's own fields.
