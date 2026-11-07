# BEFORE-EACH/BEFORE-ALL Scoping and FILE-STATUS Sugar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two `.cut` DSL ergonomics features: `BEFORE-EACH`/`BEFORE-ALL` blocks that share `MOCK` directives across every `TESTCASE` in a suite, and `FILE-STATUS IS <mnemonic-or-code>` sugar (plus an implicit default-success status) for `MOCK OPEN|CLOSE|READ|DELETE|START|UNLOCK`.

**Architecture:** `BEFORE-EACH`/`BEFORE-ALL` are resolved entirely inside `dsl/parser.py` by desugaring into each `TESTCASE`'s own `mocks` list before `parse_cut` returns — no other module ever learns the blocks existed. `FILE-STATUS` sugar is a new `mock_surface.analyze_file_status_fields` analysis (reads `FILE STATUS IS <field>` off `SELECT` statements), a new `MockDirective.file_status` field resolved at `.cut`-parse time from a fixed mnemonic table, a new `UNRESOLVED_FILE_STATUS_TARGET` refusal in `refusal.check_test_case`, and codegen in `injector.build_site_dispatch` that prepends a default-success `MOVE` (and the explicit override, if any) before the mock's own body.

**Tech Stack:** Python 3.11+, pytest, `cobolparser` (sibling package), GnuCOBOL 3.2 via the existing `mockymock-cobc` Docker container for integration tests.

## Global Constraints

- Spec: `docs/2026-07-20-before-blocks-and-file-status-design.md` — read this first; it has the full rationale, the mnemonic table, and the alternatives that were rejected.
- Every signature change to an existing function (`check_test_case`, `build_site_dispatch`, `splice_program`) must add the new parameter with a default that reproduces today's exact behavior when omitted. Every existing test and call site must keep passing unmodified — none of the tasks below should require editing a pre-existing test file's existing tests, only adding new ones.
- `WRITE`/`REWRITE` are explicitly out of scope for `FILE-STATUS` sugar and the default-success fallback (see design doc's Scope section) — do not extend `FILE_STATUS_CATEGORIES` to include them.
- `BEFORE-EACH`/`BEFORE-ALL` bodies hold `MOCK` directives only — no `MOVE`/`PERFORM`/`EXPECT`/`VERIFY`.
- All new Docker-requiring tests must use the existing `tests.integration._docker.requires_docker` skip guard so the suite stays green on a Docker-less machine.
- No new third-party dependencies.

---

### Task 1: `BEFORE-EACH`/`BEFORE-ALL` grammar and desugaring

**Files:**
- Modify: `mockymock/dsl/parser.py` (whole file — `parse_cut` and its helpers)
- Test: `tests/unit/test_dsl_parser_before_blocks.py` (new file)

**Interfaces:**
- Consumes: `MockCategory`, `MockDirective`, `MockTestCase`, `MockTestSuite` from `mockymock.dsl.model` (already imported).
- Produces: `parse_cut(text: str) -> MockTestSuite` keeps its exact existing signature and behavior for any `.cut` file with no `BEFORE-EACH`/`BEFORE-ALL` block. For a file that has them, every `MockTestSuite.test_cases[i].mocks` list already contains the resolved (desugared) mocks by the time `parse_cut` returns — no other module needs to know `BEFORE-EACH`/`BEFORE-ALL` exist.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_dsl_parser_before_blocks.py`:

```python
"""BEFORE-EACH / BEFORE-ALL mock scoping: grammar, position/uniqueness
rules, and desugar precedence into each TESTCASE's own mocks list."""

import pytest

from mockymock.dsl.model import MockCategory
from mockymock.dsl.parser import CutParseError, parse_cut

BASIC_CUT = """\
TESTSUITE "shared mocks"

BEFORE-ALL
    MOCK OPEN FILE1
    END-MOCK
END-BEFORE

BEFORE-EACH
    MOCK READ FILE2
        MOVE "default" TO WS-FIELD
    END-MOCK
END-BEFORE

TESTCASE "uses only shared mocks"
    PERFORM MAIN-PROCESS
    EXPECT WS-FIELD TO BE "default"

TESTCASE "overrides the shared READ mock"
    MOCK READ FILE2
        MOVE "override" TO WS-FIELD
    END-MOCK
    PERFORM MAIN-PROCESS
    EXPECT WS-FIELD TO BE "override"
"""


def test_before_all_and_before_each_mocks_appear_in_every_case():
    suite = parse_cut(BASIC_CUT)
    for case in suite.test_cases:
        keys = {(m.category, m.key) for m in case.mocks}
        assert (MockCategory.OPEN, "FILE1") in keys
        assert (MockCategory.READ, "FILE2") in keys


def test_testcase_mock_overrides_before_each_mock():
    suite = parse_cut(BASIC_CUT)
    first, second = suite.test_cases
    first_read = next(m for m in first.mocks if m.key == "FILE2")
    second_read = next(m for m in second.mocks if m.key == "FILE2")
    assert first_read.body_lines == ['MOVE "default" TO WS-FIELD']
    assert second_read.body_lines == ['MOVE "override" TO WS-FIELD']


def test_before_each_overrides_before_all_on_key_collision():
    cut = """\
TESTSUITE "precedence"

BEFORE-ALL
    MOCK OPEN FILE1
        MOVE "from-all" TO WS-FIELD
    END-MOCK
END-BEFORE

BEFORE-EACH
    MOCK OPEN FILE1
        MOVE "from-each" TO WS-FIELD
    END-MOCK
END-BEFORE

TESTCASE "one"
    PERFORM MAIN-PROCESS
"""
    suite = parse_cut(cut)
    mock = next(m for m in suite.test_cases[0].mocks if m.key == "FILE1")
    assert mock.body_lines == ['MOVE "from-each" TO WS-FIELD']


def test_duplicate_mock_within_before_each_is_a_parse_error():
    cut = """\
TESTSUITE "dup"

BEFORE-EACH
    MOCK OPEN FILE1
    END-MOCK
    MOCK OPEN FILE1
    END-MOCK
END-BEFORE

TESTCASE "one"
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="duplicate MOCK"):
        parse_cut(cut)


def test_before_each_after_testcase_is_a_parse_error():
    cut = """\
TESTSUITE "late"

TESTCASE "one"
    PERFORM MAIN-PROCESS

BEFORE-EACH
    MOCK OPEN FILE1
    END-MOCK
END-BEFORE
"""
    with pytest.raises(CutParseError, match="before the first TESTCASE"):
        parse_cut(cut)


def test_second_before_each_is_a_parse_error():
    cut = """\
TESTSUITE "dup-block"

BEFORE-EACH
    MOCK OPEN FILE1
    END-MOCK
END-BEFORE

BEFORE-EACH
    MOCK OPEN FILE2
    END-MOCK
END-BEFORE

TESTCASE "one"
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="second BEFORE-EACH"):
        parse_cut(cut)


def test_move_inside_before_each_is_rejected():
    cut = """\
TESTSUITE "no-move"

BEFORE-EACH
    MOVE 1 TO WS-FIELD
END-BEFORE

TESTCASE "one"
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="not allowed inside BEFORE-EACH"):
        parse_cut(cut)


def test_unterminated_before_each_at_eof_is_a_parse_error():
    cut = """\
TESTSUITE "no-end"

BEFORE-EACH
    MOCK OPEN FILE1
    END-MOCK
"""
    with pytest.raises(CutParseError, match="unterminated BEFORE-EACH"):
        parse_cut(cut)


def test_verify_against_a_before_each_mock_is_allowed():
    cut = """\
TESTSUITE "verify shared"

BEFORE-EACH
    MOCK CLOSE FILE1
    END-MOCK
END-BEFORE

TESTCASE "one"
    PERFORM MAIN-PROCESS
    VERIFY CLOSE FILE1 WAS PERFORMED ONCE
"""
    suite = parse_cut(cut)
    verification = suite.test_cases[0].verifications[0]
    assert verification.category is MockCategory.CLOSE
    assert verification.key == "FILE1"


def test_file_with_no_before_blocks_parses_exactly_as_before():
    cut = """\
