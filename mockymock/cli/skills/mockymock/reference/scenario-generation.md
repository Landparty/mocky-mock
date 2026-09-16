# Reading a scenario-generation bundle

`mockymock fixtures PROGRAM.cbl --scenarios <mode>` prints a
`FixtureBundle` (`bundle_version: 1`, same shape `generate --with-data`
uses internally) as JSON on stdout. This is how to read it to have an
informed conversation with a developer *before* writing a `.cut` file --
see `cobol-parser`'s `docs/fixture-bundle-schema.md` for the authoritative
field-by-field schema; this file is a task-oriented walkthrough of the
same shape.

Where this sits in the workflow (`paragraph-first-workflow.md`): the
read-only inventory in section 1 belongs at the very start, before any
scaffolding. The *generation* in section 3 produces whole-program cases
(each scenario `PERFORM`s the program's entry paragraph), so it belongs
in the whole-program pass, after each paragraph already has a green case
of its own. Summarize what you read here in plain language -- never
paste the bundle itself at the developer.

## 1. Inventory boundaries (before picking a mode)

```bash
mockymock fixtures PROGRAM.cbl --scenarios all > /tmp/bundle.json
```

`--scenarios all` up front is deliberate: it's the broadest single call --
it populates `scenario_coverage` (also true of `branches`, just not
`happy`; used in step 2) AND, being a superset, still gives the full
boundary inventory below, so one call covers both jobs. **every scenario
in every mode carries a fixture for every boundary that HAS one**
(IN/BIDIRECTIONAL/STATUS_ONLY -- OUT-direction boundaries never get a
fixture, see below) -- so `bundle["scenarios"][0]["fixtures"]` alone is
already a complete inventory of everything that can be seeded, regardless
of which scenario you pick.

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
scenario's `expectations` list, filtering for `kind == "stub"`. Two
shapes are worth naming separately:

- a `ref` shaped like `"CATEGORY:KEY"` -- a whole OUT-direction boundary
  (WRITE, SQL INSERT/UPDATE/DELETE, etc.). Describe these as
  "writes/produces `<key>` -- nothing to seed, but `run` can assert on it
  later."
- a bare-name `ref` (just a field name) -- typically a CALL argument's
  OUT aspect on an otherwise `BIDIRECTIONAL` boundary; check the `note`
  field for context (e.g. `"bidirectional: the OUT aspect ... is not
  asserted in v1"`). Describe these as "the OUT side of `<ref>` isn't
  asserted yet, but it is mocked in."

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
  `happy`, despite no real branch coverage being reachable -- or `all` if
  the developer wants whichever of the fixed families (empty input, error
  status, boundary values) the program's own structure happens to
  support (not all three are guaranteed to materialize; e.g. a program
  with no `INVALID KEY`/`ON EXCEPTION`/status-checked handler won't get a
  boundary-values family). Either way, name the `reason` from a couple of
  `details[]` entries so the developer understands why branch coverage
  isn't available here.
- In the mixed case (some arms `"targeted"`/`"merged"`, some `"missed"`),
  also mention any missed arm and its `reason` -- that arm won't get its
  own scenario in either mode.

Confirm the mode with the developer before generating -- don't pick
silently. The exception is `hands-off` (`mockymock skills mode`): there,
pick it yourself from `scenario_coverage.total_arms` by the same
reasoning, and put the choice *and* the arm count in the final report
("`branches`: 11 arms, 4 unresolved -- `all` would have produced 60+
cases"). "Don't pick silently" survives every mode; "ask first" doesn't.

## 3. Generate

```bash
mockymock generate PROGRAM.cbl --with-data --seed 7 --scenarios <confirmed-mode>
```

`--scenarios all` was only used for the read-only `fixtures` inventory
call above; generate with whatever mode was actually confirmed -- or, in
`hands-off`, chosen and recorded (which may be `happy` or `branches`,
not `all`).

**If a `.cut` file already exists, write to a separate path** (`-o
scenarios.cut`) and copy across the cases you want. `generate`
overwrites its output without asking, and the paragraph cases in a file
you've been editing are exactly what would be lost.

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
