# SECTION-Scoped Terminator Support (Narrow Shape) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let mockymock neutralize a `STOP RUN`/`GOBACK` that sits in the first paragraph of a `SECTION`, when that paragraph is provably entered ONLY via `PERFORM <section-name>` — replacing it with `EXIT SECTION` instead of the existing `EXIT PARAGRAPH` mechanism.

**Architecture:** A new whole-program static check, `refusal._safe_section_entry_points`, identifies which `SECTION`s' first paragraphs are exclusively entered via their section's name (never `GO TO`'d, never directly `PERFORM`'d by their own paragraph name anywhere in the program). This feeds a small extension of the existing safe-chain BFS (`_plain_perform_edges_from`) so it can resolve a `PERFORM <section-name>` edge into that first paragraph instead of dead-ending, and a new `TerminatorPlan.exit_kind` field ("PARAGRAPH" or "SECTION") tells the splicer which `EXIT` verb to emit. No new runtime mechanism: spike #5 of `docs/2026-07-08-goback-stop-run-support-design.md` already proved `EXIT SECTION` works for this exact shape — this plan only adds the static analysis needed to safely recognize it and route the existing splice primitive.

**Tech Stack:** Python 3.14, `cobolparser` (editable/vendored dependency), `pytest`, GnuCOBOL 3.2 via the `mockymock-cobc` Docker container for integration tests.

## Global Constraints

- Full design: `docs/2026-07-10-section-scoped-terminator-support-design.md` — read it before starting Task 1.
- This iteration implements **shape 1 only** (section's first paragraph, entered exclusively via `PERFORM <section-name>`). Fall-through-reached paragraphs and direct-paragraph-name entry into a section member stay refused — do not attempt to support them.
- Every new/changed check must fail closed: if in doubt, refuse `UNSUPPORTED_TERMINATOR_LAYOUT` rather than guess.
- Follow existing code style exactly — this codebase has no type-annotation ceremony beyond what's already there (see `_plain_perform_edges_from`'s current unannotated locals); match it, don't add more.
- Integration tests are `@requires_docker`-gated (`tests/integration/_docker.py`) and will skip, not fail, without a reachable Docker daemon — that's expected and fine.
- Run `python -m pytest tests/unit -q` after every task to confirm no regressions, in addition to the task's own targeted run.

---

### Task 1: Whole-program safe-section-entry detection

**Files:**
- Modify: `mockymock/analysis/refusal.py` (new function, insert immediately after `_go_to_targets`, which ends at line 925, and before `_plain_perform_edges_from`, which starts at line 928)
- Test: `tests/unit/test_terminator_reachability.py`

**Interfaces:**
- Consumes: `program.get_division("PROCEDURE")`, `procedure._sections` (dict `str -> CobolSection`, each with `.paragraphs: list[CobolParagraph]`), `_go_to_targets(program)` (existing), `_all_paragraphs(procedure)` (existing import from `mock_surface`), `_find_statements_of_type(statements, PerformStatement)` (existing, recursive).
- Produces: `_safe_section_entry_points(program) -> dict[str, str]`, mapping `section_name -> first_paragraph_name` for every section whose first paragraph is safely enterable only via `PERFORM <section-name>`. Task 2 consumes this return type directly.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_terminator_reachability.py`, after the existing imports (line 10) and before `CHAIN_SOURCE`:

```python
from mockymock.analysis.refusal import (
    _go_to_targets,
    _plain_perform_edges_from,
    _safe_section_entry_points,
)
```

(This replaces the existing single-line import at line 10 — `_safe_section_entry_points` is added to the same `from` clause.)

Add these fixtures after `CHAIN_SOURCE` (line 39) and before `_program()` (line 42):

```python
SAFE_SECTION_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INIT-SECTION.

       1000-INIT-SECTION SECTION.
       1000-INIT-FIRST.
           DISPLAY "FIRST".
       1000-INIT-SECOND.
           DISPLAY "SECOND".
"""

SECTION_GO_TO_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTGOTOUNSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INIT-SECTION.

       9000-ALIAS.
           GO TO 1000-INIT-FIRST.

       1000-INIT-SECTION SECTION.
       1000-INIT-FIRST.
           DISPLAY "FIRST".
"""

SECTION_DIRECT_PERFORM_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTDIRECTUNSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INIT-SECTION.

       9000-ALSO-CALLS-DIRECTLY.
           PERFORM 1000-INIT-FIRST.

       1000-INIT-SECTION SECTION.
       1000-INIT-FIRST.
           DISPLAY "FIRST".
