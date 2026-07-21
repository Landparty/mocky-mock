---
type: Module
title: DSL (.cut test files)
description: MockTestSuite/MockTestCase/MockDirective model, the parser that reads .cut text into it, and the generator that scaffolds .cut files from a MockSurface.
tags: [dsl, parser, cut-file]
timestamp: 2026-07-21T01:00:00Z
---

# Overview

`mockymock/dsl/` is the DSL layer for `.cut` test files: a small text format
that says which COBOL boundaries to mock, what to move into working-storage
before running, which paragraph to `PERFORM`, and what to assert after.

```
.cut text ──▶ parser.py: parse_cut() ──▶ model.py: MockTestSuite
                                                │
                             (consumed by splicer/ to instrument COBOL)

MockSurface (static analysis) ──▶ generator.py: scaffold_cut() ──▶ starter .cut text
```

`model.py` holds no behavior beyond `describe()` and `all_mock_keys()` — it's
the shared vocabulary between the parser (produces it), the generator
(also produces it, indirectly, as text), and the splicer (consumes it).

# Grammar

```
TESTSUITE "<name>"

[ PROVIDER <name>
      HEADER <col>, ... [, <col>]*
      ROW <value>, ... [, <value>]* [ ROW ... ]* ]*

TESTCASE "<name>" [ TAGS "<tag>" ... ] [ USING PROVIDER <name> ]
    [ MOCK <category> <key>
          <COBOL statement lines, passed through verbatim>
      END-MOCK ]*
    [ MOVE <value> TO <target> ]*
    PERFORM <paragraph> [ THRU|THROUGH <paragraph> ]
    [ EXPECT <data-name> TO BE <value> ]*
    [ VERIFY [<category>] <key> WAS CALLED|PERFORMED <expectation> ]*
```

- Exactly one `TESTSUITE` per file — a second `TESTSUITE` line raises
  `CutParseError` with its line number (it used to silently discard every
  previously parsed test case, so concatenated .cut files ran only the
  last suite).
- `TESTCASE` must follow a `TESTSUITE`; `MOCK`/`MOVE`/`PERFORM`/`EXPECT`/`VERIFY`
  must all be inside a `TESTCASE`. Violating order raises `CutParseError` at
  the offending line.
- One `PERFORM` per test case — a second `PERFORM` line raises
  `CutParseError` (`already has a PERFORM target`).
- `<expectation>` is validated **at parse time**: `ONCE`, `NEVER`,
  `AT LEAST ONCE`, or `<n> TIMES` (case-insensitive), matching exactly what
  `splicer/driver.py`'s `_verify_condition` compiles — anything else raises
  `CutParseError` with the .cut line number instead of exploding later in
  codegen as a raw `ValueError`. Keep `_validate_expectation` (parser) and
  `_verify_condition` (driver) in sync.
- Lines starting with `*>` are comments **outside** a `MOCK` body; inside a
  body they pass straight through as valid free-form COBOL (a mock body can
  legitimately contain a COBOL comment).
- Blank lines are always skipped.
- `TAGS "<tag>" ["<tag>" ...]` after the TESTCASE name attaches selection
  tags (`run --tag`, `collect --json`, the JSON run report). Tags have no
  runtime semantics; an empty (`""`/blank) tag raises `CutParseError`.
- The parser records 1-based `.cut` line numbers on the model: `MockTestSuite
  .line`, `MockTestCase.line`, `ExpectDirective.line`, `VerifyDirective.line`
  (all default 0 for hand-built models). Editor integrations rely on these
  for navigation and failure locations — keep them accurate when touching
  the parse loop.

### `BEFORE-EACH` / `BEFORE-ALL`

