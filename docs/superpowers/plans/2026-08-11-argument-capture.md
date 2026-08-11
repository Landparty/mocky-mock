# Argument-Capture Assertions on Mocked CALLs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a `.cut` author write `CAPTURE ARG <n> INTO <target>` inside a `MOCK CALL`/`MOCK MQ`/bare-`MOCK CALL <id>` body to capture the real `CALL`'s Nth `USING` parameter value into an ordinary WORKING-STORAGE field, then assert it with the existing `EXPECT <target> TO BE <value>` — closing the "no argument capture/spies on mocked CALLs" gap in the 2026-07-06 readiness audit's Finding 6.

**Architecture:** `<n>` is positional, resolved per physical call site against the real `CallStatement.using_parameters` AST (already carried on `BoundarySite.statement`, no new analysis field needed). The splicer emits one `MOVE <real-arg-name> TO <target>` per capture, before the directive's own body, in the same `EVALUATE UT-CURRENT-CASE` `WHEN` branch the tally increment already lives in. A new fail-closed refusal (`CAPTURE_ARG_OUT_OF_RANGE`) catches an index that exceeds some reachable site's real argument count. No new report/runtime protocol — `EXPECT` already does the assertion.

**Tech Stack:** Python 3, `cobolparser` (pinned dependency), `pytest`, GnuCOBOL via Docker (integration tests only).

## Global Constraints

- Full design and rationale: [`docs/2026-08-11-argument-capture-design.md`](../../2026-08-11-argument-capture-design.md) — read it before starting; this plan implements it task-by-task and does not repeat every "why."
- `CAPTURE ARG <n> INTO <target>` is valid **only** inside a `MOCK CALL "..."` (category `CALL`), `MOCK MQ "..."` (sugar for `CALL`), or bare `MOCK CALL <identifier>` (category `DYNCALL`) body. Anywhere else is a `CutParseError`.
- `<n>` is a positive integer (`1`, `2`, ...), 1-based, selecting the `USING` clause's Nth parameter — never a COBOL variable name.
- `<target>` reuses the `_SUBSCRIPTED_NAME` grammar fragment already shared by `EXPECT`'s data-name and `MOVE`'s target (`mockymock/dsl/parser.py`).
- Multi-call semantics: **last call wins**. The generated `MOVE` re-fires on every dispatch through that site's `WHEN` branch, so after `PERFORM` returns, the target field holds whichever call happened most recently. Do not build any per-call history/table — that is explicitly out of scope (see design doc Scope section).
- Fail closed: an index that exceeds some reachable matching site's actual `USING` parameter count must refuse at `mockymock lint`/`run` time (`CAPTURE_ARG_OUT_OF_RANGE`), never crash in codegen and never silently emit nothing.
- No changes to `dsl/generator.py` (`scaffold_cut`) — `CAPTURE` is hand-authoring only for this pass, same as `ROWS`'s inline sugar.
- Every new/changed Python file must stay `ruff`/`black`/`mypy` clean (this project's existing CI gate — see `.okf/testing.md`).
- Follow this project's TDD discipline throughout: write the failing test, run it, watch it fail for the *right* reason, then write the minimal implementation.

---

## File Structure

| File | Responsibility |
|---|---|
| `mockymock/dsl/model.py` | Modify: add `CAPTURE_CATEGORIES` constant and `MockDirective.captures: list[tuple[int, str]]` field. |
| `mockymock/dsl/parser.py` | Modify: recognize `CAPTURE ARG <n> INTO <target>` inside an open `MOCK` body, validate category/index/duplicates. |
| `mockymock/analysis/refusal.py` | Modify: new `CAPTURE_ARG_OUT_OF_RANGE` check in `check_test_case`, reading `CallStatement.using_parameters` off `BoundarySite.statement`. |
| `mockymock/splicer/injector.py` | Modify: `build_site_dispatch` emits the resolved `MOVE <real-arg-name> TO <target>` line(s) before `directive.body_lines`. |
| `interface-contract.md`, `.okf/integration.md` | Modify: pin `CallStatement.using_parameters: list[CallParameter]` / `CallParameter.name: str` as a dependency mockymock now relies on. |
| `examples/ordrproc/ORDRPROC.cbl`, `ORDRPROC.cut`, `README.md` | Modify: add a capture field and a `CAPTURE`+`EXPECT` pair proving the feature end-to-end via the existing Docker-gated `tests/integration/test_ordrproc_example.py`. |
| `.okf/dsl.md`, `.okf/splicer.md`, `.okf/analysis.md`, `.okf/log.md` | Modify: document the new grammar, codegen ordering, and refusal code; dated log entry. |
| `mockymock/cli/skills/mockymock/reference/cut-dsl.md` | Modify: the AI-skill's own DSL reference gets the same grammar section. |
| `docs/2026-07-06-real-world-readiness-audit.md` | Modify: mark Finding 6's "argument capture/spies" bullet closed. |
| `tests/unit/test_dsl_parser_capture.py` | Create: grammar/validation unit tests. |
| `tests/unit/test_refusal_capture.py` | Create: `CAPTURE_ARG_OUT_OF_RANGE` unit tests. |
| `tests/unit/test_injector.py` | Modify: add capture-codegen unit tests alongside the existing dispatch tests. |

---

### Task 1: DSL grammar — `CAPTURE ARG <n> INTO <target>`

**Files:**
- Modify: `mockymock/dsl/model.py`
- Modify: `mockymock/dsl/parser.py`
- Test: `tests/unit/test_dsl_parser_capture.py` (create)

**Interfaces:**
- Consumes: nothing new — `MockCategory.CALL`/`MockCategory.DYNCALL` (existing), `_SUBSCRIPTED_NAME` (existing regex fragment in `parser.py`).
- Produces: `mockymock.dsl.model.CAPTURE_CATEGORIES: frozenset[MockCategory]` (`{CALL, DYNCALL}`); `MockDirective.captures: list[tuple[int, str]]` (`(1-based USING position, target data-name)` pairs, declaration order, empty by default) — Tasks 2 and 3 read this field.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_dsl_parser_capture.py`:

```python
"""CAPTURE ARG <n> INTO <target>: grammar, category restriction, index
validation, and duplicate-in-body rejection -- mirrors
test_dsl_parser_file_status.py's structure for the sibling FILE-STATUS IS
sugar."""

import pytest

from mockymock.dsl.parser import CutParseError, parse_cut


def _mock(cut: str):
    return parse_cut(cut).test_cases[0].mocks[0]


def test_capture_parses_index_and_target():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG 1 INTO WS-CAPTURED-RATE
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).captures == [(1, "WS-CAPTURED-RATE")]


