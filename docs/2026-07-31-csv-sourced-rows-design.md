# mockymock — CSV-Sourced `ROWS` for `SQL` and `READ` Mocks

Date: 2026-07-31
Status: partially shipped — inline `MOCK READ ... ROWS ( ... )` with an
optional `TERMINAL ( ... )` group landed in the unify-with-data branch
(2026-08-05, see `.okf/dsl.md`'s "`ROWS` cursor sugar" section and
`.okf/log.md`); the `ROWS FROM CSV "<path>"` row-source extension
described below (for both `SQL` and `READ`) remains proposed/unimplemented.

## Motivation

`MOCK SQL "..." ROWS ( FIELD = value, ... ) ( ... ) END-MOCK` already lets a
`.cut` author script a sequence of cursor-fetch results, but only by typing
COBOL literal text inline, and only for `SQL`. Two gaps:

1. A realistic cursor mock (a customer table, a rate schedule) is tabular
   data that's easier to maintain as a spreadsheet than as inline
   `FIELD = value` parens buried in `.cut` text — the same ergonomic gap the
   `PROVIDER` design doc named and partly closed for `MOVE`/`EXPECT` values,
   but explicitly left open for `ROWS`: "CSV/external-file-sourced provider
   rows... Rows are only ever inline `ROW` lines... for v1" (that doc's
   Scope section).
2. `READ` (flatfile) mocks have no sequencing mechanism at all today — one
   static body fires on every `READ` of a mocked file, regardless of which
   call it is. Testing a paragraph that reads N records from a file and
   processes them differently record-by-record requires hand-written
   `IF UT-READ-<FILE>-TALLY = 1 ... ELSE IF ... = 2 ...` chains against an
   internal tally field name the DSL never documents as public API.

This doc adds `ROWS FROM CSV "<path>"` as a second row-source (alongside
today's inline parens) and extends the whole `ROWS` mechanism from
`SQL`-only to `SQL` + `READ`.

## Scope

**In scope:**
- `SQL`: `ROWS FROM CSV "<path>"` alongside the existing inline form. CSV
  keeps a header row (named columns, same `FIELD = value` semantics as
  today, just file-sourced).
- `READ`: `ROWS` support at all, both forms —
  - Inline `ROWS ( FIELD = value, ... )`, same named grammar as `SQL`,
    keyed to the file's record fields instead of SQL host variables.
  - `ROWS FROM CSV "<path>"`, **headerless** — columns map **positionally**
    to the record's elementary (leaf) fields in declaration order. A COBOL
    record's storage *is* the depth-first concatenation of its leaf fields,
    so a positional CSV mirrors a real flat-file dump exactly; a header
    would be redundant against an already-fixed field order. (This is a
    deliberate asymmetry from `SQL`'s named CSV form — confirmed, not an
    oversight: naming columns costs nothing extra when a human types
    `ROWS ( FIELD = value )` inline, but a CSV standing in for a physical
    record dump gains nothing from restating field names that are already
    fixed by the copybook.)
- CSV auto-typing: cell text is plain data (`SMITH`, `100.00`), not COBOL
  literal syntax; mockymock resolves each target field's `PICTURE` and
  decides bare-vs-quoted, validates the value fits, and fails closed
  instead of reproducing COBOL's native silent-corruption behavior on
  overflow (see CSV Value Typing below — every claim there was verified
  against the real GnuCOBOL toolchain, not assumed).
- Row exhaustion: `SQL` keeps today's `SQLCODE = 100`. `READ` reuses the
  existing `FILE-STATUS` `END-OF-FILE` mnemonic (`"10"`) on files that
  declare a status field; files that don't are refused up front (same
  precondition `FILE-STATUS IS` sugar already has).

**Explicitly out of scope (v1):**
- `CALL`/dynamic-`CALL` `ROWS` (either form). Considered and designed —
  exhaustion would hard-fail the run (an extra invocation beyond the
  scripted rows is treated like reaching an unmocked site) — but dropped
  from v1 scope. Noted here so the exhaustion decision doesn't need
  re-litigating if this comes back.
