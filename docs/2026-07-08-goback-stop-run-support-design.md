# GOBACK / STOP RUN Support — Design

Date: 2026-07-08 (revised)
Status: design approved (second brainstorming session, Approach B); ready for implementation planning

## Revision note

The originally approved design (Approach A: redirect via `GO TO`, dispatched
on `UT-CURRENT-CASE`) was **disproven by its own verification spike** and
never implemented. See "Approach A — rejected, kept for history" below for
the concrete evidence. This document now describes Approach B (propagate an
early-exit flag via `EXIT PARAGRAPH`/`EXIT SECTION`), validated by six
separate compile-and-run spikes against the real GnuCOBOL 3.2 toolchain
before being written up here. No implementation code exists yet for either
approach — a plan (`docs/superpowers/plans/2026-07-08-goback-stop-run-support.md`)
was written for Approach A and must be discarded/rewritten for Approach B.

## Problem

Unchanged from the original design — restated briefly. A `.cut` test case's
`PERFORM` target running into `STOP RUN` or `GOBACK` — directly, or
transitively through any paragraph it performs — terminates the whole
compiled test binary immediately, before that case's own checks run and
before any later test case in the suite gets a chance to run. This blocks
testing a program's real main paragraph, which almost always ends this way;
every real-world example in this repo (`DEPTMQP`/`DEPTMQC`/`ACCTPRG`) routes
around it by targeting sub-paragraphs instead. See the original design's
"Problem" section (git history, or the superseded content this revision
replaces) for the full worked `TERMDEMO` crash transcript.

## Scope decision (unchanged from the original brainstorming session)

Real support was chosen over a cheaper fail-fast-only refusal, fail-closed
on unverified/ambiguous shapes, no `STOP RUN GIVING`/`GOBACK RETURNING`
return-code capture, `EXIT PROGRAM` confirmed out of scope as a transform
target (verified: no-op when `PERFORM`ed, see below).

## Approach A — rejected, kept for history

**The idea:** split each `UT-TESTCASE-NNN` into a setup half and a
`UT-TESTCASE-NNN-CHECK` half, performed as `PERFORM UT-TESTCASE-NNN THRU
UT-TESTCASE-NNN-CHECK`; replace a reachable terminator with `EVALUATE
UT-CURRENT-CASE / WHEN "NNN" GO TO UT-TESTCASE-NNN-CHECK`.

**Why it failed, verified concretely:** a spike mirroring the *exact*
driver skeleton (`SUITE-PARA` performs `SETUP-PARA THRU CHECK-PARA`;
`SETUP-PARA` performs `TARGET-PARA`; `TARGET-PARA` does `GO TO CHECK-PARA`
in place of the terminator; `CHECK-PARA` sits immediately after
`SETUP-PARA`) compiled clean but **never returned to `SUITE-PARA`** — it
looped between `CHECK-PARA` and `TARGET-PARA` printing `CHECK-RAN`
until the 30s harness timeout killed it (exit 124). An earlier, more
deeply nested variant of the same shape segfaulted instead (exit 139,
"attempt to reference invalid memory address").

**Root cause:** GnuCOBOL's `PERFORM` return mechanism is tied to the actual
out-of-line `PERFORM` call chain, not to "whichever `THRU` range is
lexically active." `GO TO` bypasses that bookkeeping entirely. The
driver's own `PERFORM {target}` call (`UT-TESTCASE-NNN` performing the
program's target paragraph) is *itself* exactly this kind of pending,
not-yet-returned nested call — so the failure is structural, present for
*every* test case, not just deeply nested ones. No positional fix exists:
`PERFORM {target} THRU {check}` (putting target and check in one range,
avoiding the nested-call problem entirely) doesn't work because check
paragraphs are necessarily generated near the top of the file while the
target is the user's own code, physically elsewhere — an unavoidably
backwards range for arbitrary target paragraphs.

## Approach B — chosen

Instead of jumping anywhere, propagate an "early exit" flag back up through
the *real* `PERFORM` call chain, using `EXIT PARAGRAPH`/`EXIT SECTION` at
every level instead of `GO TO`. `EXIT PARAGRAPH`/`EXIT SECTION` never jump
to an unrelated location — they end the *current* paragraph/section early
and return through the same well-formed "return to whoever actually
performed me" mechanism that ordinary, uninstrumented COBOL already relies
on everywhere. Nothing is ever abandoned, so there is no pending-frame
confusion.

