# GOBACK / STOP RUN Terminator Support Implementation Plan (Approach B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Supersedes note:** an earlier version of this plan implemented Approach A
(redirect a neutralized terminator via `GO TO` into a `PERFORM ... THRU
...` range). That approach was disproven by its own verification spike —
see `docs/2026-07-08-goback-stop-run-support-design.md`'s "Approach A —
rejected, kept for history" section for the concrete crash evidence. This
plan implements Approach B (propagate an early-exit flag via `EXIT
PARAGRAPH`/`EXIT SECTION`) from scratch. No code from the earlier attempt
exists in the repo — nothing was ever merged.

**Goal:** Let a `.cut` test case's `PERFORM` target reach `STOP RUN`/`GOBACK`
(through a chain of plain, unconditional, top-level `PERFORM` calls — the
scope this plan supports) without killing the whole compiled suite, by
propagating an early-exit flag back up the real call chain via `EXIT
PARAGRAPH` instead of jumping anywhere.

**Architecture:** Detect every terminator reachable from a test case whose
enclosing paragraph — and every intermediate paragraph between it and the
test's target — is reached *exclusively* via plain `PERFORM` (never `GO
TO`, never as a `SECTION` member). Replace the terminator with `MOVE "Y" TO
UT-EARLY-EXIT` + `EXIT PARAGRAPH`. Insert `IF UT-EARLY-EXIT = "Y" EXIT
PARAGRAPH END-IF` immediately after every intermediate `PERFORM` statement
on the safe chain. No `driver.py` restructuring: the existing
`EXPECT`/`VERIFY` checks in `UT-TESTCASE-NNN`, right after `PERFORM
{target}`, run automatically once the flag has propagated all the way back
via ordinary `PERFORM` returns.

**Tech Stack:** Python 3.11+, cobolparser (editable sibling dependency),
GnuCOBOL 3.2 via the `mockymock-cobc` Docker container, pytest
(`tests/unit` no Docker, `tests/integration` `@requires_docker`).

**Design doc:** `docs/2026-07-08-goback-stop-run-support-design.md` — read
it before starting, especially the six-spike verification table. This plan
implements Approach B task-by-task and does not re-derive its reasoning.

## Global Constraints

- The only new refusal code is `UNSUPPORTED_TERMINATOR_LAYOUT` (reused for
  every kind of unsafe shape: `SECTION`-scoped, `GO TO`-reachable,
  non-`PERFORM`-chain-reachable, or line-sharing).
- `STOP RUN GIVING`/`GOBACK RETURNING` return codes are not captured
  anywhere.
- `EXIT PROGRAM` is not a transform target (already confirmed a no-op when
  `PERFORM`ed — see the design doc's original scope-decision spike).
- Out of scope for v1, refused rather than attempted: `SECTION`-scoped
  terminators; an intermediate `PERFORM` nested inside a conditional body;
  any terminator or intermediate paragraph reachable via `GO TO` anywhere
  in the program.
- Every existing test in `tests/unit/` and `tests/integration/` must still
  pass unmodified after each task — every new parameter this plan adds to
  an existing public function has a default that preserves current
  behavior exactly.

---

## Task 1: Classify STOP RUN (RUN-form) / GOBACK — `mock_surface.py`

**Files:**
- Modify: `mockymock/analysis/mock_surface.py`
- Test: `tests/unit/test_mock_surface.py`

**Interfaces:**
- Consumes: `cobolparser.models.statements.control.StopStatement` (`.stop_type`
  — `"RUN"` or `"literal"`; `.location.line`),
  `cobolparser.models.statements.misc.GobackStatement` (`.location.line`).
- Produces: `mockymock.analysis.mock_surface._TERMINATOR_LABELS: frozenset[str]`
  = `{"STOP RUN", "GOBACK"}` — Task 3 imports this. `BoundarySite` entries
  with `category=None`, `label="STOP RUN"` or `label="GOBACK"` appear in
  `MockSurface.boundary_sites` — Task 3 consumes these via
  `surface.boundary_sites`/`surface.sites_in(...)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_mock_surface.py` (append; do not modify existing
content):

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

(The file already imports `parse_cobol` and `analyze` — reuse them, do not
duplicate.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_mock_surface.py -v -k terminator`
Expected: FAIL — `ImportError: cannot import name '_TERMINATOR_LABELS'`.

- [ ] **Step 3: Implement**

In `mockymock/analysis/mock_surface.py`, extend the existing control-statement
import (currently `from cobolparser.models.statements.control import
EvaluateStatement, SearchStatement`):

```python
from cobolparser.models.statements.control import (
    EvaluateStatement,
    SearchStatement,
    StopStatement,
)
```

Extend the existing misc-statement import (currently `CancelStatement,
MergeStatement, ReleaseStatement, ReturnStatement, SortStatement`):

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

Add this constant right after `_SORT_MERGE_TYPES` (around line 168), before
`_BOUNDARY_STATEMENT_TYPES`:

```python
# STOP RUN/GOBACK are detected (category None, like CANCEL/SORT-MERGE) but
# never spliced by directive-matching -- a .cut author never writes a MOCK
# for these; the terminator-support feature neutralizes them automatically
# when found safe (see docs/2026-07-08-goback-stop-run-support-design.md).
# Exported so refusal.py can recognize these labels without duplicating
# the literal set.
_TERMINATOR_LABELS = frozenset({"STOP RUN", "GOBACK"})
```

In `_classify_statement`, add this block immediately after the existing
`CancelStatement` block (after its `return` statement, before the
`ExecSQLStatement` check):

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
Expected: PASS (all tests in the file).

**Step 5 is not optional — do not skip it even though `test_mock_surface.py`
is fully green.** `refusal.py`'s existing `check_test_case` has a catch-all:
any `category=None` `BoundarySite` reachable from a test case that isn't
labeled `"CANCEL"` or `"dynamic CALL"` is unconditionally reported as
`UNSUPPORTED_SORT_MERGE` (`mockymock/analysis/refusal.py`, the `else:`
branch inside `if site.category is None:`, around line 565). Steps 1-4
above just made `"STOP RUN"`/`"GOBACK"` two *new* `category=None` labels —
without this step, every test case whose target reaches one immediately
gets misreported as `UNSUPPORTED_SORT_MERGE` instead of leaving the site
alone for `check_terminator_layout` (Task 3) to evaluate on its own,
merits. Confirmed empirically: skipping this step breaks
`tests/unit/test_cli_docker.py::test_run_neutralizes_entry_linkage_and_reports_it`,
`tests/unit/test_refusal.py::test_per_case_check_expands_perform_thru_range`,
`tests/unit/test_refusal.py::test_per_case_check_follows_perform_of_a_section`,
and `tests/unit/test_refusal_v2.py::test_spliceable_nested_sites_pass_the_gate`
— all four have a reachable `STOP RUN`/`GOBACK` in their fixture and all
four regress without this fix.

- [ ] **Step 5: Write the failing test for the `check_test_case` exclusion**

Add to `tests/unit/test_terminators.py`... but that file doesn't exist
yet (Task 3 creates it) — add this test to `tests/unit/test_mock_surface.py`
instead, since it's a regression guard for *this* task's own consequence,
not terminator-specific detection logic:

```python
from mockymock.analysis.refusal import check_test_case
from mockymock.dsl.model import MockTestCase


def test_reachable_terminator_is_not_misreported_as_sort_merge():
    """check_test_case's category=None catch-all must not fire on the new
    STOP RUN/GOBACK labels -- they are handled separately by
    check_terminator_layout (Task 3), not here."""
    result = parse_cobol(TERMINATOR_SOURCE, filename="termsamp.cbl")
    surface = analyze(result.ast)
    case = MockTestCase(name="c", perform_target="MAIN-PARA")
    reasons = check_test_case(surface, result.ast, case)
    assert not any(r.code == "UNSUPPORTED_SORT_MERGE" for r in reasons)
```

(`TERMINATOR_SOURCE` and `parse_cobol`/`analyze` are already defined/imported
earlier in this file from Step 1 — reuse them, do not redefine.)

- [ ] **Step 6: Run the test to verify it fails**

Run: `python -m pytest tests/unit/test_mock_surface.py -v -k sort_merge`
Expected: FAIL — `AssertionError` (an `UNSUPPORTED_SORT_MERGE` reason is
present).

- [ ] **Step 7: Implement the `check_test_case` exclusion**

In `mockymock/analysis/refusal.py`, extend the existing `mock_surface`
import (currently `BoundarySite, MockSurface, _all_paragraphs,
_find_statements_of_type, normalize_exec_text` — exact names depend on
what's already there, add to whichever import statement already pulls
from `mockymock.analysis.mock_surface`):

```python
from mockymock.analysis.mock_surface import (
    BoundarySite,
    MockSurface,
    _all_paragraphs,
    _find_statements_of_type,
    _TERMINATOR_LABELS,
    normalize_exec_text,
)
```

Locate `check_test_case`'s `category is None` handling (the `if
site.label == "CANCEL": ... elif site.label == "dynamic CALL": ... else:
... UNSUPPORTED_SORT_MERGE ...` chain) and add a new `elif` branch
immediately before the final `else:`:

```python
            elif site.label in _TERMINATOR_LABELS:
                # Handled entirely separately by check_terminator_layout
                # (Task 3, docs/2026-07-08-goback-stop-run-support-design.md)
                # -- not refused here, and deliberately not folded into
                # this function, so a safely-neutralizable terminator
                # doesn't need every OTHER test case in the suite to also
                # satisfy check_test_case's unrelated matching rules.
                pass
            else:
                reasons.append(
                    RefusalReason(
                        code="UNSUPPORTED_SORT_MERGE",
                        message=(
                            f"paragraph '{site.paragraph_name}' (line {site.line}) "
                            f"contains a SORT/MERGE-family statement "
                            f"(SORT/MERGE/RELEASE/RETURN), which mocks an "
                            f"algorithm plus its INPUT/OUTPUT PROCEDURE "
                            f"contract rather than a boundary -- not supported"
                        ),
                    )
                )