"""
```

Add these tests at the end of the file (after `test_plain_perform_edges_from_ignores_looping_perform`):

```python
def test_safe_section_entry_points_finds_a_safely_entered_section():
    program = parse_cobol(SAFE_SECTION_SOURCE, filename="sectsafe.cbl").ast
    assert _safe_section_entry_points(program) == {
        "1000-INIT-SECTION": "1000-INIT-FIRST"
    }


def test_safe_section_entry_points_excludes_a_go_to_reachable_first_paragraph():
    program = parse_cobol(SECTION_GO_TO_UNSAFE_SOURCE, filename="sectgoto.cbl").ast
    assert _safe_section_entry_points(program) == {}


def test_safe_section_entry_points_excludes_a_directly_performed_first_paragraph():
    program = parse_cobol(
        SECTION_DIRECT_PERFORM_UNSAFE_SOURCE, filename="sectdirect.cbl"
    ).ast
    assert _safe_section_entry_points(program) == {}


def test_safe_section_entry_points_empty_when_program_has_no_sections():
    assert _safe_section_entry_points(_program()) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_terminator_reachability.py -v -k safe_section_entry`
Expected: FAIL — `ImportError: cannot import name '_safe_section_entry_points'`

- [ ] **Step 3: Implement `_safe_section_entry_points`**

In `mockymock/analysis/refusal.py`, insert this new function between `_go_to_targets` (ends line 925) and `_plain_perform_edges_from` (starts line 928):

```python
def _safe_section_entry_points(program) -> dict[str, str]:
    """Maps each SECTION name whose first paragraph is safely enterable
    ONLY via `PERFORM <section-name>` to that first paragraph's name --
    the one shape docs/2026-07-08-goback-stop-run-support-design.md's
    spike #5 proved `EXIT SECTION` correctly neutralizes (see
    docs/2026-07-10-section-scoped-terminator-support-design.md).

    Safe means: the section has at least one paragraph; neither the
    section's own name nor its first paragraph's name is ever a GO TO
    target anywhere in the program (`_go_to_targets`); and the first
    paragraph's name is never itself named as a PERFORM target -- plain
    or THRU, conditional or not, top-level or nested -- anywhere in the
    whole program. That last check is deliberately maximally inclusive:
    any second way to enter that paragraph is a standing risk regardless
    of whether any one test's execution happens to take it, the same
    reasoning already applied to the GO TO exclusion above.

    A section failing any of these is simply absent from the returned
    map -- callers must treat that identically to any other unresolvable
    PERFORM target (the existing dead-end/refusal behavior)."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return {}

    go_to_targets = _go_to_targets(program)
    performed_names: set[str] = set()
    for paragraph in _all_paragraphs(procedure):
        for statement in _find_statements_of_type(
            paragraph.statements, PerformStatement
        ):
            if statement.target_paragraph:
                performed_names.add(statement.target_paragraph)
            if statement.thru_paragraph:
                performed_names.add(statement.thru_paragraph)

    safe_entries: dict[str, str] = {}
    for section_name, section in procedure._sections.items():
        if not section.paragraphs:
            continue
        first_name = section.paragraphs[0].paragraph_name
        if section_name in go_to_targets or first_name in go_to_targets:
            continue
        if first_name in performed_names:
            continue
        safe_entries[section_name] = first_name
    return safe_entries
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_terminator_reachability.py -v`
Expected: PASS (all tests, including the 4 pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add mockymock/analysis/refusal.py tests/unit/test_terminator_reachability.py
git commit -m "feat(analysis): add whole-program safe-section-entry detection"
```

---

### Task 2: Resolve safe section entries in the safe-chain BFS

**Files:**
- Modify: `mockymock/analysis/refusal.py:928-987` (`_plain_perform_edges_from`)
- Test: `tests/unit/test_terminator_reachability.py`

**Interfaces:**
- Consumes: `_safe_section_entry_points` (Task 1) return type `dict[str, str]`.
- Produces: `_plain_perform_edges_from(program, start, safe_section_entries=None) -> tuple[set[str], list]` — same shape as before, but `seen` now contains a SECTION's first-paragraph name (not the section's own name) whenever the BFS crosses a safe section entry, and the BFS continues from that paragraph's own statements. Task 3 passes `_safe_section_entry_points(program)`'s result into this new third parameter.

- [ ] **Step 1: Write the failing tests**

Add these fixtures to `tests/unit/test_terminator_reachability.py`, after `SECTION_DIRECT_PERFORM_UNSAFE_SOURCE`:

```python
SECTION_CONTINUES_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTCONTINUES.

       PROCEDURE DIVISION.
       TARGET-PARA.
           PERFORM SAFE-SECTION.

       LEVEL2-PARA.
           DISPLAY "REACHED FROM SECTION".

       SAFE-SECTION SECTION.
       SAFE-FIRST.
           PERFORM LEVEL2-PARA.
"""
```

Add these tests after `test_safe_section_entry_points_empty_when_program_has_no_sections`:

```python
def test_plain_perform_edges_from_resolves_safe_section_entry_to_first_paragraph():
    program = parse_cobol(SAFE_SECTION_SOURCE, filename="sectsafe2.cbl").ast
    safe_entries = _safe_section_entry_points(program)
    seen, edges = _plain_perform_edges_from(program, "0000-MAIN-PROCESS", safe_entries)
    assert seen == {"0000-MAIN-PROCESS", "1000-INIT-FIRST"}
    assert len(edges) == 1
    assert edges[0].target_paragraph == "1000-INIT-SECTION"


def test_plain_perform_edges_from_continues_bfs_from_section_first_paragraph():
    program = parse_cobol(SECTION_CONTINUES_SOURCE, filename="sectcontinues.cbl").ast
    safe_entries = _safe_section_entry_points(program)
    seen, edges = _plain_perform_edges_from(program, "TARGET-PARA", safe_entries)
    assert seen == {"TARGET-PARA", "SAFE-FIRST", "LEVEL2-PARA"}
    assert {e.target_paragraph for e in edges} == {"SAFE-SECTION", "LEVEL2-PARA"}


def test_plain_perform_edges_from_still_dead_ends_on_section_without_safe_entries():
    """Regression guard: callers that don't pass safe_section_entries (the
    default, e.g. every pre-existing call site) get exactly today's
    behavior -- a SECTION name is an unresolved dead end, its raw name
    landing in `seen` but never traversed further."""
    program = parse_cobol(SAFE_SECTION_SOURCE, filename="sectsafe3.cbl").ast
    seen, edges = _plain_perform_edges_from(program, "0000-MAIN-PROCESS")
    assert seen == {"0000-MAIN-PROCESS", "1000-INIT-SECTION"}
    assert len(edges) == 1
    assert edges[0].target_paragraph == "1000-INIT-SECTION"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_terminator_reachability.py -v -k "resolves_safe_section or continues_bfs_from_section or still_dead_ends"`