- `ROWS` for `OPEN`/`CLOSE`/`DELETE`/`START`/`UNLOCK`. No demonstrated need;
  these categories don't have an obvious "returns different data each call"
  shape the way `READ` does.
- CSV-sourced `PROVIDER` rows (parameterizing `MOVE`/`EXPECT` values across
  whole generated `TESTCASE`s from a CSV). This is a different feature —
  `PROVIDER` varies test *inputs/assertions*; this doc varies mocked
  *boundary data*. Still open per the original `PROVIDER` doc's deferred
  scope; not addressed here.
- Subscripted CSV column targets (`WS-TABLE(1)`) for either form.
- A record containing `OCCURS` or `REDEFINES` fields in its leaf layout is
  refused for **positional** (`READ` CSV) `ROWS` — flattening either
  correctly needs more than a flat column list, matching the fail-closed
  treatment `reset.py` already gives `OCCURS`-with-`VALUE` children for the
  same structural reason.
- One CSV = one directive's full row sequence. No slicing/subsetting one
  file across multiple directives or test cases.

## Design

### Grammar

```cobol
*> SQL — existing category, new row source (header row = host-variable names)
MOCK SQL "SELECT * FROM CUSTOMERS"
    ROWS FROM CSV "data/customers.csv"
END-MOCK
```
```
CUST-ID,CUST-NAME,CUST-BAL
1001,SMITH,100.00
1002,"O'BRIEN, JR.",250.50
```

```cobol
*> READ — new category support, inline form (named, mirrors SQL's syntax)
MOCK READ CUST-FILE
    ROWS ( CUST-ID = 1001, CUST-NAME = "SMITH", CUST-BAL = 100.00 )
    ( CUST-ID = 1002, CUST-NAME = "O'BRIEN, JR.", CUST-BAL = 250.50 )
END-MOCK

*> READ — CSV form, headerless/positional
MOCK READ CUST-FILE
    ROWS FROM CSV "data/custfile.csv"
END-MOCK
```
```
1001,SMITH,100.00
1002,O'BRIEN JR,250.50
```
(column 1 → the record's first leaf field, column 2 → its second, ...
depth-first through any nested `05`/`10` groups, matching physical layout.)

