# GOBACK / STOP RUN Terminator Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a `.cut` test case's `PERFORM` target reach `STOP RUN`/`GOBACK` (directly, or transitively) without killing the whole compiled suite — the case's own `EXPECT`/`VERIFY` checks still run, and later test cases in the suite still run afterward.

**Architecture:** Detect every `STOP RUN`/`GOBACK` statement reachable from at least one test case (reusing the existing reachability BFS unchanged); validate each one through the same span-safety machinery every other boundary site already goes through; split each `UT-TESTCASE-NNN` driver paragraph into a setup half and a `-CHECK` half; replace each reachable terminator with an `EVALUATE UT-CURRENT-CASE` block that `GO TO`s the reaching case's own `-CHECK` paragraph (reusing the existing per-site dispatch pattern).

**Tech Stack:** Python 3.11+, cobolparser (editable sibling dependency), GnuCOBOL 3.2 via the `mockymock-cobc` Docker container, pytest (`tests/unit` no Docker, `tests/integration` `@requires_docker`).

**Design doc:** `docs/2026-07-08-goback-stop-run-support-design.md` — read it before starting; this plan implements it task-by-task and does not re-derive its reasoning.

## Global Constraints

- Every new refusal reason uses the code `UNSUPPORTED_TERMINATOR_LAYOUT` (no other new refusal codes).
- No new `.cut` DSL syntax — the entire feature is analysis/splicer-only.
- `STOP RUN GIVING`/`GOBACK RETURNING` return codes are not captured anywhere.
- `EXIT PROGRAM` is not a transform target — Task 1 verifies it is already a no-op.
- Every existing test in `tests/unit/` and `tests/integration/` must still pass unmodified after each task (this plan only ever *adds* optional parameters with safe defaults to existing public functions — never changes an existing default behavior).
- Follow this repo's docstring convention: a short module/function docstring explaining *why*, not *what*, matching the style already in `mockymock/analysis/refusal.py`, `mockymock/analysis/linkage.py`, and `mockymock/splicer/orchestrator.py`.

---

## Task 1: Verification spike — prove the two load-bearing GnuCOBOL facts

This gates every later task. If either assertion below fails, **stop** — do not proceed to Task 2. Report the actual observed behavior; the design in `docs/2026-07-08-goback-stop-run-support-design.md` needs rework before any code is written.

**Files:**
- Create: `tests/integration/test_terminator_spike.py`

**Interfaces:**
- Consumes: `mockymock.runtime.docker_toolchain` (`ensure_toolchain`, `WORK_ROOT`, `compile_source`, `run_binary`), `tests.integration._docker.requires_docker` — all existing, see `tests/integration/test_splicer_linkage.py` for the exact usage pattern this task copies.
- Produces: nothing consumed by later tasks (this is a standalone empirical check, kept permanently as a regression test against future GnuCOBOL toolchain upgrades).

- [ ] **Step 1: Write the spike test file**

```python
"""Verification spike for docs/2026-07-08-goback-stop-run-support-design.md:
two GnuCOBOL facts the whole design depends on, neither previously tested
in this repo. If either assertion below ever fails (e.g. a GnuCOBOL version
bump), the design needs rework -- do not proceed with the rest of that
design's implementation until these pass again.
"""

import tempfile
from pathlib import Path

from mockymock.runtime import docker_toolchain as dt
from tests.integration._docker import requires_docker

# Proves: PERFORM X THRU Y returns to its caller when execution reaches the
# END of the named range, regardless of whether that end was reached by
# ordinary fall-through or by a GO TO jump into the range from arbitrarily
# deep inside a nested, unrelated PERFORM chain (B-PARA -> C-PARA, neither
# of which is part of the THRU range). This is the mechanism the terminator
# splice depends on: a neutralized STOP RUN/GOBACK, wherever it is nested,
# does a GO TO straight to the reaching test case's own -CHECK paragraph.
THRU_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUSPIKE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MARKER           PIC X(8) VALUE "NONE".

       PROCEDURE DIVISION.
       DRIVER-PARA.
           PERFORM A-PARA THRU A-CHECK
           DISPLAY "RETURNED " WS-MARKER
           STOP RUN.

       A-PARA.
           PERFORM B-PARA.

       A-CHECK.
           DISPLAY "CHECK-RAN".

       B-PARA.
           PERFORM C-PARA.

       C-PARA.
           MOVE "REACHED" TO WS-MARKER
           GO TO A-CHECK.
"""

# Proves: EXIT PROGRAM reached mid-flow in a program that is PERFORMed (not
# CALLed) is a no-op per the COBOL standard -- execution continues to the
# next statement. If this is NOT a no-op under the pinned GnuCOBOL 3.2
# build, EXIT PROGRAM must be folded into the design as a third terminator
# alongside STOP RUN/GOBACK.
EXIT_PROGRAM_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXITSPIKE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MARKER           PIC X(10) VALUE "NONE".

       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM WORK-PARA
           DISPLAY "AFTER " WS-MARKER
           STOP RUN.

       WORK-PARA.
           MOVE "BEFORE" TO WS-MARKER
           EXIT PROGRAM
           MOVE "AFTER-EXIT" TO WS-MARKER.
"""


def _compile_and_run(source: str, name: str):
    dt.ensure_toolchain()
    dt.WORK_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="test-terminator-spike-", dir=dt.WORK_ROOT))
    path = tmp / f"{name}.cbl"
    path.write_text(source, newline="\n")
    compiled = dt.compile_source(path)
    assert compiled.success, compiled.stderr
    return dt.run_binary(compiled.binary_path)


@requires_docker
def test_thru_range_returns_via_goto_from_nested_perform():
    executed = _compile_and_run(THRU_SOURCE, "thruspike")
    assert executed.exit_code == 0, executed.stderr
    # C-PARA ran (proves the GO TO chain reached it), A-CHECK ran (proves
    # the GO TO landed inside the THRU range), and DRIVER-PARA's own
    # DISPLAY ran with the marker C-PARA set -- proving control returned
    # to the THRU range's *caller*, not merely that execution didn't hang.
    assert "REACHED" in executed.stdout
    assert "CHECK-RAN" in executed.stdout
    assert "RETURNED REACHED" in executed.stdout
    # Exactly one pass through C-PARA/A-CHECK -- if the return did NOT
    # happen and execution instead fell through past A-CHECK into B-PARA
    # again, "REACHED" would appear more than once (or the run would hang
    # and this test would time out inside run_binary instead of returning).
    assert executed.stdout.count("REACHED") == 1


@requires_docker
def test_exit_program_is_noop_when_performed_not_called():
    executed = _compile_and_run(EXIT_PROGRAM_SOURCE, "exitspike")
    assert executed.exit_code == 0, executed.stderr
    assert "AFTER AFTER-EXIT" in executed.stdout
```

- [ ] **Step 2: Run the spike (requires Docker)**

Run: `python -m pytest tests/integration/test_terminator_spike.py -v`
Expected: both tests PASS.

- [ ] **Step 3: Decision gate**

If both passed: proceed to Task 2.

If `test_thru_range_returns_via_goto_from_nested_perform` failed: **stop**. Do not write any of Tasks 2–10. The GO-TO-dispatch design (Approach A in the design doc) is unsound as written; report the actual observed `stdout`/`exit_code` back before deciding how to proceed.

If `test_exit_program_is_noop_when_performed_not_called` failed: **stop** before Task 2. `EXIT PROGRAM` needs to be added as a third terminator label everywhere this plan says `STOP RUN`/`GOBACK` (Tasks 2–8) — update `docs/2026-07-08-goback-stop-run-support-design.md`'s "Out of scope" section first, then resume at Task 2 with `EXIT PROGRAM` included in scope.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_terminator_spike.py
git commit -m "test: verify PERFORM THRU return and EXIT PROGRAM no-op facts