TESTSUITE "plain"

TESTCASE "one"
    MOCK OPEN FILE1
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    suite = parse_cut(cut)
    assert [m.key for m in suite.test_cases[0].mocks] == ["FILE1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_dsl_parser_before_blocks.py -v`
Expected: every test fails — `BEFORE-EACH`/`BEFORE-ALL`/`END-BEFORE` are not recognized keywords yet, so `parse_cut` raises `CutParseError: ... unrecognized statement` for every fixture that uses them (the last test, with no before-blocks, is expected to already pass — that's fine, it's a regression guard for the next step).

- [ ] **Step 3: Replace `mockymock/dsl/parser.py` with the version below**

```python
"""Parses .cut files into MockTestSuite objects.

v2 grammar: MOCK takes a category — quoted-key categories
(CALL/MQ/SQL/CICS/DLI) vs bare-COBOL-word categories (the eight file-op
verbs and ACCEPT). `MOCK MQ "X"` is sugar for `MOCK CALL "X"`. CALL alone
takes both forms: `MOCK CALL "X"` mocks a static CALL with literal 'X',
while `MOCK CALL WS-PGM` (bare word) mocks a *dynamic* CALL through the
identifier WS-PGM (parsed as MockCategory.DYNCALL; MQ stays quoted-only —
the MQI is invoked through static CALLs by definition). `MOCK PARAGRAPH
<name>` / `MOCK SECTION <name>` (bare COBOL names) mock an internal flow
target: the named paragraph's/section's body is replaced by the mock body
whenever it is entered through its own header while this test case runs.
VERIFY mirrors the same key syntax; a bare `VERIFY "X"` stays CALL for v1
back-compat, and CALLED/PERFORMED are interchangeable. Lines starting with `*>` outside
MOCK bodies are comments; inside a body they pass through (they're valid
free-form COBOL).

BEFORE-ALL/BEFORE-EACH (see
docs/2026-07-20-before-blocks-and-file-status-design.md): at most one of
each per TESTSUITE, appearing after the TESTSUITE header and before the
first TESTCASE, holding MOCK directives only. Resolved by desugaring,
purely inside this module: after the file is fully parsed, each
TESTCASE's own mocks list is extended with every BEFORE-EACH mock whose
(category, key) it didn't already declare, then every BEFORE-ALL mock
neither it nor BEFORE-EACH already declared -- so TESTCASE overrides
BEFORE-EACH overrides BEFORE-ALL, silently. No other module ever learns
these blocks existed; by the time parse_cut returns, every case's
`mocks` list looks exactly as if the author had typed everything by
hand.
"""

from __future__ import annotations

import re

from mockymock.dsl.model import (
    ExpectDirective,
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
    VerifyDirective,
)

_QUOTED_CATS = "CALL|MQ|SQL|CICS|DLI"
# CALL also appears here: the bare-key form is the dynamic-CALL mock.
# PARAGRAPH/SECTION mock an internal flow target (a PROCEDURE DIVISION
# paragraph or section) rather than an external boundary.
_BARE_CATS = (
    "CALL|OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START|UNLOCK|ACCEPT" "|PARAGRAPH|SECTION"
)

_TESTSUITE_RE = re.compile(r'^TESTSUITE\s+"(?P<name>[^"]*)"$')
_TESTCASE_RE = re.compile(
    r'^TESTCASE\s+"(?P<name>[^"]*)"(?:\s+TAGS\s+(?P<tags>"[^"]*"(?:\s+"[^"]*")*))?$'
)
_TAG_RE = re.compile(r'"([^"]*)"')
_BEFORE_ALL_RE = re.compile(r"^BEFORE-ALL$")
_BEFORE_EACH_RE = re.compile(r"^BEFORE-EACH$")
# END-BEFORE is deliberately lenient, same rationale as END-MOCK below: a
# missed terminator must not silently swallow the rest of the file.
_END_BEFORE_RE = re.compile(r"^END-BEFORE\.?$", re.IGNORECASE)
_MOCK_QUOTED_RE = re.compile(
    rf'^MOCK\s+(?P<cat>{_QUOTED_CATS})\s+"(?P<key>[^"]*)"(?:\s+(?P<rows>ROWS))?$'
)
_MOCK_BARE_RE = re.compile(
    rf"^MOCK\s+(?P<cat>{_BARE_CATS})\s+(?P<key>[A-Za-z0-9][A-Za-z0-9-]*)$"
)
# END-MOCK is deliberately more forgiving than the other keywords: an
# optional trailing period (the natural COBOL habit) and any letter case
# are accepted, because a missed END-MOCK doesn't fail at this line -- it
# silently swallows the rest of the file into the mock body and surfaces
# later as a confusing refusal or compile error. Every other DSL keyword
# stays case-sensitive uppercase (see the "Case rules" section in
# .okf/dsl.md).
_END_MOCK_RE = re.compile(r"^END-MOCK\.?$", re.IGNORECASE)
_MOVE_RE = re.compile(r"^MOVE\s+(?P<value>.+?)\s+TO\s+(?P<target>\S+)$")
_PERFORM_RE = re.compile(
    r"^PERFORM\s+(?P<target>\S+)(?:\s+(?:THRU|THROUGH)\s+(?P<thru>\S+))?$"
)
_EXPECT_RE = re.compile(r"^EXPECT\s+(?P<name>\S+)\s+TO\s+BE\s+(?P<value>.+)$")
_VERIFY_QUOTED_RE = re.compile(
    rf'^VERIFY\s+(?:(?P<cat>{_QUOTED_CATS})\s+)?"(?P<key>[^"]*)"'
    rf"\s+WAS\s+(?:CALLED|PERFORMED)\s+(?P<expectation>.+)$"
)
_VERIFY_BARE_RE = re.compile(
    rf"^VERIFY\s+(?P<cat>{_BARE_CATS})\s+(?P<key>[A-Za-z0-9][A-Za-z0-9-]*)"
    rf"\s+WAS\s+(?:CALLED|PERFORMED)\s+(?P<expectation>.+)$"
)
_COMMENT_RE = re.compile(r"^\*>")
_ROW_RE = re.compile(r"^\((?P<pairs>.+)\)$")
_ROW_PAIR_RE = re.compile(r"^(?P<field>[A-Za-z][A-Za-z0-9-]*)\s*=\s*(?P<value>.+)$")


class CutParseError(ValueError):
    """Raised when a .cut file doesn't match the grammar."""


def _resolve_category(cat: str | None, bare_key: bool = False) -> MockCategory:
    if cat is None or cat == "MQ":  # bare VERIFY "X" and MOCK MQ are CALL
        return MockCategory.CALL
    if cat == "CALL" and bare_key:  # CALL <identifier> is the dynamic form
        return MockCategory.DYNCALL
    return MockCategory(cat)


def _validate_expectation(expectation: str, line_no: int) -> None:
    """Reject a VERIFY expectation the driver codegen cannot compile.

    Must accept exactly what splicer/driver.py's `_verify_condition`
    accepts (it upper-cases and strips before matching) -- keep the two in
    sync. Validating here turns a late, tracebacking ValueError in codegen
    into a line-numbered CutParseError at parse time."""
    normalized = expectation.strip().upper()
    if normalized in ("ONCE", "NEVER", "AT LEAST ONCE"):
        return
    if re.match(r"^\d+\s+TIMES$", normalized):
        return
    raise CutParseError(
        f"line {line_no}: unrecognized VERIFY expectation {expectation!r} "
        f"(expected ONCE, NEVER, AT LEAST ONCE, or <n> TIMES)"
    )


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


def _apply_before_blocks(
    suite: MockTestSuite,
    before_all: list[MockDirective],
    before_each: list[MockDirective],
) -> None:
    """Desugar BEFORE-ALL/BEFORE-EACH into every TESTCASE's own mocks list.
    Precedence when a (category, key) appears in more than one place:
    TESTCASE > BEFORE-EACH > BEFORE-ALL, silently -- see
    docs/2026-07-20-before-blocks-and-file-status-design.md."""
    if not before_all and not before_each:
        return
    for case in suite.test_cases:
        declared = {(m.category, m.key) for m in case.mocks}
        for directive in before_each:
            key = (directive.category, directive.key)
            if key in declared:
                continue
            declared.add(key)
            case.mocks.append(directive)
        for directive in before_all:
            key = (directive.category, directive.key)
            if key in declared:
                continue
            declared.add(key)
            case.mocks.append(directive)


def parse_cut(text: str) -> MockTestSuite:
    suite: MockTestSuite | None = None
    case: MockTestCase | None = None
    in_mock: MockDirective | None = None
    in_mock_line = 0
    # (category, key) -> declaring line, reset per TESTCASE/BEFORE-EACH/
    # BEFORE-ALL: a duplicate MOCK would otherwise parse fine and surface
    # much later as an AMBIGUOUS_MOCK refusal with no line numbers and
    # misleading advice.
    mock_lines: dict[tuple[MockCategory, str], int] = {}
    # The list new MOCK directives are appended to: case.mocks inside a
    # TESTCASE, before_each/before_all inside those blocks, None
    # otherwise (MOCK outside any of them is a parse error).
    mock_target: list[MockDirective] | None = None
    before_all: list[MockDirective] = []
    before_each: list[MockDirective] = []
    before_all_seen = False
    before_each_seen = False
    seen_testcase = False
    in_before: str | None = None  # None, "BEFORE-ALL", or "BEFORE-EACH"
    before_open_line = 0

    def _current_scope_label() -> str:
        if case is not None:
            return f"TESTCASE {case.name!r}"
        assert in_before is not None
        return in_before

    def _open_mock(directive: MockDirective, line_no: int) -> MockDirective:
        assert mock_target is not None
        mock_id = (directive.category, directive.key)
        if mock_id in mock_lines:
            raise CutParseError(
                f"line {line_no}: duplicate MOCK {directive.describe()} in "
                f"{_current_scope_label()} (first declared at line "
                f"{mock_lines[mock_id]})"
            )
        mock_lines[mock_id] = line_no
        mock_target.append(directive)
        return directive

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

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

        if _COMMENT_RE.match(line):
            continue

        if (m := _TESTSUITE_RE.match(line)) is not None:
            if suite is not None:
                raise CutParseError(
                    f"line {line_no}: second TESTSUITE line (suite "
                    f"{suite.name!r} is already open); a .cut file holds "
                    f"exactly one TESTSUITE -- concatenated files would "
                    f"silently run only the last suite"
                )
            suite = MockTestSuite(name=m.group("name"), line=line_no)
        elif (m := _TESTCASE_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: TESTCASE before TESTSUITE")
            if in_before is not None:
                raise CutParseError(
                    f"line {line_no}: TESTCASE inside {in_before} -- "
                    f"missing END-BEFORE"
                )
            tags = _TAG_RE.findall(m.group("tags") or "")
            for tag in tags:
                if not tag.strip():
                    raise CutParseError(
                        f"line {line_no}: empty tag in TAGS list -- every "
                        f"tag must be a non-blank quoted word"
                    )
            case = MockTestCase(name=m.group("name"), line=line_no, tags=tags)
            suite.test_cases.append(case)
            seen_testcase = True
            mock_target = case.mocks
            mock_lines = {}
        elif (m := _BEFORE_ALL_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: BEFORE-ALL before TESTSUITE")
            if seen_testcase:
                raise CutParseError(
                    f"line {line_no}: BEFORE-ALL must appear before the "
                    f"first TESTCASE"
                )
            if before_all_seen:
                raise CutParseError(
                    f"line {line_no}: a second BEFORE-ALL block -- a "
                    f"TESTSUITE holds at most one"
                )
            before_all_seen = True
            in_before = "BEFORE-ALL"
            before_open_line = line_no
            mock_target = before_all
            mock_lines = {}
        elif (m := _BEFORE_EACH_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: BEFORE-EACH before TESTSUITE")
            if seen_testcase:
                raise CutParseError(
                    f"line {line_no}: BEFORE-EACH must appear before the "
                    f"first TESTCASE"
                )
            if before_each_seen:
                raise CutParseError(
                    f"line {line_no}: a second BEFORE-EACH block -- a "
                    f"TESTSUITE holds at most one"
                )
            before_each_seen = True
            in_before = "BEFORE-EACH"
            before_open_line = line_no
            mock_target = before_each
            mock_lines = {}
        elif _END_BEFORE_RE.match(line):
            if in_before is None:
                raise CutParseError(
                    f"line {line_no}: END-BEFORE without an open "
                    f"BEFORE-EACH/BEFORE-ALL"
                )
            in_before = None
            mock_target = None
            mock_lines = {}
        elif (m := _MOCK_QUOTED_RE.match(line)) is not None:
            if mock_target is None:
                raise CutParseError(
                    f"line {line_no}: MOCK outside TESTCASE/BEFORE-EACH/"
                    f"BEFORE-ALL"
                )
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
        elif (m := _MOCK_BARE_RE.match(line)) is not None:
            if mock_target is None:
                raise CutParseError(
                    f"line {line_no}: MOCK outside TESTCASE/BEFORE-EACH/"
                    f"BEFORE-ALL"
                )
            in_mock = _open_mock(
                MockDirective(
                    category=_resolve_category(m.group("cat"), bare_key=True),
                    key=m.group("key").upper(),
                ),
                line_no,
            )
            in_mock_line = line_no
        elif line.startswith("MOCK"):
            raise CutParseError(
                f"line {line_no}: malformed MOCK directive: {line!r} "
                f"(MQ/SQL/CICS/DLI take a quoted key; "
                f"{_BARE_CATS.replace('|', '/')} take a bare COBOL name; "
                f'CALL takes both -- quoted "X" for a static CALL, bare '
                f"WS-NAME for a dynamic CALL through that identifier)"
            )
        elif (m := _MOVE_RE.match(line)) is not None:
            if case is None:
                if in_before is not None:
                    raise CutParseError(
                        f"line {line_no}: MOVE not allowed inside "
                        f"{in_before} (only MOCK directives are)"
                    )
                raise CutParseError(f"line {line_no}: MOVE outside TESTCASE")
            case.setup_moves.append((m.group("value"), m.group("target")))
        elif (m := _PERFORM_RE.match(line)) is not None:
            if case is None:
                if in_before is not None:
                    raise CutParseError(
                        f"line {line_no}: PERFORM not allowed inside "
                        f"{in_before} (only MOCK directives are)"
                    )
                raise CutParseError(f"line {line_no}: PERFORM outside TESTCASE")
            if case.perform_target:
                raise CutParseError(
                    f"line {line_no}: TESTCASE {case.name!r} already has a "
                    f"PERFORM target {case.perform_target!r}; one PERFORM "
                    f"per test case"
                )
            case.perform_target = m.group("target")
            case.perform_thru = m.group("thru")
        elif (m := _EXPECT_RE.match(line)) is not None:
            if case is None:
                if in_before is not None:
                    raise CutParseError(
                        f"line {line_no}: EXPECT not allowed inside "
                        f"{in_before} (only MOCK directives are)"
                    )
                raise CutParseError(f"line {line_no}: EXPECT outside TESTCASE")
            case.expectations.append(
                ExpectDirective(
                    data_name=m.group("name"),
                    expected_value=m.group("value"),
                    line=line_no,
                )
            )
        elif (m := _VERIFY_QUOTED_RE.match(line)) is not None:
            if case is None:
                if in_before is not None:
                    raise CutParseError(
                        f"line {line_no}: VERIFY not allowed inside "
                        f"{in_before} (only MOCK directives are)"
                    )
                raise CutParseError(f"line {line_no}: VERIFY outside TESTCASE")
            _validate_expectation(m.group("expectation"), line_no)
            case.verifications.append(
                VerifyDirective(
                    category=_resolve_category(m.group("cat")),
                    key=m.group("key"),
                    expectation=m.group("expectation"),
                    line=line_no,
                )
            )
        elif (m := _VERIFY_BARE_RE.match(line)) is not None:
            if case is None:
                if in_before is not None:
                    raise CutParseError(
                        f"line {line_no}: VERIFY not allowed inside "
                        f"{in_before} (only MOCK directives are)"
                    )
                raise CutParseError(f"line {line_no}: VERIFY outside TESTCASE")
            _validate_expectation(m.group("expectation"), line_no)
            case.verifications.append(
                VerifyDirective(
                    category=_resolve_category(m.group("cat"), bare_key=True),
                    key=m.group("key").upper(),
                    expectation=m.group("expectation"),
                    line=line_no,
                )
            )
        else:
            raise CutParseError(f"line {line_no}: unrecognized statement: {line!r}")

    if in_mock is not None:
        raise CutParseError(
            f"line {in_mock_line}: unterminated MOCK {in_mock.describe()}: "
            f"reached end of file with no END-MOCK"
        )

    if in_before is not None:
        raise CutParseError(
            f"line {before_open_line}: unterminated {in_before}: reached "
            f"end of file with no END-BEFORE"
        )

    if suite is None:
        raise CutParseError("no TESTSUITE found")
    _apply_before_blocks(suite, before_all, before_each)
    return suite
```

- [ ] **Step 4: Run the new tests, plus the full existing parser suite**

Run: `python -m pytest tests/unit/test_dsl_parser_before_blocks.py tests/unit/test_dsl_parser.py tests/unit/test_dsl_parser_v2.py tests/unit/test_dsl_tags_lines.py -v`
Expected: all PASS, including every pre-existing test in `test_dsl_parser.py`/`test_dsl_parser_v2.py`/`test_dsl_tags_lines.py` unchanged.

- [ ] **Step 5: Run the full unit suite as a regression check**

Run: `python -m pytest tests/unit -v`
Expected: all PASS (nothing outside the parser should have moved yet).

- [ ] **Step 6: Commit**

```bash
git add mockymock/dsl/parser.py mockymock/dsl/model.py tests/unit/test_dsl_parser_before_blocks.py
git commit -m "feat: add BEFORE-EACH/BEFORE-ALL mock scoping to the .cut DSL"
```

---

### Task 2: `mock_surface.analyze_file_status_fields`

**Files:**
- Modify: `mockymock/analysis/mock_surface.py` (add one function + two imports)
- Test: `tests/unit/test_mock_surface_file_status.py` (new file)

**Interfaces:**
- Consumes: `program.get_division("ENVIRONMENT")` / `CobolDivision.get_section_by_name("INPUT-OUTPUT")` / `CobolSection.get_paragraph_by_name("FILE-CONTROL")` (all existing `cobolparser` AST APIs, verified against `cobolparser/models/program.py` and `cobolparser/parsers/divisions/environment.py`), plus `SelectStatement.file_name`/`.file_status` (verified against `cobolparser/models/statements/misc.py`).
- Produces: `analyze_file_status_fields(program: CobolProgram) -> dict[str, str]` — uppercased file name to its declared status field name. Consumed by Task 4 (`refusal.check_test_case`) and Task 5/6 (`cli/checks.py`, `injector.build_site_dispatch`).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_mock_surface_file_status.py`:

```python
"""Unit tests for analyze_file_status_fields: FD/SELECT FILE STATUS
extraction feeding the FILE-STATUS DSL sugar."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze_file_status_fields

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STATFILE.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT WITH-STATUS ASSIGN TO "A.DAT"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-WITH-STATUS.
           SELECT NO-STATUS ASSIGN TO "B.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  WITH-STATUS.
       01  WITH-STATUS-REC    PIC X(10).
       FD  NO-STATUS.
       01  NO-STATUS-REC      PIC X(10).

       WORKING-STORAGE SECTION.
       01  WS-WITH-STATUS     PIC X(2).

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT WITH-STATUS NO-STATUS.
"""


def _program():
    result = parse_cobol(SOURCE, filename="statfile.cbl")
    assert result.success, result.errors
    return result.ast


def test_file_with_file_status_clause_is_captured():
    fields = analyze_file_status_fields(_program())
    assert fields["WITH-STATUS"] == "WS-WITH-STATUS"


def test_file_without_file_status_clause_has_no_entry():
    fields = analyze_file_status_fields(_program())
    assert "NO-STATUS" not in fields


def test_program_with_no_environment_division_returns_empty():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOENV.
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           DISPLAY "HI".
"""
    result = parse_cobol(source, filename="noenv.cbl")
    assert result.success, result.errors
    assert analyze_file_status_fields(result.ast) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_mock_surface_file_status.py -v`
Expected: `ImportError: cannot import name 'analyze_file_status_fields'`.

- [ ] **Step 3: Add the function to `mockymock/analysis/mock_surface.py`**

Change the import block near the top from:

```python
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolProgram
```

to:

```python
from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
)
```

Add a new import alongside the existing `cobolparser.models.statements.*` imports:

```python
from cobolparser.models.statements.misc import (
    CancelStatement,
    GobackStatement,
    MergeStatement,
    ReleaseStatement,
    ReturnStatement,
    SelectStatement,
    SortStatement,
)
```

(`SelectStatement` is the only addition to that existing import line.)

Add this function right after `analyze()` (near the bottom of the file):

```python
def analyze_file_status_fields(program: CobolProgram) -> dict[str, str]:
    """Uppercased file name -> its declared `FILE STATUS IS <field>` name,
    read from the ENVIRONMENT DIVISION's FILE-CONTROL SELECT statements. A
    file whose SELECT entry has no FILE STATUS clause has no entry -- there
    is no WORKING-STORAGE field to default or target with FILE-STATUS IS
    sugar (see docs/2026-07-20-before-blocks-and-file-status-design.md)."""
    fields: dict[str, str] = {}
    environment = program.get_division("ENVIRONMENT")
    if environment is None:
        return fields
    io_section = environment.get_section_by_name("INPUT-OUTPUT")
    if not isinstance(io_section, CobolSection):
        return fields
    file_control = io_section.get_paragraph_by_name("FILE-CONTROL")
    if file_control is None:
        return fields
    for statement in file_control.statements:
        if not isinstance(statement, SelectStatement):
            continue
        if statement.file_name and statement.file_status:
            fields[statement.file_name.upper()] = statement.file_status
    return fields
```

- [ ] **Step 4: Run the new tests, plus the full existing mock_surface suite**

Run: `python -m pytest tests/unit/test_mock_surface_file_status.py tests/unit/test_mock_surface.py tests/unit/test_mock_surface_v2.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add mockymock/analysis/mock_surface.py tests/unit/test_mock_surface_file_status.py
git commit -m "feat: extract declared FILE STATUS fields from FILE-CONTROL"
```

---

### Task 3: `FILE-STATUS IS` grammar, mnemonic table, and `MockDirective.file_status`

**Files:**
- Modify: `mockymock/dsl/model.py` (add `FILE_STATUS_CATEGORIES` + `MockDirective.file_status`)
- Modify: `mockymock/dsl/parser.py` (add the mnemonic table, the `FILE-STATUS IS` regex, and its handling branch inside the mock-body loop)
- Test: `tests/unit/test_dsl_parser_file_status.py` (new file)

**Interfaces:**
- Consumes: `MockCategory` from `mockymock.dsl.model` (already present).
- Produces: `FILE_STATUS_CATEGORIES: frozenset[MockCategory]` and `MockDirective.file_status: str | None` in `mockymock.dsl.model`, consumed by Task 4 (`refusal.check_test_case`) and Task 5 (`injector.build_site_dispatch`).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_dsl_parser_file_status.py`:

```python
"""FILE-STATUS IS sugar: mnemonic table, quoted-literal escape hatch,
category restriction, and duplicate-in-body rejection."""

import pytest

from mockymock.dsl.parser import CutParseError, parse_cut


def _mock(cut: str):
    return parse_cut(cut).test_cases[0].mocks[0]


def test_mnemonic_resolves_to_the_documented_code():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN FILE1
        FILE-STATUS IS FILE-NOT-FOUND
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).file_status == "35"


@pytest.mark.parametrize(
    "mnemonic,code",
    [
        ("SUCCESS", "00"),
        ("END-OF-FILE", "10"),
        ("DUPLICATE-KEY", "22"),
        ("RECORD-NOT-FOUND", "23"),
        ("FILE-NOT-FOUND", "35"),
        ("ALREADY-OPEN", "41"),
        ("NOT-OPEN", "42"),
        ("NO-CURRENT-RECORD", "43"),
    ],
)
def test_every_documented_mnemonic_resolves(mnemonic, code):
    cut = f"""\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ FILE1
        FILE-STATUS IS {mnemonic}
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).file_status == code