At most one of each per `TESTSUITE`, appearing after the `TESTSUITE`
header and before the first `TESTCASE`. Bodies hold `MOCK` directives
only. Desugared at parse time into every `TESTCASE`'s own `mocks` list;
precedence on a `(category, key)` collision is `TESTCASE` >
`BEFORE-EACH` > `BEFORE-ALL`, silently. The xUnit-style names suggest an
execution-timing difference; there isn't one -- `BEFORE-ALL` and
`BEFORE-EACH` differ **only** in override precedence. Both desugar into
every test case identically at parse time; no code path ever runs a
`BEFORE-ALL`/`BEFORE-EACH` body separately from, or before, the test
case's own spliced mocks. See
`docs/2026-07-20-before-blocks-and-file-status-design.md`.

### `FILE-STATUS IS <mnemonic-or-code>`

Usable once inside a `MOCK OPEN|CLOSE|READ|DELETE|START|UNLOCK` body
(not `WRITE`/`REWRITE`). `<mnemonic>` is one of `SUCCESS`, `END-OF-FILE`,
`DUPLICATE-KEY`, `RECORD-NOT-FOUND`, `FILE-NOT-FOUND`, `ALREADY-OPEN`,
`NOT-OPEN`, `NO-CURRENT-RECORD`; a quoted two-character literal (e.g.
`"92"`) always works too. Every eligible category also gets an implicit
`MOVE "00"` (default success) before the mock's own body whenever the
target file declares a `FILE STATUS` field, whether or not
`FILE-STATUS IS` is used. See
`docs/2026-07-20-before-blocks-and-file-status-design.md`.

Fail-closed on malformed input: any mock-body line that starts with the
`FILE-STATUS` keyword but doesn't fully match the mnemonic-or-quoted-literal
grammar above (an unquoted code like `FILE-STATUS IS 92`, a mnemonic with
digits like `FILE-STATUS IS EOF10`, a missing value) raises `CutParseError`
at that line instead of silently falling through to `body_lines` and being
spliced verbatim into generated COBOL, where it would surface as a
confusing `cobc` compile error instead of a `.cut`-level refusal.

## Case rules

Every DSL keyword is case-sensitive uppercase (`testsuite "x"` is an
`unrecognized statement` error) with one deliberate exception: **`END-MOCK`
is case-insensitive and accepts an optional trailing period** (`END-MOCK.`,
`end-mock` — the trailing period is the natural COBOL habit). The leniency
exists because a missed END-MOCK doesn't fail at its own line; it silently
swallows the rest of the file into the mock body. Bare keys are upper-cased
by the parser; quoted keys are preserved exactly (see below).

## `PROVIDER` parameterized test cases

`PROVIDER <name>` is a suite-level block (sibling of `TESTCASE`, must be
declared before any `TESTCASE` that references it) holding a `HEADER`
(bare, comma-separated column names) and one or more `ROW`s
(comma-separated, quote-aware-split free-form COBOL value text, same
convention as `MOVE`/`EXPECT` values). `TESTCASE "..." USING PROVIDER
<name>` binds a test-case template to it.

A `PROVIDER` block admits only `HEADER`/`ROW` lines (plus blanks/`*>`
comments) and is closed only by the next `TESTCASE` or `PROVIDER` line;
any other statement while it's open -- `MOVE`, `PERFORM`, `EXPECT`,
`VERIFY`, `MOCK`, `BEFORE-ALL`/`BEFORE-EACH` -- raises `CutParseError`
fail-closed. This is deliberate: opening a `PROVIDER` also clears the
current `TESTCASE`/`BEFORE-*` state (`case = None`, `mock_target =
None`), so before this rule existed a stray statement between/after
`ROW` lines silently attached to whichever `TESTCASE`/`BEFORE-*` block
was open *before* the `PROVIDER`, with any `{Placeholder}` left
unsubstituted (see `tests/unit/test_dsl_parser.py::
test_stray_move_inside_open_provider_raises` and the two neighboring
tests, including one that pins a `BEFORE-EACH` appearing while a
`PROVIDER` is open as an error too).

