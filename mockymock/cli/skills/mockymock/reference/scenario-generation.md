# Reading a scenario-generation bundle

`mockymock fixtures PROGRAM.cbl --scenarios <mode>` prints a
`FixtureBundle` (`bundle_version: 1`, same shape `generate --with-data`
uses internally) as JSON on stdout. This is how to read it to have an
informed conversation with a developer *before* writing a `.cut` file --
see `cobol-parser`'s `docs/fixture-bundle-schema.md` for the authoritative
field-by-field schema; this file is a task-oriented walkthrough of the
same shape.

## 1. Inventory boundaries (before picking a mode)

```bash
mockymock fixtures PROGRAM.cbl --scenarios all > /tmp/bundle.json
```

`--scenarios all` up front is deliberate: it's the broadest single call --
it populates `scenario_coverage` (also true of `branches`, just not
`happy`; used in step 2) AND, being a superset, still gives the full
boundary inventory below, so one call covers both jobs. **every scenario in
every mode carries a fixture for every boundary the program touches** --
so `bundle["scenarios"][0]["fixtures"]` alone is already a complete
inventory, regardless of which scenario you pick.

For each entry in `fixtures`, read:

- `category` + `key` -- e.g. `"READ"` + `"ORDER-FILE"`.
- `paragraph` + `line` -- where in PROCEDURE DIVISION it's invoked.
- `direction` -- `"IN"` (mockymock supplies data), `"OUT"` (the program
  produces it -- see below, these never appear in `fixtures`),
  `"BIDIRECTIONAL"`, or `"STATUS_ONLY"` (nothing to generate, just a
  status code, e.g. OPEN/CLOSE/DELETE/START/UNLOCK).
- `layout` -- the record's fields (name/picture/usage), when non-empty.

Translate each into one plain-language sentence, e.g. "reads
`ORDER-FILE` records in `MAIN-PARA` -- mockymock will need to supply
`ORDER-QTY` rows" or "opens/closes `ORDER-FILE` -- status-only, nothing
to seed."

**OUT-direction boundaries never appear in `fixtures`** (nothing to mock;
the program produces the value) -- find them instead in that same
scenario's `expectations` list, filtering for `kind == "stub"` and a
`ref` shaped like `"CATEGORY:KEY"` (as opposed to a bare field name,
which is a `field_equals`/other-kind stub about a single field, not a
boundary). Describe these as "writes/produces `<key>` -- nothing to
seed, but `run` can assert on it later."

Also check the bundle's top-level `unresolved` list (program-level gaps
not tied to one boundary, e.g. an unresolved `COPY` member or an
untraceable dynamic `CALL` target) and `coverage` (`total_boundaries`/
`resolved_boundaries`/`unresolved_boundaries`) for a one-line summary.

## 2. Recommend a `--scenarios` mode

Read `scenario_coverage` from the same `all`-mode bundle (this key is
only populated for `"branches"`/`"all"`, so this recommendation piggybacks
on the inventory call rather than needing a second one):

- `total_arms == 0` -- no branching worth separating; recommend `happy`.
- `total_arms >= 1` and at least one arm is `"targeted"` or `"merged"` --
  recommend `branches` (one scenario per reachable arm), naming the arm
  count and, if you want to be specific, the `parent_proc` of a few
  `details[]` entries (e.g. "3 reachable arms, 2 of them in
  `VALIDATE-ORDER`"). Mention `all` as the option if the developer also
  wants fixed edge-case families (empty input, error status, boundary
  values) beyond what's reachable by construction.
- `total_arms >= 1` but every `details[]` entry is `"missed"` -- `branches`
  alone has nothing to target and `generate --scenarios branches` will
  fail outright ("the fixture bundle has zero scenarios"). Recommend
  `happy`, or `all` if the developer wants the fixed-family scenarios
  (empty input/error status/boundary values) despite no real branch
  coverage being reachable -- name the `reason` from a couple of
  `details[]` entries so the developer understands why branch coverage
  isn't available here.
- If any `details[]` entry has `status == "missed"`, mention it and its
  `reason` -- that arm won't get its own scenario in either mode.

Confirm the mode with the developer before generating -- don't pick
silently.

## 3. Generate

```bash
mockymock generate PROGRAM.cbl --with-data --seed 7 --scenarios <confirmed-mode>
```

`--scenarios all` was only used for the read-only `fixtures` inventory
call above; generate with whatever mode was actually confirmed (which
may be `happy` or `branches`, not `all`).

## 4. Read back the result

After `generate` writes the `.cut` file:

- If it printed any un-mockable boundaries (dynamic `CALL` with no
  traceable target, unspliceable nested site), name them and their
  paragraph -- these will make `run` refuse any test case that reaches
  them until resolved.
- If you want to double check coverage without re-parsing `generate`'s
  own stdout, re-run `mockymock fixtures` with the same mode/seed and
  read `coverage`/`unresolved` the same way as step 1.
- Offer to refine based on what the developer says is missing:
  - Downgrade a boundary to a placeholder body:
    `--placeholder CATEGORY:KEY` (repeatable).
  - Reproduce or vary the generated data: `--seed N`.
  - Narrower or wider coverage: re-run with a different `--scenarios`.

## Determinism note

The same `(program, seed, mode)` always produces byte-identical output --
if a developer asks "why did the numbers change", the answer is either a
different (or unset/random) `--seed`, or the program/copybooks changed
between runs.
