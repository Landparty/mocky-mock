---
type: Module
title: DSL (.cut test files)
description: MockTestSuite/MockTestCase/MockDirective model, the parser that reads .cut text into it, and the generator that scaffolds .cut files from a MockSurface.
tags: [dsl, parser, cut-file]
timestamp: 2026-09-27T00:00:00Z
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
    [ EXPECT <data-name> [NOT] TO BE [GREATER|LESS THAN [OR EQUAL TO]] <value> ]*
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
- `EXPECT` supports negation and comparison phrases: `EXPECT <name>
  [NOT] TO BE [GREATER THAN|LESS THAN [OR EQUAL TO]] <value>`. Each
  phrase normalizes at parse time to one canonical COBOL relation
  operator on `ExpectDirective.operator` (`model.EXPECT_OPERATORS`:
  `=`, `NOT =`, `>`, `NOT >`, `<`, `NOT <`, `>=`, `NOT >=`, `<=`,
  `NOT <=`); plain `TO BE` stays `=`, so pre-operator `.cut` files and
  hand-built directives are unchanged. `splicer/driver.py`'s
  `_EXPECT_FAIL_CONDITIONS` compiles each operator's *negation* into the
  generated `IF` (the IF guards the failure branch; `>=`/`<=` negate to
  the equivalent plain `<`/`>` to keep emitted conditions to the
  simplest COBOL-85 relational forms) — keep that map in sync with
  `EXPECT_OPERATORS`. The FAIL `DISPLAY` carries the operator between
  name and value (`expected WS-X > 5, got ...`), and
  `report/json_report.py`'s `_EXPECT_HEAD_RE` splits attribution on it
  (`expected` field keeps the bare value for `=`, is operator-prefixed
  otherwise). Fail-closed: a dangling phrase (`TO BE GREATER 5`,
  `... OR EQUAL 5`) raises `CutParseError` at the line instead of
  splicing leftover words into the generated IF
  (`_EXPECT_DANGLING_PHRASE_RE`, whole-word so `GREATER-VALUE` still
  parses as an ordinary value). Likewise an EXPECT value ending in a
  period outside quotes (`EXPECT WS-X TO BE 5.`, the COBOL sentence habit)
  raises `CutParseError` (`_reject_sentence_period`, 2026-09-27) --
  spliced into the generated `IF`, the period ended the sentence mid-IF
  and `cobc` rejected the driver while `lint` passed; a PROVIDER row
  substituting such a value is refused at its `ROW` line. Phrase words are case-sensitive
  uppercase like every other keyword.
- `EXPECT <data-name> TO BE <value>`'s `<data-name>` and `MOVE <value> TO
  <target>`'s `<target>` both accept one non-nested `(...)` group appended
  to an identifier — a table subscript (`WS-TABLE(1, 1)`, `WS-TABLE(1 1)`,
  `WS-TABLE(1,1)` all parse) or reference modification (`FIELD(1:5)`).
  Nested parens and `A OF B` qualification are unsupported and fail closed
  (`unrecognized statement`) rather than being mis-parsed. Both regexes
  share the `_SUBSCRIPTED_NAME` fragment in `parser.py`, which falls back to
  plain `\S+` for non-identifier tokens — that's what lets a literal
  `{Placeholder}` name (see `PROVIDER` below — data-names/MOVE-targets are
  deliberately never substituted) keep parsing verbatim. `PERFORM`'s target
  stays plain `\S+`: a paragraph/section name is never subscripted.

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

`FILE-STATUS IS` also parses correctly *inside* an open `MOCK READ ...
ROWS` body, not just in the ordinary mock-body case above — fixed
2026-08-10 (audit finding F19). `parser.py`'s `elif` chain used to check
`in_mock.rows is not None` (the generic ROWS-row branch) before the
FILE-STATUS IS / malformed-FILE-STATUS branches, so any `FILE-STATUS IS`
line written inside a `ROWS` body fell into "malformed ROWS row" instead
— reordered so the FILE-STATUS IS branches are checked first.

### `CAPTURE ARG <n> INTO <target>`

Usable inside a `MOCK CALL "..."` / `MOCK MQ "..."` (category `CALL`) or
bare `MOCK CALL <identifier>` (category `DYNCALL`) body only — any other
category raises `CutParseError` at that line. `<n>` is a 1-based
positive integer selecting the real `CALL`'s Nth `USING` parameter
*positionally* — deliberately not by COBOL variable name, so one
`CAPTURE` line stays correct even when two physical call sites sharing
the mocked key use differently-named arguments. `<target>` reuses
`_SUBSCRIPTED_NAME` (same fragment as `MOVE`'s target and `EXPECT`'s
data-name).

```
MOCK CALL "DISCRATE"
    CAPTURE ARG 1 INTO WS-CAPTURED-RATE
    MOVE 0 TO RETURN-CODE
