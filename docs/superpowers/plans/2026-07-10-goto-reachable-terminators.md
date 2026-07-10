# GO TO-Reachable Terminators Investigation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settle, via compile-and-run spikes against the pinned GnuCOBOL 3.2 toolchain, whether spike #4's broken case from `docs/2026-07-08-goback-stop-run-support-design.md` (a GO-TO-reachable terminator or chain paragraph defeats `EXIT PARAGRAPH`'s return-address resolution) can ever be safely neutralized. Produce either a proven-viable mechanism (handed off to a follow-up implementation plan) or a confirmed, permanent root-cause writeup that replaces today's "empirically observed as broken" hedge.

**Architecture:** Reproduce spike #4's exact failure mode as a baseline (raw hand-authored COBOL, not mockymock's splicer output — the splicer still correctly refuses this shape and stays untouched by this plan). Then try Candidate 1 (force `cobc` to emit return-capable exit code for a GO-TO-touched paragraph by giving it a genuinely dead, never-executed `PERFORM` callsite elsewhere in the source) against both shapes spike #4 covers: the terminator's own paragraph as the GO TO target, and an intermediate chain paragraph as the GO TO target. If either shape fails Candidate 1, try Candidate 2 (wrap the GO-TO-reachable paragraph in its own `SECTION`, using `EXIT SECTION` instead of `EXIT PARAGRAPH` — spike #5 already proved this construct unwinds correctly when genuinely `PERFORM`ed). Whatever the outcome, write the confirmed finding back into both design docs.

**Tech Stack:** Python 3.11+, GnuCOBOL 3.2 via the `mockymock-cobc` Docker container (`mockymock/runtime/docker_toolchain.py`), pytest (`tests/integration`, `@requires_docker`).

