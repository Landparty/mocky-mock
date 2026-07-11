# GO TO-Reachable Terminators — Investigation Design

Date: 2026-07-10
Status: **investigation complete — no fix found.** Both candidate
mechanisms scoped by this doc were tested against the simplest shape and
both failed with the identical symptom. See "## Outcome" below.

## Outcome (2026-07-10)

**No candidate mechanism fixed the broken shape. The refusal stands.**

- **Candidate 1 (dead-PERFORM coercion)** was tested against shape (a) —
  the terminator's own paragraph as the `GO TO` target (Task 1). **Failed**:
  stdout was `TERMINATOR-RAN\n` only, `CALLER-CHECK-RAN` never printed,
  exit code 0 — the identical silent-wrong-pass symptom spike #4 originally
  observed. Full evidence: `.superpowers/sdd/task-1-report.md`.
- **Candidate 2 (SECTION-scoped `EXIT SECTION` fallback)** was tested
  against shape (a) (Task 3). **Failed** with the *identical* symptom:
  `TERMINATOR-RAN\n` only, `CALLER-CHECK-RAN` never printed, exit code 0.
  Full evidence: `.superpowers/sdd/task-3-report.md`.
- **Shape (b)** (an intermediate chain paragraph, rather than the
  terminator's own paragraph, as the `GO TO` target) was **never reached**
  for either candidate — Tasks 2 and 4 were skipped as moot once each
  candidate had already failed the simpler shape (a). Shape (b) remains
  genuinely untested; it was not "tried and failed," it was never
  attempted.
- **The refusal stands.** `mockymock/analysis/refusal.py`'s
  `UNSUPPORTED_TERMINATOR_LAYOUT` for `GO TO`-reachable chains is confirmed
  permanent for now. No production code changed as a result of this
  investigation (per the plan's commit-on-success-only rule, neither
  candidate's test file was committed — both were deleted from the working
  tree after their failing runs).
- **What would it take to reopen this?** A future investigation would need
  a genuinely different mechanism, not a variant of either candidate tried
  here — both a paragraph-frame approach (`EXIT PARAGRAPH`, Candidate 1)
  and a section-frame approach (`EXIT SECTION`, Candidate 2) hit the same
  wall, which is weak evidence (see "Root-cause status" below — not
  confirmed via generated-C comparison) that the problem lives in how
  `GO TO` entry itself is codegen'd, upstream of which exit statement is
  used to try to unwind afterward. Any future attempt should start with
  the still-unrun Phase 1 diagnostic (`cobc -C` generated-C comparison) to
  get an actual confirmed root cause before spending effort on more
  candidate fixes.

(The `.superpowers/sdd/task-*-report.md` files cited above are
investigation-local artifacts — gitignored scratch from the worktree that
ran this investigation, not part of this repo's committed history. The
exact stdout/exit-code evidence they contain is already quoted inline
above, so this doc stands on its own without them.)

## Problem

`docs/2026-07-08-goback-stop-run-support-design.md`'s Approach B (propagate
an early-exit flag via `EXIT PARAGRAPH`/`EXIT SECTION`) neutralizes
`STOP RUN`/`GOBACK` terminators reached through a chain of plain,
unconditional `PERFORM`s. Its spike #4 found one broken shape: if the
terminator's paragraph — or any paragraph on the chain to it — can ever be
entered via `GO TO` instead of `PERFORM`, `EXIT PARAGRAPH` does not resolve
the correct return address. Verified behavior: execution just stops after
the terminator's own code — exit 0, no crash, but incomplete output, and the
caller's checks never run. That's a silent wrong-pass, worse than the crash
it replaces, so `find_terminator_plans` refuses it
(`UNSUPPORTED_TERMINATOR_LAYOUT`) rather than attempting a possibly-wrong
transform. This is verified still correctly wired today (`_go_to_targets`
checked against every paragraph on the chain, not just the terminator's
own).

This doc scopes an investigation into whether that refusal can ever be
narrowed — i.e., whether any mechanism can safely neutralize a
GO-TO-touched chain — rather than accepting the refusal as permanent by
default. Consistent with how every fact in the original design doc was
settled (six compile-and-run spikes against the pinned GnuCOBOL 3.2
toolchain, not reasoning from documentation), any claim here must be
verified the same way before it's trusted.

