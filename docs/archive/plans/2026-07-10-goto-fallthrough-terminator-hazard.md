# GO TO Fall-Through Terminator Hazard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the documented-but-unmodeled gap in `mockymock/analysis/refusal.py`: a `GO TO` target paragraph that falls through past its own end into the next paragraph in source order shares the same `EXIT PARAGRAPH` hazard as a direct `GO TO` target, but is currently invisible to `_go_to_targets`. Add `_falls_through` and `_go_to_fallthrough_targets`, wire them into `find_terminator_plans`'s two existing `GO TO` checks, and update docs.

**Design doc:** `docs/2026-07-10-goto-fallthrough-terminator-hazard-design.md` — read it before starting; this plan implements it task-by-task and does not re-derive its reasoning.

**Tech Stack:** Python 3.11+, pytest (`tests/unit`). No Docker/GnuCOBOL needed — this is a pure static-analysis change over the AST (see design doc's "Why no new spike is needed").

## Global Constraints

- `_go_to_targets(program)` itself is unchanged. The new hazard set is computed and unioned in separately at the two call sites in `find_terminator_plans`.
- Every new refusal uses the existing `UNSUPPORTED_TERMINATOR_LAYOUT` code — this is the same hazard class as the existing `GO TO` checks, not a new refusal category.
- Follow `tests/unit/test_terminators.py`'s existing conventions exactly: module-level `..._SOURCE` string fixtures, the `_analyze`/`_suite` helpers, one focused test per shape.

---

## Task 1: `_falls_through` helper, test-first

**Files:**
- Modify: `mockymock/analysis/refusal.py`
- Modify: `tests/unit/test_terminators.py`

**Interfaces:**
- Produces: `_falls_through(paragraph) -> bool`, consumed by Task 2.

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_terminators.py` (needs a new import: `from mockymock.analysis.refusal import _falls_through`, alongside the existing `check_terminator_layout, find_terminator_plans` import — plus `parse_cobol`/`normalize_fixed_format` are already imported). Since `_falls_through` takes a single paragraph, not a whole program, add a small local helper to fetch one paragraph by name from a source string:

```python
def _paragraph(source, name):
    program, _, _, _ = _analyze(source)
    procedure = program.get_division("PROCEDURE")
    for p in procedure.paragraphs:
        if p.paragraph_name == name:
            return p
    for section in getattr(procedure, "_sections", {}).values():
        for p in section.paragraphs:
            if p.paragraph_name == name:
                return p
    raise AssertionError(f"paragraph {name!r} not found")


def test_falls_through_true_for_empty_paragraph():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPTYPARA.

       PROCEDURE DIVISION.
       P1.
       P2.
           STOP RUN.
"""
    assert _falls_through(_paragraph(source, "P1")) is True


def test_falls_through_false_for_goback():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOBACKEND.

       PROCEDURE DIVISION.
       P1.
           DISPLAY "X"
           GOBACK.
"""
    assert _falls_through(_paragraph(source, "P1")) is False


def test_falls_through_false_for_stop_run():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STOPRUNEND.

       PROCEDURE DIVISION.
       P1.
           DISPLAY "X"
           STOP RUN.
"""
    assert _falls_through(_paragraph(source, "P1")) is False


def test_falls_through_true_for_stop_literal():
    """STOP "MSG" only pauses for operator input and resumes -- it does
    not terminate control flow, unlike STOP RUN."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STOPLITEND.

       PROCEDURE DIVISION.
       P1.
           DISPLAY "X"
           STOP "MSG".
       P2.
           DISPLAY "Y".
"""
    assert _falls_through(_paragraph(source, "P1")) is True


def test_falls_through_false_for_plain_go_to():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PLAINGOTOEND.

       PROCEDURE DIVISION.
       P1.
           GO TO P2.
       P2.
           STOP RUN.
"""
    assert _falls_through(_paragraph(source, "P1")) is False


def test_falls_through_true_for_computed_go_to():
    """GO TO ... DEPENDING ON falls through to the next statement when the
    subscript is out of range -- it is NOT a guaranteed unconditional
    transfer, unlike a plain single-target GO TO."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPUTEDGOTOEND.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N                PIC 9 VALUE 9.

       PROCEDURE DIVISION.
       P1.
           GO TO P2 P3 DEPENDING ON WS-N.
       P2.
           STOP RUN.
       P3.
           STOP RUN.
"""
    assert _falls_through(_paragraph(source, "P1")) is True


def test_falls_through_false_for_exit_paragraph():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXITPARAEND.

       PROCEDURE DIVISION.
       P1.
           DISPLAY "X"
           EXIT PARAGRAPH.
       P2.
           STOP RUN.
"""
    assert _falls_through(_paragraph(source, "P1")) is False


def test_falls_through_true_for_trailing_if():
    """Conservative: no attempt to prove every branch of a trailing IF
    terminates."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRAILINGIF.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG             PIC X VALUE "N".

       PROCEDURE DIVISION.
       P1.
           IF WS-FLAG = "Y"
               STOP RUN
           END-IF.
       P2.
           DISPLAY "Y".
"""
    assert _falls_through(_paragraph(source, "P1")) is True
```

Run: `python -m pytest tests/unit/test_terminators.py -k falls_through -v`
Expect: `ImportError` (no `_falls_through` yet) or collection failure.

- [ ] **Step 2: Implement `_falls_through`**

Add to `mockymock/analysis/refusal.py`, near `_go_to_targets`. Needs new imports from `cobolparser.models.statements.misc`: `ExitStatement`, `GobackStatement`, `StopStatement` (alongside the existing `AlterStatement` import from the same module).

```python
def _falls_through(paragraph) -> bool:
    """True unless `paragraph`'s last top-level statement provably diverts
    control away -- GOBACK, STOP RUN (not STOP <literal>, which only
    pauses for operator input and resumes), a single-target GO TO (a
    computed GO TO ... DEPENDING ON is NOT included: GnuCOBOL falls
    through to the next statement when the subscript is out of range, so
    it is not a guaranteed unconditional transfer), or EXIT PARAGRAPH/
    SECTION/PROGRAM (a bare EXIT./EXIT PERFORM does not qualify -- the
    former is a no-op placeholder, the latter exits an in-line loop body,
    not the paragraph). Everything else -- no statements at all, or
    ending in MOVE/DISPLAY/PERFORM/IF/EVALUATE/... -- is conservatively
    assumed to fall through, matching this module's fail-closed posture
    elsewhere: no attempt is made to prove that every branch of a
    trailing IF/EVALUATE terminates. See
    docs/2026-07-10-goto-fallthrough-terminator-hazard-design.md."""
    statements = paragraph.statements
    if not statements:
        return True
    last = statements[-1]
    if isinstance(last, GobackStatement):
        return False
    if isinstance(last, StopStatement) and last.stop_type == "RUN":
        return False
    if isinstance(last, GoStatement) and last.depending_on_variable is None:
        return False
    if isinstance(last, ExitStatement) and last.exit_type in (
        "PARAGRAPH",
        "SECTION",
        "PROGRAM",
    ):
        return False
    return True
```

- [ ] **Step 3: Run tests, confirm green**

Run: `python -m pytest tests/unit/test_terminators.py -k falls_through -v`
Expect: all pass.

---

## Task 2: `_go_to_fallthrough_targets`, test-first

**Only proceed once Task 1 is green.**

**Files:**
- Modify: `mockymock/analysis/refusal.py`
- Modify: `tests/unit/test_terminators.py`

**Interfaces:**
- Consumes: `_falls_through` (Task 1), `_source_ordered_paragraphs` (existing), `_go_to_targets` (existing).
- Produces: `_go_to_fallthrough_targets(program, go_to_targets) -> dict[str, str]`, consumed by Task 3.

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_terminators.py` (new import: `_go_to_fallthrough_targets` alongside `_falls_through`):

```python
def test_go_to_fallthrough_targets_finds_paragraph_after_falling_through():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FALLTHRU.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK.

       1000-DO-WORK-ALIAS.
           GO TO 1000-DO-WORK.

       1000-DO-WORK.
           DISPLAY "WORK".

       1000-AFTER.
           STOP RUN.
"""
    program, _, _, _ = _analyze(source)
    go_to_targets = {"1000-DO-WORK"}
    hazard = _go_to_fallthrough_targets(program, go_to_targets)
    assert hazard == {"1000-AFTER": "1000-DO-WORK"}


def test_go_to_fallthrough_targets_stops_at_a_terminating_paragraph():
    """1000-DO-WORK's own STOP RUN means it never falls through --
    1000-AFTER must not be hazarded."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOFALLTHRU.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK.

       1000-DO-WORK-ALIAS.
           GO TO 1000-DO-WORK.

       1000-DO-WORK.
           DISPLAY "WORK"
           STOP RUN.

       1000-AFTER.
           STOP RUN.
"""
    program, _, _, _ = _analyze(source)
    go_to_targets = {"1000-DO-WORK"}
    hazard = _go_to_fallthrough_targets(program, go_to_targets)
    assert hazard == {}


def test_go_to_fallthrough_targets_propagates_through_computed_go_to():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPUTEDCHAIN.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N                PIC 9 VALUE 9.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK.

       1000-DO-WORK-ALIAS.
           GO TO 1000-DO-WORK.

       1000-DO-WORK.
           GO TO 1000-A 1000-B DEPENDING ON WS-N.

       1000-A.
           DISPLAY "A".

       1000-B.
           STOP RUN.
"""
    program, _, _, _ = _analyze(source)
    go_to_targets = {"1000-DO-WORK"}
    hazard = _go_to_fallthrough_targets(program, go_to_targets)
    # 1000-DO-WORK's own computed GO TO does not stop fall-through, so
    # BOTH 1000-A (falls through) and 1000-B (terminates, chain stops
    # there) are hazarded.
    assert hazard == {"1000-A": "1000-DO-WORK", "1000-B": "1000-DO-WORK"}


def test_go_to_fallthrough_targets_seeds_from_section_first_paragraph():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTIONFALLTHRU.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-SECTION.

       1000-SECTION-ALIAS.
           GO TO 1000-SECTION.

       1000-SECTION SECTION.
       1000-FIRST.
           DISPLAY "FIRST".
       1000-SECOND.
           DISPLAY "SECOND".

       1000-AFTER.
           STOP RUN.
"""
    program, _, _, _ = _analyze(source)
    go_to_targets = {"1000-SECTION"}
    hazard = _go_to_fallthrough_targets(program, go_to_targets)
    assert hazard == {
        "1000-SECOND": "1000-SECTION",
        "1000-AFTER": "1000-SECTION",
    }
```

Run: `python -m pytest tests/unit/test_terminators.py -k go_to_fallthrough_targets -v`
Expect: fails (function doesn't exist yet).

- [ ] **Step 2: Implement `_go_to_fallthrough_targets`**

Add to `mockymock/analysis/refusal.py`, directly after `_falls_through`:

```python
def _go_to_fallthrough_targets(
    program, go_to_targets: set[str]
) -> dict[str, str]:
    """Every paragraph reachable ONLY by falling through past a GO TO
    target's own end -- an unmodeled shape the reachability BFS does not
    represent as a flow edge (see the module docstring). Maps each such
    paragraph name to the GO-TO-target paragraph/section name whose
    fall-through chain reaches it, for diagnosable refusal messages.

    A paragraph entered this way carries the exact same EXIT PARAGRAPH
    hazard as a paragraph directly named by a GO TO (spike #4, docs/
    2026-07-08-goback-stop-run-support-design.md): the runtime frame-stack
    context at the point its code executes never went through a genuine
    PERFORM call, whether that paragraph is itself the GO TO target or was
    merely fallen into afterward.

    Conservative and fail-closed like the rest of this module: propagates
    through every paragraph after a GO TO target in source order until one
    is found whose own last top-level statement provably cannot fall
    through further (see _falls_through). A GO TO targeting a SECTION name
    is seeded from that section's first paragraph -- fall-through is
    transparent to SECTION boundaries, a header doesn't stop it; the
    section's own member paragraphs are covered by the walk since
    _source_ordered_paragraphs includes every paragraph regardless of
    section membership.

    Returns {} when _source_ordered_paragraphs can't establish a strict
    source order -- the same pre-existing blind spot that already limits
    other checks in this module (e.g. _expand_thru_range) to refusing only
    the specific reachability question they were asked, not every
    reachability question in the file."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return {}
    ordered = _source_ordered_paragraphs(procedure)
    if ordered is None:
        return {}
    index_by_name = {p.paragraph_name: i for i, p in enumerate(ordered)}
    section_members: dict[str, list[str]] = {}
    for section_name, section in getattr(procedure, "_sections", {}).items():
        if not section_name:
            continue
        section_members.setdefault(
            section_name, [p.paragraph_name for p in section.paragraphs]
        )

    hazard: dict[str, str] = {}
    for name in go_to_targets:
        start = index_by_name.get(name)
        if start is None:
            members = section_members.get(name)
            if not members:
                continue
            start = index_by_name.get(members[0])
            if start is None:
                continue
        cursor = start
        while _falls_through(ordered[cursor]) and cursor + 1 < len(ordered):
            cursor += 1
            hazard.setdefault(ordered[cursor].paragraph_name, name)
    return hazard
```

- [ ] **Step 3: Run tests, confirm green**

Run: `python -m pytest tests/unit/test_terminators.py -k go_to_fallthrough_targets -v`
Expect: all pass.

---

## Task 3: Wire into `find_terminator_plans`, test-first

**Only proceed once Task 2 is green.**

**Files:**
- Modify: `mockymock/analysis/refusal.py`
- Modify: `tests/unit/test_terminators.py`

**Interfaces:**
- Consumes: `_go_to_fallthrough_targets` (Task 2).
- Produces: two new refusal paths in `find_terminator_plans`, both `UNSUPPORTED_TERMINATOR_LAYOUT`.

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_terminators.py`, alongside `test_go_to_reachable_terminator_refuses` and `test_go_to_target_refuses_even_when_a_different_case_uses_it_safely`:

```python
GO_TO_FALLTHROUGH_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOFALLUNSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK
           STOP RUN.

       1000-DO-WORK.
           DISPLAY "WORK".

       1000-DO-WORK-ALIAS.
           GO TO 1000-DO-WORK.

       1000-AFTER.
           STOP RUN.
"""

GO_TO_FALLTHROUGH_CHAIN_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOFALLCHAIN.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  UT-EARLY-EXIT       PIC X VALUE "N".

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-WRAPPER.

       1000-WRAPPER.
           PERFORM 1000-DO-WORK
           STOP RUN.

       1000-DO-WORK.
           DISPLAY "WORK".

       1000-DO-WORK-ALIAS.
           GO TO 1000-DO-WORK.

       1000-AFTER.
           STOP RUN.
"""


def test_go_to_fallthrough_terminator_refuses():
    """1000-AFTER's STOP RUN is never itself a GO TO target -- it's only
    reachable because 1000-DO-WORK (a GO TO target) falls through into
    it. Must refuse with the same UNSUPPORTED_TERMINATOR_LAYOUT code as a
    direct GO TO target, naming the fall-through path."""
    program, surface, scope_map, lines = _analyze(GO_TO_FALLTHROUGH_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "1000-DO-WORK" in reasons[0].message
    assert "falling through" in reasons[0].message


def test_go_to_fallthrough_does_not_refuse_when_target_terminates():
    """Negative control: 1000-DO-WORK's own STOP RUN means it never falls
    through, so 1000-AFTER's terminator is unaffected -- no false-positive
    refusal of an ordinary safe program."""
    source = GO_TO_FALLTHROUGH_UNSAFE_SOURCE.replace(
        '1000-DO-WORK.\n           DISPLAY "WORK".',
        '1000-DO-WORK.\n           DISPLAY "WORK"\n           STOP RUN.',
    )
    program, surface, scope_map, lines = _analyze(source)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert reasons == []
    assert len(plans) == 2
    assert {p.site.paragraph_name for p in plans} == {
        "0000-MAIN-PROCESS",
        "1000-DO-WORK",
    }


def test_go_to_fallthrough_chain_paragraph_refuses():
    """The terminator itself (in 1000-WRAPPER) is perfectly fine on its
    own -- the hazard is that 1000-AFTER, reached via GO-TO-fallthrough,
    is part of this test's own restricted-reachable chain_performs set.
    Mirrors test_go_to_target_refuses_even_when_a_different_case_uses_it_safely's
    chain-level shape but for the fallthrough hazard instead of a direct
    GO TO target."""
    program, surface, scope_map, lines = _analyze(GO_TO_FALLTHROUGH_CHAIN_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "falling through" in reasons[0].message
```

Note on `test_go_to_fallthrough_chain_paragraph_refuses`: `1000-AFTER` is
never PERFORMed by anything, so it must still land in the case's
`safe_names` (via `_plain_perform_edges_from`) for `chain_fallthrough_names`
to be non-empty -- re-check this fixture against actual `_plain_perform_edges_from`
behavior when running the test; adjust the source (e.g. add a real
`PERFORM 1000-AFTER` edge from `1000-WRAPPER` if the dead-reckoning above
doesn't actually land `1000-AFTER` in `safe_names`) so the test exercises
the *chain* check specifically rather than accidentally exercising the
per-terminator check from Step 1 of this task on a different paragraph.
Verify the fixture produces exactly the intended code path before trusting
the assertions.

Run: `python -m pytest tests/unit/test_terminators.py -k go_to_fallthrough -v`
Expect: `test_go_to_fallthrough_terminator_refuses` and
`test_go_to_fallthrough_chain_paragraph_refuses` fail (reasons currently
empty, plans non-empty or shaped differently). Others may already pass
incidentally -- confirm which.

- [ ] **Step 2: Wire the checks into `find_terminator_plans`**

In `mockymock/analysis/refusal.py`, inside `find_terminator_plans`:

Right after:
```python
    top_level_names = {p.paragraph_name for p in procedure.paragraphs}
    go_to_targets = _go_to_targets(program)
```
add:
```python
    go_to_fallthrough = _go_to_fallthrough_targets(program, go_to_targets)
```

Inside the `for case in suite.test_cases:` loop, right after:
```python
        chain_go_to_names = safe_names & go_to_targets
```
add:
```python
        chain_fallthrough_names = safe_names & go_to_fallthrough.keys()
```

In the per-site `if/elif` chain, right after the existing:
```python
            elif paragraph_name in go_to_targets:
                problem = (
                    "is reachable via GO TO somewhere in this program -- "
                    "the early-exit propagation mechanism (EXIT PARAGRAPH) "
                    "only works correctly when a paragraph is entered "
                    "exclusively via PERFORM"
                )
```
add:
```python
            elif paragraph_name in go_to_fallthrough:
                problem = (
                    f"is reached by falling through past the end of "
                    f"paragraph '{go_to_fallthrough[paragraph_name]}', "
                    f"which is itself reachable via GO TO somewhere in "
                    f"this program -- a paragraph entered this way was "
                    f"never PERFORMed either, so it shares the same "
                    f"EXIT PARAGRAPH hazard as a direct GO TO target even "
                    f"though it is never named by a GO TO itself"
                )
```

And right after the existing:
```python
            elif chain_go_to_names:
                # paragraph_name can't be a member here: the preceding elif
                # already excluded it from go_to_targets, and chain_go_to_names
                # is a subset of go_to_targets.
                bad_name = sorted(chain_go_to_names)[0]
                problem = (
                    f"is only reachable through this test's own early-exit "
                    f"propagation chain by way of '{bad_name}', which is "
                    f"reachable via GO TO somewhere in this program -- the "
                    f"early-exit propagation mechanism (EXIT PARAGRAPH) "
                    f"only works correctly when a paragraph is entered "
                    f"exclusively via PERFORM"
                )
```
add:
```python
            elif chain_fallthrough_names:
                bad_name = sorted(chain_fallthrough_names)[0]
                problem = (
                    f"is only reachable through this test's own early-exit "
                    f"propagation chain by way of '{bad_name}', which is "
                    f"reached by falling through past the end of paragraph "
                    f"'{go_to_fallthrough[bad_name]}' rather than via "
                    f"PERFORM -- the early-exit propagation mechanism "
                    f"(EXIT PARAGRAPH) only works correctly when every "
                    f"paragraph on the chain is entered exclusively via "
                    f"PERFORM"
                )
```

- [ ] **Step 3: Run the full terminator test suite, confirm green**

Run: `python -m pytest tests/unit/test_terminators.py -v`
Expect: all pass, including every pre-existing test (no regressions).

- [ ] **Step 4: Run the full unit suite**

Run: `python -m pytest tests/unit -q`
Expect: all pass.

---

## Task 4: Docs sync

**Only proceed once Task 3 is green.**

**Files:**
- Modify: `mockymock/analysis/refusal.py` (module docstring only)
- Modify: `docs/2026-07-06-real-world-readiness-audit.md`

- [ ] **Step 1: Update the module docstring's GO TO bullet**

In `refusal.py`, the module docstring's parenthetical currently reads (in part):

```
(A GO TO that escapes its PERFORM range and
  relies on falling through *past* its target paragraph is not modeled --
  such control flow runs off the end of the program at test runtime and is
  covered by the documented STOP RUN limitation. Noted by the 2026-07-09
  final branch review: ...
  Exotic, not hardened
  against; documented here rather than silently assumed harmless.)
```

Replace it with a version stating this is now modeled and refused --
describe `_go_to_fallthrough_targets` in the same explanatory register as
the rest of the docstring (what hazard it closes, and a pointer to
`docs/2026-07-10-goto-fallthrough-terminator-hazard-design.md`), removing
the "exotic, not hardened against" framing since it no longer applies.

- [ ] **Step 2: Update the readiness audit doc**

In `docs/2026-07-06-real-world-readiness-audit.md`, Finding 3's bullet list
currently ends with: "One documented-but-unmodeled edge case remains: a
`GO TO` that escapes its `PERFORM` range and falls through to an
already-neutralized terminator in a different test case." Update this to
say it's now guarded (refused via `UNSUPPORTED_TERMINATOR_LAYOUT`), citing
this design doc.

- [ ] **Step 3: Commit**

```bash
git add mockymock/analysis/refusal.py tests/unit/test_terminators.py \
  docs/2026-07-10-goto-fallthrough-terminator-hazard-design.md \
  docs/2026-07-06-real-world-readiness-audit.md
git commit -m "fix(analysis): refuse terminators reached via GO TO fall-through"
```

(The design doc itself and this plan may already be committed from an
earlier step depending on how the brainstorming/planning flow was run --
adjust the `git add` list to whatever is actually still unstaged.)