Design spike for GOBACK/STOP RUN support (docs/2026-07-08-goback-stop-run-support-design.md).
These two facts are load-bearing for the neutralize-and-redirect design;
both are now proven against the real GnuCOBOL 3.2 toolchain."
```

---

## Task 2: Classify STOP RUN / GOBACK in `mock_surface.py`

**Files:**
- Modify: `mockymock/analysis/mock_surface.py`
- Test: `tests/unit/test_mock_surface.py`

**Interfaces:**
- Consumes: `cobolparser.models.statements.control.StopStatement` (fields: `.stop_type` — `"RUN"` or `"literal"`; `.location.line`), `cobolparser.models.statements.misc.GobackStatement` (no fields needed beyond `.location.line`).
- Produces: `mockymock.analysis.mock_surface._TERMINATOR_LABELS: frozenset[str]` = `{"STOP RUN", "GOBACK"}` — Tasks 3 and 4 import this. `BoundarySite` entries with `category=None`, `label="STOP RUN"` or `label="GOBACK"` appear in `MockSurface.boundary_sites` for every terminating `STOP RUN`/every `GOBACK` — Tasks 3 and 4 consume these via `surface.boundary_sites`/`surface.sites_in(...)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_mock_surface.py` (append; do not modify existing content):

```python
from mockymock.analysis.mock_surface import _TERMINATOR_LABELS

TERMINATOR_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMSAMP.

       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM SUB-PARA
           STOP RUN.

       SUB-PARA.
           GOBACK.

       MESSAGE-PARA.
           STOP "OPERATOR MESSAGE".
"""


def _terminator_surface():
    result = parse_cobol(TERMINATOR_SOURCE, filename="termsamp.cbl")
    assert result.success, result.errors
    return analyze(result.ast)


def test_stop_run_is_detected_as_unmockable_terminator_site():
    surface = _terminator_surface()
    sites = [s for s in surface.boundary_sites if s.label == "STOP RUN"]
    assert len(sites) == 1
    assert sites[0].category is None
    assert sites[0].paragraph_name == "MAIN-PARA"


def test_goback_is_detected_as_unmockable_terminator_site():
    surface = _terminator_surface()
    sites = [s for s in surface.boundary_sites if s.label == "GOBACK"]
    assert len(sites) == 1
    assert sites[0].category is None
    assert sites[0].paragraph_name == "SUB-PARA"


def test_stop_literal_is_not_a_terminator_site():
    """STOP "message" (stop_type == "literal") displays and continues --
    it is not STOP RUN and must not be classified as a terminator."""
    surface = _terminator_surface()
    assert not any(
        s.paragraph_name == "MESSAGE-PARA" and s.label in ("STOP RUN", "GOBACK")
        for s in surface.boundary_sites
    )


def test_terminator_labels_constant_matches_classified_labels():
    assert _TERMINATOR_LABELS == frozenset({"STOP RUN", "GOBACK"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_mock_surface.py -v -k terminator`
Expected: FAIL — `ImportError: cannot import name '_TERMINATOR_LABELS'` (or the classification assertions fail with empty `sites` lists).

- [ ] **Step 3: Implement**

In `mockymock/analysis/mock_surface.py`:

Extend the existing control-statement import (currently `from cobolparser.models.statements.control import EvaluateStatement, SearchStatement`):

```python
from cobolparser.models.statements.control import (
    EvaluateStatement,
    SearchStatement,
    StopStatement,
)
```

Extend the existing misc-statement import (currently `CancelStatement, MergeStatement, ReleaseStatement, ReturnStatement, SortStatement`):

```python
from cobolparser.models.statements.misc import (
    CancelStatement,
    GobackStatement,
    MergeStatement,
    ReleaseStatement,
    ReturnStatement,
    SortStatement,
)
```

Add this constant right after `_SORT_MERGE_TYPES` (around line 168), before `_BOUNDARY_STATEMENT_TYPES`:

```python
# STOP RUN/GOBACK are detected (category None, like CANCEL/SORT-MERGE) but
# never spliced by directive-matching -- a .cut author never writes a MOCK
# for these; the terminator-support feature neutralizes them automatically
# when reachable (see docs/2026-07-08-goback-stop-run-support-design.md).
# Exported so source_map.py and refusal.py can recognize these labels
# without duplicating the literal set.
_TERMINATOR_LABELS = frozenset({"STOP RUN", "GOBACK"})
```

In `_classify_statement`, add this block immediately after the existing `CancelStatement` block (after its `return` statement, before the `ExecSQLStatement` check):

```python
    if isinstance(statement, StopStatement):
        # STOP "literal" (stop_type == "literal") displays the literal and
        # continues -- only STOP RUN terminates the run unit.
        if statement.stop_type == "RUN":
            add_site(None, "STOP RUN")
        return

    if isinstance(statement, GobackStatement):
        add_site(None, "GOBACK")
        return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_mock_surface.py -v`
Expected: PASS (all tests in the file, including the new ones and every pre-existing one).

- [ ] **Step 5: Commit**

```bash
git add mockymock/analysis/mock_surface.py tests/unit/test_mock_surface.py
git commit -m "feat(analysis): classify STOP RUN/GOBACK as detected terminator sites

Part of GOBACK/STOP RUN support (docs/2026-07-08-goback-stop-run-support-design.md).
Category=None, matching the existing CANCEL/SORT-MERGE detected-but-
unmockable pattern. STOP <literal> (a console message, not a terminator)
is explicitly excluded."
```

---

## Task 3: Let `annotate_nested_sites` validate terminator-site splice spans

**Files:**
- Modify: `mockymock/splicer/source_map.py`
- Test: `tests/unit/test_source_map.py`

**Interfaces:**
- Consumes: `mockymock.analysis.mock_surface._TERMINATOR_LABELS` (Task 2).
- Produces: `annotate_nested_sites` now stamps `.span`/`.unspliceable_reason` on `BoundarySite` entries whose `label` is in `_TERMINATOR_LABELS`, using the exact same validation every other boundary site gets. Task 4 depends on this running before `find_reachable_terminators`/`check_terminator_layout` are called.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_source_map.py` (append):

```python
TERMINATOR_OWN_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMOWNLINE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK
           STOP RUN.

       1000-DO-WORK.
           CALL "CALCPGM" USING WS-RESULT.
"""

TERMINATOR_SHARED_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMSHARELINE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           MOVE 1 TO WS-RESULT STOP RUN.
"""

CANCEL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CANCELSAMP.

       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "SUBPGM".
           CANCEL "SUBPGM".
"""


def _analyze_and_annotate(source, name="X.cbl"):
    result = parse_cobol(source, filename=name)
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    return surface


def test_terminator_on_its_own_line_gets_no_unspliceable_reason():
    surface = _analyze_and_annotate(TERMINATOR_OWN_LINE_SOURCE)
    site = next(s for s in surface.boundary_sites if s.label == "STOP RUN")
    assert site.unspliceable_reason is None


def test_terminator_sharing_its_line_is_flagged_unspliceable():
    surface = _analyze_and_annotate(TERMINATOR_SHARED_LINE_SOURCE)
    site = next(s for s in surface.boundary_sites if s.label == "STOP RUN")
    assert site.unspliceable_reason == "does not start its own line"


