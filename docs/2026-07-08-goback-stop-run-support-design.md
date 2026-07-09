# GOBACK / STOP RUN Support — Design

Date: 2026-07-08
Status: design approved (brainstorming session); verification spike required before implementation begins

## Problem

A `.cut` test case's `PERFORM` target running into `STOP RUN` or `GOBACK` —
directly, or transitively through any paragraph it performs or jumps to via
`GO TO` — terminates the whole compiled test binary immediately. That
happens before the case's own `EXPECT`/`VERIFY` checks run, and before any
later test case in the same suite gets a chance to run at all.
`mockymock run` reports this honestly as `[CRASH]` rather than a misleading
`[PASS]` (`report/results.py` `crashed`/`ended`), but the underlying
limitation is unchanged: **you cannot test any paragraph that reaches a
program terminator.**

This is not a rare edge case. Real batch programs' main entry points almost
always end this way, and it shows up as the dominant hidden constraint on
"does mockymock work on a given program": every real-world example that
exists today routes around it rather than solving it —
`examples/real-world/DEPTMQP`/`DEPTMQC` explicitly "trade loop-iteration
depth for harness safety" by targeting single sub-paragraphs
(`docs/2026-07-06-realworld-cobol-examples-design.md`, "Driving strategy"),
and the new `examples/real-world/ACCTPRG` targets sub-paragraphs
specifically to avoid `0000-MAIN-PROCESS`'s `GOBACK`
(`docs/2026-07-08-ims-linkage-support-design.md`, "Worked example"). No
example in this repo tests a program's actual top-level driver loop.

Confirmed concretely in this design session: a minimal program
(`0000-MAIN-PROCESS. PERFORM 1000-DO-WORK STOP RUN.`) with a `.cut` case
`PERFORM`ing `0000-MAIN-PROCESS` produces **zero refusals** from today's
`check_whole_program`/`check_test_case` — it compiles clean and crashes at
`STOP RUN` before its own `EXPECT WS-RESULT TO BE 42` ever runs. See the
worked example below for the real, generated spliced output.

`analysis/refusal.py:24`'s existing comment ("covered by the documented
STOP RUN limitation") and `README.md`'s "Known limitation" section
currently only name `STOP RUN` — `GOBACK` is not mentioned anywhere in
user-facing docs, though it is caught by the same crash-detection mechanism
(missing `CASE NNN END` marker) since that check is terminator-agnostic.

## Scope decision (from this session's brainstorming)

Real support was chosen over a cheaper fail-fast-only refusal: a test
case's target should be able to reach `STOP RUN`/`GOBACK` and still get its
`EXPECT`/`VERIFY` checked, with later test cases in the suite still
running normally afterward. Also decided:

- Fail-closed: unverified/ambiguous terminator shapes refuse rather than
  attempt a possibly-wrong transform, matching this codebase's consistent
  discipline (`check_linkage_layout`, the nested-mock-target rules).
- `STOP RUN GIVING`/`GOBACK RETURNING` return codes are **not** captured or
  exposed to `.cut` assertions in this pass — out of scope, to keep this
  change scoped to the actual pain point rather than growing the DSL at
  the same time.
- `EXIT PROGRAM` is out of scope as a *transform target* — per the COBOL
  standard it is a no-op when the enclosing program is the primary run
  unit (never `CALL`ed), which is exactly mockymock's `PERFORM`-driven
  model. This needs an empirical verification spike (below) to confirm and
  document, not a code change.

## Verification spike required before implementation

Two claims this whole design depends on, neither yet confirmed against the
real GnuCOBOL 3.2 toolchain — must be proven with a crafted minimal program
compiled and run in the `mockymock-cobc` container before any splicer code
is written, the same way the IMS/LINKAGE fix opened with a crash-repro
spike:

1. **The THRU-range return invariant.** `PERFORM X THRU Y` must return
   control to its caller when execution reaches the *end of the named
   range* — regardless of whether that end was reached by ordinary
   fall-through (no terminator hit) or by a `GO TO` jump into the range
   from arbitrarily deep inside a nested `PERFORM` chain. The codebase
   already assumes a closely related fact for the ordinary
   `... GO TO MAIN-EXIT ... MAIN-EXIT. EXIT.` idiom (PERFORM THRU
   reachability, `.okf/analysis.md`), but this design needs the
   GO-TO-from-nested-PERFORM-depth case specifically, which has not been
   tested. If this does not hold, Approach A (below) is unsound and the
   design needs rework.
2. **`EXIT PROGRAM` is a no-op when the program is `PERFORM`ed, not
   `CALL`ed.** Compile and run a minimal program where a `PERFORM`ed
   paragraph executes `EXIT PROGRAM` mid-flow, and confirm execution
   continues to the next statement rather than terminating. If this is
   *not* a no-op under GnuCOBOL 3.2, `EXIT PROGRAM` needs to be folded into
   this design as a third terminator alongside `STOP RUN`/`GOBACK`.