**Design doc:** `docs/2026-07-10-goto-reachable-terminators-design.md` — read it before starting; this plan implements its investigation phases task-by-task and does not re-derive its reasoning. Background: `docs/2026-07-08-goback-stop-run-support-design.md` (spike #4, spike #5, and the six-spike table this plan's methodology mirrors).

## Global Constraints

- No changes to mockymock's production code (`mockymock/analysis/refusal.py`, `mockymock/splicer/*`, `mockymock/cli/*`) anywhere in this plan. This is an investigation only; a working candidate is handed off to a *new* follow-up plan for real implementation, exactly as the design doc's decision gate specifies.
- Every spike test compiles and runs hand-authored COBOL directly through `mockymock.runtime.docker_toolchain` (`ensure_toolchain`, `WORK_ROOT`, `compile_source`, `run_binary`) — never through `mockymock.cli.main.main`, since these fixtures represent hypothetical *already-neutralized* source, not something mockymock's splicer is meant to produce today.
- **Commit-on-success only.** A spike test file is committed only if its own decision gate confirms the candidate works for that shape. If a candidate fails, do not commit that test file — report the actual observed `stdout`/`exit_code` back instead. This mirrors the precedent set by the original (superseded) Approach A plan's Task 1: its spike disproved the design, was not committed, and the finding was reported directly.
- Follow this repo's existing integration-test conventions: module docstring explaining *why* (see `tests/integration/test_terminator_support.py`), `@requires_docker` decorator from `tests.integration._docker`, `tmp_path`-based fixture files.
- All GnuCOBOL behavior claims in this plan are unverified until a Docker spike confirms them — do not treat any "expected" annotation below as ground truth before running it.

---

## Task 1: Candidate 1, shape (a) — terminator's own paragraph is the GO TO target

Reproduces spike #4's exact failure mode as a baseline, then tests whether a dead-PERFORM coercion fixes it.

**Files:**
- Create: `tests/integration/test_goto_terminator_investigation.py`

**Interfaces:**
- Consumes: `mockymock.runtime.docker_toolchain` (`ensure_toolchain`, `WORK_ROOT`, `compile_source`, `run_binary`), `tests.integration._docker.requires_docker`.
- Produces: a pass/fail verdict for "Candidate 1, shape (a)" that Task 2's decision gate and Task 5's writeup reference by name.

- [ ] **Step 1: Write the baseline (confirm-still-broken) test**

```python
"""Investigation spike for docs/2026-07-10-goto-reachable-terminators-design.md:
whether spike #4's broken case (docs/2026-07-08-goback-stop-run-support-design.md)
can ever be safely neutralized. Every test here compiles and runs hand-authored,
already-neutralized COBOL directly -- it does NOT exercise mockymock's splicer,
which still correctly refuses this shape (UNSUPPORTED_TERMINATOR_LAYOUT) and is
untouched by this investigation. If a candidate here is later adopted, the real
splicer implementation is a separate follow-up plan.
"""

import tempfile
from pathlib import Path

from mockymock.runtime import docker_toolchain as dt
from tests.integration._docker import requires_docker

# Baseline: reproduces spike #4 exactly. TERMINATOR-PARA is *only* ever a GO TO
# target (never a PERFORM target anywhere in this source) -- the shape the
# original design doc found broken.
BASELINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOSPIKEA.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EARLY-EXIT       PIC X VALUE "N".

       PROCEDURE DIVISION.
       DRIVER-PARA.
           PERFORM REACHED-PARA
           DISPLAY "CALLER-CHECK-RAN"
           STOP RUN.

       REACHED-PARA.
           GO TO TERMINATOR-PARA.

       TERMINATOR-PARA.
           DISPLAY "TERMINATOR-RAN"
           MOVE "Y" TO WS-EARLY-EXIT
           EXIT PARAGRAPH.
"""

# Candidate 1: identical to BASELINE_SOURCE except DEAD-COERCION-PARA gives
# TERMINATOR-PARA a second, genuinely-unreachable static PERFORM callsite.
# WS-NEVER-TRUE is a variable (not a literal), so cobc cannot constant-fold
# the IF away -- the PERFORM callsite must survive into the generated code
# even though it never executes at runtime.
CANDIDATE1_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOFIX1A.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EARLY-EXIT       PIC X VALUE "N".
       01  WS-NEVER-TRUE       PIC X VALUE "N".

       PROCEDURE DIVISION.
       DRIVER-PARA.
           PERFORM REACHED-PARA
           DISPLAY "CALLER-CHECK-RAN"
           STOP RUN.

       REACHED-PARA.
           GO TO TERMINATOR-PARA.

       DEAD-COERCION-PARA.
           IF WS-NEVER-TRUE = "Y"
               PERFORM TERMINATOR-PARA
           END-IF.

       TERMINATOR-PARA.
           DISPLAY "TERMINATOR-RAN"
           MOVE "Y" TO WS-EARLY-EXIT
           EXIT PARAGRAPH.
"""


def _compile_and_run(source: str, name: str):
    dt.ensure_toolchain()
    dt.WORK_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f"test-{name}-", dir=dt.WORK_ROOT))
    path = tmp / f"{name}.cbl"
    path.write_text(source, newline="\n")
    compiled = dt.compile_source(path)
    assert compiled.success, compiled.stderr
    return dt.run_binary(compiled.binary_path)


@requires_docker
def test_baseline_confirms_spike_4_still_broken():
    """Locks in the known-broken behavior as a reproducible baseline. If
    this ever fails (starts printing CALLER-CHECK-RAN), a GnuCOBOL upgrade
    silently changed the exact behavior this whole investigation is about --
    stop and re-read the design doc before touching anything else."""
    executed = _compile_and_run(BASELINE_SOURCE, "gotospikea")
    assert executed.exit_code == 0, executed.stderr
    assert "TERMINATOR-RAN" in executed.stdout
    assert "CALLER-CHECK-RAN" not in executed.stdout


@requires_docker
def test_candidate1_dead_perform_coercion_shape_a():
    executed = _compile_and_run(CANDIDATE1_SOURCE, "gotofix1a")
    assert executed.exit_code == 0, executed.stderr
    assert "TERMINATOR-RAN" in executed.stdout
    assert "CALLER-CHECK-RAN" in executed.stdout
```

- [ ] **Step 2: Run both tests (requires Docker)**

Run: `python -m pytest tests/integration/test_goto_terminator_investigation.py -v`

Expected: `test_baseline_confirms_spike_4_still_broken` PASSES (confirms the known-broken shape reproduces). `test_candidate1_dead_perform_coercion_shape_a` result is genuinely unknown — this is what the spike is for.

- [ ] **Step 3: Capture supporting evidence — generated C comparison (optional, non-gating)**

For the writeup in Task 5, dump `cobc`'s generated C for both `TERMINATOR_PARA` label regions to see whether Candidate 1 visibly changes codegen:

Run:
```
docker exec mockymock-cobc cobc -free -C /work/<baseline-tmp-dir>/gotospikea.cbl -o /work/<baseline-tmp-dir>/gotospikea.c
docker exec mockymock-cobc cobc -free -C /work/<candidate1-tmp-dir>/gotofix1a.cbl -o /work/<candidate1-tmp-dir>/gotofix1a.c
```
(substitute the actual tmp dir names `_compile_and_run` created, printed by adding a `print(tmp)` if needed, or re-run the compile step manually with a fixed path instead of `tempfile.mkdtemp`)

Then read both `.c` files and compare the compiled code around the label matching `TERMINATOR_PARA` (or its mangled equivalent — grep case-insensitively for `TERMINATOR`). Record in Task 5 whether the two differ in how the paragraph's exit/return code is generated (e.g. one references a frame-stack pop the other doesn't). This step does not gate Step 4 — it's explanatory evidence for the writeup, not a pass/fail check. If the `-C` flag or output naming behaves differently than shown here under the pinned GnuCOBOL 3.2 build, adjust and note the actual invocation used.

