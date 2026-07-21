# PROVIDER Parameterized Test Cases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `PROVIDER`/`HEADER`/`ROW` block to the `.cut` DSL so one `TESTCASE "..." USING PROVIDER <name>` template expands, at parse time, into one ordinary test case per data row.

**Architecture:** `mockymock/dsl/parser.py` grows a small provider registry during its existing single-pass scan, then — after the whole file is parsed — replaces every provider-bound `TESTCASE` in `suite.test_cases` with N ordinary `MockTestCase` objects (one per row, `{ColumnName}` placeholders substituted into `MOVE`/`EXPECT` values). Every other module (analysis, splicer, runtime, report, cli) is untouched: they only ever see the already-expanded, ordinary cases.

**Tech Stack:** Python 3, `re` (stdlib), `pytest`. No new dependencies.

Spec: `docs/2026-07-20-provider-parameterized-test-cases-design.md` (read this first if anything below is ambiguous — it has the full rationale).

## Global Constraints

- `PROVIDER`/`HEADER`/`ROW`/`USING`/`PROVIDER` are new DSL keywords, case-sensitive uppercase — no lenient-casing exception (unlike `END-MOCK`).
- No changes to `mockymock/analysis/`, `mockymock/splicer/`, `mockymock/runtime/`, `mockymock/report/`, or `mockymock/cli/` — the feature is fully contained in `mockymock/dsl/`.
- A `TESTCASE` with no `USING PROVIDER` must be byte-for-byte unaffected — no scanning or substitution happens on it. This is a strict backward-compatibility requirement; every existing test in `tests/unit/test_dsl_parser.py` and every existing `examples/*/*.cut` file must keep passing/parsing unmodified.
- Placeholder substitution applies only to `MOVE` values and `EXPECT` values — never to `MOCK` bodies, `MOVE` targets, `EXPECT` data-names, `PERFORM` target/thru, or `VERIFY` key/expectation.
- All new tests follow this repo's existing pytest conventions (see `tests/unit/test_dsl_parser.py` for style — plain functions, `pytest.raises(CutParseError, match=...)`, no test classes).

---

### Task 1: `DataProvider` model + `PROVIDER`/`HEADER`/`ROW` grammar

**Files:**
- Modify: `mockymock/dsl/model.py` (add `DataProvider` dataclass)
- Modify: `mockymock/dsl/parser.py` (add regexes, parser state, `PROVIDER`/`HEADER`/`ROW` line handling — no `TESTCASE` binding yet, no expansion yet)
- Test: `tests/unit/test_dsl_parser.py`

**Interfaces:**
- Produces: `mockymock.dsl.model.DataProvider` — `@dataclass` with fields `name: str`, `line: int = 0`, `header: list[str] = field(default_factory=list)`, `rows: list[list[str]] = field(default_factory=list)`, `row_lines: list[int] = field(default_factory=list)`.
- Produces (parser-internal, not exported): module-level regexes `_PROVIDER_RE`, `_HEADER_RE`, `_PROVIDER_ROW_RE` in `parser.py`; inside `parse_cut()`, locals `providers: dict[str, DataProvider]`, `current_provider: DataProvider | None`, and a nested `_close_provider()` helper. Task 2 consumes all of these by name.

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/unit/test_dsl_parser.py`:

```python
# --- PROVIDER parameterized test cases: grammar ------------------------------


def test_provider_block_parses_without_affecting_unrelated_cases():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER StateNames\n"
        "    HEADER Abbreviation, Name\n"
        '    ROW "AZ", "Arizona"\n'
        '    ROW "KY", "Kentucky"\n'
        'TESTCASE "unrelated"\n'
        "    PERFORM MAIN\n"
    )
    suite = parse_cut(text)
    assert len(suite.test_cases) == 1
    assert suite.test_cases[0].name == "unrelated"


def test_provider_row_before_header_raises():
    text = 'TESTSUITE "s"\n' "PROVIDER StateNames\n" '    ROW "AZ", "Arizona"\n'
    with pytest.raises(CutParseError, match="line 3: ROW before HEADER"):
        parse_cut(text)


def test_provider_row_arity_mismatch_raises():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER StateNames\n"
        "    HEADER Abbreviation, Name\n"
        '    ROW "AZ"\n'
    )
    with pytest.raises(
        CutParseError,
        match=r"line 4: ROW has 1 value\(s\) but PROVIDER 'StateNames'.*2 column\(s\)",
    ):
        parse_cut(text)