def test_quoted_literal_code_is_the_escape_hatch():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ FILE1
        FILE-STATUS IS "92"
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).file_status == "92"


def test_unrecognized_mnemonic_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ FILE1
        FILE-STATUS IS NOT-A-REAL-MNEMONIC
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="unrecognized FILE-STATUS mnemonic"):
        parse_cut(cut)


def test_literal_not_two_characters_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ FILE1
        FILE-STATUS IS "9"
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="exactly two characters"):
        parse_cut(cut)


def test_file_status_inside_write_is_rejected():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK WRITE REC1
        FILE-STATUS IS SUCCESS
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="only valid inside"):
        parse_cut(cut)


def test_file_status_inside_call_is_rejected():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "X"
        FILE-STATUS IS SUCCESS
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="only valid inside"):
        parse_cut(cut)


def test_second_file_status_in_one_body_is_rejected():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ FILE1
        FILE-STATUS IS SUCCESS
        FILE-STATUS IS FILE-NOT-FOUND
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="a second FILE-STATUS IS"):
        parse_cut(cut)


def test_mock_without_file_status_has_none():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN FILE1
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).file_status is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_dsl_parser_file_status.py -v`
Expected: every test fails with `AttributeError: 'MockDirective' object has no attribute 'file_status'` (the grammar doesn't exist yet — `FILE-STATUS IS ...` lines currently fall through to the generic `else: in_mock.body_lines.append(line)` branch, so nothing ever sets `.file_status` and the attribute itself doesn't exist yet).

- [ ] **Step 3: Add `FILE_STATUS_CATEGORIES` and `MockDirective.file_status` to `mockymock/dsl/model.py`**

Add this frozenset right after `FLOW_CATEGORIES` (near the other category-set constants):

```python
# FILE-STATUS IS sugar and the implicit default-success MOVE apply only
# to these six file-op categories -- WRITE/REWRITE key on the *record*
# name, not the file name, and resolving record -> owning FD -> file
# name is out of scope (see
# docs/2026-07-20-before-blocks-and-file-status-design.md).
FILE_STATUS_CATEGORIES = frozenset(
    {
        MockCategory.OPEN,
        MockCategory.CLOSE,
        MockCategory.READ,
        MockCategory.DELETE,
        MockCategory.START,
        MockCategory.UNLOCK,
    }
)
```

Add a new field to the `MockDirective` dataclass, after `rows` and its docstring:

```python
    file_status: str | None = None
    """Resolved two-character status code from `FILE-STATUS IS
    <mnemonic-or-code>` inside this mock's body -- only ever set for
    FILE_STATUS_CATEGORIES. `None` when the body didn't use the sugar
    (the file may still get an implicit default-success MOVE at splice
    time if it declares a FILE STATUS field -- see
    injector.build_site_dispatch)."""