def test_cancel_site_is_still_unannotated_after_terminator_change():
    """Regression guard: broadening the category-None skip must not start
    annotating CANCEL (or any other category=None label) -- only STOP
    RUN/GOBACK."""
    surface = _analyze_and_annotate(CANCEL_SOURCE)
    site = next(s for s in surface.boundary_sites if s.label == "CANCEL")
    assert site.span is None
    assert site.unspliceable_reason is None
```

Add these imports at the top of `tests/unit/test_source_map.py` if not already present: `from cobolparser import parse_cobol`, `from cobolparser.preprocess import normalize_fixed_format`, `from mockymock.analysis.mock_surface import analyze`, `from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map`. (Check the file's existing imports first — reuse them if already present rather than duplicating.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_source_map.py -v -k terminator`
Expected: FAIL — `site.unspliceable_reason` assertions fail because `annotate_nested_sites` currently skips every `category is None` site unconditionally, leaving both `span` and `unspliceable_reason` at their dataclass defaults (`None`) for STOP RUN too.

- [ ] **Step 3: Implement**

In `mockymock/splicer/source_map.py`, extend the existing import:

```python
from mockymock.analysis.mock_surface import (
    BoundarySite,
    MockSurface,
    _nested_statement_lists,
    _TERMINATOR_LABELS,
)
```

Change `annotate_nested_sites`'s loop (currently `if site.category is None: continue`):

```python
def annotate_nested_sites(
    surface: MockSurface, scope_map: ScopeMap, lines: list[str]
) -> None:
    """... (existing docstring unchanged, add one sentence:) Also validates
    STOP RUN/GOBACK terminator sites (category None, but not skipped like
    other detected-but-unmockable categories) through the identical rules
    -- see docs/2026-07-08-goback-stop-run-support-design.md."""
    for site in surface.boundary_sites:
        if site.category is None and site.label not in _TERMINATOR_LABELS:
            continue
        if site.nested:
            span, reason = _nested_site_span(site, scope_map, lines)
            site.span = span
            site.unspliceable_reason = reason
        else:
            site.unspliceable_reason = _top_level_site_problem(site, scope_map, lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_source_map.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Run the full unit suite to confirm no regression**

Run: `python -m pytest tests/unit -q`
Expected: PASS, same count as baseline plus the new tests from Tasks 2–3 (no prior test broken — CANCEL/SORT-MERGE/dynamic-CALL sites are unaffected since their `label` is never in `_TERMINATOR_LABELS`).

- [ ] **Step 6: Commit**

```bash
git add mockymock/splicer/source_map.py tests/unit/test_source_map.py
git commit -m "feat(splicer): validate terminator-site splice spans

Part of GOBACK/STOP RUN support (docs/2026-07-08-goback-stop-run-support-design.md).
STOP RUN/GOBACK sites now get the same top-level own-line guard and
nested-span validation every other boundary site already gets -- no new
span-computation logic. Other category=None sites (CANCEL, SORT/MERGE,
unresolved dynamic CALL) are unaffected."
```

---

## Task 4: Reachability + guardrails — `refusal.py`

**Files:**
- Modify: `mockymock/analysis/refusal.py`
- Test: Create `tests/unit/test_terminators.py`

**Interfaces:**
- Consumes: `_reachable_paragraphs` (existing, unchanged), `MockSurface.sites_in` (existing), `_TERMINATOR_LABELS` (Task 2), `annotate_nested_sites` output (Task 3 — callers must run it first).
- Produces: `mockymock.analysis.refusal.TerminatorSite` (dataclass: `site: BoundarySite`, `case_ids: list[str]`), `find_reachable_terminators(surface, program, suite) -> list[TerminatorSite]`, `check_terminator_layout(surface, program, suite) -> list[RefusalReason]` (code `"UNSUPPORTED_TERMINATOR_LAYOUT"`). Tasks 5, 7, and 8 import all three names from `mockymock.analysis.refusal`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_terminators.py`:

```python
"""Unit tests for terminator (STOP RUN/GOBACK) reachability and the
UNSUPPORTED_TERMINATOR_LAYOUT guardrail. Mirrors tests/unit/test_linkage.py's
structure: analysis.py functions and refusal.py's wrapper of them are tested
together since they're always used together. See
docs/2026-07-08-goback-stop-run-support-design.md.
"""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import (
    check_terminator_layout,
    find_reachable_terminators,
)
from mockymock.dsl.model import MockTestCase, MockTestSuite
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMTEST.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK
           STOP RUN.

       1000-DO-WORK.
           CALL "CALCPGM" USING WS-RESULT.
"""

SHARED_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMSHARE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           MOVE 1 TO WS-RESULT STOP RUN.
"""


def _analyze(source, name="TERMTEST.cbl"):
    result = parse_cobol(source, filename=name)
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    return result.ast, surface


def _suite(perform_target="0000-MAIN-PROCESS"):
    case = MockTestCase(name="c", perform_target=perform_target)
    return MockTestSuite(name="S", test_cases=[case])


def test_find_reachable_terminators_finds_stop_run_reachable_from_target():
    program, surface = _analyze(SOURCE)
    terms = find_reachable_terminators(surface, program, _suite())
    assert len(terms) == 1
    assert terms[0].site.label == "STOP RUN"
    assert terms[0].case_ids == ["001"]


def test_find_reachable_terminators_empty_when_unreachable():
    program, surface = _analyze(SOURCE)
    suite = _suite(perform_target="1000-DO-WORK")
    assert find_reachable_terminators(surface, program, suite) == []


def test_find_reachable_terminators_collects_every_reaching_case():
    program, surface = _analyze(SOURCE)
    suite = MockTestSuite(
        name="S",
        test_cases=[
            MockTestCase(name="a", perform_target="0000-MAIN-PROCESS"),
            MockTestCase(name="b", perform_target="1000-DO-WORK"),
            MockTestCase(name="c", perform_target="0000-MAIN-PROCESS"),
        ],
    )
    terms = find_reachable_terminators(surface, program, suite)
    assert len(terms) == 1
    assert terms[0].case_ids == ["001", "003"]


def test_check_terminator_layout_clean_for_qualifying_shape():
    program, surface = _analyze(SOURCE)
    assert check_terminator_layout(surface, program, _suite()) == []


def test_check_terminator_layout_refuses_shared_line():
    program, surface = _analyze(SHARED_LINE_SOURCE)
    reasons = check_terminator_layout(surface, program, _suite())
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "0000-MAIN-PROCESS" in reasons[0].message


def test_check_terminator_layout_clean_when_unreachable():
    program, surface = _analyze(SHARED_LINE_SOURCE)
    suite = _suite(perform_target="0000-MAIN-PROCESS")
    suite.test_cases[0].perform_target = "NO-SUCH-PARA"
    # Deliberately unresolved target: check_test_case would separately
    # report UNKNOWN_PARAGRAPH for this -- check_terminator_layout must not
    # also raise or report a terminator finding for an unreachable target.
    assert check_terminator_layout(surface, program, suite) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_terminators.py -v`
Expected: FAIL — `ImportError: cannot import name 'find_reachable_terminators' from 'mockymock.analysis.refusal'`.

- [ ] **Step 3: Implement**

In `mockymock/analysis/refusal.py`, extend the existing `mock_surface` import (currently `BoundarySite, MockSurface, _all_paragraphs, _nested_statement_lists, normalize_exec_text`):

```python
from mockymock.analysis.mock_surface import (
    BoundarySite,
    MockSurface,
    _all_paragraphs,
    _nested_statement_lists,
    _TERMINATOR_LABELS,
    normalize_exec_text,
)
```

Extend the existing `dsl.model` import (currently `EXEC_CATEGORIES, MockCategory, MockDirective, MockTestCase`):