`FROM CSV "<path>"` is parsed as a third alternative on the existing `ROWS`
keyword (today: `ROWS ( ... ) ( ... )` inline groups). `<path>` resolves
relative to the `.cut` file's own directory — no new CLI flag, consistent
with `.cut` files already being self-contained, author-portable fixtures
(the way `PROVIDER`'s inline rows are literally inline).

### Relaxing the category gate

Today `parser.py` hard-refuses `ROWS` on anything but `MockCategory.SQL`
(the quoted-key regex path, ~line 675: `if m.group("rows") and category is
not MockCategory.SQL: raise CutParseError(...)`). `READ` is a **bare**-key
category, matched by a separate regex (`_MOCK_BARE_RE`) that today has no
`ROWS` suffix at all — extending `READ` needs both regexes' `ROWS` handling
extended, not just relaxing one check. `CALL`/`MQ`/`CICS`/`DLI` stay
refused (mirrors today's message, updated to name `SQL`/`READ` as the
eligible set).

### AST model additions (`model.py`)

`MockDirective` gains a fourth, mutually-exclusive-with-the-other-three
payload:

```python
@dataclass
class CsvRowSource:
    raw_path: str          # exactly as written in the .cut file
    resolved_path: Path    # raw_path resolved against the .cut file's directory
    line: int               # 1-based .cut line of the ROWS FROM CSV directive
    positional: bool         # True for READ (headerless), False for SQL (header row)
    header: list[str] | None  # SQL only; column names in file order. None when positional.
    raw_rows: list[list[str]]  # untyped cell text, one inner list per CSV data row
```

`MockDirective.csv_source: CsvRowSource | None = None`. Exactly one of
`body_lines` (non-empty) / `rows` (not `None`) / `csv_source` (not `None`)
is meaningful per directive — the existing `rows`/`body_lines` mutual
exclusivity just grows a third arm.

**Why the parser stores raw, untyped cell text instead of resolving field
types itself:** `parse_cut()` takes `.cut` text only — no COBOL AST — and
that has to stay true, because `mockymock collect --cut PATH` parses a
`.cut` file with **no `.cbl` argument at all** (see `.okf/cli.md`). Any
signature that makes `parse_cut` depend on an AST either breaks `collect`
or forks its behavior from every other subcommand. So the parser's job
stops at: is this syntactically a `ROWS FROM CSV` directive, does the file
exist, and (for `SQL`'s named form only, since it's the one that
self-describes its width via the header) does every row have exactly as
many cells as the header has columns — the same class of check `PROVIDER`
already does at parse time for its own `HEADER`/`ROW` arity. `READ`'s
positional form can't be arity-checked here at all; nothing in the parser
knows the record's field count. That check moves to splice time.

### Resolution (splice time, where the AST is available)

A new module, `mockymock/analysis/csv_rows.py`, exposes:

```python
def resolve_csv_row_sources(
    suite: MockTestSuite, program: CobolProgram
) -> tuple[dict[int, list[list[tuple[str, str]]]], list[RefusalReason]]
```

Keyed by `id(directive)` (mirroring `orchestrator.py`'s existing
`seen_statement_ids` id-keying pattern) rather than mutating
`MockDirective` in place — this follows the same shape
`analyze_file_status_fields` and `TallyRegistry` already use: compute a
side table once, thread it through as a parameter, leave the parsed model
alone. Called from `checks.py::run_static_checks` alongside
`analyze_file_status_fields`, and its resolved-rows table threaded into
`splice_program` → `build_site_dispatch` exactly the way
`file_status_fields` already is.

For each directive with a `csv_source`:
1. **`SQL` (named):** look up each header column as a WORKING-STORAGE data
   item (new name-indexed lookup — `reset.py` already walks every
   WORKING-STORAGE item for its reset-line logic but never builds a
   name → item index; this adds one). `RETURN-CODE` is special-cased as a
   known numeric special register, not a WORKING-STORAGE lookup.
2. **`READ` (positional):** resolve the file's `FileDescription` (found by
   `directive.key`, the file name — `cobolparser`'s `FileDescription` node
   already carries `.data_records: list[CobolDataItem]`, so file → record
   is a direct link, unlike the record → owning-FD direction the
   before-blocks design doc explicitly scoped out for `WRITE`/`REWRITE`).
   Flatten `.data_records` depth-first to its elementary leaf fields; a
   leaf with an `OCCURS` or `REDEFINES` clause anywhere in the record
   refuses `CSV_RECORD_UNSUPPORTED_SHAPE` for the whole directive. Zip CSV
   columns against leaf fields positionally for **every** row in the file
   (rows are checked independently — a CSV can have inconsistent row
   widths even with no header to compare against); the first row whose
   width doesn't match the leaf-field count refuses `CSV_ARITY_MISMATCH`
   naming that row's line number and both counts.

   **Cross-repo note:** "flatten a record to its ordered, typed leaf
   fields" is a generic COBOL-AST capability, not something specific to
   CSV mocking — a CSV template scaffold (see below) needs the identical
   traversal. Rather than implementing this walk as mockymock-internal
   logic against `cobolparser`'s existing public surface, it should be
   built as a new public `cobolparser` API (tentatively
   `cobolparser.analysis.flatten_record(fd: FileDescription) ->
   list[LeafField]`, `LeafField` carrying at least name + resolved
   PICTURE/usage) and consumed from both mockymock's resolver here and
   the scaffold tool, so the two can never disagree about field order.
   This is new surface `interface-contract.md` doesn't pin today — see
   Open Dependency below. Until it exists, this slice can fall back to a
   mockymock-local implementation as a stopgap, but the shared-API version
   is the intended end state.
