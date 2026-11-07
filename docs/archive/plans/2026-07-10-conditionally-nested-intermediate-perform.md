# Conditionally-Nested Intermediate PERFORM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the terminator early-exit chain (Approach B) follow a chain-link
`PERFORM` that is itself nested inside an `IF`/`ELSE` branch, an `EVALUATE`
`WHEN`/`WHEN OTHER` branch, or an inline `PERFORM ... END-PERFORM` loop
body — instead of refusing every terminator behind such a link.

**Architecture:** Extend `_plain_perform_edges_from`'s chain-following BFS to
recurse into nested statement bodies (reusing `mock_surface.py`'s
`_nested_statement_lists`/`_walk_statements` pattern), tagging each edge
`nested`/`in_boundary`. A new `nested_chain_perform_problem` in
`source_map.py` validates a nested edge's line-ownership and computes its
insertion point using the scope-word-aware `ScopeMap` (unlike a top-level
edge, which stays on the existing `collect_boundaries`-derived path
unchanged). `find_terminator_plans` precomputes and validates every chain
edge's insertion point up front (where `scope_map` already lives) and stores
it on a new `ChainPerform` wrapper, so `orchestrator.py`'s splicer never
needs `scope_map` and its top-level code path is untouched.

**Tech Stack:** Python 3.11+, cobolparser (editable sibling dependency),
GnuCOBOL 3.2 via the `mockymock-cobc` Docker container, pytest
(`tests/unit` no Docker, `tests/integration` `@requires_docker`).

