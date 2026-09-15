# Refusals that hand you the fix, and `generate --fill` (2026-09-15)

## Problem

`UNMOCKED_*` refusals are precise but leave the mechanical part of the
fix to the user. Today's message
(`mockymock/analysis/refusal/_gates.py:1400-1412`):

```
READ boundary at line 42 (paragraph 'PROCESS-LOOP', keys INV-FILE) is
reachable from 'MAIN-PROCESS' but no MOCK directive in this test case
matches it
```

names the site exactly (category, line, paragraph, keys) but not the
`.cut` text that would resolve it. That text is fully determined by the
same information the message already carries -- `mockymock/dsl/generator.py`'s
`_directive_for`/`_placeholder_body_for` already render exactly this
shape for `generate`'s scaffold. The refusal path and the scaffold path
independently know how to describe a mock block; only the refusal path
throws that knowledge away before printing the message.

This forces a "refuse, hand-edit, re-lint" loop even for the common case
where the fix is entirely mechanical (a new boundary appeared after an
edit, and it just needs an empty `MOCK ... END-MOCK`).

## Goals

- Every `UNMOCKED_*` `RefusalReason` message ends with the literal `.cut`
  snippet that would resolve it, reusing the scaffold's own directive
  renderer so the two can never drift apart.
- `mockymock generate --fill <existing.cut>` inserts only the missing
  mock blocks for a `.cut` file's own `TESTCASE`s into that file in
  place, leaving every existing directive, `EXPECT`, `VERIFY`, and
  comment untouched.
- Full-file `generate` (no `--fill`) is unchanged.

## Non-goals

- `--fill` never edits or removes an *existing* `MOCK` block, even one
  whose body is empty or wrong -- filling in blanks is safe to automate,
  rewriting authored logic is not. That stays a `lint`-reported problem
  for the human.
- No attempt to fill `UNSUPPORTED_*` refusals (DECLARATIVES, ALTER,
  SORT/MERGE mixed form, etc.) -- those are structural refusals with no
  mechanical fix; only `UNMOCKED_*` (a boundary exists and is reachable,
  but nothing in the test case matches it) has one.

## Design

### 1. Refusal messages carry their own fix

`RefusalReason` (`mockymock/analysis/refusal/_types.py:88-90`) gets one
new optional field:

```python
@dataclass
class RefusalReason:
    code: str
    message: str
    suggested_fix: str | None = None   # literal .cut text, or None
```

`None` for anything without a mechanical fix (every `UNSUPPORTED_*`
code); the four-line `MOCK ... END-MOCK` block for `UNMOCKED_*` codes.
`_types.py` already has a dataclass here, so this is additive and every
existing construction (`RefusalReason(code=..., message=...)`) keeps
working unchanged.

In `check_test_case` (`_gates.py:1195` onward), at the point each
`UNMOCKED_*` `RefusalReason` is built (`_gates.py:1400-1412` and its
sibling branches for `CANCEL`/dynamic `CALL`/CICS/DLI/report-writer),
call a new `mockymock.dsl.generator.directive_snippet(site, surface) ->
str` -- a thin public wrapper around the existing `_directive_for` /
`_placeholder_body_for` pair, changed from private to a small public
surface (`directive_snippet` calls the existing private helpers; no
duplication). Pass the result as `suggested_fix`.

Console/JSON refusal rendering (wherever `RefusalReason.message` is
printed today -- `_cmd_lint`, `_cmd_run`'s pre-splice gate, VS Code's
`lintDiagnostics.ts` which parses `mockymock lint`'s output) appends,
when `suggested_fix` is set:

```
READ boundary at line 42 (paragraph 'PROCESS-LOOP', keys INV-FILE) is
reachable from 'MAIN-PROCESS' but no MOCK directive in this test case
matches it

    Add to this TESTCASE:
        MOCK READ INV-FILE
        END-MOCK
```

`mockymock lint --format json` (the machine-readable path the extension
consumes) adds `"suggested_fix"` as a new key on the finding object --
additive, so an older client parsing the JSON ignores it safely.

### 2. `generate --fill`

New flag on the `generate` subcommand: `--fill EXISTING.cut` (mutually
exclusive with `-o`/`--output`, which controls where a *fresh* scaffold
is written -- `--fill` always writes back to the file it read).

Algorithm, in `mockymock/dsl/generator.py`:

1. Parse the existing `.cut` with `dsl.parser.parse_cut` (already used by
   `collect`/`lint`).
2. For each `TESTCASE`, run the *same* reachability + refusal analysis
   `mockymock lint` already runs (`refusal.check_test_case`), and collect
   every `UNMOCKED_*` `RefusalReason` for that case along with its now-
   populated `suggested_fix`.
3. For each such reason, insert the fix snippet as a new `MOCK ... END-MOCK`
   block immediately before that `TESTCASE`'s `PERFORM` line (matching
   where a hand-authored mock block conventionally goes, and where the
   scaffold itself places them), using the *original file's own line
   ending and indentation style* (sniffed from the first existing `MOCK`
   line's leading whitespace, defaulting to 4 spaces if the case has no
   existing mock to sniff from).