3. For every resolved (field, cell) pair: classify the field's `PICTURE`
   via the same numeric/alphanumeric rule `reset.py::_is_numeric` already
   encodes (factor it out for reuse rather than reimplementing), then
   apply the typing table below. An unresolvable field name/position
   refuses `CSV_FIELD_NOT_FOUND`; a group item, `POINTER`/`INDEX` usage, or
   88-level target refuses `CSV_UNTYPEABLE_TARGET` (POINTER/INDEX
   illegality already established empirically elsewhere in this codebase —
   see `reset.py`'s reset-line table).
4. `READ` directives additionally require the target file to declare a
   `FILE STATUS` field (reuses the existing `UNRESOLVED_FILE_STATUS_TARGET`
   refusal) — needed so exhaustion has somewhere to signal `"10"`. This
   applies to **both** `READ ROWS` forms (inline and CSV), not just CSV.

Once resolved, the output is the *exact same shape* `MockDirective.rows`
already has for inline `ROWS`. `injector.build_rows_block` never learns a
CSV was involved — `build_site_dispatch` picks whichever of
`directive.rows` (inline) or the resolved-rows table (CSV) applies before
calling it, same as it already picks `file_status_fields.get(...)` today.

### CSV Value Typing

Every rule below was verified by compiling throwaway COBOL against the
real `mockymock-cobc` container (`cobc -free`, GnuCOBOL 3.2), not assumed:

| Cell | Target PIC | Emitted | Basis |
|---|---|---|---|
| `SMITH` | `PIC X(20)` | `MOVE "SMITH" TO CUST-NAME` | alphanumeric → quoted |
| `100.00` | `PIC 9(5)V99` | `MOVE 100.00 TO CUST-BAL` | numeric → bare |
| `123.45` → `PIC 9(3)V99 COMP-3` | — | `MOVE 123.45 TO field` | verified: `COMP-3` with an explicit `PICTURE` takes an ordinary numeric-literal `MOVE`, identical to `DISPLAY` usage — no special case needed |
| *(empty)* | alphanumeric | `MOVE SPACES TO field` | verified: `MOVE "" TO X` **compiles** (`cobc` emits `warning: alphanumeric literal has zero length; a SPACE will be assumed`) and is runtime-equivalent to space-filling the whole field. We emit the explicit `MOVE SPACES` form instead of relying on that compiler leniency. |
| *(empty)* | numeric | `MOVE 0 TO field` | `MOVE 0 TO <numeric-PIC>` needs no compiler-leniency check — it's the same literal `reset.py`'s own numeric reset lines already emit throughout this codebase |
| `O'BRIEN, JR.` (embedded `"`) | alphanumeric | `MOVE "O""BRIEN, JR." TO field` | verified: doubled-quote escaping round-trips correctly at runtime (`[O"BRIEN, JR.        ]` observed) — same technique `driver.py::_display_text` already uses for `DISPLAY` literals, now reused for `MOVE` literals |

**Refused, not silently handled** (also verified empirically):
- **Value wider than its target PIC.** `MOVE "HELLO WORLD" TO` `PIC X(3)`
  truncates from the **right**, keeping the leftmost characters (`HEL`).
  `MOVE 123456 TO` `PIC 9(3)` truncates from the **left**, keeping the
  *rightmost* digits (`456`) — **opposite direction from the alphanumeric
  case**. Silently reproducing either is a real corruption trap for a CSV
  author who doesn't realize a target field is narrower than their data;
  we refuse (`CSV_VALUE_TOO_WIDE`) instead of emitting a `MOVE` that would
  compile clean and misbehave.
- **Negative value into an unsigned `PIC 9`.** Verified: `MOVE -5 TO` an
  unsigned `PIC 9(3)` compiles and silently stores the absolute value
  (`005`, sign dropped) — no warning at all, unlike the empty-literal case.
  Refused (`CSV_SIGN_MISMATCH`) rather than reproduced.
- Group-item targets, `USAGE POINTER`/`INDEX` targets, 88-level targets —
  `CSV_UNTYPEABLE_TARGET` (see Resolution step 3 above).

### Interaction with existing features

- **`FILE-STATUS IS` sugar is structurally unreachable inside a `ROWS`
  body**, by construction, not by a new check: `parser.py`'s in-mock-body
  loop tries the row-pattern match (`_ROW_RE`) before the
  `FILE-STATUS`-line pattern whenever `in_mock.rows is not None`, so a
  `FILE-STATUS IS ...` line inside a `ROWS` block hits "malformed ROWS
  row" first. A `ROWS`-based `READ` mock always gets the automatic
  `"00"`-on-match / `"10"`-on-exhaustion pair (see below) and cannot
  override individual rows' status codes via `FILE-STATUS IS` — documented
  limitation, not a bug to fix here.
- **`build_site_dispatch`'s existing file-status preamble
  (`injector.py` ~lines 95-103) must become conditional.** Today, for any
  `FILE_STATUS_CATEGORIES` directive, it unconditionally emits
  `MOVE "00" TO <status-field>` (plus any `FILE-STATUS IS` override)
  *before* the directive's body, once per dispatch. That's correct for an
  ordinary body (fires once per statement execution) but wrong once `READ`
  gets `ROWS`: status needs to vary **per row** (`"00"` on a matched row,
  `"10"` once exhausted), not once per dispatch regardless of which row
  fired. Fix: skip the existing preamble when `directive.rows is not None
  or directive.csv_source is not None`; the generalized `build_rows_block`
  (below) owns file-status emission per-branch instead.
- **`build_rows_block` generalizes from `SQL`-only to category-aware:**

  ```python
  def build_rows_block(
      tally_name: str,
      rows: list[list[tuple[str, str]]],
      category: MockCategory,
      file_status_field: str | None = None,
  ) -> list[str]:
  ```

  `SQL` trailer unchanged (`MOVE 0 TO SQLCODE` / `MOVE 100 TO SQLCODE`).
  `READ` trailer: `MOVE "00" TO <file_status_field>` on a matched row,
  `MOVE "10" TO <file_status_field>` on exhaustion (`file_status_field` is
  guaranteed non-`None` here — the refusal gate already required the file
  to declare one). The per-row `EVALUATE TRUE` / `WHEN tally = N` structure
  itself needs no change — it was already category-agnostic; only the two
  hardcoded `SQLCODE` trailer lines were `SQL`-specific.
- `TallyRegistry`, `MockTestSuite.all_mock_keys()` dedup, and the outer
  `EVALUATE UT-CURRENT-CASE` dispatch in `build_site_dispatch` are all
  already category-agnostic and need no changes.

## Implementation slices

Each independently testable, in dependency order:

1. Generalize `build_rows_block`'s exhaustion trailer to be category-aware
   and relax the parser gate for `READ`'s **inline** `ROWS` form only (no
   CSV yet). Includes the `build_site_dispatch` file-status-preamble fix.
   Smallest slice; `READ` gets `ROWS` at all, shippable on its own.