**Consequence: no `driver.py` restructuring at all.** No paragraph split,
no `THRU` range. `UT-TESTCASE-NNN`'s existing `EXPECT`/`VERIFY` checks stay
exactly where they are today, right after `PERFORM {target}` — because once
the flag has propagated all the way back up through every intermediate
`PERFORM`, that's precisely where control lands next, via the ordinary
return path.

### Verified facts (six spikes against the pinned GnuCOBOL 3.2 toolchain)

| # | Shape | Result |
|---|---|---|
| 1 | Terminator directly in the paragraph a test's `PERFORM` reaches, replaced with nothing (bare removal, no `EXIT` even needed since it's the paragraph's last statement) | **Works.** Two sequential cases both PERFORM a shared paragraph whose `STOP RUN` is simply deleted; both cases' checks ran correctly, suite completed normally. |
| 2 | Terminator nested inside an `IF`, with a `DISPLAY` after the `IF` in the same paragraph, replaced with `MOVE "Y" TO UT-EARLY-EXIT` + `EXIT PARAGRAPH` | **Bare removal is unsafe here** (confirmed separately: the trailing `DISPLAY` ran, which a real terminator would have prevented) — **but the flag + `EXIT PARAGRAPH` replacement correctly suppresses it.** |
| 3 | Terminator behind one intermediate `PERFORM` (`MIDDLE-PARA` performs `INNER-TERMINATOR-PARA`), with a `DISPLAY` in `MIDDLE-PARA` after that `PERFORM` | **Bare removal is unsafe here too** (confirmed: the trailing `DISPLAY` ran) — **`IF UT-EARLY-EXIT = "Y" EXIT PARAGRAPH END-IF` inserted right after `MIDDLE-PARA`'s `PERFORM` correctly suppresses it**, and control correctly returns further up the chain. |
| 4 | Terminator's paragraph entered via `GO TO` (not `PERFORM`) from the paragraph the test's `PERFORM` actually reaches | **Broken.** `EXIT PARAGRAPH` does not correctly resolve the return point when the paragraph it's issued from was entered via `GO TO` — execution silently stops after the terminator's own code; the caller's checks never run (exit 0, but incomplete output, no crash — a *silent* failure, worse than a loud one). Follow-up investigation ran 2026-07-10 (`docs/2026-07-10-goto-reachable-terminators-design.md`) and confirmed no fix was found among the two candidate mechanisms tried — the refusal for this shape is permanent for now; see that doc's "## Outcome" section before assuming this is unexplored. |
| 5 | Terminator is the first paragraph of a `PERFORM`ed `SECTION` (with a second paragraph in that section that must not run), replaced with `EXIT SECTION` | **Works.** The second paragraph correctly did not run; control correctly returned to the real caller. |
| 6 | Terminator behind three levels of intermediate `PERFORM` (each with its own flag-check-and-`EXIT PARAGRAPH` after its `PERFORM`) | **Works**, both intermediate siblings correctly suppressed, all the way back to the suite level. |

### Design consequence of #4 (the one broken case)

**A terminator is only safely neutralizable when its enclosing paragraph,
and every paragraph in the `PERFORM` chain between it and the test's own
target, is reached *exclusively* via plain out-of-line `PERFORM` — never
via `GO TO`, anywhere in the program.** This can't be narrowed to "on the
path this test happens to take" because that's a runtime fact, not a
static one; the only sound rule is "never a `GO TO` target at all."

### Design consequence of #5 (deferred despite working)

`SECTION` support is scoped **out of v1**, even though the mechanism works,
because safely distinguishing "the section's own first paragraph, reached
via `PERFORM <section-name>`" from "a later paragraph in that section,
reached only by fall-through" is real additional analysis complexity, and
it's not the shape that motivated this feature — real corpus
`0000-MAIN-PROCESS`-style paragraphs aren't wrapped in `SECTION`s. Documented
as future work, reusing the same detection machinery once there's demand.

## Design (Approach B) — detailed

### Detection: the "safe chain" check

Reuses the existing reachability BFS unchanged to find candidate terminator
sites per test case (same as Approach A's detection layer — `mock_surface.py`
still gains `StopStatement`(RUN-form)/`GobackStatement` as detected,
category-`None` sites, same shape as the existing `CancelStatement`
handling).