def test_provider_with_zero_rows_raises():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER StateNames\n"
        "    HEADER Abbreviation, Name\n"
        'TESTCASE "c"\n'
        "    PERFORM MAIN\n"
    )
    with pytest.raises(
        CutParseError, match="line 2: PROVIDER 'StateNames' has no ROWs"
    ):
        parse_cut(text)


def test_duplicate_provider_name_raises_with_both_lines():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER StateNames\n"
        "    HEADER Abbreviation, Name\n"
        '    ROW "AZ", "Arizona"\n'
        "PROVIDER StateNames\n"
        "    HEADER Abbreviation, Name\n"
        '    ROW "KY", "Kentucky"\n'
    )
    with pytest.raises(
        CutParseError,
        match=r"line 5: duplicate PROVIDER 'StateNames' \(first declared at line 2\)",
    ):
        parse_cut(text)


def test_provider_before_testsuite_raises():
    with pytest.raises(CutParseError, match="line 1: PROVIDER before TESTSUITE"):
        parse_cut("PROVIDER StateNames\n    HEADER A, B\n    ROW 1, 2\n")


def test_header_outside_provider_raises():
    text = 'TESTSUITE "s"\n' "HEADER A, B\n"
    with pytest.raises(CutParseError, match="line 2: HEADER outside PROVIDER"):
        parse_cut(text)


def test_row_outside_provider_raises():
    text = 'TESTSUITE "s"\n' '    ROW "x"\n'
    with pytest.raises(CutParseError, match="line 2: ROW outside PROVIDER"):
        parse_cut(text)


def test_duplicate_header_in_provider_raises():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER StateNames\n"
        "    HEADER Abbreviation, Name\n"
        "    HEADER A, B\n"
    )
    with pytest.raises(
        CutParseError, match="line 4: duplicate HEADER in PROVIDER 'StateNames'"
    ):
        parse_cut(text)


def test_provider_row_values_preserve_commas_inside_quotes():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER Names\n"
        "    HEADER Full-Name\n"
        '    ROW "SMITH, JR."\n'
        'TESTCASE "c"\n'
        "    PERFORM MAIN\n"
    )
    # If the comma inside the quoted value had split the row into two
    # fields, this would raise a ROW-arity CutParseError against the
    # 1-column HEADER instead of parsing cleanly.
    suite = parse_cut(text)
    assert len(suite.test_cases) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_dsl_parser.py -k provider -v`
Expected: every new test FAILs — most with `CutParseError: line N: unrecognized statement: 'PROVIDER StateNames'` (or similar), since `PROVIDER`/`HEADER`/`ROW` aren't recognized yet.

- [ ] **Step 3: Implement the grammar**

In `mockymock/dsl/model.py`, add this class after `VerifyDirective` and before `MockTestCase`:

```python
@dataclass
class DataProvider:
    """A named, columnar test-data table declared with `PROVIDER <name>` /
    `HEADER <col>, ...` / `ROW <value>, ...`. Resolved and consumed
    entirely within parser.py's `_expand_providers` -- never stored on
    MockTestSuite/MockTestCase, so every downstream consumer (analysis,
    splicer, runtime, report, cli) sees only ordinary, already-expanded
    MockTestCase objects and never learns PROVIDER exists."""

    name: str
    line: int = 0
    """1-based .cut line of the PROVIDER header."""
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    row_lines: list[int] = field(default_factory=list)
    """1-based .cut line of each row in `rows`, same index alignment."""
```

In `mockymock/dsl/parser.py`:

1. Add `DataProvider` to the import from `mockymock.dsl.model`:

```python
from mockymock.dsl.model import (
    DataProvider,
    ExpectDirective,
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
    VerifyDirective,
)
```

2. Add three new regexes immediately after `_ROW_PAIR_RE` (the last regex constant before `class CutParseError`):

```python
_PROVIDER_RE = re.compile(r"^PROVIDER\s+(?P<name>[A-Za-z0-9][A-Za-z0-9-]*)$")
_HEADER_RE = re.compile(
    r"^HEADER\s+(?P<fields>[A-Za-z][A-Za-z0-9-]*(?:\s*,\s*[A-Za-z][A-Za-z0-9-]*)*)$"
)
_PROVIDER_ROW_RE = re.compile(r"^ROW\s+(?P<values>.+)$")
```

3. Inside `parse_cut()`, right after the existing `mock_lines: dict[...] = {}` declaration (before the `def _open_mock(...)` closure), add:

```python
    providers: dict[str, DataProvider] = {}
    current_provider: DataProvider | None = None

    def _close_provider() -> None:
        nonlocal current_provider
        if current_provider is not None and not current_provider.rows:
            raise CutParseError(
                f"line {current_provider.line}: PROVIDER "
                f"{current_provider.name!r} has no ROWs -- give at least "
                f"one row or drop the PROVIDER entirely"
            )
        current_provider = None