```python
from mockymock.dsl.model import (
    EXEC_CATEGORIES,
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
)
```

Add this after `check_test_case` (before `_find_flow_statements`):

```python
@dataclass
class TerminatorSite:
    """One physical STOP RUN/GOBACK statement reachable from at least one
    .cut test case, with every case id (driver.py's zero-padded
    `{index:03d}` convention) that can reach it. See
    docs/2026-07-08-goback-stop-run-support-design.md."""

    site: BoundarySite
    case_ids: list[str] = field(default_factory=list)


def find_reachable_terminators(
    surface: MockSurface, program, suite: MockTestSuite
) -> list[TerminatorSite]:
    """One entry per physical STOP RUN/GOBACK statement reachable from at
    least one test case's PERFORM target/thru range, reusing
    `_reachable_paragraphs` unchanged -- no new control-flow modeling.
    Sites reachable from no test case are omitted (left untouched, exactly
    like any other unmocked boundary)."""
    terminator_sites = {
        id(s.statement): s
        for s in surface.boundary_sites
        if s.category is None and s.label in _TERMINATOR_LABELS
    }
    by_statement: dict[int, TerminatorSite] = {}
    for index, case in enumerate(suite.test_cases, start=1):
        reachable, _ = _reachable_paragraphs(
            program, case.perform_target, case.perform_thru
        )
        for site in surface.sites_in(reachable):
            key = id(site.statement)
            if key not in terminator_sites:
                continue
            if key not in by_statement:
                by_statement[key] = TerminatorSite(site=terminator_sites[key])
            by_statement[key].case_ids.append(f"{index:03d}")
    return list(by_statement.values())


def check_terminator_layout(
    surface: MockSurface, program, suite: MockTestSuite
) -> list[RefusalReason]:
    """UNSUPPORTED_TERMINATOR_LAYOUT for any STOP RUN/GOBACK reachable from
    at least one test case whose splice span did not validate -- reuses the
    exact same top-level own-line guard / nested scope validation every
    other boundary site goes through (`annotate_nested_sites` must have run
    already, same precondition as `check_nested_exec`/`check_test_case`).
    See docs/2026-07-08-goback-stop-run-support-design.md."""
    reasons: list[RefusalReason] = []
    for term in find_reachable_terminators(surface, program, suite):
        site = term.site
        cases = ", ".join(term.case_ids)
        if site.nested and site.span is None:
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_TERMINATOR_LAYOUT",
                    message=(
                        f"{site.label} at line {site.line} (paragraph "
                        f"'{site.paragraph_name}') is reachable from test "
                        f"case(s) {cases} but is nested inside a "
                        f"conditional/loop body and cannot be safely "
                        f"spliced: {site.unspliceable_reason or _UNANNOTATED}"
                    ),
                )
            )
        elif not site.nested and site.unspliceable_reason:
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_TERMINATOR_LAYOUT",
                    message=(
                        f"{site.label} at line {site.line} (paragraph "
                        f"'{site.paragraph_name}') is reachable from test "
                        f"case(s) {cases} but {site.unspliceable_reason} -- "
                        f"splicing it would corrupt sibling code sharing "
                        f"its line(s)"
                    ),
                )
            )
    return reasons
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_terminators.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Run the full unit suite to confirm no regression**

Run: `python -m pytest tests/unit -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mockymock/analysis/refusal.py tests/unit/test_terminators.py
git commit -m "feat(analysis): reachability + UNSUPPORTED_TERMINATOR_LAYOUT guardrail

Part of GOBACK/STOP RUN support (docs/2026-07-08-goback-stop-run-support-design.md).
find_reachable_terminators reuses _reachable_paragraphs unchanged;
check_terminator_layout wraps it in the same fail-closed style as
check_linkage_layout/check_nested_exec."
```

---

## Task 5: `build_terminator_dispatch` — `injector.py`

**Files:**
- Modify: `mockymock/splicer/injector.py`
- Test: `tests/unit/test_injector.py`

**Interfaces:**
- Consumes: `mockymock.analysis.refusal.TerminatorSite` (Task 4).
- Produces: `build_terminator_dispatch(term: TerminatorSite) -> list[str]`. Task 7 calls this from `orchestrator.splice_program`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_injector.py` (append):

```python
from mockymock.analysis.refusal import TerminatorSite
from mockymock.splicer.injector import build_terminator_dispatch


def _terminator_site(label="STOP RUN", line=9):
    return BoundarySite(
        category=None,
        label=label,
        keys=(),
        match_text=None,
        paragraph_name="0000-MAIN-PROCESS",
        line=line,
        nested=False,
        statement=object(),
    )


def test_terminator_dispatch_go_tos_each_reaching_case_check_paragraph():
    term = TerminatorSite(site=_terminator_site(), case_ids=["001", "003"])
    lines = build_terminator_dispatch(term)
    joined = "\n".join(lines)
    assert 'WHEN "001"' in joined
    assert "GO TO UT-TESTCASE-001-CHECK" in joined
    assert 'WHEN "003"' in joined
    assert "GO TO UT-TESTCASE-003-CHECK" in joined
    assert "MOCK" not in joined  # no tally increment -- terminators are never mocked


def test_terminator_dispatch_when_other_matches_existing_precedent():
    term = TerminatorSite(site=_terminator_site(label="GOBACK", line=42), case_ids=["001"])
    lines = build_terminator_dispatch(term)
    assert lines[0] == "           EVALUATE UT-CURRENT-CASE"
    assert lines[-4] == "               WHEN OTHER"
    assert "GOBACK (line 42) reached" in lines[-3]
    assert lines[-2] == "                   ADD 1 TO UT-FAIL-COUNT"
    assert lines[-1] == "           END-EVALUATE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_injector.py -v -k terminator`
Expected: FAIL — `ImportError: cannot import name 'build_terminator_dispatch'`.

- [ ] **Step 3: Implement**

In `mockymock/splicer/injector.py`, extend the existing import:

```python
from mockymock.analysis.mock_surface import BoundarySite
from mockymock.analysis.refusal import TerminatorSite, directive_matches_site
from mockymock.dsl.model import MockTestSuite
from mockymock.splicer.naming import TallyRegistry
```

Add after `build_exec_trap`:

```python
def build_terminator_dispatch(term: TerminatorSite) -> list[str]:
    """EVALUATE block replacing one reachable STOP RUN/GOBACK statement:
    redirects control to each reaching test case's own -CHECK paragraph
    instead of terminating the whole compiled suite (see
    docs/2026-07-08-goback-stop-run-support-design.md). WHEN OTHER matches
    build_site_dispatch's precedent exactly -- a loud failure, not a hard
    stop -- since the refusal gate is expected to make this branch
    unreachable in practice."""
    lines = ["           EVALUATE UT-CURRENT-CASE"]
    for case_id in term.case_ids:
        lines.append(f'               WHEN "{case_id}"')
        lines.append(f"                   GO TO UT-TESTCASE-{case_id}-CHECK")
    lines.append("               WHEN OTHER")
    lines.append(
        f'                   DISPLAY "__MOCKYMOCK__ ERROR: {term.site.label} '
        f'(line {term.site.line}) reached "'
    )
    lines.append(
        '                       "from unexpected test case " UT-CURRENT-CASE'
    )
    lines.append("                   ADD 1 TO UT-FAIL-COUNT")
    lines.append("           END-EVALUATE")
    return lines
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_injector.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/injector.py tests/unit/test_injector.py
git commit -m "feat(splicer): add build_terminator_dispatch

Part of GOBACK/STOP RUN support (docs/2026-07-08-goback-stop-run-support-design.md).
Same EVALUATE UT-CURRENT-CASE dispatch shape as build_site_dispatch, but
GO TOs the reaching case's -CHECK paragraph instead of splicing a mock body."
```