New analysis on top: for each reachable terminator, walk backward from its
enclosing paragraph through the chain of paragraphs that `PERFORM` it (and
whoever performs those, up to the test's own `perform_target`). This chain
is about *how the terminator's paragraph is reached*, not about where the
terminator sits *within* that paragraph — spike #2 above already confirms
the terminator itself can be nested inside a conditional in its own
paragraph. Every link in the chain — i.e. every `PERFORM` statement that
performs the next paragraph on the way to the terminator's paragraph — must
be:

- a plain `PERFORM <paragraph-name>` statement (no `THRU`, no section
  target),
- unconditional and top-level in its own paragraph (not nested inside an
  `IF`/`EVALUATE` — deferred, see below),
- and the paragraph it targets must **never** appear as a `GO TO` target
  anywhere in the whole program (whole-program check, not just within the
  reachable set — a `GO TO` edge that exists anywhere is a standing risk
  regardless of whether this particular test's execution happens to take
  it).

Any failure refuses with a new code (`UNSUPPORTED_TERMINATOR_LAYOUT`,
reusing the naming precedent from `UNSUPPORTED_MOCK_TARGET_LAYOUT`/
`UNSUPPORTED_LINKAGE_LAYOUT`) rather than attempting a possibly-wrong
transform.

**Deferred to future work, refused in v1:** the terminator's own paragraph
being a `SECTION`'s member; any *intermediate chain-link* `PERFORM`
(not the terminator itself — see the note above) nested inside a
conditional body, which needs the same nested-scope span validation
(`collect_scope_map`/`annotate_nested_sites`) boundary sites already use,
to know where inside the conditional block to insert the check — not
needed for v1's plain-chain-only scope.

### Splice mechanics

Two operations, both new, neither restructuring `driver.py`:

**At the terminator:** replace `STOP RUN`/`GOBACK` with `MOVE "Y" TO
UT-EARLY-EXIT` followed by `EXIT PARAGRAPH`. Unlike Approach A, this
replacement is **identical regardless of which test case is running** — no
`EVALUATE UT-CURRENT-CASE` dispatch needed here at all, since it doesn't
need to know *where* to jump. Uses the existing `stub_writer.comment_and_replace`
primitive exactly as every other terminator/boundary replacement does.

**After every intermediate `PERFORM` in the chain:** insert (not replace)
`IF UT-EARLY-EXIT = "Y" EXIT PARAGRAPH END-IF` immediately following the
existing statement, leaving the original `PERFORM` untouched. This needs a
**new low-level splice primitive** — every existing splice in this codebase
(`comment_and_replace`) replaces a statement's span; this one needs to
*keep* the original text and add lines after it. New function,
`insert_lines_after(lines, line_number, new_lines)`, alongside
`comment_and_replace` in `stub_writer.py`.

**Guardrail for the insertion itself:** the intermediate `PERFORM`
statement must own its own source line (reusing the existing top-level
own-line check, `source_map`'s `_top_level_site_problem`, applied to
`PerformStatement` nodes) — if it shares a line with other code (e.g.
`PERFORM 1000-DO-WORK MOVE 5 TO WS-X.` as one sentence), inserting the
check after that whole line would let the sibling statement run
unconditionally before the check ever fires. Refuses
`UNSUPPORTED_TERMINATOR_LAYOUT` (same code) if violated.

### `driver.py` — the only change

- `UT-EARLY-EXIT PIC X VALUE "N"` declared once in `build_driver`'s
  `working_storage` list.
- Reset to `"N"` in the existing per-case setup, alongside where tally
  fields already get zeroed (`_build_testcase_paragraph`, one new line).
- Nothing else changes. No paragraph split, no new `THRU` usage, no
  dispatch-block generation keyed on case IDs for this feature.

### Testing

- Unit (Docker-free): safe-chain detection tests (qualifying multi-level
  `PERFORM`-only chain; each of the four deferred/broken shapes —
  `GO TO`-reached, `SECTION`-scoped, conditional-nested intermediate
  `PERFORM`, line-sharing `PERFORM` — each asserting
  `UNSUPPORTED_TERMINATOR_LAYOUT`); `insert_lines_after` unit tests
  (`stub_writer`-style, verifying original lines are preserved verbatim);
  driver.py tests for the `UT-EARLY-EXIT` declaration/reset.
- Integration (`@requires_docker`): the six spike shapes above as permanent
  regression fixtures (`test_splicer_linkage.py`-style — this is exactly
  the kind of empirically-load-bearing fact that deserves a permanent
  compile-and-run test, not just a design-session throwaway script); an
  end-to-end `TERMDEMO`-based test proving `[PASS]` (not `[CRASH]`) and a
  later test case in the same suite still running.
- A worked `examples/real-world/` addition once proven: re-target
  `ACCTPRG`'s `0000-MAIN-PROCESS` (currently avoided specifically because
  of this limitation) at its real entry point.

