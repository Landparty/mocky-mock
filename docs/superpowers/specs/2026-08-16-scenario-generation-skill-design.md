# Design: teach the mockymock skill to reason about scenario generation

Date: 2026-08-16
Status: approved (brainstormed in-session; companion spec: mocky-mock-vscode-extension
`docs/superpowers/specs/2026-08-16-remove-boundaries-tree-view-design.md`)

## Problem

`mockymock generate --with-data --scenarios {happy,branches,all}` and
`mockymock fixtures` already do the heavy lifting for seeded `.cut`
generation (`cobolparser.generators.ProgramFixtureGenerator` underneath).
The VS Code "COBOL Boundaries" tree view wraps these in a checkbox
tree + mode quick-pick, but that UI is unintuitive: it names three modes
with no explanation, treats boundary curation as a mechanical checkbox
exercise disconnected from *why* a boundary matters, and drops a `.cut`
file with no read-back on whether the result is actually good.

The already-shipped, packaged `mockymock` Claude Code skill
(`mockymock/cli/skills/mockymock/`, installed via `mockymock skills
install`) currently mentions `--with-data --scenarios all` as one scaffold
command in its Workflow step 1, but does none of the reasoning — it's the
same opacity as the tree view, just in a code block instead of a UI. This
spec enriches that skill so an AI-driven conversation replaces the tree
view entirely (see companion spec, which removes it).

## Decision

Rewrite `SKILL.md`'s Workflow step 1 into an explicit checklist, and add
a new `reference/scenario-generation.md` for the detail (progressive
disclosure, matching how `cut-dsl.md`/`cli-flags.md` are already split
out). No new CLI flags, no new packaging — `mockymock fixtures` already
emits everything needed (boundary list, direction, scenarios,
expectations, `unresolved` gaps) as JSON on stdout.

### New Workflow step 1 (in `SKILL.md`)

```
1. **Understand before generating** -- for a program you haven't scaffolded yet:
   a. Run `mockymock fixtures PROGRAM.cbl --scenarios all` and read the
      boundary list. Explain in plain language what's mockable (which
      CALLs/files/SQL/ACCEPT, which direction) before generating anything --
      see reference/scenario-generation.md for how to read the bundle.
   b. Recommend a `--scenarios` mode with a reason tied to the program
      (branch count, loop/EOF idioms) instead of defaulting silently to
      `happy`. Confirm with the developer.
   c. `mockymock generate PROGRAM.cbl --with-data --seed N --scenarios <mode>`
   d. Read back the result: name any unresolved boundaries by paragraph,
      not just a count. Offer to refine (--placeholder, different --seed
      or --scenarios) based on what's missing.
```

`SKILL.md` stays short; step (a)/(b)/(d)'s detail — how to read a
`FixtureBundle`'s `boundaries`/`scenarios`/`unresolved` fields, how to
map branch/loop counts to a mode recommendation, how to phrase a coverage
read-back — moves into the new reference file, linked from the "Full
reference" section.

### `reference/scenario-generation.md` (new)

Content, adapted from `cobolparser`'s `docs/fixture-bundle-schema.md` and
`.okf/generators.md` (Phase 2 `BoundaryInventoryAnalyzer`, Phase 5
`ScenarioPlanner`) for agent consumption:

- **Reading a boundary inventory**: what `category`/`key`/`direction`
  mean, how to describe a boundary in one sentence a developer would
  recognize from their source (e.g. "READ INV-FILE, incoming record
  layout with 6 fields").
- **Picking a mode**: `happy` when a paragraph chain has no branching
  worth separating; `branches` when `mockymock fixtures` (or
  `mockymock analyze program-flow`) shows multiple reachable arms;
  `all` when the developer wants edge cases (empty input, error status,
  boundary values) included, not just what's reachable by construction.
  This is a recommendation heuristic for the agent, not a new CLI
  behavior — the CLI's own mode semantics (cli-flags.md) are unchanged.
- **Reading generation output**: `unresolved` entries carry a reason
  (per `docs/fixture-bundle-schema.md`) — surface the reason and the
  paragraph, not a bare list of keys. `coverage`'s
  total/resolved/unresolved should be spoken as a sentence, not echoed
  as raw JSON.
- **Refinement loop**: mapping a developer's follow-up ("skip the file
  write boundary", "use a fixed seed", "just branches, not all") to the
  corresponding re-run flags.

### `SKILL.md` maintainer-note update

Extend the existing header comment (already flags DSL/CLI-flag drift) to
also cover this file:

```
A .cut directive or CLI flag change should be reflected in
reference/cut-dsl.md and reference/cli-flags.md here too. A
FixtureBundle schema change (docs/fixture-bundle-schema.md in
cobol-parser) should be reflected in reference/scenario-generation.md.
```

## Distribution

No changes needed — `mockymock skills install [--project] [--force]`
already copies the whole `skills/mockymock/` tree (`SKILL.md` +
`reference/*.md`); the new reference file is picked up automatically once
`pyproject.toml`'s existing glob (`reference/*.md`) is confirmed to match
it (it does — no `pyproject.toml` change needed).

## Docs to update

- `.okf/cli.md`: the existing "mockymock skills" subsection should note
  that the skill now includes scenario-generation reasoning, not just a
  file copy target — one sentence, plus a `log.md` entry.
- No README change needed (the AI-assistant-skill section already points
  at `mockymock skills install`; its content isn't duplicated there).

## Testing

- No new unit tests needed — this is pure Markdown content, not code.
  Verify manually: install the skill (`mockymock skills install --project
  --force` in a scratch checkout), start a Claude Code session, ask it to
  "generate tests for" a sample program (e.g. `examples/invupdt/`), and
  confirm the conversation follows the new checklist (inventory →
  recommend → confirm → generate → explain → offer refinement) rather
  than jumping straight to a `generate --with-data` call.
- Cross-check the reference file's claims about `FixtureBundle` fields
  against `cobol-parser`'s `docs/fixture-bundle-schema.md` at write time
  (no schema currently in flux, but this is a hand-duplicated fourth
  description of the same surface — same known tradeoff already accepted
  for `cut-dsl.md`/`cli-flags.md`).

## Out of scope

- No VS Code chat participant / `languageModelTools` integration — the
  terminal/Claude Code chat skill is the whole surface (see companion
  spec's rejected alternatives).
- No change to `mockymock fixtures`/`generate`'s actual behavior, flags,
  or output shape.
- No auto-detection of "should I recommend branches" beyond what's
  already computable from the fixtures JSON / `analyze program-flow` --
  no new static analysis is being built for this.