Expected: FAIL — the first two assert `seen`/`edges` shapes the current dead-end-only implementation cannot produce (e.g. `1000-INIT-FIRST` missing from `seen`); the third currently passes already (it's a pre-registration of existing behavior) but is listed here for the "run again after Step 3" comparison.

- [ ] **Step 3: Rewrite `_plain_perform_edges_from`**

Replace the whole function body (`mockymock/analysis/refusal.py:928-987`) with:

```python
def _plain_perform_edges_from(
    program, start: str, safe_section_entries: dict[str, str] | None = None
) -> tuple[set[str], list]:
    """BFS from `start` following ONLY plain (non-THRU), unconditional,
    single-shot, top-level PERFORM statements -- i.e. PerformStatement
    nodes that are direct members of a paragraph's own `.statements` list
    (not nested inside IF/EVALUATE), with `thru_paragraph is None` and
    `perform_type == "SIMPLE"`.

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
    refusal branch needed.

    `safe_section_entries` (from `_safe_section_entry_points`, or omitted
    for callers that don't care about SECTIONs -- e.g. this module's own
    dead-end regression test) resolves a PERFORM target that names one of
    its KEYS (a SECTION whose first paragraph is provably safely
    enterable only that way) to that first paragraph's name, continuing
    the BFS from that paragraph's own statements exactly like any other
    paragraph -- see
    docs/2026-07-10-section-scoped-terminator-support-design.md. This is
    the ONLY SECTION shape this restricted BFS ever resolves: a target
    name that is a SECTION but not a safe entry (or any other
    unresolvable name) still dead-ends exactly as before, its raw,
    unresolved name landing in `seen`.

    SECTION members that aren't a safe entry's first paragraph are still
    excluded entirely, same as before: this only looks up names in
    `procedure.paragraphs` (top-level paragraphs) and, when
    `safe_section_entries` resolves one, the specific first-paragraph
    names it names -- never any other section member -- so a chain that
    would need to pass through one of those (fall-through, or a direct
    PERFORM of a non-first section member) still naturally refuses via
    the existing "reachable but not via a plain chain" check."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set(), []
    safe_section_entries = safe_section_entries or {}
    by_name = {p.paragraph_name: p for p in procedure.paragraphs}
    section_member_by_name = {
        paragraph.paragraph_name: paragraph
        for section in procedure._sections.values()
        for paragraph in section.paragraphs
    }

    def resolve(name):
        if name in by_name:
            return name, by_name[name]
        first_name = safe_section_entries.get(name)
        if first_name is not None:
            return first_name, section_member_by_name.get(first_name)
        return name, None

    start_name, start_paragraph = resolve(start)
    seen = {start_name}
    resolved = {}
    stack = []
    if start_paragraph is not None:
        resolved[start_name] = start_paragraph
        stack.append(start_name)
    edges: list = []
    while stack:
        name = stack.pop()
        paragraph = resolved.get(name)
        if paragraph is None:
            continue
        for statement in paragraph.statements:
            if (
                isinstance(statement, PerformStatement)
                and statement.thru_paragraph is None
                and statement.target_paragraph
                and statement.perform_type == "SIMPLE"
            ):
                edges.append(statement)
                target_name, target_paragraph = resolve(statement.target_paragraph)
                if target_name not in seen:
                    seen.add(target_name)
                    if target_paragraph is not None:
                        resolved[target_name] = target_paragraph
                        stack.append(target_name)
    return seen, edges
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_terminator_reachability.py -v`
Expected: PASS (all tests, including the 4 original ones from before Task 1)

- [ ] **Step 5: Commit**

```bash
git add mockymock/analysis/refusal.py tests/unit/test_terminator_reachability.py
git commit -m "feat(analysis): resolve safe section entries in the safe-chain BFS"
```

---

### Task 3: Wire into `find_terminator_plans` and `TerminatorPlan`

**Files:**
- Modify: `mockymock/analysis/refusal.py` (`TerminatorPlan` dataclass, `find_terminator_plans`)
- Test: `tests/unit/test_terminators.py`

**Interfaces:**
- Consumes: `_safe_section_entry_points` (Task 1), the updated `_plain_perform_edges_from` (Task 2).
- Produces: `TerminatorPlan.exit_kind: str` (`"PARAGRAPH"` or `"SECTION"`). Task 4 (`injector.build_terminator_neutralization`, `orchestrator.py`) consumes this field.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_terminators.py`, replace `test_section_scoped_terminator_refuses` (lines 278-287) with:

```python
def test_section_touched_only_via_safe_entry_no_longer_refuses():
    """SECTION_UNSAFE_SOURCE's terminator sits directly in
    0000-MAIN-PROCESS, a top-level paragraph -- the chain merely PERFORMs
    1000-SECTION on the way, and 1000-SECTION's only paragraph
    (1000-DO-WORK) is never GO TO'd or directly PERFORMed anywhere else,
    so it's a safe section entry
    (docs/2026-07-10-section-scoped-terminator-support-design.md). This
    used to refuse under the old blanket "any SECTION anywhere in the
    chain is unsafe" check; now it's correctly recognized as safe. The
    terminator's own paragraph is still top-level, so exit_kind stays
    PARAGRAPH -- this test is about the chain-level check, not the
    terminator's own paragraph classification (see
    test_terminator_in_safe_section_first_paragraph_is_accepted for
    that)."""
    program, surface, scope_map, lines = _analyze(SECTION_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert plans[0].exit_kind == "PARAGRAPH"
```

Add this fixture after `SECTION_OWN_PARAGRAPH_UNSAFE_SOURCE` (line 117):

```python
CHAIN_SECTION_STILL_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CHAINSECTUNSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-SECTION
           STOP RUN.

       9000-ALSO-CALLS-DIRECTLY.
           PERFORM 1000-DO-WORK.

       1000-SECTION SECTION.
       1000-DO-WORK.
           DISPLAY "WORK".
"""

SECTION_FIRST_PARAGRAPH_SAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTFIRSTSAFE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-TERM-SECTION
           DISPLAY "AFTER-SECTION".

       1000-TERM-SECTION SECTION.
       1000-TERM-FIRST.
           MOVE 1 TO WS-RESULT
           STOP RUN.
       1000-TERM-SECOND.
           MOVE 999 TO WS-RESULT.
"""

SECTION_LATER_PARAGRAPH_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTLATERUNSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-TERM-SECTION.

       1000-TERM-SECTION SECTION.
       1000-TERM-FIRST.
           DISPLAY "FIRST".
       1000-TERM-SECOND.
           STOP RUN.
"""
```

Add these tests immediately after the (now rewritten) `test_section_touched_only_via_safe_entry_no_longer_refuses`:

```python
def test_chain_touching_a_genuinely_unsafe_section_still_refuses():
    """Unlike SECTION_UNSAFE_SOURCE, 1000-DO-WORK here is ALSO directly
    PERFORMed by 9000-ALSO-CALLS-DIRECTLY -- a second entry path -- so
    1000-SECTION is NOT a safe entry, and the terminator (still in the
    top-level 0000-MAIN-PROCESS) must still refuse via
    chain_section_names."""
    program, surface, scope_map, lines = _analyze(CHAIN_SECTION_STILL_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "SECTION" in reasons[0].message


def test_terminator_in_safe_section_first_paragraph_is_accepted():
    """The core shape-1 feature: STOP RUN sits in 1000-TERM-FIRST, the
    first paragraph of 1000-TERM-SECTION, entered only via PERFORM
    1000-TERM-SECTION. Whether 1000-TERM-SECOND actually fails to run at
    real GnuCOBOL runtime is the integration test's job
    (tests/integration/test_terminator_support.py) -- here we confirm the
    plan itself: SECTION exit kind, and the section-name PERFORM captured
    as a chain_performs edge (0000-MAIN-PROCESS has a DISPLAY after it,
    so it needs the standard post-PERFORM flag check)."""
    program, surface, scope_map, lines = _analyze(SECTION_FIRST_PARAGRAPH_SAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert plans[0].site.paragraph_name == "1000-TERM-FIRST"
    assert plans[0].exit_kind == "SECTION"
    assert {p.target_paragraph for p in plans[0].chain_performs} == {
        "1000-TERM-SECTION"
    }


def test_terminator_in_safe_section_reached_directly_by_test_target():
    """When the test's own PERFORM_TARGET names the section directly,
    there's no intermediate chain at all -- mirrors how a top-level
    terminator directly in perform_target needs no chain_performs
    (test_find_terminator_plans_accepts_a_safe_plain_perform_chain)."""
    program, surface, scope_map, lines = _analyze(SECTION_FIRST_PARAGRAPH_SAFE_SOURCE)
    suite = _suite(perform_target="1000-TERM-SECTION")
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert plans[0].exit_kind == "SECTION"
    assert plans[0].chain_performs == []


def test_terminator_in_a_later_section_paragraph_still_refuses():
    """Even though 1000-TERM-SECTION is a safe entry (its first paragraph
    is never GO TO'd or directly PERFORMed elsewhere), the terminator
    here sits in 1000-TERM-SECOND -- reached only by fall-through after
    1000-TERM-FIRST, never PERFORMed by name anywhere this codebase's BFS
    would follow. Shape 2 from
    docs/2026-07-10-section-scoped-terminator-support-design.md,
    deliberately still out of scope: pins the boundary as documented
    intent, not an accident of the safe_section_first_names check."""
    program, surface, scope_map, lines = _analyze(SECTION_LATER_PARAGRAPH_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "SECTION" in reasons[0].message
```

Update `test_check_terminator_layout_is_reasons_only` (lines 329-336) to use the still-genuinely-unsafe fixture instead of the now-safe one:

```python
def test_check_terminator_layout_is_reasons_only():
    program, surface, scope_map, lines = _analyze(SAFE_CHAIN_SOURCE)
    assert check_terminator_layout(surface, program, _suite(), scope_map, lines) == []

    program, surface, scope_map, lines = _analyze(CHAIN_SECTION_STILL_UNSAFE_SOURCE)
    reasons = check_terminator_layout(surface, program, _suite(), scope_map, lines)
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_terminators.py -v`
Expected: FAIL — `AttributeError: 'TerminatorPlan' object has no attribute 'exit_kind'` on the new/rewritten tests; `test_section_touched_only_via_safe_entry_no_longer_refuses` and `test_terminator_in_safe_section_first_paragraph_is_accepted` also fail on `assert reasons == []` / `assert len(plans) == 1` since the old code still refuses every SECTION shape.

- [ ] **Step 3: Add `exit_kind` to `TerminatorPlan` and wire the checks**

In `mockymock/analysis/refusal.py`, replace the `TerminatorPlan` dataclass (lines 173-186):

```python
@dataclass
class TerminatorPlan:
    """One physical STOP RUN(RUN-form)/GOBACK statement found safe to
    neutralize, plus every intermediate PERFORM statement (deduped across
    the whole suite by identity) that needs the early-exit flag-check
    inserted after it for this terminator's propagation to correctly
    reach the test driver. Empty `chain_performs` means the terminator
    sits directly in a test's own PERFORM target -- no intermediate
    instrumentation needed. `exit_kind` is "PARAGRAPH" (the default) or
    "SECTION" for the one SECTION-scoped shape
    docs/2026-07-10-section-scoped-terminator-support-design.md supports
    -- a terminator in a SECTION's first paragraph, entered exclusively
    via PERFORM <section-name>. See
    docs/2026-07-08-goback-stop-run-support-design.md and
    docs/2026-07-10-section-scoped-terminator-support-design.md."""

    site: BoundarySite
    chain_performs: list = field(default_factory=list)
    exit_kind: str = "PARAGRAPH"
```

Then, in `find_terminator_plans`, make three edits:

1. After line 1048 (`go_to_targets = _go_to_targets(program)`), add:

```python
    safe_section_entries = _safe_section_entry_points(program)
    safe_section_first_names = set(safe_section_entries.values())
```

2. Replace lines 1063-1066:

```python
        safe_names, chain_performs = _plain_perform_edges_from(
            program, case.perform_target
        )
        chain_section_names = safe_names - top_level_names
```

with:

```python
        safe_names, chain_performs = _plain_perform_edges_from(
            program, case.perform_target, safe_section_entries
        )
        chain_section_names = safe_names - (top_level_names | safe_section_first_names)
```

3. Replace lines 1088-1094:

```python
            paragraph_name = site.paragraph_name
            problem = None
            if paragraph_name not in top_level_names:
                problem = (
                    "is inside a paragraph that belongs to a SECTION -- "
                    "SECTION-scoped terminators are not yet supported"
                )
```

with:

```python
            paragraph_name = site.paragraph_name
            problem = None
            if (
                paragraph_name not in top_level_names
                and paragraph_name not in safe_section_first_names
            ):
                problem = (
                    "is inside a paragraph that belongs to a SECTION -- "
                    "SECTION-scoped terminators are not yet supported"
                )
```

4. Replace lines 1158-1159:

```python
            if key not in plans_by_statement:
                plans_by_statement[key] = TerminatorPlan(site=terminator_sites[key])
```

with:

```python
            if key not in plans_by_statement:
                exit_kind = (
                    "SECTION"
                    if paragraph_name in safe_section_first_names
                    else "PARAGRAPH"
                )
                plans_by_statement[key] = TerminatorPlan(
                    site=terminator_sites[key], exit_kind=exit_kind
                )
```

Finally, update the module-level docstring on `find_terminator_plans` (the "Safe means:" sentence, part of the large docstring spanning lines 997-1042) — replace:

```
    Safe means: the terminator's enclosing paragraph is a top-level
    paragraph (not a SECTION member), is reachable from the test's own
```

with:

```
    Safe means: the terminator's enclosing paragraph is a top-level
    paragraph (not a SECTION member) -- or is the first paragraph of a
    SECTION whose only entry point, whole-program, is `PERFORM
    <section-name>` (`_safe_section_entry_points`; see
    docs/2026-07-10-section-scoped-terminator-support-design.md) -- is
    reachable from the test's own
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_terminators.py -v`
Expected: PASS (all tests, including `test_section_own_paragraph_terminator_refuses`, unchanged and still refusing shape 3)

- [ ] **Step 5: Run the full unit suite**

Run: `python -m pytest tests/unit -q`
Expected: PASS, no regressions elsewhere

- [ ] **Step 6: Commit**

```bash
git add mockymock/analysis/refusal.py tests/unit/test_terminators.py
git commit -m "feat(analysis): recognize safe SECTION-scoped terminators in find_terminator_plans"
```

---

### Task 4: Splice `EXIT SECTION` for section-scoped plans

**Files:**
- Modify: `mockymock/splicer/injector.py:74-85` (`build_terminator_neutralization`)
- Modify: `mockymock/splicer/orchestrator.py:133`
- Test: `tests/unit/test_injector.py`, `tests/unit/test_orchestrator.py`

**Interfaces:**
- Consumes: `TerminatorPlan.exit_kind` (Task 3).
- Produces: `build_terminator_neutralization(exit_kind: str = "PARAGRAPH") -> list[str]` — same 2-line shape as before, with `EXIT {exit_kind}` on the second line.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_injector.py`, immediately after `test_terminator_neutralization_sets_flag_and_exits_paragraph` (line 144):

```python
def test_terminator_neutralization_with_section_exit_kind_exits_section():
    lines = build_terminator_neutralization("SECTION")
    assert lines == [
        '           MOVE "Y" TO UT-EARLY-EXIT',
        "           EXIT SECTION",
    ]
```

Add to `tests/unit/test_orchestrator.py`, at the end of the file (after `test_perform_immediately_followed_by_terminator_interleaves_correctly`):

```python
SECTION_TERMINATOR_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTTERM.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-TERM-SECTION
           DISPLAY "AFTER-SECTION".

       1000-TERM-SECTION SECTION.
       1000-TERM-FIRST.
           MOVE 1 TO WS-RESULT
           STOP RUN.
       1000-TERM-SECOND.
           MOVE 999 TO WS-RESULT.
"""


def test_section_scoped_terminator_is_replaced_with_exit_section():
    result = parse_cobol(SECTION_TERMINATOR_SOURCE, filename="sectterm.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(SECTION_TERMINATOR_SOURCE.splitlines()).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    boundaries = collect_boundaries(result.ast)
    suite = MockTestSuite(
        name="T",
        test_cases=[MockTestCase(name="main", perform_target="0000-MAIN-PROCESS")],
    )
    plans, reasons = find_terminator_plans(surface, result.ast, suite, scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert plans[0].exit_kind == "SECTION"

    spliced = splice_program(
        lines, boundaries, surface, suite, TallyRegistry(suite), plans
    )
    joined = "\n".join(spliced)
    assert "      *>     STOP RUN." in joined
    assert 'MOVE "Y" TO UT-EARLY-EXIT' in joined
    assert "EXIT SECTION" in joined
    # the intermediate PERFORM's own post-check is still EXIT PARAGRAPH --
    # only the terminator's own replacement uses EXIT SECTION
    assert 'IF UT-EARLY-EXIT = "Y"' in joined
    assert "EXIT PARAGRAPH" in joined
```

(No new imports needed in `test_orchestrator.py` — `parse_cobol`, `normalize_fixed_format`, `analyze`, `collect_scope_map`, `annotate_nested_sites`, `collect_boundaries`, `MockTestCase`, `MockTestSuite`, `find_terminator_plans`, `splice_program`, `TallyRegistry` are all already imported earlier in the file.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_injector.py tests/unit/test_orchestrator.py -v -k "section_exit_kind or section_scoped_terminator_is_replaced"`
Expected: FAIL — `build_terminator_neutralization()` takes no arguments yet, and the orchestrator test's `assert "EXIT SECTION" in joined` fails since the splicer always emits `EXIT PARAGRAPH` today.

- [ ] **Step 3: Implement the change**

In `mockymock/splicer/injector.py`, replace `build_terminator_neutralization` (lines 74-85):

```python
def build_terminator_neutralization(exit_kind: str = "PARAGRAPH") -> list[str]:
    """Replacement for a STOP RUN/GOBACK statement found safe to
    neutralize (see docs/2026-07-08-goback-stop-run-support-design.md):
    set the early-exit flag and return via EXIT PARAGRAPH/EXIT SECTION --
    never GO TO, since these are the only mechanisms verified to
    correctly resume the real PERFORM caller. `exit_kind` is
    `TerminatorPlan.exit_kind` -- "PARAGRAPH" (the default) for the
    ordinary case, or "SECTION" for the one SECTION-scoped shape
    docs/2026-07-10-section-scoped-terminator-support-design.md
    supports. Identical regardless of which test case is running --
    unlike build_site_dispatch, no per-case EVALUATE UT-CURRENT-CASE
    dispatch is needed here."""
    return [
        '           MOVE "Y" TO UT-EARLY-EXIT',
        f"           EXIT {exit_kind}",
    ]
```

In `mockymock/splicer/orchestrator.py`, replace line 133:

```python
        replacement = build_terminator_neutralization()
```

with:

```python
        replacement = build_terminator_neutralization(plan.exit_kind)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_injector.py tests/unit/test_orchestrator.py -v`
Expected: PASS (all tests, including every pre-existing terminator/orchestrator test using the default `"PARAGRAPH"` behavior)

- [ ] **Step 5: Run the full unit suite**

Run: `python -m pytest tests/unit -q`
Expected: PASS, no regressions elsewhere

- [ ] **Step 6: Commit**

```bash
git add mockymock/splicer/injector.py mockymock/splicer/orchestrator.py tests/unit/test_injector.py tests/unit/test_orchestrator.py
git commit -m "feat(splicer): emit EXIT SECTION for section-scoped terminator plans"
```

---

### Task 5: Permanent Docker regression fixture (spike #5, finally committed)

**Files:**
- Modify: `tests/integration/test_terminator_support.py`

**Interfaces:**
- Consumes: `mockymock.cli.main.main` (existing CLI entry point), `tests.integration._docker.requires_docker` (existing).
- Produces: nothing new consumed elsewhere — this is the end-to-end proof.

- [ ] **Step 1: Write the new integration test**

Append to `tests/integration/test_terminator_support.py`:

```python
SECTION_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTTERM.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-TERM-SECTION
           DISPLAY "__MOCKYMOCK__ SHOULD-NOT-DISPLAY: AFTER-SECTION".

       1000-TERM-SECTION SECTION.
       1000-TERM-FIRST.
           MOVE 1 TO WS-RESULT
           STOP RUN.
       1000-TERM-SECOND.
           DISPLAY "__MOCKYMOCK__ SHOULD-NOT-RUN: SECOND-PARAGRAPH".
"""

SECTION_CUT = """\
TESTSUITE "SECTTERM smoke"

TESTCASE "terminator in section's first paragraph is neutralized"
    PERFORM 0000-MAIN-PROCESS
    EXPECT WS-RESULT TO BE 1

TESTCASE "second case still runs after the first hits the section terminator"
    PERFORM 0000-MAIN-PROCESS
    EXPECT WS-RESULT TO BE 1
"""


@requires_docker
def test_section_scoped_terminator_neutralized_and_second_paragraph_does_not_run(
    tmp_path: Path, capsys
):
    """Permanent regression fixture for spike #5 of
    docs/2026-07-08-goback-stop-run-support-design.md, finally committed
    now that docs/2026-07-10-section-scoped-terminator-support-design.md
    implements it: STOP RUN in a SECTION's first paragraph, entered only
    via PERFORM <section-name>, is replaced with EXIT SECTION. Proves two
    things a unit test cannot: 1000-TERM-SECOND's DISPLAY never runs
    (real GnuCOBOL EXIT SECTION semantics, not just the splice shape),
    and control correctly returns to the test driver (the case's own
    EXPECT runs, and a second test case in the suite still runs
    afterward)."""
    cbl_path = tmp_path / "SECTTERM.cbl"
    cbl_path.write_text(SECTION_CBL)
    cut_path = tmp_path / "SECTTERM.cut"
    cut_path.write_text(SECTION_CUT)

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "[PASS] terminator in section's first paragraph is neutralized" in out
    assert (
        "[PASS] second case still runs after the first hits the section terminator"
        in out
    )
    assert "SHOULD-NOT-RUN" not in out
    assert "SHOULD-NOT-DISPLAY" not in out
    assert "CRASH" not in out
    assert "FAIL" not in out
```

- [ ] **Step 2: Run the test to verify it fails without the feature (sanity check on a clean checkout)**

Skip this step if Tasks 1-4 are already committed in this working tree (the feature will already be present, so this test should pass immediately) — otherwise `git stash` first, run, then `git stash pop`. In the normal task-by-task flow, proceed directly to Step 3.

- [ ] **Step 3: Run the test**

Run: `python -m pytest tests/integration/test_terminator_support.py -v -k section_scoped_terminator_neutralized`
Expected: PASS if Docker is reachable; SKIPPED ("Docker daemon not reachable") otherwise.

**This step is the only point in the whole plan where the actual spliced
output gets compiled and run by real GnuCOBOL** — every earlier task only
asserts the splice *shape* (`"EXIT SECTION" in joined`), not that `cobc`
accepts it or that `EXIT SECTION` really returns to the right caller once
composed with the generated driver scaffolding and any chain-check
insertions. A SKIP here is not evidence the feature works — it means the
feature is unverified, same as if this test didn't exist yet. Do not
report this plan as complete, and do not claim the feature works end to
end, on the strength of Tasks 1-4's unit tests alone if this test skips.
If Docker is unavailable in the execution environment, say so explicitly
and flag Task 5 as unverified rather than done.

- [ ] **Step 4: Run the full integration file to confirm no regressions**

Run: `python -m pytest tests/integration/test_terminator_support.py -v`
Expected: all PASS or all SKIPPED, consistently (no mix of PASS and FAIL)

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_terminator_support.py
git commit -m "test(integration): commit spike #5 as a permanent SECTION-terminator regression fixture"
```

---

### Task 6: Docs sync

**Files:**
- Modify: `docs/2026-07-08-goback-stop-run-support-design.md`
- Modify: `.okf/analysis.md`
- Modify: `.okf/splicer.md`
- Modify: `docs/2026-07-06-real-world-readiness-audit.md`
- Modify: `.okf/log.md`

**Interfaces:** None — documentation only, no code consumes these.

- [ ] **Step 1: Update the original design doc's deferred-scope note**

In `docs/2026-07-08-goback-stop-run-support-design.md`, after the "Design consequence of #5 (deferred despite working)" paragraph (ends `"...reusing the same detection machinery once there's demand."`), append:

```markdown

**Update (2026-07-10):** the first half of this distinction — "the
section's own first paragraph, reached via `PERFORM <section-name>`" — is
now implemented; see
[docs/2026-07-10-section-scoped-terminator-support-design.md](2026-07-10-section-scoped-terminator-support-design.md).
"A later paragraph in that section, reached only by fall-through" and "a
section member entered by directly `PERFORM`ing its own paragraph name"
both remain future work.
```

- [ ] **Step 2: Update `.okf/analysis.md`**

Find this row in the per-test-case checks table (currently line 140):

```
| terminator site (`StopStatement`(RUN-form)/`GobackStatement`) found unsafe by `find_terminator_plans` | `UNSUPPORTED_TERMINATOR_LAYOUT` | evaluated by `check_terminator_layout`, run alongside `check_test_case` in the CLI's refusal loop, not as one of `check_test_case`'s own per-site conditions above -- see [splicer](splicer.md#terminator-neutralization-gobackstop-run-approach-b) |
```

Replace with:

```
| terminator site (`StopStatement`(RUN-form)/`GobackStatement`) found unsafe by `find_terminator_plans` | `UNSUPPORTED_TERMINATOR_LAYOUT` | evaluated by `check_terminator_layout`, run alongside `check_test_case` in the CLI's refusal loop, not as one of `check_test_case`'s own per-site conditions above -- see [splicer](splicer.md#terminator-neutralization-gobackstop-run-approach-b). One narrow SECTION-scoped shape is safe (a `SECTION`'s first paragraph, entered exclusively via `PERFORM <section-name>`) and produces a plan instead of a refusal — see `_safe_section_entry_points` and `docs/2026-07-10-section-scoped-terminator-support-design.md` |
```

- [ ] **Step 3: Update `.okf/splicer.md`**

Find this sentence (currently lines 410-411):

```
never a `GO TO` target anywhere in the program
(`refusal._go_to_targets`), never a `SECTION` member. Safe terminators
```

Replace with:

```
never a `GO TO` target anywhere in the program
(`refusal._go_to_targets`), never a `SECTION` member — except the one
narrow, whole-program-verified shape: a `SECTION`'s own first paragraph,
entered exclusively via `PERFORM <section-name>`
(`refusal._safe_section_entry_points`), replaced with `EXIT SECTION`
instead of `EXIT PARAGRAPH` (`TerminatorPlan.exit_kind`) — see
`docs/2026-07-10-section-scoped-terminator-support-design.md`. Safe
terminators
```

- [ ] **Step 4: Update `docs/2026-07-06-real-world-readiness-audit.md`**

Find this paragraph (currently lines 138-143):

```markdown
**Partially resolved 2026-07-08** — see
[docs/2026-07-08-goback-stop-run-support-design.md](2026-07-08-goback-stop-run-support-design.md).
A terminator reachable through a chain of plain, unconditional `PERFORM`
calls is now neutralized and the test case completes normally; `GO
TO`-reachable and `SECTION`-scoped terminators still refuse rather than
crash. The remainder of this finding is kept below for history.
```

Replace with:

```markdown
**Partially resolved 2026-07-08, extended 2026-07-10** — see
[docs/2026-07-08-goback-stop-run-support-design.md](2026-07-08-goback-stop-run-support-design.md)
and
[docs/2026-07-10-section-scoped-terminator-support-design.md](2026-07-10-section-scoped-terminator-support-design.md).
A terminator reachable through a chain of plain, unconditional `PERFORM`
calls is now neutralized and the test case completes normally, including
the one `SECTION`-scoped shape verified safe: a terminator in a
`SECTION`'s first paragraph, entered exclusively via `PERFORM
<section-name>`. `GO TO`-reachable terminators, and `SECTION`-scoped
terminators reached any other way (fall-through, or a direct
paragraph-name `PERFORM`), still refuse rather than crash. The remainder
of this finding is kept below for history.
```

- [ ] **Step 5: Add a dated `.okf/log.md` entry**

Insert at the very top of `.okf/log.md`, before the existing `## 2026-07-09 (Fix: ...)` entry (line 3):

```markdown
## 2026-07-10 (SECTION-scoped terminator support, narrow shape)
* **Added**: `refusal._safe_section_entry_points` (whole-program check: a
  `SECTION`'s first paragraph is safe to neutralize with `EXIT SECTION`
  only when neither it nor its `SECTION` is ever a `GO TO` target, and
  the paragraph is never itself a direct `PERFORM` target anywhere in
  the program) and wired it into `_plain_perform_edges_from` and
  `find_terminator_plans` (`TerminatorPlan.exit_kind`,
  `injector.build_terminator_neutralization(exit_kind)`). Closes the
  narrow half of spike #5's deferred scope from
  `docs/2026-07-08-goback-stop-run-support-design.md` — see
  `docs/2026-07-10-section-scoped-terminator-support-design.md`.
  Fall-through and direct-paragraph-`PERFORM` section shapes remain
  refused.
* **Side effect**: `test_section_scoped_terminator_refuses` (renamed
  `test_section_touched_only_via_safe_entry_no_longer_refuses`) now
  asserts a plan is produced instead of a refusal, since its `SECTION`'s
  only paragraph is a genuinely safe entry — the old blanket "any
  `SECTION` anywhere in the chain is unsafe" check was strictly more
  conservative than necessary for that shape. A new fixture
  (`CHAIN_SECTION_STILL_UNSAFE_SOURCE`) keeps the true-unsafe chain-level
  case covered.

```

- [ ] **Step 6: Commit**

```bash
git add docs/2026-07-08-goback-stop-run-support-design.md .okf/analysis.md .okf/splicer.md docs/2026-07-06-real-world-readiness-audit.md .okf/log.md
git commit -m "docs: sync SECTION-scoped terminator support (narrow shape)"
```

---

## Self-Review Notes

- **Spec coverage:** detection (Task 1) → BFS wiring (Task 2) → `find_terminator_plans`/`TerminatorPlan` integration incl. the documented existing-test consequence (Task 3) → splice mechanics (Task 4) → integration regression fixture (Task 5) → docs sync (Task 6). Every section of `docs/2026-07-10-section-scoped-terminator-support-design.md` maps to a task.
- **Placeholder scan:** none — every step has complete code, exact file paths/line numbers, and exact commands.
- **Type consistency:** `TerminatorPlan.exit_kind` (Task 3) flows unchanged into `plan.exit_kind` (Task 4's `orchestrator.py` edit) and `build_terminator_neutralization(exit_kind: str = "PARAGRAPH")` (Task 4). `_safe_section_entry_points(program) -> dict[str, str]` (Task 1) flows unchanged into `_plain_perform_edges_from(program, start, safe_section_entries)` (Task 2) and `find_terminator_plans` (Task 3). Verified no signature drift across tasks.