## Approaches considered

**A. Redirect via `GO TO`, dispatched on `UT-CURRENT-CASE` (chosen).** Split
each `UT-TESTCASE-NNN` paragraph into `UT-TESTCASE-NNN` (setup + `PERFORM`
target) and `UT-TESTCASE-NNN-CHECK` (the existing `EXPECT`/`VERIFY` logic).
The suite driver performs `PERFORM UT-TESTCASE-NNN THRU UT-TESTCASE-NNN-CHECK`
instead of a single-paragraph `PERFORM`. Every `STOP RUN`/`GOBACK` reachable
from at least one test case is replaced with an `EVALUATE UT-CURRENT-CASE`
block whose branches `GO TO` that case's own `-CHECK` paragraph. This reuses
two mechanisms the codebase already has: the `GO TO MAIN-EXIT ... MAIN-EXIT.
EXIT.` idiom already assumed sound by the reachability BFS, and the
per-site `EVALUATE UT-CURRENT-CASE` dispatch pattern
(`injector.build_site_dispatch`) already used for every other mocked
boundary. Handles a terminator at any `PERFORM` nesting depth from the
test's target — not just one level.

**B. Substitute `EXIT PARAGRAPH`/`EXIT SECTION` in place.** Rejected as
insufficient alone. Simpler splice (a text swap, no paragraph
restructuring), but semantically only unwinds *one* `PERFORM` frame. If the
terminator sits behind more than one level of nested `PERFORM` from the
test's target — the common shape, e.g. a main loop performs an
error-handling paragraph that does `STOP RUN` — this returns control to the
wrong place and silently continues executing code that should have
terminated: a false-green risk, the exact failure class this codebase works
hardest to avoid (`docs/2026-07-06-real-world-readiness-audit.md` Finding
4). Would need its own depth-zero guardrail to be safe, at which point it
is about as much implementation work as Approach A for a strictly narrower
result.

**C. Isolate each test case in its own process.** Rejected. Would stop one
case's crash from taking down the rest of the suite, but does not solve the
actual problem: the crashing case's own `EXPECT`/`VERIFY` still never runs,
because that code lives after the `PERFORM` in the same compiled unit
regardless of process boundaries. Also inverts the documented "one binary
serves the whole suite" architectural invariant (`.okf/splicer.md`,
"Global Constraint") for no corresponding benefit.

## Design (Approach A)

### Detection (analysis layer)

`mock_surface.py` gains `StopStatement`/`GobackStatement` as a new
detected-but-special category, the same shape as the existing `CancelStatement`
treatment (`category=None`, a label, and location data) — both modules see
these through the one existing statement walk, no separate traversal.

`refusal.py` reuses the existing `_reachable_paragraphs` BFS unchanged: for
each test case, find every terminator site reachable from
`perform_target`/`perform_thru`. Because the BFS already models `PERFORM`,
`PERFORM <section>`, and `GO TO` edges (the 2026-07-07 reachability-hole
remediation), a terminator behind any of those constructs — including the
program's own `GO TO MAIN-EXIT`-style idiom — is found for free, no new edge
modeling needed. Sites not reachable from any test case are left untouched
entirely, matching the existing "unmocked non-EXEC sites are left alone"
principle — this keeps the transform's blast radius to exactly what a
`.cut` suite actually exercises.

### Guardrails

Every reachable terminator site is validated through the same span-checking
machinery every other boundary site already goes through — no new span
logic:

- Top-level sites: the existing "owns its line" guard
  (`source_map`'s top-level own-line check).
- Nested sites (inside `IF`/`EVALUATE`/inline `PERFORM`): the existing
  `collect_scope_map`/`annotate_nested_sites` validation.

A site that fails either check refuses with a new code,
`UNSUPPORTED_TERMINATOR_LAYOUT`, rather than transforming — same fail-closed
discipline as `UNSUPPORTED_MOCK_TARGET_LAYOUT`/`UNSUPPORTED_NESTED_MOCK_TARGET`/
`UNSUPPORTED_LINKAGE_LAYOUT`. No guardrail is needed for interaction with
the target program's own control-flow idioms (THRU ranges, GO-TO-to-exit
patterns) — those compose for free through the reused BFS and reused span
validation, per the "Detection" section above.

### Transform

`driver.py`:
- `_build_testcase_paragraph` splits into `UT-TESTCASE-NNN` (reset → move
  case ID → zero tallies → start marker → `setup_moves` → `PERFORM
  {target}`) and a new `UT-TESTCASE-NNN-CHECK` (today's `EXPECT`/`VERIFY`
  checks → end marker).
- The suite paragraph's `PERFORM UT-TESTCASE-{index:03d}` becomes
  `PERFORM UT-TESTCASE-{index:03d} THRU UT-TESTCASE-{index:03d}-CHECK`.