- [ ] **Step 4: Decision gate**

If `test_candidate1_dead_perform_coercion_shape_a` PASSED:
- Commit the test file (`git add tests/integration/test_goto_terminator_investigation.py && git commit -m "spike: candidate-1 dead-PERFORM coercion fixes GO TO-reachable terminator (shape a)"`).
- Proceed to Task 2.

If it FAILED:
- Do NOT commit the test file. Report the actual observed `stdout`/`exit_code`.
- Skip Task 2 (shape (b) of Candidate 1 is moot if shape (a) already fails). Proceed directly to Task 3 (Candidate 2, shape (a)).

---

## Task 2: Candidate 1, shape (b) — intermediate chain paragraph is the GO TO target

**Only execute this task if Task 1's decision gate said PASSED/proceed.** If Task 1 failed, skip to Task 3.

Tests the other shape spike #4 covers: not the terminator's own paragraph, but an *intermediate* paragraph on the safe chain (one that itself uses the `IF WS-EARLY-EXIT = "Y" EXIT PARAGRAPH END-IF` chain-check pattern from Approach B) being a GO TO target.

**Files:**
- Modify: `tests/integration/test_goto_terminator_investigation.py`

**Interfaces:**
- Consumes: `_compile_and_run` helper defined in Task 1, same file.
- Produces: a pass/fail verdict for "Candidate 1, shape (b)" that Task 5's writeup references by name.

- [ ] **Step 1: Add the shape-(b) baseline and candidate tests**

Append to `tests/integration/test_goto_terminator_investigation.py`:

```python
# Shape (b) baseline: 0000-MAIN-PROCESS (the test's own PERFORM target) does
# GO TO REACHED-PARA instead of PERFORM -- REACHED-PARA is an *intermediate*
# chain paragraph, not the terminator itself. REACHED-PARA and MIDDLE-PARA
# both use the ordinary Approach B chain-check pattern, already proven safe
# in isolation by the original design's spikes #3 and #6. Only REACHED-PARA's
# own GO TO-entry is new.
BASELINE_B_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOSPIKEB.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EARLY-EXIT       PIC X VALUE "N".

       PROCEDURE DIVISION.
       DRIVER-PARA.
           PERFORM 0000-MAIN-PROCESS
           DISPLAY "CALLER-CHECK-RAN"
           STOP RUN.

       0000-MAIN-PROCESS.
           GO TO REACHED-PARA.

       REACHED-PARA.
           PERFORM MIDDLE-PARA
           IF WS-EARLY-EXIT = "Y"
               EXIT PARAGRAPH
           END-IF
           DISPLAY "REACHED-PARA-CONTINUED-WRONGLY".

       MIDDLE-PARA.
           PERFORM TERMINATOR-PARA
           IF WS-EARLY-EXIT = "Y"
               EXIT PARAGRAPH
           END-IF
           DISPLAY "MIDDLE-PARA-CONTINUED-WRONGLY".

       TERMINATOR-PARA.
           DISPLAY "TERMINATOR-RAN"
           MOVE "Y" TO WS-EARLY-EXIT
           EXIT PARAGRAPH.
"""

# Candidate 1 for shape (b): DEAD-COERCION-PARA gives REACHED-PARA (the
# GO-TO-touched intermediate paragraph, not the terminator this time) a
# genuinely-unreachable static PERFORM callsite.
CANDIDATE1_B_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOFIX1B.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EARLY-EXIT       PIC X VALUE "N".
       01  WS-NEVER-TRUE       PIC X VALUE "N".

       PROCEDURE DIVISION.
       DRIVER-PARA.
           PERFORM 0000-MAIN-PROCESS
           DISPLAY "CALLER-CHECK-RAN"
           STOP RUN.

       0000-MAIN-PROCESS.
           GO TO REACHED-PARA.

       DEAD-COERCION-PARA.
           IF WS-NEVER-TRUE = "Y"
               PERFORM REACHED-PARA
           END-IF.

       REACHED-PARA.
           PERFORM MIDDLE-PARA
           IF WS-EARLY-EXIT = "Y"
               EXIT PARAGRAPH
           END-IF
           DISPLAY "REACHED-PARA-CONTINUED-WRONGLY".

       MIDDLE-PARA.
           PERFORM TERMINATOR-PARA
           IF WS-EARLY-EXIT = "Y"
               EXIT PARAGRAPH
           END-IF
           DISPLAY "MIDDLE-PARA-CONTINUED-WRONGLY".

       TERMINATOR-PARA.
           DISPLAY "TERMINATOR-RAN"
           MOVE "Y" TO WS-EARLY-EXIT
           EXIT PARAGRAPH.
"""


@requires_docker
def test_baseline_confirms_shape_b_also_broken():
    executed = _compile_and_run(BASELINE_B_SOURCE, "gotospikeb")
    assert executed.exit_code == 0, executed.stderr
    assert "TERMINATOR-RAN" in executed.stdout
    assert "CALLER-CHECK-RAN" not in executed.stdout


@requires_docker
def test_candidate1_dead_perform_coercion_shape_b():
    executed = _compile_and_run(CANDIDATE1_B_SOURCE, "gotofix1b")
    assert executed.exit_code == 0, executed.stderr
    assert "TERMINATOR-RAN" in executed.stdout
    assert "CALLER-CHECK-RAN" in executed.stdout
    # Not just "did the driver's checks run" -- confirm the chain-check
    # actually suppressed both intermediate paragraphs' wrongful continuation,
    # the same correctness bar the original design's spikes #3/#6 held to.
    assert "REACHED-PARA-CONTINUED-WRONGLY" not in executed.stdout
    assert "MIDDLE-PARA-CONTINUED-WRONGLY" not in executed.stdout
```

- [ ] **Step 2: Run the new tests**

Run: `python -m pytest tests/integration/test_goto_terminator_investigation.py -v -k shape_b`
Expected: `test_baseline_confirms_shape_b_also_broken` PASSES. `test_candidate1_dead_perform_coercion_shape_b` result is unknown.

- [ ] **Step 3: Decision gate**

If PASSED: commit (`git add tests/integration/test_goto_terminator_investigation.py && git commit -m "spike: candidate-1 dead-PERFORM coercion fixes GO TO-reachable terminator (shape b)"`). Both shapes of Candidate 1 now proven — proceed to Task 5, skip Tasks 3-4.

If FAILED: do not commit the new shape-(b) tests (the shape-(a) tests from Task 1 stay committed, since they passed independently). Report actual `stdout`/`exit_code`. Proceed to Task 4 (Candidate 2, shape (b) only — shape (a) already has a Candidate-1 fix from Task 1, so only shape (b) needs Candidate 2).

---

## Task 3: Candidate 2, shape (a) — SECTION-scoped fallback for the terminator's own paragraph

**Only execute this task if Task 1's decision gate FAILED.** If Task 1 passed, this task is not needed (skip to Task 2, then Task 5).