`parser.py`'s `_expand_providers` runs as the last step of `parse_cut()`:
it replaces a provider-bound `TESTCASE` with one ordinary `MockTestCase`
per row, substituting `{ColumnName}` tokens (`_PLACEHOLDER_RE`) into that
case's `MOVE` and `EXPECT` values only -- `MOCK` bodies, `MOVE` targets,
`EXPECT` data-names, `PERFORM` target/thru, and `VERIFY` stay untouched
and identical across every row. An unknown `{Foo}` token is a
`CutParseError` naming the provider's real columns; an undeclared/
mistyped `USING PROVIDER` reference errors at the `TESTCASE` line.

Generated cases are named `"<name> [row <n>: <first column value>]"` and
their `.line` points at that row's own `ROW` line (not the shared
`TESTCASE` header) -- `MockTestSuite.test_cases` after `parse_cut()`
returns holds only these expanded, ordinary cases: analysis, splicer,
runtime, report, and every CLI flag never learn `PROVIDER` existed. A
`TESTCASE` with no `USING PROVIDER` is never scanned for `{...}` tokens
at all -- strict backward compatibility.

See `docs/2026-07-20-provider-parameterized-test-cases-design.md` for
the full design and rejected alternatives (a single compiled
`OCCURS`-table loop, `ROW ( FIELD = value, ... )` pairs, `MOCK`-body
templating).

## `MOCK <kind> <key>` forms

Two key syntaxes, split by category:

| Syntax | Categories | Key regex | Example |
|---|---|---|---|
| Quoted | `CALL`, `MQ` (sugar), `SQL`, `CICS`, `DLI` | `"[^"]*"` | `MOCK CALL "DISCRATE"`, `MOCK SQL "UPDATE INVENTORY"` |
| Bare COBOL word | `CALL` (dynamic form), `OPEN`, `CLOSE`, `READ`, `WRITE`, `REWRITE`, `DELETE`, `START`, `UNLOCK`, `ACCEPT`, `PARAGRAPH`, `SECTION` | `[A-Za-z0-9][A-Za-z0-9-]*` | `MOCK OPEN INV-FILE`, `MOCK CALL WS-PGM-NAME`, `MOCK PARAGRAPH CALC-TOTALS` |

Bare keys are upper-cased by the parser (`m.group("key").upper()`); quoted
keys are kept exactly as written.

`MockCategory` (in `model.py`) has 14 members, but `MOCK`/`VERIFY` text only
ever spells 12 keywords, because two collapse via sugar/aliasing at parse
time (`_resolve_category` in `parser.py`):

| Category enum | `.cut` keyword | How it's reached |
|---|---|---|
| `CALL` | `CALL` | `MOCK CALL "X"` (quoted key) |
| `DYNCALL` | `CALL` | `MOCK CALL WS-PGM` (bare key) — **never written as `DYNCALL`** in `.cut` files |
| `SQL`, `CICS`, `DLI` | `SQL`, `CICS`, `DLI` | quoted key, prefix-matches normalized EXEC text |
| `OPEN`,`CLOSE`,`READ`,`WRITE`,`REWRITE`,`DELETE`,`START`,`UNLOCK` | same | bare key = file/record name |
| `ACCEPT` | `ACCEPT` | bare key = data-name being accepted into |
| `PARAGRAPH`, `SECTION` | same | bare key = a PROCEDURE DIVISION paragraph/section name — flow-target mocks, not boundaries; grouped as `FLOW_CATEGORIES` in `model.py` (see [analysis](analysis.md)'s `flow_mocks.py` and [splicer](splicer.md)'s header dispatch) |
| `CALL` (again) | `MQ` | `MOCK MQ "X"` — pure sugar, becomes a `CALL` directive; MQ is invoked through static `CALL`s, so there is no `MockCategory.MQ` |

`VERIFY` mirrors the same two-syntax split (`_VERIFY_QUOTED_RE` /
`_VERIFY_BARE_RE`), plus one more back-compat wrinkle: a bare `VERIFY "X" WAS
CALLED ...` with **no category keyword at all** resolves to `CALL` (v1
grammar had no category concept). `CALLED` and `PERFORMED` are accepted
interchangeably everywhere.