```

4. In the main `for line_no, raw_line in enumerate(...)` loop, add three new `elif` branches. Insert them right after the `TESTSUITE` branch (`elif (m := _TESTSUITE_RE.match(line)) is not None: ...`) and before the `TESTCASE` branch:

```python
        elif (m := _PROVIDER_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: PROVIDER before TESTSUITE")
            _close_provider()
            name = m.group("name")
            if name in providers:
                raise CutParseError(
                    f"line {line_no}: duplicate PROVIDER {name!r} (first "
                    f"declared at line {providers[name].line})"
                )
            current_provider = DataProvider(name=name, line=line_no)
            providers[name] = current_provider
        elif (m := _HEADER_RE.match(line)) is not None:
            if current_provider is None:
                raise CutParseError(f"line {line_no}: HEADER outside PROVIDER")
            if current_provider.header:
                raise CutParseError(
                    f"line {line_no}: duplicate HEADER in PROVIDER "
                    f"{current_provider.name!r}"
                )
            current_provider.header = [
                field.strip() for field in m.group("fields").split(",")
            ]
        elif (m := _PROVIDER_ROW_RE.match(line)) is not None:
            if current_provider is None:
                raise CutParseError(f"line {line_no}: ROW outside PROVIDER")
            if not current_provider.header:
                raise CutParseError(
                    f"line {line_no}: ROW before HEADER in PROVIDER "
                    f"{current_provider.name!r}"
                )
            values = [
                v.strip() for v in _split_top_level(m.group("values"), ",")
            ]
            if len(values) != len(current_provider.header):
                raise CutParseError(
                    f"line {line_no}: ROW has {len(values)} value(s) but "
                    f"PROVIDER {current_provider.name!r} HEADER has "
                    f"{len(current_provider.header)} column(s)"
                )
            current_provider.rows.append(values)
            current_provider.row_lines.append(line_no)
```

5. In the `TESTCASE` branch (`elif (m := _TESTCASE_RE.match(line)) is not None:`), add a `_close_provider()` call as its first line, right after the existing `if suite is None: raise ...` check:

```python
        elif (m := _TESTCASE_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: TESTCASE before TESTSUITE")
            _close_provider()
            tags = _TAG_RE.findall(m.group("tags") or "")
```

(leave the rest of the existing TESTCASE branch body unchanged for this task)

6. Right after the main `for` loop ends, before the existing `if in_mock is not None: raise ...` check, add:

```python
    _close_provider()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_dsl_parser.py -v`
Expected: all tests PASS, including every pre-existing test in the file (nothing regressed).

- [ ] **Step 5: Commit**

```bash
git add mockymock/dsl/model.py mockymock/dsl/parser.py tests/unit/test_dsl_parser.py
git commit -m "feat: parse PROVIDER/HEADER/ROW data-table blocks in .cut files"
```

---

### Task 2: `USING PROVIDER` binding + parse-time expansion

**Files:**
- Modify: `mockymock/dsl/parser.py` (extend `_TESTCASE_RE`, add expansion machinery, wire it into `parse_cut()`'s return)
- Test: `tests/unit/test_dsl_parser.py`, `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `DataProvider` (Task 1), the `providers`/`current_provider`/`_close_provider` scaffolding already inside `parse_cut()` (Task 1).
- Produces: module-level `_PLACEHOLDER_RE`, `_expand_providers(test_cases, pending)`, `_substitute(text, provider, row, case_name, line_no)`, `_display_value(raw)`, `_instantiate_row(case, provider, row, row_index)` in `parser.py`. `parse_cut()` now returns a suite whose `test_cases` are fully expanded — this is the feature's public contract; no other module needs to change to consume it.

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/unit/test_dsl_parser.py`:

```python
# --- PROVIDER parameterized test cases: binding & expansion ------------------

PROVIDER_CUT = """\
TESTSUITE "state lookup"

PROVIDER StateNames
    HEADER Abbreviation, Name
    ROW "AZ", "Arizona"
    ROW "KY", "Kentucky"
    ROW "XX", "*Undefined*"

TESTCASE "lookup state" USING PROVIDER StateNames
    MOVE {Abbreviation} TO WS-STATE-CODE
    PERFORM LOOKUP-STATE
    EXPECT WS-STATE-NAME TO BE {Name}
"""


def test_using_provider_expands_into_one_case_per_row():
    suite = parse_cut(PROVIDER_CUT)
    assert len(suite.test_cases) == 3


def test_expanded_case_names_and_substituted_values():
    suite = parse_cut(PROVIDER_CUT)
    names = [case.name for case in suite.test_cases]
    assert names == [
        "lookup state [row 1: AZ]",
        "lookup state [row 2: KY]",
        "lookup state [row 3: XX]",
    ]
    first = suite.test_cases[0]
    assert first.setup_moves == [('"AZ"', "WS-STATE-CODE")]
    assert first.expectations[0].expected_value == '"Arizona"'
    third = suite.test_cases[2]
    assert third.expectations[0].expected_value == '"*Undefined*"'


def test_expanded_case_line_points_at_its_own_row():
    suite = parse_cut(PROVIDER_CUT)
    # ROW "AZ" is line 5, ROW "KY" is line 6, ROW "XX" is line 7.
    assert [case.line for case in suite.test_cases] == [5, 6, 7]


PROVIDER_WITH_MOCK_AND_TAGS_CUT = """\
TESTSUITE "s"

PROVIDER Nums
    HEADER N
    ROW 1
    ROW 2

TESTCASE "c" TAGS "fast" USING PROVIDER Nums
    MOCK CALL "X"
        MOVE 0 TO RETURN-CODE
    END-MOCK
    MOVE {N} TO WS-N
    PERFORM MAIN
    VERIFY "X" WAS CALLED ONCE
"""


def test_mocks_tags_verify_inherited_unchanged_across_rows():
    suite = parse_cut(PROVIDER_WITH_MOCK_AND_TAGS_CUT)
    assert len(suite.test_cases) == 2
    for case in suite.test_cases:
        assert case.tags == ["fast"]
        assert len(case.mocks) == 1
        assert case.mocks[0].program_name == "X"
        assert case.verifications[0].expectation == "ONCE"
    assert suite.test_cases[0].setup_moves == [("1", "WS-N")]
    assert suite.test_cases[1].setup_moves == [("2", "WS-N")]


def test_value_with_no_placeholder_repeated_identically():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER Nums\n"
        "    HEADER N\n"
        "    ROW 1\n"
        "    ROW 2\n"
        'TESTCASE "c" USING PROVIDER Nums\n'
        "    MOVE 999 TO WS-FIXED\n"
        "    MOVE {N} TO WS-N\n"
        "    PERFORM MAIN\n"
    )
    suite = parse_cut(text)
    assert suite.test_cases[0].setup_moves == [("999", "WS-FIXED"), ("1", "WS-N")]
    assert suite.test_cases[1].setup_moves == [("999", "WS-FIXED"), ("2", "WS-N")]


def test_undeclared_provider_reference_raises():
    text = 'TESTSUITE "s"\n' 'TESTCASE "c" USING PROVIDER Ghost\n' "    PERFORM MAIN\n"
    with pytest.raises(
        CutParseError,
        match="line 2: TESTCASE 'c' uses PROVIDER 'Ghost', which was never declared",
    ):
        parse_cut(text)


def test_unknown_placeholder_raises():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER Nums\n"
        "    HEADER N\n"
        "    ROW 1\n"
        'TESTCASE "c" USING PROVIDER Nums\n'
        "    MOVE {Bogus} TO WS-N\n"
        "    PERFORM MAIN\n"
    )
    with pytest.raises(
        CutParseError,
        match=r"unknown placeholder \{Bogus\} in TESTCASE 'c'.*columns are N",
    ):
        parse_cut(text)