4. Write the result back to the same path. Case order, `TESTCASE` names,
   existing directive text, and all comments are preserved byte-for-byte
   outside the inserted lines -- this is a text insertion at known line
   numbers, not a re-serialization of the parsed model (re-serializing
   would risk reformatting hand-written directives, e.g. reflowing a
   `PROVIDER` table, which `--fill` must never touch).
5. Print a summary: `mockymock generate --fill: added N mock block(s)
   across M test case(s)` and, for each, `<file>:<line>: MOCK <category>
   <key>` so the user can review the diff before committing it.
6. If a `TESTCASE` has zero `UNMOCKED_*` reasons, it is left completely
   untouched (not even whitespace-normalized) and is not mentioned in the
   summary beyond a final "N test case(s) already fully mocked."
7. `UNSUPPORTED_*`/`UNKNOWN_PARAGRAPH` reasons found during the same pass
   are printed as warnings (they have no `suggested_fix`) but do not
   block filling the mockable ones in the same run -- consistent with
   "refusal checks are cumulative within one gate" (`.okf/cli.md`'s
   Gotchas section).

### 3. Interaction with `--with-data`

`--fill` and `--with-data` are mutually exclusive in this iteration:
`--with-data` scaffolds a *fresh* file with real generated data per
boundary (bundle-driven), and mixing that generation model with
insertion-into-existing-file is a separate, harder problem (which
scenario does an inserted mock belong to?) left for a future iteration
if requested. `--fill` always uses the same empty-placeholder bodies a
plain (non-`--with-data`) `generate` would.

## Implementation steps

1. `mockymock/analysis/refusal/_types.py`: add `suggested_fix` field.
2. `mockymock/dsl/generator.py`: extract/export `directive_snippet(site,
   surface) -> str`; unit test that it matches what a full `generate`
   scaffold emits for the same site (regression guard against drift).
3. `mockymock/analysis/refusal/_gates.py`: populate `suggested_fix` at
   each `UNMOCKED_*` construction site (the `_gates.py:1400`-family
   branches plus the CANCEL/dynamic-CALL/report-writer siblings named in
   `.okf/analysis.md`'s refusal table).
4. `mockymock/report/formatters.py` and `_cmd_lint`'s console path: print
   the suggestion block when present.
5. `mockymock/report/json_report.py` (or wherever `lint --format json`
   serializes findings): add `suggested_fix` key.
6. `mockymock/cli/main.py`: add `--fill` to the `generate` subparser
   (mutually exclusive group with `-o`/`--output` and `--with-data`); new
   `_fill_cut_file(cut_path, program_path, args) -> int` function, called
   from `_cmd_generate` when `--fill` is set instead of the existing
   fresh-scaffold path.
7. `mocky-mock-vscode`: `lintDiagnostics.ts` already parses `mockymock
   lint`'s JSON; extend the diagnostic it creates to carry
   `suggested_fix` as a `Diagnostic.data`-equivalent (VS Code diagnostics
   don't carry arbitrary data directly, so store it in a side map keyed
   by `(uri, range)` the way the extension's coverage/mutation reports
   already keep parallel side-channel data) and offer it as a Quick Fix
   (`CodeAction`) that inserts the snippet -- this is the natural
   companion to `--fill` for editor users and is cheap once the JSON
   carries the field; call out as a fast-follow in the same PR or the
   next one.
8. Update `.okf/dsl.md` (generate's flags) and `.okf/analysis.md`
   (`RefusalReason` shape) and append a dated `.okf/log.md` entry.

## Testing plan

- Unit: `directive_snippet` output equals what `scaffold_cut` emits for
  every `MockCategory` with a placeholder body, parameterized.
- Unit: each `UNMOCKED_*` refusal in `test_refusal.py`-equivalent tests
  gains an assertion on `suggested_fix`'s exact text.
- Unit: `--fill` against a small hand-built `.cut` with one case missing
  a `READ` mock and one case already fully mocked -- assert only the
  first case gained a block, byte-diff the rest of the file against the
  original.
- Unit: `--fill` twice in a row is idempotent (second run reports "0
  mock blocks added, N already fully mocked").
- Integration (Docker-gated): `generate --fill` on
  `examples/invupdt/INVUPDT.cut` after deleting one of its `MOCK` blocks
  reproduces the original file's mocking behavior (not necessarily its
  exact text, since the deleted block may have had a non-empty body) and
  the resulting suite still runs.
- JSON contract test: `lint --format json`'s schema test (if one exists
  per `.okf/testing.md`'s contract-test tier) gains `suggested_fix` as an
  optional key, confirming an older-schema consumer still parses the
  output.

## Backward compatibility

`suggested_fix` is additive on `RefusalReason` and in the JSON schema.
Console output grows by a few lines per finding but the pass/fail
exit code and existing message text are unchanged. `--fill` is a new,
separately-invoked flag; plain `generate` is untouched.