---

## Task 6: Split `UT-TESTCASE-NNN` into setup + `-CHECK` paragraphs — `driver.py`

**Files:**
- Modify: `mockymock/splicer/driver.py`
- Test: `tests/unit/test_driver.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `build_driver`'s generated suite paragraph now performs `UT-TESTCASE-NNN THRU UT-TESTCASE-NNN-CHECK` (was: `UT-TESTCASE-NNN` alone); every case now emits two paragraphs, `UT-TESTCASE-NNN.` (setup, ending with a period-terminated `PERFORM {target}` sentence) and `UT-TESTCASE-NNN-CHECK.` (the `EXPECT`/`VERIFY` checks). This is the paragraph-name contract Task 5's `build_terminator_dispatch` (`GO TO UT-TESTCASE-{case_id}-CHECK`) and Task 8's integration test depend on.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_driver.py` (append):

```python
def test_suite_performs_testcase_thru_check_paragraph():
    joined = "\n".join(_build().procedure_lines)
    assert "PERFORM UT-TESTCASE-001 THRU UT-TESTCASE-001-CHECK" in joined


def test_testcase_check_paragraph_header_exists():
    joined = "\n".join(_build().procedure_lines)
    assert "UT-TESTCASE-001-CHECK." in joined


def test_setup_paragraph_perform_line_is_period_terminated():
    lines = _build().procedure_lines
    perform_line = next(
        ln for ln in lines if ln.strip().startswith("PERFORM PROCESS-ORDER")
    )
    assert perform_line.rstrip().endswith(".")


def test_check_paragraph_comes_after_setup_paragraph_and_perform():
    lines = _build().procedure_lines
    setup_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "UT-TESTCASE-001.")
    perform_idx = next(
        i for i, ln in enumerate(lines) if ln.strip().startswith("PERFORM PROCESS-ORDER")
    )
    check_idx = next(
        i for i, ln in enumerate(lines) if ln.strip() == "UT-TESTCASE-001-CHECK."
    )
    assert setup_idx < perform_idx < check_idx
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_driver.py -v -k "thru_check or check_paragraph or period_terminated or comes_after"`
Expected: FAIL — the suite paragraph still says `PERFORM UT-TESTCASE-001` with no `THRU`, and no `UT-TESTCASE-001-CHECK.` header exists yet.

- [ ] **Step 3: Implement**

In `mockymock/splicer/driver.py`, replace the suite-perform loop inside `build_driver` (currently `for index in range(1, len(suite.test_cases) + 1): procedure.append(f"           PERFORM UT-TESTCASE-{index:03d}")`):

```python
    for index in range(1, len(suite.test_cases) + 1):
        case_id = f"{index:03d}"
        procedure.append(
            f"           PERFORM UT-TESTCASE-{case_id} THRU UT-TESTCASE-{case_id}-CHECK"
        )
```

Replace the per-case loop (currently calls `_build_testcase_paragraph` once per case):

```python
    for index, case in enumerate(suite.test_cases, start=1):
        procedure.extend(
            _build_testcase_setup_paragraph(index, case, registry, bool(reset_lines))
        )
        procedure.append("")
        procedure.extend(_build_testcase_check_paragraph(index, case, registry))
        procedure.append("")
```

Replace the entire `_build_testcase_paragraph` function with these two functions:

```python
def _build_testcase_setup_paragraph(
    index: int, case: MockTestCase, registry: TallyRegistry, has_reset: bool
) -> list[str]:
    case_id = f"{index:03d}"
    lines = [f"       UT-TESTCASE-{case_id}."]

    if has_reset:
        lines.append("           PERFORM UT-RESET-WORKING-STORAGE")
    lines.append(f'           MOVE "{case_id}" TO UT-CURRENT-CASE')
    for category, key in dict.fromkeys((m.category, m.key) for m in case.mocks):
        lines.append(f"           MOVE 0 TO {registry.name(category, key)}")
    lines.append(
        f'           DISPLAY "__MOCKYMOCK__ CASE {case_id} START: '
        f'{_display_text(case.name)}"'
    )

    for value, target in case.setup_moves:
        lines.append(f"           MOVE {value} TO {target}")

    lines.append("")
    perform_line = f"           PERFORM {case.perform_target}"
    if case.perform_thru:
        perform_line += f" THRU {case.perform_thru}"
    # This is now the setup paragraph's LAST statement -- it must
    # terminate the sentence with a period, or the UT-TESTCASE-NNN-CHECK
    # paragraph header right after it creates an unterminated sentence
    # that cobc rejects.
    lines.append(perform_line + ".")
    return lines


def _build_testcase_check_paragraph(
    index: int, case: MockTestCase, registry: TallyRegistry
) -> list[str]:
    case_id = f"{index:03d}"
    case_mocks = {(mock.category, mock.key) for mock in case.mocks}
    lines = [f"       UT-TESTCASE-{case_id}-CHECK."]

    for expectation in case.expectations:
        lines.append(
            f"           IF {expectation.data_name} NOT = {expectation.expected_value}"
        )
        lines.append(
            f'               DISPLAY "__MOCKYMOCK__ CASE {case_id} FAIL: expected '
            f'{expectation.data_name} = {_display_text(expectation.expected_value)}"'
        )
        lines.append("               ADD 1 TO UT-FAIL-COUNT")
        lines.append("           END-IF")

    for verification in case.verifications:
        if (verification.category, verification.key) not in case_mocks:
            raise ValueError(
                f"VERIFY references {verification.category.keyword} "
                f"{verification.key!r}, which no MOCK directive in this TESTCASE "
                f"declares (should have been refused before codegen)"
            )
        tally = registry.name(verification.category, verification.key)
        condition = _verify_condition(verification.expectation, tally)
        lines.append(f"           IF {condition}")
        lines.append(
            f'               DISPLAY "__MOCKYMOCK__ CASE {case_id} FAIL: VERIFY '
            f"{verification.category.keyword} {_display_text(verification.key)} WAS CALLED "
            f'{verification.expectation}"'
        )
        lines.append("               ADD 1 TO UT-FAIL-COUNT")
        lines.append("           END-IF")

    lines.append(f'           DISPLAY "__MOCKYMOCK__ CASE {case_id} END".')
    return lines
```