def test_capture_works_on_bare_dyncall_key():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL WS-PGM-NAME
        CAPTURE ARG 2 INTO WS-CAPTURED-ARG2
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).captures == [(2, "WS-CAPTURED-ARG2")]


def test_capture_target_may_be_subscripted():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG 1 INTO WS-TABLE(1, 1)
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).captures == [(1, "WS-TABLE(1, 1)")]


def test_multiple_captures_in_one_body_are_kept_in_declared_order():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG 2 INTO WS-SECOND
        CAPTURE ARG 1 INTO WS-FIRST
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).captures == [(2, "WS-SECOND"), (1, "WS-FIRST")]


def test_capture_index_zero_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG 0 INTO WS-CAPTURED-RATE
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="positive integer"):
        parse_cut(cut)


def test_capture_non_numeric_index_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG FIRST INTO WS-CAPTURED-RATE
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="positive integer"):
        parse_cut(cut)


def test_capture_outside_call_category_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN INV-FILE
        CAPTURE ARG 1 INTO WS-CAPTURED
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="CAPTURE ARG is only valid"):
        parse_cut(cut)


def test_duplicate_capture_arg_in_one_body_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG 1 INTO WS-FIRST
        CAPTURE ARG 1 INTO WS-FIRST-AGAIN
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="duplicate CAPTURE ARG 1"):
        parse_cut(cut)


def test_directive_with_no_capture_lines_has_empty_captures_list():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        MOVE 0 TO RETURN-CODE
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).captures == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_dsl_parser_capture.py -v`
Expected: every test FAILs — `CAPTURE ARG 1 INTO WS-CAPTURED-RATE` is not recognized by any grammar rule today, so it falls into `body_lines` verbatim (no `CutParseError`, and `_mock(cut).captures` raises `AttributeError: 'MockDirective' object has no attribute 'captures'`).

- [ ] **Step 3: Add `CAPTURE_CATEGORIES` and `MockDirective.captures`**

In `mockymock/dsl/model.py`, add the new frozenset right after `FILE_STATUS_CATEGORIES` (around line 87):

```python
# CAPTURE ARG <n> INTO <target> is valid only inside a mock body whose
# category can carry a COBOL USING clause -- CALL/DYNCALL. MQ is sugar
# for CALL at parse time (see MockCategory docstring), so it never
# appears here as its own category.
CAPTURE_CATEGORIES = frozenset({MockCategory.CALL, MockCategory.DYNCALL})
```

Then, in the `MockDirective` dataclass, add the new field right after `terminal_row` (around line 108-112):

```python
    captures: list[tuple[int, str]] = field(default_factory=list)
    """CAPTURE ARG <n> INTO <target> lines from this mock's body: (n, target)
    pairs, n a 1-based USING-parameter position, in declaration order.
    Only ever populated for CAPTURE_CATEGORIES (CALL/DYNCALL) directives;
    empty for every other category. Resolved against the real call site's
    CallStatement.using_parameters at splice time -- see
    injector.build_site_dispatch."""
