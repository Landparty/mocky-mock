# SQL v1: EXEC SQL INCLUDE + Cursor ROWS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve `EXEC SQL INCLUDE <member> END-EXEC` (non-SQLCA, e.g. a DCLGEN host-variable copybook) via the existing `--copybook-path` mechanism instead of refusing the whole program, and add `MOCK SQL "<prefix>" ROWS` DSL sugar for cursor FETCH loops.

**Architecture:** Two independent, additive components. (1) `mockymock/splicer/sqlca.py`'s DATA DIVISION EXEC SQL transform resolves a non-SQLCA `INCLUDE <member>` by expanding a synthetic `COPY <member>.` snippet through cobolparser's public `expand_copybooks` and splicing the (normalized) result in place, re-scanning it in-line so an embedded DCLGEN `DECLARE ... TABLE` stanza is commented out by the transform's existing branch with no new recursion. (2) `MOCK SQL "..." ROWS (...) (...) END-MOCK` is new `.cut` grammar that stores structured rows on `MockDirective` instead of free-form `body_lines`; at splice time (`mockymock/splicer/injector.py`), a rows-bearing directive codegens a tally-driven `EVALUATE`/`WHEN` block instead of splicing `body_lines` verbatim.

**Tech Stack:** Python 3.11+, `cobolparser` (editable sibling dependency), GnuCOBOL 3.2 in Docker (`mockymock-cobc` container) for integration tests, `pytest`/`ruff`/`black`/`mypy`.

## Global Constraints

- No new refusal codes: unresolvable `EXEC SQL INCLUDE <member>` reuses `UNRESOLVED_COPYBOOK` (the same code plain unresolved `COPY` already uses); nested `EXEC SQL INCLUDE` inside a resolved member reuses `UNSUPPORTED_DATA_DIVISION_EXEC`.
- Only cobolparser's **public** surface may be used: `cobolparser.preprocess.{expand_copybooks, normalize_fixed_format, CopybookNotFoundError}` (all in `cobolparser/preprocess/__init__.py`'s `__all__`). Do **not** import `cobolparser.preprocess.path_resolver` or `cobolparser.preprocess.models` — those are not declared public surface and are not pinned by `interface-contract.md`.
- `EXEC SQL INCLUDE` resolution goes through a synthetic `"       COPY <member>."` snippet passed to `expand_copybooks(snippet, copybook_paths=...)` — this is the literal same resolution path plain `COPY` already uses (same extensions, same case rules, same path-traversal protection), not a reimplementation.
- Only one level of `EXEC SQL INCLUDE` resolution is supported: a resolved member's own content is re-scanned for `DECLARE TABLE`/`DECLARE CURSOR`/`BEGIN|END DECLARE SECTION` (commented out, as today), but a second live `EXEC SQL INCLUDE` inside it refuses rather than resolving.
- `ROWS` is SQL-category only (`MOCK CALL/CICS/DLI ... ROWS` is a `CutParseError`), and is mutually exclusive with a hand-written mock body — a `ROWS` directive's `body_lines` stays empty; a non-`ROWS` directive's `rows` stays `None`.
- `ROWS` exhaustion always sets `SQLCODE 100` (not configurable in v1).
- Match this codebase's existing style exactly: function-local imports for heavyweight/optional dependencies (cobolparser inside `sqlca.py`'s resolution helper, not at module scope), plain-function pytest tests (no test classes), `RefusalReason(code=..., message=...)` for every refusal.
- Every task's tests run via `python -m pytest tests/unit -v` (or the specific test file/function) from the repo root with `.venv` active; the final task runs the full suite plus `ruff check .`, `black --check .`, `mypy mockymock/` (matching `.github/workflows/ci.yml`).
- Design doc: `docs/2026-07-09-sql-v1-include-cursor-rows-design.md`. Read it before starting — this plan implements it directly.

---

### Task 1: `ROWS` grammar — `MockDirective.rows` + `.cut` parsing

**Files:**
- Modify: `mockymock/dsl/model.py`
- Modify: `mockymock/dsl/parser.py`
- Test: `tests/unit/test_dsl_parser_v2.py`