(`_verify_condition` and `_display_text` are unchanged, module-level helpers already used by the new `_build_testcase_check_paragraph`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_driver.py -v`
Expected: PASS — every pre-existing test in the file passes unchanged (they all assert substrings via `in joined`, which the split does not remove, only relocates into a second paragraph) plus the four new tests.

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/driver.py tests/unit/test_driver.py
git commit -m "feat(splicer): split UT-TESTCASE-NNN into setup + -CHECK paragraphs

Part of GOBACK/STOP RUN support (docs/2026-07-08-goback-stop-run-support-design.md).
The suite driver now performs each case as a THRU range; this is what lets
a neutralized terminator GO TO straight to a case's own checks and still
return control to the suite paragraph afterward. No existing test's
assertions needed to change -- all pre-existing checks were substring-based
and the split only relocates content, never removes it."
```

---

## Task 7: Splice terminator sites — `orchestrator.py`

**Files:**
- Modify: `mockymock/splicer/orchestrator.py`
- Test: `tests/unit/test_orchestrator.py`

**Interfaces:**
- Consumes: `mockymock.analysis.refusal.TerminatorSite` (Task 4), `mockymock.splicer.injector.build_terminator_dispatch` (Task 5).
- Produces: `splice_program(lines, boundaries, surface, suite, registry, terminator_sites=())` — new optional last parameter, default `()`, so every existing call site (8 of them, listed below) keeps working with zero changes. Task 8 is the only call site that will pass a non-empty list.

**Existing call sites that must keep working unmodified (verify, do not edit unless a step below says to):** `mockymock/cli/main.py:301`, `tests/integration/test_cli.py:365,492`, `tests/unit/test_orchestrator.py:61,178,269,315` (line numbers as of this plan's writing; re-`grep -n "splice_program(" .` if they've drifted).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_orchestrator.py` (append; the file already imports `parse_cobol`, `normalize_fixed_format`, `analyze`, `MockCategory`, `MockDirective`, `MockTestCase`, `MockTestSuite`, `TallyRegistry`, `splice_program`, `collect_boundaries`, `annotate_nested_sites`, `collect_scope_map` — reuse them, do not re-import):

```python
from mockymock.analysis.refusal import find_reachable_terminators

TERMINATOR_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMSPLICE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK
           STOP RUN.

       1000-DO-WORK.
           CALL "CALCPGM" USING WS-RESULT.
"""


def _terminator_suite():
    case = MockTestCase(
        name="main",
        mocks=[MockDirective(MockCategory.CALL, "CALCPGM", ["MOVE 42 TO WS-RESULT"])],
        perform_target="0000-MAIN-PROCESS",
    )
    return MockTestSuite(name="T", test_cases=[case])


def _splice_terminator(suite):
    result = parse_cobol(TERMINATOR_SOURCE, filename="termsplice.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(TERMINATOR_SOURCE.splitlines()).splitlines()
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    boundaries = collect_boundaries(result.ast)
    terminator_sites = find_reachable_terminators(surface, result.ast, suite)
    return splice_program(
        lines, boundaries, surface, suite, TallyRegistry(suite), terminator_sites
    )


def test_terminator_site_is_commented_and_dispatch_spliced():
    lines = _splice_terminator(_terminator_suite())
    joined = "\n".join(lines)
    assert "      *>     STOP RUN." in joined
    assert 'WHEN "001"' in joined
    assert "GO TO UT-TESTCASE-001-CHECK" in joined


def test_terminator_splice_coexists_with_mocked_call_splice():
    """Proves the combined bottom-up application (both regular boundary
    splices and terminator splices in ONE sorted spans list) doesn't
    corrupt either one's line numbers."""
    lines = _splice_terminator(_terminator_suite())
    joined = "\n".join(lines)
    assert "ADD 1 TO UT-CALCPGM-TALLY" in joined
    assert "MOVE 42 TO WS-RESULT" in joined
    assert '      *>     CALL "CALCPGM"' in joined


def test_no_terminator_sites_argument_leaves_existing_behavior_unchanged():
    """The old 5-positional-argument call (no terminator_sites) must still
    work exactly as before -- this is the regression guard for every
    existing caller of splice_program."""
    result = parse_cobol(TERMINATOR_SOURCE, filename="termsplice.cbl")
    surface = analyze(result.ast)
    lines = normalize_fixed_format(TERMINATOR_SOURCE.splitlines()).splitlines()
    boundaries = collect_boundaries(result.ast)
    suite = _terminator_suite()
    spliced = splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))
    joined = "\n".join(spliced)
    assert "STOP RUN." in joined
    assert "      *>     STOP RUN." not in joined
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_orchestrator.py -v -k terminator`
Expected: FAIL — `TypeError: splice_program() takes from 5 to 5 positional arguments but 6 were given` (for the tests passing `terminator_sites`).

- [ ] **Step 3: Implement**

In `mockymock/splicer/orchestrator.py`, extend the existing imports:

```python
from mockymock.analysis.mock_surface import MockSurface
from mockymock.analysis.refusal import TerminatorSite, directive_matches_site
from mockymock.dsl.model import EXEC_CATEGORIES, MockTestSuite
from mockymock.splicer.injector import build_exec_trap, build_site_dispatch, build_terminator_dispatch
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.source_map import statement_span
from mockymock.splicer.stub_writer import comment_and_replace
```

Add this helper function above `splice_program` (factored out of the existing per-site span-resolution logic so both the existing boundary-site loop and the new terminator loop share it — verbatim behavior, verified by Step 5's full-suite regression run):

```python
def _resolve_span(
    site,
    replacement: list[str],
    lines: list[str],
    boundaries: list[int],
    last_line: int,
) -> tuple[int, int, list[str]]:
    """Shared span-resolution + trailing-period propagation for any site
    (mocked boundary or neutralized terminator) whose `.span`/
    `.unspliceable_reason` were already stamped by `annotate_nested_sites`."""
    if site.nested:
        if site.span is None:
            raise ValueError(
                f"nested {site.label} site at line {site.line} reached "
                f"the splicer without a validated span -- the refusal "
                f"gate should have refused it"
            )
        start, end = site.span
    else:
        if site.unspliceable_reason:
            raise ValueError(
                f"top-level {site.label} site at line {site.line} "
                f"reached the splicer although it {site.unspliceable_reason} "
                f"-- the refusal gate should have refused it"
            )
        start, end = statement_span(site.statement, boundaries, last_line)
    last_span_line = next(
        (lines[i - 1] for i in range(end, start - 1, -1) if lines[i - 1].strip()),
        "",
    )
    if last_span_line.rstrip().endswith("."):
        replacement = replacement[:-1] + [replacement[-1] + "."]
    return start, end, replacement
```

Replace `splice_program`'s signature and body:

```python
def splice_program(
    lines: list[str],
    boundaries: list[int],
    surface: MockSurface,
    suite: MockTestSuite,
    registry: TallyRegistry,
    terminator_sites: list[TerminatorSite] = (),
) -> list[str]:
    last_line = len(lines)
    spans: list[tuple[int, int, list[str]]] = []
    seen_statement_ids: set[int] = set()

    for site in surface.boundary_sites:
        if site.category is None:
            continue
        if id(site.statement) in seen_statement_ids:
            continue

        mocked = any(
            directive_matches_site(directive, site)
            for case in suite.test_cases
            for directive in case.mocks
        )
        if mocked:
            replacement = build_site_dispatch(site, suite, registry)
        elif site.category in EXEC_CATEGORIES:
            replacement = build_exec_trap(site.label, site.line)
        else:
            continue

        seen_statement_ids.add(id(site.statement))
        spans.append(_resolve_span(site, replacement, lines, boundaries, last_line))

    for term in terminator_sites:
        site = term.site
        if id(site.statement) in seen_statement_ids:
            continue
        seen_statement_ids.add(id(site.statement))
        replacement = build_terminator_dispatch(term)
        spans.append(_resolve_span(site, replacement, lines, boundaries, last_line))

    for start, end, replacement in sorted(spans, key=lambda s: s[0], reverse=True):
        lines = comment_and_replace(lines, start, end, replacement)
    return lines
```

(The module docstring at the top of the file should also gain one sentence noting that terminator sites are spliced through the same bottom-up `spans` list — update it, but this is not required for the tests to pass.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_orchestrator.py -v`
Expected: PASS — every pre-existing test in the file (including the two tests that check exact `ValueError` message substrings, `"without a validated span"` and `"does not start its own line"`, both of which `_resolve_span` still raises verbatim) plus the three new tests.

- [ ] **Step 5: Run the full unit suite to confirm no regression**

