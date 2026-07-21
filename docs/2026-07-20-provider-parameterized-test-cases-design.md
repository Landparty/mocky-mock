# mockymock — `PROVIDER` Parameterized Test Cases

Date: 2026-07-20
Status: proposed

## Motivation

A `TESTCASE` that needs to exercise the same paragraph against many
input/output pairs — e.g. a state-abbreviation lookup, a discount-code
table, a validation routine's boundary cases — today requires N
hand-written, nearly-identical `TESTCASE` blocks differing only in a
couple of `MOVE`/`EXPECT` values. Repetitive to write and easy to let
drift out of sync (a shared bug fix applied to 9 of 10 copies). This is
the same "DSL/authoring ergonomics" gap flagged in the 2026-07-06
readiness audit's Finding 6, and mirrors a well-worn pattern in other
test frameworks (pytest's `@pytest.mark.parametrize`, JUnit5's
`@ParameterizedTest`, Cucumber's `Examples:` tables).

## Scope

**In scope:**
- A `PROVIDER <name>` block — suite-level, sibling of `TESTCASE` — holding
  a `HEADER` (column names) and one or more `ROW`s (positional values).
- `TESTCASE "..." [TAGS ...] USING PROVIDER <name>` binding a test-case
  template to a provider.
- Parse-time expansion of a provider-bound `TESTCASE` into one ordinary
  `MockTestCase` per row. `{ColumnName}` placeholders are substituted in
  that case's `MOVE` values and `EXPECT` values only.
- A deterministic naming scheme (`"<name> [row <n>: <first column
  value>]"`) and per-row `.line` attribution (points at the `ROW` line,
  not the shared `TESTCASE` header).

**Explicitly out of scope** (considered, deferred):
- Placeholder substitution inside `MOCK` bodies. Mock bodies stay
  verbatim, opaque COBOL text — today's invariant. Revisit only if a real
  need for per-row mock *behavior* (not just per-row assertions) shows up;
  templating currently-opaque free-form COBOL text is a new parsing risk
  for a need not yet demonstrated.
- Placeholder substitution in `MOVE` targets, `EXPECT` data-names,
  `PERFORM` target/thru, or `VERIFY` key/expectation. No clear use case,
  and templating a *target* or *key* name would vary the case's compiled
  shape per row instead of just its data — a bigger, unrequested change.
- Fuzzy/prefix `--case` selection for "all rows of a provider" in one
  flag. v1 requires the exact generated name, or `--tag` for the whole
  family. Documented as a known consequence, not solved (YAGNI).
- A single-compiled-loop/`OCCURS`-table execution model, where one
  compiled test case loops over an in-line COBOL table instead of
  becoming N separate cases (considered, rejected — see Alternatives).
- CSV/external-file-sourced provider rows. Rows are only ever inline
  `ROW` lines in the `.cut` file for v1.

## Design

### Grammar

```
TESTSUITE "..."

PROVIDER StateNames
    HEADER "Abbreviation", "Name"
    ROW "AZ", "Arizona"
    ROW "KY", "Kentucky"
    ROW "XX", "*Undefined*"

TESTCASE "lookup state" USING PROVIDER StateNames
    MOVE {Abbreviation} TO WS-STATE-CODE
    PERFORM LOOKUP-STATE
    EXPECT WS-STATE-NAME TO BE {Name}
```

- `PROVIDER <name>` — bare identifier, same charset as a paragraph name
  (`[A-Za-z0-9][A-Za-z0-9-]*`), consistent with how `PARAGRAPH`/`SECTION`
  mock keys are already bare COBOL names in this grammar.
- `HEADER`/`ROW` take quoted, comma-separated fields, reusing the
  existing quote-aware comma-splitter (`_split_top_level`) already used
  by `MOCK SQL "..." ROWS`. Every `ROW` must have exactly as many values
  as `HEADER` has columns — checked at parse time; a mismatch is a
  `CutParseError` naming the line and both counts.
- A `PROVIDER` block needs a `HEADER` before any `ROW`; a `ROW` before
  `HEADER` is a parse error.
- A `PROVIDER` with zero `ROW` lines is a parse error (mirrors the
  existing empty-`ROWS`-block rule), detected when the block closes
  (next `PROVIDER`/`TESTCASE`/EOF) — same timing pattern as the
  unterminated-`MOCK` check at EOF.
- Duplicate `PROVIDER` name in one suite → `CutParseError` naming both
  lines (mirrors the "one `TESTSUITE`" / "duplicate `MOCK`" pattern).
- `TESTCASE "..." [TAGS ...] USING PROVIDER <name>` — extends
  `_TESTCASE_RE` with an optional trailing clause. Referencing an
  undeclared/mistyped provider errors immediately at that line —
  providers must be declared **before** they're referenced (no forward
  references; consistent with the parser's single-pass, no-lookahead
  design).

### AST model additions (`model.py`)

```python
@dataclass
class DataProvider:
    name: str
    header: list[str]
    rows: list[list[str]]
    row_lines: list[int]   # 1-based .cut line of each ROW, parallel to rows
    line: int = 0          # 1-based .cut line of the PROVIDER header
```

No new field on `MockTestCase`/`MockTestSuite` — see Expansion below for
why this stays purely a parser-internal concept.

### Expansion (the core mechanism)

`parse_cut()` performs the provider→cases expansion as its last step,
before returning. For each provider-bound `TESTCASE`, it produces **one
ordinary `MockTestCase` per row** (mocks, `PERFORM` target/thru, `TAGS`,
and `VERIFY`s copied unchanged into every row) and replaces the template
case in `suite.test_cases` with that list, in row order.

