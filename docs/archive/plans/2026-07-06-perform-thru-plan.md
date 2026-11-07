# PERFORM ... THRU Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support `PERFORM A THRU B` both inside analyzed COBOL programs (source-order range expansion in the refusal gate's reachability BFS) and as a `.cut` test case entry point (parsed, emitted by the driver, and seeded into reachability), per `docs/2026-07-06-perform-thru-design.md`.

**Architecture:** `PERFORM ... THRU` is not a boundary statement — nothing is spliced. The change is confined to (1) the `.cut` DSL model/parser, (2) the driver paragraph generator, and (3) `analysis/refusal.py`'s `_reachable_paragraphs` BFS, which gains positional range expansion over a line-ordered paragraph list with a runtime strict-increase check. The `UNSUPPORTED_PERFORM_THRU` refusal code survives, narrowed to degenerate ranges only.

**Tech Stack:** Python 3.14, pytest, cobolparser 1.2.0 (sibling repo, editable install), GnuCOBOL in Docker for integration tests.

## Global Constraints

- Work on the existing `perform-thru` branch (already created; design doc committed).
- Run unit tests with the repo venv: `./.venv/Scripts/python.exe -m pytest tests/unit -v` (Windows Git Bash paths).
- Integration tests need Docker Desktop running; they self-skip otherwise.
- Fail closed: every degenerate THRU range must produce a refusal naming the exact problem — never best-effort endpoints (cobolparser's flow analyzer does best-effort; the gate must not).
- Do not import `ProgramFlowAnalyzer` in `analysis/refusal.py` — the module's policy is depending only on individually verified AST attributes (`CobolParagraph.statements`, `CobolParagraph.location.line`, `PerformStatement.target_paragraph`, `PerformStatement.thru_paragraph`).
- Comment style: module docstrings explain *why*; no change-narration comments.

**Verified facts you may rely on (do not re-derive):** `PerformStatement.thru_paragraph` is populated for `PERFORM A THRU B`; `_all_paragraphs` returns paragraphs with strictly increasing `location.line` in plain and sectioned programs; phantom `"."` paragraphs are empty artifacts (no statements, no boundary sites) that can appear interleaved (e.g. after a `PERFORM ... THRU` sentence followed by another statement); duplicate paragraph names across sections parse successfully and appear as two entries.

---

### Task 1: `.cut` DSL — parse `PERFORM A THRU B`

**Files:**
- Modify: `mockymock/dsl/model.py` (MockTestCase, ~line 86)
- Modify: `mockymock/dsl/parser.py` (`_PERFORM_RE` line 38, handler line 113)
- Test: `tests/unit/test_dsl_parser_v2.py`

**Interfaces:**
- Produces: `MockTestCase.perform_thru: str | None` (default `None`) — read by Task 2 (driver emission) and Task 3 (refusal seeding). Parser accepts `PERFORM <t>`, `PERFORM <t> THRU <u>`, `PERFORM <t> THROUGH <u>`; anything else on a PERFORM line stays a `CutParseError`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_dsl_parser_v2.py`:

```python
THRU_CUT = """\
TESTSUITE "THRU driver"

TESTCASE "invokes a range"
    MOCK CALL "RATELKP"
    END-MOCK
    PERFORM PROCESS-ORDER THRU PROCESS-EXIT
"""


def test_parses_perform_thru():
    case = parse_cut(THRU_CUT).test_cases[0]
    assert case.perform_target == "PROCESS-ORDER"
    assert case.perform_thru == "PROCESS-EXIT"


def test_parses_perform_through_synonym():
    case = parse_cut(THRU_CUT.replace(" THRU ", " THROUGH ")).test_cases[0]
    assert case.perform_thru == "PROCESS-EXIT"


def test_plain_perform_leaves_thru_unset():
    case = parse_cut(ALL_BOUNDARIES_CUT).test_cases[0]
    assert case.perform_target == "MAIN-PARA"
    assert case.perform_thru is None


def test_perform_thru_with_trailing_junk_rejected():
    with pytest.raises(CutParseError):
        parse_cut(THRU_CUT.replace("THRU PROCESS-EXIT", "THRU PROCESS-EXIT EXTRA"))


def test_perform_thru_missing_endpoint_rejected():
    with pytest.raises(CutParseError):
        parse_cut(THRU_CUT.replace(" PROCESS-EXIT", ""))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_dsl_parser_v2.py -v`
Expected: the two positive THRU tests FAIL — `test_parses_perform_thru` raises `CutParseError: line 6: unrecognized statement` (the current `_PERFORM_RE` doesn't match the THRU form). `test_plain_perform_leaves_thru_unset` FAILS with `AttributeError: 'MockTestCase' object has no attribute 'perform_thru'`. The two rejection tests already PASS (fail-closed today) — that's expected; they pin the behavior so Task 1 can't loosen it.

- [ ] **Step 3: Add the model field**

In `mockymock/dsl/model.py`, change `MockTestCase`:

```python
@dataclass
class MockTestCase:
    name: str
    mocks: list[MockDirective] = field(default_factory=list)
    setup_moves: list[tuple[str, str]] = field(default_factory=list)  # (value, target)
    perform_target: str = ""
    perform_thru: str | None = None  # PERFORM <target> THRU <perform_thru>
    expectations: list[ExpectDirective] = field(default_factory=list)
    verifications: list[VerifyDirective] = field(default_factory=list)
```

- [ ] **Step 4: Extend the parser**

In `mockymock/dsl/parser.py`, replace line 38:

```python
_PERFORM_RE = re.compile(
    r"^PERFORM\s+(?P<target>\S+)(?:\s+(?:THRU|THROUGH)\s+(?P<thru>\S+))?$"
)
```

and replace the handler body (currently line 113-116):

```python
        elif (m := _PERFORM_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: PERFORM outside TESTCASE")
            case.perform_target = m.group("target")
            case.perform_thru = m.group("thru")
```

(`m.group("thru")` is `None` when the optional group didn't participate — exactly the model default.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_dsl_parser_v2.py tests/unit/test_dsl_parser.py -v`
Expected: all PASS (including the pre-existing v1 parser tests — the regex change must not break plain `PERFORM X`).

- [ ] **Step 6: Commit**

```bash
git add mockymock/dsl/model.py mockymock/dsl/parser.py tests/unit/test_dsl_parser_v2.py
git commit -m "feat: .cut DSL parses PERFORM <target> THRU <endpoint>"
```

---

### Task 2: Driver emits `PERFORM A THRU B`

**Files:**
- Modify: `mockymock/splicer/driver.py` (`_build_testcase_paragraph`, line 104-106)
- Test: `tests/unit/test_driver.py`

**Interfaces:**
- Consumes: `MockTestCase.perform_thru: str | None` (Task 1).
- Produces: generated test case paragraphs contain `PERFORM <target> THRU <thru>` when `perform_thru` is set, unchanged `PERFORM <target>` otherwise. GnuCOBOL executes the range natively — no other driver change.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_driver.py`:

```python
def test_testcase_emits_perform_thru_when_set():
    suite = _suite()
    suite.test_cases[0].perform_thru = "PROCESS-EXIT"
    joined = "\n".join(_build(suite).procedure_lines)
    assert "PERFORM PROCESS-ORDER THRU PROCESS-EXIT" in joined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_driver.py::test_testcase_emits_perform_thru_when_set -v`
Expected: FAIL — the assertion, because the emitted line is `PERFORM PROCESS-ORDER` with no THRU suffix.

- [ ] **Step 3: Implement emission**

In `mockymock/splicer/driver.py`, replace lines 104-106:

```python
    lines.append("")
    lines.append(f"           PERFORM {case.perform_target}")
    lines.append("")
```

with:

```python
    lines.append("")
    perform_line = f"           PERFORM {case.perform_target}"
    if case.perform_thru:
        perform_line += f" THRU {case.perform_thru}"
    lines.append(perform_line)
    lines.append("")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_driver.py -v`
Expected: all PASS (existing `test_testcase_emits_setup_moves_and_perform` still asserts the plain form).

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/driver.py tests/unit/test_driver.py
git commit -m "feat: driver emits PERFORM ... THRU for range entry points"
```

---

### Task 3: Refusal gate — source-order range expansion, narrowed refusal, driver-side seeding

**Files:**
- Modify: `mockymock/analysis/refusal.py` (module docstring; `check_test_case` lines 195-225; `_reachable_paragraphs` lines 351-379; two new helpers)
- Test: `tests/unit/test_refusal.py`

**Interfaces:**
- Consumes: `MockTestCase.perform_thru` (Task 1); `_all_paragraphs`, `_find_performs` (existing).
- Produces: `_reachable_paragraphs(program, start, thru=None) -> tuple[set[str], list[RefusalReason]]` — the second element is now degenerate-range refusals (was: names of THRU-containing paragraphs). `UNSUPPORTED_PERFORM_THRU` fires only for: unverifiable paragraph order, missing endpoint (in-program), ambiguous endpoint, backwards range. A missing *driver-side* endpoint uses `UNKNOWN_PARAGRAPH`.

- [ ] **Step 1: Rewrite the THRU sample source and flip the refusal test**

In `tests/unit/test_refusal.py`, replace the `PERFORM_THRU_SOURCE` block (lines 226-245) with:

```python
# PERFORM ... THRU reachable from START-HERE: the RANGE-START..RANGE-END
# range is expanded in source order, so the CALL in RANGE-MID (a range
# member never PERFORMed directly) and the CALL in HELPER-PARA (reached
# via RANGE-MID's own nested single-member THRU) are both reachable; the
# in-range GO TO RANGE-END is covered positionally. RANGE-MID's
# "PERFORM ... THRU <x>." sentence followed by another statement is the
# (verified) layout that makes cobolparser emit an empty phantom "."
# paragraph INSIDE the outer range -- expansion must tolerate phantom
# members.
PERFORM_THRU_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.

       PROCEDURE DIVISION.
       START-HERE.
           PERFORM RANGE-START THRU RANGE-END.
           STOP RUN.

       RANGE-START.
           DISPLAY "START".

       RANGE-MID.
           PERFORM HELPER-PARA THRU HELPER-PARA.
           CALL "MIDCALL" USING WS-AMOUNT.
           GO TO RANGE-END.

       RANGE-END.
           DISPLAY "END".

       HELPER-PARA.
           CALL "HELPCALL" USING WS-AMOUNT.
"""

# Degenerate ranges: endpoints reversed in source order / endpoint that
# does not exist. Both must refuse fail-closed, never best-effort.
BACKWARDS_THRU_SOURCE = PERFORM_THRU_SOURCE.replace(
    "PERFORM RANGE-START THRU RANGE-END.", "PERFORM RANGE-END THRU RANGE-START."
)
MISSING_THRU_SOURCE = PERFORM_THRU_SOURCE.replace(
    "PERFORM RANGE-START THRU RANGE-END.", "PERFORM RANGE-START THRU NO-SUCH-PARA."
)

# Duplicate endpoint name across two sections: the range is ambiguous.
DUP_THRU_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DUPSAMP.

       PROCEDURE DIVISION.
       MAIN SECTION.
       START-HERE.
           PERFORM DUP-PARA THRU LAST-PARA.
           STOP RUN.

       WORK-A SECTION.
       DUP-PARA.
           DISPLAY "A".

       WORK-B SECTION.
       DUP-PARA.
           DISPLAY "B".

       LAST-PARA.
           DISPLAY "Z".
"""
```

Then replace `test_per_case_check_refuses_reachable_perform_thru` (lines 452-461) with:

```python
def test_per_case_check_expands_perform_thru_range():
    """The THRU range is expanded in source order: both the CALL in a
    mid-range paragraph and the CALL reached transitively from it are
    reachable -- unmocked they surface UNMOCKED_CALL, mocked the case is
    clean. UNSUPPORTED_PERFORM_THRU no longer fires for a well-formed
    range."""
    result = _perform_thru_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("START-HERE", call_names=())
    )
    codes = [r.code for r in reasons]
    assert "UNSUPPORTED_PERFORM_THRU" not in codes
    assert codes.count("UNMOCKED_CALL") == 2

    reasons = check_test_case(
        surface,
        result.ast,
        _case("START-HERE", call_names=("MIDCALL", "HELPCALL")),
    )
    assert reasons == []


def test_per_case_check_refuses_backwards_thru_range():
    result = parse_cobol(BACKWARDS_THRU_SOURCE, filename="backthru.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("START-HERE", call_names=())
    )
    thru = [r for r in reasons if r.code == "UNSUPPORTED_PERFORM_THRU"]
    assert len(thru) == 1
    assert "backwards" in thru[0].message


def test_per_case_check_refuses_missing_thru_endpoint():
    result = parse_cobol(MISSING_THRU_SOURCE, filename="missthru.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("START-HERE", call_names=())
    )
    thru = [r for r in reasons if r.code == "UNSUPPORTED_PERFORM_THRU"]
    assert len(thru) == 1
    assert "NO-SUCH-PARA" in thru[0].message


def test_per_case_check_refuses_ambiguous_thru_endpoint():
    result = parse_cobol(DUP_THRU_SOURCE, filename="dupthru.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("START-HERE", call_names=())
    )
    thru = [r for r in reasons if r.code == "UNSUPPORTED_PERFORM_THRU"]
    assert len(thru) == 1
    assert "DUP-PARA" in thru[0].message


def test_per_case_check_seeds_driver_side_thru_range():
    """A .cut `PERFORM RANGE-START THRU RANGE-END` seeds reachability with
    the whole range even though no in-program PERFORM points at it."""
    result = _perform_thru_result()
    surface = analyze(result.ast)
    case = _case(
        "RANGE-START", call_names=("MIDCALL", "HELPCALL"), perform_thru="RANGE-END"
    )
    assert check_test_case(surface, result.ast, case) == []

    unmocked = _case("RANGE-START", call_names=(), perform_thru="RANGE-END")
    codes = [r.code for r in check_test_case(surface, result.ast, unmocked)]
    assert codes.count("UNMOCKED_CALL") == 2


def test_per_case_check_unknown_driver_side_thru_endpoint():
    result = _perform_thru_result()
    surface = analyze(result.ast)
    case = _case("RANGE-START", call_names=(), perform_thru="NO-SUCH-PARA")
    reasons = check_test_case(surface, result.ast, case)
    assert any(r.code == "UNKNOWN_PARAGRAPH" for r in reasons)


def test_expand_thru_range_refuses_unverifiable_order():
    """The runtime source-order guarantee: when ordering could not be
    verified (`ordered is None`, a parser-regression guard no real program
    triggers), expansion refuses instead of guessing."""
    members, problem = _expand_thru_range(None, "A", "B", "paragraph 'X'")
    assert members == []
    assert problem.code == "UNSUPPORTED_PERFORM_THRU"
    assert "source order" in problem.message
```

(`_expand_thru_range` must be added to the module's imports at the top of
the test file: `from mockymock.analysis.refusal import ..., _expand_thru_range`.)

And extend the `_case` helper (line 13) to thread `perform_thru`:

```python
def _case(perform_target, call_names=(), mocks=(), verifications=(), perform_thru=None):
    return MockTestCase(
        name="case",
        mocks=[MockDirective(MockCategory.CALL, n) for n in call_names]
        + list(mocks),
        perform_target=perform_target,
        perform_thru=perform_thru,
        verifications=list(verifications),
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_refusal.py -v -k thru`
Expected: `test_per_case_check_expands_perform_thru_range` FAILS (gets `UNSUPPORTED_PERFORM_THRU`, zero `UNMOCKED_CALL`); the backwards/missing/ambiguous tests FAIL on message-content asserts (`"backwards" in ...` — today's generic message doesn't contain it) or on count; the driver-side tests FAIL (`perform_thru` ignored, MIDCALL/HELPCALL unreachable → `UNMATCHED_MOCK` instead of clean).

- [ ] **Step 3: Implement range expansion in `refusal.py`**

Replace `_reachable_paragraphs` (lines 351-379) with the three functions below, and update `check_test_case` (see step 4):

```python
def _source_ordered_paragraphs(procedure) -> list | None:
    """All paragraphs sorted by location.line, or None when the sorted
    line sequence is not strictly increasing -- the runtime check behind
    the source-order guarantee THRU range expansion depends on. Verified
    to hold for plain and sectioned programs; a parser regression trips
    the None path and every expansion refuses fail-closed."""
    paragraphs = sorted(_all_paragraphs(procedure), key=lambda p: p.location.line)
    lines = [p.location.line for p in paragraphs]
    if any(later <= earlier for earlier, later in zip(lines, lines[1:])):
        return None
    return paragraphs


def _expand_thru_range(
    ordered,
    start: str,
    thru: str,
    origin: str,
    missing_code: str = "UNSUPPORTED_PERFORM_THRU",
) -> tuple[list[str], RefusalReason | None]:
    """Names of every paragraph in the source-order slice [start..thru]
    inclusive (phantom '.' members ride along; they are empty artifacts),
    or ([], reason) for a degenerate range: unverifiable order, missing
    endpoint, ambiguous endpoint name, or thru preceding start. Never
    best-effort -- cobolparser's flow analyzer degrades to [start, end]
    endpoints when a range is malformed, but the refusal gate must not."""
    if ordered is None:
        return [], RefusalReason(
            code="UNSUPPORTED_PERFORM_THRU",
            message=(
                f"{origin}: PERFORM {start} THRU {thru} cannot be "
                f"range-expanded -- paragraph source order could not be "
                f"verified (location lines are not strictly increasing)"
            ),
        )
    names = [p.paragraph_name for p in ordered]
    for endpoint in (start, thru):
        count = names.count(endpoint)
        if count == 0:
            return [], RefusalReason(
                code=missing_code,
                message=(
                    f"{origin}: PERFORM {start} THRU {thru} endpoint "
                    f"'{endpoint}' not found in PROCEDURE DIVISION"
                ),
            )
        if count > 1:
            return [], RefusalReason(
                code="UNSUPPORTED_PERFORM_THRU",
                message=(
                    f"{origin}: PERFORM {start} THRU {thru} endpoint "
                    f"'{endpoint}' names {count} paragraphs -- the range "
                    f"is ambiguous"
                ),
            )
    i, j = names.index(start), names.index(thru)
    if j < i:
        return [], RefusalReason(
            code="UNSUPPORTED_PERFORM_THRU",
            message=(
                f"{origin}: PERFORM {start} THRU {thru} is a backwards "
                f"range ('{thru}' precedes '{start}' in source order)"
            ),
        )
    return names[i : j + 1], None


def _reachable_paragraphs(
    program, start: str, thru: str | None = None
) -> tuple[set[str], list[RefusalReason]]:
    """Return (reachable paragraph names, degenerate-THRU-range refusals),
    computed in a single BFS pass over PerformStatement edges. A
    PERFORM ... THRU pushes every paragraph of its source-order range
    (fall-through executes them all); `thru` seeds the BFS with the test
    case's own driver-side range, whose missing endpoints are the .cut
    author's typo and use UNKNOWN_PARAGRAPH."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set(), []
    ordered = _source_ordered_paragraphs(procedure)
    by_name: dict[str, object] = {}
    for paragraph in _all_paragraphs(procedure):
        by_name.setdefault(paragraph.paragraph_name, paragraph)

    reasons: list[RefusalReason] = []
    stack = [start]
    if thru is not None and start in by_name:
        members, problem = _expand_thru_range(
            ordered,
            start,
            thru,
            "test case PERFORM",
            missing_code="UNKNOWN_PARAGRAPH",
        )
        if problem is not None:
            reasons.append(problem)
        stack.extend(members)

    seen: set[str] = set()
    while stack:
        name = stack.pop()
        if name in seen or name not in by_name:
            continue
        seen.add(name)
        for statement in _find_performs(by_name[name].statements):
            if statement.target_paragraph:
                stack.append(statement.target_paragraph)
                if statement.thru_paragraph:
                    members, problem = _expand_thru_range(
                        ordered,
                        statement.target_paragraph,
                        statement.thru_paragraph,
                        f"paragraph '{name}'",
                    )
                    if problem is not None:
                        reasons.append(problem)
                    stack.extend(members)
    return seen, reasons
```

Notes for the implementer:
- `by_name` switches from last-wins dict comprehension to first-occurrence `setdefault`, matching COBOL's resolution and the range slice's first-occurrence semantics.
- `RefusalReason` is defined above in the same module (line 101); no new imports are needed.

- [ ] **Step 4: Update `check_test_case` and the module docstring**

In `check_test_case`, replace lines 200-225 (the `_reachable_paragraphs` call, the UNKNOWN_PARAGRAPH check, and the whole `for paragraph_name in sorted(thru_paragraphs)` loop) with:

```python
    reachable, thru_reasons = _reachable_paragraphs(
        program, case.perform_target, case.perform_thru
    )

    if case.perform_target not in reachable:
        reasons.append(
            RefusalReason(
                code="UNKNOWN_PARAGRAPH",
                message=(
                    f"PERFORM target '{case.perform_target}' not found in "
                    f"PROCEDURE DIVISION"
                ),
            )
        )
        return reasons

    reasons.extend(thru_reasons)
```

In the module docstring, replace the sentence

```
PERFORM ... THRU targets are deliberately NOT
range-expanded (that needs paragraph source-order guarantees this module
doesn't verify); any reachable paragraph containing one triggers
UNSUPPORTED_PERFORM_THRU.
```

with

```
PERFORM ... THRU ranges ARE expanded: every paragraph in the
source-order slice [target..thru] is reachable (fall-through executes
them all), with the required source-order guarantee checked at runtime
(_source_ordered_paragraphs). UNSUPPORTED_PERFORM_THRU survives only for
degenerate ranges -- unverifiable order, missing or ambiguous endpoints,
backwards ranges -- and a test case's own PERFORM ... THRU seeds the BFS
with its range (missing driver-side endpoints are UNKNOWN_PARAGRAPH).
```

Also update the docstring's introductory sentence about reachability's
verified attributes to include the two new ones: `CobolParagraph.location.line`
and `PerformStatement.thru_paragraph`.

- [ ] **Step 5: Run the full unit suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit -v`
Expected: all PASS. Pay attention to `tests/unit/test_refusal_v2.py` — it exercises `check_test_case` broadly and must be unaffected (its cases don't use THRU).

- [ ] **Step 6: Commit**

```bash
git add mockymock/analysis/refusal.py tests/unit/test_refusal.py
git commit -m "feat: range-expand PERFORM THRU in reachability; narrow UNSUPPORTED_PERFORM_THRU to degenerate ranges"
```

---

### Task 4: End-to-end integration fixture + README

**Files:**
- Create: `tests/integration/fixtures/thru_boundaries.cbl`
- Create: `tests/integration/fixtures/thru_boundaries.cut`
- Create: `tests/integration/test_thru_boundaries.py`
- Modify: `README.md` (lines 66-74, the refused-layouts paragraph)

**Interfaces:**
- Consumes: the whole pipeline (`mockymock run` via `mockymock.cli.main.main`) with Tasks 1-3 in place.
- Produces: proof that a GO-TO-exit-style THRU range compiles and runs in the GnuCOBOL container with mocked CALLs, both happy path and short-circuit.

- [ ] **Step 1: Write the fixture program**

Create `tests/integration/fixtures/thru_boundaries.cbl`:

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUBND.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STATUS           PIC X(2)  VALUE SPACES.
       01  WS-RATE             PIC 9V99  VALUE 0.
       01  WS-TOTAL            PIC 9(5)  VALUE 0.

       PROCEDURE DIVISION.
       MAIN-DRIVER.
           PERFORM PROCESS-ORDER THRU PROCESS-EXIT.
           STOP RUN.

       PROCESS-ORDER.
           CALL "RATELKP" USING WS-RATE.
           IF WS-RATE = 0
               MOVE "ER" TO WS-STATUS
               GO TO PROCESS-EXIT
           END-IF.

       PROCESS-APPLY.
           CALL "TOTCALC" USING WS-RATE WS-TOTAL.
           MOVE "OK" TO WS-STATUS.

       PROCESS-EXIT.
           EXIT.
```

(The tested range is the classic THRU shape: entry paragraph, in-range `GO TO` to the exit paragraph, a mid-range paragraph reached only by fall-through, an `EXIT` terminator. `MAIN-DRIVER` keeps the program independently runnable but is not the test entry — its `STOP RUN` must not run under the driver.)

- [ ] **Step 2: Write the .cut**

Create `tests/integration/fixtures/thru_boundaries.cut`:

```
TESTSUITE "THRUBND perform thru range"

TESTCASE "nonzero rate falls through the whole range"
    MOCK CALL "RATELKP"
        MOVE 0.10 TO WS-RATE
    END-MOCK
    MOCK CALL "TOTCALC"
        MOVE 500 TO WS-TOTAL
    END-MOCK
    PERFORM PROCESS-ORDER THRU PROCESS-EXIT
    EXPECT WS-STATUS TO BE "OK"
    EXPECT WS-TOTAL TO BE 500
    VERIFY "RATELKP" WAS CALLED ONCE
    VERIFY "TOTCALC" WAS CALLED ONCE

TESTCASE "zero rate short-circuits via GO TO the exit paragraph"
    MOCK CALL "RATELKP"
        MOVE 0 TO WS-RATE
    END-MOCK
    MOCK CALL "TOTCALC"
        MOVE 99999 TO WS-TOTAL
    END-MOCK
    PERFORM PROCESS-ORDER THRU PROCESS-EXIT
    EXPECT WS-STATUS TO BE "ER"
    EXPECT WS-TOTAL TO BE 0
    VERIFY "RATELKP" WAS CALLED ONCE
    VERIFY "TOTCALC" WAS CALLED NEVER
```

(Case 2 proves the range's `GO TO PROCESS-EXIT` skips `PROCESS-APPLY` at
runtime: the TOTCALC mock exists — the gate requires it, since the site is
statically in-range — but its tally stays 0 and `WS-TOTAL` keeps its reset
value.)

- [ ] **Step 3: Write the integration test**

Create `tests/integration/test_thru_boundaries.py`:

```python
"""End-to-end proof for PERFORM ... THRU: a GO-TO-exit-style range is
invoked via a driver-side `PERFORM PROCESS-ORDER THRU PROCESS-EXIT`,
its mid-range fall-through paragraph's CALL is mocked, and the range's
in-range GO TO short-circuit is observable at runtime -- the layout that
was blanket-refused (UNSUPPORTED_PERFORM_THRU) before
docs/2026-07-06-perform-thru-design.md."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"


@requires_docker
def test_thru_boundaries_run_passes():
    exit_code = main(
        [
            "run",
            str(FIXTURES / "thru_boundaries.cbl"),
            "--cut",
            str(FIXTURES / "thru_boundaries.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_thru_boundaries_fail_when_expectation_is_wrong(tmp_path: Path):
    cut = (FIXTURES / "thru_boundaries.cut").read_text()
    broken = tmp_path / "thru_boundaries.cut"
    broken.write_text(
        cut.replace('EXPECT WS-STATUS TO BE "OK"', 'EXPECT WS-STATUS TO BE "XX"')
    )
    exit_code = main(
        ["run", str(FIXTURES / "thru_boundaries.cbl"), "--cut", str(broken)]
    )
    assert exit_code == 1
```

- [ ] **Step 4: Run the integration tests (Docker Desktop must be running)**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_thru_boundaries.py -v`
Expected: 2 PASS (or 2 SKIP if Docker is unreachable — in that case start Docker Desktop and rerun; do not commit on SKIP).

- [ ] **Step 5: Update the README**

In `README.md`, the paragraph at lines 66-74 currently reads:

```
Boundary statements nested inside IF/EVALUATE/inline-PERFORM bodies
(including nested EXEC blocks) are mockable when the statement sits on its
own line(s) — the common layout. Still refused, fail-closed: dynamic
`CALL identifier`, `SORT`/`MERGE`/`RELEASE`/`RETURN`, `PERFORM ... THRU`,
nested statements sharing a line with other code (`IF X CALL "F" END-IF`
one-liners), statements inside another boundary statement's clause body
(`READ ... AT END`, `CALL ... ON EXCEPTION`), and mocks with clause bodies
of their own — each refusal names the exact layout problem. `DISPLAY`
passes through unmocked. See the worked example in `examples/invupdt/`.
```

Replace it with:

```
Boundary statements nested inside IF/EVALUATE/inline-PERFORM bodies
(including nested EXEC blocks) are mockable when the statement sits on its
own line(s) — the common layout. `PERFORM A THRU B` is supported both
inside the program (the range is expanded in source order for
reachability) and as a test case's entry point (`PERFORM A THRU B` in the
.cut, `THROUGH` accepted); degenerate ranges — missing, duplicate, or
backwards endpoints — are refused. Still refused, fail-closed: dynamic
`CALL identifier`, `SORT`/`MERGE`/`RELEASE`/`RETURN`, nested statements
sharing a line with other code (`IF X CALL "F" END-IF` one-liners),
statements inside another boundary statement's clause body
(`READ ... AT END`, `CALL ... ON EXCEPTION`), and mocks with clause bodies
of their own — each refusal names the exact layout problem. `DISPLAY`
passes through unmocked. See the worked example in `examples/invupdt/`.
```

- [ ] **Step 6: Run the full test suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit tests/integration -v`
Expected: all unit tests PASS; all integration tests PASS (Docker running).

- [ ] **Step 7: Commit**

```bash
git add tests/integration/fixtures/thru_boundaries.cbl tests/integration/fixtures/thru_boundaries.cut tests/integration/test_thru_boundaries.py README.md
git commit -m "test: end-to-end PERFORM THRU fixture through GnuCOBOL; README reflects THRU support"
```