```

- [ ] **Step 4: Add the grammar to `mockymock/dsl/parser.py`**

Change the import from `mockymock.dsl.model` from:

```python
from mockymock.dsl.model import (
    ExpectDirective,
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
    VerifyDirective,
)
```

to:

```python
from mockymock.dsl.model import (
    FILE_STATUS_CATEGORIES,
    ExpectDirective,
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
    VerifyDirective,
)
```

Add these two constants right after `_ROW_PAIR_RE`:

```python
# FILE-STATUS IS <mnemonic> -> two-character GnuCOBOL file status code.
# A quoted two-character literal (FILE-STATUS IS "92") always works too,
# as the escape hatch for a code not listed here.
_FILE_STATUS_MNEMONICS = {
    "SUCCESS": "00",
    "END-OF-FILE": "10",
    "DUPLICATE-KEY": "22",
    "RECORD-NOT-FOUND": "23",
    "FILE-NOT-FOUND": "35",
    "ALREADY-OPEN": "41",
    "NOT-OPEN": "42",
    "NO-CURRENT-RECORD": "43",
}
_FILE_STATUS_RE = re.compile(
    r'^FILE-STATUS\s+IS\s+(?:(?P<mnemonic>[A-Za-z][A-Za-z-]*)|"(?P<literal>[^"]*)")$'
)
```

Inside `parse_cut`'s `if in_mock is not None:` block, change:

```python
                in_mock.rows.append(row)
            else:
                in_mock.body_lines.append(line)
            continue