### Docs sync

Same set as Approach A's plan named: `README.md`'s known-limitation
section, `.okf/analysis.md`/`.okf/splicer.md` concept rows (now describing
the flag-propagation mechanism and `insert_lines_after`, not the dispatch/
`THRU`-split mechanism), `docs/2026-07-06-real-world-readiness-audit.md`
Finding 3 marked resolved, `docs/2026-07-08-ims-linkage-support-design.md`'s
worked-example note updated once `ACCTPRG` is re-targeted.

## Out of scope

- Everything Approach A's design already scoped out: `STOP RUN GIVING`/
  `GOBACK RETURNING` return-code capture, `EXIT PROGRAM` as a transform
  target (confirmed no-op, see the original scope-decision verification),
  driving a program's multi-record read loop with different mock data per
  iteration.
- `SECTION`-scoped terminators (mechanism verified safe, deferred for
  analysis-complexity reasons — see above).
- Intermediate `PERFORM` statements nested inside a conditional body
  (needs the nested-scope span machinery; deferred, not attempted).
- Terminators reachable via `GO TO` anywhere in the chain (confirmed
  unsafe with this mechanism — refused, not a "future work" item unless a
  different mechanism is found for this specific shape).
- Terminators reachable only through the target paragraph of a looping
  `PERFORM ... UNTIL`/`VARYING`/`TIMES` (confirmed unsafe with this
  mechanism, 2026-07-09: `EXIT PARAGRAPH` only ends the current loop
  iteration, not the loop construct, so the flag never stops the loop
  early — a synthetic spike proved the neutralized program ran extra
  unwanted iterations past where the real terminator would have stopped
  it. `_plain_perform_edges_from` now excludes these edges
  (`perform_type != "SIMPLE"`), so such a terminator refuses via the
  existing "not via a plain chain" check. Not originally considered by
  this design — surfaced while qualifying `ACCTPRG` for Task 10's
  re-target, whose own loop is safe because its terminator sits outside
  the loop entirely.).
  **Correction (final review, 2026-07-09):** this `perform_type` guard
  only actually discriminates the out-of-line `UNTIL`/`TIMES` forms and
  the inline `VARYING`/`UNTIL`/`TIMES` forms (all correctly tagged by
  `cobolparser`). The **out-of-line** form —
  `PERFORM paragraph-name VARYING var FROM x BY y UNTIL cond` — is NOT
  parsed by `cobolparser`'s out-of-line PERFORM path at all: the trailing
  `VARYING ...` clause is silently dropped, leaving `perform_type`
  mistagged as `"SIMPLE"` (verified directly: `parse_cobol` on this shape
  returns a `PerformStatement` with `perform_type='SIMPLE'`,
  `target_paragraph` set, `thru_paragraph=None` -- indistinguishable from
  a genuine plain PERFORM to `_plain_perform_edges_from`). What actually
  prevents this from reaching the terminator logic today is a completely
  unrelated mechanism: cobolparser also emits a
  `"Unparsed tokens starting at 'VARYING' ... content dropped from the
  AST"` warning for this shape, and `check_whole_program` refuses any
  program with a parse warning (`PARSE_WARNING`) before
  `find_terminator_plans` ever runs (confirmed via `mockymock run`
  end-to-end: exit 1, `refused (PARSE_WARNING): ... Unparsed tokens
  starting at 'VARYING'`). This is a real but *accidental* safety net --
  if cobolparser is ever fixed to parse out-of-line `VARYING` without
  also correctly tagging `perform_type='VARYING'`, this hole reopens
  silently. See the pinning regression test in
  `tests/unit/test_terminator_reachability.py` and
  `tests/integration/test_terminator_support.py` that asserts the
  refusal happens via `PARSE_WARNING` specifically, so a future
  cobolparser change that removes the warning without fixing the tagging
  turns this into a loud test failure instead of a silent regression.
