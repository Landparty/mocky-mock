# CSV-Sourced `ROWS` for `SQL` and `READ` Mocks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ROWS FROM CSV "<path>"` as a second row-source for `MOCK SQL ... ROWS` (alongside today's inline parens) and extend the whole `ROWS` mechanism from `SQL`-only to `SQL` + `READ`, per `docs/2026-07-31-csv-sourced-rows-design.md`.

**Architecture:** Three independently-shippable slices. Slice 1 generalizes the existing `ROWS` codegen (`build_rows_block`/`build_site_dispatch`) to be category-aware and gives `READ` its own inline `ROWS ( ... )` grammar — no CSV yet. Slice 2 adds `ROWS FROM CSV "<path>"` parsing + a new splice-time resolver (`mockymock/analysis/csv_rows.py`) for `SQL`'s named-column form. Slice 3 extends that resolver to `READ`'s headerless/positional form (FD record → flattened leaf fields).

**Tech Stack:** Python 3.11+, `cobolparser` (editable sibling checkout, pinned at `4db83941dccefbf3d185d02a518378c37c392d46` in `pyproject.toml` — verified this commit already has the FD-clause metadata tagging and `PictureClause` digit fields this plan depends on, so no pin bump is needed), GnuCOBOL 3.2 via the `mockymock-cobc` Docker container, pytest.

## Global Constraints