Run: `python -m pytest tests/unit -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mockymock/splicer/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "feat(splicer): splice reachable terminator sites in splice_program

Part of GOBACK/STOP RUN support (docs/2026-07-08-goback-stop-run-support-design.md).
terminator_sites defaults to () so every existing 5-argument caller is
unaffected. Factored the existing span-resolution + trailing-period logic
into _resolve_span so both the boundary-site loop and the new terminator
loop share it, and both loops' spans go into ONE sorted-descending
application list -- terminator splices and mocked-boundary splices in the
same program are computed against the same pre-splice line numbers and
applied together, so neither corrupts the other's line offsets."
```

---

## Task 8: Wire it into the CLI + end-to-end integration test

**Files:**
- Modify: `mockymock/cli/main.py`
- Test: Create `tests/integration/test_terminator_support.py`

**Interfaces:**
- Consumes: `check_terminator_layout`, `find_reachable_terminators` (Task 4); `splice_program`'s new `terminator_sites` parameter (Task 7).
- Produces: `mockymock run` no longer crashes when a test case's `PERFORM` target reaches `STOP RUN`/`GOBACK`.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_terminator_support.py`:

```python
"""End-to-end proof that a test case whose PERFORM target reaches STOP RUN
no longer crashes the suite, and that a later test case in the same suite
still runs -- see docs/2026-07-08-goback-stop-run-support-design.md,
Finding 3 of docs/2026-07-06-real-world-readiness-audit.md."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMDEMO.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK
           STOP RUN.

       1000-DO-WORK.
           CALL "CALCPGM" USING WS-RESULT.
"""

CUT = """\
TESTSUITE "TERMDEMO smoke"

TESTCASE "main process computes result"
    MOCK CALL "CALCPGM"
        MOVE 42 TO WS-RESULT
    END-MOCK
    PERFORM 0000-MAIN-PROCESS
    EXPECT WS-RESULT TO BE 42
    VERIFY "CALCPGM" WAS CALLED ONCE

TESTCASE "second case still runs after the first hits STOP RUN"
    MOCK CALL "CALCPGM"
        MOVE 7 TO WS-RESULT
    END-MOCK
    PERFORM 0000-MAIN-PROCESS
    EXPECT WS-RESULT TO BE 7
"""


@requires_docker
def test_case_reaching_stop_run_passes_and_later_case_still_runs(tmp_path: Path, capsys):
    cbl_path = tmp_path / "TERMDEMO.cbl"
    cbl_path.write_text(CBL)
    cut_path = tmp_path / "TERMDEMO.cut"
    cut_path.write_text(CUT)

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "CASE 001 END" in out
    assert "CASE 002 END" in out
    assert "CRASH" not in out
    assert "FAIL" not in out


@requires_docker
def test_expectation_mismatch_after_terminator_still_fails_loudly(
    tmp_path: Path, capsys
):
    """Regression guard: neutralizing the terminator must not accidentally
    make a genuinely wrong EXPECT pass."""
    cbl_path = tmp_path / "TERMDEMO.cbl"
    cbl_path.write_text(CBL)
    broken_cut = CUT.replace("EXPECT WS-RESULT TO BE 42", "EXPECT WS-RESULT TO BE 99")
    cut_path = tmp_path / "TERMDEMO.cut"
    cut_path.write_text(broken_cut)

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "CASE 001 FAIL" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_terminator_support.py -v`
Expected: FAIL — `mockymock run` refuses with no output related to CASE markers, or the run crashes (exit_code != 0 with no `CASE 001 END`/`CASE 002 END` in stdout), since the CLI does not yet call `check_terminator_layout`/`find_reachable_terminators` or pass `terminator_sites` into `splice_program`.

- [ ] **Step 3: Implement**

In `mockymock/cli/main.py`, extend the existing `mockymock.analysis.refusal` import (currently `check_expansion_warnings, check_linkage_layout, check_nested_exec, check_test_case, check_unresolved_copybooks, check_whole_program`):

```python
    from mockymock.analysis.refusal import (
        check_expansion_warnings,
        check_linkage_layout,
        check_nested_exec,
        check_terminator_layout,
        check_test_case,
        check_unresolved_copybooks,
        check_whole_program,
        find_reachable_terminators,
    )
```

Replace this block (the per-case refusal loop through the splice call, currently reading `refused = False` ... `lines = splice_program(lines, boundaries, surface, suite, registry)` ... `lines, _ = transform_data_division_exec(lines)`):

