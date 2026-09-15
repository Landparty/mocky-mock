# `.cut` completion, hover, and quick fixes (2026-09-15)

**Repos:** mockymock CLI (this repo, new server-side surface) and
`mocky-mock-vscode` (consumer -- its own `src/`/`docs/design` are
gitignored in that repo, per its `.gitignore:6`, so its side of this
design is tracked here instead, following the same cross-repo pattern
already used by `2026-07-21-debug-trace-design.md` and
`2026-07-22-dap-debugger-design.md`).

## Problem

The `.cut` DSL has real editor-relevant structure -- boundary categories
and keys scoped to one specific program, generated names like tally
fields (`UT-READ-INV-FILE-TALLY`) and capture targets
(`UT-CAP-MQPUT-1`), `FILE-STATUS IS` mnemonics, and `*> STUB EXPECT`
comments that are a protocol, not a comment -- documented across
`.okf/dsl.md` (899 lines) and `docs/options-reference.md` (697 lines).
None of it is machine-assisted today. `mocky-mock-vscode`'s only
`.cut`-specific behavior is TextMate grammar highlighting, snippets,
folding (`language/`, `snippets/`, `syntaxes/cut.tmLanguage.json` in that
repo), and lint-on-save (`src/linting/lintDiagnostics.ts`) -- confirmed
no `registerCompletionItemProvider`/`registerHoverProvider`/
`registerCodeActionsProvider` call exists anywhere in that repo's `src/`
for the `cut` language ID. A user has to hold the DSL, and every specific
program's own boundary names, in their head, or keep the reference docs
open in a second window.

Everything a completion/hover provider would need is already computed
server-side by `mockymock collect --cut --json` (suite/case structure)
and, for program-specific boundary names, `mockymock lint`/`generate`'s
own analysis of the paired `.cbl` -- none of it currently exposed as a
stable, purpose-built JSON contract for editor tooling to consume.

## Goals

- Typing `MOCK <TAB>` after a category keyword suggests only the keys
  that program actually has for that category (file names it OPENs,
  paragraph/section names, etc.), not a blind free-text field.
- Hovering a tally name, a capture target, a `FILE-STATUS IS` mnemonic,
  or a refusal code shows what it means and where its value comes from,
  without leaving the editor.
- A lint finding with a `suggested_fix` (from
  `2026-09-15-actionable-refusals-and-fill-design.md`) is offered as a
  one-click Quick Fix in the extension, not just readable diagnostic
  text.
- None of this requires Docker or a running toolchain -- everything here
  is static analysis, matching `lint`'s own "fast, editor/CI friendly, no
  Docker" framing.

## Non-goals

- No full language-server protocol implementation, no semantic
  tokenization beyond what the existing TextMate grammar already
  provides, no refactor/rename support for `.cut` files -- COBOL Analyzer
  owns that kind of tooling for `.cbl` itself, and `mocky-mock-vscode`
  deliberately stays narrow per its own README's division-of-labor
  framing.
- No caching/incremental-reparse infrastructure beyond what a
  request-per-keystroke-with-debounce already gets from reusing the
  existing lint request queue in `lintDiagnostics.ts` (one in-flight
  request per file, already implemented there).

## Design

### 1. New mockymock CLI surface: `collect --boundaries`

`mockymock collect` today only reports suite/case structure. Add
`--boundaries` (combinable with `--json`, required with it since
boundary listing has no human-readable console mode planned):

```
mockymock collect PROG.cbl --cut PROG.cut --json --boundaries
```