```

to:

```python
                in_mock.rows.append(row)
            elif (m := _FILE_STATUS_RE.match(line)) is not None:
                if in_mock.category not in FILE_STATUS_CATEGORIES:
                    eligible = "/".join(c.keyword for c in FILE_STATUS_CATEGORIES)
                    raise CutParseError(
                        f"line {line_no}: FILE-STATUS IS is only valid "
                        f"inside MOCK {eligible} bodies, not MOCK "
                        f"{in_mock.category.keyword}"
                    )
                if in_mock.file_status is not None:
                    raise CutParseError(
                        f"line {line_no}: a second FILE-STATUS IS in one "
                        f"MOCK body -- only one is allowed"
                    )
                if m.group("literal") is not None:
                    code = m.group("literal")
                    if len(code) != 2:
                        raise CutParseError(
                            f"line {line_no}: FILE-STATUS IS {code!r} must "
                            f"be exactly two characters (a raw file status "
                            f"code)"
                        )
                else:
                    mnemonic = m.group("mnemonic").upper()
                    if mnemonic not in _FILE_STATUS_MNEMONICS:
                        valid = ", ".join(sorted(_FILE_STATUS_MNEMONICS))
                        raise CutParseError(
                            f"line {line_no}: unrecognized FILE-STATUS "
                            f"mnemonic {m.group('mnemonic')!r} (expected "
                            f'one of {valid}, or a quoted two-character '
                            f'code like "92")'
                        )
                    code = _FILE_STATUS_MNEMONICS[mnemonic]
                in_mock.file_status = code
            else:
                in_mock.body_lines.append(line)
            continue
```

Also update the module docstring (top of the file) to add a paragraph documenting the new statement, right after the existing `MOCK PARAGRAPH`/`MOCK SECTION` paragraph:

```python
FILE-STATUS IS <mnemonic-or-code> (see
docs/2026-07-20-before-blocks-and-file-status-design.md): usable once
inside a MOCK OPEN/CLOSE/READ/DELETE/START/UNLOCK body, resolved here to
a two-character status code and stored on MockDirective.file_status --
the WORKING-STORAGE field it targets isn't knowable until the target
.cbl's FILE-CONTROL has been analyzed, which happens later in the
pipeline (mock_surface.analyze_file_status_fields), not during .cut
parsing.
```

- [ ] **Step 5: Run the new tests, plus the full existing parser suite**

Run: `python -m pytest tests/unit/test_dsl_parser_file_status.py tests/unit/test_dsl_parser_before_blocks.py tests/unit/test_dsl_parser.py tests/unit/test_dsl_parser_v2.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full unit suite as a regression check**

Run: `python -m pytest tests/unit -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add mockymock/dsl/model.py mockymock/dsl/parser.py tests/unit/test_dsl_parser_file_status.py
git commit -m "feat: add FILE-STATUS IS sugar to the .cut DSL"
```

---

### Task 4: `UNRESOLVED_FILE_STATUS_TARGET` refusal

**Files:**
- Modify: `mockymock/analysis/refusal.py:535-539` (`check_test_case` signature) and its body (add a new loop before `return reasons`)
- Modify: `mockymock/cli/checks.py` (`StaticCheckResult` + `run_static_checks`)
- Test: `tests/unit/test_refusal_file_status.py` (new file)
- Test: `tests/unit/test_checks.py` (append new tests)