```

(Only the new `elif` block is new — the surrounding `if`/`elif "dynamic
CALL"`/`else` structure and the `UNSUPPORTED_SORT_MERGE` body are
unchanged, shown here only so the insertion point is unambiguous.)

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_mock_surface.py -v`
Expected: PASS (all tests in the file, including the new one).

- [ ] **Step 9: Run the full unit suite to confirm the regression is gone**

Run: `python -m pytest tests/unit -q`
Expected: PASS except the one already-known, unrelated pre-existing
failure (`tests/unit/test_source_map.py::test_multiline_call_span_covers_all_three_lines`
— a cobol-parser version-drift issue, confirmed present on `main` before
this plan started; not caused by this task). Specifically, confirm these
four are GREEN again (they must NOT appear in the failures list):
`tests/unit/test_cli_docker.py::test_run_neutralizes_entry_linkage_and_reports_it`,
`tests/unit/test_refusal.py::test_per_case_check_expands_perform_thru_range`,
`tests/unit/test_refusal.py::test_per_case_check_follows_perform_of_a_section`,
`tests/unit/test_refusal_v2.py::test_spliceable_nested_sites_pass_the_gate`.

**Steps 11-14 were added after Task 1's task-review**, which found two more
consequences of the same root cause (introducing two new `category=None`
labels breaks *other* pre-existing code that assumed only `CANCEL`/
`"dynamic CALL"` could be `category=None` besides SORT/MERGE) — do not skip
them either.

- [ ] **Step 11: Fix the lint failure**

Run: `python -m ruff check .` (the exact command CI's required `lint` job
runs). Expected at this point: `I001 Import block is un-sorted or
un-formatted` on `mockymock/analysis/refusal.py` — Step 7's import addition
(`_TERMINATOR_LABELS` inserted into the existing `mockymock.analysis.mock_surface`
import block) isn't in isort's expected order. Fix with `python -m ruff
check --fix mockymock/analysis/refusal.py`, then re-run `python -m ruff
check .` to confirm clean.

- [ ] **Step 12: Fix `generate`'s misleading boundary-report for terminators**

`mockymock/cli/main.py`'s `_report_unsupported_boundaries` (called by
`_cmd_generate`, untouched by Steps 1-10) treats every `category=None`
`BoundarySite` uniformly, printing `"N boundary point(s) detected that are
not mockable (test cases reaching them will be refused)"`. After Step 7's
fix, `STOP RUN`/`GOBACK` sites are `category=None` but are *not*
unconditionally refused anymore — whether a test reaching one is refused
depends on `check_terminator_layout` (Task 3), which `generate` never
calls (it has no specific test case's `perform_target` to evaluate
reachability against — it's scaffolding a `.cut`, not running one). Since
nearly every real COBOL program ends in `STOP RUN`, this would make
`generate` claim "will be refused" for something that frequently won't be,
once Tasks 2-8 land.

Locate `mockymock/cli/main.py`'s `_report_unsupported_boundaries`:

```python
def _report_unsupported_boundaries(surface) -> None:
    """Name every detected boundary point that stays unmockable (the
    SORT/MERGE family, identifier-less dynamic CALLs, unspliceable nested
    sites), so the scaffold is never mistaken for complete coverage of the
    program's outputs. Test cases whose PERFORM target reaches one of
    these are refused by `run`."""
    findings: list[str] = []
    for site in surface.boundary_sites:
        if site.category is None:
            findings.append(
                f"{site.label} in paragraph '{site.paragraph_name}' "
                f"(line {site.line})"
            )
        elif site.nested and site.span is None:
            findings.append(
                f"nested {site.label} in paragraph '{site.paragraph_name}' "
                f"(line {site.line}) -- {site.unspliceable_reason}"
            )
    if not findings:
        return
    print(
        f"mockymock generate: {len(findings)} boundary point(s) detected that "
        f"are not mockable (test cases reaching them will be refused):"
    )
    for finding in findings:
        print(f"  - {finding}")
```

Replace it with (splits terminator sites into their own, honestly-worded
report rather than folding them into the unconditional "will be refused"
list):

```python
def _report_unsupported_boundaries(surface) -> None:
    """Name every detected boundary point that stays unmockable (the
    SORT/MERGE family, identifier-less dynamic CALLs, unspliceable nested
    sites), so the scaffold is never mistaken for complete coverage of the
    program's outputs. Test cases whose PERFORM target reaches one of
    these are refused by `run`.

    STOP RUN/GOBACK sites are reported separately and more cautiously:
    unlike the other category=None labels, `run` does not always refuse a
    test case reaching one -- check_terminator_layout (see
    docs/2026-07-08-goback-stop-run-support-design.md) may find it safe.
    `generate` has no specific test case's PERFORM target to evaluate
    reachability against, so it cannot know which outcome a future `.cut`
    will get -- claiming "will be refused" here would be wrong as often as
    it's right.
    """
    findings: list[str] = []
    terminator_findings: list[str] = []
    for site in surface.boundary_sites:
        if site.category is None:
            if site.label in _TERMINATOR_LABELS:
                terminator_findings.append(
                    f"{site.label} in paragraph '{site.paragraph_name}' "
                    f"(line {site.line})"
                )
            else:
                findings.append(
                    f"{site.label} in paragraph '{site.paragraph_name}' "
                    f"(line {site.line})"
                )
        elif site.nested and site.span is None:
            findings.append(
                f"nested {site.label} in paragraph '{site.paragraph_name}' "
                f"(line {site.line}) -- {site.unspliceable_reason}"
            )
    if findings:
        print(
            f"mockymock generate: {len(findings)} boundary point(s) detected "
            f"that are not mockable (test cases reaching them will be "
            f"refused):"
        )
        for finding in findings:
            print(f"  - {finding}")
    if terminator_findings:
        print(
            f"mockymock generate: {len(terminator_findings)} STOP RUN/GOBACK "
            f"site(s) detected -- whether a test case reaching one is "
            f"refused depends on how it's reached; see "
            f"docs/2026-07-08-goback-stop-run-support-design.md:"
        )
        for finding in terminator_findings:
            print(f"  - {finding}")
```

Add this import to `mockymock/cli/main.py`'s existing `mockymock.analysis.mock_surface`
import (check the exact current import statement first — it's a
function-local import inside `_cmd_generate`/`_cmd_run`, not a top-level
one, per this file's existing style; add `_TERMINATOR_LABELS` to whichever
one already imports from `mockymock.analysis.mock_surface`, or add a new
function-local import line next to it if none currently does):

```python
    from mockymock.analysis.mock_surface import _TERMINATOR_LABELS
```

- [ ] **Step 13: Write a regression test and run it**

Add to `tests/unit/test_cli.py` (check the file's existing imports/helpers
first and reuse them — this codebase's CLI tests typically invoke `main()`
directly and capture stdout via `capsys`, matching the pattern already
used elsewhere in that file):

```python
def test_generate_reports_terminators_separately_from_unmockable(tmp_path, capsys):
    cbl = tmp_path / "TERMDEMO.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TERMDEMO.\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        "           STOP RUN.\n"
    )
    exit_code = main(["generate", str(cbl)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "STOP RUN/GOBACK site(s) detected" in out
    assert "will be refused" not in out
```

Run: `python -m pytest tests/unit/test_cli.py -v -k terminator` — expect
FAIL before Step 12's implementation (old message says "will be refused"
unconditionally), PASS after.

- [ ] **Step 14: Run tests and lint to verify everything passes**