**Design doc:** `docs/2026-07-10-conditionally-nested-intermediate-perform-design.md`
— read it before starting. This plan implements it task-by-task and does not
re-derive its reasoning. A Phase 0 empirical spike already confirmed (outside
this plan, not committed — see the design doc's Verification plan) that
`EXIT PARAGRAPH` correctly exits the whole enclosing paragraph when issued
from inside an inline `PERFORM ... END-PERFORM` loop body and control
returns correctly to the real `PERFORM` caller — the one shape in this
feature that carried genuine runtime uncertainty (the others reduce to the
already-proven mechanisms from spikes #2/#3 in
`docs/2026-07-08-goback-stop-run-support-design.md`).

## Global Constraints

- Every existing top-level chain-PERFORM code path (`statement_top_level_problem`,
  `collect_boundaries`/`statement_span`, `splice_program`'s positional
  signature) must remain byte-for-byte unchanged in behavior — this is an
  additive extension to a merged, spike-verified feature, not a rewrite.
- `UNSUPPORTED_TERMINATOR_LAYOUT` is the refusal code for every new failure
  mode this feature introduces (no new refusal code), matching existing
  precedent for every other terminator-layout shape.
- Dedup of chain-check insertions must key off `id(chain_perform.statement)`,
  never `id(chain_perform)` — two `ChainPerform` wrappers can legitimately
  wrap the same shared `PerformStatement` for two different terminators.

---

### Task 1: Extend chain-edge detection into nested statement bodies

**Files:**
- Modify: `mockymock/analysis/refusal.py` (`_plain_perform_edges_from`, ~line 928; its import block, ~line 137)
- Test: `tests/unit/test_terminator_reachability.py`

**Interfaces:**
- Consumes: `mockymock.analysis.mock_surface._nested_statement_lists` (already imported in `refusal.py`), `mockymock.analysis.mock_surface._BOUNDARY_STATEMENT_TYPES` (new import needed).
- Produces: `_plain_perform_edges_from(program, start) -> tuple[set[str], list[tuple[PerformStatement, bool]]]` — the edges list now holds `(statement, nested)` pairs instead of bare statements. This is the exact interface Task 3 consumes.

- [ ] **Step 1: Write the failing tests**

Replace `tests/unit/test_terminator_reachability.py` in full with:

```python
"""Unit tests for the two new reachability primitives Approach B's
safe-chain check depends on: which paragraphs are EVER a GO TO target
anywhere in the program, and which paragraphs are reachable from a given
start paragraph via ONLY plain, unconditional, single-shot PERFORM
statements -- now including ones nested inside IF/EVALUATE/inline-PERFORM
bodies. See docs/2026-07-08-goback-stop-run-support-design.md and
docs/2026-07-10-conditionally-nested-intermediate-perform-design.md.
"""

from cobolparser import parse_cobol

from mockymock.analysis.refusal import _go_to_targets, _plain_perform_edges_from

CHAIN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CHAINTEST.

       PROCEDURE DIVISION.
       TARGET-PARA.
           PERFORM LEVEL1-PARA.

       LEVEL1-PARA.
           PERFORM LEVEL2-PARA.

       LEVEL2-PARA.
           DISPLAY "REACHED".

       UNRELATED-PARA.
           GO TO LEVEL1-PARA.

       THRU-CALLER.
           PERFORM LEVEL2-PARA THRU LEVEL2-PARA.

       CONDITIONAL-CALLER.
           IF 1 = 1
               PERFORM LEVEL2-PARA
           END-IF.

       LOOP-CALLER.
           PERFORM LEVEL2-PARA UNTIL 1 = 1.
"""


def _program():
    result = parse_cobol(CHAIN_SOURCE, filename="chaintest.cbl")
    assert result.success, result.errors
    return result.ast


def test_go_to_targets_finds_every_go_to_target_in_whole_program():
    targets = _go_to_targets(_program())
    assert targets == {"LEVEL1-PARA"}


def test_plain_perform_edges_from_walks_the_chain():
    seen, edges = _plain_perform_edges_from(_program(), "TARGET-PARA")
    assert seen == {"TARGET-PARA", "LEVEL1-PARA", "LEVEL2-PARA"}
    assert len(edges) == 2
    assert {stmt.target_paragraph for stmt, _nested in edges} == {
        "LEVEL1-PARA",
        "LEVEL2-PARA",
    }
    assert all(nested is False for _stmt, nested in edges)


def test_plain_perform_edges_from_ignores_thru_and_goto():
    """THRU-CALLER's PERFORM...THRU and UNRELATED-PARA's GO TO must never
    contribute edges -- neither is a plain, single-shot PERFORM."""
    seen, edges = _plain_perform_edges_from(_program(), "THRU-CALLER")
    assert seen == {"THRU-CALLER"}
    assert edges == []

    seen, edges = _plain_perform_edges_from(_program(), "UNRELATED-PARA")
    assert seen == {"UNRELATED-PARA"}
    assert edges == []


def test_plain_perform_edges_from_ignores_looping_perform():
    """A PERFORM ... UNTIL is not a plain, single-shot PERFORM: EXIT
    PARAGRAPH from its target only ends the current iteration, not the
    loop, so its target must not be treated as safely reachable --
    discovered 2026-07-09 while qualifying ACCTPRG for Task 10, fixed by
    excluding perform_type != "SIMPLE" edges (see "Out of scope", below,
    and .okf/log.md)."""
    seen, edges = _plain_perform_edges_from(_program(), "LOOP-CALLER")
    assert seen == {"LOOP-CALLER"}
    assert edges == []


def test_plain_perform_edges_from_now_follows_a_conditionally_nested_perform():
    """2026-07-10: a PERFORM nested inside an IF is no longer excluded --
    it's a valid edge, tagged nested=True."""
    seen, edges = _plain_perform_edges_from(_program(), "CONDITIONAL-CALLER")
    assert seen == {"CONDITIONAL-CALLER", "LEVEL2-PARA"}
    assert len(edges) == 1
    stmt, nested = edges[0]
    assert stmt.target_paragraph == "LEVEL2-PARA"
    assert nested is True


NESTED_SHAPES_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTCHAIN.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X.

       PROCEDURE DIVISION.
       EVALUATE-CALLER.
           EVALUATE WS-FLAG
               WHEN "A"
                   PERFORM EVAL-TARGET
               WHEN OTHER
                   DISPLAY "OTHER"
           END-EVALUATE.

       EVAL-TARGET.
           DISPLAY "EVAL-TARGET".

       LOOP-BODY-CALLER.
           PERFORM UNTIL WS-FLAG = "N"
               PERFORM LOOP-TARGET
           END-PERFORM.

       LOOP-TARGET.
           DISPLAY "LOOP-TARGET".

       HANDLER-CALLER.
           CALL "SOMEPGM"
               ON EXCEPTION
                   PERFORM HANDLER-TARGET
           END-CALL.

       HANDLER-TARGET.
           DISPLAY "HANDLER-TARGET".
"""


def _nested_shapes_program():
    result = parse_cobol(NESTED_SHAPES_SOURCE, filename="nestchain.cbl")
    assert result.success, result.errors
    return result.ast


def test_plain_perform_edges_from_follows_an_evaluate_nested_perform():
    seen, edges = _plain_perform_edges_from(_nested_shapes_program(), "EVALUATE-CALLER")
    assert seen == {"EVALUATE-CALLER", "EVAL-TARGET"}
    assert len(edges) == 1
    stmt, nested = edges[0]
    assert stmt.target_paragraph == "EVAL-TARGET"
    assert nested is True


def test_plain_perform_edges_from_follows_an_inline_loop_body_perform():
    seen, edges = _plain_perform_edges_from(_nested_shapes_program(), "LOOP-BODY-CALLER")
    assert seen == {"LOOP-BODY-CALLER", "LOOP-TARGET"}
    assert len(edges) == 1
    stmt, nested = edges[0]
    assert stmt.target_paragraph == "LOOP-TARGET"
    assert nested is True


def test_plain_perform_edges_from_excludes_a_perform_inside_a_boundary_handler():
    """A PERFORM nested inside another boundary statement's clause body
    (here, CALL ... ON EXCEPTION) is never a valid edge, regardless of
    layout: splicing the enclosing CALL when it's mocked would delete the
    PERFORM and any inserted check along with it -- structural, not a v1
    scope choice. HANDLER-TARGET must never enter the reachable set."""
    seen, edges = _plain_perform_edges_from(_nested_shapes_program(), "HANDLER-CALLER")
    assert seen == {"HANDLER-CALLER"}
    assert edges == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_terminator_reachability.py -v`
Expected: the two new-shape tests and
`test_plain_perform_edges_from_now_follows_a_conditionally_nested_perform`
FAIL (today's code returns `edges == []` for all nested/handler cases and
`seen` without the nested target); the unchanged assertions
(`test_go_to_targets...`, `test_plain_perform_edges_from_walks_the_chain`,
`..._ignores_thru_and_goto`, `..._ignores_looping_perform`) still PASS.

- [ ] **Step 3: Implement the nested-body walk**

In `mockymock/analysis/refusal.py`, update the import block (~line 137):

```python
from mockymock.analysis.mock_surface import (
    _TERMINATOR_LABELS,
    BoundarySite,
    MockSurface,
    _all_paragraphs,
    _BOUNDARY_STATEMENT_TYPES,
    _nested_statement_lists,
    normalize_exec_text,
)
```

Replace `_plain_perform_edges_from` (and add the new helper immediately
before it):

```python
def _plain_perform_statements(
    statements: list, nested: bool = False, in_boundary: bool = False
) -> list[tuple[PerformStatement, bool, bool]]:
    """Recursively collect every plain, unconditional, single-shot,
    out-of-line PerformStatement in `statements` -- thru_paragraph is
    None, target_paragraph set, perform_type == "SIMPLE" -- at ANY
    nesting depth, tagged with:

    - `nested`: False only for a direct member of the paragraph's own
      top-level `.statements` list (today's only supported shape); True
      at any depth >= 1 -- an IF/ELSE branch, an EVALUATE
      WHEN/WHEN OTHER branch, or an inline PERFORM ... END-PERFORM loop
      body (via _nested_statement_lists' then_statements/else_statements/
      when_clauses/inline_statements).
    - `in_boundary`: sticky -- True once recursion has entered another
      boundary statement's clause body (CALL's ON EXCEPTION, a file
      statement's AT END, ...). Mirrors mock_surface._walk_statements'
      identical child_in_boundary propagation: a PERFORM found there is
      never a valid chain edge, because splicing the enclosing boundary
      statement (when it's mocked) removes the PERFORM and any inserted
      check along with it -- the same structural reason a nested
      BoundarySite there is unsplicable.

    Every recursive call passes nested=True literally (not the parent's
    nested value), matching mock_surface._walk_statements' own pattern,
    so a PERFORM is marked nested at every depth >= 1 while a genuinely
    top-level one (the initial call, nested defaults to False) stays
    unmarked. See docs/2026-07-10-conditionally-nested-intermediate-perform-design.md.
    """
    found: list[tuple[PerformStatement, bool, bool]] = []
    for statement in statements:
        if (
            isinstance(statement, PerformStatement)
            and statement.thru_paragraph is None
            and statement.target_paragraph
            and statement.perform_type == "SIMPLE"
        ):
            found.append((statement, nested, in_boundary))
        child_in_boundary = in_boundary or isinstance(
            statement, _BOUNDARY_STATEMENT_TYPES
        )
        for nested_list in _nested_statement_lists(statement):
            found.extend(
                _plain_perform_statements(
                    nested_list, nested=True, in_boundary=child_in_boundary
                )
            )
    return found


def _plain_perform_edges_from(
    program, start: str
) -> tuple[set[str], list[tuple[PerformStatement, bool]]]:
    """BFS from `start` following plain (non-THRU), unconditional,
    single-shot PERFORM statements -- PerformStatement nodes with
    thru_paragraph is None and perform_type == "SIMPLE" -- at ANY nesting
    depth within a paragraph (top-level, or nested inside an IF/ELSE
    branch, an EVALUATE WHEN/WHEN OTHER branch, or an inline
    PERFORM ... END-PERFORM loop body). A PERFORM nested inside another
    boundary statement's clause body (CALL's ON EXCEPTION, a file
    statement's AT END, ...) is never followed -- see
    _plain_perform_statements.

    A PERFORM ... UNTIL/VARYING/TIMES (perform_type != "SIMPLE") is
    deliberately NOT followed and NOT added to the edge set, even though
    it also carries a `target_paragraph` with `thru_paragraph is None`:
    the early-exit mechanism sets a flag and does `EXIT PARAGRAPH`, which
    only ends the CURRENT iteration of the looped paragraph -- control
    returns to the loop construct, which re-checks its own unrelated
    UNTIL/VARYING/TIMES condition and may iterate again. A terminator
    reached from inside a loop's target would silently run extra
    unwanted iterations instead of stopping, which was proven empirically
    (a synthetic STOP RUN placed inside a looped paragraph kept iterating
    past it). Excluding the edge means such a terminator's paragraph never
    enters `seen`, so `find_terminator_plans` naturally refuses it via the
    existing "reachable but not via a plain chain" check -- no new
    refusal branch needed. (This is distinct from a PERFORM nested INSIDE
    an inline `PERFORM ... END-PERFORM` loop BODY, which IS followed --
    EXIT PARAGRAPH from inside an inline loop body correctly exits the
    whole enclosing paragraph, verified empirically 2026-07-10; the
    excluded case here is an OUT-OF-LINE PERFORM that IS itself a loop
    over a different paragraph.)

    SECTION members are excluded entirely: this only looks up names in
    `procedure.paragraphs` (top-level paragraphs), never
    `procedure._sections[...].paragraphs` -- a paragraph that only exists
    as a section member is an unreachable dead end here, naturally
    refusing any chain that would need to pass through one (SECTION
    support is deferred -- see the design doc).

    Returns (reachable paragraph names via this restricted edge set, the
    (PerformStatement, nested) pairs that ARE those edges) -- every one of
    those statements is a candidate for the early-exit flag-check
    instrumentation, `nested` telling the caller which validator/
    insertion-point computation applies. Deliberately NOT the same as
    `_reachable_paragraphs`: that function also follows GO TO and
    section/THRU fall-through edges, exactly the unsafe shapes this
    restricted variant must exclude."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set(), []
    by_name = {p.paragraph_name: p for p in procedure.paragraphs}
    seen = {start}
    stack = [start]
    edges: list[tuple[PerformStatement, bool]] = []
    while stack:
        name = stack.pop()
        paragraph = by_name.get(name)
        if paragraph is None:
            continue
        for statement, nested, in_boundary in _plain_perform_statements(
            paragraph.statements
        ):
            if in_boundary:
                continue
            edges.append((statement, nested))
            target = statement.target_paragraph
            if target not in seen:
                seen.add(target)
                stack.append(target)
    return seen, edges
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_terminator_reachability.py -v`
Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mockymock/analysis/refusal.py tests/unit/test_terminator_reachability.py
git commit -m "feat(analysis): follow conditionally-nested intermediate PERFORM edges"
```

---

### Task 2: Add the nested-chain-PERFORM span/validation function

**Files:**
- Modify: `mockymock/splicer/source_map.py`
- Test: `tests/unit/test_source_map.py`

**Interfaces:**
- Consumes: `ScopeMap`/`collect_scope_map` (existing), `PerformStatement` (`cobolparser.models.statements.control`).
- Produces: `nested_chain_perform_problem(statement, scope_map, lines) -> tuple[tuple[int, int] | None, str | None]` — `(span, None)` on success where `span[1]` is the line to insert the flag-check after; `(None, reason)` on failure. This is the exact interface Task 3 consumes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_source_map.py` (after the existing
`statement_top_level_problem` tests at the end of the file):

```python
# --- nested_chain_perform_problem (conditionally-nested intermediate PERFORM) ---

from mockymock.splicer.source_map import nested_chain_perform_problem

NESTED_PERFORM_OWN_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTPERFORMOK.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X.

       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-FLAG = "Y"
               PERFORM SUB-PARA
           END-IF
           DISPLAY "AFTER".

       SUB-PARA.
           DISPLAY "SUB".
"""

NESTED_PERFORM_SHARES_END_IF_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTPERFORMBAD.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X.

       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-FLAG = "Y" PERFORM SUB-PARA END-IF
           DISPLAY "AFTER".

       SUB-PARA.
           DISPLAY "SUB".
"""

NESTED_PERFORM_EVALUATE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTPERFORMEVAL.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X.

       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE WS-FLAG
               WHEN "A"
                   PERFORM SUB-PARA
               WHEN OTHER
                   DISPLAY "OTHER"
           END-EVALUATE.

       SUB-PARA.
           DISPLAY "SUB".
"""


def test_nested_chain_perform_problem_none_when_perform_owns_its_line():
    result = parse_cobol(NESTED_PERFORM_OWN_LINE_SOURCE, filename="x.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(
        NESTED_PERFORM_OWN_LINE_SOURCE.splitlines()
    ).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    perform = _find_perform(result.ast, "MAIN-PARA")
    span, reason = nested_chain_perform_problem(perform, scope_map, lines)
    assert reason is None
    start, end = span
    assert start == _line_of(lines, "PERFORM SUB-PARA")
    assert "END-IF" in lines[end]  # insertion point is right before END-IF


def test_nested_chain_perform_problem_set_when_perform_shares_line_with_end_if():
    result = parse_cobol(NESTED_PERFORM_SHARES_END_IF_SOURCE, filename="x.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(
        NESTED_PERFORM_SHARES_END_IF_SOURCE.splitlines()
    ).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    perform = _find_perform(result.ast, "MAIN-PARA")
    span, reason = nested_chain_perform_problem(perform, scope_map, lines)
    assert span is None
    assert "shares its start line" in reason


def test_nested_chain_perform_problem_none_inside_evaluate_when_branch():
    result = parse_cobol(NESTED_PERFORM_EVALUATE_SOURCE, filename="x.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(
        NESTED_PERFORM_EVALUATE_SOURCE.splitlines()
    ).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    perform = _find_perform(result.ast, "MAIN-PARA")
    span, reason = nested_chain_perform_problem(perform, scope_map, lines)
    assert reason is None
    start, end = span
    assert start == _line_of(lines, "PERFORM SUB-PARA")
    assert "WHEN OTHER" in lines[end]
```

Note: `_find_perform` (the existing shared helper near
`statement_top_level_problem`'s tests, ~line 525) only looks up a
paragraph's TOP-LEVEL `.statements`, which is fine for its existing
callers but not for these three new tests -- their target PERFORM is
nested inside an `IF`/`EVALUATE`, not top-level. Before adding the tests
above, update `_find_perform` in place to search recursively, so both the
existing top-level tests and these new nested tests share the same
helper:

```python
def _find_perform(program, paragraph_name):
    from mockymock.analysis.mock_surface import _nested_statement_lists

    procedure = program.get_division("PROCEDURE")
    paragraph = next(
        p for p in procedure.paragraphs if p.paragraph_name == paragraph_name
    )

    def _search(statements):
        for statement in statements:
            if isinstance(statement, PerformStatement):
                return statement
            for nested in _nested_statement_lists(statement):
                found = _search(nested)
                if found is not None:
                    return found
        return None

    # Not `.statements[0]`: PERFORM_SHARED_LINE_SOURCE's MAIN-PARA holds a
    # MoveStatement *then* the PerformStatement on the same line -- depth-
    # first search over top-level statements first, then nested bodies,
    # finds the right one either way (verified empirically against
    # cobolparser's parse).
    found = _search(paragraph.statements)
    assert found is not None, f"no PerformStatement found in {paragraph_name}"
    return found
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_source_map.py -v -k nested_chain_perform`
Expected: FAIL with `ImportError: cannot import name 'nested_chain_perform_problem'`.

- [ ] **Step 3: Implement `nested_chain_perform_problem`**

In `mockymock/splicer/source_map.py`, add after `statement_top_level_problem`
(~line 337):

```python
def nested_chain_perform_problem(
    statement, scope_map: ScopeMap, lines: list[str]
) -> tuple[tuple[int, int] | None, str | None]:
    """The reason a NESTED intermediate-PERFORM statement (one
    `_plain_perform_edges_from` found inside an IF/ELSE branch, an
    EVALUATE WHEN/WHEN OTHER branch, or an inline PERFORM ... END-PERFORM
    loop body) cannot safely host an inserted early-exit flag-check
    immediately after it, or ((start, end), None) when it can.

    `end` is the line to insert the check after -- the next scope-map
    boundary (of ANY kind: another statement start at any depth, or a
    scope word like END-IF/ELSE/WHEN/END-PERFORM), minus one -- so the
    check lands immediately after the PERFORM, inside the same
    conditional/loop branch, before whatever closes it. This is a trimmed
    sibling of `_nested_site_span`'s span-end computation: it drops the
    EXEC-range and `_VERB_TERMINATORS` handling, neither of which applies
    to a plain out-of-line PERFORM statement (a SIMPLE out-of-line
    PERFORM has no clause body of its own, so there is no "own
    terminator" token to exclude the way a CALL's END-CALL is excluded
    for a nested CALL boundary site).

    Unlike `statement_top_level_problem` (used for a TOP-LEVEL chain
    PERFORM), this checks against the FULL, unfiltered
    `scope_map.boundaries` -- not just `top_level`-flagged entries -- so
    it correctly detects a PERFORM sharing its line with a scope word
    like END-IF, which `statement_top_level_problem`'s `b.top_level`
    filter would silently miss. See
    docs/2026-07-10-conditionally-nested-intermediate-perform-design.md.
    """
    start = statement.location.line
    column = statement.location.column
    if lines[start - 1][: column - 1].strip():
        return None, "does not start its own line"

    if any(
        b.line == start and not (b.column == column and b.word == "")
        for b in scope_map.boundaries
    ):
        return None, "shares its start line with another statement or scope word"

    following = [b for b in scope_map.boundaries if b.line > start]
    if not following:
        return None, "no following statement or scope word to bound the insertion point"
    nxt = following[0]
    if lines[nxt.line - 1][: nxt.column - 1].strip():
        return None, (
            f"the next scope word or statement (line {nxt.line}) does not "
            f"start its own line"
        )

    return (start, nxt.line - 1), None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_source_map.py -v -k "nested_chain_perform or statement_top_level_problem"`
Expected: all PASS (the pre-existing `statement_top_level_problem` tests
must still pass unchanged after the `_find_perform` helper edit).

Run: `pytest tests/unit/test_source_map.py -v`
Expected: full file PASSES (no regressions from the `_find_perform` change).

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/source_map.py tests/unit/test_source_map.py
git commit -m "feat(splicer): validate and locate nested chain-PERFORM insertion points"
```

---

### Task 3: Wire nested edges into `find_terminator_plans` via `ChainPerform`

**Files:**
- Modify: `mockymock/analysis/refusal.py` (`TerminatorPlan`, `find_terminator_plans`, imports)
- Test: `tests/unit/test_terminators.py`

**Interfaces:**
- Consumes: Task 1's `_plain_perform_edges_from` returning `list[tuple[PerformStatement, bool]]`; Task 2's `nested_chain_perform_problem`.
- Produces: `ChainPerform` dataclass (`statement: PerformStatement`, `insertion_line: int | None = None`); `TerminatorPlan.chain_performs: list[ChainPerform]`. This is the exact interface Task 4 consumes.

- [ ] **Step 1: Write the failing tests**

Read `tests/unit/test_terminators.py` first to find the exact two lines
reading `chain_performs` elements directly (`{p.target_paragraph for p in
plans[0].chain_performs}`, at the safe-plain-chain and
intermediate-perform-in-chain tests) and change both to
`{p.statement.target_paragraph for p in plans[0].chain_performs}`.

Then append these new tests at the end of the file:

```python
NESTED_CHAIN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTEDCHAIN.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.
       01  WS-FLAG             PIC X VALUE "Y".

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-WRAPPER
           DISPLAY "AFTER-WRAPPER".

       1000-WRAPPER.
           IF WS-FLAG = "Y"
               PERFORM 2000-INNER
           END-IF
           DISPLAY "AFTER-INNER-CALL".

       2000-INNER.
           CALL "CALCPGM" USING WS-RESULT
           STOP RUN.
"""

NESTED_CHAIN_SHARED_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTEDCHAINBAD.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG             PIC X VALUE "Y".

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-WRAPPER.

       1000-WRAPPER.
           IF WS-FLAG = "Y" PERFORM 2000-INNER END-IF
           DISPLAY "AFTER".

       2000-INNER.
           STOP RUN.
"""


def _plan_fixture(source, filename):
    result = parse_cobol(source, filename=filename)
    assert result.success, result.errors
    program = result.ast
    surface = analyze(program)
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    scope_map = collect_scope_map(program, lines)
    annotate_nested_sites(surface, scope_map, lines)
    return program, surface, scope_map, lines


def test_find_terminator_plans_accepts_a_conditionally_nested_intermediate_perform():
    program, surface, scope_map, lines = _plan_fixture(
        NESTED_CHAIN_SOURCE, "nestedchain.cbl"
    )
    suite = MockTestSuite(
        name="T",
        test_cases=[
            MockTestCase(
                name="main",
                mocks=[
                    MockDirective(
                        MockCategory.CALL, "CALCPGM", ["MOVE 42 TO WS-RESULT"]
                    )
                ],
                perform_target="0000-MAIN-PROCESS",
            )
        ],
    )
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert {p.statement.target_paragraph for p in plans[0].chain_performs} == {
        "1000-WRAPPER",
        "2000-INNER",
    }
    nested_entry = next(
        p for p in plans[0].chain_performs if p.statement.target_paragraph == "2000-INNER"
    )
    assert nested_entry.insertion_line is not None
    top_level_entry = next(
        p
        for p in plans[0].chain_performs
        if p.statement.target_paragraph == "1000-WRAPPER"
    )
    assert top_level_entry.insertion_line is None


def test_find_terminator_plans_refuses_a_nested_perform_sharing_its_line():
    program, surface, scope_map, lines = _plan_fixture(
        NESTED_CHAIN_SHARED_LINE_SOURCE, "nestedchainbad.cbl"
    )
    suite = MockTestSuite(
        name="T",
        test_cases=[MockTestCase(name="main", perform_target="0000-MAIN-PROCESS")],
    )
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "nested inside a conditional" in reasons[0].message
```

Check the top of `tests/unit/test_terminators.py` for existing imports of
`parse_cobol`, `analyze`, `normalize_fixed_format`, `collect_scope_map`,
`annotate_nested_sites`, `MockTestSuite`, `MockTestCase`, `MockDirective`,
`MockCategory` — add any missing from this list (all are already used
elsewhere in this codebase's tests, e.g. `tests/unit/test_orchestrator.py`,
so match those import paths exactly).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_terminators.py -v`
Expected: the two updated `chain_performs` assertions FAIL with
`AttributeError` (tuples/statements don't have the shape the old assertion
expects until Step 3 lands — actually at this point `chain_performs` still
holds bare `PerformStatement`s from the pre-Task-3 code, so
`p.statement.target_paragraph` fails with `AttributeError: 'PerformStatement'
object has no attribute 'statement'`); the two new nested-chain tests FAIL
(the first refuses today via `UNSUPPORTED_TERMINATOR_LAYOUT` since nested
edges aren't in `safe_names` pre-Task-1... wait, Task 1 already landed, so
today this test reaches `chain_problem` = None and produces a plan, but
`insertion_line` doesn't exist yet -- FAIL with `AttributeError`).

- [ ] **Step 3: Implement `ChainPerform` and the branching validation**

In `mockymock/analysis/refusal.py`, add the import (~line 153):

```python
from mockymock.splicer.source_map import (
    nested_chain_perform_problem,
    statement_top_level_problem,
)
```

Add `ChainPerform` right before `TerminatorPlan` (~line 174):

```python
@dataclass
class ChainPerform:
    """One intermediate PERFORM statement on a terminator's safe chain.
    `insertion_line` is None for a top-level edge -- orchestrator.py keeps
    using its existing `statement_span`+`collect_boundaries` computation
    for those, completely unchanged. For a nested edge (found inside an
    IF/EVALUATE/inline-PERFORM body), `insertion_line` is precomputed and
    validated here, using `scope_map` (which orchestrator.py's splicer
    never receives) -- exactly the line `nested_chain_perform_problem`
    confirmed is safe to insert the flag-check after. See
    docs/2026-07-10-conditionally-nested-intermediate-perform-design.md."""

    statement: PerformStatement
    insertion_line: int | None = None
```

Update `TerminatorPlan`'s docstring reference to `chain_performs` type (no
code change needed there, just note the type is now `list[ChainPerform]`
in the class's existing docstring at ~line 174-182 — update the words
"every intermediate PERFORM statement" to "every intermediate PERFORM
statement, wrapped in a ChainPerform").

Now update `find_terminator_plans`'s per-case loop (~line 1059-1080),
replacing:

```python
        safe_names, chain_performs = _plain_perform_edges_from(
            program, case.perform_target
        )
        chain_section_names = safe_names - top_level_names
        chain_go_to_names = safe_names & go_to_targets

        chain_problem: str | None = None
        for perform in chain_performs:
            line_problem = statement_top_level_problem(perform, scope_map, lines)
            if line_problem is not None:
                chain_problem = (
                    f"an intermediate PERFORM {perform.target_paragraph} at "
                    f"line {perform.location.line} {line_problem} -- "
                    f"inserting the early-exit check after it would corrupt "
                    f"sibling code sharing its line"
                )
                break
```

with:

```python
        safe_names, chain_edges = _plain_perform_edges_from(
            program, case.perform_target
        )
        chain_section_names = safe_names - top_level_names
        chain_go_to_names = safe_names & go_to_targets

        chain_problem: str | None = None
        chain_performs: list[ChainPerform] = []
        for perform, nested in chain_edges:
            if nested:
                span, reason = nested_chain_perform_problem(perform, scope_map, lines)
                if reason is not None:
                    chain_problem = (
                        f"an intermediate PERFORM {perform.target_paragraph} "
                        f"at line {perform.location.line}, nested inside a "
                        f"conditional/loop body, {reason} -- inserting the "
                        f"early-exit check there would corrupt sibling code "
                        f"or land outside the conditional"
                    )
                    break
                chain_performs.append(ChainPerform(perform, insertion_line=span[1]))
            else:
                line_problem = statement_top_level_problem(perform, scope_map, lines)
                if line_problem is not None:
                    chain_problem = (
                        f"an intermediate PERFORM {perform.target_paragraph} "
                        f"at line {perform.location.line} {line_problem} -- "
                        f"inserting the early-exit check after it would "
                        f"corrupt sibling code sharing its line"
                    )
                    break
                chain_performs.append(ChainPerform(perform))
```

Finally, update the dedup merge loop at the bottom of the per-case block
(~line 1162-1168), replacing:

```python
        for key in qualified_keys:
            plan = plans_by_statement[key]
            existing_ids = {id(p) for p in plan.chain_performs}
            for perform in chain_performs:
                if id(perform) not in existing_ids:
                    plan.chain_performs.append(perform)
                    existing_ids.add(id(perform))
```

with:

```python
        for key in qualified_keys:
            plan = plans_by_statement[key]
            existing_ids = {id(cp.statement) for cp in plan.chain_performs}
            for chain_perform in chain_performs:
                if id(chain_perform.statement) not in existing_ids:
                    plan.chain_performs.append(chain_perform)
                    existing_ids.add(id(chain_perform.statement))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_terminators.py -v`
Expected: all PASS.

Run: `pytest tests/unit/ -v -k terminator`
Expected: all PASS (`test_terminators.py`, `test_terminator_reachability.py`
both green together).

- [ ] **Step 5: Commit**

```bash
git add mockymock/analysis/refusal.py tests/unit/test_terminators.py
git commit -m "feat(analysis): precompute nested chain-PERFORM insertion points in ChainPerform"
```

---

### Task 4: Wire `ChainPerform.insertion_line` into the splicer

**Files:**
- Modify: `mockymock/splicer/orchestrator.py` (chain-check insertion loop, ~line 167-175)
- Test: `tests/unit/test_orchestrator.py`

**Interfaces:**
- Consumes: Task 3's `TerminatorPlan.chain_performs: list[ChainPerform]`.
- Produces: no new public interface — this is the final consumer.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_orchestrator.py` (after
`test_perform_immediately_followed_by_terminator_interleaves_correctly`,
reusing that section's imports):

```python
NESTED_TERMINATOR_CHAIN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTEDTERMCHAIN.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.
       01  WS-FLAG             PIC X VALUE "Y".

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-WRAPPER
           DISPLAY "AFTER-WRAPPER".

       1000-WRAPPER.
           IF WS-FLAG = "Y"
               PERFORM 2000-INNER
           END-IF
           DISPLAY "AFTER-INNER-CALL".

       2000-INNER.
           CALL "CALCPGM" USING WS-RESULT
           STOP RUN.
"""


def test_chain_check_lands_inside_the_if_after_a_nested_intermediate_perform():
    result = parse_cobol(NESTED_TERMINATOR_CHAIN_SOURCE, filename="nestedtermchain.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(
        NESTED_TERMINATOR_CHAIN_SOURCE.splitlines()
    ).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    boundaries = collect_boundaries(result.ast)
    suite = MockTestSuite(
        name="T",
        test_cases=[
            MockTestCase(
                name="main",
                mocks=[
                    MockDirective(
                        MockCategory.CALL, "CALCPGM", ["MOVE 42 TO WS-RESULT"]
                    )
                ],
                perform_target="0000-MAIN-PROCESS",
            )
        ],
    )
    plans, reasons = find_terminator_plans(surface, result.ast, suite, scope_map, lines)
    assert reasons == []
    spliced = splice_program(
        lines, boundaries, surface, suite, TallyRegistry(suite), plans
    )
    joined = "\n".join(spliced)
    # both the top-level PERFORM 1000-WRAPPER and the nested PERFORM
    # 2000-INNER get a chain-check; neither PERFORM's own line is touched
    assert "PERFORM 1000-WRAPPER" in joined
    assert "PERFORM 2000-INNER" in joined
    assert joined.count('IF UT-EARLY-EXIT = "Y"') == 2
    # the nested check must land BEFORE 1000-WRAPPER's END-IF, i.e. still
    # inside the IF block, not after it
    perform_2000_idx = next(
        i for i, line in enumerate(spliced) if "PERFORM 2000-INNER" in line
    )
    end_if_idx = next(
        i
        for i in range(perform_2000_idx + 1, len(spliced))
        if "END-IF" in spliced[i]
    )
    check_indices = [
        i for i, line in enumerate(spliced) if 'IF UT-EARLY-EXIT = "Y"' in line
    ]
    nested_check_idx = next(i for i in check_indices if perform_2000_idx < i < end_if_idx)
    assert nested_check_idx < end_if_idx
    # AFTER-INNER-CALL must never run if the flag is set -- still inside
    # the paragraph, but after the IF -- this test only checks splice
    # shape (a Docker integration test in Task 5 checks runtime behavior)
    assert 'DISPLAY "AFTER-INNER-CALL"' in joined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_orchestrator.py -v -k nested_intermediate_perform`
Expected: FAIL — today's `orchestrator.py` calls
`statement_span(perform, boundaries, last_line)` unconditionally (it
expects a bare `PerformStatement`, not a `ChainPerform`), so this either
raises `AttributeError` (no `.location` on a dataclass access path
mismatch) or mis-times the insertion using the coarse top-level
`boundaries` list, landing the check outside the `IF`. Either way the
`nested_check_idx < end_if_idx` assertion fails.

- [ ] **Step 3: Implement the branch in `orchestrator.py`**

In `mockymock/splicer/orchestrator.py`, replace the chain-check insertion
loop (~line 167-175):

```python
    seen_perform_ids: set[int] = set()
    insertions: list[tuple[int, list[str]]] = []
    for plan in terminator_plans:
        for perform in plan.chain_performs:
            if id(perform) in seen_perform_ids:
                continue
            seen_perform_ids.add(id(perform))
            _, end = statement_span(perform, boundaries, last_line)
            insertions.append((end, build_chain_check()))
```

with:

```python
    seen_perform_ids: set[int] = set()
    insertions: list[tuple[int, list[str]]] = []
    for plan in terminator_plans:
        for chain_perform in plan.chain_performs:
            if id(chain_perform.statement) in seen_perform_ids:
                continue
            seen_perform_ids.add(id(chain_perform.statement))
            if chain_perform.insertion_line is not None:
                end = chain_perform.insertion_line
            else:
                _, end = statement_span(chain_perform.statement, boundaries, last_line)
            insertions.append((end, build_chain_check()))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_orchestrator.py -v`
Expected: all PASS, including every pre-existing terminator-chain test
(`test_terminator_is_replaced_with_flag_and_exit_paragraph`,
`test_intermediate_performs_get_chain_check_inserted_after`,
`test_terminator_splice_coexists_with_mocked_call_splice`,
`test_no_terminator_plans_argument_leaves_existing_behavior_unchanged`,
`test_chain_check_survives_a_mocked_call_spliced_earlier_in_the_file`,
`test_two_terminators_in_one_paragraph_are_each_neutralized_and_chain_check_deduped`,
`test_perform_immediately_followed_by_terminator_interleaves_correctly`) —
these exercise only top-level chains, so this task's change must not
alter their output at all.

Run: `pytest tests/unit/ -v`
Expected: full unit suite PASSES.

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "feat(splicer): insert chain-checks at precomputed nested insertion points"
```

---

### Task 5: End-to-end Docker regression fixtures

**Files:**
- Modify: `tests/integration/test_terminator_support.py`

**Interfaces:**
- Consumes: `mockymock.cli.main.main` (existing, unchanged), the full pipeline built by Tasks 1-4.
- Produces: none (terminal task).

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_terminator_support.py`:

```python
@requires_docker
def test_terminator_behind_an_if_nested_intermediate_perform_passes(
    tmp_path: Path, capsys
):
    """N1: the chain-link PERFORM is nested inside an IF in its own
    paragraph; a trailing DISPLAY in that paragraph must not run once the
    flag propagates. Runtime mechanism already proven by spikes #2/#3 in
    docs/2026-07-08-goback-stop-run-support-design.md; this is the
    permanent end-to-end fixture through the real mockymock CLI. See
    docs/2026-07-10-conditionally-nested-intermediate-perform-design.md."""
    cbl_path = tmp_path / "IFNEST.cbl"
    cbl_path.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. IFNEST.\n"
        "\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-RESULT           PIC 9(4) VALUE 0.\n"
        '       01  WS-FLAG             PIC X VALUE "Y".\n'
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        "           PERFORM 1000-WRAPPER\n"
        "           DISPLAY \"AFTER-WRAPPER\".\n"
        "\n"
        "       1000-WRAPPER.\n"
        '           IF WS-FLAG = "Y"\n'
        "               PERFORM 2000-INNER\n"
        "           END-IF\n"
        "           DISPLAY \"MUST-NOT-PRINT\".\n"
        "\n"
        "       2000-INNER.\n"
        '           CALL "CALCPGM" USING WS-RESULT\n'
        "           STOP RUN.\n"
    )
    cut_path = tmp_path / "IFNEST.cut"
    cut_path.write_text(
        'TESTSUITE "ifnest"\n'
        "\n"
        'TESTCASE "reaches terminator via an if-nested intermediate perform"\n'
        '    MOCK CALL "CALCPGM"\n'
        "        MOVE 42 TO WS-RESULT\n"
        "    END-MOCK\n"
        "    PERFORM 0000-MAIN-PROCESS\n"
        "    EXPECT WS-RESULT TO BE 42\n"
    )

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "[PASS]" in out
    assert "CRASH" not in out
    assert "FAIL" not in out


@requires_docker
def test_terminator_behind_an_evaluate_nested_intermediate_perform_passes(
    tmp_path: Path, capsys
):
    """N3: the chain-link PERFORM is nested inside an EVALUATE WHEN
    branch."""
    cbl_path = tmp_path / "EVALNEST.cbl"
    cbl_path.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. EVALNEST.\n"
        "\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-RESULT           PIC 9(4) VALUE 0.\n"
        '       01  WS-FLAG             PIC X VALUE "A".\n'
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        "           PERFORM 1000-WRAPPER\n"
        "           DISPLAY \"AFTER-WRAPPER\".\n"
        "\n"
        "       1000-WRAPPER.\n"
        "           EVALUATE WS-FLAG\n"
        '               WHEN "A"\n'
        "                   PERFORM 2000-INNER\n"
        "               WHEN OTHER\n"
        "                   DISPLAY \"OTHER-BRANCH\"\n"
        "           END-EVALUATE\n"
        "           DISPLAY \"MUST-NOT-PRINT\".\n"
        "\n"
        "       2000-INNER.\n"
        '           CALL "CALCPGM" USING WS-RESULT\n'
        "           STOP RUN.\n"
    )
    cut_path = tmp_path / "EVALNEST.cut"
    cut_path.write_text(
        'TESTSUITE "evalnest"\n'
        "\n"
        'TESTCASE "reaches terminator via an evaluate-nested intermediate perform"\n'
        '    MOCK CALL "CALCPGM"\n'
        "        MOVE 42 TO WS-RESULT\n"
        "    END-MOCK\n"
        "    PERFORM 0000-MAIN-PROCESS\n"
        "    EXPECT WS-RESULT TO BE 42\n"
    )

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "[PASS]" in out
    assert "CRASH" not in out
    assert "FAIL" not in out


@requires_docker
def test_terminator_behind_an_inline_loop_nested_intermediate_perform_passes(
    tmp_path: Path, capsys
):
    """N4: the chain-link PERFORM is nested inside an inline
    PERFORM ... END-PERFORM loop body, in the SAME paragraph as the loop
    -- the one shape in this feature with genuine runtime uncertainty
    (does EXIT PARAGRAPH from inside an inline loop body exit the whole
    paragraph, or just the current iteration?), confirmed empirically via
    a Phase 0 spike before this feature was built -- see
    docs/2026-07-10-conditionally-nested-intermediate-perform-design.md.
    The loop must stop propagating extra iterations once the flag is set:
    WS-COUNT must never reach past the iteration that set the flag."""
    cbl_path = tmp_path / "LOOPNEST.cbl"
    cbl_path.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. LOOPNEST.\n"
        "\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-RESULT           PIC 9(4) VALUE 0.\n"
        "       01  WS-COUNT            PIC 9(2) VALUE 0.\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        "           PERFORM 1000-WRAPPER\n"
        "           DISPLAY \"AFTER-WRAPPER, COUNT=\" WS-COUNT.\n"
        "\n"
        "       1000-WRAPPER.\n"
        "           PERFORM UNTIL WS-COUNT > 5\n"
        "               ADD 1 TO WS-COUNT\n"
        "               PERFORM 2000-INNER\n"
        "           END-PERFORM.\n"
        "\n"
        "       2000-INNER.\n"
        "           IF WS-COUNT = 2\n"
        '               CALL "CALCPGM" USING WS-RESULT\n'
        "               STOP RUN\n"
        "           END-IF.\n"
    )
    cut_path = tmp_path / "LOOPNEST.cut"
    cut_path.write_text(
        'TESTSUITE "loopnest"\n'
        "\n"
        'TESTCASE "reaches terminator via an inline-loop-nested intermediate perform"\n'
        '    MOCK CALL "CALCPGM"\n'
        "        MOVE 42 TO WS-RESULT\n"
        "    END-MOCK\n"
        "    PERFORM 0000-MAIN-PROCESS\n"
        "    EXPECT WS-RESULT TO BE 42\n"
    )

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "[PASS]" in out
    assert "CRASH" not in out
    assert "FAIL" not in out
    # the terminator fired at COUNT=2 -- if the flag failed to stop the
    # loop, COUNT would reach 6 instead
    assert "COUNT=02" in out
    assert "COUNT=06" not in out
```

- [ ] **Step 2: Run the new tests — this is an end-to-end confirmation, not a red-green cycle**

Unlike Tasks 1-4, these tests are not driving new production code — Tasks
1-4 already implemented the full feature, unit-tested at each layer. This
step is the final proof that those layers compose correctly through the
real `mockymock run` CLI end to end.

Run: `pytest tests/integration/test_terminator_support.py -v -k "if_nested or evaluate_nested or inline_loop_nested"`
Expected: all three PASS immediately. If any fails, do not proceed —
return to Tasks 1-4 and fix the regression before adding more tests; do
not patch around it here.

- [ ] **Step 3: Run the full file**

Run: `pytest tests/integration/test_terminator_support.py -v`
Expected: entire file PASSES, including every pre-existing test.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_terminator_support.py
git commit -m "test(integration): end-to-end regression fixtures for nested chain-PERFORM shapes"
```

---

### Task 6: Docs sync

**Files:**
- Modify: `docs/2026-07-08-goback-stop-run-support-design.md`
- Modify: `docs/2026-07-06-real-world-readiness-audit.md`
- Modify: `README.md`
- Modify: `.okf/analysis.md`, `.okf/splicer.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Update the original design doc's Out-of-scope bullet**

In `docs/2026-07-08-goback-stop-run-support-design.md`, find the "Out of
scope" bullet "Intermediate `PERFORM` statements nested inside a
conditional body..." (~line 234-235) and append:

```markdown
  **Resolved 2026-07-10** — see
  `docs/2026-07-10-conditionally-nested-intermediate-perform-design.md`.
```

- [ ] **Step 2: Update the readiness audit**

In `docs/2026-07-06-real-world-readiness-audit.md`, find Finding 3's
"conditionally-nested intermediate `PERFORM`s" sub-bullet and mark it
resolved with a pointer to the new design doc, matching how the
looping-PERFORM and `GO TO`-reachable sub-bullets (if already marked) are
annotated — read the surrounding text first to match the exact phrasing
convention already used there before editing.

- [ ] **Step 3: Update README known-limitations**

Read `README.md`'s known-limitations section first. If it lists
"conditionally-nested intermediate PERFORM" (or the general "deferred
terminator shapes" bullet naming it) as unsupported, remove that clause or
narrow it to the shapes still refused (a PERFORM inside another boundary
statement's clause body, `GO TO`-reachable chains, `SECTION`-scoped
chains).

- [ ] **Step 4: Update `.okf/analysis.md` and `.okf/splicer.md`**

Read both files' existing terminator/chain-detection concept rows first
(they currently describe `_plain_perform_edges_from` as top-level-only and
`statement_top_level_problem` as the sole validator). Update the prose to
describe the extended nested-body walk, `_plain_perform_statements`,
`nested_chain_perform_problem`, and `ChainPerform`, refresh each file's
`timestamp` field, and append a dated entry to `.okf/log.md` per this
repo's OKF convention (see the workspace `CLAUDE.md`'s OKF instructions).

- [ ] **Step 5: Commit**

```bash
git add docs/2026-07-08-goback-stop-run-support-design.md docs/2026-07-06-real-world-readiness-audit.md README.md .okf/analysis.md .okf/splicer.md .okf/log.md
git commit -m "docs: sync conditionally-nested intermediate PERFORM support"
```