emits everything `collect --json` already does, plus a `boundaries`
array: one entry per `(category, key)` mock_surface's own analysis found
reachable in the program, each with `category`, `key`, `paragraph`,
`line`, and -- for `CALL`/`DYNCALL` -- the argument-direction ladder
already exposed by cobol-parser's `BoundaryInventoryAnalyzer.call_args`
(`.okf/analysis.md`, re-surfaced through `mock_surface` per
`.okf/analysis.md`'s own cross-reference). This is a read of data
`mockymock generate`/`lint` already compute internally
(`mockymock/analysis/mock_surface.py`'s `analyze()`); `--boundaries`
exposes it as a stable contract rather than requiring a scaffold to be
generated and diffed.

### 2. `mockymock explain <CODE>`: one source of truth for refusal text

New subcommand:

```
$ mockymock explain UNSUPPORTED_DECLARATIVES
UNSUPPORTED_DECLARATIVES
  A DECLARATIVES block exists in the program. USE procedures run on I/O
  conditions outside any PERFORM/GO TO edge, so the reachability gate
  cannot verify the boundary statements inside them -- refused
  unconditionally, the same posture as SORT/MERGE.
  See .okf/analysis.md's refusal table.
```

`--json` mode for editor consumption. Backed by a single
`REFUSAL_EXPLANATIONS: dict[str, str]` in
`mockymock/analysis/refusal/_types.py`, populated from the same
explanatory text `.okf/analysis.md`'s refusal table already carries in
prose -- this makes that table's text executable/queryable instead of
documentation-only. `mockymock lint`'s own console output can append
"run 'mockymock explain <CODE>' for details" once this lands.

### 3. mocky-mock-vscode: completion provider

`src/completion/cutCompletionProvider.ts` in that repo, registered for
language `cut`:

- **After `MOCK `**: suggest every `MockCategory` value (`CALL`, `READ`,
  `OPEN`, ..., `PARAGRAPH`, `SECTION`) -- this list is static
  (`.okf/dsl.md`'s grammar section), no CLI round-trip needed.
- **After `MOCK <CATEGORY> `**: call `collect --boundaries` (cached per
  document version -- re-run only when the paired `.cbl` or `.cut`
  changes, keyed the same way `lintDiagnostics.ts` already keys its
  in-flight/queued sets) and suggest the `key`s reachable for that
  category, each with detail text showing the paragraph and line where
  it's reachable from.
- **Inside a `MOCK` body, at start of line**: suggest `MOVE`, `IF`,
  `CAPTURE ARG`, `END-MOCK` per the grammar; for `CAPTURE ARG n INTO`,
  suggest the next unused tally-safe capture name
  (`UT-CAP-<KEY>-<n>`) matching the naming convention
  `mockymock/splicer/naming.py` documents server-side, so the user never
  has to construct that name by hand.
- **After `VERIFY `**: suggest every `(category, key)` this test case's
  own `MOCK` blocks declare, plus `PARAGRAPH`/`SECTION` targets (for the
  branch-verification pattern `2026-09-04-scenario-branch-verification.md`
  recommends), each pre-filled with the matching tally field name as a
  snippet placeholder.
- **After `FILE-STATUS IS `**: suggest the fixed mnemonic set the DSL
  defines (`.okf/dsl.md`'s FILE-STATUS section) -- static list, no CLI
  call.

### 4. mocky-mock-vscode: hover provider

`src/hover/cutHoverProvider.ts` in that repo, registered for language
`cut`:

- Hovering a `UT-*-TALLY` identifier: "Tally for `<CATEGORY> <KEY>` --
  incremented each time the program reaches this boundary while this
  mock is active. Use in a MOVE/IF condition or a VERIFY count."
- Hovering a `UT-CAP-*` identifier: "Captures argument `<n>` of `<CALL
  KEY>` the last time it was called. Use in an EXPECT after PERFORM."
- Hovering a refusal code referenced in a `*>` comment (some authored
  `.cut` files reference a refusal code in a comment explaining a
  workaround, per convention in the example suite): shell out to
  `mockymock explain <CODE> --json` for the tooltip text, so the
  explanation lives in one place rather than being duplicated into the
  extension.
- Hovering `*> STUB EXPECT <name>`: "Placeholder for `mockymock run
  --record-expectations` to fill in. See docs/2026-08-04-record-
  expectations-design.md."

### 5. mocky-mock-vscode: Quick Fix for `suggested_fix`

Depends on `2026-09-15-actionable-refusals-and-fill-design.md` landing
its `suggested_fix` field on `lint --format json` output.

`src/linting/lintCodeActionProvider.ts` in that repo, registered via
`registerCodeActionsProvider('cut', provider, { providedCodeActionKinds:
[vscode.CodeActionKind.QuickFix] })`:

- `lintOutput.ts`'s existing parser (`parseLintOutput`) gains
  `suggested_fix` in its returned finding shape.
- `lintDiagnostics.ts` stores each diagnostic's `suggested_fix` in a
  `Map<string, string>` keyed by a stable per-diagnostic id (range +
  message, the same de-duplication key the diagnostic collection
  implicitly uses), since VS Code `Diagnostic` objects don't carry
  arbitrary payload data reliably across re-lints.
- The Quick Fix inserts the snippet text at the end of the relevant
  `TESTCASE` (mirroring where `generate --fill` would place it, so
  manual Quick Fix and CLI `--fill` produce the same result) and, if more
  than one finding in the same file has a fix, offers a "Fill all
  detected mocks in this file" action that shells out to `mockymock
  generate --fill` on the open file and reloads it -- reusing the CLI
  behavior rather than reimplementing insertion logic twice.

## Implementation steps

**This repo (mocky-mock), land first:**
1. `collect --boundaries` (Design section 1).
2. `suggested_fix` on `lint --format json` (already planned in
   `2026-09-15-actionable-refusals-and-fill-design.md`).
3. `mockymock explain <CODE>` subcommand + `REFUSAL_EXPLANATIONS` table
   (Design section 2).

**mocky-mock-vscode, after the above ships:**
1. `src/completion/cutBoundaryCache.ts`: wraps `collect --boundaries`,
   cached per `(cutPath, cblMtime, cutMtime)`, invalidated on save --
   mirrors the existing debounce/in-flight pattern in
   `lintDiagnostics.ts` rather than introducing a new caching strategy.
2. `src/completion/cutCompletionProvider.ts` + registration in
   `extension.ts`'s `activate()`.
3. `src/hover/cutHoverProvider.ts`, backed by a small static map for
   tally/capture pattern recognition (regex against the naming
   convention) plus `mockymock explain --json` for refusal-code hovers.
4. `src/linting/lintOutput.ts`: extend the parsed finding shape with
   `suggested_fix`.
5. `src/linting/lintCodeActionProvider.ts` + registration.
6. `package.json`: no new `contributes.languages`/`grammars` needed
   (reuses the existing `cut` language id); does need
   `activationEvents`/`main` wiring for the new providers, which VS Code
   handles automatically via the `languages.*` registration calls in
   `activate()`.
7. `mocky-mock-vscode`'s README: document the new hover/completion/
   quick-fix behavior under a new subsection, and cross-link this repo's
   `.okf/dsl.md` for the full grammar reference these providers
   summarize inline.

## Testing plan

- This repo: unit tests for `collect --boundaries`'s JSON shape,
  `mockymock explain`'s exit code for an unknown code (non-zero, lists
  valid codes) and known code (zero, prints the table entry).
- `mocky-mock-vscode`: existing test patterns in that repo are mostly
  pure-function unit tests against fixture strings
  (`cutDiscovery.test.ts`'s style) -- follow that for `lintOutput.ts`'s
  extended parsing and any pure snippet-construction helpers.
  Provider-level behavior (does VS Code actually show the completion
  list) is harder to unit test in that repo's existing harness; scope
  those to manual verification against `examples/` plus a thin
  integration test using `vscode-test` if that repo's CI already runs
  one (check its `package.json`'s `test` script and `.github/workflows/`
  before assuming one needs to be added from scratch).
- Manual verification script: open `examples/invupdt/INVUPDT.cut`
  (mocky-mock-vscode's copy), type `MOCK ` and confirm the category list,
  type `MOCK READ ` and confirm only `INV-FILE` (the program's real file
  name) is suggested, hover a `UT-READ-INV-FILE-TALLY` reference and
  confirm the tooltip, trigger a known `UNMOCKED_*` finding and confirm
  the Quick Fix inserts the exact same text `mockymock generate --fill`
  would.

## Backward compatibility

All new mocky-mock-vscode providers are additive registrations; no
existing command, setting, or grammar changes in that repo.
`collect`/`lint`/`explain` CLI additions here are new flags/subcommands
with no change to existing output when the new flags aren't passed.