## Root-cause status (still a preliminary hypothesis — not confirmed)

**What is confirmed:** both candidate fix mechanisms this investigation
scoped (dead-PERFORM coercion, SECTION-scoped `EXIT SECTION`) empirically
fail to restore caller-return semantics for a GO-TO-reachable terminator
paragraph (shape (a) — see "## Outcome" above for the evidence).

**What is not confirmed:** the exact `cobc`-internals explanation for
*why*. Phase 1's diagnostic step (compare `cobc -C` generated C for a
GO-TO-only paragraph vs. the same paragraph with a dead/unreachable
`PERFORM` callsite added) was scoped as optional/non-gating in the original
plan and was never run — Task 1 proceeded straight to the Candidate 1
runtime spike instead. So the following remains exactly what it was when
this doc was first written: a *hypothesis*, now somewhat strengthened by
Candidate 1's failure (which is consistent with it) but not verified
against actual generated code, and therefore still not to be trusted or
built on:

> Best guess: `cobc` only emits the runtime frame-stack machinery that
> `EXIT PARAGRAPH` pops (the "return to whoever actually performed me"
> mechanism Approach B depends on) for paragraphs that are *statically* a
> `PERFORM` target somewhere in the source. A paragraph that is *only* ever
> reached via `GO TO` may get cheaper codegen where `EXIT PARAGRAPH`
> degrades to "fall through to the next physical paragraph" rather than a
> real return — which would exactly explain spike #4's observed behavior
> (execution stops where the terminator's paragraph happens to end, rather
> than returning to the caller).

Candidate 1's failure (Task 1) is *consistent* with this hypothesis but
does not prove it: the dead `PERFORM` never executing at runtime means the
spike cannot distinguish "cobc's codegen genuinely ignores unreachable
static `PERFORM` targets" from "the hypothesis's premise is wrong for some
other reason." Candidate 2's failure (Task 3) adds a further data point —
the problem survives switching from `EXIT PARAGRAPH`/paragraph-frame
machinery to `EXIT SECTION`/section-frame machinery — which suggests
(again, without generated-C confirmation) that the root cause sits in how
`GO TO` entry itself is codegen'd, rather than being specific to one exit
mechanism. Neither report elevates this past "preliminary." A future
investigation that wants a confirmed root cause still needs to run the
Phase 1 diagnostic (or equivalent) before trusting any explanation of *why*
these mechanisms fail.

## Investigation plan

### Phase 1 — diagnostic spike (no fix attempt yet)

Reproduce spike #4's synthetic program (or one close to it) in an isolated
worktree. Compile with `cobc -C` (C-only, no link) and inspect the
generated C for the terminator's paragraph in two variants:

1. The paragraph is *only* ever a `GO TO` target (spike #4's exact shape).
2. The same paragraph is *also* the target of a `PERFORM` statement
   elsewhere in the source (even one that is never actually executed at
   runtime — e.g., dead code behind a condition that's always false).

Compare the generated C for both. This either confirms the hypothesis above
(codegen visibly differs — variant 2 gets return machinery variant 1
lacks), refutes it (codegen is identical, or differs for some other
reason), or surfaces a different root cause entirely. Whatever the result,
it settles what Phase 2 is worth attempting.

### Phase 2 — candidate fixes (only if Phase 1 finds a tractable root cause)

*(Gate bypassed in practice — see "## Outcome" above. Phase 1's diagnostic
was never run; Tasks 1 and 3 dispatched both candidates directly against the
runtime behavior instead, treating the compile-and-run result as the
authoritative signal rather than waiting on generated-C inspection.)*

- **Candidate 1 — dead-PERFORM coercion.** If Phase 1 confirms the
  hypothesis: inject an unreachable `PERFORM <chain-paragraph>` — gated
  behind a working-storage flag that is never set true — purely to force
  `cobc` to emit return-capable exit code for every paragraph on the
  GO-TO-touched chain. Spike questions: does this actually change codegen
  for the *real* target paragraph (not just a throwaway repro)? Does the
  real, GO-TO-driven execution path then correctly unwind through
  `EXIT PARAGRAPH` all the way back to the test case's own checks? Tested
  for both shapes: the terminator's own paragraph as the GO TO target, and
  an *intermediate* chain paragraph as the GO TO target (spike #4's finding
  in the original design doc already establishes both must be covered).
- **Candidate 2 — SECTION-scoped fallback.** Only attempted if Candidate 1
  fails or proves unreliable. The original design's spike #5 already proved
  `EXIT SECTION` correctly unwinds when a `SECTION` is `PERFORM`ed. Test
  whether wrapping a GO-TO-reachable paragraph in its own `SECTION` changes
  `EXIT SECTION`'s ability to unwind when that paragraph is instead entered
  via `GO TO` — a different `cobc` codegen path, worth ruling out
  empirically even though it may hit the same underlying wall as Candidate
  1.

**Explicitly not re-spiked:** reviving Approach A's `GO TO`-based
redirection (jumping to a caller-injected check paragraph). The original
design doc's "Root cause" section already proved this fails structurally
for *any* live nested-`PERFORM` chain — the driver's own pending
`PERFORM {target}` frame gets corrupted regardless of *why* the redirecting
`GO TO` exists. That is a different, already-closed question and is out of
scope for this investigation.

## Decision gate

**Outcome: nothing survived.** Neither candidate passed even the simplest
shape, so the "if nothing survives" branch below is what actually happened:

- ~~**If** a candidate spike works reliably...~~ — did not happen. Neither
  Candidate 1 nor Candidate 2 passed shape (a); shape (b) was never
  reached (moot once shape (a) failed for both candidates). No follow-up
  design/plan is warranted for either mechanism tried here.
- **What happened:** nothing survived. Per the plan's own decision gate,
  this is still a valuable, legitimate terminal outcome: the refusal in
  `mockymock/analysis/refusal.py` (`UNSUPPORTED_TERMINATOR_LAYOUT` for
  `GO TO`-reachable chains) is confirmed permanent for now. What this
  investigation adds over the original design doc's spike #4 is **not** a
  confirmed root cause (see "Root-cause status" above — that remains
  preliminary) but a confirmed absence of a viable fix among the two
  mechanisms judged most promising going in. A future reader should treat
  this as "two specific fix ideas were tried and empirically ruled out,"
  not as "the root cause is understood and unfixable in principle."

## Risks

(Moot in practice, since neither candidate proved viable — kept here as
the historical record of what a follow-up plan would have needed to
disclose had one of them succeeded.)

Even a working Candidate 1 leans on `cobc` behavior — whether a paragraph
is *ever* statically a `PERFORM` target, even unreachably — that GnuCOBOL
does not document as a guaranteed contract. Same posture as every other
spike this feature already depends on: verified for the pinned GnuCOBOL 3.2
toolchain used in this repo's Docker toolchain, not assumed portable to
other versions. If shipped, this must be called out explicitly in the
docs-sync pass (README known-limitations section, `.okf/analysis.md`) as
resting on empirically-verified-but-undocumented compiler behavior.

## Out of scope

- `SECTION`-scoped terminators unrelated to `GO TO` (already deferred by
  the original design's spike #5 finding, unaffected by this investigation).
- Conditionally-nested intermediate `PERFORM`s (already deferred, unrelated
  to `GO TO` reachability).
- `GO TO ... DEPENDING ON` and computed-`GO TO` — if Phase 1/2 produces a
  working mechanism, whether it also covers computed `GO TO` targets is a
  follow-up question, not answered by this doc.
- Reviving Approach A (see above).
- Everything the original design doc already scoped out: `STOP RUN GIVING`/
  `GOBACK RETURNING` return-code capture, `EXIT PROGRAM` as a transform
  target.

## Testing

Same pattern as the original six spikes: Docker-backed compile-and-run
fixtures (`@requires_docker`), not just unit tests, since the entire
question here is genuine GnuCOBOL runtime behavior. Phase 1's diagnostic
spike does not need to become a permanent test (it's a one-time
investigation artifact); any Phase 2 candidate that is later adopted must
get a permanent regression fixture, matching
`test_splicer_linkage.py`-style precedent.