END-MOCK
...
PERFORM CALC-DISCOUNT
EXPECT WS-CAPTURED-RATE TO BE 0.15
```

At splice time (`injector.build_site_dispatch`, see
[splicer](splicer.md)), `<n>` is resolved against *that exact physical
call site's* `CallStatement.using_parameters` and emitted as `MOVE
<real-arg-name> TO <target>`, before the directive's own body lines —
the captured value is then asserted with the ordinary `EXPECT`, no new
assertion syntax. Multiple `CAPTURE` lines in one body are allowed (one
per `USING` argument worth capturing); the same `<n>` twice in one body
is a `CutParseError`. `<n>` of `0` or non-numeric is a `CutParseError`.

**Multi-call semantics: last call wins.** The `MOVE` re-fires on every
dispatch through that site's `WHEN` branch, identical to any
hand-written mock-body `MOVE` — if the mocked `CALL` is reached more than
once in one `TESTCASE` (e.g. inside a loop), the captured field holds
whichever call happened *last* by the time `EXPECT` runs. Per-call
history/table capture is not supported.

**Fail-closed validation:** `CAPTURE_ARG_OUT_OF_RANGE` (see
[analysis](analysis.md)) refuses if `<n>` exceeds the real `USING`
parameter count of any call site the directive matches **anywhere in the
program** — reachability is deliberately not a filter, because the splicer
isn't one either. Because dispatch is per physical *site*, not per key,
two sites sharing one mocked key can legitimately declare a different
number of `USING` parameters — this refuses if **any** matching site has
too few, even if another matching site would be fine (fail closed over
partial safety, same posture as `UNRESOLVED_FILE_STATUS_TARGET`).

**Synthesized targets (`UT-CAP-...`, 2026-09-04).** A `<target>` whose
name starts with `splicer.captures.CAPTURE_TARGET_PREFIX` (`UT-CAP-`) means
"declare this for me": `splicer.captures.plan_captures` synthesizes a
WORKING-STORAGE item mirroring the captured argument's own PICTURE/USAGE
(a DISPLAY-only group becomes one `PIC X(<byte length>)` field, which is
exactly what a group MOVE copies) and a reset line, both threaded through
`cli.checks.extra_working_storage` / `extra_reset_lines_for` so all four
splice-and-compile pipelines (`run`, `debug`, `export`, `mutate`) stay in
step. The reset matters as much as the declaration: the suite compiles to
ONE binary, so an unreset capture would let a case that never reached its
CALL assert against the previous case's value.

That is what finally let `generate` scaffold captures at all — the target
previously had to be an existing item of a compatible type, so finding or
adding one was a manual step before every single capture, and the scaffold
never emitted one. The reserved prefix is what keeps it from being a
footgun: a mistyped real data name never starts with `UT-CAP-`, so it can
never silently become a new field. Fail-closed on everything else:
`UNRESOLVED_CAPTURE_TARGET` (raised from `run_static_checks` step 9)
refuses a synthesized target whose argument names different items at
different matching call sites, whose layout cannot be mirrored (a table, a
PICTURE-less COMP-1/POINTER item, a group holding non-DISPLAY data whose
bytes an alphanumeric copy would render unreadable), or whose name the
program already declares. A target WITHOUT the prefix is untouched — it
still has to exist in the program, exactly as before.

`generate` emits a `CAPTURE ARG <n> INTO UT-CAP-<key>-<n>` per mirrorable
argument (`_capture_lines_by_key`, precomputed onto `ProgramContext`),
first in the mock body so the `.cut` reads the way it executes, plus one
`*> STUB EXPECT <target>` comment per capture after the `PERFORM` — a
captured value with nothing pointing at it is not an assertion, and `run
--record-expectations` promotes those stubs to real `EXPECT` lines from an
actual run, which is the workflow that makes a captured argument useful
without the author guessing the value up front. The generator applies the
same mirrorability and agreement checks the refusal does, so a scaffolded
`.cut` never trips its own gate: an argument that fails either is simply
not captured, and the boundary's other arguments still are.
Agreement means every CALL site sharing the key passes the SAME item at
that position (and every site passes that many arguments at all); a key
called from several places whose sites agree is captured like a
single-site one (before 2026-09-27 any key with 2+ sites got no captures).

See docs/2026-08-11-argument-capture-design.md for the full design and
rejected alternatives (a dedicated `VERIFY ... WAS CALLED WITH ARG n =
value` combined syntax; capturing by COBOL variable name instead of
position; per-call history capture). That doc lists `generate` emitting
`CAPTURE` automatically as explicitly out of scope for v1; this is the
follow-up that closed it.

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
and identical across every row. A `{Column}` token naming one of the
bound provider's own columns inside a `MOCK` body is a `CutParseError`
at that line (`_reject_mock_body_placeholder`; `*>` comment lines are
exempt) -- left verbatim it linted clean and failed cobc on
`invalid symbol '{'`. An unknown `{Foo}` token is a
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
| Bare COBOL word | `CALL` (dynamic form), `OPEN`, `CLOSE`, `READ`, `WRITE`, `REWRITE`, `DELETE`, `START`, `UNLOCK`, `SORT`, `MERGE`, `RELEASE`, `RETURN`, `INITIATE`, `GENERATE`, `TERMINATE`, `ACCEPT`, `PARAGRAPH`, `SECTION` | `[A-Za-z0-9][A-Za-z0-9-]*` | `MOCK OPEN INV-FILE`, `MOCK CALL WS-PGM-NAME`, `MOCK SORT SORT-FILE`, `MOCK RETURN SORT-FILE ROWS ... TERMINAL (...)`, `MOCK PARAGRAPH CALC-TOTALS` |

Bare keys are upper-cased by the parser (`m.group("key").upper()`); quoted
keys are kept exactly as written.

`MockCategory` (in `model.py`) has 23 members. `MOCK`/`VERIFY` text spells
23 distinct keywords too (`sorted(set(m.keyword for m in MockCategory) |
{"MQ"})`), but the two counts don't line up member-for-member: `DYNCALL`
collapses into the `CALL` keyword (no `.cut` file is ever written with
`DYNCALL`), while `MQ` is a keyword with no member of its own (pure sugar
for `CALL`) — see `_resolve_category` in `parser.py`:

| Category enum | `.cut` keyword | How it's reached |
|---|---|---|
| `CALL` | `CALL` | `MOCK CALL "X"` (quoted key) |
| `DYNCALL` | `CALL` | `MOCK CALL WS-PGM` (bare key) — **never written as `DYNCALL`** in `.cut` files |
| `SQL`, `CICS`, `DLI` | `SQL`, `CICS`, `DLI` | quoted key, prefix-matches normalized EXEC text |
| `OPEN`,`CLOSE`,`READ`,`WRITE`,`REWRITE`,`DELETE`,`START`,`UNLOCK` | same | bare key = file/record name |
| `SORT`, `MERGE` | same | bare key = the SORT/MERGE statement's own SD file name -- only a plain-file-form site (`USING ... GIVING ...`, no INPUT/OUTPUT PROCEDURE) is ever classified into these categories; a mixed-form site (a USING/GIVING file paired with a procedure clause on the other side) stays `category=None`/`UNSUPPORTED_SORT_MERGE`, see [analysis](analysis.md) |
| `RELEASE`, `RETURN` | same | RELEASE keys on the record name (WRITE-shaped); RETURN keys on the SD file name (READ-shaped, `ROWS ( ... ) TERMINAL ( ... )` sugar reused from READ -- see below -- but RETURN always needs its own `TERMINAL` group since it is never in `FILE_STATUS_CATEGORIES`). Both only ever appear inside a SORT's INPUT/OUTPUT PROCEDURE, but are mockable independent of whether the enclosing SORT/MERGE turned out pure-procedure (left real) or mixed-form (still refused) |
| `ACCEPT` | `ACCEPT` | bare key = data-name being accepted into |
| `INITIATE`, `GENERATE`, `TERMINATE` | same | Report Writer (2026-09-02). Bare key = the report name (INITIATE/TERMINATE; a statement naming several reports is one site with several keys, like a multi-file OPEN) or the report/detail-group name (GENERATE). Grouped as `REPORT_WRITER_CATEGORIES` in `model.py`: bare-word keys, free-form body, no ROWS/TERMINAL/FILE-STATUS sugar (an RD has no status field) -- the splice alone is the mock, the RD/FD stay declared and the report file is never touched. Needs a cobol-parser that parses the REPORT SECTION (the 2026-09-02 release); earlier releases warn on it and the whole program refuses PARSE_WARNING before any directive is considered |
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

## `*> STUB EXPECT` comments (`mockymock run --record-expectations`)

```
*> STUB EXPECT <data-name> [-- <note>]
```

A convention, **not a grammar addition** — as far as `parse_cut()` is
concerned this is an ordinary `*>` comment (parses today with zero parser
changes) that does nothing at runtime until `mockymock run
--record-expectations` fills it in, turning it into a real
`EXPECT <data-name> TO BE <value>` line in place. `<data-name>` reuses the
same `_SUBSCRIPTED_NAME` fragment `EXPECT`/`MOVE` targets already parse
with, so a subscripted stub (`WS-TABLE(1, 1)`) is recognized identically.
`-- <note>` is optional, free text, never parsed for meaning (mirrors
cobol-parser's `Expectation.note` field it's meant to echo, e.g.
`"computed in CALC-TOTALS"`).

Meant to be written next to a would-be `EXPECT` — inside a `TESTCASE`, at
the point a real assertion would go — for a field whose correct value the
author (or an automated scaffolder, see cobol-parser's tier-3 stub
`Expectation`s) doesn't yet know. `mockymock.analysis.stub_expectations`
scans for these as raw text (deliberately not part of this grammar — see
that module's docstring for why); `mockymock.report.record_rewrite`
matches a scan against a recorded run and does the rewrite. Once
recorded, the resulting `EXPECT` line is an ordinary one in every way —
nothing distinguishes it from a hand-written `EXPECT`, and nothing about
this feature can ever touch it again (there's no more `*> STUB EXPECT`
text left to match). See
docs/2026-08-04-record-expectations-design.md for the full design.

# AST Model (`model.py`)

| Class | Fields | Notes |
|---|---|---|
| `MockCategory` (Enum) | `CALL, DYNCALL, OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, UNLOCK, SQL, CICS, DLI, ACCEPT, PARAGRAPH, SECTION` | `.keyword` property maps `DYNCALL → "CALL"`, everything else to its own name |
| `MockDirective` | `category, key, body_lines: list[str], rows: list[list[tuple[str, str]]] \| None, terminal_row: list[tuple[str, str]] \| None, captures: list[tuple[int, str]]` | `.program_name` is v1-compat alias for `.key` (CALL-only meaning); `.describe()` renders `.cut`-style text (`CALL "X"`, `CALL WS-PGM`, `READ INFILE`) used in refusal messages; `rows` is set only for a `MOCK SQL "..." ROWS`, `MOCK READ <file> ROWS`, or `MOCK RETURN <sd-file> ROWS` directive and is mutually exclusive with `body_lines`; `terminal_row` holds a READ/RETURN ROWS directive's optional (READ) or effectively mandatory (RETURN) `TERMINAL ( FIELD = value, ... )` group (its rows-exhausted `WHEN OTHER` field assignments) — always `None` for SQL rows (SQLCODE 100 is fixed) and for non-ROWS mocks; `captures` holds `CAPTURE ARG <n> INTO <target>` `(n, target)` pairs, only ever non-empty for CALL/DYNCALL directives |
| `DataProvider` | `name, line, header: list[str], rows: list[list[str]], row_lines: list[int]` | Parser-internal only -- never stored on `MockTestSuite`/`MockTestCase`; consumed and discarded by `_expand_providers` before `parse_cut()` returns |
| `ExpectDirective` | `data_name, expected_value, operator` | one `EXPECT` line; `operator` is the canonical relation asserted between the two (one of `EXPECT_OPERATORS`, default `"="`) |
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
   parser), with one fail-closed exception: a line holding a COBOL
   sentence-terminating period (`.` followed by whitespace/end of line,
   outside quotes and before any `*>`) raises `CutParseError`
   (`_reject_body_sentence_period`, 2026-09-27). The body is spliced into
   a `WHEN` of the generated `EVALUATE UT-CURRENT-CASE`, where the period
   ends the sentence mid-EVALUATE -- `lint` used to pass and `cobc` then
   failed on generated code (`unexpected END-EVALUATE`). ROWS/`TERMINAL`
   field values get the same check. A decimal point (`1.5`), a period
   inside a literal, or one in a comment is untouched.
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
- **`directive_snippet(site, surface) -> str | None` (2026-09-15)** wraps
  `_directive_for` to render one site's full `MOCK ... END-MOCK` block as a
  single string (4-space header/footer, 8-space body — exactly what
  `_scaffold_placeholder` itself emits). `None` whenever `_directive_for`
  is. This is the one place `RefusalReason.suggested_fix`
  (`analysis/refusal/_gates.py`) and `generate --fill`
  (`cli/main.py`'s `_fill_cut_file`) both get their fix text from, so a
  refusal's suggestion and a fresh scaffold can never disagree about what
  a site's directive looks like. See
  docs/2026-09-15-actionable-refusals-and-fill-design.md.
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

### `ROWS` cursor sugar (`SQL`) and `ROWS ... TERMINAL` (`READ`, `RETURN`)

`MOCK SQL "<prefix>" ROWS ( FIELD = value, ... ) ( FIELD = value, ... )
END-MOCK`, `MOCK READ <file> ROWS ( FIELD = value, ... ) ( ... )
[TERMINAL ( FIELD = value, ... )] END-MOCK`, and `MOCK RETURN <sd-file>
ROWS ( FIELD = value, ... ) ( ... ) TERMINAL ( FIELD = value, ... )
END-MOCK` are the only three categories `ROWS` is valid on (RETURN joined
2026-08-17, SORT/MERGE mocking) — any other category raises
`CutParseError` at parse time (`"ROWS is only supported for MOCK SQL,
MOCK READ, and MOCK RETURN, not MOCK <cat>"`). All three store structured
rows on `MockDirective.rows` instead of free-form `body_lines` — the two
are mutually exclusive by construction (the parser routes lines to one or
the other based on whether `ROWS` appeared on the opening line). Row
values are unparsed free text (matching `EXPECT ... TO BE <value>`'s
convention) split on top-level commas — `_split_top_level` in `parser.py`
is quote-aware, so a value like `EMP-NAME = "SMITH, JR."` isn't cut at the
comma inside the literal. An empty `ROWS` block (`ROWS` immediately
followed by `END-MOCK`/`TERMINAL`) is a `CutParseError`, not a silent
no-op.