**Interfaces:**
- Consumes: `analyze_file_status_fields` from `mockymock.analysis.mock_surface` (Task 2).
- Produces: `check_test_case(surface, program, case, file_status_fields: dict[str, str] | None = None) -> list[RefusalReason]` — the new fourth parameter is optional and defaults to behaving exactly as before. `StaticCheckResult.file_status_fields: dict[str, str] | None` — populated by `run_static_checks`, consumed by Task 5's `_cmd_run` change.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_refusal_file_status.py`:

```python
"""UNRESOLVED_FILE_STATUS_TARGET: a MOCK using FILE-STATUS IS must target
a file whose SELECT entry declares a FILE STATUS field."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze, analyze_file_status_fields
from mockymock.analysis.refusal import check_test_case
from mockymock.dsl.parser import parse_cut

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STATCHK.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT WITH-STATUS ASSIGN TO "A.DAT"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-STATUS.
           SELECT NO-STATUS ASSIGN TO "B.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  WITH-STATUS.
       01  WITH-STATUS-REC    PIC X(10).
       FD  NO-STATUS.
       01  NO-STATUS-REC      PIC X(10).

       WORKING-STORAGE SECTION.
       01  WS-STATUS          PIC X(2).

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT WITH-STATUS NO-STATUS.
"""


def _check(cut_text: str):
    result = parse_cobol(SOURCE, filename="statchk.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    file_status_fields = analyze_file_status_fields(result.ast)
    suite = parse_cut(cut_text)
    case = suite.test_cases[0]
    return check_test_case(surface, result.ast, case, file_status_fields)


def test_file_status_on_a_file_with_a_declared_field_does_not_refuse():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN WITH-STATUS
        FILE-STATUS IS FILE-NOT-FOUND
    END-MOCK
    MOCK OPEN NO-STATUS
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    reasons = _check(cut)
    assert not any(r.code == "UNRESOLVED_FILE_STATUS_TARGET" for r in reasons)


def test_file_status_on_a_file_with_no_declared_field_refuses():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN WITH-STATUS
    END-MOCK
    MOCK OPEN NO-STATUS
        FILE-STATUS IS SUCCESS
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    reasons = _check(cut)
    matches = [r for r in reasons if r.code == "UNRESOLVED_FILE_STATUS_TARGET"]
    assert len(matches) == 1
    assert "NO-STATUS" in matches[0].message


def test_check_test_case_defaults_file_status_fields_to_empty():
    """The new parameter is optional -- every existing caller that omits
    it must keep working exactly as before."""
    result = parse_cobol(SOURCE, filename="statchk.cbl")
    surface = analyze(result.ast)
    suite = parse_cut(
        """\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN WITH-STATUS
    END-MOCK
    MOCK OPEN NO-STATUS
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    )
    reasons = check_test_case(surface, result.ast, suite.test_cases[0])
    assert reasons == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_refusal_file_status.py -v`