2. `ROWS FROM CSV` for `SQL` — extends the already-proven mechanism with
   the new parser-level file-reading/arity-checking and the splice-time
   typing/refusal resolution pass (`csv_rows.py`).
3. `ROWS FROM CSV` for `READ` — positional mapping, leaf-field flattening,
   `OCCURS`/`REDEFINES` guard. Reuses slice 2's typing/refusal
   infrastructure; saved for last because it's the most novel piece and
   carries the open `cobolparser` dependency noted below.

## Testing

- **Unit:** `SQL` CSV header/arity mismatch (mirrors `PROVIDER`'s existing
  arity test); missing CSV file (parse-time `CutParseError`); `READ`
  positional column-count mismatch against a stubbed record layout;
  typing-table decisions (bare/quoted/`SPACES`/`0`) for each PIC shape in
  the table above, via a fake resolver fixture; every refusal path
  (`CSV_FIELD_NOT_FOUND`, `CSV_UNTYPEABLE_TARGET`, `CSV_VALUE_TOO_WIDE`,
  `CSV_SIGN_MISMATCH`, `CSV_ARITY_MISMATCH`, `CSV_RECORD_UNSUPPORTED_SHAPE`,
  `READ ROWS` with no declared `FILE STATUS` field); path resolution
  relative to the `.cut` file.