**`TERMINAL ( FIELD = value, ... )`** is READ/RETURN-only grammar
(`_TERMINAL_RE` in `parser.py`): an optional (for READ) or, in practice,
**mandatory** (for RETURN — see below) line inside a `MOCK READ ... ROWS`
or `MOCK RETURN ... ROWS` body, at most one per directive, giving the
rows-exhausted branch's own field assignments instead of the parser's
implicit default. Parsed only while `in_mock.rows is not None` (i.e. only
inside an open `ROWS` block); using it inside `MOCK SQL ... ROWS` is a
`CutParseError` (SQLCODE's exhaustion value is fixed at 100, not
overridable), as is a second `TERMINAL` group on the same directive
(`"duplicate TERMINAL group"`). Stored on `MockDirective.terminal_row`,
`None` when omitted. **RETURN has no implicit default at all** — it is
never in `FILE_STATUS_CATEGORIES` (a SORT/MERGE's SD has no FILE STATUS
clause of its own, same reasoning as WRITE/REWRITE, see
[analysis](analysis.md)) — so `refusal.check_test_case`'s
`UNRESOLVED_FILE_STATUS_TARGET` check refuses a `MOCK RETURN ... ROWS`
with no `TERMINAL` group unconditionally, not just when a status field
happens to be missing (unlike READ, where the same check only fires when
BOTH the TERMINAL group and a FILE STATUS field are absent).