Tests whether wrapping the GO-TO-reachable terminator paragraph in its own `SECTION` — using `EXIT SECTION` instead of `EXIT PARAGRAPH` — survives GO TO entry, on the theory that `SECTION`-level unwind may use different `cobc` codegen than paragraph-level unwind (spike #5 of the original design already proved `EXIT SECTION` correctly unwinds when genuinely `PERFORM`ed).

**Files:**
- Modify: `tests/integration/test_goto_terminator_investigation.py`

**Interfaces:**
- Consumes: `_compile_and_run` helper defined in Task 1.
- Produces: a pass/fail verdict for "Candidate 2, shape (a)" that Task 5's writeup references by name.

- [ ] **Step 1: Add the Candidate 2 test**

Append to `tests/integration/test_goto_terminator_investigation.py`:

```python
# Candidate 2 for shape (a): TERMINATOR-PARA becomes the first (and only)
# paragraph of its own SECTION, using EXIT SECTION instead of EXIT PARAGRAPH.
# Once any SECTION header appears in the PROCEDURE DIVISION, GnuCOBOL
# requires every paragraph to belong to an explicit SECTION -- bare
# paragraphs before the first SECTION header are rejected -- so DRIVER-PARA
# and REACHED-PARA get their own SECTIONs too, even though that's incidental
# to what this candidate is actually testing.
CANDIDATE2_A_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOFIX2A.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EARLY-EXIT       PIC X VALUE "N".

       PROCEDURE DIVISION.
       DRIVER-SECTION SECTION.
       DRIVER-PARA.
           PERFORM REACHED-PARA
           DISPLAY "CALLER-CHECK-RAN"
           STOP RUN.

       REACHED-SECTION SECTION.
       REACHED-PARA.
           GO TO TERMINATOR-PARA.

       TERMINATOR-SECTION SECTION.
       TERMINATOR-PARA.
           DISPLAY "TERMINATOR-RAN"
           MOVE "Y" TO WS-EARLY-EXIT
           EXIT SECTION.
"""


@requires_docker
def test_candidate2_section_fallback_shape_a():
    executed = _compile_and_run(CANDIDATE2_A_SOURCE, "gotofix2a")
    assert executed.exit_code == 0, executed.stderr
    assert "TERMINATOR-RAN" in executed.stdout
    assert "CALLER-CHECK-RAN" in executed.stdout
```

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/integration/test_goto_terminator_investigation.py -v -k candidate2_section_fallback_shape_a`
Expected: unknown — this is the spike.

- [ ] **Step 3: Decision gate**

If PASSED: commit (`git add tests/integration/test_goto_terminator_investigation.py && git commit -m "spike: candidate-2 SECTION fallback fixes GO TO-reachable terminator (shape a)"`). Proceed to Task 4.

If FAILED: do not commit this test. Both candidates have now failed shape (a) — proceed directly to Task 5 to write up the confirmed-no-fix finding. Skip Task 4 (shape (b) is moot if neither candidate fixes the simpler shape (a)).

---

## Task 4: Candidate 2, shape (b) — SECTION-scoped fallback for an intermediate chain paragraph

**Only execute this task if Task 3's decision gate PASSED, or if Task 2's decision gate FAILED and Task 1 PASSED** (i.e., shape (a) is solved by one candidate or the other, but shape (b) still needs a working mechanism).

**Files:**
- Modify: `tests/integration/test_goto_terminator_investigation.py`

**Interfaces:**
- Consumes: `_compile_and_run` helper defined in Task 1.
- Produces: a pass/fail verdict for "Candidate 2, shape (b)" that Task 5's writeup references by name.

- [ ] **Step 1: Add the Candidate 2 shape-(b) test**

Append to `tests/integration/test_goto_terminator_investigation.py`:

```python
# Candidate 2 for shape (b): REACHED-PARA (the GO-TO-touched intermediate
# chain paragraph) becomes its own SECTION; its chain-check now uses
# EXIT SECTION instead of EXIT PARAGRAPH. MIDDLE-PARA and TERMINATOR-PARA
# are untouched (already proven safe when genuinely PERFORMed). As in
# Candidate 2 shape (a), every paragraph needs an explicit SECTION once any
# SECTION header is present, so DRIVER-PARA and 0000-MAIN-PROCESS get one too.
CANDIDATE2_B_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOFIX2B.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EARLY-EXIT       PIC X VALUE "N".

       PROCEDURE DIVISION.
       DRIVER-SECTION SECTION.
       DRIVER-PARA.
           PERFORM 0000-MAIN-PROCESS
           DISPLAY "CALLER-CHECK-RAN"
           STOP RUN.

       MAIN-PROCESS-SECTION SECTION.
       0000-MAIN-PROCESS.
           GO TO REACHED-PARA.

       REACHED-SECTION SECTION.
       REACHED-PARA.
           PERFORM MIDDLE-PARA
           IF WS-EARLY-EXIT = "Y"
               EXIT SECTION
           END-IF
           DISPLAY "REACHED-PARA-CONTINUED-WRONGLY".

       MIDDLE-SECTION SECTION.
       MIDDLE-PARA.
           PERFORM TERMINATOR-PARA
           IF WS-EARLY-EXIT = "Y"
               EXIT PARAGRAPH
           END-IF
           DISPLAY "MIDDLE-PARA-CONTINUED-WRONGLY".

       TERMINATOR-PARA.
           DISPLAY "TERMINATOR-RAN"
           MOVE "Y" TO WS-EARLY-EXIT
           EXIT PARAGRAPH.
"""


@requires_docker
def test_candidate2_section_fallback_shape_b():
    executed = _compile_and_run(CANDIDATE2_B_SOURCE, "gotofix2b")
    assert executed.exit_code == 0, executed.stderr
    assert "TERMINATOR-RAN" in executed.stdout
    assert "CALLER-CHECK-RAN" in executed.stdout
    assert "REACHED-PARA-CONTINUED-WRONGLY" not in executed.stdout
    assert "MIDDLE-PARA-CONTINUED-WRONGLY" not in executed.stdout
```

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/integration/test_goto_terminator_investigation.py -v -k candidate2_section_fallback_shape_b`
Expected: unknown — this is the spike.

- [ ] **Step 3: Decision gate**

If PASSED: commit (`git add tests/integration/test_goto_terminator_investigation.py && git commit -m "spike: candidate-2 SECTION fallback fixes GO TO-reachable terminator (shape b)"`).

If FAILED: do not commit this test.

Either way, proceed to Task 5 — this is the last spike task regardless of outcome.

---

## Task 5: Write up findings

Always executed, regardless of which prior tasks passed or failed. Updates both design docs with the confirmed outcome, replacing every "unverified"/hedged claim this investigation was scoped to settle.

**Files:**
- Modify: `docs/2026-07-10-goto-reachable-terminators-design.md`
- Modify: `docs/2026-07-08-goback-stop-run-support-design.md`
- Modify: `README.md` (only if a working candidate changes the known-limitations section)

**Interfaces:**
- Consumes: the pass/fail verdicts and any generated-C evidence recorded by Tasks 1-4.
- Produces: nothing consumed by later tasks — this is the terminal task of this plan.

- [ ] **Step 1: Update `docs/2026-07-10-goto-reachable-terminators-design.md`**

Replace the "Root-cause hypothesis (unverified)" section's content with the confirmed finding from Task 1 Step 3's generated-C comparison (whichever it turned out to be — confirmed, refuted, or a different mechanism entirely). Replace the "Decision gate" section's two bullet outcomes with which one actually happened, naming the specific candidate(s) and shape(s) that passed or failed. If any candidate passed for both shapes, add a new top-level "## Outcome" section stating that a follow-up implementation plan is needed (extending `mockymock/analysis/refusal.py`'s `find_terminator_plans` and the splicer to stop refusing this shape and apply the proven transform instead) — do not write that follow-up plan here, this task only records the finding. Carry the "Risks" section's caveat (reliance on undocumented `cobc` behavior, pinned-toolchain-only) into this Outcome section explicitly, since it's the first thing the follow-up plan's author needs to see. If no candidate passed, state plainly that the refusal in `mockymock/analysis/refusal.py` (`UNSUPPORTED_TERMINATOR_LAYOUT` for `GO TO`-reachable chains) is confirmed permanent, with the root cause now known rather than merely observed.

- [ ] **Step 2: Update `docs/2026-07-08-goback-stop-run-support-design.md`**

In the "Verified facts (six spikes...)" table, row #4 ("Terminator's paragraph entered via GO TO... | Broken."), add a footnote or trailing sentence pointing to `docs/2026-07-10-goto-reachable-terminators-design.md` for the follow-up investigation and its outcome, so a future reader of the original design doc doesn't stop at "Broken" without discovering this investigation happened.

- [ ] **Step 3: Update `README.md`'s known-limitations section (only if a candidate passed)**

Find the existing bullet describing GO-TO-reachable terminators as refused (added when Approach B shipped — search for "GO TO" in `README.md`). If a candidate proved viable for both shapes, soften or remove that bullet according to what was actually proven (e.g., if only shape (a) works but shape (b) doesn't, say so precisely — do not claim broader support than what Tasks 1-4 actually demonstrated). If no candidate passed, leave `README.md` unchanged — the existing bullet is still accurate.

- [ ] **Step 4: Commit the docs updates**

```bash
git add docs/2026-07-10-goto-reachable-terminators-design.md docs/2026-07-08-goback-stop-run-support-design.md README.md
git commit -m "docs: record GO TO-reachable terminator investigation outcome"
```

(Omit `README.md` from the `git add` if Step 3 made no changes to it.)