```

- [ ] **Step 4: Add the `CAPTURE` grammar to the parser**

In `mockymock/dsl/parser.py`:

1. Add `CAPTURE_CATEGORIES` to the import block (around line 54-63):

```python
from mockymock.dsl.model import (
    CAPTURE_CATEGORIES,
    FILE_STATUS_CATEGORIES,
    DataProvider,
    ExpectDirective,
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
    VerifyDirective,
)
```

2. Add two new module-level regexes right after `_FILE_STATUS_PREFIX_RE` (around line 164):

```python
# CAPTURE ARG <n> INTO <target> -- n is a 1-based USING-parameter
# position (never a COBOL variable name), resolved against the real call
# site's CallStatement.using_parameters at splice time (injector.py), not
# here -- .cut parsing has no access to the target .cbl's AST. <target>
# reuses _SUBSCRIPTED_NAME, same as MOVE/EXPECT.
_CAPTURE_RE = re.compile(
    rf"^CAPTURE\s+ARG\s+(?P<index>\S+)\s+INTO\s+(?P<target>{_SUBSCRIPTED_NAME})$"
)
_CAPTURE_INDEX_RE = re.compile(r"^[1-9][0-9]*$")
```

   (This must be placed textually after `_SUBSCRIPTED_NAME` is defined,
   which it already is at line 111 — `_FILE_STATUS_PREFIX_RE` at line 164
   is safely after that point.)

3. In the body-line scanning loop (`elif (m := _FILE_STATUS_RE.match(line))
   is not None:` branch runs at line 442; `_FILE_STATUS_PREFIX_RE`'s
   fail-closed `elif` is at line 477-483), insert a new `elif` branch
   immediately after the `_FILE_STATUS_PREFIX_RE` branch and before
   `elif in_mock.rows is not None:` (line 484):

```python
            elif (m := _CAPTURE_RE.match(line)) is not None:
                if in_mock.category not in CAPTURE_CATEGORIES:
                    raise CutParseError(
                        f"line {line_no}: CAPTURE ARG is only valid inside "
                        f"MOCK CALL bodies (static or dynamic), not MOCK "
                        f"{in_mock.category.keyword}"
                    )
                index_text = m.group("index")
                if _CAPTURE_INDEX_RE.match(index_text) is None:
                    raise CutParseError(
                        f"line {line_no}: CAPTURE ARG {index_text!r} must "
                        f"be a positive integer (1-based USING parameter "
                        f"position)"
                    )
                index = int(index_text)
                if index in {n for n, _ in in_mock.captures}:
                    raise CutParseError(
                        f"line {line_no}: duplicate CAPTURE ARG {index} in "
                        f"one MOCK body -- only one CAPTURE per argument "
                        f"position is allowed"
                    )
                in_mock.captures.append((index, m.group("target")))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_dsl_parser_capture.py -v`
Expected: PASS, all 9 tests.

- [ ] **Step 6: Run the full unit suite to check for regressions**

Run: `pytest tests/unit -q`
Expected: PASS, no new failures.

- [ ] **Step 7: Lint and type-check**

Run: `ruff check mockymock/dsl/model.py mockymock/dsl/parser.py tests/unit/test_dsl_parser_capture.py && black --check mockymock/dsl/model.py mockymock/dsl/parser.py tests/unit/test_dsl_parser_capture.py && mypy mockymock/dsl/model.py mockymock/dsl/parser.py`
Expected: clean. Fix any findings before committing.

- [ ] **Step 8: Commit**

```bash
git add mockymock/dsl/model.py mockymock/dsl/parser.py tests/unit/test_dsl_parser_capture.py
git commit -m "feat: add CAPTURE ARG <n> INTO <target> grammar to MOCK CALL bodies"
```

---

### Task 2: Fail-closed refusal — `CAPTURE_ARG_OUT_OF_RANGE`

**Files:**
- Modify: `mockymock/analysis/refusal.py`
- Modify: `interface-contract.md`, `.okf/integration.md`
- Test: `tests/unit/test_refusal_capture.py` (create)

**Interfaces:**
- Consumes: `MockDirective.captures` (Task 1); `cobolparser.models.statements.call.CallStatement.using_parameters: list[CallParameter]`, `CallParameter.name: str` (pinned cobolparser attribute, not previously in mockymock's dependency surface); `BoundarySite.statement: object` (existing field, already holds the real AST node — no `mock_surface.py` change needed).
- Produces: `check_test_case` now also returns `RefusalReason(code="CAPTURE_ARG_OUT_OF_RANGE", ...)` entries — Task 4's integration proof relies on this *not* firing for a correctly-indexed capture; no other task consumes this directly.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_refusal_capture.py`:

```python
"""CAPTURE_ARG_OUT_OF_RANGE: a MOCK CALL's CAPTURE ARG <n> must not exceed
the real USING-parameter count of every reachable site it matches. Mirrors
test_refusal_file_status.py's structure for the sibling
UNRESOLVED_FILE_STATUS_TARGET check."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import check_test_case
from mockymock.dsl.parser import parse_cut

# ONE-ARG-SITE and TWO-ARG-SITE both CALL "VALIDATE", with different
# USING-parameter counts, exactly the "two physical sites sharing one
# mocked key with different arg counts" shape the design doc's "Multi-site
# nuance" section describes. BOTH-SITES PERFORMs both, giving a third,
# combined reachable set for the partial-safety test below.
SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CAPCHK.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A            PIC 9(5).
       01  WS-B            PIC 9(5).
       01  WS-CAPTURED     PIC 9(5).

       PROCEDURE DIVISION.
       BOTH-SITES.
           PERFORM ONE-ARG-SITE.
           PERFORM TWO-ARG-SITE.
       ONE-ARG-SITE.
           CALL "VALIDATE" USING WS-A.
       TWO-ARG-SITE.
           CALL "VALIDATE" USING WS-A WS-B.
"""


def _reasons_for(cut_text: str):
    result = parse_cobol(SOURCE, filename="capchk.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    suite = parse_cut(cut_text)
    case = suite.test_cases[0]
    return check_test_case(surface, result.ast, case)


def test_index_within_range_of_the_only_reachable_site_does_not_refuse():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "VALIDATE"
        CAPTURE ARG 1 INTO WS-CAPTURED
    END-MOCK
    PERFORM ONE-ARG-SITE
"""
    reasons = _reasons_for(cut)
    assert not any(r.code == "CAPTURE_ARG_OUT_OF_RANGE" for r in reasons)


def test_index_within_range_of_a_two_arg_site_does_not_refuse():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "VALIDATE"
        CAPTURE ARG 2 INTO WS-CAPTURED
    END-MOCK
    PERFORM TWO-ARG-SITE
"""
    reasons = _reasons_for(cut)
    assert not any(r.code == "CAPTURE_ARG_OUT_OF_RANGE" for r in reasons)


def test_index_exceeding_the_only_reachable_sites_arg_count_refuses():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "VALIDATE"
        CAPTURE ARG 2 INTO WS-CAPTURED
    END-MOCK
    PERFORM ONE-ARG-SITE
"""
    reasons = _reasons_for(cut)
    matches = [r for r in reasons if r.code == "CAPTURE_ARG_OUT_OF_RANGE"]
    assert len(matches) == 1
    assert "ONE-ARG-SITE" in matches[0].message
    assert "1 USING parameter" in matches[0].message


def test_shared_key_partial_safety_refuses_for_the_narrower_site():
    """Both ONE-ARG-SITE and TWO-ARG-SITE are reachable and both match the
    one MOCK CALL "VALIDATE" directive -- CAPTURE ARG 2 is valid for
    TWO-ARG-SITE but exceeds ONE-ARG-SITE's single USING parameter, so
    this must refuse (fail closed over "safe for some sites")."""
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "VALIDATE"
        CAPTURE ARG 2 INTO WS-CAPTURED
    END-MOCK
    PERFORM BOTH-SITES
"""
    reasons = _reasons_for(cut)
    matches = [r for r in reasons if r.code == "CAPTURE_ARG_OUT_OF_RANGE"]
    assert len(matches) == 1
    assert "ONE-ARG-SITE" in matches[0].message


def test_directive_with_no_captures_never_refuses():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "VALIDATE"
        MOVE 0 TO RETURN-CODE
    END-MOCK
    PERFORM BOTH-SITES
"""
    reasons = _reasons_for(cut)
    assert not any(r.code == "CAPTURE_ARG_OUT_OF_RANGE" for r in reasons)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_refusal_capture.py -v`