**Interfaces:**
- Produces: `MockDirective.rows: list[list[tuple[str, str]]] | None` — `None` for an ordinary mock; for a `ROWS` mock, a list of rows, each row a list of `(field, value)` pairs in source order. Mutually exclusive with `body_lines` (a `ROWS` mock's `body_lines` stays `[]`).
- Consumes: nothing from other tasks.

- [ ] **Step 1: Add the `rows` field to `MockDirective`**

In `mockymock/dsl/model.py`, change:

```python
@dataclass
class MockDirective:
    category: MockCategory
    key: str
    body_lines: list[str] = field(default_factory=list)
```

to:

```python
@dataclass
class MockDirective:
    category: MockCategory
    key: str
    body_lines: list[str] = field(default_factory=list)
    rows: list[list[tuple[str, str]]] | None = None
    """Structured rows for `MOCK SQL "..." ROWS (...) (...) END-MOCK`.
    `None` for an ordinary mock (its body lives in `body_lines` instead);
    populated only for SQL-category ROWS mocks, mutually exclusive with
    `body_lines`."""
```

(Leave `describe()` and `program_name` unchanged — they don't need to know about `rows`.)

- [ ] **Step 2: Write the failing grammar tests**

Append to `tests/unit/test_dsl_parser_v2.py`:

```python
ROWS_CUT = """\
TESTSUITE "cursor rows"

TESTCASE "fetches two rows then exhausts"
    MOCK SQL "FETCH EMP-CURSOR" ROWS
        ( EMP-NAME = "SMITH", EMP-ID = 100 )
        ( EMP-NAME = "JONES", EMP-ID = 101 )
    END-MOCK
    PERFORM MAIN-PARA
    EXPECT WS-ROW-COUNT TO BE 2
"""


def test_rows_mock_parses_each_row_as_field_value_pairs():
    case = parse_cut(ROWS_CUT).test_cases[0]
    fetch_mock = case.mocks[0]
    assert fetch_mock.category is MockCategory.SQL
    assert fetch_mock.key == "FETCH EMP-CURSOR"
    assert fetch_mock.rows == [
        [("EMP-NAME", '"SMITH"'), ("EMP-ID", "100")],
        [("EMP-NAME", '"JONES"'), ("EMP-ID", "101")],
    ]
    assert fetch_mock.body_lines == []


def test_rows_mock_value_may_contain_a_comma_inside_quotes():
    cut = """\
TESTSUITE "quoted comma"

TESTCASE "one row"
    MOCK SQL "FETCH EMP-CURSOR" ROWS
        ( EMP-NAME = "SMITH, JR." )
    END-MOCK
    PERFORM MAIN-PARA
"""
    case = parse_cut(cut).test_cases[0]
    assert case.mocks[0].rows == [[("EMP-NAME", '"SMITH, JR."')]]


def test_rows_on_non_sql_category_is_rejected():
    cut = """\
TESTSUITE "bad rows"

TESTCASE "call rows"
    MOCK CALL "PGMA" ROWS
        ( X = 1 )
    END-MOCK
    PERFORM MAIN-PARA
"""
    with pytest.raises(CutParseError, match="ROWS is only supported for MOCK SQL"):
        parse_cut(cut)


def test_empty_rows_block_is_rejected():
    cut = """\
TESTSUITE "empty rows"

TESTCASE "no rows"
    MOCK SQL "FETCH EMP-CURSOR" ROWS
    END-MOCK
    PERFORM MAIN-PARA
"""
    with pytest.raises(CutParseError, match="no rows"):
        parse_cut(cut)


def test_malformed_row_syntax_is_rejected():
    cut = """\
TESTSUITE "bad row"

TESTCASE "bad"
    MOCK SQL "FETCH EMP-CURSOR" ROWS
        EMP-NAME = "SMITH"
    END-MOCK
    PERFORM MAIN-PARA
"""
    with pytest.raises(CutParseError, match="malformed ROWS row"):
        parse_cut(cut)


def test_malformed_row_field_assignment_is_rejected():
    cut = """\
TESTSUITE "bad field"

TESTCASE "bad"
    MOCK SQL "FETCH EMP-CURSOR" ROWS
        ( EMP-NAME "SMITH" )
    END-MOCK
    PERFORM MAIN-PARA
"""
    with pytest.raises(CutParseError, match="malformed ROWS field assignment"):
        parse_cut(cut)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_dsl_parser_v2.py -v -k rows`
Expected: FAIL — `ROWS` isn't part of the grammar yet, so the first test fails with either a `CutParseError` (malformed MOCK line) or an `AttributeError`/mismatched parse, and the "rejected" tests fail because no `CutParseError` is raised (or the wrong one is).

- [ ] **Step 4: Implement the grammar**

In `mockymock/dsl/parser.py`:

1. Change the import line to also bring in `MockCategory` explicitly if not already (it already is — no change needed there).

2. Change `_MOCK_QUOTED_RE`:

```python
_MOCK_QUOTED_RE = re.compile(
    rf'^MOCK\s+(?P<cat>{_QUOTED_CATS})\s+"(?P<key>[^"]*)"(?:\s+(?P<rows>ROWS))?$'
)
```

3. Add two new module-level regexes right after `_COMMENT_RE`:

```python
_ROW_RE = re.compile(r"^\((?P<pairs>.+)\)$")
_ROW_PAIR_RE = re.compile(r"^(?P<field>[A-Za-z][A-Za-z0-9-]*)\s*=\s*(?P<value>.+)$")
```

4. Add a quote-aware comma splitter, right after `_validate_expectation`:

```python
def _split_top_level(text: str, sep: str) -> list[str]:
    """Split `text` on `sep`, ignoring any occurrence inside a '...' or
    "..." span -- so a ROWS row value like EMP-NAME = "SMITH, JR." isn't
    cut at the comma inside the quoted literal."""
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in text:
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
            current.append(char)
            continue
        if char == sep:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts
```

5. Replace the `if in_mock is not None:` block inside `parse_cut`'s loop:

```python
        if in_mock is not None:
            if _END_MOCK_RE.match(line):
                in_mock = None
            else:
                in_mock.body_lines.append(line)
            continue
```

with:

```python
        if in_mock is not None:
            if _END_MOCK_RE.match(line):
                if in_mock.rows is not None and not in_mock.rows:
                    raise CutParseError(
                        f"line {line_no}: MOCK {in_mock.describe()} ROWS "
                        f"block has no rows -- give at least one row or "
                        f"drop ROWS entirely"
                    )
                in_mock = None
            elif in_mock.rows is not None:
                row_match = _ROW_RE.match(line)
                if row_match is None:
                    raise CutParseError(
                        f"line {line_no}: malformed ROWS row {line!r} -- "
                        f"expected ( FIELD = value, FIELD = value, ... )"
                    )
                row: list[tuple[str, str]] = []
                for raw_pair in _split_top_level(row_match.group("pairs"), ","):
                    pair_match = _ROW_PAIR_RE.match(raw_pair.strip())
                    if pair_match is None:
                        raise CutParseError(
                            f"line {line_no}: malformed ROWS field "
                            f"assignment {raw_pair.strip()!r} -- expected "
                            f"FIELD = value"
                        )
                    row.append(
                        (pair_match.group("field"), pair_match.group("value").strip())
                    )
                in_mock.rows.append(row)
            else:
                in_mock.body_lines.append(line)
            continue
```

6. Replace the `_MOCK_QUOTED_RE` branch inside `parse_cut`'s loop:

```python
        elif (m := _MOCK_QUOTED_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: MOCK outside TESTCASE")
            if not m.group("key"):
                raise CutParseError(
                    f'line {line_no}: empty MOCK {m.group("cat")} key -- '
                    f"the quoted key must name what to mock"
                )
            in_mock = _open_mock(
                MockDirective(
                    category=_resolve_category(m.group("cat")),
                    key=m.group("key"),
                ),
                line_no,
            )
            in_mock_line = line_no
```

with:

```python
        elif (m := _MOCK_QUOTED_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: MOCK outside TESTCASE")
            if not m.group("key"):
                raise CutParseError(
                    f'line {line_no}: empty MOCK {m.group("cat")} key -- '
                    f"the quoted key must name what to mock"
                )
            category = _resolve_category(m.group("cat"))
            if m.group("rows") and category is not MockCategory.SQL:
                raise CutParseError(
                    f"line {line_no}: ROWS is only supported for MOCK SQL, "
                    f'not MOCK {m.group("cat")}'
                )
            in_mock = _open_mock(
                MockDirective(
                    category=category,
                    key=m.group("key"),
                    rows=[] if m.group("rows") else None,
                ),
                line_no,
            )
            in_mock_line = line_no
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_dsl_parser_v2.py -v`
Expected: PASS (all tests in the file, including the pre-existing ones — the `_MOCK_QUOTED_RE` change must not break non-ROWS parsing).

- [ ] **Step 6: Commit**

```bash
git add mockymock/dsl/model.py mockymock/dsl/parser.py tests/unit/test_dsl_parser_v2.py
git commit -m "feat(dsl): add MOCK SQL ... ROWS grammar for cursor row sequences"
```

---

### Task 2: `ROWS` codegen — `build_rows_block` + wire into `build_site_dispatch`

**Files:**
- Modify: `mockymock/splicer/injector.py`
- Test: `tests/unit/test_injector.py`

**Interfaces:**
- Consumes: `MockDirective.rows` (Task 1).
- Produces: `build_rows_block(tally_name: str, rows: list[list[tuple[str, str]]]) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_injector.py`:

```python
from mockymock.splicer.injector import build_rows_block


def test_rows_block_codegens_indexed_when_branches_and_exhaustion():
    lines = build_rows_block(
        "UT-SQL-FETCH-EMP-CURSOR-TALLY",
        [
            [("EMP-NAME", '"SMITH"'), ("EMP-ID", "100")],
            [("EMP-NAME", '"JONES"'), ("EMP-ID", "101")],
        ],
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


def test_dispatch_splices_rows_block_using_resolved_tally_name():
    site = _site(MockCategory.SQL, "SQL", keys=(), match_text="FETCH EMP-CURSOR")
    case = MockTestCase(
        name="cursor",
        mocks=[
            MockDirective(
                MockCategory.SQL,
                "FETCH EMP-CURSOR",
                rows=[[("EMP-NAME", '"SMITH"')]],
            )
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    joined = "\n".join(_dispatch(suite, site))
    assert "ADD 1 TO UT-SQL-FETCH-EMP-CURSOR-TALLY" in joined
    assert "EVALUATE TRUE" in joined
    assert "WHEN UT-SQL-FETCH-EMP-CURSOR-TALLY = 1" in joined
    assert 'MOVE "SMITH" TO EMP-NAME' in joined
    assert "WHEN OTHER" in joined
    assert "MOVE 100 TO SQLCODE" in joined
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_injector.py -v -k rows`
Expected: FAIL — `build_rows_block` doesn't exist yet (`ImportError`), and the dispatch test fails because `directive.rows` is ignored.

- [ ] **Step 3: Implement `build_rows_block` and wire it in**

In `mockymock/splicer/injector.py`, add this function after `build_site_dispatch` (or before it — placement doesn't matter, but keep it near its only caller):

```python
def build_rows_block(tally_name: str, rows: list[list[tuple[str, str]]]) -> list[str]:
    """EVALUATE block for a MOCK SQL ... ROWS directive: row N's MOVEs fire
    once `tally_name` (already incremented by the caller before this runs,
    so the first call sees tally == 1) reaches N, followed by MOVE 0 TO
    SQLCODE; once rows are exhausted, MOVE 100 TO SQLCODE (DB2's real "not
    found" code) fires instead."""
    lines = ["EVALUATE TRUE"]
    for index, row in enumerate(rows, start=1):
        lines.append(f"    WHEN {tally_name} = {index}")
        for field, value in row:
            lines.append(f"        MOVE {value} TO {field}")
        lines.append("        MOVE 0 TO SQLCODE")
    lines.append("    WHEN OTHER")
    lines.append("        MOVE 100 TO SQLCODE")
    lines.append("END-EVALUATE")
    return lines
```

Then change `build_site_dispatch`'s loop body from:

```python
        directive = matches[0]
        lines.append(f'               WHEN "{index:03d}"')
        lines.append(
            f"                   ADD 1 TO "
            f"{registry.name(directive.category, directive.key)}"
        )
        lines.extend(f"                   {body}" for body in directive.body_lines)
```

to:

```python
        directive = matches[0]
        tally_name = registry.name(directive.category, directive.key)
        lines.append(f'               WHEN "{index:03d}"')
        lines.append(f"                   ADD 1 TO {tally_name}")
        if directive.rows is not None:
            lines.extend(
                f"                   {body}"
                for body in build_rows_block(tally_name, directive.rows)
            )
        else:
            lines.extend(f"                   {body}" for body in directive.body_lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_injector.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/injector.py tests/unit/test_injector.py
git commit -m "feat(splicer): codegen ROWS mocks as a tally-driven EVALUATE block"
```

---

### Task 3: `EXEC SQL INCLUDE <member>` resolution in `sqlca.py`

**Files:**
- Modify: `mockymock/splicer/sqlca.py`
- Modify: `tests/unit/test_sqlca.py`

**Interfaces:**
- Produces: `transform_data_division_exec(lines: list[str], copybook_paths: list[str] | None = None) -> tuple[list[str], list[RefusalReason]]` — new optional parameter, default `None` preserves today's behavior for every existing caller that doesn't pass it.
- Consumes: `mockymock.analysis.refusal.check_expansion_warnings` (already exists, already imported elsewhere), `cobolparser.preprocess.{expand_copybooks, normalize_fixed_format, CopybookNotFoundError}` (public API — see Global Constraints).

- [ ] **Step 1: Write the failing tests**

First, in `tests/unit/test_sqlca.py`, **replace** the existing `test_include_other_member_refuses` (this behavior is changing: an unresolvable INCLUDE with no `--copybook-path` now refuses `UNRESOLVED_COPYBOOK`, not `UNSUPPORTED_DATA_DIVISION_EXEC`):

Replace:

```python
def test_include_other_member_refuses():
    src = BASE[:5] + ["    EXEC SQL INCLUDE ORDHOST END-EXEC."] + BASE[5:]
    lines, reasons = transform_data_division_exec(src)
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_DATA_DIVISION_EXEC"
    assert "ORDHOST" in reasons[0].message
```

with:

```python
def test_include_other_member_without_copybook_path_refuses_unresolved():
    src = BASE[:5] + ["    EXEC SQL INCLUDE ORDHOST END-EXEC."] + BASE[5:]
    lines, reasons = transform_data_division_exec(src)
    assert len(reasons) == 1
    assert reasons[0].code == "UNRESOLVED_COPYBOOK"
    assert "ORDHOST" in reasons[0].message
```

Then append these new tests to the same file:

```python
def test_include_other_member_resolves_with_copybook_path(tmp_path):
    copybook_dir = tmp_path / "copybooks"
    copybook_dir.mkdir()
    (copybook_dir / "ORDHOST.CPY").write_text(
        "       01  ORD-HOST.\n           05  ORD-AMOUNT PIC 9(5)V99.\n"
    )
    src = BASE[:5] + ["    EXEC SQL INCLUDE ORDHOST END-EXEC."] + BASE[5:]
    lines, reasons = transform_data_division_exec(
        src, copybook_paths=[str(copybook_dir)]
    )
    assert reasons == []
    joined = "\n".join(lines)
    assert "ORD-AMOUNT PIC 9(5)V99" in joined
    assert "EXEC SQL INCLUDE ORDHOST END-EXEC." not in joined


def test_include_member_with_embedded_declare_table_is_commented_out(tmp_path):
    """A DCLGEN-style copybook embeds its own EXEC SQL DECLARE ... TABLE
    stanza right before the host-variable record -- the re-scan after
    splicing must catch and comment it out via the same DECLARE-TABLE
    branch that already handles a directly-authored one, with no new
    recursion code."""
    copybook_dir = tmp_path / "copybooks"
    copybook_dir.mkdir()
    (copybook_dir / "CUSTREC.CPY").write_text(
        "           EXEC SQL DECLARE CUSTREC TABLE\n"
        "           ( CUST_ID     INTEGER NOT NULL,\n"
        "             CUST_NAME   CHAR(30) )\n"
        "           END-EXEC.\n"
        "       01  CUSTREC.\n"
        "           05  CUST-ID         PIC S9(9) COMP-5.\n"
        "           05  CUST-NAME       PIC X(30).\n"
    )
    src = BASE[:5] + ["    EXEC SQL INCLUDE CUSTREC END-EXEC."] + BASE[5:]
    lines, reasons = transform_data_division_exec(
        src, copybook_paths=[str(copybook_dir)]
    )
    assert reasons == []
    joined = "\n".join(lines)
    assert "01  CUSTREC." in joined
    assert "05  CUST-ID" in joined
    live_declare = [
        ln
        for ln in lines
        if "DECLARE CUSTREC TABLE" in ln and not ln.strip().startswith("*>")
    ]
    assert live_declare == []


def test_nested_include_inside_resolved_member_refuses(tmp_path):
    copybook_dir = tmp_path / "copybooks"
    copybook_dir.mkdir()
    (copybook_dir / "OUTER.CPY").write_text(
        "       EXEC SQL INCLUDE INNER END-EXEC.\n"
    )
    (copybook_dir / "INNER.CPY").write_text("       01  INNER-FIELD PIC X(5).\n")
    src = BASE[:5] + ["    EXEC SQL INCLUDE OUTER END-EXEC."] + BASE[5:]
    lines, reasons = transform_data_division_exec(
        src, copybook_paths=[str(copybook_dir)]
    )
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_DATA_DIVISION_EXEC"
    assert "nested" in reasons[0].message
    assert "INNER" in reasons[0].message


def test_include_missing_member_with_copybook_path_refuses_unresolved(tmp_path):
    copybook_dir = tmp_path / "copybooks"
    copybook_dir.mkdir()
    src = BASE[:5] + ["    EXEC SQL INCLUDE NOPE END-EXEC."] + BASE[5:]
    lines, reasons = transform_data_division_exec(
        src, copybook_paths=[str(copybook_dir)]
    )
    assert len(reasons) == 1
    assert reasons[0].code == "UNRESOLVED_COPYBOOK"
    assert "NOPE" in reasons[0].message


def test_sqlca_include_still_uses_generated_fields_not_resolution(tmp_path):
    """INCLUDE SQLCA must keep using the hardcoded SQLCA_FIELDS path even
    when a --copybook-path happens to be given -- it must never go through
    member resolution (there is no SQLCA.CPY file to find)."""
    copybook_dir = tmp_path / "copybooks"
    copybook_dir.mkdir()
    lines, reasons = transform_data_division_exec(
        BASE, copybook_paths=[str(copybook_dir)]
    )
    assert reasons == []
    assert "01  SQLCA." in "\n".join(lines)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_sqlca.py -v`
Expected: FAIL — `transform_data_division_exec` doesn't accept `copybook_paths` yet (`TypeError`), and the replaced test now expects `UNRESOLVED_COPYBOOK` which the current code doesn't produce.

- [ ] **Step 3: Implement the resolution + re-scan + nested-INCLUDE tracking**

In `mockymock/splicer/sqlca.py`:

1. Update the import line:

```python
from mockymock.analysis.refusal import RefusalReason, check_expansion_warnings
```

2. Update the module docstring's INCLUDE bullet — change:

```
- Any other DATA DIVISION EXEC SQL (INCLUDE <member>, WHENEVER, ...) is a
  whole-program refusal (UNSUPPORTED_DATA_DIVISION_EXEC): an INCLUDE pulls
  in host-variable declarations this tool cannot resolve (same spirit as
  UNRESOLVED_COPYBOOK), and anything unrecognized fails closed.
```

to:

```
- `EXEC SQL INCLUDE <member> END-EXEC` (member != SQLCA) is resolved the
  same way plain `COPY` is: a synthetic `COPY <member>.` snippet is
  expanded through cobolparser's public `expand_copybooks` against
  `copybook_paths`, and the (normalized) result is spliced in and
  re-scanned in place -- so a DCLGEN-style member's own embedded
  `EXEC SQL DECLARE ... TABLE ... END-EXEC` stanza gets commented out by
  this module's existing DECLARE-TABLE branch automatically. No
  `--copybook-path`, or the member can't be found, refuses
  UNRESOLVED_COPYBOOK (the same code plain unresolved COPY uses). A second,
  live `EXEC SQL INCLUDE` found while re-scanning already-spliced content
  refuses UNSUPPORTED_DATA_DIVISION_EXEC (only one level of resolution is
  supported). Any other unrecognized DATA DIVISION EXEC SQL (WHENEVER,
  ...) still fails closed the same way.
```

3. Add the resolution helper, right before `_handle_block`:

```python
def _resolve_include_member(
    member: str, copybook_paths: list[str] | None
) -> tuple[list[str] | None, list[RefusalReason]]:
    """Resolve `member` the same way plain COPY is resolved: build a
    synthetic `COPY <member>.` snippet and expand it through cobolparser's
    public `expand_copybooks` -- not a reimplementation of copybook path
    resolution, so INCLUDE resolves exactly the way COPY does (same
    extensions, same case rules, same path-traversal protection; see
    cobolparser.preprocess.path_resolver, which this module deliberately
    does not import -- it isn't in cobolparser.preprocess's __all__).
    Returns (normalized lines, []) on success, or (None, [<refusal>]) on
    failure -- never both a result and a reason."""
    if not copybook_paths:
        return None, [
            RefusalReason(
                code="UNRESOLVED_COPYBOOK",
                message=(
                    f"EXEC SQL INCLUDE {member} could not be resolved -- "
                    f"pass --copybook-path pointing at the copybook's "
                    f"directory"
                ),
            )
        ]

    from cobolparser.preprocess import (
        CopybookNotFoundError,
        expand_copybooks,
        normalize_fixed_format,
    )

    try:
        expansion = expand_copybooks(
            f"       COPY {member}.", copybook_paths=copybook_paths
        )
    except CopybookNotFoundError:
        return None, [
            RefusalReason(
                code="UNRESOLVED_COPYBOOK",
                message=(
                    f"EXEC SQL INCLUDE {member} could not be resolved in "
                    f"{copybook_paths} -- pass --copybook-path pointing at "
                    f"the copybook's directory"
                ),
            )
        ]

    expansion_reasons = check_expansion_warnings(expansion)
    if expansion_reasons:
        return None, expansion_reasons

    normalized = normalize_fixed_format(
        expansion.expanded_source.splitlines()
    ).splitlines()
    return normalized, []
```

4. Replace `transform_data_division_exec` entirely with:

```python
def transform_data_division_exec(
    lines: list[str],
    copybook_paths: list[str] | None = None,
) -> tuple[list[str], list[RefusalReason]]:
    """Return (new lines, refusal reasons) for the DATA DIVISION EXEC SQL
    blocks in already-normalized free-form `lines`.

    All transforms here replace or comment out WHOLE lines, so a block that
    shares a line with other content -- data-item text before the
    `EXEC SQL`, or trailing content after the `END-EXEC.` -- refuses
    (UNSUPPORTED_DATA_DIVISION_EXEC) instead of silently deleting the
    sibling content. `EXEC SQL` / `END-EXEC` appearing inside VALUE-clause
    string literals is ignored entirely (see `_search_outside_literals`).

    `copybook_paths` is threaded through to a resolved EXEC SQL INCLUDE
    member's content -- see `_resolve_include_member`. When an INCLUDE is
    resolved, the scan does NOT advance past the newly-spliced lines
    (`include_splice_end` tracks the boundary instead): this lets the
    DECLARE-TABLE/DECLARE-CURSOR/BEGIN-END-DECLARE-SECTION branches below
    catch content the resolved member itself embeds (a DCLGEN copybook
    always carries its own `EXEC SQL DECLARE ... TABLE ... END-EXEC`) with
    no separate recursion path, while a second live INCLUDE found inside
    that re-scanned region refuses instead of resolving (only one level of
    INCLUDE resolution is supported)."""
    result = list(lines)
    reasons: list[RefusalReason] = []

    in_data_division = False
    include_splice_end: int | None = None
    index = 0
    while index < len(result):
        if include_splice_end is not None and index >= include_splice_end:
            include_splice_end = None
        line = result[index]
        exec_match = None
        if _DATA_DIVISION_RE.match(line):
            in_data_division = True
        elif _PROCEDURE_DIVISION_RE.match(line):
            in_data_division = False
        elif in_data_division:
            exec_match = _search_outside_literals(_EXEC_SQL_RE, line)
        if exec_match is not None:
            end = index
            end_match = _search_outside_literals(_END_EXEC_RE, result[end])
            while end_match is None:
                end += 1
                if end == len(result):
                    break
                end_match = _search_outside_literals(_END_EXEC_RE, result[end])
            if end == len(result):
                reasons.append(
                    RefusalReason(
                        code="UNSUPPORTED_DATA_DIVISION_EXEC",
                        message=(
                            f"EXEC SQL block starting at line {index + 1} has "
                            f"no END-EXEC"
                        ),
                    )
                )
                break
            shared_line_problem = _shared_line_problem(
                result, index, exec_match, end, end_match
            )
            if shared_line_problem is not None:
                reasons.append(shared_line_problem)
                index = end + 1
                continue
            block = " ".join(
                " ".join(result[i].upper().split()) for i in range(index, end + 1)
            )
            nested_include = include_splice_end is not None
            index, splice_end = _handle_block(
                result, index, end, block, reasons, copybook_paths, nested_include
            )
            if splice_end is not None:
                include_splice_end = splice_end
            continue
        index += 1

    return result, reasons
```

5. Replace `_handle_block` entirely with:

```python
def _handle_block(
    result: list[str],
    start: int,
    end: int,
    block: str,
    reasons: list[RefusalReason],
    copybook_paths: list[str] | None,
    nested_include: bool,
) -> tuple[int, int | None]:
    """Apply the transform for one EXEC SQL block spanning result[start:end+1]
    (already uppercased/whitespace-collapsed into `block`). Returns (next
    scan index, splice-end index or None) -- the second element is set only
    when this call spliced in a resolved EXEC SQL INCLUDE member's content,
    so the caller can track "inside spliced INCLUDE content" for the
    nested-INCLUDE refusal. The first element is `start` (not past the
    splice) exactly when that happens, so the caller re-scans the newly
    inserted lines instead of skipping them."""
    if re.search(r"\bINCLUDE\s+SQLCA\b", block):
        replacement = [
            "      *> EXEC SQL INCLUDE SQLCA replaced by mockymock-generated SQLCA:"
        ] + [f"       {field}" for field in SQLCA_FIELDS]
        result[start : end + 1] = replacement
        return start + len(replacement), None

    if re.search(r"\b(BEGIN|END)\s+DECLARE\s+SECTION\b", block) or re.search(
        r"\bDECLARE\b.*\b(TABLE|CURSOR)\b", block
    ):
        for i in range(start, end + 1):
            if result[i].strip():
                result[i] = "      *> " + result[i]
        return end + 1, None

    include_match = re.search(r"\bINCLUDE\s+(\S+)", block)
    if include_match:
        member = include_match.group(1).rstrip(".")
        if nested_include:
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_DATA_DIVISION_EXEC",
                    message=(
                        f"EXEC SQL INCLUDE {member} at line {start + 1} is "
                        f"nested inside another resolved EXEC SQL INCLUDE -- "
                        f"only one level of EXEC SQL INCLUDE resolution is "
                        f"supported; inline {member}'s content directly"
                    ),
                )
            )
            return end + 1, None
        resolved_lines, resolve_reasons = _resolve_include_member(
            member, copybook_paths
        )
        if resolved_lines is None:
            reasons.extend(resolve_reasons)
            return end + 1, None
        replacement = [
            f"      *> EXEC SQL INCLUDE {member} replaced by resolved "
            f"copybook content:"
        ] + resolved_lines
        result[start : end + 1] = replacement
        new_index = start + len(replacement)
        return start, new_index

    reasons.append(
        RefusalReason(
            code="UNSUPPORTED_DATA_DIVISION_EXEC",
            message=(
                f"unrecognized DATA DIVISION EXEC SQL block at line "
                f"{start + 1}: {block[:80]!r} -- fail closed"
            ),
        )
    )
    return end + 1, None
```

(Note the INCLUDE-member-resolved branch returns `start` as the next scan index, not `new_index` — this is the re-scan behavior. Every other branch returns `end + 1`/`start + len(replacement)` unchanged from before.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_sqlca.py -v`
Expected: PASS (all tests in the file, including every pre-existing test — `copybook_paths` defaulting to `None` must not change any existing behavior except the one test updated in Step 1).

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/sqlca.py tests/unit/test_sqlca.py
git commit -m "feat(splicer): resolve EXEC SQL INCLUDE host-variable copybooks via --copybook-path"
```

---

### Task 4: CLI wiring + end-to-end Docker integration test

**Files:**
- Modify: `mockymock/cli/main.py`
- Create: `tests/integration/fixtures/sql_cursor_example/CUSTPROG.cbl`
- Create: `tests/integration/fixtures/sql_cursor_example/CUSTPROG.cut`
- Create: `tests/integration/fixtures/sql_cursor_example/copybooks/CUSTREC.CPY`
- Create: `tests/integration/test_sql_cursor_rows_example.py`

**Interfaces:**
- Consumes: `transform_data_division_exec(..., copybook_paths=...)` (Task 3), `MOCK SQL "..." ROWS` DSL + codegen (Tasks 1-2).
- Produces: nothing new for later tasks.

- [ ] **Step 1: Wire `--copybook-path` into `_cmd_run`'s two `transform_data_division_exec` calls**

In `mockymock/cli/main.py`, inside `_cmd_run`, change:

```python
    _, data_exec_reasons = transform_data_division_exec(lines)
```

to:

```python
    _, data_exec_reasons = transform_data_division_exec(
        lines, copybook_paths=args.copybook_path
    )
```

and change:

```python
    lines, _ = transform_data_division_exec(lines)
```

to:

```python
    lines, _ = transform_data_division_exec(lines, copybook_paths=args.copybook_path)
```

(`_cmd_generate` never calls `transform_data_division_exec` — no change needed there.)

- [ ] **Step 2: Create the fixture program**

Create `tests/integration/fixtures/sql_cursor_example/CUSTPROG.cbl`:

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTPROG.
      * Cursor-driven customer lister: EXEC SQL INCLUDE resolves a
      * DCLGEN-style host-variable copybook (with its own embedded
      * EXEC SQL DECLARE TABLE stanza) into real WORKING-STORAGE data
      * items, then a DECLARE CURSOR/OPEN/FETCH-loop/CLOSE walks it,
      * driven entirely by a MOCK SQL "FETCH ..." ROWS block.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           EXEC SQL INCLUDE CUSTREC END-EXEC.
       01  WS-EOF             PIC X VALUE "N".
       01  WS-ROW-COUNT       PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           EXEC SQL
               DECLARE CUST_CURSOR CURSOR FOR
               SELECT CUST_ID, CUST_NAME FROM CUSTOMERS
           END-EXEC.
           EXEC SQL
               OPEN CUST_CURSOR
           END-EXEC.
           PERFORM FETCH-LOOP UNTIL WS-EOF = "Y".
           EXEC SQL
               CLOSE CUST_CURSOR
           END-EXEC.

       FETCH-LOOP.
           EXEC SQL
               FETCH CUST_CURSOR INTO :CUST-ID, :CUST-NAME
           END-EXEC.
           IF SQLCODE = 100
               MOVE "Y" TO WS-EOF
           ELSE
               ADD 1 TO WS-ROW-COUNT
           END-IF.
```

Create `tests/integration/fixtures/sql_cursor_example/copybooks/CUSTREC.CPY`:

```
           EXEC SQL DECLARE CUSTOMERS TABLE
           ( CUST_ID     INTEGER NOT NULL,
             CUST_NAME   CHAR(30) )
           END-EXEC.
       01  CUSTREC.
           05  CUST-ID         PIC S9(9) COMP-5.
           05  CUST-NAME       PIC X(30).
```

Create `tests/integration/fixtures/sql_cursor_example/CUSTPROG.cut`:

```
TESTSUITE "CUSTPROG cursor via ROWS"

TESTCASE "fetches two customers then exhausts"
    MOCK SQL "DECLARE CUST_CURSOR"
    END-MOCK
    MOCK SQL "OPEN CUST_CURSOR"
    END-MOCK
    MOCK SQL "FETCH CUST_CURSOR" ROWS
        ( CUST-ID = 100, CUST-NAME = "SMITH" )
        ( CUST-ID = 101, CUST-NAME = "JONES" )
    END-MOCK
    MOCK SQL "CLOSE CUST_CURSOR"
    END-MOCK
    PERFORM MAIN-PROCESS
    EXPECT WS-ROW-COUNT TO BE 2
    VERIFY SQL "FETCH CUST_CURSOR" WAS PERFORMED 3 TIMES
```

- [ ] **Step 3: Write the integration test**

Create `tests/integration/test_sql_cursor_rows_example.py`:

```python
"""End-to-end proof for EXEC SQL INCLUDE host-variable copybook resolution
+ MOCK SQL ... ROWS cursor sugar: a DCLGEN-shaped copybook (with its own
embedded EXEC SQL DECLARE TABLE stanza) is resolved via --copybook-path,
and a DECLARE CURSOR/OPEN/FETCH-loop/CLOSE is driven entirely by a
MOCK SQL "FETCH ..." ROWS block, compiled with GnuCOBOL in the
mockymock-cobc container and executed for real."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sql_cursor_example"


@requires_docker
def test_cursor_rows_example_passes():
    exit_code = main(
        [
            "run",
            str(FIXTURE_DIR / "CUSTPROG.cbl"),
            "--cut",
            str(FIXTURE_DIR / "CUSTPROG.cut"),
            "--copybook-path",
            str(FIXTURE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_cursor_rows_example_fails_when_row_count_expectation_is_wrong(
    tmp_path: Path,
):
    cut = (FIXTURE_DIR / "CUSTPROG.cut").read_text()
    broken = tmp_path / "CUSTPROG.cut"
    broken.write_text(
        cut.replace("EXPECT WS-ROW-COUNT TO BE 2", "EXPECT WS-ROW-COUNT TO BE 3")
    )
    exit_code = main(
        [
            "run",
            str(FIXTURE_DIR / "CUSTPROG.cbl"),
            "--cut",
            str(broken),
            "--copybook-path",
            str(FIXTURE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 1


@requires_docker
def test_cursor_rows_example_refuses_without_copybook_path():
    """Without --copybook-path, EXEC SQL INCLUDE CUSTREC cannot resolve --
    proves the refusal fires end-to-end through the CLI, not just in the
    sqlca.py unit tests."""
    exit_code = main(
        [
            "run",
            str(FIXTURE_DIR / "CUSTPROG.cbl"),
            "--cut",
            str(FIXTURE_DIR / "CUSTPROG.cut"),
        ]
    )
    assert exit_code == 1
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/integration/test_sql_cursor_rows_example.py -v`
Expected: PASS if Docker is reachable (all 3 tests); SKIPPED (not FAIL) for all 3 if it isn't — `requires_docker` self-skips (see `tests/integration/_docker.py`). If Docker is reachable and any test fails, read the printed compile/runtime output (`mockymock run` prints `compiled.stderr` on compile failure) before changing anything — don't guess at the fix.

- [ ] **Step 5: Commit**

```bash
git add mockymock/cli/main.py tests/integration/fixtures/sql_cursor_example tests/integration/test_sql_cursor_rows_example.py
git commit -m "feat(cli): thread --copybook-path into EXEC SQL INCLUDE resolution for run"
```

---

### Task 5: Documentation — README, OKF bundle, audit finding

**Files:**
- Modify: `README.md`
- Modify: `.okf/splicer.md`
- Modify: `.okf/dsl.md`
- Modify: `docs/2026-07-06-real-world-readiness-audit.md`
- Modify: `.okf/log.md`

**Interfaces:** none — documentation only, no code interfaces.

- [ ] **Step 1: Update `README.md`**

In the `.cut` DSL section, find this bullet:

```
- `EXEC SQL INCLUDE SQLCA END-EXEC` is replaced with a generated SQLCA, so
  mock bodies can set `SQLCODE`.
```

and change it to:

```
- `EXEC SQL INCLUDE SQLCA END-EXEC` is replaced with a generated SQLCA, so
  mock bodies can set `SQLCODE`. `EXEC SQL INCLUDE <member> END-EXEC` for
  any other member (e.g. a DCLGEN host-variable copybook) is resolved via
  `--copybook-path` the same way a plain `COPY <member>.` is, exposing its
  host variables as real WORKING-STORAGE fields a mock body can `MOVE`
  into; without a matching `--copybook-path`, or if the member can't be
  found, it refuses `UNRESOLVED_COPYBOOK`. Only one level of `EXEC SQL
  INCLUDE` resolves — a member that itself contains another live `EXEC SQL
  INCLUDE` refuses.
```

Find the sentence documenting `MOCK CALL WS-PGM-NAME` / `VERIFY` tally fields (the bullet starting "Every mock gets a tally field...") and add a new bullet immediately after it:

```
- `MOCK SQL "<prefix>" ROWS ( FIELD = value, ... ) ( FIELD = value, ... )
  END-MOCK` is sugar for a cursor FETCH loop: each row's fields are MOVEd
  and `SQLCODE` is set to 0 on the Nth call (matching the mock's own tally
  field reaching N); once rows run out, `SQLCODE` is set to 100 (DB2's
  "not found" code). SQL-only; mutually exclusive with a hand-written mock
  body.
```

- [ ] **Step 2: Update `.okf/splicer.md`**

Find the table row:

```
| `EXEC SQL INCLUDE <member>` (anything else) | whole-program refusal `UNSUPPORTED_DATA_DIVISION_EXEC` — an INCLUDE pulls in host-variable declarations this tool cannot resolve, same spirit as `UNRESOLVED_COPYBOOK` |
```

and change it to:

```
| `EXEC SQL INCLUDE <member>` (anything else) | resolved via `--copybook-path` — a synthetic `COPY <member>.` snippet is expanded through cobolparser's public `expand_copybooks` (not `path_resolver` internals, which aren't in `cobolparser.preprocess`'s `__all__`) and the normalized result is spliced in and re-scanned in place, so an embedded `DECLARE ... TABLE` stanza (DCLGEN-style) gets commented out by the branch above with no new recursion. No `--copybook-path`, or member not found → `UNRESOLVED_COPYBOOK` (same code plain unresolved `COPY` uses). A second live `EXEC SQL INCLUDE` found while re-scanning already-spliced content → `UNSUPPORTED_DATA_DIVISION_EXEC` (only one level of resolution supported) |
```

Add a short new subsection right after the existing "Generated SQLCA (sqlca.py)" section's table (before whatever follows it), matching the existing prose style:

```markdown
**EXEC SQL INCLUDE member resolution**: unlike SQLCA (a hardcoded field
list), a non-SQLCA `INCLUDE <member>` has no fixed content -- it must be
read from disk. Resolution deliberately goes through the *public*
`cobolparser.preprocess.expand_copybooks` on a synthetic one-line
`COPY <member>.` snippet, not `cobolparser.preprocess.path_resolver`'s
`find_copybook_file`/`CopybookSearchPath` -- those live outside
`cobolparser.preprocess`'s `__all__` and are not pinned by
`interface-contract.md`. This also means INCLUDE resolves exactly the way
plain COPY does (same extensions, same case rules, same path-traversal
protection) for free, rather than risking a second resolution
implementation that quietly diverges from the first.
```

- [ ] **Step 3: Update `.okf/dsl.md`**

Find the `MockDirective` row in its attributes table:

```
| `MockDirective` | `category, key, body_lines: list[str]` | `.program_name` is v1-compat alias for `.key` (CALL-only meaning); `.describe()` renders `.cut`-style text (`CALL "X"`, `CALL WS-PGM`, `READ INFILE`) used in refusal messages |
```

and change it to:

```
| `MockDirective` | `category, key, body_lines: list[str], rows: list[list[tuple[str, str]]] \| None` | `.program_name` is v1-compat alias for `.key` (CALL-only meaning); `.describe()` renders `.cut`-style text (`CALL "X"`, `CALL WS-PGM`, `READ INFILE`) used in refusal messages; `rows` is set only for a `MOCK SQL "..." ROWS` directive and is mutually exclusive with `body_lines` |
```

Add a new subsection near the end of the file (matching its existing "Gotchas"-style prose), documenting the grammar:

```markdown
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
```

- [ ] **Step 4: Update `docs/2026-07-06-real-world-readiness-audit.md`**

In Finding 5's table, find:

```
| `EXEC SQL INCLUDE <member>` (non-SQLCA) | refused `UNSUPPORTED_DATA_DIVISION_EXEC` | copybook-style SQL includes block the file |
```

and change it to:

```
| `EXEC SQL INCLUDE <member>` (non-SQLCA) | **resolved 2026-07-09** via `--copybook-path` — see [docs/2026-07-09-sql-v1-include-cursor-rows-design.md](2026-07-09-sql-v1-include-cursor-rows-design.md) | closed |
```

Directly below Finding 5's table (before "**What closing it takes:**"), add:

```markdown
**Partially resolved 2026-07-09** — the non-SQLCA `EXEC SQL INCLUDE
<member>` row above is closed (host-variable copybooks now resolve the
same way `COPY` does); the `EXEC SQL DECLARE CURSOR` row was already
closed by an earlier `sqlca.py` change (DECLARE CURSOR is commented out
declaratively; OPEN/FETCH/CLOSE were always handled by the generic
boundary-mocking machinery). The remaining rows in this table are
unaffected.
```

- [ ] **Step 5: Add a dated `.okf/log.md` entry**

Prepend (log entries are newest-first, matching the existing 2026-07-09 entry already at the top) a new entry to `.okf/log.md`:

```markdown
## 2026-07-09 (Feature: EXEC SQL INCLUDE host-var copybooks + cursor ROWS sugar)
* **What shipped**: `EXEC SQL INCLUDE <member> END-EXEC` (non-SQLCA) now
  resolves via `--copybook-path` — a synthetic `COPY <member>.` snippet
  expanded through cobolparser's public `expand_copybooks`, spliced in and
  re-scanned in place so an embedded DCLGEN `DECLARE ... TABLE` stanza gets
  commented out automatically. Closes the "copybook-style SQL includes
  block the file" row of Finding 5 in the real-world-readiness audit. Also
  added `MOCK SQL "<prefix>" ROWS ( ... ) ( ... ) END-MOCK` DSL sugar,
  codegenning a tally-driven `EVALUATE`/`WHEN` block for cursor FETCH
  loops instead of requiring a hand-written tally/SQLCODE mock body.
* **Deliberate non-goal, verified during design**: `find_copybook_file` /
  `CopybookSearchPath` (`cobolparser.preprocess.path_resolver` /
  `.models`) are **not** in `cobolparser.preprocess`'s `__all__` — reaching
  into them would have added dependency surface `interface-contract.md`
  shouldn't pin. Resolution instead routes through the already-public
  `expand_copybooks` on a synthetic one-line `COPY <member>.` snippet,
  spiked directly (not just reasoned about) to confirm it resolves,
  inlines embedded `EXEC SQL DECLARE TABLE` content verbatim, and raises
  the public `CopybookNotFoundError` on a miss.
* **Scope deliberately deferred**: nested `EXEC SQL INCLUDE` (a resolved
  member containing another live INCLUDE) refuses rather than resolving;
  `ROWS`' exhaustion `SQLCODE` is fixed at 100, not overridable; `ROWS` is
  SQL-only, not generalized to other categories.
* See [docs/2026-07-09-sql-v1-include-cursor-rows-design.md](../docs/2026-07-09-sql-v1-include-cursor-rows-design.md).
```

- [ ] **Step 6: Verify the docs match the code**

Run:

```bash
grep -rn "UNSUPPORTED_DATA_DIVISION_EXEC.*INCLUDE\|INCLUDE.*cannot resolve" README.md .okf/ docs/2026-07-06-real-world-readiness-audit.md
```

Expected: no matches referring to the *old* "INCLUDE always refuses" behavior — every remaining `UNSUPPORTED_DATA_DIVISION_EXEC` mention should be about the nested-INCLUDE case or genuinely-unrecognized EXEC SQL, not plain member resolution. Fix any stale wording this surfaces.

- [ ] **Step 7: Commit**

```bash
git add README.md .okf/splicer.md .okf/dsl.md docs/2026-07-06-real-world-readiness-audit.md .okf/log.md
git commit -m "docs: document EXEC SQL INCLUDE resolution and ROWS cursor sugar"
```

---

### Task 6: Full-suite verification

**Files:** none (verification only).

**Interfaces:** none.

- [ ] **Step 1: Run the full unit + integration suite**

Run: `python -m pytest tests/ -v`
Expected: PASS (integration tests requiring Docker either PASS or SKIP, never FAIL, per `requires_docker`'s self-skip behavior).

- [ ] **Step 2: Run lint/format/type checks matching CI**

Run:

```bash
python -m ruff check .
python -m black --check .
python -m mypy mockymock/
```

Expected: all three exit 0. If `black --check` fails, run `python -m black .` to reformat, re-run `pytest`, and commit the formatting fix separately. If `mypy` flags the new `rows: list[list[tuple[str, str]]] | None` field or the new function signatures, add/adjust type annotations to satisfy it rather than suppressing with `# type: ignore` (matching this repo's existing pragmatic-but-real mypy usage).

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "chore: fix lint/format/type issues from SQL v1 work"
```

(Skip this step entirely if Step 2 was already clean — don't create an empty commit.)