- **Integration:** a real Docker/GnuCOBOL example under `examples/`
  proving, compiled and run (not just parsed): a `READ`-`ROWS`-from-CSV
  test case that consumes N records across successive `READ`s and asserts
  on each; a `READ` exhaustion case hitting `FILE STATUS = "10"`; a `SQL`
  `ROWS FROM CSV` cursor-fetch-loop test proving CSV-vs-inline `ROWS`
  produce identical compiled behavior.

## Companion idea: CSV template scaffold (not in this doc's scope)

The biggest remaining ergonomic gap: nothing in this design generates a
starter CSV. An author still has to already know the SQL cursor's host
variable names, or the flat file's field count and order, before they can
fill one in. The natural fix mirrors `mockymock generate`'s existing
pattern (AST introspection → scaffolded starter artifact, today a `.cut`
file): a companion command that emits a pre-shaped CSV — header row +
one placeholder data row for `SQL`, one placeholder row (no header) for
`READ` — directly from the cursor's/record's own layout.

Not designed here because it depends on the cross-repo capability noted
above and belongs, structurally, next to `generator.py`/`scaffold_cut`
rather than inside this doc's `csv_rows.py` resolver. Tracked as a
fast-follow, not a blocker for the rest of this design.

### Open dependency: `cobolparser` leaf-field enumeration

Both the `READ` resolver (Design → Resolution, step 2) and the scaffold
idea above need "flatten a record/cursor to its ordered, typed leaf
fields." The user is independently planning to add this to `cobolparser`.
Consequence for this doc's phasing: slice 3 (`READ`'s CSV form) can start
against a mockymock-local stopgap implementation, but should switch to the
shared `cobolparser` API once it lands, rather than the two drifting
apart. This dependency is *not yet scoped* — no shape, timeline, or
`interface-contract.md` entry exists for it as of this writing.

## Docs to update after implementation

- `.okf/dsl.md` — grammar tables, new `ROWS FROM CSV` section, `READ`
  added to the `ROWS`-eligible category list.
- `.okf/splicer.md` — `build_rows_block` generalization, the file-status
  preamble conditional-skip fix, the new `csv_rows.py` resolution pass.
- `README.md` — DSL reference section.
- `.okf/log.md` — dated entry once implemented.

## Alternatives considered

- **Threading the COBOL AST directly into `parse_cut()`** so CSV typing
  could be resolved in one pass — rejected: `mockymock collect` parses a
  `.cut` file with no `.cbl` argument at all, so any AST-dependent
  parameter either breaks `collect` or forks parser behavior by caller.
  Confirmed by reading `cli.md`'s subcommand table, not assumed.
- **CSV-only entry for `READ` `ROWS`** (no inline parenthesized form) —
  rejected: `injector.build_rows_block`'s dispatch structure turned out to
  already be category-agnostic (verified by reading `injector.py`
  directly), so restricting `READ` to CSV-only would have been *more*
  special-casing than just generalizing the inline form too.
- **Mutating `MockDirective.rows` in place during a post-parse resolution
  pass** — rejected in favor of a separate `id(directive)`-keyed resolved
  table threaded through as a parameter, matching the existing
  `file_status_fields`/`TallyRegistry` pattern (compute once, thread
  through, leave the parsed model alone).
- **Reproducing raw COBOL `MOVE` truncation/sign-drop behavior silently**
  (i.e., just emit the `MOVE` and let `cobc` do whatever it does) —
  rejected in favor of fail-closed refusal once the asymmetric truncation
  direction and silent sign-drop were confirmed empirically; matches this
  codebase's fail-closed posture everywhere else (refusal gates, `WHEN
  OTHER` traps, `FILE-STATUS` malformed-input handling).
- **`CALL`/dynamic-`CALL` `ROWS`** — designed (hard-fail-on-exhaustion,
  matching the "reached from unmocked test case" trap style) but dropped
  from v1 scope; see Scope.