`{ColumnName}` tokens (`\{([A-Za-z][A-Za-z0-9-]*)\}`) are substituted
inside each `MOVE`'s value and each `EXPECT`'s expected-value string,
wherever they appear in that text (not just whole-value matches, so
`EXPECT WS-MSG TO BE "State: {Name}"` works too, not only
`EXPECT WS-STATE-NAME TO BE {Name}`). A `{Foo}` token that doesn't match
any of the provider's `HEADER` columns is a parse-time `CutParseError`
naming the real column names. A `MOVE`/`EXPECT` value with no placeholder
at all is left untouched and simply repeated identically across every
generated row — expected, for a field that's fixed regardless of which
row is running.

**This is the load-bearing design choice:** analysis, splicer, runtime,
report, and every CLI flag (`--case`, `--tag`, `--coverage`,
`--json-report`, `--junit-xml`) never learn `PROVIDER` exists — after
`parse_cut()` returns, they see only ordinary `MockTestCase` objects,
exactly as if N `TESTCASE`s had been hand-written. Zero new concepts
leak past the parser, and zero downstream modules need to change.

A plain `TESTCASE` with no `USING PROVIDER` is completely untouched —
`{...}`-shaped text in it is never scanned or substituted. This is a
strict backward-compatibility guarantee: no existing `.cut` file's
behavior changes.

### Naming & line attribution

Each generated case is named:

```
"<original name> [row <n>: <first column's value>]"
```

e.g. `"lookup state [row 1: AZ]"`, `"lookup state [row 3: XX]"`. The row
index guarantees uniqueness even when two rows share the same first
value; this naming is applied unconditionally whenever `USING PROVIDER`
is used, even for a single-row provider (no special-casing "1 row means
don't rename").

Its `.line` is set to that row's own `ROW` line (from
`DataProvider.row_lines`), not the shared `TESTCASE` header — better for
editor "jump to failing case" navigation (`mockymock collect --json`,
the VS Code extension) than pointing every row at the same line.

One consequence, documented rather than solved in v1: `--case "lookup
state"` (the un-expanded name) matches nothing once that case is
provider-bound. Select one row with its full generated name, or the
whole family with `--tag`.

### Interaction with existing features

- `MockTestSuite.all_mock_keys()` dedupes by `(category, key)` already —
  identical mocks repeated across every generated row collapse to one
  entry, first-appearance order preserved, no change needed.
- `TallyRegistry`/compile volume: N generated cases compile into the same
  single binary as N hand-written cases would — nothing structurally
  new, just more splice sites.
- `TAGS` are copied onto every generated row unchanged, so `--tag`
  selection covers the whole family "for free."
- `mockymock generate` (scaffolding from static `.cbl` analysis) is
  unaffected — `PROVIDER` is purely a hand-authored `.cut` construct; a
  user can add it to a generated file afterward.

### Relationship to the in-flight `BEFORE-EACH`/`BEFORE-ALL` design

`docs/2026-07-20-before-blocks-and-file-status-design.md` (proposed, not
yet implemented as of this writing) adds its own new suite-level,
pre-`TESTCASE` block keywords. `PROVIDER` and `BEFORE-ALL`/`BEFORE-EACH`
are independent and compose freely (a suite can have both), but whichever
of the two lands second should extend the "what's a valid top-level
construct between `TESTSUITE` and the first `TESTCASE`" parsing switch
the first one introduces, rather than duplicating it.

## Testing

- **Unit**: grammar (`HEADER` before `ROW`, arity mismatch, duplicate
  provider name, empty-provider error, undeclared `USING PROVIDER`
  reference, unknown placeholder token), expansion (row count → case
  count, exact generated names, per-row `.line`, `TAGS`/mocks/`VERIFY`
  inherited unchanged, a value with zero placeholders repeated
  identically), backward compatibility (an existing non-provider
  `TESTCASE` with literal `{...}` text in a `MOVE`/`EXPECT` value is
  never scanned or altered).
- **Integration**: a real GnuCOBOL/Docker example under `examples/` using
  `PROVIDER` to drive a small lookup paragraph across 3+ rows, including
  an "undefined"/default-branch row (matching the `XX` → `*Undefined*`
  shape from the motivating example), proving expansion produces
  genuinely distinct, independently passing/failing compiled test cases
  — not just parsed correctly.

## Docs to update after implementation

- `.okf/dsl.md` — grammar/AST tables, a `PROVIDER` section.
- `README.md` — DSL reference section.
- `docs/2026-07-06-real-world-readiness-audit.md` Finding 6 — mark the
  "repetitive `TESTCASE`s for tabular data" footgun closed (partial:
  `MOCK`-body variance across rows is still unaddressed, see Scope).

## Alternatives considered

- **Single compiled loop over an `OCCURS` table** (one test case,
  `PERFORM VARYING` over row data compiled into `WORKING-STORAGE`) —
  closer to how a COBOL programmer hand-writes table-driven tests, but
  rejected: needs new driver codegen, a new per-iteration pass/fail wire
  protocol in stdout (today's protocol is one `PASS`/`FAIL` line per
  compiled `TESTCASE`), and loses simple per-row `--case`
  selection/reporting. Confirmed with the user before committing to the
  parse-time-expansion design.
- **`ROW ( FIELD = value, ... )` pairs**, matching the existing
  `MOCK SQL "..." ROWS` sugar, instead of `HEADER` once + positional
  `ROW` values — rejected: repeating every field name on every row
  defeats the compactness a parameterization table is for; `HEADER` once
  + positional rows is the entire point (matches the Cucumber
  `Examples:`/CSV-style table shape the motivating example itself uses).
- **Allowing placeholder substitution inside `MOCK` bodies in v1** —
  deferred per explicit confirmation; would require a first templating
  pass over free-form COBOL text that's opaque to the DSL parser today,
  more parsing risk for a need not yet demonstrated.