```python
    refused = False
    for case in suite.test_cases:
        for reason in check_test_case(surface, result.ast, case):
            print(f"mockymock run: refused ({reason.code}): {reason.message}")
            refused = True
    for reason in check_terminator_layout(surface, result.ast, suite):
        print(f"mockymock run: refused ({reason.code}): {reason.message}")
        refused = True
    if refused:
        return 1

    boundaries = collect_boundaries(result.ast)
    registry = TallyRegistry(suite)
    terminator_sites = find_reachable_terminators(surface, result.ast, suite)
    lines = splice_program(
        lines, boundaries, surface, suite, registry, terminator_sites
    )
    lines, _ = transform_data_division_exec(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_terminator_support.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Run the full test suite (unit + integration) to confirm no regression**

Run: `python -m pytest tests/ -v`
Expected: PASS (all unit tests; all Docker integration tests, including every pre-existing `examples/real-world/*` and `examples/{invupdt,ordrproc}` end-to-end test).

- [ ] **Step 6: Commit**

```bash
git add mockymock/cli/main.py tests/integration/test_terminator_support.py
git commit -m "feat(cli): support test cases whose PERFORM target reaches a terminator

Closes the core gap in docs/2026-07-08-goback-stop-run-support-design.md
and Finding 3 of docs/2026-07-06-real-world-readiness-audit.md: a test
case reaching STOP RUN/GOBACK now completes and reports PASS/FAIL, and
later test cases in the same suite still run."
```

---

## Task 9: Docs sync

**Files:**
- Modify: `README.md`
- Modify: `.okf/analysis.md`
- Modify: `.okf/splicer.md`
- Modify: `.okf/log.md`
- Modify: `docs/2026-07-06-real-world-readiness-audit.md`
- Modify: `docs/2026-07-08-ims-linkage-support-design.md`

**Interfaces:** None (documentation only).

- [ ] **Step 1: Update `README.md`'s known-limitation section**

Replace the `### Known limitation: STOP RUN inside a test case's PERFORM target` section (locate via `grep -n "Known limitation" README.md`) with:

```markdown
### `STOP RUN` / `GOBACK` inside a test case's PERFORM target

A `.cut` test case's `PERFORM` target may reach `STOP RUN` or `GOBACK` --
directly, transitively through a paragraph it performs, or via `GO TO` --
and the test still completes correctly: the terminator is neutralized and
redirects to that case's own `EXPECT`/`VERIFY` checks, and later test cases
in the same suite are unaffected. This is what makes it possible to
`PERFORM` a program's real top-level driver paragraph (the one that
naturally ends in `STOP RUN`/`GOBACK`) as a test target, not only its
sub-paragraphs.

A small number of layouts refuse (`UNSUPPORTED_TERMINATOR_LAYOUT`) rather
than risk corrupting the program: a terminator sharing its source line with
other code, or nested inside a conditional/loop body in a way that cannot
be safely spliced. Put `STOP RUN`/`GOBACK` on its own line to avoid this.
```

- [ ] **Step 2: Append a dated entry to `.okf/log.md`**

Add to the top of the "Update Log" (after the `# mocky-mock OKF Bundle — Update Log` header, before the existing `## 2026-07-08 (IMS DL/I ...)` entry):

```markdown
## 2026-07-08 (GOBACK/STOP RUN terminator support)
* **Closed Finding 3 of `docs/2026-07-06-real-world-readiness-audit.md`**:
  a `.cut` test case's `PERFORM` target reaching `STOP RUN`/`GOBACK` no
  longer kills the whole compiled suite. `mock_surface.py` detects both
  (category `None`, like `CANCEL`/SORT-MERGE); `refusal.py`'s
  `find_reachable_terminators` reuses the existing reachability BFS
  unchanged and `check_terminator_layout` refuses
  (`UNSUPPORTED_TERMINATOR_LAYOUT`) any site whose splice span doesn't
  validate through the same guard every other boundary site uses.
  `driver.py` now generates `UT-TESTCASE-NNN`/`UT-TESTCASE-NNN-CHECK` as a
  `PERFORM ... THRU ...` pair; a reachable terminator is replaced with an
  `EVALUATE UT-CURRENT-CASE` block that `GO TO`s the reaching case's own
  `-CHECK` paragraph (`injector.build_terminator_dispatch`), reusing the
  same dispatch pattern every mocked boundary already uses.
  Design: [docs/2026-07-08-goback-stop-run-support-design.md](../docs/2026-07-08-goback-stop-run-support-design.md).
```

- [ ] **Step 3: Add a concept row to `.okf/analysis.md`**

In the `# mock_surface.py — What Counts as a Boundary` categories table, add a row after the `CANCEL` row:

```markdown
| `StopStatement` (stop_type == "RUN") / `GobackStatement` | `None` (detected, neutralized when reachable) | — | label `"STOP RUN"`/`"GOBACK"`; see [splicer](splicer.md) and [docs/2026-07-08-goback-stop-run-support-design.md](../docs/2026-07-08-goback-stop-run-support-design.md) -- unlike CANCEL/SORT-MERGE this category IS spliced, via a dedicated path (`refusal.find_reachable_terminators` / `injector.build_terminator_dispatch`), not `directive_matches_site` |
```

Add a row to the per-test-case refusal table (`## Per-test-case checks (check_test_case)` section) noting `check_terminator_layout` runs alongside `check_test_case` (not inside it) with code `UNSUPPORTED_TERMINATOR_LAYOUT`.

- [ ] **Step 4: Add a section to `.okf/splicer.md`**

After the `# ENTRY/LINKAGE Neutralization (linkage.py)` section, add:

```markdown
# Terminator Neutralization (GOBACK/STOP RUN)

`refusal.find_reachable_terminators` finds every `StopStatement`
(RUN-form)/`GobackStatement` reachable from at least one test case;
`injector.build_terminator_dispatch` replaces it with an `EVALUATE
UT-CURRENT-CASE` block that `GO TO`s the reaching case's own
`UT-TESTCASE-NNN-CHECK` paragraph instead of terminating the run.
`driver.build_driver` generates each case as a `PERFORM UT-TESTCASE-NNN
THRU UT-TESTCASE-NNN-CHECK` pair specifically so this works: a `PERFORM
... THRU ...` range returns to its caller once execution reaches the end
of the named range, regardless of whether that end was reached by
ordinary fall-through or by the neutralized terminator's `GO TO` — the
same idiom this file's PERFORM THRU documentation already relies on for
`GO TO MAIN-EXIT ... MAIN-EXIT. EXIT.`-style code the *target program*
writes itself. `orchestrator.splice_program`'s `terminator_sites`
parameter feeds terminator replacements into the same bottom-up
`spans` list as every other boundary splice, so both are computed against
the same pre-splice line numbers. See
[docs/2026-07-08-goback-stop-run-support-design.md](../docs/2026-07-08-goback-stop-run-support-design.md).
```

- [ ] **Step 5: Annotate Finding 3 in the audit doc**

In `docs/2026-07-06-real-world-readiness-audit.md`, immediately after the `## Finding 3` heading line, insert:

```markdown
**Resolved 2026-07-08** — see
[docs/2026-07-08-goback-stop-run-support-design.md](2026-07-08-goback-stop-run-support-design.md).
A reachable terminator is now neutralized and redirected to the reaching
test case's own checks instead of killing the suite. The remainder of this
finding is kept below for history.
```

- [ ] **Step 6: Update the IMS/LINKAGE design doc's worked-example note**

In `docs/2026-07-08-ims-linkage-support-design.md`, in the `### Worked example` section, after the sentence ending "...that would kill the whole test binary regardless of this fix," add:

```markdown
(Resolved by `docs/2026-07-08-goback-stop-run-support-design.md` — see
Task 10 of its implementation plan for re-targeting this example at
`0000-MAIN-PROCESS`.)
```

- [ ] **Step 7: Run OKF validation**

Run: `/okf:validate .okf --strict` (or, if that skill isn't available in this session, manually confirm every edited `.okf/*.md` file still has non-empty YAML frontmatter `type:` and no broken relative links you introduced).
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add README.md .okf/analysis.md .okf/splicer.md .okf/log.md \
    docs/2026-07-06-real-world-readiness-audit.md \
    docs/2026-07-08-ims-linkage-support-design.md
git commit -m "docs: sync GOBACK/STOP RUN terminator support

Updates README's known-limitation section, .okf concepts/log, and marks
Finding 3 of the real-world-readiness audit resolved."
```

---

## Task 10 (optional / stretch): Re-target the ACCTPRG example at its real entry point

This task is explicitly optional — the feature is complete and shippable after Task 9. Do this only if time permits; it is the "once proven" worked-example follow-on the design doc calls out, not a requirement.

**Files:**
- Modify: `examples/real-world/ACCTPRG/ACCTPRG.cut`
- Modify: `examples/real-world/ACCTPRG/README.md` (if one exists — check first)

**Interfaces:** None (example content only).

- [ ] **Step 1: Read the current example**

Read `examples/real-world/ACCTPRG/ACCTPRG.cbl` (find `0000-MAIN-PROCESS` and confirm it ends in `GOBACK`, per `docs/2026-07-08-ims-linkage-support-design.md`'s "Worked example" section) and `examples/real-world/ACCTPRG/ACCTPRG.cut` (see its existing test cases targeting `1000-INITIALIZE`/`2000-SCAN-AND-PURGE`, and the `.cut` directive syntax they use for `MOCK CALL "CBLTDLI"` bodies).

- [ ] **Step 2: Add a new test case targeting `0000-MAIN-PROCESS`**

Following the exact pattern of the existing test cases in `ACCTPRG.cut` (same `MOCK CALL "CBLTDLI"` body shape, setting `CUST-STATUS`/other LINKAGE-turned-WORKING-STORAGE fields the existing cases already reference), add one new `TESTCASE` whose `PERFORM` target is `0000-MAIN-PROCESS` instead of a sub-paragraph. Choose `EXPECT`/`VERIFY` assertions appropriate to what `0000-MAIN-PROCESS` actually does (read it in Step 1 first — do not guess).

- [ ] **Step 3: Run the existing ACCTPRG integration test**

Run: `python -m pytest tests/integration/ -v -k acctprg` (or the specific test file/function covering this example — locate via `grep -rl ACCTPRG tests/integration/`)
Expected: PASS, including the new test case.

- [ ] **Step 4: Update the example's README if one exists**

If `examples/real-world/ACCTPRG/README.md` exists and mentions avoiding `0000-MAIN-PROCESS`, update it to note the new test case now exercises it directly, thanks to terminator support.

- [ ] **Step 5: Commit**

```bash
git add examples/real-world/ACCTPRG/
git commit -m "test(examples): ACCTPRG now also tests its real 0000-MAIN-PROCESS entry point

Demonstrates GOBACK/STOP RUN terminator support end-to-end on a real
corpus program, not just the synthetic TERMDEMO fixture."
```
