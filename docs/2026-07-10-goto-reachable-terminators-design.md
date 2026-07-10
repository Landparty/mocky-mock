# GO TO-Reachable Terminators — Investigation Design

Date: 2026-07-10
Status: design approved; investigation outcome unknown (this doc scopes a
spike, not a guaranteed feature)

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

## Root-cause hypothesis (unverified)

Best guess, to be confirmed or killed in Phase 1: `cobc` only emits the
runtime frame-stack machinery that `EXIT PARAGRAPH` pops (the "return to
whoever actually performed me" mechanism Approach B depends on) for
paragraphs that are *statically* a `PERFORM` target somewhere in the
source. A paragraph that is *only* ever reached via `GO TO` may get cheaper
codegen where `EXIT PARAGRAPH` degrades to "fall through to the next
physical paragraph" rather than a real return — which would exactly explain
spike #4's observed behavior (execution stops where the terminator's
paragraph happens to end, rather than returning to the caller).

This is a hypothesis about `cobc`'s internals, not a fact. It is not to be
trusted or built on until Phase 1 confirms it against actual generated code.

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

- **If** a candidate spike works reliably — across all safe-chain shapes,
  not just the synthetic repro, and without resting on `cobc` behavior that
  is likely to shift across GnuCOBOL versions or optimization flags — then
  a follow-up design/plan extends `find_terminator_plans` to stop refusing
  this shape and applies the working transform instead.
- **If** nothing survives, the outcome is still valuable: replace the
  current "empirically observed as broken" note (spike #4, in the original
  design doc) with a confirmed root cause and a confirmed absence of a
  viable fix, and keep the refusal permanently. This is a legitimate
  terminal state for this investigation, not a failure to ship.

## Risks

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