A `PERFORM ... UNTIL <flag> = <value>` loop driven by the READ's own
`AT END`-set flag (rather than the file's `FILE STATUS` field) needs that
flag's own `MOVE` inside the `TERMINAL` group too: the splicer replaces the
whole READ statement, `AT END` clause included, so without an explicit
`MOVE <value> TO <flag>` in `TERMINAL` the loop-guard flag is never set and
the loop never stops — the implicit default (`MOVE "10" TO <status field>`
when omitted) only satisfies a FILE-STATUS-driven loop, not a flag-driven
one.

**This grammar is hand-authoring only.** It exists for a human (or an
editor integration) writing a `.cut` file by hand against `mockymock
fixtures`' JSON output; `dsl/generator.py`'s bundle-driven scaffold
(`generate --with-data`/`--fixtures`, below) does **not** emit it — it
still hand-rolls its own `EVALUATE`/`WHEN <tally> = N` block for a
multi-row READ sequence (`_read_body`), mirroring this sugar's generated
shape rather than reusing the sugar's syntax. See
docs/2026-07-31-csv-sourced-rows-design.md, which proposed both this
inline form (now shipped) and a still-unimplemented `ROWS FROM CSV
"<path>"` row-source extension for `SQL` and `READ` alike.

Codegen happens at splice time (`injector.build_rows_block`), not parse
time, because the tally field name isn't resolved until
`naming.TallyRegistry` runs post-parse over the whole suite.
`build_rows_block(tally_name, rows, *, row_suffix_moves, exhausted_moves)`
is category-generic — it no longer hardcodes SQLCODE itself — each row
generates a `WHEN <tally> = N` branch that MOVEs its fields then appends
`row_suffix_moves` verbatim; `WHEN OTHER` (rows exhausted) appends
`exhausted_moves` verbatim. The two call sites in
`splicer/injector.build_site_dispatch` supply category-specific values:

- **SQL**: `row_suffix_moves=["MOVE 0 TO SQLCODE"]`,
  `exhausted_moves=["MOVE 100 TO SQLCODE"]` (DB2's "not found" code) —
  fixed in v1, matching the pre-generalization behavior exactly.
- **READ**: `row_suffix_moves=[]` (a file-op category's implicit
  default-success `MOVE "00"` already precedes the whole dispatch block
  when the file declares a `FILE STATUS` field — see the `FILE-STATUS IS`
  section above — so there is nothing left to append per row).
  `exhausted_moves` is additive, not either/or (fixed post-PR #46 review,
  Task 3): when the file has a resolved `FILE STATUS` field it always
  starts with a default `MOVE "10" TO <status field>` (COBOL's real
  end-of-file status code), and the directive's own `TERMINAL` group's
  MOVEs (`[f"MOVE {value} TO {field}" for field, value in
  directive.terminal_row]`) — when present — are appended right after, so
  an author's own MOVE to that same field (if TERMINAL includes one)
  overrides the default by coming later in the same `WHEN OTHER` branch,
  and a TERMINAL group that never mentions the status field no longer
  leaves it stuck at whatever `"00"` the default-success MOVE set on the
  call that triggered `WHEN OTHER` — it gets the correct `"10"` instead.
  With no `FILE STATUS` field, `exhausted_moves` is just the TERMINAL
  group's own MOVEs. See [analysis](analysis.md)'s
  `UNRESOLVED_FILE_STATUS_TARGET` refusal for the case where **neither**
  exists — `check_test_case` refuses fail-closed before splicing is ever
  reached, so `build_site_dispatch` raising `ValueError` for that same
  gap is a should-be-unreachable production invariant, not a normal
  control path.

### Bundle-driven scaffold (`generate --with-data`, Phase 8 of gen-fixtures)

`scaffold_cut(suite_name, surface, bundle=None)` — `bundle=None` is the
paragraph-grouped path described above, unchanged. A real
`dsl.fixture_bundle.FixtureBundle` (parsed from cobol-parser's
`ProgramFixtureGenerator` JSON, see `fixture_bundle.py` and cobol-parser's
`docs/fixture-bundle-schema.md`) switches to `_scaffold_with_bundle`:

- **One `TESTCASE` per `bundle.scenarios[]` entry**, not per paragraph,
  named from `scenario.name`, body `PERFORM <scenario.entry>`.
- **The join**: `_mockymock_boundary_keys(surface)` (this program's own
  walk — note it iterates *every* entry of `site.keys`, not just
  `keys[0]`, so a multi-file `OPEN A OUTPUT B` widens to both `(OPEN, A)`
  and `(OPEN, B)` even though it is one physical `BoundarySite`) is
  compared against `_bundle_boundary_keys(bundle)` (every fixture's
  `(category, key)` plus every `call_count`/`stub`-kind expectation's
  `ref`, since an OUT-direction boundary — a WRITE, a SQL
  INSERT/UPDATE/DELETE — gets no fixture at all, only a stub expectation;
  skipping stub refs here would misreport every OUT-direction boundary as
  a mismatch). Disagreement is never silent: `_warn_on_key_mismatch`
  prints both one-sided sets to stderr. This exact comparison is pinned by
  `tests/unit/test_fixture_bundle_contract.py`, parametrized over the
  `examples/*/` corpus — a mismatch there must be root-caused (nested-site
  span annotation missing, a real cobol-parser gap, etc.), not silently
  accepted; see that file's module docstring for the one currently
  accepted exception (`custprog`'s DCLGEN `EXEC SQL INCLUDE`, a
  cobol-parser preprocessing gap, not a Phase 1-8 regression).
- **`_bundle_mock_directives`** groups a scenario's fixtures by *physical
  site* (`id(site)`, not by key) before emitting anything — the same
  multi-file OPEN/CLOSE shape that widens `.keys` in the join above means
  naively emitting one directive per key would declare two `MOCK OPEN`
  directives that both match the same physical site
  (`AMBIGUOUS_MOCK`). One representative key per physical site is chosen
  and its status data merged instead. It returns `(lines, declared_keys,
  call_count_overrides)` — the third element covers `--placeholder`'s
  effect on VERIFY counts, see below. `declared_keys` is only the
  literally-emitted primary keys and gates
  `_render_expectation`'s `VERIFY ... WAS CALLED n TIMES` line — a
  narrower check than "is this key known to mockymock at all" is required
  here, or a `VERIFY` would be emitted for a key this TESTCASE mocked only
  as a non-primary alias of a shared site, which the run command's own
  `VERIFY_WITHOUT_MOCK` gate would then refuse. After real-data
  directives, every `mockymock_keys` entry not yet covered gets a
  placeholder directive too (reusing bundle-less `_directive_for`) — this
  unconditional "cover everything mockymock knows about" step is what
  keeps a mockymock-only key (a real key-set gap, or a boundary the bundle
  couldn't resolve, e.g. custprog's SQL FETCH above) from producing an
  UNMOCKED_* refusal instead of a scaffold a human can improve on.
- **Per-category body shape** (`_bundle_directive_for_group`, one real
  fixture group): a status-only boundary (OPEN/CLOSE/START/UNLOCK/DELETE)
  gets `_status_only_body` (a `FILE-STATUS IS` MOVE only when the status
  is non-"00"/"0" — file-op categories default to success implicitly, see
  `injector.build_site_dispatch`; SQL has no such default and always sets
  SQLCODE explicitly); a single-row READ/ACCEPT/WRITE gets
  `_single_row_body` (plain field MOVEs); a multi-row READ sequence gets
  `_read_body`'s hand-rolled `EVALUATE TRUE` / `WHEN <tally> = N` chain
  (mirroring `ROWS` sugar's own generated shape for consistency — `MOCK
  READ ... ROWS` grammar exists in the parser as of the ROWS/TERMINAL
  work above, but this bundle-driven scaffold deliberately still emits
  its own hand-rolled block rather than that syntax; see this section's
  own note above); a multi-row SQL FETCH gets real `ROWS (...)` sugar
  via `_sql_rows_directive` (`_sql_wants_rows` decides single vs. multi).
  Values render through `_bundle_rendered_value`: numeric-family
  `FieldSpec` categories render bare, everything else quoted and escaped.
- **`_read_body`'s `WHEN OTHER` branch also replicates the source `AT END`
  clause's own constant-valued statements**, not just the FILE STATUS
  field (`_replicated_at_end_statements`, via `_is_safe_literal_source`
  for MOVE and `_replicated_set_lines` for SET): the splicer replaces the
  *whole* READ statement (see `splicer/orchestrator.py`'s own module
  docstring), which deletes the real `AT END MOVE "Y" TO WS-EOF`
  idiom along with it — a mock that moves only the FILE STATUS field never
  flips the program's own application-level EOF flag, so its `PERFORM ...
  UNTIL WS-EOF = ...` loop never terminates (an infinite loop, found via a
  real Docker CI run against `examples/fixtures/FIXTUREDEMO`, not by
  `mockymock lint`, which is static and cannot see a splice-time no-op).
  **Both spellings of that idiom are covered**: the literal `MOVE`, and
  the condition-name `SET WS-FIN-FICHIER TO TRUE` against an `88`
  (`_CONSTANT_SET_TYPES` = `TRUE`/`FALSE`). SET was the later fix — it
  parses to a `SetStatement`, not a `MoveStatement`, so the original
  MOVE-only replication silently skipped it and shipped a `WHEN OTHER`
  carrying nothing but the FILE STATUS move and a TODO comment, hanging
  every generated scenario for any program using the condition-name
  spelling. A `SET` is skipped (leaving the TODO to flag it) when its
  `set_type` is not a constant (`TO` an identifier, `UP_BY`, `DOWN_BY`)
  or when it carries additional `groups` — a multi-group `SET A TO TRUE B
  TO FALSE`, where replicating only the first group would be a silent
  *partial* replication, worse than none.
  Whether the `WHEN OTHER` branch is emitted at all is gated on the
  *source* `AT END` clause existing, deliberately not on
  `fixture.terminal` alone: a file with no `FILE STATUS` clause (e.g.
  `examples/invupdt/INVUPDT.cbl`'s `INV-FILE`) has `terminal is None`
  correctly (cobol-parser's `_resolve_status_field`), but the program's
  own `AT END` handler still fires every time the sequence exhausts and
  still needs replicating. Only a `MOVE` whose source is a quoted
  string/numeric literal or figurative constant is replicated from the AST
  — never a bare identifier, whose value in the mock's own splice-time
  context isn't the real program's runtime state.
- **When the AST-driven replication comes up empty, the clause's own source
  text is lifted verbatim instead** (`_lifted_at_end_lines`, 2026-09-04).
  The `*> TODO` comment that used to be emitted there is not a visible gap
  so much as a silently hanging test: a reader who leaves it in gets a
  30-second executor timeout with no diagnosis, because the program's own
  loop guard is never set. The lift is a *slice of the program's own
  source* — exactly the text the splice is about to delete — not a
  re-render limited to the shapes an AST walk knows about, which is what
  makes it general enough to cover identifier-sourced MOVEs, `ADD`, `IF`,
  `PERFORM`, and everything else a real `AT END` clause holds.
  `SourceContext` (the normalized lines plus
  `splicer.source_map.collect_boundaries`' statement starts — the SAME two
  inputs the splicer's own `statement_span` uses, so the lifted text cannot
  drift from the deleted text) is threaded from `_cmd_generate` through
  `scaffold_cut`. `_extract_at_end_imperative` locates `AT END` positionally
  with words scanned OUTSIDE quoted literals (so a `DISPLAY "AT END OF
  FILE"` is never mistaken for the clause) and cuts at the first of `NOT AT
  END` / `END-READ` / `INVALID KEY` / `NOT INVALID KEY` / a
  sentence-terminating period (a period followed by whitespace or
  end-of-text — COBOL's own rule, which is also what keeps a numeric
  literal's decimal point from being read as one). A lifted line carries a
  `*>` provenance comment naming the source line, since a generated file a
  human reads should not silently contain code that did not come from the
  fixture data. The `*> TODO` remains the fallback when no `SourceContext`
  was supplied or the clause could not be located.
- **Expectations** render via `_render_expectation(expectation,
  declared_keys, call_count_overrides=None, counted_boundaries=None)`:
  tier 1 (`call_count`) →
  `VERIFY <cat> <key> WAS CALLED n TIMES`, gated on `declared_keys` as
  above, `n` normally `expectation.value` but see `--placeholder`'s
  `call_count_overrides` below; tier 2 (`field_equals`) → `EXPECT <name>
  TO BE <value>`; tier 3 (`stub`) → a `*> STUB EXPECT ...` comment. A
  `"CATEGORY:KEY"`-shaped boundary-level `ref` (`_is_boundary_level_ref`
  detects the colon, since COBOL names never contain one) renders as
  `*> STUB EXPECT <CAT> <KEY>` — the way a MOCK/VERIFY for that boundary
  reads — and is dropped ONLY when this same TESTCASE actually emits a live
  `VERIFY ... WAS CALLED` for it (`_rendered_call_count_refs`, which
  excludes both keys with no MOCK directive of their own and counts demoted
  to a comment by a `--placeholder` downgrade). It used to be dropped
  unconditionally on that "already covered by its own call_count VERIFY"
  reasoning, which is simply false for an OUT-direction boundary: every
  `WRITE:` stub the bundle produced under `--scenarios all` vanished, so
  the analysis knew something the generated `.cut` never said. A `*>`
  comment is inert, so surfacing it can never break the file; dropping it
  opened a gap between what the analysis knew and what reached the file,
  which is the one thing a scaffold must not do. The two-token boundary
  form deliberately does NOT match the stub scanner's data-name grammar
  (`analysis/stub_expectations.py`'s `_STUB_RE`), so `run
  --record-expectations` leaves it alone rather than mistaking `WRITE` for
  a data item — see `analysis.md`'s stub-expectation scanner for how a
  human promotes a real data-name stub comment to an `EXPECT`.
- **Unverified-scenario notes** (`_verification_comment_lines`, 2026-09-04):
  cobol-parser's bundle now carries a `Scenario.verification` verdict --
  whether that scenario's own generated data actually satisfies the branch
  it is named for. A scenario name is a claim; before that verdict existed
  the only way to check it was `mockymock run --trace` on every case. An
  `unverified` verdict renders as a `*> UNVERIFIED:` comment block directly
  above the affected TESTCASE, listing each non-satisfied field verdict and
  each path gap. A `verified` scenario gets nothing -- a note on every case
  would be noise and would train readers to skip the ones that matter -- and
  a bundle with no `verification` key at all (an older v1 bundle) is read as
  "no verdict recorded", never as unverified.
- **Lint gate**: `tests/integration/test_generate_with_data_lint_gate.py`
  generates a `.cut` for every corpus program across all three
  `--scenarios` modes (happy/branches/all) and asserts `mockymock lint`
  (via `cli.checks.run_static_checks`, Docker-free) finds zero problems —
  "a generator that emits a refusable `.cut` is worse than none."

### `--rows` / `--placeholder` on the bundle-driven scaffold (unify-with-data Task 4)

`scaffold_cut`'s fourth parameter, `placeholder_keys: frozenset[tuple[str,
str]] = frozenset()` (bundle-side string category paired with the
fixture's own key, e.g. `("READ", "ORDER-FILE")` — matching how the CLI
uppercases `--placeholder CATEGORY:KEY`'s category but leaves the key
case-sensitive), only has an effect with a bundle; without one every site
already gets a placeholder body. `--rows N` doesn't touch `generator.py`
at all — it maps to `DataGeneratorOptions(rows=N)` on the
`ProgramFixtureGenerator` construction in `cli/main.py` (`_cmd_generate`'s
`--with-data` branch, mirroring `_cmd_fixtures`), so by the time a bundle
reaches `scaffold_cut` its row counts are already baked in exactly like
`--fixtures FILE`'s are — hence `--rows` combined with `--fixtures` is a
clean CLI-level rejection (source of truth: `mockymock/cli/main.py`, not
this module).

**The downgrade** (`_bundle_directive_for`/`_bundle_directive_for_group`):
a fixture named by `placeholder_keys` gets its body stripped of seeded
data but stays MOCKED — never dropped to nothing, since an unmocked
reachable site is a refusal, not a scaffolding choice. For every category
whose ordinary body carries no loop-termination machinery
(OPEN/CLOSE/START/UNLOCK/DELETE's status-only body, CALL/DYNCALL/ACCEPT/
CICS/DLI, a single-row SQL fixture), the downgrade reuses the ordinary
bundle-less placeholder body (`_placeholder_body_for`, factored out so
the bundle-driven and bundle-less paths can never drift). Two categories
get a DEDICATED downgrade instead, because their non-downgraded body is
what makes the program's own loop actually terminate, and the
runnable-by-construction invariant covers every generated `.cut`, not
just the no-`--placeholder` ones:

- **READ**: downgrades to `_read_exhaustion_lines(...)` — the exact same
  helper `_read_body` uses for its own `WHEN OTHER` branch AND for an
  entirely empty `sequence` (a `--rows 0` bundle, or one of cobol-parser's
  own "empty input" scenario family fixtures) — an "immediately at end"
  body (`fixture.terminal`'s status MOVE(s) plus any safely-replicated
  `AT END` MOVEs), never an empty one. An empty downgraded body would
  silently drop the program's own EOF-flag idiom and hang its `PERFORM
  ... UNTIL <eof-flag>` loop forever — the exact class of bug commit
  `3ad3378` fixed for the ordinary multi-row case, closed here for the
  zero-row and downgraded cases too.
- **SQL**, only when this fixture would otherwise have used `ROWS` sugar
  (`_sql_wants_rows`): downgrades to `_SQL_ROWS_EXHAUSTED_BODY` (`["MOVE
  100 TO SQLCODE"]`, mirroring `splicer/injector.py`'s own hardcoded
  `MOCK SQL ... ROWS` exhausted-branch value), not the ordinary SQL
  placeholder's `MOVE 0 TO SQLCODE` (permanent "more rows available"),
  which would hang a `PERFORM UNTIL SQLCODE = 100` cursor-fetch loop the
  same way an empty READ body would.

**VERIFY recompute** (`CallCountOverride`, fix round 2): a downgrade that
changes what a mock body actually does at runtime can also change how
many times the program actually reaches it — a downgraded READ signals
EOF on its very first call, so a `PERFORM ... UNTIL <eof-flag>` loop
calls it exactly once, not the bundle's original un-downgraded sequence
length. Rendering the bundle's stale original count would pin a `VERIFY
... WAS CALLED N TIMES` the generated file cannot itself satisfy — the
runnable-by-construction invariant covers assertions too, not just mock
bodies. `_bundle_directive_for`/`_bundle_directive_for_group` compute a
`CallCountOverride(count=1)` for a downgraded READ that still carries a
real termination signal (`fixture.terminal` or a replicated `AT END`
MOVE/SET) and for a downgraded SQL-ROWS fixture unconditionally (its body is
always an unconditional literal MOVE, no replication gap possible); when
a downgraded READ's exhaustion body carries NO termination signal at all
(no `FILE STATUS` field and nothing `_replicated_at_end_statements` could
safely replicate), `CallCountOverride(demote_reason=...)` instead — the
real count is not knowable by construction. `_bundle_mock_directives`
collects these per `(category, key)` into `call_count_overrides` (same
seam that decided each body, so `_render_expectation` never re-derives
the downgrade decision); `_render_expectation` renders `override.count`
in place of `expectation.value` when present, or — for a `demote_reason`
— a `*>` comment instead of a `VERIFY` line at all: `*> VERIFY <directive>
WAS CALLED <count not exact by construction after --placeholder downgrade
-- <reason>>`. `count=1` is exact ASSUMING the program stops reading/
fetching this boundary once its end-of-data signal fires — the same
assumption the rest of this engine already makes about every
program-flow-driven call count; a program that reads the same file/
cursor a fixed number of times unconditionally, ignoring that signal,
would still see a stale count.

**This recompute covers only the downgraded boundary's OWN call count —
it is not a general re-derivation of every VERIFY in the TESTCASE.**
Every other category's call count is program-flow-driven (how many
times the PROCEDURE DIVISION reaches that statement) and is left exactly
as the bundle computed it, even when that count itself depends on how
many times the now-downgraded loop executes — e.g. a `CALL` made once
per row inside the same `PERFORM ... UNTIL <eof-flag>` loop as a
downgraded `READ`. A `--placeholder`-downgraded READ that now signals
EOF on call 1 makes that loop body (and anything it calls) run far fewer
times than the bundle's original, un-downgraded sequence length assumed
— but nothing recomputes the `CALL`'s own `VERIFY ... WAS CALLED N
TIMES` to match. This is inherited behavior, not new here: every in-loop
call count was already heuristic (derived from the bundle's generated
sequence length, not the downgraded body), `--placeholder` just makes it
easier to reach in practice. Review the VERIFYs on any other boundary
inside the same loop as a downgraded one before trusting the generated
file.

Deliberately NOT covered by any of this: `--rows N` combined with
`--scenarios all`'s fixed "empty input" family, which pins its own
sequence length to 0 on the cobol-parser side regardless of `--rows` (see
`cobolparser.generators.scenarios._empty_input_scenario`) — `--rows`
changes the generator's *default* row count, not a scenario family that
deliberately overrides it.

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
- [analysis](analysis.md) — `stub_expectations.py`'s raw-text scan for `*> STUB EXPECT` comments
- [report](report.md) — `record_rewrite.py`, which rewrites a stub comment into a real `EXPECT` line
