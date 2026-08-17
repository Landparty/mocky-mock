# GO TO-to-EXIT-Paragraph Simplification — Design

Date: 2026-08-17
Status: **implemented, NOT yet verified against real GnuCOBOL.** No Docker
daemon was available in the session that wrote this feature, and every
fact this codebase has ever asserted about `EXIT PARAGRAPH`/`EXIT SECTION`
semantics has been settled by a compile-and-run spike against the pinned
GnuCOBOL 3.2 toolchain, never by reasoning from documentation alone (see
`docs/2026-07-08-goback-stop-run-support-design.md`'s six spikes and
`docs/2026-07-10-goto-reachable-terminators-design.md`'s two rejected
candidates). This design is built entirely on top of primitives those
spikes already verified (see "Why no new spike is logically required, and
why one is still owed" below), but it has not itself been run against
GnuCOBOL. Treat `find_goto_exit_plans`/`GotoExitPlan` as unverified until
`docs/YYYY-MM-DD-goto-exit-paragraph-spike.md` (not yet written) records a
real compile-and-run result. See ".okf/log.md" for the dated entry noting
this status.

## Problem

The idiomatic mainframe "early exit via GO TO" pattern:

```cobol
MAIN-PROCESS.
    PERFORM STEP-A
    IF SOME-COND
        GO TO MAIN-EXIT
    END-IF
    PERFORM STEP-B.
MAIN-EXIT.
    EXIT.
```

is common enough that `.okf/analysis.md` calls it out by name ("idiomatic
mainframe shape is `MAIN-PROCESS ... GO TO MAIN-EXIT ... MAIN-EXIT.
EXIT.`"). It causes two, related problems for mockymock today:

1. **A reachable `STOP RUN`/`GOBACK` anywhere on this shape's chain is
   permanently unsupported.** `find_terminator_plans` refuses
   `UNSUPPORTED_TERMINATOR_LAYOUT` the moment `MAIN-PROCESS` (or any
   paragraph on the chain to a terminator) is ever a `GO TO` target
   anywhere in the program (`_go_to_targets`) or is reached only by
   falling through past one (`_go_to_fallthrough_targets`) —
   `docs/2026-07-10-goto-reachable-terminators-design.md` investigated two
   fix candidates for making `EXIT PARAGRAPH` itself work when *issued
   from* a GO-TO-entered paragraph, and both failed empirically. That
   investigation's own refusal message already names the workaround: *"if
   it exists purely as an early exit, an `EXIT PARAGRAPH` in its place
   usually removes the need for the jump entirely"* — but today that
   workaround requires the `.cbl` author to hand-edit their real source.
2. **The `.cut` author must know to write `PERFORM MAIN-PROCESS THRU
   MAIN-EXIT`**, not plain `PERFORM MAIN-PROCESS`, purely so the GO TO has
   a landing pad inside the performed range that lets control return
   correctly on the early-exit path. If they forget, mockymock's
   reachability BFS still analyzes the `GO TO` correctly (it's a real
   flow edge, always followed) — but the *runtime* driver's own `PERFORM
   MAIN-PROCESS` (no THRU) does not, and the compiled test can silently
   run into whatever paragraph happens to follow `MAIN-EXIT` in source
   order instead of returning. **This is a real, currently-unguarded gap,
   discovered while designing this feature — see "Adjacent gap" below.**
   It is out of scope for this design; noted here so it isn't lost.

## Insight

Both rejected candidates in the 2026-07-10 investigation tried to fix the
*target* paragraph's return machinery so a genuine `GO TO` into it would
still unwind correctly. Both failed — the working hypothesis is that
`cobc` only emits frame-stack return machinery for paragraphs that are
*statically* a `PERFORM` target somewhere in the source, and a
GO-TO-only paragraph doesn't get it.

This design does not touch the target paragraph's machinery at all. When
the `GO TO`'s target is provably inert — a paragraph whose entire body is
one bare `EXIT.` and nothing else, i.e. it does no real work regardless of
how it's entered — splice the `GO TO` statement **itself**, at its own
call site, into `EXIT PARAGRAPH`/`EXIT SECTION`. Control never physically
transfers to the target paragraph at runtime at all; the enclosing
paragraph (`MAIN-PROCESS`) just ends early, exactly the primitive
`docs/2026-07-08-goback-stop-run-support-design.md`'s spike #2 already
verified works correctly when issued from inside a conditional, in a
paragraph reached by ordinary `PERFORM`.

## Why no new spike is logically required, and why one is still owed

The transform composes two already-verified facts:

- Spike #2 (goback-stop-run design): `EXIT PARAGRAPH` nested inside an
  `IF`, in a paragraph reached by plain `PERFORM`, correctly suppresses
  the rest of that paragraph and returns to the real caller.
- Spike #5 (same design): the identical mechanism as `EXIT SECTION`,
  issued from a `SECTION`'s first paragraph entered via `PERFORM
  <section-name>`, also correctly returns.

Replacing `GO TO MAIN-EXIT` with `EXIT PARAGRAPH` is exactly spike #2's
shape, with the `GO TO`'s own enclosing paragraph playing the role spike
#2's paragraph played — no new runtime mechanism is introduced. That is
why this is written up as a design rather than a fresh investigation.

It is still **owed** a real spike before anyone trusts it, for the same
reason every fact in this file's neighborhood is: composing two verified
facts is a plausible argument, not a verified one, and this exact feature
area has already burned two rounds of effort on plausible-sounding fixes
(dead-PERFORM coercion, SECTION-scoped fallback) that failed at runtime
despite reasoning that looked sound going in. The specific residual risk
this design's reasoning does NOT cover: whether `cobc`'s codegen for
`EXIT PARAGRAPH` cares about *what statement used to occupy* the line
being replaced (a `GO TO` versus, say, a `MOVE`) — spikes #1-#3/#6 never
tested replacing a `GO TO` specifically, only `STOP RUN`/`GOBACK`. That is
the one genuinely untested variable here, and it is exactly the kind of
thing this codebase's culture would want a compile-and-run spike to rule
out before calling this "supported" rather than "should work."

## Revision note (implementation review)

The first implementation of this design got the span computation wrong
for the textbook idiom itself, and the bug was only caught by actually
running the splice through `mockymock export` on the sample program
below (a step worth doing early, not just at the end): the original text
below claimed *"a GO TO has no nested clause body of its own, so a single
`statement_top_level_problem` check is sufficient, no terminator-style
span lookup needed."* That's true of a GO TO's *own* body -- but wrong
about what it implies for computing its *replacement span* when the GO TO
is itself nested inside something else's clause body (an `IF`, in the
idiom's own motivating example). `statement_span` (correct only for
top-level statements) has no location data for block words like
`END-IF`, so replacing a nested `GO TO`'s span with it silently extended
the comment-out range past the `GO TO`'s own line and swallowed the
enclosing `IF`'s `END-IF` too -- turning `EXIT PARAGRAPH` into an
*unconditional* statement instead of one gated by the `IF`, corrupting
the paragraph's normal (early-exit-not-taken) path. Concretely, for:

```cobol
0000-MAIN-PROCESS.
    PERFORM 1000-DO-WORK
    IF WS-COND = "Y"
        GO TO 0000-MAIN-EXIT
    END-IF
    MOVE 99 TO WS-RESULT.
```

the first implementation produced:

```cobol
0000-MAIN-PROCESS.
    PERFORM 1000-DO-WORK
    IF WS-COND = "Y"
*>      GO TO 0000-MAIN-EXIT
*>  END-IF
    EXIT PARAGRAPH
    MOVE 99 TO WS-RESULT.
```

`MOVE 99 TO WS-RESULT` became permanently unreachable dead code -- exactly
the class of silent, unsound splice this codebase's fail-closed culture
exists to prevent, caught only because `mockymock export`'s output was
actually read, not because any check refused it. Fixed by giving a nested
`GO TO` the same validated-span treatment `_nested_site_span` already
gives a nested `BoundarySite`: a new `nested_statement_span` in
`source_map.py` (the same "stop before the next scope-map boundary" rule,
factored out to work on a raw statement with no `MockCategory`/own-
terminator concept), and a `_go_statements_with_nesting` walker in
`refusal.py` (mirrors `_plain_perform_statements`' `nested`/`in_boundary`
tagging) so `find_goto_exit_plans` can tell which span function applies.
`GotoExitPlan` now carries a precomputed `span` (validated at the same
place the safety checks run) instead of leaving the splicer to re-derive
it. Regression-pinned by
`tests/unit/test_goto_exit.py::test_nested_goto_replacement_does_not_swallow_the_enclosing_end_if`
(confirmed to fail against the original `statement_span`-only approach,
confirmed to pass against the fix). The rest of this document (below)
still describes the intended shape; only the span-computation mechanics
changed from what's written there.

## Detection: `_is_exit_only_paragraph` and `find_goto_exit_plans`

### What counts as an exit-only paragraph

Deliberately the narrowest, most textbook shape — one statement, a bare
`EXIT.` (an `ExitStatement` whose `exit_type` is NOT one of
`PARAGRAPH`/`SECTION`/`PROGRAM` — the same "no-op placeholder" form
`_falls_through`'s docstring already names). An **empty** paragraph body
(no statements at all) is semantically identical for this purpose but is
deliberately NOT included in v1: it is a rarer, easier-to-misclassify
shape (e.g. a paragraph mid-edit, or one whose content the parser
silently dropped — see `_check_unsupported_control_flow`'s neighboring
paranoia about exactly that class of misattribution) and there is no
corpus example needing it. Narrower now, wider later if demand shows up —
same posture the SECTION-scoped terminator work has followed throughout.

### What counts as a safely-neutralizable GO TO

A `GoStatement` qualifies only when **all** of:

- Single, unconditional target: `depending_on_variable is None`, and
  exactly one name in `target_paragraphs` (or `target_paragraph` alone,
  no list) — a computed `GO TO ... DEPENDING ON` is excluded because it
  might not go to the exit-only paragraph at all, and a multi-target
  plain `GO TO A B` is unresolvable to "always this one paragraph."
- That one target name is an exit-only paragraph (above).
- The statement owns its own source line and a validated replacement
  span exists for it: a top-level GO TO uses
  `statement_top_level_problem`/`statement_span` (the same helpers
  `find_terminator_plans` reuses for intermediate `PERFORM`
  statements); a GO TO nested inside an `IF`/`EVALUATE` branch — the
  idiom's own motivating shape — uses `nested_statement_span` instead,
  the same "stop before the next scope-map boundary" rule
  `_nested_site_span` applies to `BoundarySite`s. See "Revision note"
  above: the first implementation used `statement_span` unconditionally
  and silently swallowed the enclosing `END-IF` for the nested case.
- Its **enclosing paragraph** (found by walking `_all_paragraphs` and
  checking statement identity, since `GoStatement` carries no back-
  pointer) is itself safe to issue `EXIT PARAGRAPH`/`EXIT SECTION` from —
  reusing the exact preconditions `find_terminator_plans` already
  enforces on a terminator's own paragraph: not in `_go_to_targets`, not
  in `_go_to_fallthrough_targets`, and either a top-level paragraph or the
  first paragraph of a `_safe_section_entry_points` entry.

### All-or-nothing per target paragraph

`_go_to_targets`/`_go_to_fallthrough_targets` are whole-program
properties: a paragraph is "a GO TO target" if **any** GO TO anywhere
still names it. Neutralizing 3 of 4 `GO TO MAIN-EXIT` sites and leaving
the 4th alone would leave `MAIN-EXIT` exactly as hazardous as before — the
whole point is to make the target paragraph stop being a real GO TO
target at all. So this is evaluated per candidate exit-only paragraph,
atomically: if **every** GO TO naming it qualifies, all are neutralized
together; if even one fails a precondition, **none** of that paragraph's
GO TOs are touched, and today's behavior (including
`UNSUPPORTED_TERMINATOR_LAYOUT` if something downstream needs it) is
unchanged. This is a "plan or silently skip" shape, not "plan or
refusal": declining to apply this optimization is always safe — the
program compiles and runs exactly as it does today — so an ineligible
candidate is reported as an informational note (surfaced the same way
`--verbose` already surfaces other transform notes), never a
`RefusalReason` that would block the run.

### Wiring into `find_terminator_plans`

`find_terminator_plans` computes `goto_exit_plans` first (module-level
call before its own `go_to_targets`/`go_to_fallthrough` computation), then
subtracts every fully-neutralized target paragraph's name from
`_go_to_targets(program)`'s result before deriving `go_to_fallthrough`
from the narrowed set — so a terminator chain that only failed because of
this exact idiom now qualifies for the existing flag-propagation
mechanism, unmodified.

## THRU elision — separate, additionally gated

Once every `GO TO` into `MAIN-EXIT` is neutralized, does a `.cut` test
still need `PERFORM MAIN-PROCESS THRU MAIN-EXIT`? Only if nothing of
substance sits between `MAIN-PROCESS` and `MAIN-EXIT` in source order that
the *normal* (early-exit branch not taken) path currently depends on the
THRU range's fall-through to execute — dropping THRU changes what a plain
`PERFORM MAIN-PROCESS` runs on that path (it returns the instant
`MAIN-PROCESS`'s own body ends, rather than continuing by fall-through
into whatever the range used to cover).

This is real: a THRU range covering intermediate paragraphs between the
target and the exit label is not safe to collapse in general. The one
provably safe case, and the only one this design ships, is **the
exit-only paragraph is the immediate next paragraph after the perform
target in source order, with nothing else between them** — exactly the
textbook idiom above. There, the "normal" path's fall-through into
`MAIN-EXIT` was already a no-op, so dropping THRU changes nothing on that
path either.

mockymock does not rewrite a `.cut` file's own `TESTCASE ... PERFORM`
line — that is user-authored DSL, not splicer output. What this buys is
narrower and more important: a `.cut` author who writes plain `PERFORM
MAIN-PROCESS` (no THRU) against this exact shape, whether by choice or by
not knowing THRU was ever needed, gets a program that now behaves
correctly on both paths — where before, that same plain `PERFORM` could
silently mis-execute on the early-exit path (see "Adjacent gap" below).
The `THRU` keyword becomes optional advice, not a correctness requirement,
for this one shape.

No new analysis function is needed for this half: it falls out of the
splice itself. `GO TO MAIN-EXIT` no longer exists in the compiled source
after splicing, so `PERFORM MAIN-PROCESS` (THRU or not) behaves
identically on the early-exit path once the immediate-next-paragraph
condition holds — nothing additional to compute or gate.

## Splice mechanics

New `GotoExitPlan` dataclass (`refusal.py`, alongside `TerminatorPlan`):
`statement` (the `GoStatement`), `paragraph_name` (its enclosing
paragraph, for messages), `exit_kind` ("PARAGRAPH" or "SECTION", same
derivation as `TerminatorPlan.exit_kind`), and `span` — the precomputed,
validated `(start, end)` replacement span (see "Revision note" above):
`statement_span` for a top-level GO TO, `nested_statement_span` for one
nested inside an `IF`/`EVALUATE` branch. `find_goto_exit_plans` computes
this once, at the same place it runs the safety checks, and a plan is
only ever returned once a span was validated (never `None` on a returned
plan) — the splicer trusts it as-is rather than re-deriving it.

`splicer/orchestrator.py`'s `splice_program` gains a new
`goto_exit_plans: Sequence[GotoExitPlan] = ()` parameter and a loop
parallel to the existing terminator-neutralization one: `plan.span`
locates the `GO TO`'s own replacement span, and `comment_and_replace`
swaps it for `["EXIT PARAGRAPH"]`/`["EXIT SECTION"]` — reusing
`stub_writer.comment_and_replace` exactly as every other statement
replacement in this file does, including the same trailing-period
propagation (`build_goto_exit_replacement`; text is
`f"EXIT {plan.exit_kind}"`, no `UT-EARLY-EXIT` flag involved — this
transform never needs to propagate anything through an intermediate
`PERFORM` chain, unlike terminator neutralization, because it always
ends the SAME paragraph the `GO TO` already lived in).

`cli/main.py`'s three `find_terminator_plans` call sites (`run`, `debug`,
`export` — `lint` never reaches the splicer) each gain a
`find_goto_exit_plans(result.ast, scope_map, lines)` call immediately
after their existing `find_terminator_plans` call, and thread the result
into `splice_program`.

## Adjacent gap (discovered, out of scope)

While designing this, a pre-existing, unrelated correctness gap surfaced:
mockymock's reachability BFS (`_reachable_paragraphs`, used for MOCK
coverage gating) always follows a `GO TO` edge regardless of whether the
`.cut` test declared a matching `PERFORM ... THRU`. The *compiled driver's
own* `PERFORM {target} [THRU {thru}]` statement, however, is emitted
directly from `case.perform_target`/`case.perform_thru` with no
cross-check against what the program's control flow actually needs for
correct runtime return semantics. A `.cut` author who mocks this idiom's
boundaries correctly but forgets `THRU MAIN-EXIT` gets a suite that
compiles clean and may run silently wrong (falls through into unrelated
paragraphs after the early-exit `GO TO`) with no refusal today. This
design's GO-TO-to-EXIT-PARAGRAPH splice happens to close this gap for the
one shape it covers (see "THRU elision" above), but does not address the
general case (a THRU range covering real intermediate paragraphs, forgotten
by the `.cut` author). Left as a discovered-but-unfixed finding, matching
this codebase's audit-log convention — not folded into this design's scope
to avoid scope creep on an already-unverified feature.

## Out of scope

- Empty-body (zero-statement) "exit-only" paragraphs — narrower detection
  chosen deliberately, see above.
- `GO TO ... DEPENDING ON` / multi-target `GO TO` into an exit-only
  paragraph — excluded, not a single resolvable target.
- The general THRU-elision case (intermediate real paragraphs between
  target and exit label) — not provably safe, not attempted.
- The adjacent missing-THRU correctness gap above — a separate, larger
  finding, not this design's to fix.
- Any variant of Candidate 1/2 from
  `docs/2026-07-10-goto-reachable-terminators-design.md` (fixing the
  *target* paragraph's own return machinery) — still confirmed dead ends;
  this design does not revisit them.

## Testing

- Unit (Docker-free): `_is_exit_only_paragraph` (positive: bare `EXIT.`;
  negative: `EXIT PARAGRAPH.`, `EXIT.` plus another statement, empty
  body); `find_goto_exit_plans` (positive: single safe GO TO; negative:
  computed GO TO, GO TO from a GO-TO-entered enclosing paragraph, GO TO
  sharing its line with sibling code, GO TO into a SECTION member that
  isn't a safe entry, one-of-several-sites-unsafe leaves ALL of that
  target's sites untouched); the splice output itself (golden-text style,
  matching `build_terminator_neutralization`'s existing test precedent);
  wiring into `find_terminator_plans` (a terminator behind a
  now-neutralized GO TO chain gets a `TerminatorPlan`, where before it
  refused `UNSUPPORTED_TERMINATOR_LAYOUT`); a dedicated regression pin
  (`test_nested_goto_replacement_does_not_swallow_the_enclosing_end_if`)
  for the nested-span bug the Revision note above describes — confirmed
  to fail against the original `statement_span`-only approach and pass
  against `nested_statement_span`.
- `tests/integration/test_goto_exit_support.py::test_goto_is_actually_
  spliced_out_of_the_compiled_source` (no `@requires_docker` — `export`
  is Docker-free) **was run in the session that wrote this feature** and
  passed: real end-to-end verification through the full CLI pipeline
  (parse → analysis → `find_goto_exit_plans` → `splice_program` →
  written output) that the GO TO is spliced out and `EXIT PARAGRAPH`
  lands correctly inside its `IF`. This is what caught the nested-span
  bug in the first place. It does NOT verify GnuCOBOL's own runtime
  behavior — no compile or execution happens in this test.
- `tests/integration/test_goto_exit_support.py::test_early_exit_branch_
  returns_correctly_with_no_perform_thru` (`@requires_docker`, **not run
  in the session that wrote this** — see Status above): the one check
  that actually matters for trusting this feature at runtime — compiles
  and runs the textbook idiom through real GnuCOBOL, both branches
  (early-exit taken and not taken), with no `PERFORM ... THRU` declared,
  and asserts a later test case in the suite still runs. This fixture
  must be run and pass before `README.md`/`.okf/analysis.md` describe
  this feature as supported rather than "implemented, pending
  verification."

## Docs sync

- `.okf/analysis.md`: new subsection under `refusal.py`'s per-test-case
  section, cross-referencing `find_terminator_plans`'s existing GO-TO-
  target refusal text (which already suggests this exact workaround).
- `.okf/splicer.md`: `GotoExitPlan` splice mechanics alongside the
  existing terminator-neutralization writeup.
- `.okf/log.md`: dated entry noting implementation without runtime
  verification.