Run: `python -m pytest tests/unit -q` — expect the same result as Step 9
(only the one known pre-existing failure) plus the new test from Step 13
passing.
Run: `python -m ruff check .` — expect clean (confirms Step 11's fix
holds after Step 12's edit).

- [ ] **Step 15: Commit**

```bash
git add mockymock/analysis/mock_surface.py mockymock/analysis/refusal.py \
    mockymock/cli/main.py tests/unit/test_mock_surface.py tests/unit/test_cli.py
git commit -m "feat(analysis): classify STOP RUN/GOBACK as detected terminator sites

Part of GOBACK/STOP RUN support, Approach B
(docs/2026-07-08-goback-stop-run-support-design.md). Category=None,
matching the existing CANCEL/SORT-MERGE detected-but-unmockable pattern.
STOP <literal> (a console message, not a terminator) is excluded.

Also excludes the two new labels from check_test_case's existing
category=None catch-all (previously only CANCEL/dynamic-CALL were
excluded; anything else was reported as UNSUPPORTED_SORT_MERGE) --
without this, every test case reaching a terminator would be misreported
as SORT/MERGE-family instead of being left for check_terminator_layout
(Task 3) to evaluate. Confirmed via 4 previously-passing tests that
regressed without this fix and are green again with it.

Also fixes generate's boundary-point report, which had the identical
problem one layer up: it unconditionally called every category=None site
"not mockable ... will be refused," which is no longer true for
terminators. Terminator sites now get their own, honestly-worded report.

Also fixes a ruff import-order lint failure introduced by the
check_test_case fix's import addition."
```

---

## Task 2: Whole-program GO TO targets + plain-PERFORM-only reachability + terminator span validation

**Files:**
- Modify: `mockymock/analysis/refusal.py`
- Modify: `mockymock/splicer/source_map.py`
- Test: Create `tests/unit/test_terminator_reachability.py`
- Test: `tests/unit/test_source_map.py`

**Interfaces:**
- Consumes: `cobolparser.models.statements.control.PerformStatement`
  (`.target_paragraph`, `.thru_paragraph`, `.location.line`),
  `cobolparser.models.statements.control.GoStatement` (`.target_paragraphs`,
  `.target_paragraph`) — both already imported in `refusal.py`.
  `mockymock.analysis.mock_surface._TERMINATOR_LABELS` (Task 1).
- Produces: `mockymock.analysis.refusal._go_to_targets(program) -> set[str]`
  and `mockymock.analysis.refusal._plain_perform_edges_from(program, start:
  str) -> tuple[set[str], list]` (the list is `list[PerformStatement]`) —
  Task 3 imports and calls both. Also: `annotate_nested_sites` (existing,
  in `source_map.py`) now ALSO validates terminator-labeled `BoundarySite`s
  (previously skipped entirely, like every other `category=None` site) —
  Task 3's `find_terminator_plans` reads the resulting `site.span`/
  `site.unspliceable_reason` fields directly, the same way
  `check_test_case`/`check_nested_exec` already do for mocked boundaries.

**Why this task also touches `annotate_nested_sites`:** Approach B's
terminator replacement is a `comment_and_replace` span splice, exactly
like every other boundary replacement — which means it needs the exact
same "does this statement own its line(s)" validation every other
boundary site already gets, or a terminator sharing its line with sibling
code (or nested somewhere `annotate_nested_sites` can't safely compute a
span for) would corrupt that sibling code when spliced. This is the same
fix Approach A's design needed for the same reason — restoring it here.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_terminator_reachability.py`:

```python
"""Unit tests for the two new reachability primitives Approach B's
safe-chain check depends on: which paragraphs are EVER a GO TO target
anywhere in the program, and which paragraphs are reachable from a given
start paragraph via ONLY plain, unconditional, top-level PERFORM
statements. See docs/2026-07-08-goback-stop-run-support-design.md.
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
    assert {e.target_paragraph for e in edges} == {"LEVEL1-PARA", "LEVEL2-PARA"}


def test_plain_perform_edges_from_ignores_thru_and_conditional_and_goto():
    """THRU-CALLER's PERFORM...THRU, CONDITIONAL-CALLER's nested PERFORM,
    and UNRELATED-PARA's GO TO must never contribute edges -- none of them
    are plain, unconditional, top-level PERFORM statements."""
    seen, edges = _plain_perform_edges_from(_program(), "THRU-CALLER")
    assert seen == {"THRU-CALLER"}
    assert edges == []

    seen, edges = _plain_perform_edges_from(_program(), "CONDITIONAL-CALLER")
    assert seen == {"CONDITIONAL-CALLER"}
    assert edges == []

    seen, edges = _plain_perform_edges_from(_program(), "UNRELATED-PARA")
    assert seen == {"UNRELATED-PARA"}
    assert edges == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_terminator_reachability.py -v`
Expected: FAIL — `ImportError: cannot import name '_go_to_targets'`.

- [ ] **Step 3: Implement**

In `mockymock/analysis/refusal.py`, add these two functions after
`_reachable_paragraphs` (end of file):

```python
def _go_to_targets(program) -> set[str]:
    """Every paragraph/section name that is EVER a GO TO target anywhere
    in the whole program, regardless of reachability from any one test
    case -- a categorical, whole-program exclusion list.

    A paragraph that could ever be entered via GO TO cannot safely use
    EXIT PARAGRAPH/EXIT SECTION for early-exit propagation: verified
    empirically (docs/2026-07-08-goback-stop-run-support-design.md, spike
    #4) that EXIT PARAGRAPH silently fails to return to the correct
    caller when the paragraph it's issued from was entered via GO TO
    rather than PERFORM -- execution just stops, no crash, no return,
    the caller's checks never run."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set()
    targets: set[str] = set()
    for paragraph in _all_paragraphs(procedure):
        for statement in _find_statements_of_type(paragraph.statements, GoStatement):
            targets.update(statement.target_paragraphs)
            if statement.target_paragraph:
                targets.add(statement.target_paragraph)
    return targets


def _plain_perform_edges_from(program, start: str) -> tuple[set[str], list]:
    """BFS from `start` following ONLY plain (non-THRU), unconditional,
    top-level PERFORM statements -- i.e. PerformStatement nodes that are
    direct members of a paragraph's own `.statements` list (not nested
    inside IF/EVALUATE), with `thru_paragraph is None`.

    SECTION members are excluded entirely: this only looks up names in
    `procedure.paragraphs` (top-level paragraphs), never
    `procedure._sections[...].paragraphs` -- a paragraph that only exists
    as a section member is an unreachable dead end here, naturally
    refusing any chain that would need to pass through one (SECTION
    support is deferred -- see the design doc).

    Returns (reachable paragraph names via this restricted edge set, the
    PerformStatement objects that ARE those edges) -- every one of those
    statements is a candidate for the early-exit flag-check
    instrumentation. Deliberately NOT the same as `_reachable_paragraphs`:
    that function also follows GO TO and section/THRU fall-through edges,
    exactly the unsafe shapes this restricted variant must exclude."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set(), []
    by_name = {p.paragraph_name: p for p in procedure.paragraphs}
    seen = {start}
    stack = [start]
    edges: list = []
    while stack:
        name = stack.pop()
        paragraph = by_name.get(name)
        if paragraph is None:
            continue
        for statement in paragraph.statements:
            if (
                isinstance(statement, PerformStatement)
                and statement.thru_paragraph is None
                and statement.target_paragraph
            ):
                edges.append(statement)
                target = statement.target_paragraph
                if target not in seen:
                    seen.add(target)
                    stack.append(target)
    return seen, edges
```

(`PerformStatement`/`GoStatement` are already imported at the top of
`refusal.py`: `from cobolparser.models.statements.control import
GoStatement, PerformStatement`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_terminator_reachability.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Write the failing test for the `annotate_nested_sites` broadening**

Add to `tests/unit/test_source_map.py` (append; reuse the file's existing
`parse_cobol`, `normalize_fixed_format`, `analyze`, `annotate_nested_sites`,
`collect_scope_map` imports):

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

- [ ] **Step 6: Run the test to verify it fails**

Run: `python -m pytest tests/unit/test_source_map.py -v -k terminator`
Expected: FAIL — `annotate_nested_sites` currently skips every
`category is None` site unconditionally, so `site.unspliceable_reason`
stays `None` even for the shared-line fixture.

- [ ] **Step 7: Implement the `annotate_nested_sites` broadening**

In `mockymock/splicer/source_map.py`, extend the existing `mock_surface`
import:

```python
from mockymock.analysis.mock_surface import (
    BoundarySite,
    MockSurface,
    _nested_statement_lists,
    _TERMINATOR_LABELS,
)
```

Change `annotate_nested_sites`'s loop condition (currently `if site.category
is None: continue`):

```python
def annotate_nested_sites(
    surface: MockSurface, scope_map: ScopeMap, lines: list[str]
) -> None:
    """... (existing docstring, add one sentence:) Also validates STOP
    RUN/GOBACK terminator sites (category None, but not skipped like other
    detected-but-unmockable categories) through the identical rules -- see
    docs/2026-07-08-goback-stop-run-support-design.md."""
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

- [ ] **Step 8: Write the failing test for `statement_top_level_problem`**

Add to `tests/unit/test_source_map.py` (append):

```python
PERFORM_OWN_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERFORMOWNLINE.

       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM SUB-PARA.
           DISPLAY "AFTER".

       SUB-PARA.
           DISPLAY "SUB".
"""

PERFORM_SHARED_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERFORMSHARE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC 9.

       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A PERFORM SUB-PARA.

       SUB-PARA.
           DISPLAY "SUB".
"""


def _find_perform(program, paragraph_name):
    procedure = program.get_division("PROCEDURE")
    paragraph = next(
        p for p in procedure.paragraphs if p.paragraph_name == paragraph_name
    )
    return paragraph.statements[0]


def test_statement_top_level_problem_none_when_perform_owns_its_line():
    result = parse_cobol(PERFORM_OWN_LINE_SOURCE, filename="x.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(PERFORM_OWN_LINE_SOURCE.splitlines()).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    perform = _find_perform(result.ast, "MAIN-PARA")
    assert statement_top_level_problem(perform, scope_map, lines) is None


def test_statement_top_level_problem_set_when_perform_shares_its_line():
    result = parse_cobol(PERFORM_SHARED_LINE_SOURCE, filename="x.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(PERFORM_SHARED_LINE_SOURCE.splitlines()).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    perform = _find_perform(result.ast, "MAIN-PARA")
    assert (
        statement_top_level_problem(perform, scope_map, lines)
        == "does not start its own line"
    )
```

Add this import at the top of `tests/unit/test_source_map.py` if not already
present (check first — the file may already import some of these from the
earlier steps in this task): `from mockymock.splicer.source_map import
collect_scope_map, statement_top_level_problem`.

- [ ] **Step 9: Run the test to verify it fails**

Run: `python -m pytest tests/unit/test_source_map.py -v -k top_level_problem`
Expected: FAIL — `ImportError: cannot import name 'statement_top_level_problem'`.

- [ ] **Step 10: Implement `statement_top_level_problem`**

In `mockymock/splicer/source_map.py`, locate `_top_level_site_problem`
(the existing function, whose body extracts `statement = cast(ASTNode,
site.statement)` then operates on `statement`/`start`/`column`):

```python
def _top_level_site_problem(
    site: BoundarySite, scope_map: ScopeMap, lines: list[str]
) -> str | None:
    """..."""  # existing docstring, unchanged
    statement = cast(ASTNode, site.statement)
    start = statement.location.line
    column = statement.location.column
    if lines[start - 1][: column - 1].strip():
        return "does not start its own line"
    if any(
        b.top_level and b.line == start and b.column != column
        for b in scope_map.boundaries
    ):
        return "shares its line with another statement or paragraph header"
    return None
```

Replace it with a one-line wrapper plus the factored-out, statement-level
function:

```python
def _top_level_site_problem(
    site: BoundarySite, scope_map: ScopeMap, lines: list[str]
) -> str | None:
    """..."""  # existing docstring, unchanged
    return statement_top_level_problem(cast(ASTNode, site.statement), scope_map, lines)


def statement_top_level_problem(
    statement, scope_map: ScopeMap, lines: list[str]
) -> str | None:
    """The reason a top-level STATEMENT's whole-line splice/insertion
    would corrupt sibling code, or None when it owns its line -- the same
    check `_top_level_site_problem` applies to BoundarySites, factored out
    so it can also be applied directly to a PerformStatement (which is
    never wrapped in a BoundarySite; used by
    refusal.find_terminator_plans to validate each intermediate PERFORM
    on a safe chain before it's cleared for the
    stub_writer.insert_lines_after early-exit-check instrumentation). See
    _top_level_site_problem's docstring for the exact rules; this is that
    function's body, unchanged, operating on `statement` directly instead
    of `site.statement`."""
    start = statement.location.line
    column = statement.location.column
    if lines[start - 1][: column - 1].strip():
        return "does not start its own line"
    if any(
        b.top_level and b.line == start and b.column != column
        for b in scope_map.boundaries
    ):
        return "shares its line with another statement or paragraph header"
    return None
```

- [ ] **Step 11: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_source_map.py tests/unit/test_terminator_reachability.py -v`
Expected: PASS (every test in both files).

- [ ] **Step 12: Run the full unit suite to confirm no regression**

Run: `python -m pytest tests/unit -q`
Expected: PASS, same count as baseline plus the new tests from this task
(CANCEL/SORT-MERGE/unresolved-dynamic-CALL sites are unaffected — their
`label` is never in `_TERMINATOR_LABELS`; the `_top_level_site_problem`
refactor must be behavior-preserving — every existing test that exercises
it, e.g. `test_orchestrator.py`'s shared-line tests, must still pass
unchanged).

- [ ] **Step 13: Commit**

```bash
git add mockymock/analysis/refusal.py mockymock/splicer/source_map.py \
    tests/unit/test_terminator_reachability.py tests/unit/test_source_map.py
git commit -m "feat: add terminator reachability primitives + span/line validation

Part of GOBACK/STOP RUN support, Approach B
(docs/2026-07-08-goback-stop-run-support-design.md). Two new refusal.py
primitives the safe-chain terminator check builds on: _go_to_targets
(whole-program, categorical) and _plain_perform_edges_from (restricted
BFS -- only plain, unconditional, top-level, non-THRU PERFORM edges).
annotate_nested_sites now also validates terminator-labeled sites through
the same top-level own-line guard / nested-span machinery every other
boundary site already goes through. statement_top_level_problem factors
that same guard into a form reusable for a bare PerformStatement, needed
to validate intermediate PERFORM statements before instrumenting them.
Both are pure refactors of existing logic plus additive changes -- no
existing behavior changes for any other category=None site or any
existing BoundarySite check."
```

---

## Task 3: Safe-chain terminator detection + refusal — `refusal.py`

**Files:**
- Modify: `mockymock/analysis/refusal.py`
- Test: Create `tests/unit/test_terminators.py`

**Interfaces:**
- Consumes: `_go_to_targets`, `_plain_perform_edges_from`, the broadened
  `annotate_nested_sites` (Task 2 — MUST have already run on `surface`
  before calling `find_terminator_plans`/`check_terminator_layout`, same
  precondition as `check_test_case`/`check_nested_exec`, so `site.span`/
  `site.unspliceable_reason` are populated), `_reachable_paragraphs`
  (existing), `MockSurface.sites_in` (existing), `_TERMINATOR_LABELS`
  (Task 1).
- Produces: `mockymock.analysis.refusal.TerminatorPlan` (dataclass:
  `site: BoundarySite`, `chain_performs: list` — deduped
  `list[PerformStatement]` needing the flag-check instrumentation),
  `find_terminator_plans(surface, program, suite) -> tuple[list[TerminatorPlan],
  list[RefusalReason]]`, `check_terminator_layout(surface, program, suite)
  -> list[RefusalReason]` (thin wrapper: `find_terminator_plans(...)[1]`).
  Task 6 imports `TerminatorPlan`/`find_terminator_plans`; Task 8 (CLI)
  imports `check_terminator_layout`/`find_terminator_plans`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_terminators.py`:

```python
"""Unit tests for Approach B's safe-chain terminator detection
(docs/2026-07-08-goback-stop-run-support-design.md). Mirrors
tests/unit/test_linkage.py's structure: the analysis functions and the
refusal wrapper are tested together since they're always used together.
"""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import (
    check_terminator_layout,
    find_terminator_plans,
)
from mockymock.dsl.model import MockTestCase, MockTestSuite
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

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

CHAIN_SHARED_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CHAINSHARE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC 9.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           MOVE 1 TO WS-A PERFORM 1000-WRAPPER.

       1000-WRAPPER.
           STOP RUN.
"""

SAFE_CHAIN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAFECHAIN.

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

GO_TO_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOUNSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK
           STOP RUN.

       1000-DO-WORK.
           DISPLAY "WORK".

       1000-DO-WORK-ALIAS.
           GO TO 1000-DO-WORK.
"""

SECTION_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTUNSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-SECTION
           STOP RUN.

       1000-SECTION SECTION.
       1000-DO-WORK.
           DISPLAY "WORK".
"""


def _analyze(source, name="X.cbl"):
    """Returns (program, surface, scope_map, lines) -- find_terminator_plans
    needs all four: program/surface for the reachability walk,
    scope_map/lines to validate each intermediate PERFORM's line ownership
    via statement_top_level_problem."""
    result = parse_cobol(source, filename=name)
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    return result.ast, surface, scope_map, lines


def _suite(perform_target="0000-MAIN-PROCESS"):
    case = MockTestCase(name="c", perform_target=perform_target)
    return MockTestSuite(name="S", test_cases=[case])


def test_find_terminator_plans_accepts_a_safe_plain_perform_chain():
    program, surface, scope_map, lines = _analyze(SAFE_CHAIN_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert plans[0].site.label == "STOP RUN"
    assert plans[0].site.paragraph_name == "0000-MAIN-PROCESS"
    assert plans[0].chain_performs == []  # terminator is directly in the target paragraph


def test_find_terminator_plans_empty_when_unreachable():
    program, surface, scope_map, lines = _analyze(SAFE_CHAIN_SOURCE)
    suite = _suite(perform_target="1000-DO-WORK")
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert plans == []
    assert reasons == []


def test_find_terminator_plans_includes_intermediate_perform_in_chain():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWOLEVEL.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-WRAPPER.

       1000-WRAPPER.
           PERFORM 2000-INNER.

       2000-INNER.
           STOP RUN.
"""
    program, surface, scope_map, lines = _analyze(source)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    # both PERFORM 1000-WRAPPER and PERFORM 2000-INNER are on the chain
    assert {p.target_paragraph for p in plans[0].chain_performs} == {
        "1000-WRAPPER",
        "2000-INNER",
    }


def test_go_to_reachable_terminator_refuses():
    program, surface, scope_map, lines = _analyze(GO_TO_UNSAFE_SOURCE)
    suite = _suite()
    suite.test_cases[0].perform_target = "1000-DO-WORK-ALIAS"
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "GO TO" in reasons[0].message


def test_go_to_target_refuses_even_when_a_different_case_uses_it_safely():
    """1000-DO-WORK is safely PERFORM-reachable from case "safe", but it is
    ALSO a GO TO target somewhere in the program (via 1000-DO-WORK-ALIAS) --
    per the design doc this refuses unconditionally, not just for the case
    that actually takes the GO TO path."""
    program, surface, scope_map, lines = _analyze(GO_TO_UNSAFE_SOURCE)
    suite = MockTestSuite(
        name="S",
        test_cases=[MockTestCase(name="safe", perform_target="0000-MAIN-PROCESS")],
    )
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"


def test_section_scoped_terminator_refuses():
    program, surface, scope_map, lines = _analyze(SECTION_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "SECTION" in reasons[0].message


def test_terminator_sharing_its_line_refuses():
    """Complements Task 2's direct source_map.py test: here the same
    shared-line shape is checked through the full find_terminator_plans
    path, proving the span-validation wiring actually runs."""
    program, surface, scope_map, lines = _analyze(SHARED_LINE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "does not start its own line" in reasons[0].message


def test_intermediate_perform_sharing_its_line_refuses():
    """The terminator itself (STOP RUN in 1000-WRAPPER) is perfectly safe
    on its own -- the problem is the intermediate PERFORM 1000-WRAPPER in
    0000-MAIN-PROCESS sharing its line with a MOVE. Proves
    statement_top_level_problem is actually being called against
    chain_performs, not just built and left unused."""
    program, surface, scope_map, lines = _analyze(CHAIN_SHARED_LINE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "does not start its own line" in reasons[0].message


def test_check_terminator_layout_is_reasons_only():
    program, surface, scope_map, lines = _analyze(SAFE_CHAIN_SOURCE)
    assert check_terminator_layout(surface, program, _suite(), scope_map, lines) == []

    program, surface, scope_map, lines = _analyze(SECTION_UNSAFE_SOURCE)
    reasons = check_terminator_layout(surface, program, _suite(), scope_map, lines)
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_terminators.py -v`
Expected: FAIL — `ImportError: cannot import name 'find_terminator_plans'`.

- [ ] **Step 3: Implement**

In `mockymock/analysis/refusal.py`, add this dataclass near the top,
alongside `RefusalReason` (after its definition):

```python
@dataclass
class TerminatorPlan:
    """One physical STOP RUN(RUN-form)/GOBACK statement found safe to
    neutralize, plus every intermediate PERFORM statement (deduped across
    the whole suite by identity) that needs the early-exit flag-check
    inserted after it for this terminator's propagation to correctly
    reach the test driver. Empty `chain_performs` means the terminator
    sits directly in a test's own PERFORM target -- no intermediate
    instrumentation needed. See
    docs/2026-07-08-goback-stop-run-support-design.md."""

    site: BoundarySite
    chain_performs: list = field(default_factory=list)
```

(`field` needs importing: change `from dataclasses import dataclass` to
`from dataclasses import dataclass, field`.)

Add these two functions after `_plain_perform_edges_from` (end of file):

```python
def find_terminator_plans(
    surface: MockSurface,
    program,
    suite: MockTestSuite,
    scope_map,
    lines: list[str],
) -> tuple[list[TerminatorPlan], list[RefusalReason]]:
    """For every STOP RUN(RUN-form)/GOBACK reachable from at least one test
    case, decide whether it is safely neutralizable and return either a
    TerminatorPlan or an UNSUPPORTED_TERMINATOR_LAYOUT RefusalReason --
    never both for the same physical statement. Sites unreachable from
    every test case are omitted entirely (left untouched, like any other
    unmocked boundary).

    Safe means: the terminator's enclosing paragraph is a top-level
    paragraph (not a SECTION member), is never a GO TO target anywhere in
    the whole program, is reachable from the test's own perform_target via
    `_plain_perform_edges_from` (a chain of nothing but plain,
    unconditional, top-level PERFORM statements), the terminator's own
    statement owns its line/has a validated span (`site.span`/
    `site.unspliceable_reason`, populated by a broadened
    `annotate_nested_sites` call the caller must have already made), and
    every intermediate PERFORM on the case's restricted-reachable chain
    also owns its own line (`statement_top_level_problem`, checked once
    per case since the same chain_performs set is a candidate for every
    terminator that case reaches -- see the design doc's "over-inclusive
    instrumentation is fine" rationale). Once ANY test case finds a given
    terminator unsafe, it is refused permanently -- fail-closed,
    regardless of what other test cases' paths say. `scope_map`/`lines`
    must be the same `collect_scope_map(program, lines)` result and
    normalized lines the caller already computed for
    `annotate_nested_sites`."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return [], []

    top_level_names = {p.paragraph_name for p in procedure.paragraphs}
    go_to_targets = _go_to_targets(program)
    terminator_sites = {
        id(s.statement): s
        for s in surface.boundary_sites
        if s.category is None and s.label in _TERMINATOR_LABELS
    }

    plans_by_statement: dict[int, TerminatorPlan] = {}
    reasons: list[RefusalReason] = []
    refused_statement_ids: set[int] = set()

    for case in suite.test_cases:
        reachable, _ = _reachable_paragraphs(
            program, case.perform_target, case.perform_thru
        )
        safe_names, chain_performs = _plain_perform_edges_from(
            program, case.perform_target
        )

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

        qualified_keys: list[int] = []

        for site in surface.sites_in(reachable):
            key = id(site.statement)
            if key not in terminator_sites or key in refused_statement_ids:
                continue

            paragraph_name = site.paragraph_name
            problem = None
            if paragraph_name not in top_level_names:
                problem = (
                    "is inside a paragraph that belongs to a SECTION -- "
                    "SECTION-scoped terminators are not yet supported"
                )
            elif paragraph_name in go_to_targets:
                problem = (
                    "is reachable via GO TO somewhere in this program -- "
                    "the early-exit propagation mechanism (EXIT PARAGRAPH) "
                    "only works correctly when a paragraph is entered "
                    "exclusively via PERFORM"
                )
            elif paragraph_name not in safe_names:
                problem = (
                    f"is reachable from '{case.perform_target}' but not via "
                    f"a chain of plain, unconditional, top-level PERFORM "
                    f"statements -- this is the only shape this feature can "
                    f"safely neutralize today"
                )
            elif site.nested and site.span is None:
                problem = (
                    f"is nested inside a conditional/loop body and cannot "
                    f"be safely spliced: "
                    f"{site.unspliceable_reason or _UNANNOTATED}"
                )
            elif not site.nested and site.unspliceable_reason:
                problem = (
                    f"{site.unspliceable_reason} -- splicing it would "
                    f"corrupt sibling code sharing its line(s)"
                )
            elif chain_problem is not None:
                problem = chain_problem

            if problem is not None:
                reasons.append(
                    RefusalReason(
                        code="UNSUPPORTED_TERMINATOR_LAYOUT",
                        message=(
                            f"{site.label} at line {site.line} (paragraph "
                            f"'{paragraph_name}') {problem}"
                        ),
                    )
                )
                refused_statement_ids.add(key)
                plans_by_statement.pop(key, None)
                continue

            if key not in plans_by_statement:
                plans_by_statement[key] = TerminatorPlan(site=terminator_sites[key])
            qualified_keys.append(key)

        for key in qualified_keys:
            plan = plans_by_statement[key]
            existing_ids = {id(p) for p in plan.chain_performs}
            for perform in chain_performs:
                if id(perform) not in existing_ids:
                    plan.chain_performs.append(perform)
                    existing_ids.add(id(perform))

    return list(plans_by_statement.values()), reasons


def check_terminator_layout(
    surface: MockSurface,
    program,
    suite: MockTestSuite,
    scope_map,
    lines: list[str],
) -> list[RefusalReason]:
    """Thin wrapper over find_terminator_plans for the CLI's refusal-gate
    loop, which only needs the refusal reasons, not the plans themselves
    (the plans are recomputed again right before splicing -- see the CLI
    wiring task -- matching this codebase's existing pattern of computing
    a cheap, pure "plan" twice rather than threading it through every
    caller, e.g. analysis.linkage.linkage_plan)."""
    return find_terminator_plans(surface, program, suite, scope_map, lines)[1]
```

Also add this import at the top of `mockymock/analysis/refusal.py`, alongside
the existing `mockymock.analysis.mock_surface` import block:

```python
from mockymock.splicer.source_map import statement_top_level_problem
```

This is a deliberate cross-layer import (`analysis` importing from
`splicer`) — the reverse of this codebase's usual direction. It's safe (no
circular import: `source_map.py` only imports from `mock_surface.py` and
`dsl.model`, never from `refusal.py`) and avoids duplicating
`statement_top_level_problem`'s logic rather than crossing the layering
boundary; the alternative (reimplementing the same check in `refusal.py`)
would create two copies of the same rule to keep in sync.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_terminators.py -v`
Expected: PASS (all 9 tests).

- [ ] **Step 5: Run the full unit suite to confirm no regression**

Run: `python -m pytest tests/unit -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mockymock/analysis/refusal.py tests/unit/test_terminators.py
git commit -m "feat(analysis): safe-chain terminator detection + UNSUPPORTED_TERMINATOR_LAYOUT

Part of GOBACK/STOP RUN support, Approach B
(docs/2026-07-08-goback-stop-run-support-design.md). find_terminator_plans
combines the Task 2 primitives into the full safety check (top-level,
never a GO TO target, plain-PERFORM-chain-reachable) and collects the
deduped set of intermediate PERFORM statements each safe terminator needs
instrumented. check_terminator_layout is the CLI-facing refusal wrapper."
```

---

## Task 4: `insert_lines_after` — `stub_writer.py`

**Files:**
- Modify: `mockymock/splicer/stub_writer.py`
- Test: `tests/unit/test_stub_writer.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `insert_lines_after(lines: list[str], line_number: int, new_lines:
  list[str]) -> list[str]`. Task 5 calls this for intermediate-`PERFORM`
  instrumentation.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_stub_writer.py` (append; if the file doesn't exist
yet, check first with `ls tests/unit/test_stub_writer.py` — it does exist
per this repo's test suite, reuse its existing imports):

```python
from mockymock.splicer.stub_writer import insert_lines_after


def test_insert_lines_after_leaves_original_lines_untouched():
    lines = ["AAA", "BBB", "CCC"]
    result = insert_lines_after(lines, 2, ["NEW1", "NEW2"])
    assert result == ["AAA", "BBB", "NEW1", "NEW2", "CCC"]
    assert lines == ["AAA", "BBB", "CCC"]  # original list not mutated


def test_insert_lines_after_at_end_of_file():
    lines = ["AAA", "BBB"]
    result = insert_lines_after(lines, 2, ["NEW"])
    assert result == ["AAA", "BBB", "NEW"]


def test_insert_lines_after_no_new_lines_is_a_no_op():
    lines = ["AAA", "BBB"]
    assert insert_lines_after(lines, 1, []) == ["AAA", "BBB"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_stub_writer.py -v -k insert_lines_after`
Expected: FAIL — `ImportError: cannot import name 'insert_lines_after'`.

- [ ] **Step 3: Implement**

In `mockymock/splicer/stub_writer.py`, add after `comment_and_replace`:

```python
def insert_lines_after(
    lines: list[str], line_number: int, new_lines: list[str]
) -> list[str]:
    """Return a NEW list with `new_lines` inserted immediately after
    `line_number` (1-indexed). Unlike comment_and_replace, this NEVER
    touches the original line(s) -- used when an existing statement must
    stay exactly as written and something new just needs to run right
    after it (see docs/2026-07-08-goback-stop-run-support-design.md, the
    intermediate-PERFORM early-exit flag-check instrumentation)."""
    return lines[:line_number] + new_lines + lines[line_number:]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_stub_writer.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/stub_writer.py tests/unit/test_stub_writer.py
git commit -m "feat(splicer): add insert_lines_after primitive

Part of GOBACK/STOP RUN support, Approach B
(docs/2026-07-08-goback-stop-run-support-design.md). Unlike
comment_and_replace, preserves the original line(s) verbatim -- needed
for inserting an early-exit flag-check after an existing PERFORM
statement without touching the PERFORM itself."
```

---

## Task 5: Dispatch-block builders — `injector.py`

**Files:**
- Modify: `mockymock/splicer/injector.py`
- Test: `tests/unit/test_injector.py`

**Interfaces:**
- Consumes: nothing new from earlier tasks (pure codegen).
- Produces: `injector.build_terminator_neutralization() -> list[str]`,
  `injector.build_chain_check() -> list[str]` (both parameterless — see
  below for why). Task 6 imports both.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_injector.py` (append):

```python
from mockymock.splicer.injector import build_chain_check, build_terminator_neutralization


def test_terminator_neutralization_sets_flag_and_exits_paragraph():
    lines = build_terminator_neutralization()
    assert lines == [
        '           MOVE "Y" TO UT-EARLY-EXIT',
        "           EXIT PARAGRAPH",
    ]


def test_chain_check_exits_paragraph_when_flag_set():
    lines = build_chain_check()
    assert lines == [
        '           IF UT-EARLY-EXIT = "Y"',
        "               EXIT PARAGRAPH",
        "           END-IF",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_injector.py -v -k "terminator_neutralization or chain_check"`
Expected: FAIL — `ImportError`s for the not-yet-defined names.

- [ ] **Step 3: Implement**

In `mockymock/splicer/injector.py`, add after `build_exec_trap`:

```python
def build_terminator_neutralization() -> list[str]:
    """Replacement for a STOP RUN/GOBACK statement found safe to
    neutralize (see docs/2026-07-08-goback-stop-run-support-design.md):
    set the early-exit flag and return via EXIT PARAGRAPH -- never GO TO,
    since EXIT PARAGRAPH is the only mechanism verified to correctly
    resume the real PERFORM caller. Identical regardless of which test
    case is running -- unlike build_site_dispatch, no per-case EVALUATE
    UT-CURRENT-CASE dispatch is needed here."""
    return [
        '           MOVE "Y" TO UT-EARLY-EXIT',
        "           EXIT PARAGRAPH",
    ]


def build_chain_check() -> list[str]:
    """Inserted immediately after an intermediate PERFORM statement lying
    on a safe chain toward a neutralized terminator: if the flag is set,
    stop this paragraph too instead of running whatever sibling code
    follows -- propagating the early exit one more level toward the test
    driver. Identical every time it's used; no parameters needed."""
    return [
        '           IF UT-EARLY-EXIT = "Y"',
        "               EXIT PARAGRAPH",
        "           END-IF",
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_injector.py -v`
Expected: PASS (every test in the file).

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/injector.py tests/unit/test_injector.py
git commit -m "feat(splicer): terminator neutralization + chain-check codegen

Part of GOBACK/STOP RUN support, Approach B
(docs/2026-07-08-goback-stop-run-support-design.md).
build_terminator_neutralization/build_chain_check are the two new
replacement/insertion blocks the orchestrator wires up in the next task."
```

---

## Task 6: Splice it all together — `orchestrator.py`

**Files:**
- Modify: `mockymock/splicer/orchestrator.py`
- Test: `tests/unit/test_orchestrator.py`

**Interfaces:**
- Consumes: `TerminatorPlan` (Task 3), `insert_lines_after` (Task 4),
  `build_terminator_neutralization`/`build_chain_check` (Task 5). Note:
  `orchestrator.py` never calls `statement_top_level_problem` itself —
  every `chain_performs` entry it receives has already been validated by
  `find_terminator_plans` (Task 2/3) before `splice_program` ever sees it.
- Produces: `splice_program(lines, boundaries, surface, suite, registry,
  terminator_plans=())` — new optional last parameter, default `()`, so
  every existing call site (8 of them) keeps working unmodified.

**Existing call sites that must keep working unmodified (verify, do not
edit unless a step below says to):** `mockymock/cli/main.py:301`,
`tests/integration/test_cli.py:365,492`,
`tests/unit/test_orchestrator.py:61,178,269,315` (line numbers as of this
plan's writing — re-`grep -n "splice_program(" .` if they've drifted).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_orchestrator.py` (append; reuse the file's
existing `parse_cobol`, `normalize_fixed_format`, `analyze`,
`MockCategory`, `MockDirective`, `MockTestCase`, `MockTestSuite`,
`TallyRegistry`, `splice_program`, `collect_boundaries`,
`annotate_nested_sites`, `collect_scope_map` imports — do not re-import):

```python
from mockymock.analysis.refusal import find_terminator_plans

TERMINATOR_CHAIN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMCHAIN.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-WRAPPER
           DISPLAY "AFTER-WRAPPER".

       1000-WRAPPER.
           PERFORM 2000-INNER.
           DISPLAY "AFTER-INNER".

       2000-INNER.
           CALL "CALCPGM" USING WS-RESULT
           STOP RUN.
"""


def _terminator_chain_suite():
    case = MockTestCase(
        name="main",
        mocks=[MockDirective(MockCategory.CALL, "CALCPGM", ["MOVE 42 TO WS-RESULT"])],
        perform_target="0000-MAIN-PROCESS",
    )
    return MockTestSuite(name="T", test_cases=[case])


def _splice_terminator_chain(suite):
    result = parse_cobol(TERMINATOR_CHAIN_SOURCE, filename="termchain.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(TERMINATOR_CHAIN_SOURCE.splitlines()).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    boundaries = collect_boundaries(result.ast)
    plans, reasons = find_terminator_plans(surface, result.ast, suite, scope_map, lines)
    assert reasons == []
    return splice_program(
        lines, boundaries, surface, suite, TallyRegistry(suite), plans
    )


def test_terminator_is_replaced_with_flag_and_exit_paragraph():
    lines = _splice_terminator_chain(_terminator_chain_suite())
    joined = "\n".join(lines)
    assert "      *>     STOP RUN." in joined
    assert 'MOVE "Y" TO UT-EARLY-EXIT' in joined
    assert "EXIT PARAGRAPH" in joined


def test_intermediate_performs_get_chain_check_inserted_after():
    lines = _splice_terminator_chain(_terminator_chain_suite())
    joined = "\n".join(lines)
    # both PERFORM 1000-WRAPPER and PERFORM 2000-INNER are on the chain --
    # each must be followed by the flag check, and neither PERFORM's own
    # line is touched (still live, not commented out)
    assert "           PERFORM 1000-WRAPPER" in joined
    assert "           PERFORM 2000-INNER." in joined
    assert joined.count('IF UT-EARLY-EXIT = "Y"') == 2
    # the two DISPLAY lines that must not run past a real terminator stay
    # in the source (this test only checks the splice shape, not runtime
    # behavior -- that's the Task 7 integration test)
    assert 'DISPLAY "AFTER-WRAPPER"' in joined
    assert 'DISPLAY "AFTER-INNER"' in joined


def test_terminator_splice_coexists_with_mocked_call_splice():
    lines = _splice_terminator_chain(_terminator_chain_suite())
    joined = "\n".join(lines)
    assert "ADD 1 TO UT-CALCPGM-TALLY" in joined
    assert "MOVE 42 TO WS-RESULT" in joined
    assert '      *>     CALL "CALCPGM"' in joined


def test_no_terminator_plans_argument_leaves_existing_behavior_unchanged():
    """The old 5-positional-argument call (no terminator_plans) must still
    work exactly as before -- the regression guard for every existing
    caller of splice_program."""
    result = parse_cobol(TERMINATOR_CHAIN_SOURCE, filename="termchain.cbl")
    surface = analyze(result.ast)
    lines = normalize_fixed_format(TERMINATOR_CHAIN_SOURCE.splitlines()).splitlines()
    boundaries = collect_boundaries(result.ast)
    suite = _terminator_chain_suite()
    spliced = splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))
    joined = "\n".join(spliced)
    assert "STOP RUN." in joined
    assert "      *>     STOP RUN." not in joined
    assert "UT-EARLY-EXIT" not in joined
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_orchestrator.py -v -k terminator`
Expected: FAIL — `TypeError: splice_program() takes from 5 to 5 positional
arguments but 6 were given` (for tests passing `terminator_plans`).

- [ ] **Step 3: Implement**

In `mockymock/splicer/orchestrator.py`, extend the existing imports:

```python
from mockymock.analysis.mock_surface import MockSurface
from mockymock.analysis.refusal import TerminatorPlan, directive_matches_site
from mockymock.dsl.model import EXEC_CATEGORIES, MockTestSuite
from mockymock.splicer.injector import (
    build_chain_check,
    build_exec_trap,
    build_site_dispatch,
    build_terminator_neutralization,
)
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.source_map import statement_span
from mockymock.splicer.stub_writer import comment_and_replace, insert_lines_after
```

Replace `splice_program`'s signature and body:

```python
def splice_program(
    lines: list[str],
    boundaries: list[int],
    surface: MockSurface,
    suite: MockTestSuite,
    registry: TallyRegistry,
    terminator_plans: list[TerminatorPlan] = (),
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
        if site.nested:
            if site.span is None:
                raise ValueError(
                    f"nested {site.label} site at line {site.line} reached "
                    f"the splicer without a validated span -- the refusal "
                    f"gate (UNSUPPORTED_NESTED_MOCK_TARGET / NESTED_EXEC) "
                    f"should have refused it"
                )
            start, end = site.span
        else:
            if site.unspliceable_reason:
                raise ValueError(
                    f"top-level {site.label} site at line {site.line} "
                    f"reached the splicer although it "
                    f"{site.unspliceable_reason} -- the refusal gate "
                    f"(UNSUPPORTED_MOCK_TARGET_LAYOUT / UNSPLICEABLE_EXEC) "
                    f"should have refused it; splicing would delete the "
                    f"sibling code sharing its line"
                )
            start, end = statement_span(site.statement, boundaries, last_line)
        last_span_line = next(
            (lines[i - 1] for i in range(end, start - 1, -1) if lines[i - 1].strip()),
            "",
        )
        if last_span_line.rstrip().endswith("."):
            replacement = replacement[:-1] + [replacement[-1] + "."]
        spans.append((start, end, replacement))

    # Terminator neutralization: replace the STOP RUN/GOBACK statement's
    # own span, exactly like any other boundary replacement above.
    seen_terminator_ids: set[int] = set()
    for plan in terminator_plans:
        site = plan.site
        if id(site.statement) in seen_terminator_ids:
            continue
        seen_terminator_ids.add(id(site.statement))
        replacement = build_terminator_neutralization()
        if site.nested:
            if site.span is None:
                raise ValueError(
                    f"nested {site.label} site at line {site.line} reached "
                    f"the splicer without a validated span -- "
                    f"check_terminator_layout (UNSUPPORTED_TERMINATOR_LAYOUT) "
                    f"should have refused it"
                )
            start, end = site.span
        else:
            if site.unspliceable_reason:
                raise ValueError(
                    f"top-level {site.label} site at line {site.line} "
                    f"reached the splicer although it "
                    f"{site.unspliceable_reason} -- "
                    f"check_terminator_layout (UNSUPPORTED_TERMINATOR_LAYOUT) "
                    f"should have refused it"
                )
            start, end = statement_span(site.statement, boundaries, last_line)
        last_span_line = next(
            (lines[i - 1] for i in range(end, start - 1, -1) if lines[i - 1].strip()),
            "",
        )
        if last_span_line.rstrip().endswith("."):
            replacement = replacement[:-1] + [replacement[-1] + "."]
        spans.append((start, end, replacement))

    # Chain-check insertion: every intermediate PERFORM statement across
    # every plan, deduped by identity (several plans can share the same
    # PERFORM edge -- e.g. two terminators reached through one common
    # wrapper paragraph).
    seen_perform_ids: set[int] = set()
    insertions: list[tuple[int, list[str]]] = []
    for plan in terminator_plans:
        for perform in plan.chain_performs:
            if id(perform) in seen_perform_ids:
                continue
            seen_perform_ids.add(id(perform))
            _, end = statement_span(perform, boundaries, last_line)
            insertions.append((end, build_chain_check()))

    for start, end, replacement in sorted(spans, key=lambda s: s[0], reverse=True):
        lines = comment_and_replace(lines, start, end, replacement)
    for line_number, new_lines in sorted(insertions, key=lambda i: i[0], reverse=True):
        lines = insert_lines_after(lines, line_number, new_lines)
    return lines
```

**Note on ordering:** insertions are applied in a *second* bottom-up pass,
after every `comment_and_replace` span has already been applied. This is
safe (not a repeat of the original top-down-vs-bottom-up line-shift bug)
because `insert_lines_after` inserts entirely new lines rather than
replacing existing ones — as long as `line_number` values are recomputed
against `lines` as it stood at that point, which they are here since every
`insertions` value comes from `boundaries`/`last_line` computed once
up-front against the *original* `lines`, and insertions are applied
bottom-up too. If an intermediate `PERFORM`'s span was already shifted by
an earlier-applied (higher-line-number) `comment_and_replace`, this would
break — but `comment_and_replace` only changes lines *within* the spans it
replaces, and `insert_lines_after` inserts strictly *after* a `PERFORM`'s
own end line, which — because both `spans` and `insertions` were computed
from the same pre-splice `boundaries`/`last_line` — never overlaps a
comment-and-replace span (a `PERFORM` statement is never itself a boundary
site). Run the tests below to confirm this holds in practice.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_orchestrator.py -v`
Expected: PASS — every pre-existing test in the file (including the two
that check exact `ValueError` message substrings) plus the five new
terminator tests.

- [ ] **Step 5: Run the full unit suite to confirm no regression**

Run: `python -m pytest tests/unit -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mockymock/splicer/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "feat(splicer): splice terminator neutralization + chain-check insertions

Part of GOBACK/STOP RUN support, Approach B
(docs/2026-07-08-goback-stop-run-support-design.md). terminator_plans
defaults to () so every existing 5-argument caller is unaffected. Two
splice passes: comment-and-replace for the terminator itself (same
bottom-up-ordered spans list as every other boundary splice), then a
second bottom-up pass inserting the flag-check after each deduped
intermediate PERFORM -- safe because insertions never overlap a
comment-and-replace span (a PERFORM is never itself a boundary site)."
```

---

## Task 7: `driver.py` — declare and reset `UT-EARLY-EXIT`

**Files:**
- Modify: `mockymock/splicer/driver.py`
- Test: `tests/unit/test_driver.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `build_driver`'s `working_storage_lines` now always includes
  `UT-EARLY-EXIT`; `_build_testcase_paragraph` resets it to `"N"` per
  case. No signature changes to `build_driver`/`DriverArtifact`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_driver.py` (append; reuse the file's existing
`_build`/`_suite` helpers):

```python
def test_working_storage_declares_early_exit_flag():
    joined = "\n".join(_build().working_storage_lines)
    assert 'UT-EARLY-EXIT          PIC X VALUE "N".' in joined


def test_testcase_resets_early_exit_flag():
    joined = "\n".join(_build().procedure_lines)
    assert 'MOVE "N" TO UT-EARLY-EXIT' in joined
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_driver.py -v -k early_exit`
Expected: FAIL — `AssertionError` (the string isn't in the output yet).

- [ ] **Step 3: Implement**

In `mockymock/splicer/driver.py`, extend the `working_storage` list inside
`build_driver` (currently `["01  UT-CURRENT-CASE ...", "01  UT-FAIL-COUNT
..."]`):

```python
    working_storage = [
        "01  UT-CURRENT-CASE        PIC X(9).",
        "01  UT-FAIL-COUNT          PIC 9(9) VALUE 0.",
        '01  UT-EARLY-EXIT          PIC X VALUE "N".',
    ]
```

In `_build_testcase_paragraph`, add the reset line right after the
existing `MOVE "{case_id}" TO UT-CURRENT-CASE` line:

```python
    lines.append(f'           MOVE "{case_id}" TO UT-CURRENT-CASE')
    lines.append('           MOVE "N" TO UT-EARLY-EXIT')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_driver.py -v`
Expected: PASS (every test in the file, including all pre-existing ones —
they use substring `in joined` checks unaffected by this addition).

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/driver.py tests/unit/test_driver.py
git commit -m "feat(splicer): declare and reset UT-EARLY-EXIT per test case

Part of GOBACK/STOP RUN support, Approach B
(docs/2026-07-08-goback-stop-run-support-design.md). The only driver.py
change this design needs -- no paragraph restructuring."
```

---

## Task 8: CLI wiring + end-to-end integration test

**Files:**
- Modify: `mockymock/cli/main.py`
- Test: Create `tests/integration/test_terminator_support.py`

**Interfaces:**
- Consumes: `check_terminator_layout`, `find_terminator_plans` (Task 3);
  `splice_program`'s new `terminator_plans` parameter (Task 6).
- Produces: `mockymock run` no longer crashes when a test case's `PERFORM`
  target reaches a safely-neutralizable `STOP RUN`/`GOBACK`.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_terminator_support.py`:

```python
"""End-to-end proof that a test case whose PERFORM target reaches
STOP RUN (through a chain of plain PERFORM calls) no longer crashes the
suite, and that a later test case in the same suite still runs -- see
docs/2026-07-08-goback-stop-run-support-design.md, Finding 3 of
docs/2026-07-06-real-world-readiness-audit.md."""

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


@requires_docker
def test_go_to_reachable_terminator_refuses_before_compiling(tmp_path: Path, capsys):
    """The one deferred-scope shape this integration tier should verify
    end-to-end: a GO TO-reachable terminator refuses cleanly instead of
    reaching the (unsafe) splicer."""
    cbl_path = tmp_path / "GOTOTERM.cbl"
    cbl_path.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. GOTOTERM.\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        "           GO TO 1000-EXIT.\n"
        "\n"
        "       1000-EXIT.\n"
        "           STOP RUN.\n"
    )
    cut_path = tmp_path / "GOTOTERM.cut"
    cut_path.write_text(
        'TESTSUITE "gototerm"\n'
        "\n"
        'TESTCASE "reaches terminator via GO TO"\n'
        "    PERFORM 0000-MAIN-PROCESS\n"
    )

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "UNSUPPORTED_TERMINATOR_LAYOUT" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_terminator_support.py -v`
Expected: FAIL — `mockymock run` crashes (no `CASE 001 END`/`CASE 002 END`
in stdout) since the CLI does not yet call
`check_terminator_layout`/`find_terminator_plans` or pass `terminator_plans`
into `splice_program`.

- [ ] **Step 3: Implement**

In `mockymock/cli/main.py`, extend the existing `mockymock.analysis.refusal`
import (currently `check_expansion_warnings, check_linkage_layout,
check_nested_exec, check_test_case, check_unresolved_copybooks,
check_whole_program`):

```python
    from mockymock.analysis.refusal import (
        check_expansion_warnings,
        check_linkage_layout,
        check_nested_exec,
        check_terminator_layout,
        check_test_case,
        check_unresolved_copybooks,
        check_whole_program,
        find_terminator_plans,
    )
```

First, locate the CLI's existing nested-site annotation line (it runs
earlier in `_cmd_run`, before `check_nested_exec`):

```python
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
```

`check_terminator_layout`/`find_terminator_plans` need that same
`scope_map` object (Task 3's `statement_top_level_problem` check), so
change this line to keep it in a variable instead of discarding it inline:

```python
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
```

Then replace this block (the per-case refusal loop through the splice
call, currently reading `refused = False` ... `lines =
splice_program(lines, boundaries, surface, suite, registry)` ... `lines,
_ = transform_data_division_exec(lines)`):

```python
    refused = False
    for case in suite.test_cases:
        for reason in check_test_case(surface, result.ast, case):
            print(f"mockymock run: refused ({reason.code}): {reason.message}")
            refused = True
    for reason in check_terminator_layout(surface, result.ast, suite, scope_map, lines):
        print(f"mockymock run: refused ({reason.code}): {reason.message}")
        refused = True
    if refused:
        return 1

    boundaries = collect_boundaries(result.ast)
    registry = TallyRegistry(suite)
    terminator_plans, _ = find_terminator_plans(
        surface, result.ast, suite, scope_map, lines
    )
    lines = splice_program(
        lines, boundaries, surface, suite, registry, terminator_plans
    )
    lines, _ = transform_data_division_exec(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_terminator_support.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Run the full test suite (unit + integration) to confirm no regression**

Run: `python -m pytest tests/ -v`
Expected: PASS (all unit tests; all Docker integration tests, including
every pre-existing `examples/real-world/*` and `examples/{invupdt,ordrproc}`
end-to-end test).

- [ ] **Step 6: Commit**

```bash
git add mockymock/cli/main.py tests/integration/test_terminator_support.py
git commit -m "feat(cli): support test cases whose PERFORM target reaches a terminator

Closes the core gap in docs/2026-07-08-goback-stop-run-support-design.md
and Finding 3 of docs/2026-07-06-real-world-readiness-audit.md, for the
plain-PERFORM-chain shape this feature supports: a test case reaching
STOP RUN/GOBACK through such a chain now completes and reports
PASS/FAIL, later test cases in the same suite still run, and a
GO TO-reachable terminator refuses cleanly instead of crashing."
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

Locate the section via `grep -n "Known limitation" README.md` and replace
it with:

```markdown
### `STOP RUN` / `GOBACK` inside a test case's PERFORM target

A `.cut` test case's `PERFORM` target may reach `STOP RUN` or `GOBACK`
through a chain of plain, unconditional `PERFORM` calls, and the test
still completes correctly: the terminator is neutralized (an early-exit
flag propagates back up the real call chain via `EXIT PARAGRAPH`) and
this case's own `EXPECT`/`VERIFY` checks run normally, with later test
cases in the same suite unaffected. This is what makes it possible to
`PERFORM` a program's real top-level driver paragraph (the one that
naturally ends in `STOP RUN`/`GOBACK`) as a test target, not only its
sub-paragraphs.

Some layouts are not yet supported and refuse
(`UNSUPPORTED_TERMINATOR_LAYOUT`) rather than risk corrupting the
program: a terminator reachable via `GO TO` anywhere in the program, one
inside a `SECTION`, or one reached through an intermediate `PERFORM`
that's nested inside a conditional body. Restructure to a plain,
unconditional `PERFORM` chain to avoid this.
```

- [ ] **Step 2: Append a dated entry to `.okf/log.md`**

Add to the top of the "Update Log" (after the `# mocky-mock OKF Bundle —
Update Log` header):

```markdown
## 2026-07-08 (GOBACK/STOP RUN terminator support, Approach B)
* **Closed Finding 3 of `docs/2026-07-06-real-world-readiness-audit.md`**
  for the plain-PERFORM-chain shape: a `.cut` test case's `PERFORM`
  target reaching `STOP RUN`/`GOBACK` through a chain of plain,
  unconditional `PERFORM` calls no longer kills the whole compiled
  suite. An earlier design (redirect via `GO TO` into a `PERFORM ...
  THRU ...` range) was disproven by its own verification spike and
  never shipped -- see
  [docs/2026-07-08-goback-stop-run-support-design.md](../docs/2026-07-08-goback-stop-run-support-design.md)
  for the concrete crash evidence and the chosen replacement.
  `mock_surface.py` detects `StopStatement`(RUN-form)/`GobackStatement`
  (category `None`, like `CANCEL`/SORT-MERGE); `refusal.py`'s
  `find_terminator_plans` walks backward from each reachable terminator
  through the chain of paragraphs that plainly `PERFORM` it, refusing
  (`UNSUPPORTED_TERMINATOR_LAYOUT`) if any link is a `SECTION` member,
  a `GO TO` target anywhere in the program, or not reached via a plain
  top-level `PERFORM`. Safe terminators get `MOVE "Y" TO UT-EARLY-EXIT`
  + `EXIT PARAGRAPH` in place of the real statement
  (`injector.build_terminator_neutralization`); every intermediate
  `PERFORM` on the chain gets `IF UT-EARLY-EXIT = "Y" EXIT PARAGRAPH
  END-IF` inserted after it (`injector.build_chain_check`, via the new
  `stub_writer.insert_lines_after` primitive). No `driver.py`
  restructuring needed -- `UT-TESTCASE-NNN`'s existing checks, right
  after `PERFORM {target}`, run once the flag has propagated back via
  ordinary `PERFORM` returns.
```

- [ ] **Step 3: Add a concept row to `.okf/analysis.md`**

In the `# mock_surface.py — What Counts as a Boundary` categories table,
add a row after the `CANCEL` row:

```markdown
| `StopStatement` (stop_type == "RUN") / `GobackStatement` | `None` (detected, neutralized when found on a safe plain-PERFORM chain) | — | label `"STOP RUN"`/`"GOBACK"`; see [splicer](splicer.md) and [docs/2026-07-08-goback-stop-run-support-design.md](../docs/2026-07-08-goback-stop-run-support-design.md) -- unlike CANCEL/SORT-MERGE this category IS spliced, via a dedicated path (`refusal.find_terminator_plans` / `injector.build_terminator_neutralization`/`build_chain_check`), not `directive_matches_site` |
```

Add a row to the per-test-case refusal table noting `check_terminator_layout`
runs alongside `check_test_case` (not inside it) with code
`UNSUPPORTED_TERMINATOR_LAYOUT`.

- [ ] **Step 4: Add a section to `.okf/splicer.md`**

After the `# ENTRY/LINKAGE Neutralization (linkage.py)` section, add:

```markdown
# Terminator Neutralization (GOBACK/STOP RUN, Approach B)

`refusal.find_terminator_plans` finds every `StopStatement`(RUN-form)/
`GobackStatement` reachable from at least one test case whose enclosing
paragraph -- and every intermediate paragraph between it and the test's
`perform_target` -- is reached exclusively via plain, unconditional,
top-level `PERFORM` statements (`refusal._plain_perform_edges_from`),
never a `GO TO` target anywhere in the program
(`refusal._go_to_targets`), never a `SECTION` member. Safe terminators
are replaced with `MOVE "Y" TO UT-EARLY-EXIT` + `EXIT PARAGRAPH`
(`injector.build_terminator_neutralization`); every intermediate
`PERFORM` statement on the chain gets `IF UT-EARLY-EXIT = "Y" EXIT
PARAGRAPH END-IF` inserted immediately after it
(`injector.build_chain_check`, via `stub_writer.insert_lines_after` --
the only splice primitive in this codebase that preserves the original
statement rather than replacing it). `driver.py` needs only one addition:
`UT-EARLY-EXIT` declared once, reset to `"N"` per test case. No paragraph
restructuring -- `UT-TESTCASE-NNN`'s existing checks run automatically
once the flag has propagated back via ordinary, unmodified `PERFORM`
returns. An earlier design (`GO TO` redirect into a `PERFORM ... THRU
...` range) was proven unsound by a verification spike and replaced
before any of it shipped -- see
[docs/2026-07-08-goback-stop-run-support-design.md](../docs/2026-07-08-goback-stop-run-support-design.md).
```

- [ ] **Step 5: Annotate Finding 3 in the audit doc**

In `docs/2026-07-06-real-world-readiness-audit.md`, immediately after the
`## Finding 3` heading line, insert:

```markdown
**Partially resolved 2026-07-08** — see
[docs/2026-07-08-goback-stop-run-support-design.md](2026-07-08-goback-stop-run-support-design.md).
A terminator reachable through a chain of plain, unconditional `PERFORM`
calls is now neutralized and the test case completes normally; `GO
TO`-reachable and `SECTION`-scoped terminators still refuse rather than
crash. The remainder of this finding is kept below for history.
```

- [ ] **Step 6: Update the IMS/LINKAGE design doc's worked-example note**

In `docs/2026-07-08-ims-linkage-support-design.md`, in the `### Worked
example` section, after the sentence ending "...that would kill the whole
test binary regardless of this fix," add:

```markdown
(Partially resolved by `docs/2026-07-08-goback-stop-run-support-design.md`
— see Task 10 of its implementation plan for re-targeting this example at
`0000-MAIN-PROCESS`, if its GOBACK is reached via a plain PERFORM chain.)
```

- [ ] **Step 7: Run OKF validation**

Run: `/okf:validate .okf --strict` (or, if that skill isn't available in
this session, manually confirm every edited `.okf/*.md` file still has
non-empty YAML frontmatter `type:` and no broken relative links you
introduced).
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add README.md .okf/analysis.md .okf/splicer.md .okf/log.md \
    docs/2026-07-06-real-world-readiness-audit.md \
    docs/2026-07-08-ims-linkage-support-design.md
git commit -m "docs: sync GOBACK/STOP RUN terminator support (Approach B)

Updates README's known-limitation section, .okf concepts/log, and marks
Finding 3 of the real-world-readiness audit partially resolved."
```

---

## Task 10 (optional / stretch): Re-target the ACCTPRG example at its real entry point

Optional — the feature is complete and shippable after Task 9. Do this
only if time permits and `ACCTPRG.cbl`'s `0000-MAIN-PROCESS` actually
qualifies for this design's scope (plain-PERFORM chain to its `GOBACK`,
verify by reading the file first — if it uses `GO TO` or a `SECTION`
anywhere on the path, it does not qualify and this task should be skipped,
not forced).

**Files:**
- Modify: `examples/real-world/ACCTPRG/ACCTPRG.cut`
- Modify: `examples/real-world/ACCTPRG/README.md` (if one exists — check first)

**Interfaces:** None (example content only).

- [ ] **Step 1: Read the current example and check it qualifies**

Read `examples/real-world/ACCTPRG/ACCTPRG.cbl`: confirm `0000-MAIN-PROCESS`
reaches its `GOBACK` via a chain of plain, unconditional, top-level
`PERFORM` statements only (no `GO TO`, no `SECTION`, per this plan's
Global Constraints). If it doesn't qualify, stop here and report
`DONE_WITH_CONCERNS` — do not force the re-target.

If it qualifies, read `examples/real-world/ACCTPRG/ACCTPRG.cut`'s existing
test cases (targeting `1000-INITIALIZE`/`2000-SCAN-AND-PURGE`) for the
`.cut` directive syntax and `MOCK CALL "CBLTDLI"` body shape already in use.

- [ ] **Step 2: Add a new test case targeting `0000-MAIN-PROCESS`**

Following the exact pattern of the existing test cases, add one new
`TESTCASE` whose `PERFORM` target is `0000-MAIN-PROCESS`. Choose
`EXPECT`/`VERIFY` assertions appropriate to what `0000-MAIN-PROCESS`
actually does (read it in Step 1 first — do not guess).

- [ ] **Step 3: Run the existing ACCTPRG integration test**

Run: `python -m pytest tests/integration/ -v -k acctprg` (locate the exact
test file/function via `grep -rl ACCTPRG tests/integration/` if this
doesn't match).
Expected: PASS, including the new test case.

- [ ] **Step 4: Update the example's README if one exists**

If `examples/real-world/ACCTPRG/README.md` exists and mentions avoiding
`0000-MAIN-PROCESS`, update it to note the new test case now exercises it
directly.

- [ ] **Step 5: Commit**

```bash
git add examples/real-world/ACCTPRG/
git commit -m "test(examples): ACCTPRG now also tests its real 0000-MAIN-PROCESS entry point

Demonstrates GOBACK/STOP RUN terminator support (Approach B) end-to-end
on a real corpus program, not just the synthetic TERMDEMO fixture."
```