- One CSV = one directive's full row sequence. No slicing/subsetting one CSV file across multiple directives or test cases.
- `<path>` in `ROWS FROM CSV "<path>"` resolves relative to the `.cut` file's own directory — no new CLI flag.
- `SQL`'s CSV form keeps a header row (named columns, same `FIELD = value` semantics as today). `READ`'s CSV form is headerless: columns map positionally to the record's elementary (leaf) fields in declaration order (depth-first through nested groups).
- CSV auto-typing must fail closed on a value that doesn't fit its target `PICTURE` (`CSV_VALUE_TOO_WIDE`) or a negative value into an unsigned `PIC 9` (`CSV_SIGN_MISMATCH`) — never reproduce COBOL's native silent-truncation/sign-drop behavior.
- `parse_cut()` must keep working from `.cut` text with no `.cbl`/AST dependency — `mockymock collect --cut PATH` parses a `.cut` file with no `.cbl` argument at all (`.okf/cli.md`). CSV typing resolution therefore happens at splice-check time (`checks.py::run_static_checks`), not parse time; the parser's job stops at syntax, file-existence, and (`SQL` only) header/row arity.
- Out of scope for this feature (unchanged from the design doc): `CALL`/dynamic-`CALL` `ROWS`; `ROWS` for `OPEN`/`CLOSE`/`DELETE`/`START`/`UNLOCK`; CSV-sourced `PROVIDER` rows; subscripted CSV column targets (`WS-TABLE(1)`); a CSV template scaffold command.
- A record containing an `OCCURS` or `REDEFINES` field anywhere in its leaf layout is refused (`CSV_RECORD_UNSUPPORTED_SHAPE`) for **positional** (`READ` CSV) `ROWS` — flattening either needs more than a flat column list. A file whose FD declares more than one `01`-level record is refused the same way (v1 supports exactly one record per FD for positional mapping — this is a necessary addition beyond the design doc's own text, since real multi-record FDs are legal, idiomatic COBOL and this is a *shape* limitation, not a lookup failure).
- `READ` directives using `ROWS` (either form) require the target file to declare a `FILE STATUS` field (reuses `UNRESOLVED_FILE_STATUS_TARGET`) — needed so exhaustion has somewhere to signal `"10"`.

## Design decisions resolved during planning (read before starting)

1. **`cobolparser.models.program.CobolFileDescription`/`.data_records` is never populated by the real parser.** Verified empirically (see Task 9): the FILE SECTION parser (`cobolparser/parsers/divisions/data.py`) tags each `01`-level FILE SECTION record with `set_metadata("fd_file_name", <FD's file name>)` instead of constructing a `CobolFileDescription` node at all — that class is only ever instantiated in cobolparser's own unit tests. The correct way to go from a file name to its record is: `program.get_division("DATA")._sections["FILE"].data_items`, filtered by `item.get_metadata("fd_file_name")`. This is genuinely new cobolparser surface for mockymock and gets pinned in `interface-contract.md`/`.okf/integration.md` as part of Task 9, including this correction.
2. **`READ`'s inline `ROWS` grammar mirrors `SQL`'s exactly**: `ROWS` is a suffix on the opening `MOCK READ <key>` line (`MOCK READ CUST-FILE ROWS`), then `( FIELD = value, ... )` lines, then `END-MOCK` — identical mechanics to today's `MOCK SQL "..." ROWS`. (The design doc's own illustrative code block shows `ROWS ( ... )` starting on the line *after* `MOCK READ CUST-FILE`; that formatting contradicts the doc's own prose — "extending READ needs both regexes' ROWS handling extended" describes literally adding the same optional suffix group `_MOCK_QUOTED_RE` already has to `_MOCK_BARE_RE` — and reuses an already-shipped, already-tested mechanism. Task 13 (final) fixes the doc's example to match.)
3. **`ROWS FROM CSV "<path>"` is a body-line pattern**, recognized inside a `MOCK <cat> <key>` body regardless of whether the opening line said `ROWS` — there's no opening-line flag needed since a single line fully determines the directive (no further lines follow it before `END-MOCK`).
4. **Grammar eligibility for `ROWS FROM CSV` tracks resolution capability per slice**: Slice 2's parser gate only accepts `SQL`; Slice 3 widens it to `SQL`/`READ`. This avoids a window where the grammar accepts `MOCK READ ... ROWS FROM CSV` but the resolver doesn't know how to handle it (which would surface as a confusing internal `ValueError` at splice time instead of a clean parse-time refusal).
5. **`build_site_dispatch` keys `has_rows` off `directive.rows is not None or directive.csv_source is not None`** (an attribute check), never off table membership. If `csv_source` is set but `id(directive)` is missing from the resolved table, that's an invariant violation (the refusal gate should have caught it) — **raise**, matching `orchestrator.splice_program`'s existing "the refusal gate should have refused this" `ValueError` idiom, never silently fall back to `body_lines` (which is empty for a CSV directive).
6. **Field-level typing problems are resolved once per column/leaf, not once per (row, cell)**: `CSV_FIELD_NOT_FOUND`/`CSV_UNTYPEABLE_TARGET` describe the *target* (fixed per column), so they're computed once and reused across every row. `CSV_VALUE_TOO_WIDE`/`CSV_SIGN_MISMATCH` describe the *value* (varies per row), so they're computed per (row, cell) and all accumulate. `CSV_ARITY_MISMATCH` stops at the **first** mismatching row (mirrors `PROVIDER`'s existing parse-time arity check, which raises immediately on the first bad `ROW` line rather than continuing).
7. **`reset.py`'s `_is_numeric`/`_is_group`/`_is_filler` become public** (`is_numeric_picture`/`is_group_item`/`is_filler_item`) so `csv_rows.py` can reuse them instead of reimplementing — confirmed no test references the private names directly, so this is a safe mechanical rename.
8. **`mockymock collect` will now fail on a missing/malformed CSV file**, since `parse_cut` validates CSV existence (and, for `SQL`, header/row arity) unconditionally, the same as it already does for `PROVIDER`. Per `.okf/cli.md`, `collect --json` is the VS Code extension's authoritative test-discovery source — a broken CSV path makes every test in that `.cut` file vanish from Test Explorer, not just the one directive. This is the same fail-closed posture `PROVIDER` already established there; documented explicitly rather than left as a surprise.
9. **An elementary item with `OCCURS n TIMES` and its own `PIC` on the same line (`05 OCC-TABLE OCCURS 2 TIMES PIC 9(2).`, no nested child item) sets `occurs_clause` correctly** — spiked directly against the pinned cobolparser commit (not just the group-with-nested-child form used in the original FD spike): `parse_cobol` on a `WORKING-STORAGE` item of exactly this shape returns `occurs=OccursClause(...)` and `pic=9(2)` on the same node. Task 9's `test_read_positional...` fixtures use this exact shape for `OCCFILE`/`OCC-TABLE`; `_has_occurs_or_redefines` can rely on `.occurs_clause is not None` regardless of whether the OCCURS item is a group or an elementary item.

## File Structure

- Modify `mockymock/dsl/model.py` — new `CsvRowSource` dataclass, `MockDirective.csv_source` field.
- Modify `mockymock/dsl/parser.py` — `READ` inline `ROWS` grammar (Slice 1); `parse_cut(text, cut_dir=...)` + `ROWS FROM CSV` grammar + CSV file reading (Slice 2 for `SQL`, Slice 3 widens to `READ`).
- Modify `mockymock/splicer/reset.py` — export `is_numeric_picture`/`is_group_item`/`is_filler_item`.
- Create `mockymock/analysis/csv_rows.py` — `resolve_csv_row_sources` and its helpers.
- Modify `mockymock/splicer/injector.py` — category-aware `build_rows_block`; `build_site_dispatch` gains `csv_rows` param and conditional FILE-STATUS preamble.
- Modify `mockymock/splicer/orchestrator.py` — `splice_program` threads `csv_rows` through.
- Modify `mockymock/analysis/refusal.py` — widen `UNRESOLVED_FILE_STATUS_TARGET`'s trigger.
- Modify `mockymock/cli/checks.py` — `StaticCheckResult.csv_rows`, wire `resolve_csv_row_sources` into the pipeline.
- Modify `mockymock/cli/main.py` — `_cmd_run`/`_cmd_debug` pass `checked.csv_rows` to `splice_program`; `_cmd_collect` passes `cut_dir`.
- New tests: `tests/unit/test_dsl_parser_csv_rows.py`, `tests/unit/test_csv_rows.py`. Modified tests: `tests/unit/test_injector.py`, `tests/unit/test_refusal_file_status.py`, `tests/unit/test_dsl_parser_v2.py` (message-wording assertion stays valid, no change needed — verified in Task 1).
- New integration fixture: `tests/integration/fixtures/read_rows_inline/` (Slice 1). New/extended examples: `examples/custprog/` gains a second test case + `data/customers.csv` (Slice 2); new `examples/custfile/` (Slice 3).
- Docs: `.okf/dsl.md`, `.okf/splicer.md`, `.okf/analysis.md`, `README.md`, `.okf/log.md`, `interface-contract.md`, `.okf/integration.md`, and a correction to `docs/2026-07-31-csv-sourced-rows-design.md`'s own `READ` inline-`ROWS` example (Task 13, final).

---

## Slice 1 — `READ` gets `ROWS` (inline form only)

### Task 1: Parser grammar — `READ` inline `ROWS`

**Files:**
- Modify: `mockymock/dsl/parser.py`
- Test: `tests/unit/test_dsl_parser_csv_rows.py` (new file — houses every grammar test this whole design adds, both inline-`ROWS`-for-`READ` and, later, `ROWS FROM CSV`)

**Interfaces:**
- Consumes: `mockymock.dsl.model.MockCategory`, `MockDirective`, `FILE_STATUS_CATEGORIES` (existing).
- Produces: `_MOCK_BARE_RE` now captures an optional trailing `ROWS` group; `MOCK READ <key> ROWS` opens a directive with `rows=[]` exactly like today's `MOCK SQL "<key>" ROWS` does. Later tasks (2, 3, 4) consume `directive.rows is not None` for `READ` directives.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_dsl_parser_csv_rows.py`:

```python
"""Grammar tests for READ's inline ROWS support and ROWS FROM CSV (both
SQL and READ) -- docs/2026-07-31-csv-sourced-rows-design.md."""

import pytest

from mockymock.dsl.model import MockCategory
from mockymock.dsl.parser import CutParseError, parse_cut


def test_read_rows_parses_each_row_as_field_value_pairs():
    cut = """\
TESTSUITE "read rows"

TESTCASE "reads two customers then exhausts"
    MOCK READ CUST-FILE ROWS
        ( CUST-ID = 1001, CUST-NAME = "SMITH" )
        ( CUST-ID = 1002, CUST-NAME = "O'BRIEN, JR." )
    END-MOCK
    PERFORM MAIN-PARA
"""
    case = parse_cut(cut).test_cases[0]
    mock = case.mocks[0]
    assert mock.category is MockCategory.READ
    assert mock.key == "CUST-FILE"
    assert mock.rows == [
        [("CUST-ID", "1001"), ("CUST-NAME", '"SMITH"')],
        [("CUST-ID", "1002"), ("CUST-NAME", '"O\'BRIEN, JR."')],
    ]
    assert mock.body_lines == []


def test_read_key_is_upper_cased_even_with_rows_suffix():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ cust-file ROWS
        ( X = 1 )
    END-MOCK
    PERFORM MAIN-PARA
"""
    case = parse_cut(cut).test_cases[0]
    assert case.mocks[0].key == "CUST-FILE"


def test_rows_on_a_bare_category_other_than_read_is_rejected():
    cut = """\
TESTSUITE "bad rows"
TESTCASE "open rows"
    MOCK OPEN INFILE ROWS
        ( X = 1 )
    END-MOCK
    PERFORM MAIN-PARA
"""
    with pytest.raises(
        CutParseError, match="ROWS is only supported for MOCK SQL"
    ):
        parse_cut(cut)


def test_rows_on_dynamic_call_bare_form_is_rejected():
    """MOCK CALL <identifier> ROWS -- the bare (dynamic-CALL) spelling of
    CALL -- must be refused the same as any other ineligible bare category;
    CALL/dynamic-CALL ROWS is explicitly out of scope for this feature."""
    cut = """\
TESTSUITE "bad rows"
TESTCASE "dyncall rows"
    MOCK CALL WS-PGM-NAME ROWS
        ( X = 1 )
    END-MOCK
    PERFORM MAIN-PARA
"""
    with pytest.raises(
        CutParseError, match="ROWS is only supported for MOCK SQL"
    ):
        parse_cut(cut)


def test_empty_read_rows_block_is_rejected():
    cut = """\
TESTSUITE "empty rows"
TESTCASE "no rows"
    MOCK READ CUST-FILE ROWS
    END-MOCK
    PERFORM MAIN-PARA
"""
    with pytest.raises(CutParseError, match="no rows"):
        parse_cut(cut)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_dsl_parser_csv_rows.py -v`
Expected: FAIL — `MOCK READ CUST-FILE ROWS` doesn't match `_MOCK_BARE_RE` today (no `ROWS` group), so it falls through to the `line.startswith("MOCK")` branch and raises a "malformed MOCK directive" `CutParseError` instead of parsing.

- [ ] **Step 3: Widen `_MOCK_BARE_RE` and its handler**

In `mockymock/dsl/parser.py`, change:

```python
_MOCK_BARE_RE = re.compile(
    rf"^MOCK\s+(?P<cat>{_BARE_CATS})\s+(?P<key>[A-Za-z0-9][A-Za-z0-9-]*)$"
)
```

to:

```python
_MOCK_BARE_RE = re.compile(
    rf"^MOCK\s+(?P<cat>{_BARE_CATS})\s+(?P<key>[A-Za-z0-9][A-Za-z0-9-]*)"
    rf"(?:\s+(?P<rows>ROWS))?$"
)
```

Then update the quoted-form gate's message (so both gates name the same eligible set) and the bare-form handler. Change:

```python
            category = _resolve_category(m.group("cat"))
            if m.group("rows") and category is not MockCategory.SQL:
                raise CutParseError(
                    f"line {line_no}: ROWS is only supported for MOCK SQL, "
                    f'not MOCK {m.group("cat")}'
                )
```

to:

```python
            category = _resolve_category(m.group("cat"))
            if m.group("rows") and category is not MockCategory.SQL:
                raise CutParseError(
                    f"line {line_no}: ROWS is only supported for MOCK SQL "
                    f'(quoted key) or MOCK READ (bare key), not MOCK '
                    f'{m.group("cat")}'
                )
```

and change the bare-form handler:

```python
        elif (m := _MOCK_BARE_RE.match(line)) is not None:
            if mock_target is None:
                raise CutParseError(
                    f"line {line_no}: MOCK outside TESTCASE/BEFORE-EACH/" f"BEFORE-ALL"
                )
            in_mock = _open_mock(
                MockDirective(
                    category=_resolve_category(m.group("cat"), bare_key=True),
                    key=m.group("key").upper(),
                ),
                line_no,
            )
            in_mock_line = line_no
```

to:

```python
        elif (m := _MOCK_BARE_RE.match(line)) is not None:
            if mock_target is None:
                raise CutParseError(
                    f"line {line_no}: MOCK outside TESTCASE/BEFORE-EACH/" f"BEFORE-ALL"
                )
            category = _resolve_category(m.group("cat"), bare_key=True)
            if m.group("rows") and category is not MockCategory.READ:
                raise CutParseError(
                    f"line {line_no}: ROWS is only supported for MOCK SQL "
                    f'(quoted key) or MOCK READ (bare key), not MOCK '
                    f'{m.group("cat")}'
                )
            in_mock = _open_mock(
                MockDirective(
                    category=category,
                    key=m.group("key").upper(),
                    rows=[] if m.group("rows") else None,
                ),
                line_no,
            )
            in_mock_line = line_no
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_dsl_parser_csv_rows.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Run the full existing DSL parser test suite to confirm no regression**

Run: `python -m pytest tests/unit/test_dsl_parser.py tests/unit/test_dsl_parser_v2.py tests/unit/test_dsl_parser_before_blocks.py tests/unit/test_dsl_parser_composition.py tests/unit/test_dsl_parser_file_status.py tests/unit/test_dsl_tags_lines.py -v`
Expected: PASS. In particular, `test_dsl_parser_v2.py::test_rows_on_non_sql_category_is_rejected` still passes: its `match="ROWS is only supported for MOCK SQL"` is a substring search (`pytest.raises(..., match=...)` uses `re.search`), and the new message `"ROWS is only supported for MOCK SQL (quoted key) or MOCK READ (bare key), not MOCK CALL"` still contains that substring.

- [ ] **Step 6: Commit**

```bash
git add mockymock/dsl/parser.py tests/unit/test_dsl_parser_csv_rows.py
git commit -m "feat(dsl): give READ its own inline ROWS grammar"
```

---

### Task 2: Injector — category-aware `build_rows_block` + conditional FILE-STATUS preamble

**Files:**
- Modify: `mockymock/splicer/injector.py`
- Modify: `tests/unit/test_injector.py` (one existing call site needs updating; new tests added)

**Interfaces:**
- Consumes: `mockymock.dsl.model.MockCategory`, `FILE_STATUS_CATEGORIES` (existing).
- Produces: `build_rows_block(tally_name, rows, category, file_status_field=None) -> list[str]` (signature change — `category` and `file_status_field` are new). `build_site_dispatch`'s FILE-STATUS preamble is now skipped whenever `directive.rows is not None` (this task) or `directive.csv_source is not None` (Task 5 makes the attribute exist; this task's code already checks it defensively via `getattr` — see Step 3 note).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_injector.py`:

```python
def test_rows_block_uses_file_status_trailer_for_read_category():
    lines = build_rows_block(
        "UT-READ-CUST-FILE-TALLY",
        [[("CUST-ID", "1001")], [("CUST-ID", "1002")]],
        MockCategory.READ,
        "WS-CUST-STATUS",
    )
    assert lines == [
        "EVALUATE TRUE",
        "    WHEN UT-READ-CUST-FILE-TALLY = 1",
        "        MOVE 1001 TO CUST-ID",
        '        MOVE "00" TO WS-CUST-STATUS',
        "    WHEN UT-READ-CUST-FILE-TALLY = 2",
        "        MOVE 1002 TO CUST-ID",
        '        MOVE "00" TO WS-CUST-STATUS',
        "    WHEN OTHER",
        '        MOVE "10" TO WS-CUST-STATUS',
        "END-EVALUATE",
    ]


def test_read_rows_dispatch_uses_file_status_trailer_not_sqlcode():
    case = MockTestCase(
        name="c",
        mocks=[
            MockDirective(
                MockCategory.READ,
                "CUST-FILE",
                rows=[[("CUST-ID", "1001")]],
            )
        ],
        perform_target="MAIN-PARA",
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    site = _site(category=MockCategory.READ, label="READ", keys=("CUST-FILE",))
    lines = build_site_dispatch(
        site, suite, TallyRegistry(suite), {"CUST-FILE": "WS-CUST-STATUS"}
    )
    joined = "\n".join(lines)
    assert 'MOVE "00" TO WS-CUST-STATUS' in joined
    assert 'MOVE "10" TO WS-CUST-STATUS' in joined
    assert "SQLCODE" not in joined
    # The old unconditional default-success preamble must NOT ALSO fire --
    # exactly one "00" MOVE (from build_rows_block's own WHEN branch), not
    # two (preamble + rows-block trailer).
    assert joined.count('MOVE "00" TO WS-CUST-STATUS') == 1
```

Update the one existing call site that breaks (2-positional-arg call needs the new required `category` argument):

```python
def test_rows_block_codegens_indexed_when_branches_and_exhaustion():
    lines = build_rows_block(
        "UT-SQL-FETCH-EMP-CURSOR-TALLY",
        [
            [("EMP-NAME", '"SMITH"'), ("EMP-ID", "100")],
            [("EMP-NAME", '"JONES"'), ("EMP-ID", "101")],
        ],
        MockCategory.SQL,
    )
    assert lines == [
        "EVALUATE TRUE",
        "    WHEN UT-SQL-FETCH-EMP-CURSOR-TALLY = 1",
        '        MOVE "SMITH" TO EMP-NAME',
        "        MOVE 100 TO EMP-ID",
        "        MOVE 0 TO SQLCODE",
        "    WHEN UT-SQL-FETCH-EMP-CURSOR-TALLY = 2",
        '        MOVE "JONES" TO EMP-NAME',
        "        MOVE 101 TO EMP-ID",
        "        MOVE 0 TO SQLCODE",
        "    WHEN OTHER",
        "        MOVE 100 TO SQLCODE",
        "END-EVALUATE",
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_injector.py -v -k rows_block or read_rows_dispatch`
Expected: FAIL — `build_rows_block` doesn't accept a 3rd/4th argument yet, and `build_site_dispatch` still hardcodes `SQLCODE` in `build_rows_block`'s call.

- [ ] **Step 3: Generalize `build_rows_block` and `build_site_dispatch`**

In `mockymock/splicer/injector.py`, change the existing module-level import line

```python
from mockymock.dsl.model import FILE_STATUS_CATEGORIES, MockTestSuite
```

to add `MockCategory`:

```python
from mockymock.dsl.model import FILE_STATUS_CATEGORIES, MockCategory, MockTestSuite
```

Then replace `build_rows_block`:

```python
def build_rows_block(
    tally_name: str,
    rows: list[list[tuple[str, str]]],
    category,
    file_status_field: str | None = None,
) -> list[str]:
    """EVALUATE block for a MOCK SQL/READ ... ROWS directive: row N's MOVEs
    fire once `tally_name` (already incremented by the caller before this
    runs, so the first call sees tally == 1) reaches N, followed by the
    category's own success signal; once rows are exhausted, its exhaustion
    signal fires instead. SQL: MOVE 0/100 TO SQLCODE (DB2's real "not
    found" code) -- unchanged from before this generalization. READ:
    MOVE "00"/"10" TO file_status_field (GnuCOBOL's END-OF-FILE code);
    file_status_field is guaranteed non-None here for READ -- the refusal
    gate already requires the file to declare a FILE STATUS field before a
    READ ROWS directive reaches splicing."""
    lines = ["EVALUATE TRUE"]
    for index, row in enumerate(rows, start=1):
        lines.append(f"    WHEN {tally_name} = {index}")
        for field, value in row:
            lines.append(f"        MOVE {value} TO {field}")
        if category is MockCategory.SQL:
            lines.append("        MOVE 0 TO SQLCODE")
        else:
            assert file_status_field is not None, (
                "READ ROWS requires a FILE STATUS field -- the refusal "
                "gate should have required one before this ran"
            )
            lines.append(f'        MOVE "00" TO {file_status_field}')
    lines.append("    WHEN OTHER")
    if category is MockCategory.SQL:
        lines.append("        MOVE 100 TO SQLCODE")
    else:
        assert file_status_field is not None
        lines.append(f'        MOVE "10" TO {file_status_field}')
    lines.append("END-EVALUATE")
    return lines
```

Now update `build_site_dispatch`'s per-branch body. Replace:

```python
        if directive.category in FILE_STATUS_CATEGORIES:
            status_field = file_status_fields.get(directive.key.upper())
            if status_field:
                lines.append(f'                   MOVE "00" TO {status_field}')
                if directive.file_status is not None:
                    lines.append(
                        f'                   MOVE "{directive.file_status}" '
                        f"TO {status_field}"
                    )
        if directive.rows is not None:
            lines.extend(
                f"                   {body}"
                for body in build_rows_block(tally_name, directive.rows)
            )
        else:
            lines.extend(f"                   {body}" for body in directive.body_lines)
```

with:

```python
        has_rows = directive.rows is not None or getattr(
            directive, "csv_source", None
        ) is not None
        status_field = None
        if directive.category in FILE_STATUS_CATEGORIES:
            status_field = file_status_fields.get(directive.key.upper())
            if status_field and not has_rows:
                lines.append(f'                   MOVE "00" TO {status_field}')
                if directive.file_status is not None:
                    lines.append(
                        f'                   MOVE "{directive.file_status}" '
                        f"TO {status_field}"
                    )
        if has_rows:
            if directive.rows is not None:
                rows = directive.rows
            else:
                if id(directive) not in csv_rows:
                    raise ValueError(
                        f"MOCK {directive.describe()} has a CSV row source "
                        f"with no resolved rows -- resolve_csv_row_sources "
                        f"should have refused this before splicing"
                    )
                rows = csv_rows[id(directive)]
            lines.extend(
                f"                   {body}"
                for body in build_rows_block(
                    tally_name, rows, directive.category, status_field
                )
            )
        else:
            lines.extend(f"                   {body}" for body in directive.body_lines)
```

(`getattr(directive, "csv_source", None)` in the `has_rows` line is deliberately defensive **only within this task**: `MockDirective.csv_source` doesn't exist as a field until Task 5's model.py change. Task 5 replaces this `getattr` with a plain `directive.csv_source is not None` once the field exists — see Task 5, Step 3.)

Update `build_site_dispatch`'s signature to accept `csv_rows` (used above) — it doesn't exist as a parameter yet in this task; add it now so the code above type-checks, defaulting to an always-empty dict until Task 5 populates it for real:

```python
def build_site_dispatch(
    site: BoundarySite,
    suite: MockTestSuite,
    registry: TallyRegistry,
    file_status_fields: dict[str, str] | None = None,
    csv_rows: dict[int, list[list[tuple[str, str]]]] | None = None,
    trace: bool = False,
) -> list[str]:
    file_status_fields = file_status_fields or {}
    csv_rows = csv_rows or {}
    lines = ["           EVALUATE UT-CURRENT-CASE"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_injector.py -v`
Expected: PASS (all tests, including the pre-existing ones — `test_omitting_file_status_fields_keeps_todays_exact_output` in particular confirms a directive with no `rows` produces byte-identical output to before this change).

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/injector.py tests/unit/test_injector.py
git commit -m "feat(splicer): generalize ROWS codegen to be category-aware"
```

---

### Task 3: Refusal — require a declared `FILE STATUS` field when `READ` uses `ROWS`

**Files:**
- Modify: `mockymock/analysis/refusal.py`
- Modify: `tests/unit/test_refusal_file_status.py`

**Interfaces:**
- Consumes: `MockDirective.rows`, `.category`, `.file_status` (existing); `MockCategory.READ` (existing).
- Produces: `check_test_case`'s final per-directive loop now also refuses `UNRESOLVED_FILE_STATUS_TARGET` for a `READ` directive using `ROWS` with no declared `FILE STATUS` field, even without explicit `FILE-STATUS IS` sugar.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_refusal_file_status.py`:

```python
def test_read_rows_without_declared_file_status_refuses():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ NO-STATUS ROWS
        ( X = 1 )
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    reasons = _check(cut)
    matches = [r for r in reasons if r.code == "UNRESOLVED_FILE_STATUS_TARGET"]
    assert len(matches) == 1
    assert "NO-STATUS" in matches[0].message


def test_read_rows_with_declared_file_status_does_not_refuse():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ WITH-STATUS ROWS
        ( X = 1 )
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    reasons = _check(cut)
    assert not any(r.code == "UNRESOLVED_FILE_STATUS_TARGET" for r in reasons)
```

(Reuses this file's existing `SOURCE`/`_check` fixture — `WITH-STATUS` declares `FILE STATUS IS WS-STATUS`; `NO-STATUS` doesn't. Both files already exist in `SOURCE`'s `FILE-CONTROL`, so no fixture changes are needed.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_refusal_file_status.py -v -k read_rows`
Expected: FAIL — `check_test_case`'s final loop today only fires when `directive.file_status is not None`; a plain `ROWS` directive with no `FILE-STATUS IS` sugar never reaches the check at all, so `test_read_rows_without_declared_file_status_refuses` finds zero matches instead of one.

- [ ] **Step 3: Widen the trigger condition**

In `mockymock/analysis/refusal.py`, inside `check_test_case`, replace:

```python
    for directive in case.mocks:
        if directive.file_status is None:
            continue
        if directive.key.upper() not in file_status_fields:
```

with:

```python
    for directive in case.mocks:
        needs_file_status = directive.file_status is not None or (
            directive.category is MockCategory.READ and directive.rows is not None
        )
        if not needs_file_status:
            continue
        if directive.key.upper() not in file_status_fields:
```

and update the message so it reads correctly for both trigger paths:

```python
            reasons.append(
                RefusalReason(
                    code="UNRESOLVED_FILE_STATUS_TARGET",
                    message=(
                        f"MOCK {directive.describe()} uses FILE-STATUS IS, "
                        f"or ROWS (which needs FILE STATUS to signal "
                        f"end-of-file), but '{directive.key}' has no FILE "
                        f"STATUS IS <field> clause declared in its SELECT "
                        f"entry -- there is no WORKING-STORAGE field to "
                        f"move the status into"
                    ),
                )
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_refusal_file_status.py -v`
Expected: PASS (all tests, including the three pre-existing ones — `test_check_test_case_defaults_file_status_fields_to_empty` in particular confirms a plain `MOCK OPEN` with no `rows`/`file_status` still produces zero reasons).

- [ ] **Step 5: Run the full refusal test suite to confirm no regression**

Run: `python -m pytest tests/unit/test_refusal.py tests/unit/test_refusal_v2.py tests/unit/test_refusal_file_status.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add mockymock/analysis/refusal.py tests/unit/test_refusal_file_status.py
git commit -m "fix(analysis): require a declared FILE STATUS field for READ ROWS"
```

---

### Task 4: Integration proof — `READ` inline `ROWS` compiles and runs

**Files:**
- Create: `tests/integration/fixtures/read_rows_inline/READROWS.cbl`
- Create: `tests/integration/fixtures/read_rows_inline/READROWS.cut`
- Create: `tests/integration/test_read_rows_inline.py`

**Interfaces:**
- Consumes: `mockymock.cli.main.main` (existing, in-process invocation — never the `PATH` binary, per the stale-global-install gotcha in `.okf/testing.md`).
- Produces: nothing new — this is a pure verification task proving Tasks 1-3 combine correctly against a real GnuCOBOL compile+run, closing out Slice 1 ("shippable on its own").

- [ ] **Step 1: Write the fixture program**

Create `tests/integration/fixtures/read_rows_inline/READROWS.cbl`:

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. READROWS.
      * Proves READ's new inline ROWS support end to end: no real
      * CUSTFILE.DAT needed in the sandbox, no hand-written tally
      * branching in the .cut -- ROWS ( ... ) ( ... ) drives two
      * successive READs, then FILE STATUS "10" ends the loop.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO "CUSTFILE.DAT"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-CUST-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-REC.
           05  CUST-ID        PIC 9(5).
           05  CUST-NAME      PIC X(20).

       WORKING-STORAGE SECTION.
       01  WS-CUST-STATUS     PIC X(2).
       01  WS-EOF             PIC X VALUE "N".
       01  WS-EOF-STATUS      PIC X(2) VALUE SPACES.
       01  WS-REC-COUNT       PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT CUST-FILE.
           PERFORM READ-LOOP UNTIL WS-EOF = "Y".
           CLOSE CUST-FILE.

       READ-LOOP.
           READ CUST-FILE.
           IF WS-CUST-STATUS = "10"
               MOVE WS-CUST-STATUS TO WS-EOF-STATUS
               MOVE "Y" TO WS-EOF
           ELSE
               ADD 1 TO WS-REC-COUNT
           END-IF.
```

`WS-EOF-STATUS` captures the exhaustion status the instant it happens, inside
`READ-LOOP`, before `CLOSE CUST-FILE` ever runs. This matters because `MOCK
CLOSE CUST-FILE END-MOCK` has an empty body, and `CLOSE` is one of
`FILE_STATUS_CATEGORIES` — with no `rows` on that directive, `build_site_dispatch`
still emits its unconditional default-success preamble (`MOVE "00" TO
WS-CUST-STATUS`) when the mock fires. `CLOSE` runs *after* the `PERFORM
READ-LOOP UNTIL ...` loop exits, and `EXPECT`/`VERIFY` run only after the whole
`PERFORM MAIN-PARA` returns (per `driver.py`'s ordering) — so an `EXPECT`
directly on `WS-CUST-STATUS` would observe the `CLOSE` mock's `"00"`, not the
`"10"` the `READ` loop actually exited on. Asserting on `WS-EOF-STATUS`
instead sidesteps that entirely, and is arguably the stronger assertion anyway
(it proves the exhaustion signal was seen at the moment it mattered, not just
that some field happened to hold `"10"` at test-case end).

Create `tests/integration/fixtures/read_rows_inline/READROWS.cut`:

```
TESTSUITE "READROWS inline ROWS"

TESTCASE "reads two customers then exhausts"
    MOCK OPEN CUST-FILE
    END-MOCK
    MOCK READ CUST-FILE ROWS
        ( CUST-ID = 1001, CUST-NAME = "SMITH" )
        ( CUST-ID = 1002, CUST-NAME = "O'BRIEN, JR." )
    END-MOCK
    MOCK CLOSE CUST-FILE
    END-MOCK
    PERFORM MAIN-PARA
    EXPECT WS-REC-COUNT TO BE 2
    EXPECT WS-EOF-STATUS TO BE "10"
    VERIFY READ CUST-FILE WAS PERFORMED 3 TIMES
```

- [ ] **Step 2: Write the integration test**

Create `tests/integration/test_read_rows_inline.py`:

```python
"""Integration proof: READ's inline ROWS (no CSV yet) compiles and runs for
real -- Slice 1 of docs/2026-07-31-csv-sourced-rows-design.md, "shippable
on its own"."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "read_rows_inline"


@requires_docker
def test_read_rows_inline_consumes_records_then_signals_eof(capsys):
    exit_code = main(
        [
            "run",
            str(FIXTURES / "READROWS.cbl"),
            "--cut",
            str(FIXTURES / "READROWS.cut"),
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "CASE 001 START" in out
    assert "FAILURES=0" in out
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `python -m pytest tests/integration/test_read_rows_inline.py -v`
Expected: PASS (Docker daemon confirmed reachable in this environment — real compile + run, not a skip).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/fixtures/read_rows_inline tests/integration/test_read_rows_inline.py
git commit -m "test(integration): prove READ inline ROWS compiles and runs"
```

---

## Slice 2 — `ROWS FROM CSV` for `SQL`

### Task 5: Model + `reset.py` prep + `csv_rows.py` (SQL-only resolution)

**Files:**
- Modify: `mockymock/dsl/model.py`
- Modify: `mockymock/splicer/reset.py`
- Modify: `mockymock/splicer/injector.py` (remove the Task-2 `getattr` shim now that the field exists)
- Create: `mockymock/analysis/csv_rows.py`
- Test: `tests/unit/test_csv_rows.py` (new)

**Interfaces:**
- Consumes: `cobolparser.models.data_items.CobolDataItem`, `ConditionNameItem`, `RenamesItem` (verified surface — see Step 5's citation). `mockymock.analysis.refusal.RefusalReason` (existing).
- Produces: `mockymock.dsl.model.CsvRowSource` (new dataclass), `MockDirective.csv_source: CsvRowSource | None = None` (new field). `mockymock.splicer.reset.is_numeric_picture(item) -> bool`, `is_group_item(item) -> bool`, `is_filler_item(item) -> bool` (renamed from private). `mockymock.analysis.csv_rows.resolve_csv_row_sources(suite, program) -> tuple[dict[int, list[list[tuple[str, str]]]], list[RefusalReason]]` — Task 8 (Slice 3) extends this same function to also handle `READ`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_csv_rows.py`:

```python
"""Unit tests for mockymock.analysis.csv_rows -- resolving MOCK SQL/READ
... ROWS FROM CSV directives against the parsed COBOL AST. SQL-only for
now (Slice 2); READ positional resolution is added in Slice 3."""

from pathlib import Path

from cobolparser import parse_cobol

from mockymock.analysis.csv_rows import resolve_csv_row_sources
from mockymock.dsl.model import CsvRowSource, MockCategory, MockDirective, MockTestCase, MockTestSuite

SQL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CSVSPIKE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-GROUP.
           05  CUST-ID         PIC S9(9) COMP-5.
           05  CUST-NAME       PIC X(10).
           05  CUST-BAL        PIC 9(5)V99.
           05  CUST-FLAG        PIC 9 VALUE 0.
               88  CUST-FLAG-ON VALUE 1.
           05  CUST-PTR         USAGE POINTER.

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _directive(header, raw_rows, row_lines=None) -> MockDirective:
    directive = MockDirective(MockCategory.SQL, "FETCH CUR")
    directive.csv_source = CsvRowSource(
        raw_path="x.csv",
        resolved_path=Path("x.csv"),
        line=1,
        positional=False,
        header=header,
        raw_rows=raw_rows,
        row_lines=row_lines or list(range(2, len(raw_rows) + 2)),
    )
    return directive


def _resolve(directive):
    result = parse_cobol(SQL_SOURCE, filename="csvspike.cbl")
    assert result.success, result.errors
    case = MockTestCase(name="c", mocks=[directive])
    suite = MockTestSuite(name="S", test_cases=[case])
    return resolve_csv_row_sources(suite, result.ast)


def test_resolves_alphanumeric_and_numeric_columns():
    directive = _directive(
        ["CUST-ID", "CUST-NAME", "CUST-BAL"],
        [["1001", "SMITH", "100.00"]],
    )
    table, reasons = _resolve(directive)
    assert reasons == []
    assert table[id(directive)] == [
        [
            ("CUST-ID", "1001"),
            ("CUST-NAME", '"SMITH"'),
            ("CUST-BAL", "100.00"),
        ]
    ]


def test_empty_alphanumeric_cell_becomes_move_spaces():
    directive = _directive(["CUST-NAME"], [[""]])
    table, reasons = _resolve(directive)
    assert reasons == []
    assert table[id(directive)] == [[("CUST-NAME", "SPACES")]]


def test_empty_numeric_cell_becomes_move_zero():
    directive = _directive(["CUST-BAL"], [[""]])
    table, reasons = _resolve(directive)
    assert reasons == []
    assert table[id(directive)] == [[("CUST-BAL", "0")]]


def test_embedded_quote_is_doubled():
    directive = _directive(["CUST-NAME"], [['O"BRIEN']])
    table, reasons = _resolve(directive)
    assert reasons == []
    assert table[id(directive)] == [[("CUST-NAME", '"O""BRIEN"')]]


def test_return_code_is_special_cased_not_looked_up():
    directive = _directive(["RETURN-CODE"], [["4"]])
    table, reasons = _resolve(directive)
    assert reasons == []
    assert table[id(directive)] == [[("RETURN-CODE", "4")]]


def test_unknown_column_refuses_field_not_found():
    directive = _directive(["BOGUS-FIELD"], [["1"]])
    table, reasons = _resolve(directive)
    assert id(directive) not in table
    assert len(reasons) == 1
    assert reasons[0].code == "CSV_FIELD_NOT_FOUND"
    assert "BOGUS-FIELD" in reasons[0].message


def test_group_item_target_refuses_untypeable():
    directive = _directive(["WS-GROUP"], [["1"]])
    table, reasons = _resolve(directive)
    assert id(directive) not in table
    assert reasons[0].code == "CSV_UNTYPEABLE_TARGET"


def test_condition_name_target_refuses_untypeable():
    directive = _directive(["CUST-FLAG-ON"], [["1"]])
    table, reasons = _resolve(directive)
    assert reasons[0].code == "CSV_UNTYPEABLE_TARGET"


def test_pointer_usage_target_refuses_untypeable():
    directive = _directive(["CUST-PTR"], [["1"]])
    table, reasons = _resolve(directive)
    assert reasons[0].code == "CSV_UNTYPEABLE_TARGET"


def test_value_wider_than_alphanumeric_pic_refuses_too_wide():
    directive = _directive(["CUST-NAME"], [["A" * 11]])  # PIC X(10)
    table, reasons = _resolve(directive)
    assert id(directive) not in table
    assert reasons[0].code == "CSV_VALUE_TOO_WIDE"


def test_value_wider_than_numeric_pic_refuses_too_wide():
    directive = _directive(["CUST-BAL"], [["1234567.00"]])  # PIC 9(5)V99
    table, reasons = _resolve(directive)
    assert reasons[0].code == "CSV_VALUE_TOO_WIDE"


def test_negative_value_into_unsigned_numeric_refuses_sign_mismatch():
    directive = _directive(["CUST-BAL"], [["-5.00"]])  # unsigned PIC
    table, reasons = _resolve(directive)
    assert reasons[0].code == "CSV_SIGN_MISMATCH"


def test_negative_value_into_signed_numeric_is_accepted():
    directive = _directive(["CUST-ID"], [["-5"]])  # PIC S9(9) COMP-5, signed
    table, reasons = _resolve(directive)
    assert reasons == []
    assert table[id(directive)] == [[("CUST-ID", "-5")]]


def test_multiple_rows_all_resolve_independently():
    directive = _directive(
        ["CUST-ID", "CUST-NAME"],
        [["1001", "SMITH"], ["1002", "JONES"]],
    )
    table, reasons = _resolve(directive)
    assert reasons == []
    assert table[id(directive)] == [
        [("CUST-ID", "1001"), ("CUST-NAME", '"SMITH"')],
        [("CUST-ID", "1002"), ("CUST-NAME", '"JONES"')],
    ]


def test_no_csv_source_directives_is_a_cheap_noop():
    plain = MockDirective(MockCategory.SQL, "UPDATE X", body_lines=["MOVE 0 TO SQLCODE"])
    result = parse_cobol(SQL_SOURCE, filename="csvspike.cbl")
    suite = MockTestSuite(
        name="S", test_cases=[MockTestCase(name="c", mocks=[plain])]
    )
    table, reasons = resolve_csv_row_sources(suite, result.ast)
    assert table == {}
    assert reasons == []


def test_same_directive_shared_across_cases_is_resolved_once():
    """A directive inherited from BEFORE-EACH/BEFORE-ALL is the SAME
    MockDirective object aliased into every case's mocks list (see
    parser.py's _apply_before_blocks) -- must not be double-processed."""
    directive = _directive(["CUST-ID"], [["1001"]])
    case_one = MockTestCase(name="a", mocks=[directive])
    case_two = MockTestCase(name="b", mocks=[directive])
    result = parse_cobol(SQL_SOURCE, filename="csvspike.cbl")
    suite = MockTestSuite(name="S", test_cases=[case_one, case_two])
    table, reasons = resolve_csv_row_sources(suite, result.ast)
    assert reasons == []
    assert len(table) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_csv_rows.py -v`
Expected: FAIL — `mockymock.analysis.csv_rows` doesn't exist yet; `MockDirective` has no `csv_source` field; `CsvRowSource` doesn't exist.

- [ ] **Step 3: Add `CsvRowSource` and `MockDirective.csv_source` to `model.py`**

In `mockymock/dsl/model.py`, add `from pathlib import Path` to the imports, then add after `DataProvider`:

```python
@dataclass
class CsvRowSource:
    """A `ROWS FROM CSV "<path>"` row source. Mutually exclusive with
    `MockDirective.rows`/`.body_lines` by construction -- the parser routes
    a directive's body to exactly one of the three. The parser's job stops
    at syntax/file-existence/(SQL-only) header arity; splice-time
    resolution (mockymock/analysis/csv_rows.py) does the PICTURE-aware
    typing, since parse_cut() has no COBOL AST to resolve against (see
    docs/2026-07-31-csv-sourced-rows-design.md)."""

    raw_path: str
    """Exactly as written in the .cut file."""
    resolved_path: Path
    """`raw_path` resolved against the .cut file's own directory."""
    line: int
    """1-based .cut line of the ROWS FROM CSV directive."""
    positional: bool
    """True for READ (headerless), False for SQL (header row)."""
    header: list[str] | None
    """SQL only: column names in file order. None when positional."""
    raw_rows: list[list[str]]
    """Untyped cell text, one inner list per CSV data row."""
    row_lines: list[int]
    """1-based line number WITHIN THE CSV FILE of each row in `raw_rows`,
    same index alignment -- needed for CSV_ARITY_MISMATCH messages, which
    name a specific bad row (mirrors DataProvider.row_lines's purpose)."""
```

Then add to `MockDirective` (after the existing `file_status` field):

```python
    csv_source: CsvRowSource | None = None
    """Set only for a `ROWS FROM CSV "<path>"` directive (SQL or READ).
    Mutually exclusive with `rows` and `body_lines` by construction."""
```

- [ ] **Step 4: Rename the three `reset.py` helpers to public names**

In `mockymock/splicer/reset.py`, rename (definitions and every call site within this file):
- `_is_filler` → `is_filler_item`
- `_is_group` → `is_group_item`
- `_is_numeric` → `is_numeric_picture`

(Purely mechanical — four call sites total: two in `reset_lines_for_items`/`_child_value_restores` for `is_filler_item`/`is_group_item`, one in `_elementary_reset` for `is_numeric_picture`, plus the three `def` lines. No behavior change.)

- [ ] **Step 5: Run reset.py's existing tests to confirm the rename didn't break anything**

Run: `python -m pytest tests/unit/test_reset.py -v`
Expected: PASS (unchanged — confirms the rename is behavior-preserving)

- [ ] **Step 6: Create `mockymock/analysis/csv_rows.py`**

```python
"""Resolves `MOCK SQL/READ ... ROWS FROM CSV` directives (mockymock/dsl/
model.py's CsvRowSource) against the parsed COBOL program: for SQL, named
columns resolve against WORKING-STORAGE items; for READ (added in a later
slice), positional columns resolve against the target file's flattened
record layout. Produces the exact same shape MockDirective.rows already
has for inline ROWS, keyed by id(directive) (mirroring orchestrator.py's
seen_statement_ids id-keying pattern) so the parsed model is never
mutated -- see docs/2026-07-31-csv-sourced-rows-design.md.

Runs at splice-check time (checks.py::run_static_checks), not parse time:
parse_cut() takes .cut text only, no .cbl -- mockymock collect --cut PATH
parses a .cut file with no .cbl argument at all (.okf/cli.md), so nothing
here can be pulled forward into the parser.

NOTE on cobolparser surface: `cobolparser.models.program.
CobolFileDescription`/`.data_records` is NEVER populated by the real
parser -- verified empirically; the FILE SECTION parser tags each
01-level record with `set_metadata("fd_file_name", ...)` instead (added in
a later slice's file-flattening code). This module deliberately does not
import CobolFileDescription for that reason.
"""

from __future__ import annotations

from dataclasses import dataclass

from cobolparser.models.data_items import CobolDataItem, ConditionNameItem, RenamesItem

from mockymock.analysis.refusal import RefusalReason
from mockymock.dsl.model import MockCategory, MockDirective, MockTestSuite
from mockymock.splicer.reset import is_group_item, is_numeric_picture

_POINTER_USAGES = frozenset(
    {"POINTER", "PROCEDURE-POINTER", "FUNCTION-POINTER", "PROGRAM-POINTER"}
)


@dataclass
class _TypedField:
    """One resolved CSV column/leaf-field target: its COBOL name (for the
    generated MOVE) and whether it takes a bare numeric or quoted
    alphanumeric literal. `picture` is None only for RETURN-CODE (a
    special register with no PICTURE to validate width/sign against)."""

    name: str
    numeric: bool
    picture: object | None


def resolve_csv_row_sources(
    suite: MockTestSuite, program
) -> tuple[dict[int, list[list[tuple[str, str]]]], list[RefusalReason]]:
    """Resolve every `MOCK ... ROWS FROM CSV` directive in `suite` against
    `program`'s AST. Returns (rows table keyed by id(directive), refusal
    reasons). A directive with any refusal gets no table entry -- callers
    must refuse the whole run when `reasons` is non-empty and must never
    consult the table for a directive that had a problem."""
    table: dict[int, list[list[tuple[str, str]]]] = {}
    reasons: list[RefusalReason] = []
    seen_ids: set[int] = set()
    ws_index: dict[str, object] | None = None

    for case in suite.test_cases:
        for directive in case.mocks:
            if directive.csv_source is None:
                continue
            if id(directive) in seen_ids:
                continue
            seen_ids.add(id(directive))

            assert directive.category is MockCategory.SQL
            if ws_index is None:
                ws_index = _build_working_storage_index(program)
            rows, directive_reasons = _resolve_sql_rows(directive, ws_index)

            if directive_reasons:
                reasons.extend(directive_reasons)
            else:
                table[id(directive)] = rows

    return table, reasons


def _build_working_storage_index(program) -> dict[str, object]:
    """Every named node in WORKING-STORAGE, keyed by upper-cased name --
    CobolDataItem (elementary/group), ConditionNameItem (88-level), and
    RenamesItem (66-level) alike, so a SQL CSV header naming any of them
    resolves to a definite node for `_classify_target` to accept or refuse
    with a precise reason, rather than a `CSV_FIELD_NOT_FOUND` false
    negative. First-declared name wins on a duplicate -- this DSL does not
    attempt `A OF B` qualification anywhere else either (see dsl.md's
    `_SUBSCRIPTED_NAME`), so an ambiguous unqualified name is out of scope
    here too."""
    index: dict[str, object] = {}
    data = program.get_division("DATA")
    if data is None:
        return index
    section = data._sections.get("WORKING-STORAGE")
    if section is None:
        return index

    def visit(node) -> None:
        name = getattr(node, "name", None)
        if name and name.upper() != "FILLER" and name.upper() not in index:
            index[name.upper()] = node
        for child in getattr(node, "children", []):
            visit(child)

    for item in section.data_items:
        visit(item)
    return index


def _resolve_sql_field(
    directive: MockDirective, column: str, ws_index: dict[str, object]
) -> _TypedField | RefusalReason:
    if column.upper() == "RETURN-CODE":
        return _TypedField(name="RETURN-CODE", numeric=True, picture=None)
    node = ws_index.get(column.upper())
    if node is None:
        return RefusalReason(
            code="CSV_FIELD_NOT_FOUND",
            message=(
                f"MOCK {directive.describe()} ROWS FROM CSV "
                f"{directive.csv_source.raw_path!r} (line "
                f"{directive.csv_source.line}): header column {column!r} "
                f"does not match any WORKING-STORAGE item"
            ),
        )
    return _classify_target(node, column, directive)


def _classify_target(
    node, display_name: str, directive: MockDirective
) -> _TypedField | RefusalReason:
    if isinstance(node, ConditionNameItem):
        return RefusalReason(
            code="CSV_UNTYPEABLE_TARGET",
            message=(
                f"MOCK {directive.describe()}: {display_name!r} is an "
                f"88-level condition name, not a data item -- ROWS FROM "
                f"CSV cannot target it"
            ),
        )
    if isinstance(node, RenamesItem):
        return RefusalReason(
            code="CSV_UNTYPEABLE_TARGET",
            message=(
                f"MOCK {directive.describe()}: {display_name!r} is a "
                f"level-66 RENAMES item, not an ordinary data item -- ROWS "
                f"FROM CSV cannot target it"
            ),
        )
    assert isinstance(node, CobolDataItem)
    if is_group_item(node):
        return RefusalReason(
            code="CSV_UNTYPEABLE_TARGET",
            message=(
                f"MOCK {directive.describe()}: {display_name!r} is a group "
                f"item (has subordinate fields) -- ROWS FROM CSV can only "
                f"target an elementary field"
            ),
        )
    usage = (node.usage or "").upper()
    if usage in _POINTER_USAGES or usage == "INDEX":
        return RefusalReason(
            code="CSV_UNTYPEABLE_TARGET",
            message=(
                f"MOCK {directive.describe()}: {display_name!r} is USAGE "
                f"{node.usage} -- ROWS FROM CSV cannot MOVE a plain "
                f"literal into a POINTER/INDEX item"
            ),
        )
    if node.picture_clause is None:
        return RefusalReason(
            code="CSV_UNTYPEABLE_TARGET",
            message=(
                f"MOCK {directive.describe()}: {display_name!r} has no "
                f"PICTURE clause -- ROWS FROM CSV cannot resolve a type "
                f"for it"
            ),
        )
    return _TypedField(
        name=node.name, numeric=is_numeric_picture(node), picture=node.picture_clause
    )


def _render_value(
    cell: str, field: _TypedField, directive: MockDirective, context: str
) -> str | RefusalReason:
    """Render one CSV cell as COBOL literal text for `MOVE <text> TO
    <field.name>`, or a RefusalReason if the value can't fit/sign-match
    `field.picture` (see the CSV Value Typing table in
    docs/2026-07-31-csv-sourced-rows-design.md). `field.picture` is None
    only for RETURN-CODE, which has no declared width/sign to validate."""
    if field.numeric:
        if not cell:
            return "0"
        negative = cell.startswith("-")
        magnitude = cell[1:] if negative else cell
        if field.picture is not None:
            if negative and not field.picture.is_signed:
                return RefusalReason(
                    code="CSV_SIGN_MISMATCH",
                    message=(
                        f"MOCK {directive.describe()} {context}: value "
                        f"{cell!r} is negative but {field.name} is an "
                        f"unsigned PICTURE -- GnuCOBOL silently stores the "
                        f"absolute value and drops the sign"
                    ),
                )
            integer_part = magnitude.split(".", 1)[0].lstrip("0") or "0"
            if (
                field.picture.integer_digits is not None
                and len(integer_part) > field.picture.integer_digits
            ):
                return RefusalReason(
                    code="CSV_VALUE_TOO_WIDE",
                    message=(
                        f"MOCK {directive.describe()} {context}: value "
                        f"{cell!r} has more integer digits than "
                        f"{field.name}'s PICTURE allows "
                        f"({field.picture.integer_digits}) -- GnuCOBOL "
                        f"truncates from the left, keeping the wrong digits"
                    ),
                )
        return cell
    if not cell:
        return "SPACES"
    if (
        field.picture is not None
        and field.picture.size is not None
        and len(cell) > field.picture.size
    ):
        return RefusalReason(
            code="CSV_VALUE_TOO_WIDE",
            message=(
                f"MOCK {directive.describe()} {context}: value {cell!r} "
                f"({len(cell)} chars) is wider than {field.name}'s "
                f"PICTURE ({field.picture.size}) -- GnuCOBOL truncates "
                f"from the right, keeping the wrong characters"
            ),
        )
    return '"' + cell.replace('"', '""') + '"'


def _resolve_sql_rows(
    directive: MockDirective, ws_index: dict[str, object]
) -> tuple[list[list[tuple[str, str]]], list[RefusalReason]]:
    csv_source = directive.csv_source
    assert csv_source is not None and csv_source.header is not None
    reasons: list[RefusalReason] = []
    fields: list[_TypedField | None] = []
    for column in csv_source.header:
        resolved = _resolve_sql_field(directive, column, ws_index)
        if isinstance(resolved, RefusalReason):
            reasons.append(resolved)
            fields.append(None)
        else:
            fields.append(resolved)
    if reasons:
        return [], reasons

    rows: list[list[tuple[str, str]]] = []
    for row_index, raw_row in enumerate(csv_source.raw_rows):
        resolved_row: list[tuple[str, str]] = []
        for field, cell in zip(fields, raw_row):
            assert field is not None
            context = f"row at CSV line {csv_source.row_lines[row_index]}"
            rendered = _render_value(cell, field, directive, context)
            if isinstance(rendered, RefusalReason):
                reasons.append(rendered)
            else:
                resolved_row.append((field.name, rendered))
        rows.append(resolved_row)
    if reasons:
        return [], reasons
    return rows, []
```

- [ ] **Step 7: Remove the Task-2 `getattr` shim in `injector.py`**

Now that `MockDirective.csv_source` exists as a real field, in `mockymock/splicer/injector.py` change:

```python
        has_rows = directive.rows is not None or getattr(
            directive, "csv_source", None
        ) is not None
```

to:

```python
        has_rows = directive.rows is not None or directive.csv_source is not None
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_csv_rows.py tests/unit/test_reset.py tests/unit/test_injector.py -v`
Expected: PASS (all tests)

- [ ] **Step 9: Commit**

```bash
git add mockymock/dsl/model.py mockymock/splicer/reset.py mockymock/splicer/injector.py mockymock/analysis/csv_rows.py tests/unit/test_csv_rows.py
git commit -m "feat(analysis): resolve SQL ROWS FROM CSV against WORKING-STORAGE"
```

---

### Task 6: Parser — `ROWS FROM CSV` grammar for `SQL`

**Files:**
- Modify: `mockymock/dsl/parser.py`
- Modify: `mockymock/cli/checks.py` (pass `cut_dir` — the one real caller besides `main.py`'s `collect`)
- Modify: `mockymock/cli/main.py` (`_cmd_collect` passes `cut_dir`)
- Test: `tests/unit/test_dsl_parser_csv_rows.py` (extends the file Task 1 created)

**Interfaces:**
- Consumes: `mockymock.dsl.model.CsvRowSource` (Task 5).
- Produces: `parse_cut(text: str, cut_dir: Path | None = None) -> MockTestSuite` (new optional parameter, backward compatible — every existing call site that omits it keeps working since no existing `.cut` text uses `ROWS FROM CSV`). `MockDirective.csv_source` populated for `MOCK SQL "..." \n ROWS FROM CSV "<path>" \n END-MOCK`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_dsl_parser_csv_rows.py`:

```python
from pathlib import Path

import pytest

from mockymock.dsl.model import MockCategory
from mockymock.dsl.parser import CutParseError, parse_cut


def _write_csv(tmp_path, name, rows):
    path = tmp_path / name
    path.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="")
    return path


def test_sql_rows_from_csv_resolves_path_relative_to_cut_dir(tmp_path):
    _write_csv(
        tmp_path,
        "customers.csv",
        ["CUST-ID,CUST-NAME", '1001,SMITH', '1002,"O\'BRIEN, JR."'],
    )
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK SQL "FETCH CUR"
        ROWS FROM CSV "customers.csv"
    END-MOCK
    PERFORM MAIN-PARA
"""
    suite = parse_cut(cut, cut_dir=tmp_path)
    directive = suite.test_cases[0].mocks[0]
    assert directive.rows is None
    assert directive.body_lines == []
    csv_source = directive.csv_source
    assert csv_source.raw_path == "customers.csv"
    assert csv_source.resolved_path == (tmp_path / "customers.csv").resolve()
    assert csv_source.positional is False
    assert csv_source.header == ["CUST-ID", "CUST-NAME"]
    assert csv_source.raw_rows == [["1001", "SMITH"], ["1002", "O'BRIEN, JR."]]
    assert csv_source.row_lines == [2, 3]


def test_sql_rows_from_csv_on_non_sql_category_is_rejected(tmp_path):
    _write_csv(tmp_path, "x.csv", ["A,B", "1,2"])
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN INFILE
        ROWS FROM CSV "x.csv"
    END-MOCK
    PERFORM MAIN-PARA
"""
    with pytest.raises(
        CutParseError, match="ROWS FROM CSV is only supported for MOCK SQL"
    ):
        parse_cut(cut, cut_dir=tmp_path)


def test_sql_rows_from_csv_missing_file_raises_at_parse_time(tmp_path):
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK SQL "FETCH CUR"
        ROWS FROM CSV "does-not-exist.csv"
    END-MOCK
    PERFORM MAIN-PARA
"""
    with pytest.raises(CutParseError, match="not found"):
        parse_cut(cut, cut_dir=tmp_path)


def test_sql_rows_from_csv_header_arity_mismatch_raises_at_parse_time(tmp_path):
    _write_csv(tmp_path, "bad.csv", ["A,B", "1,2,3"])
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK SQL "FETCH CUR"
        ROWS FROM CSV "bad.csv"
    END-MOCK
    PERFORM MAIN-PARA
"""
    with pytest.raises(CutParseError, match="2 column"):
        parse_cut(cut, cut_dir=tmp_path)


def test_sql_rows_from_csv_with_no_data_rows_raises(tmp_path):
    _write_csv(tmp_path, "header_only.csv", ["A,B"])
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK SQL "FETCH CUR"
        ROWS FROM CSV "header_only.csv"
    END-MOCK
    PERFORM MAIN-PARA
"""
    with pytest.raises(CutParseError, match="no data rows"):
        parse_cut(cut, cut_dir=tmp_path)


def test_rows_from_csv_without_cut_dir_raises(tmp_path):
    _write_csv(tmp_path, "x.csv", ["A", "1"])
    cut = f"""\
TESTSUITE "s"
TESTCASE "c"
    MOCK SQL "FETCH CUR"
        ROWS FROM CSV "{tmp_path / 'x.csv'}"
    END-MOCK
    PERFORM MAIN-PARA
"""
    with pytest.raises(CutParseError, match="cut_dir"):
        parse_cut(cut)


def test_body_line_after_rows_from_csv_is_rejected(tmp_path):
    _write_csv(tmp_path, "x.csv", ["A", "1"])
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK SQL "FETCH CUR"
        ROWS FROM CSV "x.csv"
        MOVE 0 TO SQLCODE
    END-MOCK
    PERFORM MAIN-PARA
"""
    with pytest.raises(CutParseError, match="already has ROWS FROM CSV"):
        parse_cut(cut, cut_dir=tmp_path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_dsl_parser_csv_rows.py -v -k rows_from_csv`
Expected: FAIL — `parse_cut` doesn't accept `cut_dir`; `ROWS FROM CSV` isn't recognized at all (falls through to `body_lines.append`, so the directive parses with wrong/no `csv_source`).

- [ ] **Step 3: Add `cut_dir` parameter and CSV grammar to `parser.py`**

Add near the top of `mockymock/dsl/parser.py` (with the other imports):

```python
import csv
from pathlib import Path

from mockymock.dsl.model import (
    FILE_STATUS_CATEGORIES,
    CsvRowSource,
    DataProvider,
    ExpectDirective,
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
    VerifyDirective,
)
```

Add a new regex near `_FILE_STATUS_RE`:

```python
_ROWS_FROM_CSV_RE = re.compile(r'^ROWS\s+FROM\s+CSV\s+"(?P<path>[^"]*)"$')
```

Add a helper function (near `_split_top_level`):

```python
def _read_csv_rows(
    resolved_path: Path, line_no: int, positional: bool
) -> tuple[list[str] | None, list[list[str]], list[int]]:
    """Reads a ROWS FROM CSV file: (header, data rows, each data row's
    1-based CSV-file line number). `positional` (READ) means no header --
    every row is data. SQL's own header/arity check happens in the caller,
    since the caller (not this generic reader) is the one that knows
    whether SQL or READ semantics apply."""
    if not resolved_path.is_file():
        raise CutParseError(
            f"line {line_no}: ROWS FROM CSV {str(resolved_path)!r} not found"
        )
    with resolved_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        all_rows: list[list[str]] = []
        all_lines: list[int] = []
        for row in reader:
            if not row:
                continue  # blank lines are tolerated, same as .cut text
            all_rows.append([cell.strip() for cell in row])
            all_lines.append(reader.line_num)

    if positional:
        header = None
        data_rows, data_lines = all_rows, all_lines
    else:
        if not all_rows:
            raise CutParseError(
                f"line {line_no}: ROWS FROM CSV {str(resolved_path)!r} has "
                f"no header row"
            )
        header = all_rows[0]
        data_rows, data_lines = all_rows[1:], all_lines[1:]

    if not data_rows:
        raise CutParseError(
            f"line {line_no}: ROWS FROM CSV {str(resolved_path)!r} has no "
            f"data rows"
        )

    return header, data_rows, data_lines
```

Update `parse_cut`'s signature:

```python
def parse_cut(text: str, cut_dir: Path | None = None) -> MockTestSuite:
```

In the in-mock-body loop, the current shape is:

```python
        if in_mock is not None:
            if _END_MOCK_RE.match(line):
                ...
                in_mock = None
            elif in_mock.rows is not None:
                ...
            elif (m := _FILE_STATUS_RE.match(line)) is not None:
                ...
            elif _FILE_STATUS_PREFIX_RE.match(line) is not None:
                ...
            else:
                in_mock.body_lines.append(line)
            continue
```

Insert two new `elif` branches between the `in_mock.rows is not None` branch and the `_FILE_STATUS_RE` branch:

```python
            elif in_mock.csv_source is not None:
                raise CutParseError(
                    f"line {line_no}: MOCK {in_mock.describe()} already "
                    f"has ROWS FROM CSV -- only one row source is allowed, "
                    f"and no further lines until END-MOCK"
                )
            elif (m := _ROWS_FROM_CSV_RE.match(line)) is not None:
                if in_mock.category is not MockCategory.SQL:
                    raise CutParseError(
                        f"line {line_no}: ROWS FROM CSV is only supported "
                        f"for MOCK SQL, not MOCK {in_mock.category.keyword}"
                    )
                if in_mock.body_lines:
                    raise CutParseError(
                        f"line {line_no}: ROWS FROM CSV must be the only "
                        f"line in this MOCK body"
                    )
                raw_path = m.group("path")
                if not raw_path:
                    raise CutParseError(
                        f"line {line_no}: ROWS FROM CSV path must not be "
                        f"empty"
                    )
                if cut_dir is None:
                    raise CutParseError(
                        f"line {line_no}: ROWS FROM CSV {raw_path!r} needs "
                        f"the .cut file's directory to resolve its "
                        f"relative path against -- this parse_cut() call "
                        f"did not provide cut_dir"
                    )
                resolved_path = (cut_dir / raw_path).resolve()
                header, raw_rows, row_lines = _read_csv_rows(
                    resolved_path, line_no, positional=False
                )
                assert header is not None
                for row_index, row in enumerate(raw_rows):
                    if len(row) != len(header):
                        raise CutParseError(
                            f"line {line_no}: ROWS FROM CSV {raw_path!r} "
                            f"row at CSV line {row_lines[row_index]} has "
                            f"{len(row)} cell(s) but the header has "
                            f"{len(header)} column(s)"
                        )
                in_mock.csv_source = CsvRowSource(
                    raw_path=raw_path,
                    resolved_path=resolved_path,
                    line=line_no,
                    positional=False,
                    header=header,
                    raw_rows=raw_rows,
                    row_lines=row_lines,
                )
```

- [ ] **Step 4: Thread `cut_dir` through the two real callers**

In `mockymock/cli/checks.py`, inside `run_static_checks`, change:

```python
    try:
        suite = parse_cut(cut_path.read_text(encoding="utf-8"))
    except CutParseError as exc:
```

to:

```python
    try:
        suite = parse_cut(cut_path.read_text(encoding="utf-8"), cut_dir=cut_path.parent)
    except CutParseError as exc:
```

In `mockymock/cli/main.py`, inside `_cmd_collect`, change:

```python
    try:
        suite = parse_cut(cut_path.read_text(encoding="utf-8"))
    except CutParseError as exc:
```

to:

```python
    try:
        suite = parse_cut(cut_path.read_text(encoding="utf-8"), cut_dir=cut_path.parent)
    except CutParseError as exc:
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_dsl_parser_csv_rows.py -v`
Expected: PASS (all tests from Tasks 1 and 6)

- [ ] **Step 6: Run the full unit suite to confirm no regression**

Run: `python -m pytest tests/unit -v`
Expected: PASS (every existing `parse_cut(text)` call site omits `cut_dir`, which defaults to `None` — harmless for every `.cut` fixture that doesn't use `ROWS FROM CSV`)

- [ ] **Step 7: Commit**

```bash
git add mockymock/dsl/parser.py mockymock/cli/checks.py mockymock/cli/main.py tests/unit/test_dsl_parser_csv_rows.py
git commit -m "feat(dsl): parse ROWS FROM CSV for SQL, resolved against the .cut dir"
```

---

### Task 7: Wire CSV resolution into the `run`/`debug`/`lint` pipeline

**Files:**
- Modify: `mockymock/cli/checks.py`
- Modify: `mockymock/splicer/orchestrator.py`
- Modify: `mockymock/cli/main.py`
- Test: `tests/unit/test_checks.py`, `tests/unit/test_orchestrator.py`

**Interfaces:**
- Consumes: `mockymock.analysis.csv_rows.resolve_csv_row_sources` (Task 5).
- Produces: `StaticCheckResult.csv_rows: dict[int, list[list[tuple[str, str]]]] | None` (new field). `splice_program(..., csv_rows: dict | None = None, ...)` (new optional parameter, threaded to `build_site_dispatch`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_checks.py`:

```python
def test_sql_rows_from_csv_populates_csv_rows_and_passes(tmp_path):
    cbl = tmp_path / "P.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  CUST-ID PIC 9(5).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           EXEC SQL\n"
        "               FETCH CUR INTO :CUST-ID\n"
        "           END-EXEC.\n"
        "           STOP RUN.\n"
    )
    (tmp_path / "rows.csv").write_text("CUST-ID\n1001\n", encoding="utf-8")
    cut = tmp_path / "P.cut"
    cut.write_text(
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOCK SQL "FETCH CUR"\n'
        '        ROWS FROM CSV "rows.csv"\n'
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
    )
    result = run_static_checks(cbl, cut, None)
    assert result.ok, result.problems
    assert result.csv_rows is not None
    directive = result.suite.test_cases[0].mocks[0]
    assert result.csv_rows[id(directive)] == [[("CUST-ID", "1001")]]


def test_csv_field_not_found_is_a_problem(tmp_path):
    cbl = tmp_path / "P.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           STOP RUN.\n"
    )
    (tmp_path / "rows.csv").write_text("BOGUS\n1\n", encoding="utf-8")
    cut = tmp_path / "P.cut"
    cut.write_text(
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOCK SQL "X"\n'
        '        ROWS FROM CSV "rows.csv"\n'
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
    )
    result = run_static_checks(cbl, cut, None)
    assert not result.ok
    assert any("CSV_FIELD_NOT_FOUND" in p for p in result.problems)
```

Add to `tests/unit/test_orchestrator.py` (near the other `splice_program` tests):

```python
def test_splice_program_uses_resolved_csv_rows_for_a_csv_sourced_directive():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CSVSPLICE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CUST-ID PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               FETCH CUR INTO :CUST-ID
           END-EXEC.
    """
    result = parse_cobol(source, filename="csvsplice.cbl")
    surface = analyze(result.ast)
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    boundaries = collect_boundaries(result.ast)

    directive = MockDirective(MockCategory.SQL, "FETCH CUR")
    directive.csv_source = CsvRowSource(
        raw_path="x.csv",
        resolved_path=Path("x.csv"),
        line=1,
        positional=False,
        header=["CUST-ID"],
        raw_rows=[["1001"]],
        row_lines=[2],
    )
    case = MockTestCase(name="c", mocks=[directive], perform_target="MAIN-PARA")
    suite = MockTestSuite(name="S", test_cases=[case])
    csv_rows = {id(directive): [[("CUST-ID", "1001")]]}

    spliced = splice_program(
        lines, boundaries, surface, suite, TallyRegistry(suite), csv_rows=csv_rows
    )
    joined = "\n".join(spliced)
    assert "MOVE 1001 TO CUST-ID" in joined
    assert "MOVE 0 TO SQLCODE" in joined


def test_splice_program_raises_when_csv_source_is_unresolved():
    """Invariant guard: a directive with csv_source set but missing from
    the csv_rows table means resolve_csv_row_sources should have refused
    it -- splicing must fail loudly, not silently emit an empty WHEN
    branch."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CSVSPLICE2.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               FETCH CUR INTO :X
           END-EXEC.
    """
    result = parse_cobol(source, filename="csvsplice2.cbl")
    surface = analyze(result.ast)
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    boundaries = collect_boundaries(result.ast)

    directive = MockDirective(MockCategory.SQL, "FETCH CUR")
    directive.csv_source = CsvRowSource(
        raw_path="x.csv",
        resolved_path=Path("x.csv"),
        line=1,
        positional=False,
        header=["X"],
        raw_rows=[["1"]],
        row_lines=[2],
    )
    case = MockTestCase(name="c", mocks=[directive], perform_target="MAIN-PARA")
    suite = MockTestSuite(name="S", test_cases=[case])

    with pytest.raises(ValueError, match="resolve_csv_row_sources"):
        splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))
```

(Add the needed imports at the top of `tests/unit/test_orchestrator.py` if not already present: `from pathlib import Path`, `from mockymock.dsl.model import CsvRowSource, MockCategory, MockDirective, MockTestCase, MockTestSuite` — check the existing import block first and only add what's missing.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_checks.py tests/unit/test_orchestrator.py -v -k csv`
Expected: FAIL — `StaticCheckResult` has no `csv_rows` field; `run_static_checks` never calls `resolve_csv_row_sources`; `splice_program` doesn't accept `csv_rows` yet (it's only threaded as far as `build_site_dispatch` from Task 2 — `splice_program` itself needs the parameter added and passed through).

- [ ] **Step 3: Add `csv_rows` to `StaticCheckResult` and wire resolution into `run_static_checks`**

In `mockymock/cli/checks.py`, add to `StaticCheckResult`:

```python
    csv_rows: dict[int, list[list[tuple[str, str]]]] | None = None
```

Add the import inside `run_static_checks` (alongside the other deferred imports):

```python
    from mockymock.analysis.csv_rows import resolve_csv_row_sources
```

Right after the existing `out.file_status_fields = analyze_file_status_fields(parse_result.ast)` line, add:

```python
    resolved_csv_rows, csv_reasons = resolve_csv_row_sources(suite, parse_result.ast)
    out.csv_rows = resolved_csv_rows
    if csv_reasons:
        out.problems.extend(
            f"refused ({r.code}): {r.message}" for r in csv_reasons
        )
        return out
```

- [ ] **Step 4: Thread `csv_rows` through `splice_program`**

In `mockymock/splicer/orchestrator.py`, change `splice_program`'s signature:

```python
def splice_program(
    lines: list[str],
    boundaries: list[int],
    surface: MockSurface,
    suite: MockTestSuite,
    registry: TallyRegistry,
    terminator_plans: Sequence[TerminatorPlan] = (),
    flow_plans: Sequence[FlowMockPlan] = (),
    file_status_fields: dict[str, str] | None = None,
    csv_rows: dict[int, list[list[tuple[str, str]]]] | None = None,
    trace: bool = False,
) -> list[str]:
```

and change the one call to `build_site_dispatch`:

```python
        if mocked:
            replacement = build_site_dispatch(
                site, suite, registry, file_status_fields, csv_rows, trace=trace
            )
```

- [ ] **Step 5: Thread `checked.csv_rows` through both CLI call sites**

In `mockymock/cli/main.py`, in `_cmd_run`, change:

```python
    lines = splice_program(
        lines,
        boundaries,
        surface,
        suite,
        registry,
        terminator_plans,
        flow_plans,
        checked.file_status_fields,
        trace=args.trace,
    )
```

to:

```python
    lines = splice_program(
        lines,
        boundaries,
        surface,
        suite,
        registry,
        terminator_plans,
        flow_plans,
        checked.file_status_fields,
        csv_rows=checked.csv_rows,
        trace=args.trace,
    )
```

In `_cmd_debug`, change the mirroring call the same way:

```python
    lines = splice_program(
        lines,
        boundaries,
        surface,
        suite,
        registry,
        terminator_plans,
        flow_plans,
        checked.file_status_fields,
        csv_rows=checked.csv_rows,
        trace=False,
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_checks.py tests/unit/test_orchestrator.py -v`
Expected: PASS (all tests)

- [ ] **Step 7: Run the full unit suite**

Run: `python -m pytest tests/unit -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add mockymock/cli/checks.py mockymock/splicer/orchestrator.py mockymock/cli/main.py tests/unit/test_checks.py tests/unit/test_orchestrator.py
git commit -m "feat(cli): wire CSV row resolution into run/debug/lint"
```

---

### Task 8: Integration proof — `SQL ROWS FROM CSV` matches inline `ROWS`

**Files:**
- Modify: `examples/custprog/CUSTPROG.cut`
- Create: `examples/custprog/data/customers.csv`
- Modify: `examples/custprog/README.md`

**Interfaces:**
- Consumes: nothing new (the existing `examples/custprog/CUSTPROG.cbl` and its `CUSTREC.CPY` copybook, unmodified).
- Produces: nothing new — this is a verification task closing out Slice 2.

- [ ] **Step 1: Add the CSV file**

Create `examples/custprog/data/customers.csv`:

```
CUST-ID,CUST-NAME
100,SMITH
101,JONES
```

- [ ] **Step 2: Add a second TESTCASE to `CUSTPROG.cut`**

Append to `examples/custprog/CUSTPROG.cut` (after the existing `TESTCASE`, keeping it untouched):

```
TESTCASE "fetches two customers via ROWS FROM CSV (same result as inline ROWS)"
    MOCK SQL "DECLARE CUST_CURSOR"
    END-MOCK
    MOCK SQL "OPEN CUST_CURSOR"
    END-MOCK
    MOCK SQL "FETCH CUST_CURSOR"
        ROWS FROM CSV "data/customers.csv"
    END-MOCK
    MOCK SQL "CLOSE CUST_CURSOR"
    END-MOCK
    PERFORM MAIN-PROCESS
    EXPECT WS-ROW-COUNT TO BE 2
    VERIFY SQL "FETCH CUST_CURSOR" WAS PERFORMED 3 TIMES
```

- [ ] **Step 3: Run it against the real toolchain**

Run: `python -m mockymock.cli.main run examples/custprog/CUSTPROG.cbl --cut examples/custprog/CUSTPROG.cut --copybook-path examples/custprog/copybooks`

(Invoke via `python -m mockymock.cli.main`, i.e. in-process from this checkout — not a `PATH`-installed `mockymock` binary, per the stale-global-install gotcha in `.okf/testing.md`.)

Expected: exit 0, `__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=0`, both `CASE 001` and `CASE 002` reported as passing.

- [ ] **Step 4: Add the corresponding integration test**

Add to `tests/integration/test_cli.py` (find the existing custprog-related test, if any, and add alongside it; otherwise add near other example-driven tests):

```python
@requires_docker
def test_custprog_rows_from_csv_matches_inline_rows(capsys):
    root = Path(__file__).resolve().parents[2] / "examples" / "custprog"
    exit_code = main(
        [
            "run",
            str(root / "CUSTPROG.cbl"),
            "--cut",
            str(root / "CUSTPROG.cut"),
            "--copybook-path",
            str(root / "copybooks"),
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "RUN=2 FAILURES=0" in out
```

(Match the existing file's import style for `main`/`requires_docker`/`Path` — check the top of `tests/integration/test_cli.py` first and reuse what's already imported rather than adding duplicate imports.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/integration/test_cli.py -v -k custprog`
Expected: PASS

- [ ] **Step 6: Update the README**

In `examples/custprog/README.md`, add a new bullet after the existing "`ROWS` cursor-fetch sugar" bullet:

```markdown
- **`ROWS FROM CSV`.** The second `TESTCASE` proves the identical cursor
  fetch-loop driven by `MOCK SQL "FETCH CUST_CURSOR" ROWS FROM CSV
  "data/customers.csv"` instead of inline `( CUST-ID = ..., CUST-NAME =
  ... )` rows -- the CSV's header names the host variables, and typing
  (bare vs. quoted) is resolved automatically from each column's
  `PICTURE`. Same result as the first `TESTCASE`, proving CSV-vs-inline
  `ROWS` produce identical compiled behavior.
```

- [ ] **Step 7: Commit**

```bash
git add examples/custprog/CUSTPROG.cut examples/custprog/data/customers.csv examples/custprog/README.md tests/integration/test_cli.py
git commit -m "test(integration): prove SQL ROWS FROM CSV matches inline ROWS"
```

---

## Slice 3 — `ROWS FROM CSV` for `READ` (positional)

### Task 9: `csv_rows.py` — `READ` positional resolution (FD record → flattened leaf fields)

**Files:**
- Modify: `mockymock/analysis/csv_rows.py`
- Modify: `tests/unit/test_csv_rows.py`

**Interfaces:**
- Consumes: `cobolparser.models.program.CobolDivision._sections["FILE"].data_items` (existing pin, generalized here to the FILE section — already covered by `interface-contract.md`'s existing DATA-division `_sections` entry). **New** surface, pinned in Task 12: `CobolDataItem.get_metadata("fd_file_name")` (and the underlying `ASTNode.get_metadata`/`.has_metadata` API), `.occurs_clause`, `.redefines`.
- Produces: `_flatten_record_for_file(program, file_key) -> list[CobolDataItem] | RefusalReason`, `_resolve_read_rows(directive, leaves) -> tuple[rows, reasons]`. Extends `resolve_csv_row_sources`'s loop to branch on `directive.category`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_csv_rows.py`:

```python
READ_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. READCSVSPIKE.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO "C.DAT"
               FILE STATUS IS WS-CUST-STATUS.
           SELECT OCCFILE ASSIGN TO "O.DAT"
               FILE STATUS IS WS-OCC-STATUS.
           SELECT REDEFFILE ASSIGN TO "R.DAT"
               FILE STATUS IS WS-REDEF-STATUS.
           SELECT MULTIFILE ASSIGN TO "M.DAT"
               FILE STATUS IS WS-MULTI-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-REC.
           05  CUST-ID         PIC 9(5).
           05  CUST-NAME       PIC X(10).
           05  CUST-BAL        PIC 9(5)V99.
       FD  OCCFILE.
       01  OCC-REC.
           05  OCC-ID          PIC 9(3).
           05  OCC-TABLE       OCCURS 2 TIMES PIC 9(2).
       FD  REDEFFILE.
       01  REDEF-REC.
           05  REDEF-A         PIC X(4).
           05  REDEF-B REDEFINES REDEF-A PIC 9(4).
       FD  MULTIFILE.
       01  MULTI-REC-A         PIC X(5).
       01  MULTI-REC-B         PIC X(5).

       WORKING-STORAGE SECTION.
       01  WS-CUST-STATUS      PIC X(2).
       01  WS-OCC-STATUS       PIC X(2).
       01  WS-REDEF-STATUS     PIC X(2).
       01  WS-MULTI-STATUS     PIC X(2).

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _read_directive(key, raw_rows, row_lines=None) -> MockDirective:
    directive = MockDirective(MockCategory.READ, key)
    directive.csv_source = CsvRowSource(
        raw_path="x.csv",
        resolved_path=Path("x.csv"),
        line=1,
        positional=True,
        header=None,
        raw_rows=raw_rows,
        row_lines=row_lines or list(range(1, len(raw_rows) + 1)),
    )
    return directive


def _resolve_read(directive):
    result = parse_cobol(READ_SOURCE, filename="readcsvspike.cbl")
    assert result.success, result.errors
    case = MockTestCase(name="c", mocks=[directive])
    suite = MockTestSuite(name="S", test_cases=[case])
    return resolve_csv_row_sources(suite, result.ast)


def test_read_positional_resolves_leaves_in_declaration_order():
    directive = _read_directive("CUST-FILE", [["1001", "SMITH", "100.00"]])
    table, reasons = _resolve_read(directive)
    assert reasons == []
    assert table[id(directive)] == [
        [
            ("CUST-ID", "1001"),
            ("CUST-NAME", '"SMITH"'),
            ("CUST-BAL", "100.00"),
        ]
    ]


def test_read_positional_multiple_rows():
    directive = _read_directive(
        "CUST-FILE",
        [["1001", "SMITH", "100.00"], ["1002", "JONES", "200.25"]],
    )
    table, reasons = _resolve_read(directive)
    assert reasons == []
    assert len(table[id(directive)]) == 2


def test_read_positional_unknown_file_refuses_unresolved_record():
    directive = _read_directive("NO-SUCH-FILE", [["1"]])
    table, reasons = _resolve_read(directive)
    assert id(directive) not in table
    assert reasons[0].code == "UNRESOLVED_FILE_RECORD"


def test_read_positional_occurs_anywhere_refuses_unsupported_shape():
    directive = _read_directive("OCCFILE", [["1", "1", "2"]])
    table, reasons = _resolve_read(directive)
    assert id(directive) not in table
    assert reasons[0].code == "CSV_RECORD_UNSUPPORTED_SHAPE"


def test_read_positional_redefines_anywhere_refuses_unsupported_shape():
    directive = _read_directive("REDEFFILE", [["ABCD"]])
    table, reasons = _resolve_read(directive)
    assert reasons[0].code == "CSV_RECORD_UNSUPPORTED_SHAPE"


def test_read_positional_multiple_01_records_refuses_unsupported_shape():
    directive = _read_directive("MULTIFILE", [["ABCDE"]])
    table, reasons = _resolve_read(directive)
    assert reasons[0].code == "CSV_RECORD_UNSUPPORTED_SHAPE"


def test_read_positional_arity_mismatch_stops_at_first_bad_row():
    directive = _read_directive(
        "CUST-FILE",
        [
            ["1001", "SMITH", "100.00"],
            ["1002", "JONES"],  # missing CUST-BAL
            ["1003", "DOE", "50.00"],
        ],
    )
    table, reasons = _resolve_read(directive)
    assert id(directive) not in table
    assert len(reasons) == 1
    assert reasons[0].code == "CSV_ARITY_MISMATCH"
    assert "2 cell" in reasons[0].message


def test_read_positional_column_typing_reused_from_sql_path():
    """A too-wide value in a positional leaf refuses the same
    CSV_VALUE_TOO_WIDE code the SQL path already exercises -- proves the
    shared _classify_target/_render_value helpers are reused, not
    reimplemented, for READ."""
    directive = _read_directive("CUST-FILE", [["1001", "TOO-LONG-NAME-X", "0"]])
    table, reasons = _resolve_read(directive)
    assert reasons[0].code == "CSV_VALUE_TOO_WIDE"
```

(Add `from mockymock.dsl.model import CsvRowSource` and `from cobolparser import parse_cobol` to this test file's imports if not already present from Task 5 — check the existing import block first.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_csv_rows.py -v -k read_positional`
Expected: FAIL — `resolve_csv_row_sources` today only handles `MockCategory.SQL` (asserts it, in fact — Task 5's `assert directive.category is MockCategory.SQL` would trip on a `READ` directive).

- [ ] **Step 3: Extend `csv_rows.py`**

In `mockymock/analysis/csv_rows.py`, replace the body of `resolve_csv_row_sources`'s per-directive branch:

```python
            assert directive.category is MockCategory.SQL
            if ws_index is None:
                ws_index = _build_working_storage_index(program)
            rows, directive_reasons = _resolve_sql_rows(directive, ws_index)

            if directive_reasons:
                reasons.extend(directive_reasons)
            else:
                table[id(directive)] = rows
```

with:

```python
            if directive.category is MockCategory.SQL:
                if ws_index is None:
                    ws_index = _build_working_storage_index(program)
                rows, directive_reasons = _resolve_sql_rows(directive, ws_index)
            else:
                assert directive.category is MockCategory.READ
                key = directive.key.upper()
                if key not in fd_leaves_cache:
                    fd_leaves_cache[key] = _flatten_record_for_file(program, directive.key)
                leaves_or_reason = fd_leaves_cache[key]
                if isinstance(leaves_or_reason, RefusalReason):
                    reasons.append(leaves_or_reason)
                    continue
                rows, directive_reasons = _resolve_read_rows(directive, leaves_or_reason)

            if directive_reasons:
                reasons.extend(directive_reasons)
            else:
                table[id(directive)] = rows
```

and add `fd_leaves_cache` alongside the existing `ws_index` local, near the top of `resolve_csv_row_sources`:

```python
    ws_index: dict[str, object] | None = None
    fd_leaves_cache: dict[str, list | RefusalReason] = {}
```

Append four new functions after `_resolve_sql_rows`:

```python
def _flatten_record_for_file(program, file_key: str) -> list[CobolDataItem] | RefusalReason:
    """The target file's FD record, flattened depth-first to its ordered
    elementary leaf fields -- a positional CSV column list mirrors a real
    flat-file dump exactly (see the design doc's Design > Resolution
    section). Refuses UNRESOLVED_FILE_RECORD if the file has no FD record
    at all; CSV_RECORD_UNSUPPORTED_SHAPE if the FD declares more than one
    01-level record (legal, idiomatic COBOL, but positional mapping needs
    exactly one -- v1 limitation) or if the record contains OCCURS/
    REDEFINES anywhere (flattening either needs more than a flat column
    list)."""
    data = program.get_division("DATA")
    file_section = data._sections.get("FILE") if data is not None else None
    upper_key = file_key.upper()
    records = [
        item
        for item in (file_section.data_items if file_section is not None else [])
        if (item.get_metadata("fd_file_name") or "").upper() == upper_key
    ]
    if not records:
        return RefusalReason(
            code="UNRESOLVED_FILE_RECORD",
            message=(
                f"file {file_key!r} has no 01-level record in the FILE "
                f"SECTION -- ROWS FROM CSV (positional) needs a record "
                f"layout to map columns against"
            ),
        )
    if len(records) > 1:
        return RefusalReason(
            code="CSV_RECORD_UNSUPPORTED_SHAPE",
            message=(
                f"file {file_key!r}'s FD declares {len(records)} 01-level "
                f"records -- positional CSV mapping supports exactly one "
                f"record per FD (v1 limitation)"
            ),
        )
    record = records[0]
    if _has_occurs_or_redefines(record):
        return RefusalReason(
            code="CSV_RECORD_UNSUPPORTED_SHAPE",
            message=(
                f"record '{record.name}' for file {file_key!r} contains "
                f"an OCCURS or REDEFINES field -- flattening either "
                f"correctly needs more than a flat column list, which "
                f"positional CSV mapping does not support"
            ),
        )
    return _leaf_fields(record)


def _has_occurs_or_redefines(item) -> bool:
    if getattr(item, "occurs_clause", None) is not None or getattr(
        item, "redefines", None
    ):
        return True
    return any(
        _has_occurs_or_redefines(child)
        for child in item.children
        if getattr(child, "level", None) is not None
    )


def _leaf_fields(item) -> list[CobolDataItem]:
    data_children = [c for c in item.children if getattr(c, "level", None) is not None]
    if not data_children:
        return [item]
    leaves: list[CobolDataItem] = []
    for child in data_children:
        leaves.extend(_leaf_fields(child))
    return leaves


def _resolve_read_rows(
    directive: MockDirective, leaves: list[CobolDataItem]
) -> tuple[list[list[tuple[str, str]]], list[RefusalReason]]:
    reasons: list[RefusalReason] = []
    fields: list[_TypedField | None] = []
    for leaf in leaves:
        resolved = _classify_target(leaf, leaf.name, directive)
        if isinstance(resolved, RefusalReason):
            reasons.append(resolved)
            fields.append(None)
        else:
            fields.append(resolved)
    if reasons:
        return [], reasons

    csv_source = directive.csv_source
    assert csv_source is not None
    for row_index, raw_row in enumerate(csv_source.raw_rows):
        if len(raw_row) != len(fields):
            return [], [
                RefusalReason(
                    code="CSV_ARITY_MISMATCH",
                    message=(
                        f"MOCK {directive.describe()} ROWS FROM CSV "
                        f"{csv_source.raw_path!r}: row at CSV line "
                        f"{csv_source.row_lines[row_index]} has "
                        f"{len(raw_row)} cell(s) but the record has "
                        f"{len(fields)} leaf field(s)"
                    ),
                )
            ]

    rows: list[list[tuple[str, str]]] = []
    for row_index, raw_row in enumerate(csv_source.raw_rows):
        resolved_row: list[tuple[str, str]] = []
        for field, cell in zip(fields, raw_row):
            assert field is not None
            context = f"row at CSV line {csv_source.row_lines[row_index]}"
            rendered = _render_value(cell, field, directive, context)
            if isinstance(rendered, RefusalReason):
                reasons.append(rendered)
            else:
                resolved_row.append((field.name, rendered))
        rows.append(resolved_row)
    if reasons:
        return [], reasons
    return rows, []
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_csv_rows.py -v`
Expected: PASS (all tests, both SQL from Task 5 and READ from this task)

- [ ] **Step 5: Commit**

```bash
git add mockymock/analysis/csv_rows.py tests/unit/test_csv_rows.py
git commit -m "feat(analysis): resolve READ ROWS FROM CSV against the FD record"
```

---

### Task 10: Parser — `ROWS FROM CSV` grammar for `READ` (positional)

**Files:**
- Modify: `mockymock/dsl/parser.py`
- Test: `tests/unit/test_dsl_parser_csv_rows.py`

**Interfaces:**
- Consumes: `_read_csv_rows(..., positional=True)` (Task 6, already handles the headerless branch).
- Produces: `MOCK READ <key> \n ROWS FROM CSV "<path>" \n END-MOCK` parses with `csv_source.positional == True`, `csv_source.header is None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_dsl_parser_csv_rows.py`:

```python
def test_read_rows_from_csv_is_positional_no_header(tmp_path):
    _write_csv(tmp_path, "custfile.csv", ["1001,SMITH", "1002,JONES"])
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ CUST-FILE
        ROWS FROM CSV "custfile.csv"
    END-MOCK
    PERFORM MAIN-PARA
"""
    suite = parse_cut(cut, cut_dir=tmp_path)
    csv_source = suite.test_cases[0].mocks[0].csv_source
    assert csv_source.positional is True
    assert csv_source.header is None
    assert csv_source.raw_rows == [["1001", "SMITH"], ["1002", "JONES"]]
    assert csv_source.row_lines == [1, 2]


def test_read_rows_from_csv_no_arity_check_at_parse_time(tmp_path):
    """READ's positional form can't be arity-checked at parse time --
    nothing in the parser knows the record's field count; inconsistent row
    widths must parse fine here and surface later at splice time
    (CSV_ARITY_MISMATCH, see test_csv_rows.py)."""
    _write_csv(tmp_path, "custfile.csv", ["1001,SMITH", "1002,JONES,EXTRA"])
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ CUST-FILE
        ROWS FROM CSV "custfile.csv"
    END-MOCK
    PERFORM MAIN-PARA
"""
    suite = parse_cut(cut, cut_dir=tmp_path)  # must not raise
    csv_source = suite.test_cases[0].mocks[0].csv_source
    assert csv_source.raw_rows == [["1001", "SMITH"], ["1002", "JONES", "EXTRA"]]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_dsl_parser_csv_rows.py -v -k read_rows_from_csv`
Expected: FAIL — the `ROWS FROM CSV` branch still gates on `in_mock.category is not MockCategory.SQL` (raises for `READ`) and always calls `_read_csv_rows(..., positional=False)`.

- [ ] **Step 3: Widen the parser's gate and branch on category**

In `mockymock/dsl/parser.py`, change:

```python
            elif (m := _ROWS_FROM_CSV_RE.match(line)) is not None:
                if in_mock.category is not MockCategory.SQL:
                    raise CutParseError(
                        f"line {line_no}: ROWS FROM CSV is only supported "
                        f"for MOCK SQL, not MOCK {in_mock.category.keyword}"
                    )
```

to:

```python
            elif (m := _ROWS_FROM_CSV_RE.match(line)) is not None:
                if in_mock.category not in (MockCategory.SQL, MockCategory.READ):
                    raise CutParseError(
                        f"line {line_no}: ROWS FROM CSV is only supported "
                        f"for MOCK SQL and MOCK READ, not MOCK "
                        f"{in_mock.category.keyword}"
                    )
```

and change the body below it (which currently assumes SQL's named/header shape unconditionally):

```python
                resolved_path = (cut_dir / raw_path).resolve()
                header, raw_rows, row_lines = _read_csv_rows(
                    resolved_path, line_no, positional=False
                )
                assert header is not None
                for row_index, row in enumerate(raw_rows):
                    if len(row) != len(header):
                        raise CutParseError(
                            f"line {line_no}: ROWS FROM CSV {raw_path!r} "
                            f"row at CSV line {row_lines[row_index]} has "
                            f"{len(row)} cell(s) but the header has "
                            f"{len(header)} column(s)"
                        )
                in_mock.csv_source = CsvRowSource(
                    raw_path=raw_path,
                    resolved_path=resolved_path,
                    line=line_no,
                    positional=False,
                    header=header,
                    raw_rows=raw_rows,
                    row_lines=row_lines,
                )
```

to:

```python
                positional = in_mock.category is MockCategory.READ
                resolved_path = (cut_dir / raw_path).resolve()
                header, raw_rows, row_lines = _read_csv_rows(
                    resolved_path, line_no, positional=positional
                )
                if not positional:
                    assert header is not None
                    for row_index, row in enumerate(raw_rows):
                        if len(row) != len(header):
                            raise CutParseError(
                                f"line {line_no}: ROWS FROM CSV "
                                f"{raw_path!r} row at CSV line "
                                f"{row_lines[row_index]} has {len(row)} "
                                f"cell(s) but the header has "
                                f"{len(header)} column(s)"
                            )
                in_mock.csv_source = CsvRowSource(
                    raw_path=raw_path,
                    resolved_path=resolved_path,
                    line=line_no,
                    positional=positional,
                    header=header,
                    raw_rows=raw_rows,
                    row_lines=row_lines,
                )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_dsl_parser_csv_rows.py -v`
Expected: PASS (all tests, all slices)

- [ ] **Step 5: Run the full unit suite**

Run: `python -m pytest tests/unit -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add mockymock/dsl/parser.py tests/unit/test_dsl_parser_csv_rows.py
git commit -m "feat(dsl): parse ROWS FROM CSV for READ (headerless/positional)"
```

---

### Task 11: Refusal — widen the `FILE STATUS` requirement to cover CSV-sourced `READ` rows

**Files:**
- Modify: `mockymock/analysis/refusal.py`
- Modify: `tests/unit/test_refusal_file_status.py`

**Interfaces:**
- Consumes: `MockDirective.csv_source` (Task 5).
- Produces: `check_test_case`'s final loop's `needs_file_status` condition also covers `directive.csv_source is not None` for `READ`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_refusal_file_status.py`:

```python
def test_read_rows_from_csv_without_declared_file_status_refuses(tmp_path):
    from mockymock.dsl.model import CsvRowSource
    from pathlib import Path

    result = parse_cobol(SOURCE, filename="statchk.cbl")
    surface = analyze(result.ast)
    file_status_fields = analyze_file_status_fields(result.ast)
    suite = parse_cut(
        'TESTSUITE "s"\nTESTCASE "c"\n    MOCK READ NO-STATUS\n    END-MOCK\n'
        "    PERFORM MAIN-PROCESS\n"
    )
    directive = suite.test_cases[0].mocks[0]
    directive.csv_source = CsvRowSource(
        raw_path="x.csv",
        resolved_path=Path("x.csv"),
        line=1,
        positional=True,
        header=None,
        raw_rows=[["1"]],
        row_lines=[1],
    )
    reasons = check_test_case(surface, result.ast, suite.test_cases[0], file_status_fields)
    matches = [r for r in reasons if r.code == "UNRESOLVED_FILE_STATUS_TARGET"]
    assert len(matches) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/unit/test_refusal_file_status.py -v -k csv`
Expected: FAIL — `needs_file_status` today only checks `directive.rows is not None`, not `.csv_source`.

- [ ] **Step 3: Widen the condition**

In `mockymock/analysis/refusal.py`, change:

```python
        needs_file_status = directive.file_status is not None or (
            directive.category is MockCategory.READ and directive.rows is not None
        )
```

to:

```python
        needs_file_status = directive.file_status is not None or (
            directive.category is MockCategory.READ
            and (directive.rows is not None or directive.csv_source is not None)
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_refusal_file_status.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full unit suite**

Run: `python -m pytest tests/unit -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add mockymock/analysis/refusal.py tests/unit/test_refusal_file_status.py
git commit -m "fix(analysis): require FILE STATUS for CSV-sourced READ rows too"
```

---

### Task 12: Integration proof — `READ ROWS FROM CSV` example (N records + exhaustion)

**Files:**
- Create: `examples/custfile/CUSTFILE.cbl`
- Create: `examples/custfile/CUSTFILE.cut`
- Create: `examples/custfile/data/custfile.csv`
- Create: `examples/custfile/data/custfile_one.csv`
- Create: `examples/custfile/README.md`
- Modify: `tests/integration/test_cli.py`
- Modify: `README.md` (repo root — new example-table row)

**Interfaces:**
- Consumes: nothing new — end-to-end proof closing out Slice 3.

- [ ] **Step 1: Write the example program**

Create `examples/custfile/CUSTFILE.cbl`:

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTFILE.
      * Sequential customer-file reader driven entirely by
      * MOCK READ CUST-FILE ROWS FROM CSV -- no hand-written tally
      * branching, no INV.DAT-style sandbox file. FILE STATUS "10"
      * (end-of-file) exhausts the CSV rows and ends the loop.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO "CUSTFILE.DAT"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-CUST-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-REC.
           05  CUST-ID        PIC 9(5).
           05  CUST-NAME      PIC X(20).
           05  CUST-BAL       PIC 9(5)V99.

       WORKING-STORAGE SECTION.
       01  WS-CUST-STATUS     PIC X(2).
       01  WS-EOF             PIC X VALUE "N".
       01  WS-EOF-STATUS      PIC X(2) VALUE SPACES.
       01  WS-REC-COUNT       PIC 9(4) VALUE 0.
       01  WS-TOTAL-BAL       PIC 9(7)V99 VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT CUST-FILE.
           PERFORM READ-LOOP UNTIL WS-EOF = "Y".
           CLOSE CUST-FILE.

       READ-LOOP.
           READ CUST-FILE.
           IF WS-CUST-STATUS = "10"
               MOVE WS-CUST-STATUS TO WS-EOF-STATUS
               MOVE "Y" TO WS-EOF
           ELSE
               ADD 1 TO WS-REC-COUNT
               ADD CUST-BAL TO WS-TOTAL-BAL
           END-IF.
```

Same reasoning as `READROWS.cbl` in Task 4: `MOCK CLOSE CUST-FILE END-MOCK` has
an empty body, so `build_site_dispatch` emits its unconditional
default-success preamble (`MOVE "00" TO WS-CUST-STATUS`) when `CLOSE` fires —
which happens *after* the `READ-LOOP` exits, and therefore after
`WS-CUST-STATUS` last held `"10"`. Since `EXPECT`/`VERIFY` only run after
`PERFORM MAIN-PROCESS` returns, an `EXPECT` directly on `WS-CUST-STATUS` would
observe the `CLOSE` mock's `"00"`, not the exhaustion status. `WS-EOF-STATUS`
captures the real value at the moment `READ-LOOP` sees it, before `CLOSE` ever
runs.

- [ ] **Step 2: Add the CSV fixtures**

Create `examples/custfile/data/custfile.csv`:

```
1001,SMITH,100.00
1002,JONES,200.25
1003,"O'BRIEN, JR.",150.50
```

Create `examples/custfile/data/custfile_one.csv`:

```
2001,DOE,50.00
```

- [ ] **Step 3: Write the `.cut` file**

Create `examples/custfile/CUSTFILE.cut`:

```
TESTSUITE "CUSTFILE sequential read via ROWS FROM CSV"

TESTCASE "reads three customers then exhausts"
    MOCK OPEN CUST-FILE
    END-MOCK
    MOCK READ CUST-FILE
        ROWS FROM CSV "data/custfile.csv"
    END-MOCK
    MOCK CLOSE CUST-FILE
    END-MOCK
    PERFORM MAIN-PROCESS
    EXPECT WS-REC-COUNT TO BE 3
    EXPECT WS-TOTAL-BAL TO BE 450.75
    VERIFY READ CUST-FILE WAS PERFORMED 4 TIMES

TESTCASE "signals end-of-file via FILE STATUS 10 once rows are exhausted"
    MOCK OPEN CUST-FILE
    END-MOCK
    MOCK READ CUST-FILE
        ROWS FROM CSV "data/custfile_one.csv"
    END-MOCK
    MOCK CLOSE CUST-FILE
    END-MOCK
    PERFORM MAIN-PROCESS
    EXPECT WS-EOF-STATUS TO BE "10"
    VERIFY READ CUST-FILE WAS PERFORMED 2 TIMES
```

- [ ] **Step 4: Run it against the real toolchain**

Run: `python -m mockymock.cli.main run examples/custfile/CUSTFILE.cbl --cut examples/custfile/CUSTFILE.cut`

Expected: exit 0, `__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=0`.

- [ ] **Step 5: Add the integration test**

Add to `tests/integration/test_cli.py`:

```python
@requires_docker
def test_custfile_read_rows_from_csv_consumes_records_and_exhausts(capsys):
    root = Path(__file__).resolve().parents[2] / "examples" / "custfile"
    exit_code = main(
        ["run", str(root / "CUSTFILE.cbl"), "--cut", str(root / "CUSTFILE.cut")]
    )
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "RUN=2 FAILURES=0" in out
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest tests/integration/test_cli.py -v -k custfile`
Expected: PASS

- [ ] **Step 7: Write the example README**

Create `examples/custfile/README.md`:

```markdown
# CUSTFILE — `READ ... ROWS FROM CSV` (positional)

A sequential customer-file reader driven entirely by `MOCK READ CUST-FILE
ROWS FROM CSV "<path>"` — the headerless, positional counterpart to
`examples/custprog/`'s named `SQL` CSV form. Columns map positionally to
`CUST-REC`'s leaf fields in declaration order (`CUST-ID`, `CUST-NAME`,
`CUST-BAL`); no header row, no hand-written tally branching, no real
`CUSTFILE.DAT` needed in the sandbox.

| Boundary | Statement | Mocked by |
|----------|-----------|-----------|
| File open | `OPEN INPUT CUST-FILE` | `MOCK OPEN CUST-FILE` |
| Sequential read loop | `READ CUST-FILE` | `MOCK READ CUST-FILE ROWS FROM CSV "..."` |
| File close | `CLOSE CUST-FILE` | `MOCK CLOSE CUST-FILE` |

Things this example demonstrates on purpose:

- **Positional CSV mapping.** `data/custfile.csv` has no header row —
  column 1 maps to `CUST-ID`, column 2 to `CUST-NAME`, column 3 to
  `CUST-BAL`, exactly mirroring `CUST-REC`'s own field order. A quoted
  cell (`"O'BRIEN, JR."`) demonstrates the same CSV-quoting the `SQL` form
  uses.
- **`FILE STATUS`-driven exhaustion.** Once the CSV's rows are consumed,
  the mocked `READ` sets `WS-CUST-STATUS` to `"10"` (GnuCOBOL's real
  end-of-file code) automatically — the second `TESTCASE` captures that
  into `WS-EOF-STATUS` the instant `READ-LOOP` sees it (before `CLOSE`
  runs its own default-success preamble and overwrites `WS-CUST-STATUS`
  back to `"00"`) and asserts on `WS-EOF-STATUS` instead. `VERIFY READ
  CUST-FILE WAS PERFORMED 2 TIMES` confirms it took exactly one real read
  plus one exhausting read for a one-row CSV.
- **Automatic typing.** `CUST-BAL`'s cells (`100.00`, `200.25`, `150.50`)
  are resolved against its `PIC 9(5)V99` and emitted as bare numeric
  `MOVE`s; `CUST-NAME`'s cells are quoted alphanumeric `MOVE`s — no COBOL
  literal syntax in the CSV at all, just plain data.

Run it:

```bash
mockymock run examples/custfile/CUSTFILE.cbl --cut examples/custfile/CUSTFILE.cut
```
```

- [ ] **Step 8: Add a row to the repo-root README's example table**

In `README.md`, add a new row to the examples table (after the `examples/statelkup/` row):

```markdown
| [`examples/custfile/`](examples/custfile/) | `MOCK READ ... ROWS FROM CSV` — headerless, positional CSV mapped to a record's leaf fields |
```

- [ ] **Step 9: Commit**

```bash
git add examples/custfile tests/integration/test_cli.py README.md
git commit -m "test(integration): add CUSTFILE example for READ ROWS FROM CSV"
```

---

## Final — Documentation

### Task 13: Update all documentation, and fix the design doc's own contradictory example

**Files:**
- Modify: `.okf/dsl.md`
- Modify: `.okf/splicer.md`
- Modify: `.okf/analysis.md`
- Modify: `interface-contract.md`
- Modify: `.okf/integration.md`
- Modify: `.okf/log.md`
- Modify: `docs/2026-07-31-csv-sourced-rows-design.md`

No tests — this is a documentation-only task. Verify each change by re-reading the edited section against the shipped code (grep the referenced function/field names to confirm they still exist with the names used in prose).

- [ ] **Step 1: `interface-contract.md` — pin the new cobolparser surface**

Add a new bullet under the "v2 (mock-all-boundaries) additions" section (this is genuinely new surface, not previously pinned — see this plan's "Design decisions resolved during planning" note 1):

```markdown
- `cobolparser.models.data_items.PictureClause.size: int | None`,
  `.integer_digits: int | None`, `.decimal_digits: int | None`,
  `.total_digits: int | None`, `.is_signed: bool` — CSV row typing
  (`mockymock/analysis/csv_rows.py`) validates a cell value's width/sign
  against these before emitting a `MOVE`.
- `cobolparser.models.data_items.CobolDataItem.occurs_clause: OccursClause
  | None`, `.redefines: str | None` — gate positional (`READ`) CSV
  mapping: a record containing either anywhere in its leaf layout is
  refused (`CSV_RECORD_UNSUPPORTED_SHAPE`).
- `ASTNode.get_metadata(key, default=None)` / `.has_metadata(key)` (the
  generic metadata API every AST node exposes) and specifically
  `CobolDataItem.get_metadata("fd_file_name")` — set on each `01`-level
  **FILE SECTION** record by `cobolparser/parsers/divisions/data.py`'s FD
  tagging (verified against the pinned commit
  `4db83941dccefbf3d185d02a518378c37c392d46`), giving file name → record
  a direct link. **Correction:** `cobolparser.models.program.
  CobolFileDescription` and its `.data_records` list are never
  instantiated by the real parser — that class is only ever constructed
  in cobolparser's own unit tests. Do not depend on it; use the
  metadata-tagged FILE SECTION `data_items` instead.
```

- [ ] **Step 2: `.okf/integration.md` — mirror the same additions**

Add a row to the "Public API Surface Depended On" table:

```markdown
| `PictureClause.size`/`.integer_digits`/`.decimal_digits`/`.total_digits`/`.is_signed` | CSV row typing (width/sign validation before a MOVE) |
| `CobolDataItem.occurs_clause`, `.redefines` | positional CSV mapping's OCCURS/REDEFINES-anywhere gate |
| `ASTNode.get_metadata`/`.has_metadata`, `CobolDataItem.get_metadata("fd_file_name")` | file name → FILE SECTION record link for positional CSV mapping |
```

Add a Gotchas entry:

```markdown
**`CobolFileDescription`/`.data_records` is never populated by the real parser.** Verified empirically while building `mockymock/analysis/csv_rows.py`'s `READ`-CSV resolver: the FILE SECTION parser tags each `01`-level record with `set_metadata("fd_file_name", <FD's file name>)` instead of ever constructing a `CobolFileDescription` node — that class is only instantiated in cobolparser's own unit tests. Resolve file → record via `program.get_division("DATA")._sections["FILE"].data_items`, filtered by `.get_metadata("fd_file_name")`, not via `CobolFileDescription`.
```

- [ ] **Step 3: `.okf/dsl.md` — grammar tables and `ROWS` section**

Update the `## MOCK <kind> <key> forms` table's `READ` row — it currently reads `OPEN,CLOSE,READ,WRITE,REWRITE,DELETE,START,UNLOCK | same | bare key = file/record name`; leave that row as-is (still accurate) and add a new subsection after `### ROWS cursor sugar`:

```markdown
### `ROWS` for `READ`, and `ROWS FROM CSV`

`READ` (a bare-key category) now also accepts `ROWS`, mirroring `SQL`'s
syntax exactly: `MOCK READ <file> ROWS ( FIELD = value, ... ) ( ... )
END-MOCK` — `FIELD` names the record's own fields instead of `SQL` host
variables, but the grammar, per-row `EVALUATE`, and mutual exclusivity
with `body_lines` are identical. Unlike `SQL` (which sets `SQLCODE`),
`READ`'s trailer sets the target file's declared `FILE STATUS` field:
`"00"` on a matched row, `"10"` (GnuCOBOL's real end-of-file code) once
exhausted — which requires the file to declare a `FILE STATUS` field at
all (`UNRESOLVED_FILE_STATUS_TARGET` refuses otherwise, the same check
`FILE-STATUS IS` sugar already triggers).

`ROWS FROM CSV "<path>"` is a third row-source alternative, recognized as
a single line inside a `MOCK SQL`/`MOCK READ` body (not a suffix on the
opening `MOCK` line the way inline `ROWS` is): `<path>` resolves relative
to the `.cut` file's own directory. `SQL`'s form keeps a header row (named
columns); `READ`'s form is headerless — columns map positionally to the
record's elementary (leaf) fields in declaration order, depth-first
through nested groups. The parser's own job stops at syntax, file
existence, and (`SQL` only, since it self-describes its width via the
header) row/header arity — `parse_cut()` takes `.cut` text only, no COBOL
AST, so it cannot resolve field types or (for `READ`) the record's field
count itself. That resolution happens at splice-check time in
`mockymock/analysis/csv_rows.py::resolve_csv_row_sources`, called from
`checks.py::run_static_checks` alongside `analyze_file_status_fields`; its
resolved-rows table (keyed by `id(directive)`, mirroring
`orchestrator.py`'s `seen_statement_ids` pattern) threads into
`splice_program` → `build_site_dispatch` exactly the way
`file_status_fields` already does.

CSV cell text is plain data (`SMITH`, `100.00`), not COBOL literal syntax:
`csv_rows.py` resolves each target field's `PICTURE`, decides bare vs.
quoted, validates the value fits, and refuses (rather than silently
truncating/dropping a sign the way a raw COBOL `MOVE` would) on:
`CSV_FIELD_NOT_FOUND` (`SQL` only — an unresolvable header column),
`CSV_UNTYPEABLE_TARGET` (a group item, `POINTER`/`INDEX` usage, an
88-level condition name, or a level-66 `RENAMES` item), `CSV_VALUE_TOO_WIDE`,
`CSV_SIGN_MISMATCH`, `CSV_ARITY_MISMATCH` (`READ` only — a positional
row's cell count doesn't match the record's leaf-field count, reported for
the first mismatching row), `CSV_RECORD_UNSUPPORTED_SHAPE` (`READ` only —
the FD's record contains `OCCURS`/`REDEFINES` anywhere, or the FD declares
more than one `01`-level record), and `UNRESOLVED_FILE_RECORD` (`READ`
only — the file has no FD record at all). See
docs/2026-07-31-csv-sourced-rows-design.md for the full typing table and
its empirical basis.
```

- [ ] **Step 4: `.okf/splicer.md` — codegen changes**

In the `### ROWS cursor sugar` section (or wherever `build_rows_block` is described — search for it), add:

```markdown
**Generalized to be category-aware (docs/2026-07-31-csv-sourced-rows-design.md).**
`build_rows_block(tally_name, rows, category, file_status_field=None)`
now takes the mocked category: `SQL`'s trailer is unchanged (`MOVE 0/100 TO
SQLCODE`); `READ`'s trailer MOVEs `"00"`/`"10"` into `file_status_field`
(guaranteed non-`None` for `READ` — the refusal gate requires the file to
declare one before a `READ` `ROWS` directive reaches splicing). Because of
this, `build_site_dispatch`'s previously-unconditional default-success
`FILE-STATUS` preamble is now skipped whenever `directive.rows is not None
or directive.csv_source is not None` — the generalized `build_rows_block`
owns file-status emission per-branch instead of the preamble emitting it
once per dispatch regardless of which row fired.

`build_site_dispatch` also gained a `csv_rows: dict[int, list[list[tuple[str, str]]]] | None`
parameter (threaded from `splice_program`, itself threaded from
`checked.csv_rows` in `cli/main.py`): for a directive with
`csv_source is not None`, the rows come from this table (keyed by
`id(directive)`) instead of `directive.rows`. A directive whose
`csv_source` has no matching table entry is an invariant violation (the
refusal gate — `mockymock/analysis/csv_rows.py::resolve_csv_row_sources` —
should have refused it) and `build_site_dispatch` raises rather than
silently falling back to an empty body.
```

- [ ] **Step 5: `.okf/analysis.md` — new module and refusal codes**

Add to the module table near the top:

```markdown
| `csv_rows.py` | `resolve_csv_row_sources(suite, program)`: resolves every `MOCK SQL/READ ... ROWS FROM CSV` directive's cell text against the target's `PICTURE` (named WORKING-STORAGE lookup for `SQL`; flattened FD-record leaf fields for `READ`), producing the same `list[list[tuple[str,str]]]` shape `MockDirective.rows` already has for inline `ROWS`, keyed by `id(directive)`. Called from `checks.py::run_static_checks` alongside `analyze_file_status_fields`. See [dsl](dsl.md)'s `ROWS FROM CSV` section and docs/2026-07-31-csv-sourced-rows-design.md. |
```

Add a new refusal-code entry to the whole-suite/per-directive check summary near `UNRESOLVED_FILE_STATUS_TARGET`'s existing description:

```markdown
`csv_rows.resolve_csv_row_sources` (whole-suite, like `analyze_file_status_fields`, not per-`MockTestCase`): `CSV_FIELD_NOT_FOUND`, `CSV_UNTYPEABLE_TARGET`, `CSV_VALUE_TOO_WIDE`, `CSV_SIGN_MISMATCH`, `CSV_ARITY_MISMATCH`, `CSV_RECORD_UNSUPPORTED_SHAPE`, `UNRESOLVED_FILE_RECORD` — see [dsl](dsl.md) for what each means. `check_test_case`'s own `UNRESOLVED_FILE_STATUS_TARGET` check additionally fires for any `READ` directive using `ROWS` (either form) against a file with no declared `FILE STATUS` field, not only explicit `FILE-STATUS IS` sugar.
```

- [ ] **Step 6: `.okf/log.md` — dated entry**

Add (check the file's existing entry format first and match it — newest entries typically at the top):

```markdown
## 2026-07-31 — CSV-sourced ROWS for SQL and READ mocks

Implemented docs/2026-07-31-csv-sourced-rows-design.md: `ROWS FROM CSV
"<path>"` as a second row-source for `MOCK SQL ... ROWS` (alongside
inline parens), and extended the whole `ROWS` mechanism to `READ` (both
inline and CSV-sourced). New module `mockymock/analysis/csv_rows.py`
resolves CSV cell text against each target field's `PICTURE` at
splice-check time. Found during implementation: the design's assumed
`cobolparser.models.program.CobolFileDescription.data_records` API is
never populated by the real parser — the actual mechanism is
`CobolDataItem.get_metadata("fd_file_name")` on each `01`-level FILE
SECTION record (confirmed present at the pinned commit
`4db83941dccefbf3d185d02a518378c37c392d46`, no cobolparser bump needed).
Also added `UNRESOLVED_FILE_RECORD` (a file has no/ambiguous FD record) as
a necessary refusal code beyond the design doc's own list.
```

- [ ] **Step 7: Fix `docs/2026-07-31-csv-sourced-rows-design.md`'s own contradictory `READ` inline-`ROWS` example**

The doc's `### Grammar` section currently shows:

```cobol
*> READ — new category support, inline form (named, mirrors SQL's syntax)
MOCK READ CUST-FILE
    ROWS ( CUST-ID = 1001, CUST-NAME = "SMITH", CUST-BAL = 100.00 )
    ( CUST-ID = 1002, CUST-NAME = "O'BRIEN, JR.", CUST-BAL = 250.50 )
END-MOCK
```

Change it to match what was actually built (the doc's own prose already says "mirrors SQL's syntax" — this just fixes the illustration to match):

```cobol
*> READ — new category support, inline form (named, mirrors SQL's syntax)
MOCK READ CUST-FILE ROWS
    ( CUST-ID = 1001, CUST-NAME = "SMITH", CUST-BAL = 100.00 )
    ( CUST-ID = 1002, CUST-NAME = "O'BRIEN, JR.", CUST-BAL = 250.50 )
END-MOCK
```

- [ ] **Step 8: Verify every changed doc against the shipped code**

For each file touched in Steps 1-7, grep the function/field/code names used in the new prose against the actual source to confirm they match exactly (e.g. `grep -rn "resolve_csv_row_sources\|CSV_RECORD_UNSUPPORTED_SHAPE\|UNRESOLVED_FILE_RECORD\|fd_file_name" mockymock/`).

- [ ] **Step 9: Commit**

```bash
git add .okf/dsl.md .okf/splicer.md .okf/analysis.md interface-contract.md .okf/integration.md .okf/log.md docs/2026-07-31-csv-sourced-rows-design.md
git commit -m "docs: document CSV-sourced ROWS and pin the new cobolparser surface"
```

---

## Self-Review

**Spec coverage** (against `docs/2026-07-31-csv-sourced-rows-design.md`):
- `SQL` `ROWS FROM CSV`, header/named form → Tasks 5, 6, 7, 8. ✓
- `READ` `ROWS`, both inline and CSV, positional → Tasks 1, 2, 3, 4, 9, 10, 11, 12. ✓
- CSV auto-typing table (bare/quoted/SPACES/0, COMP-3, embedded-quote doubling) → Task 5 (`_render_value`), tested in `test_csv_rows.py`. ✓
- Refused-not-silently-handled (too-wide both directions, sign mismatch) → Task 5, tested. ✓
- `OCCURS`/`REDEFINES`-anywhere gate, multi-01-record gate → Task 9. ✓
- Relaxing the category gate (both regexes) → Tasks 1, 6, 10. ✓
- `MockDirective`/`CsvRowSource` model → Task 5. ✓
- Splice-time resolution (`csv_rows.py`, id-keyed table) → Tasks 5, 9. ✓
- `build_rows_block` generalization, conditional FILE-STATUS preamble → Task 2. ✓
- `FILE-STATUS IS` structurally unreachable inside a `ROWS` body — already true today (`_ROW_RE` is tried before `_FILE_STATUS_RE` whenever `in_mock.rows is not None`); the new `csv_source is not None` branch is checked even earlier in the same `elif` chain (Task 6, Step 3), so it inherits the identical property with no extra code needed. ✓ (verified, no separate task required)
- Implementation slices 1/2/3 → mirrored exactly as Slices 1/2/3 above. ✓
- Testing section (unit: every refusal path, typing table, arity, path resolution; integration: `READ`-CSV N-records + exhaustion, `SQL`-CSV parity) → Tasks 1-12's test steps + Tasks 4, 8, 12. ✓
- Companion CSV-scaffold idea and the open `cobolparser` leaf-enumeration dependency → correctly out of scope; Task 9 implements the "mockymock-local stopgap" the design doc explicitly allows, not the shared `cobolparser` API (which doesn't exist upstream — see Design Decision 1). ✓
- Docs to update → Task 13, plus the two additional docs (`interface-contract.md`, `.okf/integration.md`) the design doc's own list omitted. ✓

**Placeholder scan:** no "TBD"/"add error handling"/"similar to Task N" language anywhere above; every step shows the literal code to write or the literal command to run.

**Type consistency:** `CsvRowSource` (Task 5) and its consumers (Tasks 6, 9, 10) agree on field names (`raw_path`, `resolved_path`, `line`, `positional`, `header`, `raw_rows`, `row_lines`). `resolve_csv_row_sources`'s return shape (`tuple[dict[int, list[list[tuple[str, str]]]], list[RefusalReason]]`) is identical across Tasks 5, 7, 9. `build_rows_block`'s new signature (`tally_name, rows, category, file_status_field=None`) is consistent between Task 2's definition and Task 2's own updated test call. `build_site_dispatch`'s `csv_rows` parameter (Task 2) and `splice_program`'s (Task 7) agree on position (after `file_status_fields`) and type.

**Generated-COBOL semantics (traced, not just type-checked):** every `.cbl` fixture with a `MOCK CLOSE <file> END-MOCK` alongside a `READ`-exhaustion assertion (Tasks 4, 12) captures the exhaustion `FILE STATUS` into a dedicated `WS-EOF-STATUS` field *inside* `READ-LOOP`, before `CLOSE` fires — `CLOSE` is in `FILE_STATUS_CATEGORIES` and, with an empty mock body, unconditionally re-`MOVE`s `"00"` into the same status field via `build_site_dispatch`'s default-success preamble; since `EXPECT`/`VERIFY` only run after the whole `PERFORM` chain returns (`driver.py`), asserting directly on the file's own status field after a mocked `CLOSE` runs would silently observe `"00"` instead of `"10"`. Confirmed both `READROWS.cut` (Task 4) and `CUSTFILE.cut` (Task 12) assert on `WS-EOF-STATUS`, not `WS-CUST-STATUS`, for this reason.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-31-csv-sourced-rows.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