Why `DYNCALL` exists as a distinct enum member instead of overloading `CALL`
with a "is_dynamic" flag: it keeps every `(category, key)`-keyed structure
(tally registry, declared-`VERIFY` set, dedup sets) from ever cross-matching
a quoted static-CALL directive against a bare dynamic-CALL site, or vice
versa — see the docstring on `MockCategory` in `model.py` for the full
rationale.

# AST Model (`model.py`)

| Class | Fields | Notes |
|---|---|---|
| `MockCategory` (Enum) | `CALL, DYNCALL, OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, UNLOCK, SQL, CICS, DLI, ACCEPT, PARAGRAPH, SECTION` | `.keyword` property maps `DYNCALL → "CALL"`, everything else to its own name |
| `MockDirective` | `category, key, body_lines: list[str], rows: list[list[tuple[str, str]]] \| None` | `.program_name` is v1-compat alias for `.key` (CALL-only meaning); `.describe()` renders `.cut`-style text (`CALL "X"`, `CALL WS-PGM`, `READ INFILE`) used in refusal messages; `rows` is set only for a `MOCK SQL "..." ROWS` directive and is mutually exclusive with `body_lines` |
| `DataProvider` | `name, line, header: list[str], rows: list[list[str]], row_lines: list[int]` | Parser-internal only -- never stored on `MockTestSuite`/`MockTestCase`; consumed and discarded by `_expand_providers` before `parse_cut()` returns |
| `ExpectDirective` | `data_name, expected_value` | one `EXPECT` line |
| `VerifyDirective` | `category, key, expectation` | `.program_name` same v1-compat alias as `MockDirective` |
| `MockTestCase` | `name, mocks, setup_moves: list[(value,target)], perform_target, perform_thru: str\|None, expectations, verifications` | `perform_thru` is `None` unless `PERFORM X THRU Y` was used |
| `MockTestSuite` | `name, test_cases` | `all_mock_keys()` returns every distinct `(category, key)` pair across all test cases, **first-appearance order** — this ordering is load-bearing: the tally registry, driver bookkeeping, and the splice loop all iterate this list, so first-appearance order determines codegen order |

`FILE_OP_CATEGORIES` (frozenset of the 8 file-op categories) and
`EXEC_CATEGORIES` (frozenset of `SQL/CICS/DLI`) are module-level constants
used both here and by `generator.py` to branch on key-syntax family.

# Parser (`parser.py`)

Single-pass line scanner over `text.splitlines()`, tracking three pieces of
mutable state: current `suite`, current `case`, and current open `in_mock`
directive (`None` when not inside a `MOCK...END-MOCK` block).

Key regexes, matched in this order per non-blank line:

1. If inside a `MOCK` body: look only for `END-MOCK` (any case, optional
   trailing period); anything else is appended verbatim to `body_lines`
   (no further parsing — a mock body's contents are opaque to the DSL
   parser).
2. `*>` comment (only reachable when not inside a mock body).
3. `TESTSUITE "..."` — errors if a suite is already open (one per file).
4. `TESTCASE "..."` — requires `suite` already set; resets the per-case
   duplicate-MOCK tracker.
5. `MOCK <quoted-cat> "<key>"` then `MOCK <bare-cat> <key>` — requires
   `case` already set; whichever matches opens `in_mock` and appends it to
   `case.mocks` immediately (body lines get attached as they arrive on
   subsequent iterations, single object mutated in place). An empty quoted
   key (`MOCK CALL ""`) and a duplicate `(category, key)` within the same
   TESTCASE both raise `CutParseError` here (the duplicate error names both
   line numbers; it used to surface much later as an `AMBIGUOUS_MOCK`
   refusal with misleading advice).
6. A line starting with literal `MOCK` that matched neither pattern raises
   `CutParseError` with a message that spells out the two key-syntax
   families — this is the fail-closed path for typos like `MOCK CALL
   DISCRATE` (missing quotes) or an unknown category word.
7. `MOVE <value> TO <target>` — appended to `setup_moves` as a tuple, in
   file order (order matters: later `MOVE`s to the same target win at
   runtime, same as COBOL).