Expected: `TypeError: check_test_case() takes 3 positional arguments but 4 were given` (first two tests) and the third test passes already (it matches today's behavior).

- [ ] **Step 3: Modify `check_test_case` in `mockymock/analysis/refusal.py`**

Change the signature (currently at line 535):

```python
def check_test_case(
    surface: MockSurface,
    program,
    case: MockTestCase,
) -> list[RefusalReason]:
```

to:

```python
def check_test_case(
    surface: MockSurface,
    program,
    case: MockTestCase,
    file_status_fields: dict[str, str] | None = None,
) -> list[RefusalReason]:
```

Add `file_status_fields = file_status_fields or {}` as the first line inside the function body (right after the `from mockymock.analysis.flow_mocks import resolved_flow_targets` import line).

Add this new loop immediately before the function's final `return reasons` (i.e., right after the existing `VERIFY_WITHOUT_MOCK` loop that iterates `case.verifications`):

```python
    for directive in case.mocks:
        if directive.file_status is None:
            continue
        if directive.key.upper() not in file_status_fields:
            reasons.append(
                RefusalReason(
                    code="UNRESOLVED_FILE_STATUS_TARGET",
                    message=(
                        f"MOCK {directive.describe()} uses FILE-STATUS IS, "
                        f"but '{directive.key}' has no FILE STATUS IS "
                        f"<field> clause declared in its SELECT entry -- "
                        f"there is no WORKING-STORAGE field to move the "
                        f"status into"
                    ),
                )
            )
```

- [ ] **Step 4: Wire `file_status_fields` through `mockymock/cli/checks.py`**

Add a new field to `StaticCheckResult` (after the existing `linkage` field):

```python
    linkage: LinkagePlan | None = None
    file_status_fields: dict[str, str] | None = None
```

In `run_static_checks`, add the import alongside the existing `mock_surface` import:

```python
    from mockymock.analysis.mock_surface import analyze, analyze_file_status_fields
```

Right after `surface = analyze(parse_result.ast)` / `out.surface = surface` (step 5 of the pipeline), add:

```python
    out.file_status_fields = analyze_file_status_fields(parse_result.ast)
```

Change the per-test-case loop (step 8) from:

```python
    for case in suite.test_cases:
        out.problems.extend(
            f"refused ({r.code}): {r.message}"
            for r in check_test_case(surface, parse_result.ast, case)
        )
```

to:

```python
    for case in suite.test_cases:
        out.problems.extend(
            f"refused ({r.code}): {r.message}"
            for r in check_test_case(
                surface, parse_result.ast, case, out.file_status_fields
            )
        )
```

- [ ] **Step 5: Append to `tests/unit/test_checks.py`**

```python
def test_file_status_fields_populated_on_clean_run():
    result = run_static_checks(ORDRPROC_CBL, ORDRPROC_CUT, None)
    assert result.ok
    assert result.file_status_fields is not None


def test_unresolved_file_status_target_surfaces_as_a_problem(tmp_path):
    cbl = tmp_path / "NOSTAT.cbl"
    cbl.write_text(
        """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOSTAT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT NO-STATUS ASSIGN TO "A.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  NO-STATUS.
       01  NO-STATUS-REC      PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT NO-STATUS.
"""
    )
    cut = tmp_path / "NOSTAT.cut"
    cut.write_text(
        """\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN NO-STATUS
        FILE-STATUS IS SUCCESS
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    )
    result = run_static_checks(cbl, cut, None)
    assert not result.ok
    assert any("UNRESOLVED_FILE_STATUS_TARGET" in p for p in result.problems)
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/unit/test_refusal_file_status.py tests/unit/test_checks.py tests/unit/test_refusal.py tests/unit/test_refusal_v2.py -v`
Expected: all PASS.

- [ ] **Step 7: Run the full unit suite as a regression check**

Run: `python -m pytest tests/unit -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add mockymock/analysis/refusal.py mockymock/cli/checks.py tests/unit/test_refusal_file_status.py tests/unit/test_checks.py
git commit -m "feat: refuse FILE-STATUS IS on a file with no declared status field"
```

---

### Task 5: Codegen — default-success status and `FILE-STATUS IS` override

**Files:**
- Modify: `mockymock/splicer/injector.py:44-82` (`build_site_dispatch`)
- Modify: `mockymock/splicer/orchestrator.py:55-63,68-92` (`splice_program`)
- Modify: `mockymock/cli/main.py:279-287` (`_cmd_run`'s `splice_program` call)
- Test: `tests/unit/test_injector.py` (append new tests)

**Interfaces:**
- Consumes: `FILE_STATUS_CATEGORIES` and `MockDirective.file_status` (Task 1/3), `StaticCheckResult.file_status_fields` (Task 4).
- Produces: `build_site_dispatch(site, suite, registry, file_status_fields: dict[str, str] | None = None) -> list[str]` and `splice_program(..., file_status_fields: dict[str, str] | None = None) -> list[str]` — both new parameters optional, defaulting to today's exact output when omitted.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_injector.py` (it already imports `MockCategory, MockDirective, MockTestCase, MockTestSuite, TallyRegistry, build_site_dispatch` at the top):

```python
def test_default_success_status_injected_when_file_declares_a_status_field():
    case = MockTestCase(name="c")
    case.mocks.append(MockDirective(MockCategory.OPEN, "INFILE"))
    suite = MockTestSuite(name="S", test_cases=[case])
    site = _site(category=MockCategory.OPEN, label="OPEN", keys=("INFILE",))
    lines = build_site_dispatch(
        site, suite, TallyRegistry(suite), {"INFILE": "WS-INFILE-STATUS"}
    )
    assert 'MOVE "00" TO WS-INFILE-STATUS' in "\n".join(lines)


def test_explicit_file_status_follows_the_default():
    case = MockTestCase(name="c")
    directive = MockDirective(MockCategory.OPEN, "INFILE")
    directive.file_status = "35"
    case.mocks.append(directive)
    suite = MockTestSuite(name="S", test_cases=[case])
    site = _site(category=MockCategory.OPEN, label="OPEN", keys=("INFILE",))
    lines = build_site_dispatch(
        site, suite, TallyRegistry(suite), {"INFILE": "WS-INFILE-STATUS"}
    )
    default_idx = next(
        i for i, l in enumerate(lines) if 'MOVE "00" TO WS-INFILE-STATUS' in l
    )
    override_idx = next(
        i for i, l in enumerate(lines) if 'MOVE "35" TO WS-INFILE-STATUS' in l
    )
    assert override_idx == default_idx + 1


def test_no_status_move_when_file_has_no_declared_field():
    case = MockTestCase(name="c")
    case.mocks.append(MockDirective(MockCategory.OPEN, "INFILE"))
    suite = MockTestSuite(name="S", test_cases=[case])
    site = _site(category=MockCategory.OPEN, label="OPEN", keys=("INFILE",))
    lines = build_site_dispatch(site, suite, TallyRegistry(suite), {})
    assert "STATUS" not in "\n".join(lines)


def test_no_status_move_for_a_category_outside_file_status_categories():
    case = MockTestCase(name="c")
    case.mocks.append(MockDirective(MockCategory.WRITE, "OUTREC"))
    suite = MockTestSuite(name="S", test_cases=[case])
    site = _site(category=MockCategory.WRITE, label="WRITE", keys=("OUTREC",))
    lines = build_site_dispatch(
        site, suite, TallyRegistry(suite), {"OUTREC": "WS-OUTREC-STATUS"}
    )
    assert "STATUS" not in "\n".join(lines)


def test_omitting_file_status_fields_keeps_todays_exact_output():
    lines_with_none = _dispatch(_suite())
    lines_with_empty = build_site_dispatch(_site(), _suite(), TallyRegistry(_suite()), {})
    assert lines_with_none == lines_with_empty
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_injector.py -v`
Expected: `TypeError: build_site_dispatch() takes 3 positional arguments but 4 were given` for the first four new tests; the last passes trivially (no new arg passed) but confirm it still passes as a baseline.

- [ ] **Step 3: Modify `build_site_dispatch` in `mockymock/splicer/injector.py`**

Change the import line:

```python
from mockymock.dsl.model import MockTestSuite
```

to:

```python
from mockymock.dsl.model import FILE_STATUS_CATEGORIES, MockTestSuite
```

Replace the function:

```python
def build_site_dispatch(
    site: BoundarySite,
    suite: MockTestSuite,
    registry: TallyRegistry,
    file_status_fields: dict[str, str] | None = None,
) -> list[str]:
    """EVALUATE block replacing one mocked boundary statement.

    For a file-op directive in FILE_STATUS_CATEGORIES whose file declares
    a FILE STATUS field (`file_status_fields`), the branch always starts
    with an implicit `MOVE "00"` (default success) before the directive's
    own body; an explicit FILE-STATUS IS (`directive.file_status`) follows
    it and therefore wins, same as any hand-written MOVE the author adds
    after it -- see docs/2026-07-20-before-blocks-and-file-status-design.md.
    """
    file_status_fields = file_status_fields or {}
    lines = ["           EVALUATE UT-CURRENT-CASE"]

    for index, case in enumerate(suite.test_cases, start=1):
        matches = [d for d in case.mocks if directive_matches_site(d, site)]
        if len(matches) > 1:
            raise ValueError(
                f"site at line {site.line} matched by multiple directives of "
                f"test case {index} -- refusal gate should have caught this "
                f"(AMBIGUOUS_MOCK)"
            )
        if not matches:
            continue
        directive = matches[0]
        tally_name = registry.name(directive.category, directive.key)
        lines.append(f'               WHEN "{index:03d}"')
        lines.append(f"                   ADD 1 TO {tally_name}")
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

    lines.append("               WHEN OTHER")
    lines.append(
        f'                   DISPLAY "__MOCKYMOCK__ ERROR: {site.label} '
        f'boundary (line {site.line}) reached "'
    )
    lines.append('                       "from unmocked test case " UT-CURRENT-CASE')
    lines.append("                   ADD 1 TO UT-FAIL-COUNT")
    lines.append("           END-EVALUATE")
    return lines
```

- [ ] **Step 4: Run the injector tests**

Run: `python -m pytest tests/unit/test_injector.py -v`
Expected: all PASS.

- [ ] **Step 5: Thread `file_status_fields` through `mockymock/splicer/orchestrator.py`**

Change the `splice_program` signature (currently at line 55) from:

```python
def splice_program(
    lines: list[str],
    boundaries: list[int],
    surface: MockSurface,
    suite: MockTestSuite,
    registry: TallyRegistry,
    terminator_plans: Sequence[TerminatorPlan] = (),
    flow_plans: Sequence[FlowMockPlan] = (),
) -> list[str]:
```

to:

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
) -> list[str]:
```

Change the one call to `build_site_dispatch` inside it from:

```python
        if mocked:
            replacement = build_site_dispatch(site, suite, registry)
```

to:

```python
        if mocked:
            replacement = build_site_dispatch(site, suite, registry, file_status_fields)
```

- [ ] **Step 6: Thread it through `mockymock/cli/main.py`'s `_cmd_run`**

Change the `splice_program` call (currently):

```python
    lines = splice_program(
        lines, boundaries, surface, suite, registry, terminator_plans, flow_plans
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
    )
```

- [ ] **Step 7: Run the full unit suite as a regression check**

Run: `python -m pytest tests/unit -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add mockymock/splicer/injector.py mockymock/splicer/orchestrator.py mockymock/cli/main.py tests/unit/test_injector.py
git commit -m "feat: inject default-success and FILE-STATUS IS overrides at splice time"
```

---

### Task 6: Worked example, Docker integration test, and docs

**Files:**
- Create: `examples/taxfile/TAXFILE.cbl`
- Create: `examples/taxfile/TAXFILE.cut`
- Create: `examples/taxfile/README.md`
- Create: `tests/integration/test_taxfile_example.py`
- Modify: `README.md` (Examples table)
- Modify: `.okf/dsl.md` (Grammar section)
- Modify: `docs/2026-07-06-real-world-readiness-audit.md` (Finding 6)

**Interfaces:**
- Consumes: everything from Tasks 1-5 through the public `mockymock run` CLI path (`mockymock.cli.main.main`) — this task adds no new production code, only fixtures/docs/tests.
- Produces: nothing consumed by later tasks (this is the last task).

- [ ] **Step 1: Create `examples/taxfile/TAXFILE.cbl`**

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TAXFILE.
      * Adapted from the cobol-check wiki's own taxpayer-update-file
      * example: validates a postal code after a file read, and reports
      * an error code when the file itself fails to open.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TAXPAYER-FILE ASSIGN TO "TAX.DAT"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-TAXPAYER-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  TAXPAYER-FILE.
       01  TAXPAYER-REC.
           05  TP-TAXPAYER-ID     PIC X(9).
           05  TP-POSTCODE        PIC X(10).

       WORKING-STORAGE SECTION.
       01  WS-TAXPAYER-STATUS     PIC X(2).
       01  WS-ERROR-CODE          PIC X(9) VALUE SPACES.

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           PERFORM OPEN-FILE.
           IF WS-ERROR-CODE = SPACES
               PERFORM VALIDATE-IN-REC
           END-IF.
           PERFORM CLOSE-FILE.

       OPEN-FILE.
           OPEN INPUT TAXPAYER-FILE.
           IF WS-TAXPAYER-STATUS NOT = "00"
               MOVE "TUFNOTFND" TO WS-ERROR-CODE
           END-IF.

       VALIDATE-IN-REC.
           READ TAXPAYER-FILE.
           IF TP-POSTCODE = SPACES
               MOVE "TUFNOPOST" TO WS-ERROR-CODE
           END-IF.

       CLOSE-FILE.
           CLOSE TAXPAYER-FILE.
```

- [ ] **Step 2: Create `examples/taxfile/TAXFILE.cut`**

```
TESTSUITE "TAXFILE file-status handling"

*> Adapted from the cobol-check wiki's own taxpayer-update-file example.
*> Every case needs the file opened, read, and closed -- sharing those
*> defaults here means no case has to repeat them.
BEFORE-EACH
    MOCK OPEN TAXPAYER-FILE
    END-MOCK
    MOCK READ TAXPAYER-FILE
        MOVE "000000001" TO TP-TAXPAYER-ID
        MOVE "90210" TO TP-POSTCODE
    END-MOCK
    MOCK CLOSE TAXPAYER-FILE
    END-MOCK
END-BEFORE

*> Relies entirely on the shared BEFORE-EACH mocks: MOCK OPEN's empty
*> body gets the implicit default-success FILE STATUS "00" MOVE, so the
*> program's own status check never trips.
TESTCASE "open and read succeed, no errors"
    PERFORM MAIN-PROCESS
    EXPECT WS-ERROR-CODE TO BE SPACES
    VERIFY OPEN TAXPAYER-FILE WAS PERFORMED ONCE
    VERIFY CLOSE TAXPAYER-FILE WAS PERFORMED ONCE

*> Overrides the shared OPEN mock for this case only -- BEFORE-EACH's
*> READ/CLOSE mocks still apply underneath it.
TESTCASE "open reports file-not-found"
    MOCK OPEN TAXPAYER-FILE
        FILE-STATUS IS FILE-NOT-FOUND
    END-MOCK
    PERFORM MAIN-PROCESS
    EXPECT WS-ERROR-CODE TO BE "TUFNOTFND"

*> Overrides the shared READ mock for this case only.
TESTCASE "missing postal code is caught"
    MOCK READ TAXPAYER-FILE
        MOVE "000000002" TO TP-TAXPAYER-ID
        MOVE SPACES TO TP-POSTCODE
    END-MOCK
    PERFORM MAIN-PROCESS
    EXPECT WS-ERROR-CODE TO BE "TUFNOPOST"
```

- [ ] **Step 3: Create `examples/taxfile/README.md`**

```markdown
# TAXFILE — BEFORE-EACH scoping and FILE-STATUS sugar

Adapted from the cobol-check wiki's own taxpayer-update-file example: a
program that opens a file, validates a postal code, and reports one of
two error codes.

| Feature | Demonstrated by |
|---------|-----------------|
| `BEFORE-EACH` shared mocks | `MOCK OPEN`/`MOCK READ`/`MOCK CLOSE TAXPAYER-FILE` declared once, applying to all three cases |
| `TESTCASE` overrides `BEFORE-EACH` | Case 2 overrides `OPEN`; case 3 overrides `READ` — each keeps the other two shared mocks |
| `FILE-STATUS IS <mnemonic>` | Case 2's `FILE-STATUS IS FILE-NOT-FOUND` |
| Implicit default-success status | Case 1's `MOCK OPEN` has an empty body — `WS-TAXPAYER-STATUS` still ends up `"00"` |

Things this example demonstrates on purpose:

- **A `BEFORE-EACH` mock still has to be reachable from every case's
  `PERFORM` target**, exactly like a hand-typed one — `MAIN-PROCESS`
  performs `OPEN-FILE`, `VALIDATE-IN-REC`, and `CLOSE-FILE`
  unconditionally in source order (the `IF` around `VALIDATE-IN-REC` is a
  *runtime* guard; static reachability doesn't evaluate it), so all three
  boundaries need mocks in every case even though case 2 never actually
  reaches the `READ` at runtime.
- **`TESTCASE` silently overrides `BEFORE-EACH`, not an error** — case 2
  redeclares `MOCK OPEN TAXPAYER-FILE`; the shared one from `BEFORE-EACH`
  simply doesn't apply to that case.
- **`VERIFY` works on a `BEFORE-EACH`-only mock** — case 1's
  `VERIFY OPEN/CLOSE TAXPAYER-FILE` reference mocks it never declared
  itself.

Run it:

```bash
mockymock run examples/taxfile/TAXFILE.cbl --cut examples/taxfile/TAXFILE.cut
```
```

- [ ] **Step 4: Create `tests/integration/test_taxfile_example.py`**

```python
"""End-to-end proof for BEFORE-EACH/BEFORE-ALL scoping and FILE-STATUS
sugar: the committed taxfile example compiles and runs for real in the
mockymock-cobc container."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "taxfile"


@requires_docker
def test_committed_taxfile_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "TAXFILE.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "TAXFILE.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_taxfile_fails_when_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "TAXFILE.cut").read_text()
    broken = tmp_path / "TAXFILE.cut"
    broken.write_text(
        cut.replace(
            'EXPECT WS-ERROR-CODE TO BE "TUFNOTFND"',
            'EXPECT WS-ERROR-CODE TO BE "WRONGCODE"',
            1,
        )
    )
    exit_code = main(["run", str(EXAMPLE_DIR / "TAXFILE.cbl"), "--cut", str(broken)])
    assert exit_code == 1
```

- [ ] **Step 5: Run the integration tests (requires Docker; run `mockymock setup` first if the container isn't already built)**

Run: `python -m pytest tests/integration/test_taxfile_example.py -v`
Expected: both PASS. If Docker isn't reachable, both tests SKIP (via `@requires_docker`) rather than failing — that's an acceptable local result, but this task isn't done until it's been run green against a real container at least once (CI, or locally after `mockymock setup`).

- [ ] **Step 6: Update `README.md`'s Examples table**

Add a new row to the table (near `examples/flowmock/`'s row, in `## Examples`):

```markdown
| [`examples/taxfile/`](examples/taxfile/) | `BEFORE-EACH` shared mocks with per-case overrides, `FILE-STATUS IS` sugar, implicit default-success file status |
```

- [ ] **Step 7: Update `.okf/dsl.md`'s Grammar section**

In the `# Grammar` section (after the existing `TESTSUITE`/`TESTCASE` grammar block), add:

```markdown
### `BEFORE-EACH` / `BEFORE-ALL`

At most one of each per `TESTSUITE`, appearing after the `TESTSUITE`
header and before the first `TESTCASE`. Bodies hold `MOCK` directives
only. Desugared at parse time into every `TESTCASE`'s own `mocks` list;
precedence on a `(category, key)` collision is `TESTCASE` >
`BEFORE-EACH` > `BEFORE-ALL`, silently. See
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
```

- [ ] **Step 8: Update `docs/2026-07-06-real-world-readiness-audit.md`'s Finding 6**

Add a note to Finding 6 (DSL/authoring ergonomics) marking these two items closed — locate the bullet(s) describing "every MOCK re-declared per TestCase" and "no default file-status" (or the closest existing wording) and append:

```markdown
**Closed 2026-07-20**: `BEFORE-EACH`/`BEFORE-ALL` shared mocks (no more
re-declaring the same `MOCK` in every `TESTCASE`) and `FILE-STATUS IS`
sugar with an implicit default-success status landed — see
`docs/2026-07-20-before-blocks-and-file-status-design.md` and
`examples/taxfile/`.
```

- [ ] **Step 9: Run the full test suite (unit + integration) one last time**

Run: `python -m pytest tests/unit tests/integration -v`
Expected: all PASS (integration tests SKIP cleanly if Docker isn't reachable in this environment).

- [ ] **Step 10: Commit**

```bash
git add examples/taxfile tests/integration/test_taxfile_example.py README.md .okf/dsl.md docs/2026-07-06-real-world-readiness-audit.md
git commit -m "docs: add TAXFILE example and document BEFORE-EACH/FILE-STATUS features"
```