def test_non_provider_testcase_with_literal_braces_is_untouched():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOVE "{NotAPlaceholder}" TO WS-FIELD\n'
        "    PERFORM MAIN\n"
    )
    suite = parse_cut(text)
    assert suite.test_cases[0].setup_moves == [('"{NotAPlaceholder}"', "WS-FIELD")]


def test_placeholder_substitution_works_inside_a_larger_literal():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER Nums\n"
        "    HEADER N\n"
        "    ROW 1\n"
        'TESTCASE "c" USING PROVIDER Nums\n'
        "    PERFORM MAIN\n"
        '    EXPECT WS-MSG TO BE "value: {N}"\n'
    )
    suite = parse_cut(text)
    assert suite.test_cases[0].expectations[0].expected_value == '"value: 1"'
```

Add to `tests/unit/test_cli.py`, near the other `collect` tests:

```python
def test_collect_lists_expanded_provider_cases(tmp_path, capsys):
    cut = tmp_path / "PROG.cut"
    cut.write_text(
        'TESTSUITE "s"\n'
        "PROVIDER Nums\n"
        "    HEADER N\n"
        "    ROW 1\n"
        "    ROW 2\n"
        'TESTCASE "c" USING PROVIDER Nums\n'
        "    MOVE {N} TO WS-N\n"
        "    PERFORM MAIN\n"
    )
    exit_code = main(["collect", "--cut", str(cut), "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [c["name"] for c in payload["cases"]] == [
        "c [row 1: 1]",
        "c [row 2: 2]",
    ]
```

(`json` and `main` are already imported at the top of `tests/unit/test_cli.py` — confirm before adding; both are used by the existing collect tests in that file.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_dsl_parser.py -k "provider or expand or placeholder" -v tests/unit/test_cli.py -k provider -v`
Expected: FAIL — `TESTCASE "lookup state" USING PROVIDER StateNames` doesn't match `_TESTCASE_RE` yet (falls through to "unrecognized statement"), so every new test in this step fails.

- [ ] **Step 3: Implement binding and expansion**

In `mockymock/dsl/parser.py`:

1. Replace the existing `_TESTCASE_RE` definition with:

```python
_TESTCASE_RE = re.compile(
    r'^TESTCASE\s+"(?P<name>[^"]*)"(?:\s+TAGS\s+(?P<tags>"[^"]*"(?:\s+"[^"]*")*))?'
    r"(?:\s+USING\s+PROVIDER\s+(?P<provider>[A-Za-z0-9][A-Za-z0-9-]*))?$"
)
```

2. Add `_PLACEHOLDER_RE` right after `_PROVIDER_ROW_RE` (from Task 1):

```python
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z][A-Za-z0-9-]*)\}")
```

3. Inside `parse_cut()`, add a `pending_expansions` local next to the `providers`/`current_provider` locals (from Task 1):

```python
    providers: dict[str, DataProvider] = {}
    current_provider: DataProvider | None = None
    pending_expansions: list[tuple[MockTestCase, DataProvider]] = []
```

4. In the `TESTCASE` branch, after the existing tag-validation loop (`for tag in tags: ...`) and before `case = MockTestCase(...)`, add the provider-reference check; then after appending the case to `suite.test_cases`, record the pending expansion:

```python
        elif (m := _TESTCASE_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: TESTCASE before TESTSUITE")
            _close_provider()
            tags = _TAG_RE.findall(m.group("tags") or "")
            for tag in tags:
                if not tag.strip():
                    raise CutParseError(
                        f"line {line_no}: empty tag in TAGS list -- every "
                        f"tag must be a non-blank quoted word"
                    )
            provider_name = m.group("provider")
            if provider_name is not None and provider_name not in providers:
                raise CutParseError(
                    f"line {line_no}: TESTCASE {m.group('name')!r} uses "
                    f"PROVIDER {provider_name!r}, which was never declared "
                    f"-- declare a PROVIDER block before the TESTCASE that "
                    f"uses it"
                )
            case = MockTestCase(name=m.group("name"), line=line_no, tags=tags)
            suite.test_cases.append(case)
            if provider_name is not None:
                pending_expansions.append((case, providers[provider_name]))
            mock_lines = {}
```

5. Add these four functions after `_close_provider`'s enclosing scope closes -- i.e. as **module-level** functions placed right before `def parse_cut(text: str) -> MockTestSuite:` (after `_split_top_level`, before `parse_cut`):

```python
def _substitute(
    text: str, provider: DataProvider, row: list[str], case_name: str, line_no: int
) -> str:
    """Replace every `{ColumnName}` token in `text` with that column's raw
    row value. An unknown column is a CutParseError, not a silent no-op --
    same fail-closed convention as the rest of this parser."""

    def repl(match: re.Match[str]) -> str:
        column = match.group(1)
        if column not in provider.header:
            raise CutParseError(
                f"line {line_no}: unknown placeholder {{{column}}} in "
                f"TESTCASE {case_name!r} -- PROVIDER {provider.name!r} "
                f"columns are {', '.join(provider.header)}"
            )
        return row[provider.header.index(column)]

    return _PLACEHOLDER_RE.sub(repl, text)


def _display_value(raw: str) -> str:
    """Strip one layer of matching quote characters for a human-readable
    generated case name -- cosmetic only; `_substitute` always uses the
    raw, unstripped row text."""
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    return raw


def _instantiate_row(
    case: MockTestCase, provider: DataProvider, row: list[str], row_index: int
) -> MockTestCase:
    row_line = provider.row_lines[row_index - 1]
    setup_moves = [
        (_substitute(value, provider, row, case.name, case.line), target)
        for value, target in case.setup_moves
    ]
    expectations = [
        ExpectDirective(
            data_name=expectation.data_name,
            expected_value=_substitute(
                expectation.expected_value,
                provider,
                row,
                case.name,
                expectation.line,
            ),
            line=expectation.line,
        )
        for expectation in case.expectations
    ]
    return MockTestCase(
        name=f"{case.name} [row {row_index}: {_display_value(row[0])}]",
        mocks=list(case.mocks),
        setup_moves=setup_moves,
        perform_target=case.perform_target,
        perform_thru=case.perform_thru,
        expectations=expectations,
        verifications=list(case.verifications),
        line=row_line,
        tags=list(case.tags),
    )


def _expand_providers(
    test_cases: list[MockTestCase],
    pending: list[tuple[MockTestCase, DataProvider]],
) -> list[MockTestCase]:
    """Replace every provider-bound TESTCASE with one ordinary
    MockTestCase per PROVIDER row (see
    docs/2026-07-20-provider-parameterized-test-cases-design.md). Every
    other consumer of the parsed suite -- analysis, splicer, runtime,
    report, cli -- only ever sees what this returns; PROVIDER never leaks
    past this function."""
    bound = {id(case): provider for case, provider in pending}
    expanded: list[MockTestCase] = []
    for case in test_cases:
        provider = bound.get(id(case))
        if provider is None:
            expanded.append(case)
            continue
        for row_index, row in enumerate(provider.rows, start=1):
            expanded.append(_instantiate_row(case, provider, row, row_index))
    return expanded
```

6. At the end of `parse_cut()`, change:

```python
    if suite is None:
        raise CutParseError("no TESTSUITE found")
    return suite
```

to:

```python
    if suite is None:
        raise CutParseError("no TESTSUITE found")

    if pending_expansions:
        suite.test_cases = _expand_providers(suite.test_cases, pending_expansions)

    return suite
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_dsl_parser.py tests/unit/test_cli.py -v`
Expected: all tests PASS, including every pre-existing test (backward compatibility intact).

- [ ] **Step 5: Commit**

```bash
git add mockymock/dsl/parser.py tests/unit/test_dsl_parser.py tests/unit/test_cli.py
git commit -m "feat: expand USING PROVIDER TESTCASEs into one case per row"
```

---

### Task 3: Worked example + Docker integration proof

**Files:**
- Create: `examples/statelkup/STATELKUP.cbl`
- Create: `examples/statelkup/STATELKUP.cut`
- Create: `examples/statelkup/README.md`
- Create: `tests/integration/test_statelkup_example.py`

**Interfaces:**
- Consumes: the working PROVIDER feature via `mockymock.cli.main.main(["run", ...])` and `main(["collect", ...])` — black-box only, no parser internals.
- Produces: nothing further tasks depend on; this is a leaf/proof task.

- [ ] **Step 1: Write the example program**

Create `examples/statelkup/STATELKUP.cbl`:

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STATELKUP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STATE-CODE        PIC X(2).
       01  WS-STATE-NAME        PIC X(20).

       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-LOOKUP-STATE
           GOBACK.

       1000-LOOKUP-STATE.
           EVALUATE WS-STATE-CODE
               WHEN "AZ"
                   MOVE "Arizona" TO WS-STATE-NAME
               WHEN "KY"
                   MOVE "Kentucky" TO WS-STATE-NAME
               WHEN OTHER
                   MOVE "*Undefined*" TO WS-STATE-NAME
           END-EVALUATE.
```

Create `examples/statelkup/STATELKUP.cut`:

```
TESTSUITE "STATELKUP state name lookup"

*> PROVIDER/HEADER/ROW declare a reusable data table; USING PROVIDER
*> expands this one TESTCASE into 3 independently compiled/reported
*> cases -- see docs/2026-07-20-provider-parameterized-test-cases-design.md.
PROVIDER StateNames
    HEADER Abbreviation, Name
    ROW "AZ", "Arizona"
    ROW "KY", "Kentucky"
    ROW "XX", "*Undefined*"

TESTCASE "1000-LOOKUP-STATE resolves a state name" USING PROVIDER StateNames
    MOVE {Abbreviation} TO WS-STATE-CODE
    PERFORM 1000-LOOKUP-STATE
    EXPECT WS-STATE-NAME TO BE {Name}
```

Create `examples/statelkup/README.md`:

````markdown
# STATELKUP

Demonstrates `PROVIDER`/`HEADER`/`ROW` parameterized test cases: one
`TESTCASE "..." USING PROVIDER StateNames` expands, at parse time, into
three ordinary test cases -- one per `ROW` -- each substituting
`{Abbreviation}`/`{Name}` into its `MOVE`/`EXPECT` values.

Run it:

```bash
mockymock collect --cut STATELKUP.cut
mockymock run STATELKUP.cbl --cut STATELKUP.cut
```

`collect` lists three cases even though the `.cut` file only has one
`TESTCASE` line:

```
TESTCASE '1000-LOOKUP-STATE resolves a state name [row 1: AZ]' (line 5)
TESTCASE '1000-LOOKUP-STATE resolves a state name [row 2: KY]' (line 6)
TESTCASE '1000-LOOKUP-STATE resolves a state name [row 3: XX]' (line 7)
```

The third row (`XX` -> `*Undefined*`) exercises `EVALUATE`'s `WHEN OTHER`
branch -- proving the three generated cases are genuinely independent,
not three copies of the same assertion.

See [../../docs/2026-07-20-provider-parameterized-test-cases-design.md](../../docs/2026-07-20-provider-parameterized-test-cases-design.md)
for the full design.
````

- [ ] **Step 2: Write the failing integration test**

Create `tests/integration/test_statelkup_example.py`:

```python
"""End-to-end proof for PROVIDER parameterized test cases: a single
`USING PROVIDER` TESTCASE expands into N independently compiled/run
cases -- see
docs/2026-07-20-provider-parameterized-test-cases-design.md."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "statelkup"


@requires_docker
def test_committed_statelkup_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "STATELKUP.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "STATELKUP.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_statelkup_fails_when_one_rows_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "STATELKUP.cut").read_text()
    broken = tmp_path / "STATELKUP.cut"
    broken.write_text(
        cut.replace(
            'EXPECT WS-STATE-NAME TO BE {Name}',
            'EXPECT WS-STATE-NAME TO BE "WRONG"',
            1,
        )
    )
    exit_code = main(
        ["run", str(EXAMPLE_DIR / "STATELKUP.cbl"), "--cut", str(broken)]
    )
    assert exit_code == 1


def test_statelkup_collect_lists_three_expanded_cases():
    """No Docker needed -- collect is pure parse (mockymock/cli/main.py)."""
    exit_code = main(
        ["collect", "--cut", str(EXAMPLE_DIR / "STATELKUP.cut"), "--json"]
    )
    assert exit_code == 0
```

- [ ] **Step 3: Run tests to verify the collect test passes and note Docker tests**

Run: `pytest tests/integration/test_statelkup_example.py -v`
Expected: `test_statelkup_collect_lists_three_expanded_cases` PASSes immediately (no Docker required, and Tasks 1-2 already make this work). `test_committed_statelkup_example_passes` and `test_statelkup_fails_when_one_rows_expectation_is_wrong` are decorated `@requires_docker` — they SKIP if the `mockymock-cobc` Docker toolchain isn't running locally, or PASS if it is. This step's job is to confirm collection succeeds and the skip/pass split matches expectations, not to force Docker to exist.

If Docker is available locally (`docker info` succeeds), verify both Docker tests actually PASS (not just non-error) before moving on — this is the one part of the whole feature no unit test can verify, since it's the only path proving three genuinely distinct COBOL programs' worth of behavior actually compile and run correctly (in particular, the `XX` row hitting `EVALUATE`'s `WHEN OTHER`).

- [ ] **Step 4: Commit**

```bash
git add examples/statelkup tests/integration/test_statelkup_example.py
git commit -m "test: add STATELKUP worked example for PROVIDER parameterized cases"
```

---

### Task 4: Documentation

**Files:**
- Modify: `.okf/dsl.md`
- Modify: `README.md`
- Modify: `docs/2026-07-06-real-world-readiness-audit.md`

**Interfaces:**
- Consumes: nothing code-level; documents the shipped behavior of Tasks 1-3.
- Produces: nothing further tasks depend on; this is the final task.

- [ ] **Step 1: Update `.okf/dsl.md`**

In the `# Grammar` section near the top, extend the grammar block (currently ending at `[ VERIFY [<category>] <key> WAS CALLED|PERFORMED <expectation> ]*` then a closing code fence) by adding, immediately before the `TESTCASE` line inside the fenced block:

```
[ PROVIDER <name>
      HEADER <col>, ... [, <col>]*
      ROW <value>, ... [, <value>]* [ ROW ... ]* ]*

TESTCASE "<name>" [ TAGS "<tag>" ... ] [ USING PROVIDER <name> ]
```

Add a new `## PROVIDER parameterized test cases` section after the existing `## Case rules` section (before `## \`MOCK <kind> <key>\` forms`):

```markdown
## `PROVIDER` parameterized test cases

`PROVIDER <name>` is a suite-level block (sibling of `TESTCASE`, must be
declared before any `TESTCASE` that references it) holding a `HEADER`
(bare, comma-separated column names) and one or more `ROW`s
(comma-separated, quote-aware-split free-form COBOL value text, same
convention as `MOVE`/`EXPECT` values). `TESTCASE "..." USING PROVIDER
<name>` binds a test-case template to it.

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
```

Add `DataProvider` to the `# AST Model (\`model.py\`)` table:

```markdown
| `DataProvider` | `name, line, header: list[str], rows: list[list[str]], row_lines: list[int]` | Parser-internal only -- never stored on `MockTestSuite`/`MockTestCase`; consumed and discarded by `_expand_providers` before `parse_cut()` returns |
```

- [ ] **Step 2: Update `README.md`**

In the `## The \`.cut\` DSL at a glance` section, after the existing bullet list (ending with "Lines starting with `*>` are comments.") and before the `mockymock generate <program.cbl>` paragraph, add:

```markdown
- `PROVIDER <name>` (suite-level, before any `TESTCASE` that uses it)
  declares a data table: `HEADER <col>, ...` names the columns, `ROW
  <value>, ...` adds one row each. `TESTCASE "..." USING PROVIDER <name>`
  expands, at parse time, into one ordinary test case per row --
  `{ColumnName}` in a `MOVE`/`EXPECT` value is substituted with that
  row's value. Generated cases are named `"<name> [row <n>: <first
  column value>]"`. See the worked example in `examples/statelkup/`.
```

Add a row to the `## Examples` table (after the `examples/custprog/` row, before `examples/real-world/`):

```markdown
| [`examples/statelkup/`](examples/statelkup/) | `PROVIDER`/`HEADER`/`ROW` parameterized test cases -- one `TESTCASE` expands into N rows |
```

- [ ] **Step 3: Update `docs/2026-07-06-real-world-readiness-audit.md`**

In `## Finding 6`, after the existing bullet list (ending with "...a second `PERFORM` in a case silently wins over the first (`dsl.md`, Gotchas).") and before the "**What closing it takes:**" paragraph, add:

```markdown
- (Closed 2026-07-20) N nearly-identical `TESTCASE`s that only vary a
  couple of `MOVE`/`EXPECT` values for tabular data -- see `PROVIDER`/
  `HEADER`/`ROW` parameterized test cases,
  `docs/2026-07-20-provider-parameterized-test-cases-design.md`.
```

- [ ] **Step 4: Commit**

```bash
git add .okf/dsl.md README.md docs/2026-07-06-real-world-readiness-audit.md
git commit -m "docs: document PROVIDER parameterized test cases"
```

---

## Final verification

After all four tasks:

```bash
pytest tests/unit -v
pytest tests/integration/test_statelkup_example.py -v
```

Expected: full unit suite green, `test_statelkup_collect_lists_three_expanded_cases` green, and the two `@requires_docker` tests either green (if Docker is up) or cleanly skipped (if not) -- never erroring.