8. `PERFORM <target> [THRU|THROUGH <thru>]` — a second PERFORM in the
   same TESTCASE raises `CutParseError`.
9. `EXPECT <name> TO BE <value>`.
10. `VERIFY` quoted then bare (mirrors step 5's two-family split, plus the
    no-category-means-CALL back-compat case). The expectation phrase is
    validated here via `_validate_expectation`.
11. Anything else: `CutParseError: unrecognized statement`.

After the full scan, two more checks raise `CutParseError`: `suite is None`
(no `TESTSUITE` line ever matched), and `in_mock is not None` — an
unterminated `MOCK` body errors with the line number of the `MOCK` line
that opened it (`tests/unit/test_dsl_parser.py` pins both).

# Generator (`generator.py`)

`scaffold_cut(suite_name, surface: MockSurface) -> str` builds starter `.cut`
text from static analysis, not from existing `.cut` files (no round-trip
model → text serializer exists elsewhere in this package — `scaffold_cut` is
the only text producer, and it emits strings directly rather than
constructing `MockTestSuite`/`MockDirective` objects and rendering those).

Rules:

- Groups `surface.boundary_sites` by `paragraph_name`; one `TESTCASE` per
  paragraph that has at least one **usable** site. A site is unusable and
  skipped if `site.category is None`, or if it's `nested` but has no
  validated splice `span` (unspliceable nested sites are surfaced elsewhere,
  via the CLI's unsupported-boundaries listing, not here).
- Each generated `TESTCASE` mocks **all** of that paragraph's own mockable
  sites, deduped by `(category, key)` — deliberately not a partial subset,
  because a partial mock would walk the user straight into the run
  command's refusal gate (`UNMOCKED_*` checks: an unmocked CALL has nowhere
  to link, unmocked file I/O hits a nonexistent sandbox file, unmocked EXEC
  can't compile, unmocked `ACCEPT` reads real stdin).
- Only covers each paragraph's **own** sites — boundaries reached
  transitively via `PERFORM` are not auto-mocked; those still need manual
  `.cut` edits (the run command's refusal gate names them precisely when
  missing).
- Placeholder bodies (`_PLACEHOLDER_BODIES`): `CALL`/`DYNCALL` →
  `MOVE 0 TO RETURN-CODE`; `SQL` → `MOVE 0 TO SQLCODE`; file-op categories →
  empty body; `ACCEPT` → `MOVE SPACES TO <target>` (built per-site, not from
  the static dict, since it needs the target name).
- Per-category directive-line shape (`_directive_for`):
  - `CALL`: `MOCK CALL "name"` normally, `MOCK MQ "name"` if `site.is_mq`;
    returns `None` (site skipped) if no key was captured — emitting
    `MOCK CALL ""` would no longer round-trip, since the parser rejects
    empty quoted keys.
  - `DYNCALL`: `MOCK CALL <identifier>` — bare, unquoted, from
    `site.keys[0]`.
  - File-op categories: `MOCK <CATEGORY> <key>`; returns `None` (site
    skipped) if the site parsed no usable key.
  - `ACCEPT`: `MOCK ACCEPT <target>`; returns `None` if no key.
  - `SQL`/`CICS`/`DLI`: key is **not** the full statement text — it's the
    shortest word-prefix of `site.match_text` that's unique among the
    program's sites of the same category (`_unique_prefix`), so the
    generator itself never emits an `AMBIGUOUS_MOCK` pair that the splicer
    would later reject. Falls back to the full text if no proper prefix is
    unique.
- Output shape per paragraph:
  ```
  TESTCASE "<paragraph> boundaries: <label1>, <label2>"
      MOCK <cat> <key>
          <placeholder body lines, indented>
      END-MOCK
      ...
      PERFORM <paragraph>
  ```
  `labels` are deduped `site.label` values joined with `", "`, used only in
  the human-readable `TESTCASE` name.
- Suite and TESTCASE names pass through `_quote_safe` (double quotes
  become single quotes): the .cut grammar has no escape syntax for a `"`
  inside a quoted name, so interpolating one raw would make the scaffold
  unparseable.

### `ROWS` cursor sugar

`MOCK SQL "<prefix>" ROWS ( FIELD = value, ... ) ( FIELD = value, ... )
END-MOCK` is SQL-only grammar (any other category raises `CutParseError`)
that stores structured rows on `MockDirective.rows` instead of free-form
`body_lines` — the two are mutually exclusive by construction (the parser
routes lines to one or the other based on whether `ROWS` appeared on the
opening line). Row values are unparsed free text (matching `EXPECT ... TO
BE <value>`'s convention) split on top-level commas — `_split_top_level` in
`parser.py` is quote-aware, so a value like `EMP-NAME = "SMITH, JR."`
isn't cut at the comma inside the literal. An empty `ROWS` block (`ROWS`
immediately followed by `END-MOCK`) is a `CutParseError`, not a silent
no-op.

Codegen happens at splice time (`injector.build_rows_block`), not parse
time, because the tally field name isn't resolved until
`naming.TallyRegistry` runs post-parse over the whole suite. Each row
generates a `WHEN <tally> = N` branch that MOVEs its fields and sets
`SQLCODE` to 0; `WHEN OTHER` (rows exhausted) sets `SQLCODE` to 100 (DB2's
"not found" code), fixed in v1.

# Gotchas

- **`MOCK MQ` has no `MockCategory.MQ`.** It is pure `.cut`-syntax sugar for
  `CALL`, resolved in `parser._resolve_category` (`cat == "MQ"` returns
  `MockCategory.CALL`). If you `grep` the model for MQ handling and find
  nothing, that's correct — MQ only exists in the parser's regex layer and
  in `generator.py`'s `is_mq` branch that re-adds the `MQ` keyword for
  scaffold readability. Do not add a `MockCategory.MQ`; it would break the
  `(category, key)` matching invariant described in the `MockCategory`
  docstring.
- **`DYNCALL` is never spelled `DYNCALL` in a `.cut` file.** Both `MOCK` and
  `VERIFY` spell it `CALL` with a bare (unquoted) key; the parser
  distinguishes it from static `CALL` purely by whether the key was quoted
  (`bare_key=True` passed into `_resolve_category`). A future editor adding
  a new bare-key category must extend `_BARE_CATS` in `parser.py` **and**
  add the category to `FILE_OP_CATEGORIES`/`FLOW_CATEGORIES`/handle it
  explicitly in `_resolve_category` and `MockDirective.describe()`, or it
  will silently fall through (PARAGRAPH/SECTION, added 2026-07-20, ride
  `MockCategory(cat)` in `_resolve_category` because their enum values
  equal their keywords, and render bare in `describe()` via
  `FLOW_CATEGORIES`).
- **A missing `END-MOCK` still swallows lines until EOF before erroring.**
  The unterminated-body check fires only at end of file (with the opening
  MOCK's line number); everything between the `MOCK` line and EOF —
  including what would otherwise be `TESTCASE`/`PERFORM` text — has already
  been absorbed into `body_lines` by the time the error raises. Mid-file,
  a forgotten `END-MOCK` therefore usually surfaces as this EOF error, not
  as an error at the next directive.
- **Bare keys are case-normalized, quoted keys are not.** `MOCK OPEN
  inv-file` and `MOCK OPEN INV-FILE` parse to the same key (`.upper()`
  applied); `MOCK SQL "select"` and `MOCK SQL "SELECT"` are different keys
  because quoted text is preserved exactly.
- **v1 → v2 naming residue:** `MockDirective.program_name` and
  `VerifyDirective.program_name` are both explicitly documented as "v1
  compat: the CALL key" — they alias `.key` and are only semantically
  meaningful when `category is MockCategory.CALL`; reading `.program_name`
  off a `READ`/`SQL`/etc. directive returns the key but the name is
  misleading for those categories.

# See Also

- [splicer](splicer.md) — consumes `MockTestSuite` to instrument COBOL source
- [cli](cli.md) — `mockymock generate` calls `scaffold_cut`; `mockymock run` calls `parse_cut`
