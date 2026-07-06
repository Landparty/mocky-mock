---
type: Module
title: DSL (.cut test files)
description: MockTestSuite/MockTestCase/MockDirective model, the parser that reads .cut text into it, and the generator that scaffolds .cut files from a MockSurface.
tags: [dsl, parser, cut-file]
timestamp: 2026-07-06T00:00:00Z
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

TESTCASE "<name>"
    [ MOCK <category> <key>
          <COBOL statement lines, passed through verbatim>
      END-MOCK ]*
    [ MOVE <value> TO <target> ]*
    PERFORM <paragraph> [ THRU|THROUGH <paragraph> ]
    [ EXPECT <data-name> TO BE <value> ]*
    [ VERIFY [<category>] <key> WAS CALLED|PERFORMED <expectation> ]*
```

- `TESTCASE` must follow a `TESTSUITE`; `MOCK`/`MOVE`/`PERFORM`/`EXPECT`/`VERIFY`
  must all be inside a `TESTCASE`. Violating order raises `CutParseError` at
  the offending line.
- One `PERFORM` per test case — a later `PERFORM` line overwrites
  `case.perform_target`/`case.perform_thru` rather than appending.
- `<expectation>` is free text captured as-is: `ONCE`, `AT LEAST ONCE`,
  `NEVER`, or `"<n> TIMES"` — the parser doesn't validate the phrase, the
  splicer's codegen does.
- Lines starting with `*>` are comments **outside** a `MOCK` body; inside a
  body they pass straight through as valid free-form COBOL (a mock body can
  legitimately contain a COBOL comment).
- Blank lines are always skipped.

## `MOCK <kind> <key>` forms

Two key syntaxes, split by category:

| Syntax | Categories | Key regex | Example |
|---|---|---|---|
| Quoted | `CALL`, `MQ` (sugar), `SQL`, `CICS`, `DLI` | `"[^"]*"` | `MOCK CALL "DISCRATE"`, `MOCK SQL "UPDATE INVENTORY"` |
| Bare COBOL word | `CALL` (dynamic form), `OPEN`, `CLOSE`, `READ`, `WRITE`, `REWRITE`, `DELETE`, `START`, `UNLOCK`, `ACCEPT` | `[A-Za-z0-9][A-Za-z0-9-]*` | `MOCK OPEN INV-FILE`, `MOCK CALL WS-PGM-NAME` |

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
| `MockCategory` (Enum) | `CALL, DYNCALL, OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, UNLOCK, SQL, CICS, DLI, ACCEPT` | `.keyword` property maps `DYNCALL → "CALL"`, everything else to its own name |
| `MockDirective` | `category, key, body_lines: list[str]` | `.program_name` is v1-compat alias for `.key` (CALL-only meaning); `.describe()` renders `.cut`-style text (`CALL "X"`, `CALL WS-PGM`, `READ INFILE`) used in refusal messages |
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

1. If inside a `MOCK` body: look only for `END-MOCK`; anything else is
   appended verbatim to `body_lines` (no further parsing — a mock body's
   contents are opaque to the DSL parser).
2. `*>` comment (only reachable when not inside a mock body).
3. `TESTSUITE "..."`.
4. `TESTCASE "..."` — requires `suite` already set.
5. `MOCK <quoted-cat> "<key>"` then `MOCK <bare-cat> <key>` — requires
   `case` already set; whichever matches opens `in_mock` and appends it to
   `case.mocks` immediately (body lines get attached as they arrive on
   subsequent iterations, single object mutated in place).
6. A line starting with literal `MOCK` that matched neither pattern raises
   `CutParseError` with a message that spells out the two key-syntax
   families — this is the fail-closed path for typos like `MOCK CALL
   DISCRATE` (missing quotes) or an unknown category word.
7. `MOVE <value> TO <target>` — appended to `setup_moves` as a tuple, in
   file order (order matters: later `MOVE`s to the same target win at
   runtime, same as COBOL).
8. `PERFORM <target> [THRU|THROUGH <thru>]` — overwrites, does not append.
9. `EXPECT <name> TO BE <value>`.
10. `VERIFY` quoted then bare (mirrors step 5's two-family split, plus the
    no-category-means-CALL back-compat case).
11. Anything else: `CutParseError: unrecognized statement`.

After the full scan, `suite is None` (no `TESTSUITE` line ever matched) also
raises `CutParseError`. There is no unterminated-`MOCK`-body check — a `.cut`
file that opens a `MOCK` and never closes it with `END-MOCK` parses without
error; the body simply absorbs every remaining line (including what would
otherwise be `TESTCASE`/`PERFORM`/etc. text) until EOF.

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
  - `CALL`: `MOCK CALL "name"` normally, `MOCK MQ "name"` if `site.is_mq`.
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
  add the category to `FILE_OP_CATEGORIES`/handle it explicitly in
  `_resolve_category`, or it will silently fall through.
- **An unterminated `MOCK` body doesn't error.** `parse_cut` has no
  end-of-file check for `in_mock is not None`; a missing `END-MOCK` silently
  swallows the rest of the file into that mock's `body_lines` rather than
  raising `CutParseError`. There is no regression test pinning this as
  intentional — it is simply what the single-pass state machine does.
- **`PERFORM` is last-write-wins, not additive.** A `.cut` file with two
  `PERFORM` lines in one `TESTCASE` silently keeps only the second; nothing
  in the grammar or parser prevents writing two.
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