Expected: the "does not refuse" tests PASS vacuously (no such code exists yet to fire); `test_index_exceeding_the_only_reachable_sites_arg_count_refuses` and `test_shared_key_partial_safety_refuses_for_the_narrower_site` FAIL — `matches` is empty, `len(matches) == 1` fails. Confirm these two fail before continuing (they're the real signal this task adds).

- [ ] **Step 3: Pin the new cobolparser dependency**

In `interface-contract.md`, extend the existing `CallStatement` bullet (around line 39-44) to also mention `using_parameters`:

```markdown
- `cobolparser.models.statements.call.CallStatement.called_program: str | None`,
  `.is_dynamic: bool` (property), `.on_exception`/`.not_on_exception`/`.on_overflow: list[CobolStatement] | None`
  — when `.is_dynamic` is True, `.called_program` holds the *identifier
  name* the CALL goes through (verified empirically: `CALL WS-PGM-NAME`
  yields `called_program == "WS-PGM-NAME"`); dynamic-CALL mocking keys on
  this.
- `cobolparser.models.statements.call.CallStatement.using_parameters:
  list[CallParameter]`, `CallParameter.name: str` — the `USING` clause's
  data-names in source order, for both static and dynamic CALLs.
  `CAPTURE ARG <n> INTO <target>` resolves `<n>` against this list (1-based)
  at splice time (see `.okf/splicer.md`).
```

In `.okf/integration.md`, extend the corresponding row (around line 68-69):

```markdown
| `CallStatement.called_program: str \| None`, `.is_dynamic` (property) | dynamic-CALL mocking keys on `called_program` when `is_dynamic` |
| `CallStatement.using_parameters: list[CallParameter]`, `CallParameter.name: str` | `CAPTURE ARG <n> INTO <target>` resolves `<n>` against this list (1-based) at splice time, for both static CALL and DYNCALL sites |
| `CallStatement.on_exception` / `.not_on_exception` / `.on_overflow` | exception-branch statement lists |
```

- [ ] **Step 4: Add the `CAPTURE_ARG_OUT_OF_RANGE` check**

In `mockymock/analysis/refusal.py`:

1. Add the import (near the other `cobolparser.models.statements` imports, around line 179-189):

```python
from cobolparser.models.statements.call import CallStatement
```

2. In `check_test_case`, add a new loop right after the existing FILE-STATUS
   final pass and before `return reasons` (i.e., immediately after the
   `elif` block ending around line 1317, before line 1319's `return
   reasons`):

```python
    for directive in case.mocks:
        if not directive.captures:
            continue
        matching_sites = [
            s
            for s in surface.sites_in(reachable - mocked_flow_names)
            if directive_matches_site(directive, s)
        ]
        for index, target in directive.captures:
            for site in matching_sites:
                if not isinstance(site.statement, CallStatement):
                    continue
                arg_count = len(site.statement.using_parameters)
                if index > arg_count:
                    reasons.append(
                        RefusalReason(
                            code="CAPTURE_ARG_OUT_OF_RANGE",
                            message=(
                                f"MOCK {directive.describe()} CAPTURE ARG "
                                f"{index} INTO {target} -- the CALL at "
                                f"line {site.line} (paragraph "
                                f"'{site.paragraph_name}') only declares "
                                f"{arg_count} USING parameter"
                                f"{'s' if arg_count != 1 else ''}"
                            ),
                        )
                    )
```

   (`isinstance(site.statement, CallStatement)` is always true here in
   practice — `directive.captures` is non-empty only for `CALL`/`DYNCALL`
   directives per Task 1's parser restriction, `directive_matches_site`
   only returns sites whose `category is directive.category`, and
   `mock_surface._classify_statement` only ever creates a `CALL`/`DYNCALL`
   `BoundarySite` from a real `CallStatement`. The check exists for `mypy`
   type-narrowing, not as an expected runtime filter — same posture as
   the `ValueError`-raising defensive checks elsewhere in this pipeline.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_refusal_capture.py -v`
Expected: PASS, all 5 tests.

- [ ] **Step 6: Run the full unit suite to check for regressions**

Run: `pytest tests/unit -q`
Expected: PASS, no new failures.

- [ ] **Step 7: Lint and type-check**

Run: `ruff check mockymock/analysis/refusal.py tests/unit/test_refusal_capture.py && black --check mockymock/analysis/refusal.py tests/unit/test_refusal_capture.py && mypy mockymock/analysis/refusal.py`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add mockymock/analysis/refusal.py interface-contract.md .okf/integration.md tests/unit/test_refusal_capture.py
git commit -m "feat: refuse CAPTURE_ARG_OUT_OF_RANGE when a CAPTURE index exceeds a site's real USING-parameter count"
```

---

### Task 3: Splicer codegen — emit the resolved `MOVE`

**Files:**
- Modify: `mockymock/splicer/injector.py`
- Test: `tests/unit/test_injector.py` (modify)

**Interfaces:**
- Consumes: `MockDirective.captures` (Task 1); `BoundarySite.statement` narrowed to `CallStatement` (Task 2's same pattern); `CallStatement.using_parameters[i].name`.
- Produces: `build_site_dispatch`'s returned `list[str]` now includes, for a matched directive with non-empty `captures`, one `MOVE <real-arg-name> TO <target>` line per capture, emitted before `directive.body_lines` — Task 4's integration example is the end-to-end proof this codegen is correct.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_injector.py`, add a helper and new tests. First, add
this import at the top of the file (alongside the existing imports):

```python
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.call import CallStatement
```

Then add a helper function right after the existing `_site` helper
(after line 34):

```python
def _call_site(using_names, key="DISCRATE"):
    """A BoundarySite whose .statement is a real CallStatement with the
    given USING parameter names, in order -- what CAPTURE codegen reads."""
    statement = CallStatement(SourceLocation(line=10, column=1))
    statement.set_called_program(key)
    for name in using_names:
        statement.add_using_parameter(name)
    return BoundarySite(
        category=MockCategory.CALL,
        label="CALL",
        keys=(key,),
        match_text=None,
        paragraph_name="P",
        line=10,
        nested=False,
        statement=statement,
    )
```

Then add the new tests at the end of the file:

```python
def test_capture_emits_move_from_the_real_using_parameter_name():
    site = _call_site(["ORD-AMOUNT", "WS-DISCOUNT-PCT"])
    case = MockTestCase(
        name="capture",
        mocks=[
            MockDirective(
                MockCategory.CALL,
                "DISCRATE",
                body_lines=["MOVE 0.10 TO WS-DISCOUNT-PCT"],
                captures=[(1, "WS-CAPTURED-AMOUNT")],
            )
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    joined = "\n".join(_dispatch(suite, site))
    assert "MOVE ORD-AMOUNT TO WS-CAPTURED-AMOUNT" in joined


def test_capture_move_precedes_the_directives_own_body_lines():
    site = _call_site(["ORD-AMOUNT"])
    case = MockTestCase(
        name="capture",
        mocks=[
            MockDirective(
                MockCategory.CALL,
                "DISCRATE",
                body_lines=["MOVE 0.10 TO WS-DISCOUNT-PCT"],
                captures=[(1, "WS-CAPTURED-AMOUNT")],
            )
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    lines = _dispatch(suite, site)
    capture_index = next(
        i for i, ln in enumerate(lines) if "WS-CAPTURED-AMOUNT" in ln
    )
    body_index = next(
        i for i, ln in enumerate(lines) if "WS-DISCOUNT-PCT" in ln and "MOVE 0.10" in ln
    )
    assert capture_index < body_index


def test_multiple_captures_each_emit_their_own_move_in_declared_order():
    site = _call_site(["ORD-AMOUNT", "WS-DISCOUNT-PCT"])
    case = MockTestCase(
        name="capture",
        mocks=[
            MockDirective(
                MockCategory.CALL,
                "DISCRATE",
                captures=[(2, "WS-CAPTURED-PCT"), (1, "WS-CAPTURED-AMOUNT")],
            )
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    lines = _dispatch(suite, site)
    pct_index = next(i for i, ln in enumerate(lines) if "WS-CAPTURED-PCT" in ln)
    amount_index = next(
        i for i, ln in enumerate(lines) if "WS-CAPTURED-AMOUNT" in ln
    )
    assert "MOVE WS-DISCOUNT-PCT TO WS-CAPTURED-PCT" in lines[pct_index]
    assert "MOVE ORD-AMOUNT TO WS-CAPTURED-AMOUNT" in lines[amount_index]
    assert pct_index < amount_index


def test_directive_with_no_captures_emits_no_extra_move():
    """Zero-cost when absent: a directive with captures == [] (the
    default) must produce byte-for-byte the same dispatch as before this
    feature existed."""
    site = _call_site(["ORD-AMOUNT", "WS-DISCOUNT-PCT"])
    joined = "\n".join(_dispatch(_suite(), site))
    assert "CAPTURED" not in joined
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_injector.py -v -k capture`
Expected: `test_directive_with_no_captures_emits_no_extra_move` PASSes
vacuously (nothing reads `.captures` yet, so nothing changes). The other
three FAIL — `"MOVE ORD-AMOUNT TO WS-CAPTURED-AMOUNT" in joined` is
`False` since `build_site_dispatch` doesn't look at `directive.captures`
yet.

- [ ] **Step 3: Implement the codegen**

In `mockymock/splicer/injector.py`:

1. Add the import at the top (alongside the existing imports, around line 20-23):

```python
from cobolparser.models.statements.call import CallStatement
```

2. In `build_site_dispatch`, insert a new block right after the existing
   `if directive.category in FILE_STATUS_CATEGORIES:` block (which ends
   at line 135) and before `if directive.rows is not None and
   directive.category is MockCategory.READ:` (line 136):

```python
        if directive.captures:
            if not isinstance(site.statement, CallStatement):
                raise ValueError(
                    f"MOCK {directive.describe()} has CAPTURE ARG entries "
                    f"but the site at line {site.line} is not a CALL "
                    f"statement -- refusal gate should have caught this "
                    f"(CAPTURE_ARG_OUT_OF_RANGE)"
                )
            using = site.statement.using_parameters
            for capture_index, target in directive.captures:
                if capture_index > len(using):
                    raise ValueError(
                        f"MOCK {directive.describe()} CAPTURE ARG "
                        f"{capture_index} exceeds {len(using)} USING "
                        f"parameter(s) at line {site.line} -- refusal "
                        f"gate should have caught this "
                        f"(CAPTURE_ARG_OUT_OF_RANGE)"
                    )
                lines.append(
                    f"                   MOVE {using[capture_index - 1].name} "
                    f"TO {target}"
                )
```

   Also update the function's docstring (the block starting at line 64) to
   note the new ordering, right after the FILE-STATUS paragraph:

```python
    A directive with CAPTURE ARG <n> INTO <target> entries (CALL/DYNCALL
    only) emits one `MOVE <real using-parameter name> TO <target>` line
    per entry, resolved against this exact site's own
    CallStatement.using_parameters -- before directive.body_lines, so a
    capture always reflects the value the real caller passed, never
    something an earlier body line might otherwise have overwritten it
    with. See docs/2026-08-11-argument-capture-design.md.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_injector.py -v -k capture`
Expected: PASS, all 4 tests.

- [ ] **Step 5: Run the full unit suite to check for regressions**

Run: `pytest tests/unit -q`
Expected: PASS, no new failures.

- [ ] **Step 6: Lint and type-check**

Run: `ruff check mockymock/splicer/injector.py tests/unit/test_injector.py && black --check mockymock/splicer/injector.py tests/unit/test_injector.py && mypy mockymock/splicer/injector.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add mockymock/splicer/injector.py tests/unit/test_injector.py
git commit -m "feat: splice CAPTURE ARG's resolved MOVE before a CALL/DYNCALL mock's body lines"
```

---

### Task 4: End-to-end proof — extend the `ordrproc` example

**Files:**
- Modify: `examples/ordrproc/ORDRPROC.cbl`
- Modify: `examples/ordrproc/ORDRPROC.cut`
- Modify: `examples/ordrproc/README.md`

**Interfaces:**
- Consumes: everything from Tasks 1-3 — this task adds no new Python code, only fixture content, and re-runs the existing `tests/integration/test_ordrproc_example.py::test_committed_ordrproc_example_passes` (unchanged) as the proof.
- Produces: nothing new consumed by later tasks — this is this plan's terminal correctness proof.

- [ ] **Step 1: Extend `ORDRPROC.cbl` with a capture target field**

Read the current file first (`examples/ordrproc/ORDRPROC.cbl`) to confirm
line numbers still match before editing — it is a 15-line file today. Add
one new `01` item after the existing three, so `WORKING-STORAGE SECTION`
reads:

```cobol
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  ORD-AMOUNT          PIC 9(5)V99.
       01  WS-DISCOUNT-PCT     PIC 9V99.
       01  WS-NET-AMOUNT       PIC 9(5)V99.
       01  WS-CAPTURED-AMOUNT  PIC 9(5)V99.
```

The `PROCEDURE DIVISION` body (the `CALL "DISCRATE" USING ORD-AMOUNT
WS-DISCOUNT-PCT` statement and the `COMPUTE`) is unchanged.

- [ ] **Step 2: Extend `ORDRPROC.cut`'s first test case**

Read the current file first (`examples/ordrproc/ORDRPROC.cut`). Change
only the first `TESTCASE` block (the "10% discount..." one) to:

```
TESTSUITE "ORDRPROC discount calculation"

TESTCASE "10% discount reduces net amount correctly"
    MOCK CALL "DISCRATE"
        CAPTURE ARG 1 INTO WS-CAPTURED-AMOUNT
        MOVE 0.10 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 100.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 90.00
    EXPECT WS-CAPTURED-AMOUNT TO BE 100.00
    VERIFY "DISCRATE" WAS CALLED ONCE

TESTCASE "Zero discount leaves amount unchanged"
    MOCK CALL "DISCRATE"
        MOVE 0.00 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 50.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 50.00
```

(The second `TESTCASE` is unchanged — it stays a plain, uninstrumented
CALL mock so the example also still shows the "before" shape side by
side.)

The new `EXPECT WS-CAPTURED-AMOUNT TO BE 100.00` is real signal, not a
tautology: `WS-CAPTURED-AMOUNT` has no `VALUE` clause, so
`UT-RESET-WORKING-STORAGE` resets it to `0` before every test case (see
`.okf/splicer.md`'s WORKING-STORAGE Reset table). If `CAPTURE ARG 1`
failed to move the real `ORD-AMOUNT` value into it, this `EXPECT` would
fail against `0`, not silently pass.

- [ ] **Step 3: Run the unit static checks first (fast, no Docker)**

Run: `mockymock lint examples/ordrproc/ORDRPROC.cbl --cut examples/ordrproc/ORDRPROC.cut`

(This requires the package installed in editable mode, `pip install -e ".[dev]"` from the repo root — see `.okf/testing.md`'s dev setup, or README's "Contributing" section — so the `mockymock` console script exists. If it's not installed, use `python -c "from mockymock.cli.main import main; import sys; sys.exit(main(['lint', 'examples/ordrproc/ORDRPROC.cbl', '--cut', 'examples/ordrproc/ORDRPROC.cut']))"` instead.)
Expected: no refusals printed, exit code 0. If `CAPTURE_ARG_OUT_OF_RANGE`
or any parse error appears, fix the fixture edits above before continuing
(do not touch the engine code again in this task — Tasks 1-3 are already
proven correct by their own unit tests).

- [ ] **Step 4: Run the Docker-gated integration test**

Run: `pytest tests/integration/test_ordrproc_example.py -v`
Expected: PASS (`test_committed_ordrproc_example_passes`), requires a
reachable Docker daemon — skipped automatically otherwise (see
`.okf/testing.md`'s Docker-availability skip pattern). If Docker isn't
available in this environment, note that in the task's completion report
instead of claiming it passed.

- [ ] **Step 5: Update the worked-example's own README**

In `examples/ordrproc/README.md`, replace the body paragraph:

```markdown
# ORDRPROC example

A minimal program that calls an external `DISCRATE` subprogram to get a
discount rate, then computes a net amount. Demonstrates a static `CALL`
mock plus `CAPTURE ARG <n> INTO <target>` — capturing the real
`ORD-AMOUNT` value the program passed into `DISCRATE`, asserted with an
ordinary `EXPECT`.

```bash
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut
```

Try changing `EXPECT WS-CAPTURED-AMOUNT TO BE 100.00` to a wrong value
and re-running to see a FAIL case, or `mockymock generate ORDRPROC.cbl`
to see what auto-scaffolding produces for this program from scratch
(`CAPTURE` is hand-authoring only — the scaffold won't emit it).
```

- [ ] **Step 6: Run the full unit + integration suites once more**

Run: `pytest tests/unit -q && pytest tests/integration -q`
Expected: PASS. (Integration tests unrelated to `ordrproc` were already
passing before this task and must still pass — confirms the fixture edit
didn't disturb `test_fixture_bundle_contract.py`'s or
`test_generate_with_data_lint_gate.py`'s `ordrproc/ORDRPROC.cbl`
parametrized cases, which scan the `.cbl` independently of the hand-written
`.cut`.)

- [ ] **Step 7: Commit**

```bash
git add examples/ordrproc/ORDRPROC.cbl examples/ordrproc/ORDRPROC.cut examples/ordrproc/README.md
git commit -m "docs: demonstrate CAPTURE ARG in the ordrproc worked example, proven via Docker"
```

---

### Task 5: Documentation

**Files:**
- Modify: `.okf/dsl.md`
- Modify: `.okf/splicer.md`
- Modify: `.okf/analysis.md`
- Modify: `.okf/log.md`
- Modify: `mockymock/cli/skills/mockymock/reference/cut-dsl.md`
- Modify: `docs/2026-07-06-real-world-readiness-audit.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: the finished feature from Tasks 1-4 — this task only documents what already exists and passed its own tests; it must not describe anything not actually implemented.
- Produces: nothing consumed by other tasks — this is the plan's last task.

- [ ] **Step 1: `.okf/dsl.md` — grammar section**

Add a new subsection right after the `FILE-STATUS IS <mnemonic-or-code>`
section (after line 125, before the `## Case rules` heading at line 127):

```markdown
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
parameter count of any reachable call site the directive matches. Because
dispatch is per physical *site*, not per key, two sites sharing one
mocked key can legitimately declare a different number of `USING`
parameters — this refuses if **any** matching site has too few, even if
another matching site would be fine (fail closed over partial safety,
same posture as `UNRESOLVED_FILE_STATUS_TARGET`).

See docs/2026-08-11-argument-capture-design.md for the full design and
rejected alternatives (a dedicated `VERIFY ... WAS CALLED WITH ARG n =
value` combined syntax; capturing by COBOL variable name instead of
position; per-call history capture).
```

Also add `captures: list[tuple[int, str]]` to the `MockDirective` row of
the AST Model table (around line 256):

```markdown
| `MockDirective` | `category, key, body_lines: list[str], rows: list[list[tuple[str, str]]] \| None, terminal_row: list[tuple[str, str]] \| None, captures: list[tuple[int, str]]` | ... `captures` holds `CAPTURE ARG <n> INTO <target>` `(n, target)` pairs, only ever non-empty for CALL/DYNCALL directives ... |
```

(Keep the rest of that row's existing text — only append the `captures`
mention, don't rewrite the whole cell.)

- [ ] **Step 2: `.okf/splicer.md` — codegen ordering**

In the "Dispatch and Trap Generation (injector.py)" section, right after
the existing "FILE-STATUS default-success/override injection" paragraph
(ending around line 230, before the "`ROWS` dispatch" heading), add:

```markdown
**`CAPTURE ARG` resolution.** For a matched `CALL`/`DYNCALL` directive
with `directive.captures`, `build_site_dispatch` emits one `MOVE
<real-arg-name> TO <target>` line per `(n, target)` pair, resolved
against *this exact physical site's* own AST node
(`site.statement`, narrowed via `isinstance(..., CallStatement)` --
`BoundarySite.statement` already carries the original AST statement for
every site, so no new analysis-phase field was needed) --
`site.statement.using_parameters[n - 1].name`. Emitted before
`directive.body_lines`, in declared order. See [dsl](dsl.md)'s `CAPTURE
ARG` grammar section and docs/2026-08-11-argument-capture-design.md.
```

- [ ] **Step 3: `.okf/analysis.md` — refusal table**

In the "Per-test-case checks (`check_test_case`)" section, add a new row
to the conditions table (after the `UNSUPPORTED_MOCK_TARGET_LAYOUT` row,
around line 182):

```markdown
| a `CAPTURE ARG <n>` directive matches a reachable site whose real `CallStatement.using_parameters` has fewer than `n` entries | `CAPTURE_ARG_OUT_OF_RANGE` | the splicer would resolve `<n>` against nothing -- checked against *every* reachable matching site, so refuses even if only one of several sites sharing the mocked key is too narrow (fail closed over partial safety) |
```

- [ ] **Step 4: `.okf/log.md` — dated entry**

Add a new entry at the top of the file (after the `# mocky-mock OKF
Bundle — Update Log` heading, before the existing 2026-08-11 entry):

```markdown
## 2026-08-11 — Argument-capture assertions on mocked CALLs

`CAPTURE ARG <n> INTO <target>` inside a `MOCK CALL`/`MOCK MQ`/bare-DYNCALL
body: positionally resolves the real call site's Nth `USING` parameter
(via `BoundarySite.statement`, already carrying the AST node -- no new
analysis field needed) into an ordinary WORKING-STORAGE field, asserted
with the existing `EXPECT` (no new assertion syntax or report protocol).
New fail-closed `CAPTURE_ARG_OUT_OF_RANGE` refusal when an index exceeds
some reachable matching site's real argument count. Closes the "argument
capture/spies on mocked CALLs" gap named in the 2026-07-06 readiness
audit's Finding 6. Proven end-to-end via `examples/ordrproc/`'s existing
Docker-gated integration test. See
docs/2026-08-11-argument-capture-design.md and
docs/superpowers/plans/2026-08-11-argument-capture.md.
```

- [ ] **Step 5: AI-skill's own DSL reference**

In `mockymock/cli/skills/mockymock/reference/cut-dsl.md`, add a new
section modeled on the existing `## FILE-STATUS IS <mnemonic-or-"code">`
section (around line 168), placed right after the `### ROWS` subsection
(after line 113, before `## MOVE <value> TO <target>` at line 115):

```markdown
### `CAPTURE ARG <n> INTO <target>` -- argument capture (`CALL`/dynamic `CALL` only)

Captures the real value a mocked `CALL` was passed, so you can assert on
it with an ordinary `EXPECT`:

```
MOCK CALL "DISCRATE"
    CAPTURE ARG 1 INTO WS-CAPTURED-RATE
    MOVE 0 TO RETURN-CODE
END-MOCK
...
PERFORM CALC-DISCOUNT
EXPECT WS-CAPTURED-RATE TO BE 0.15
```

- `<n>` is 1-based and positional (the CALL's Nth `USING` argument), not
  a COBOL variable name -- it works even if different call sites of the
  same mocked key use differently-named arguments.
- If the mocked `CALL` runs more than once in one `TESTCASE` (e.g. inside
  a loop), the captured field ends up holding the *last* call's value.
- Only valid inside `MOCK CALL`/`MOCK MQ` bodies; using it elsewhere is a
  parse error.
```

- [ ] **Step 6: Close the audit finding**

In `docs/2026-07-06-real-world-readiness-audit.md`, edit the Finding 6
bullet list (around line 289-291) to strike through the closed part —
change:

```markdown
- `EXPECT` is **equality only** — no ranges, comparisons, substring, or
  tolerance; no way to assert on the *arguments* a mocked `CALL` received
  (only tally counts), and no cross-mock ordering assertions.
```

to:

```markdown
- `EXPECT` is **equality only** — no ranges, comparisons, substring, or
  tolerance, and no cross-mock ordering assertions. (Closed 2026-08-11:
  asserting on the *arguments* a mocked `CALL` received -- see
  `CAPTURE ARG <n> INTO <target>`, `docs/2026-08-11-argument-capture-design.md`.)
```

And add a new "Closed" note after the existing "Closed 2026-07-20" note
(after line 312, before the `---` separator at line 314):

```markdown
**Closed 2026-08-11**: `CAPTURE ARG <n> INTO <target>` — positional
argument capture on mocked `CALL`/dynamic-`CALL`s, asserted via the
existing `EXPECT` — landed. See
`docs/2026-08-11-argument-capture-design.md` and `examples/ordrproc/`.
```

- [ ] **Step 7: `README.md` worked-examples table**

Update the `ordrproc` row of the worked-examples table (line 140) to:

```markdown
| [`examples/ordrproc/`](examples/ordrproc/) | Smallest possible teaching example: one static `CALL`, `CAPTURE ARG` |
```

- [ ] **Step 8: Verify the OKF bundle still validates**

Run: `/okf:validate .okf --strict` (via the `okf:validate` skill) and
resolve every error before committing — per this project's own CLAUDE.md
instruction to run this before committing bundle changes.

- [ ] **Step 9: Commit**

```bash
git add .okf/dsl.md .okf/splicer.md .okf/analysis.md .okf/log.md mockymock/cli/skills/mockymock/reference/cut-dsl.md docs/2026-07-06-real-world-readiness-audit.md README.md
git commit -m "docs: document CAPTURE ARG argument capture across OKF bundle, AI skill, and audit doc"
```