- This must hold even for test cases with **no** reachable terminator —
  the THRU form is used uniformly so that normal (non-crashing) cases keep
  their exact current behavior (fall through from `NNN` into `NNN-CHECK`
  unchanged), verified by the existing test suite passing unmodified.

`injector.py` gains a new dispatch-block builder alongside
`build_site_dispatch`, one per validated terminator site: an `EVALUATE
UT-CURRENT-CASE` with one `WHEN "NNN"` branch per test case that can reach
this site (each doing `GO TO UT-TESTCASE-NNN-CHECK`), and a `WHEN OTHER`
matching existing precedent exactly — loud `DISPLAY "__MOCKYMOCK__ ERROR:
..."` + `ADD 1 TO UT-FAIL-COUNT`, falling through rather than hard-stopping
— since the refusal gate is expected to make this branch unreachable in
practice, same as every other `WHEN OTHER` in the codebase.

The `UT-TESTCASE-NNN-CHECK` paragraph name is derived inline in `driver.py`
(deterministic, reusing the existing `{index:03d}` zero-padding convention
already used for `UT-TESTCASE-NNN` itself) — `naming.py` is unaffected; it
owns only `TallyRegistry`'s `(category, key)` tally-field naming, which this
design does not touch.

The original `STOP RUN`/`GOBACK` line(s) are commented out via the existing
`stub_writer.comment_and_replace` — no new low-level splice primitive.

### Worked example

See the full before/after transcript produced in this design session
(program `TERMDEMO`, a `.cut` targeting `0000-MAIN-PROCESS` which performs a
mocked-`CALL` sub-paragraph then hits `STOP RUN`). Confirmed today's real
generated output crashes with zero refusals fired; the proposed output
differs in exactly three places: the suite's `PERFORM ... THRU ...`, the
`UT-TESTCASE-001`/`UT-TESTCASE-001-CHECK` split, and the `STOP RUN` →
`EVALUATE UT-CURRENT-CASE` / `GO TO UT-TESTCASE-001-CHECK` replacement.
This transcript should be preserved as the first fixture for the unit tests
below rather than re-derived.

### Testing

- Unit (Docker-free): detection/refusal tests mirroring `test_refusal.py`'s
  `check_linkage_layout` coverage (qualifying shape; nested/shared-line
  shapes that must refuse `UNSUPPORTED_TERMINATOR_LAYOUT`; a terminator
  behind a `GO TO`/`PERFORM <section>` edge, proving BFS reuse works
  end-to-end); driver/injector splice tests (`test_driver.py`/
  `test_injector.py`-style) built directly from the `TERMDEMO` transcript
  above; a regression test asserting every existing non-terminator `.cut`
  fixture still generates byte-identical `EXPECT`/`VERIFY` logic (just
  relocated into a `-CHECK` paragraph).
- Integration (`@requires_docker`): one test per verification-spike claim
  (THRU-range-return-via-GO-TO, `EXIT PROGRAM` no-op) as its own minimal
  compiled-and-run fixture, `test_splicer_linkage.py`-style; an end-to-end
  `TERMDEMO`-based integration test proving the case now reports `[PASS]`
  (not `[CRASH]`) and a later test case in the same suite still runs.
- A worked `examples/real-world/` addition once proven: re-target one of
  the existing sub-paragraph-only examples (`ACCTPRG`'s `0000-MAIN-PROCESS`,
  which ends in `GOBACK`, is the natural candidate — it exists specifically
  to demonstrate this workaround today) at its real entry point, replacing
  the sub-paragraph workaround.

### Docs sync

- `README.md`: replace the "Known limitation: STOP RUN" section — either
  remove it (if this ships) or expand it to also name `GOBACK` (if only
  the fail-fast alternative ships first).
- `.okf/analysis.md`, `.okf/splicer.md`: new concept rows for
  `UNSUPPORTED_TERMINATOR_LAYOUT`, the terminator detection/reuse-of-BFS
  behavior, and the `UT-TESTCASE-NNN`/`-CHECK` paragraph split.
- `docs/2026-07-06-real-world-readiness-audit.md`: Finding 3 should be
  marked resolved (or partially resolved, if scope narrows during
  implementation) once this ships.
- `docs/2026-07-08-ims-linkage-support-design.md`'s "Worked example"
  section, which currently justifies avoiding `0000-MAIN-PROCESS` by
  citing this exact limitation, should be updated once `ACCTPRG` is
  re-targeted per the testing section above.

## Out of scope

- `STOP RUN GIVING`/`GOBACK RETURNING` return-code capture or new `.cut`
  assertion syntax.
- `EXIT PROGRAM` as a transform target (expected no-op; verify and
  document only — see spike above).
- Driving a program's multi-record read loop with different mock data per
  iteration ("drive the real loop, not just survive its terminator") — a
  separate, larger ambition. This design's scope is narrower and more
  mechanical: a terminator reachable from a test's target must no longer
  kill the suite. That said, it is exactly the thing blocking the
  larger ambition today, since a real main-loop paragraph almost always
  ends in one.
