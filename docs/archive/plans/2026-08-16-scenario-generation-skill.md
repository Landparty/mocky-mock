# Scenario-Generation Skill Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the packaged mockymock Claude Code skill so it reasons about `--scenarios` mode choice and boundary coverage in plain language instead of just naming the `--with-data --scenarios all` flag, replacing the VS Code boundaries tree view's UI (removed in the companion `mocky-mock-vscode-extension` plan) with a conversational flow.

**Architecture:** Pure documentation change — no code, no new CLI flags, no new packaging. `SKILL.md`'s Workflow step 1 gains an explicit inventory → recommend → generate → explain checklist; a new `reference/scenario-generation.md` carries the detail (which `FixtureBundle` JSON fields to read, how to phrase a mode recommendation, how to read back results), linked from `SKILL.md`'s "Full reference" section and picked up automatically by the existing `mockymock skills install` command (its packaging glob is `reference/*.md`, already wildcarded).

**Tech Stack:** Markdown only. No tests to write (`pytest` doesn't apply to prose) — verification is a manual end-to-end run described in Task 4.

**Spec:** `docs/superpowers/specs/2026-08-16-scenario-generation-skill-design.md`

## Global Constraints

- No changes to `mockymock fixtures`/`generate`'s actual CLI behavior, flags, or output shape.
- No `pyproject.toml` change — the existing `"reference/*.md"` glob already covers the new file.
- `FixtureBundle` field names/shapes used in the new reference file must match `cobol-parser`'s `docs/fixture-bundle-schema.md` (`bundle_version: 1`) exactly — this is a hand-duplicated description of that schema, same accepted tradeoff as `cut-dsl.md`/`cli-flags.md`.
- Keep `SKILL.md` short (progressive disclosure) — new depth goes in the reference file, not inlined.

---

### Task 1: Rewrite `SKILL.md`'s maintainer note, Workflow step 1, and reference list

**Files:**
- Modify: `mockymock/cli/skills/mockymock/SKILL.md`

**Interfaces:**
- Consumes: nothing (pure content edit).
- Produces: the `reference/scenario-generation.md` link that Task 2 must satisfy (the file must exist at that relative path once Task 2 is done).

- [ ] **Step 1: Update the maintainer-note comment**

Replace:
```markdown
<!--
Maintainer note: this is a curated duplicate of docs/options-reference.md
in the mocky-mock repo, adapted for agent consumption. A .cut directive or
CLI flag change there should be reflected in reference/cut-dsl.md and
reference/cli-flags.md here too.
-->
```
with:
```markdown
<!--
Maintainer note: this is a curated duplicate of docs/options-reference.md
in the mocky-mock repo, adapted for agent consumption. A .cut directive or
CLI flag change should be reflected in reference/cut-dsl.md and
reference/cli-flags.md here too. A FixtureBundle schema change
(docs/fixture-bundle-schema.md in cobol-parser) should be reflected in
reference/scenario-generation.md.
-->
```

- [ ] **Step 2: Replace Workflow step 1**

Replace:
```markdown
1. **Scaffold a starting point** instead of writing a `.cut` file by hand:
   ```bash
   mockymock generate PROGRAM.cbl                                       # placeholder mocks, one TESTCASE per paragraph
   mockymock generate PROGRAM.cbl --with-data --seed 7 --scenarios all  # real generated data + EXPECT/VERIFY per scenario
   ```
   `generate` also prints every boundary it could **not** mock (an
   unidentifiable dynamic `CALL`, an unspliceable nested site) -- a test
   case that reaches one of those will be refused by `run` until you
   resolve it.
```
with:
```markdown
1. **Understand before generating** -- for a program you haven't
   scaffolded a data-driven `.cut` for yet, don't jump straight to
   `--with-data`:
   a. Run `mockymock fixtures PROGRAM.cbl --scenarios all` and read the
      first scenario's `fixtures` plus any OUT-only boundaries in its
      `expectations` (every scenario carries a fixture for every boundary
      the program touches, so one scenario is a complete inventory).
      Explain in plain language what's mockable -- which CALLs/files/
      SQL/ACCEPT, and each one's direction -- before generating anything.
      See `reference/scenario-generation.md` for exactly which bundle
      fields to read and how to phrase this.
   b. Recommend a `--scenarios` mode with a reason tied to the program's
      own `scenario_coverage.total_arms` from that same bundle (0 arms:
      `happy`; 1+: `branches`, or `all` if the developer also wants fixed
      edge-case families), instead of defaulting silently to `happy`.
      Confirm with the developer.
      ```bash
      mockymock generate PROGRAM.cbl                                       # placeholder mocks, one TESTCASE per paragraph
      mockymock generate PROGRAM.cbl --with-data --seed 7 --scenarios all  # real generated data + EXPECT/VERIFY per scenario
      ```
   c. Generate with the confirmed mode. `generate` also prints every
      boundary it could **not** mock (an unidentifiable dynamic `CALL`,
      an unspliceable nested site) -- a test case that reaches one of
      those will be refused by `run` until you resolve it.
   d. Read back the result: name any unresolved boundaries by paragraph
      (from `unresolved` and each fixture's own `unresolved`), not just a
      count. Offer to refine (`--placeholder CATEGORY:KEY`, a different
      `--seed`, a narrower `--scenarios`) based on what's missing.
```

- [ ] **Step 3: Add the new reference file to "Full reference"**

Replace:
```markdown
## Full reference

- `reference/cut-dsl.md` -- every `.cut` directive: `MOCK`/`END-MOCK`
  categories, `ROWS` cursor sugar, `EXPECT`, `VERIFY`, `FILE-STATUS IS`,
  `BEFORE-ALL`/`BEFORE-EACH`, `PROVIDER`/`HEADER`/`ROW`, `*> STUB EXPECT`.
- `reference/cli-flags.md` -- every subcommand and flag: `setup`,
  `generate`, `fixtures`, `run`, `debug`, `lint`, `mutate`, `collect`,
  `dashboard`, `export`, `analyze`, `skills`.
```
with:
```markdown
## Full reference

- `reference/cut-dsl.md` -- every `.cut` directive: `MOCK`/`END-MOCK`
  categories, `ROWS` cursor sugar, `EXPECT`, `VERIFY`, `FILE-STATUS IS`,
  `BEFORE-ALL`/`BEFORE-EACH`, `PROVIDER`/`HEADER`/`ROW`, `*> STUB EXPECT`.
- `reference/cli-flags.md` -- every subcommand and flag: `setup`,
  `generate`, `fixtures`, `run`, `debug`, `lint`, `mutate`, `collect`,
  `dashboard`, `export`, `analyze`, `skills`.
- `reference/scenario-generation.md` -- how to read a `mockymock
  fixtures` bundle (boundary inventory, branch-arm coverage, unresolved
  gaps), how to recommend a `--scenarios` mode, and how to phrase a
  generation read-back.
```

- [ ] **Step 4: Commit**

```bash
git add mockymock/cli/skills/mockymock/SKILL.md
git commit -m "docs: teach the mockymock skill to reason about scenario generation"
```

---

### Task 2: Write `reference/scenario-generation.md`

**Files:**
- Create: `mockymock/cli/skills/mockymock/reference/scenario-generation.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the file `SKILL.md` (Task 1) links to.

- [ ] **Step 1: Write the file**

```markdown
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

`--scenarios all` up front is deliberate: it is the only mode that also
populates `scenario_coverage` (used in step 2), and **every scenario in
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
- `total_arms >= 1` -- recommend `branches` (one scenario per reachable
  arm), naming the arm count and, if you want to be specific, the
  `parent_proc` of a few `details[]` entries (e.g. "3 reachable arms, 2
  of them in `VALIDATE-ORDER`"). Mention `all` as the option if the
  developer also wants fixed edge-case families (empty input, error
  status, boundary values) beyond what's reachable by construction.
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
```

- [ ] **Step 2: Verify the file exists and renders as valid markdown**

Run: `test -f mockymock/cli/skills/mockymock/reference/scenario-generation.md && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add mockymock/cli/skills/mockymock/reference/scenario-generation.md
git commit -m "docs: add scenario-generation reference for the mockymock skill"
```

---

### Task 3: Update the OKF bundle

**Files:**
- Modify: `.okf/cli.md:604-624` (the `mockymock skills install` section)
- Modify: `.okf/log.md` (prepend a dated entry)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add one sentence to `.okf/cli.md`'s "mockymock skills install" section**

After the existing paragraph ending "...the same way `mockymock/runtime/docker/` and `mockymock/web/static/` ride along with theirs." (currently `.okf/cli.md:604-624`), add:

```markdown

As of 2026-08-16, the packaged skill's `SKILL.md` Workflow and its new
`reference/scenario-generation.md` also teach the agent to inventory
boundaries and recommend a `--scenarios` mode from a program's own
`scenario_coverage` before generating -- not just a copytree of static
reference material.
```

- [ ] **Step 2: Prepend a `.okf/log.md` entry**

Add after the `# mocky-mock OKF Bundle — Update Log` header, before the existing `## 2026-08-14` entry:

```markdown
## 2026-08-16 — Teach the mockymock skill to reason about scenario generation

The VS Code extension's "COBOL Boundaries" tree view (checkboxes +
happy/branches/all quick-pick) was reported unintuitive: the mode picker
named three words with no explanation, and the generated `.cut` landed
with no read-back on whether it was actually right. Rather than redesign
that UI, moved the reasoning into the already-shipped, already-packaged
`mockymock` Claude Code skill (`mockymock skills install`) instead --
`SKILL.md`'s Workflow step 1 now walks inventory boundaries -> recommend
a mode with reasoning tied to `scenario_coverage.total_arms` -> generate
-> read back unresolved boundaries by paragraph, backed by a new
`reference/scenario-generation.md`. No CLI/packaging change; the
`generate`/`fixtures` subcommands' behavior is unchanged. Companion
change: the VS Code tree view itself is removed in
`mocky-mock-vscode-extension` (see that repo's `.okf/log.md`), since it's
now a redundant, worse UI for the same underlying calls.

See `docs/superpowers/specs/2026-08-16-scenario-generation-skill-design.md`.
```

- [ ] **Step 3: Commit**

```bash
git add .okf/cli.md .okf/log.md
git commit -m "docs: update OKF for scenario-generation skill enrichment"
```

---

### Task 4: Manual end-to-end verification

**Files:** none modified.

**Interfaces:**
- Consumes: Tasks 1-3's committed content.
- Produces: a pass/fail verification record (this task's own deliverable is the confirmation, not a file).

- [ ] **Step 1: Install the skill from a scratch checkout**

```bash
mockymock skills install --project --force
```

Expected: prints the destination path (`./.claude/skills/mockymock`) with
no error.

- [ ] **Step 2: Start a fresh Claude Code session in that checkout and ask it to generate tests for a sample program**

Use `examples/invupdt/` (already in the mocky-mock repo). Prompt: "Use
the mockymock skill to generate tests for INVUPDT.cbl."

- [ ] **Step 3: Confirm the conversation follows the new checklist**

Expected, in order: the assistant runs `mockymock fixtures ... --scenarios
all` before generating anything; describes at least one boundary in plain
language (not just echoing raw JSON); states a `--scenarios` mode
recommendation with a reason (arm count) and asks for confirmation rather
than silently picking `happy`; runs `mockymock generate --with-data`;
reports any unresolved boundaries by paragraph name if present. If any
step is skipped or the assistant jumps straight to `generate --with-data
--scenarios all` without the inventory/recommendation step, the skill
content needs another pass -- re-open Task 1/2.

- [ ] **Step 4: No commit** -- this task only verifies; nothing to add to git unless verification failed and content needed a fix (in which case, fix inline in Task 1/2's files and re-run this task).
