# SECTION-Scoped Terminator Support — Design

Date: 2026-07-10
Status: design approved, ready for implementation planning

## Problem

`docs/2026-07-08-goback-stop-run-support-design.md` (Approach B, shipped in
PR #14) neutralizes `STOP RUN`/`GOBACK` reached through a chain of plain,
unconditional, top-level `PERFORM` statements, replacing the terminator with
`MOVE "Y" TO UT-EARLY-EXIT` + `EXIT PARAGRAPH` and propagating the flag back
up the chain. That design's spike #5 proved the same mechanism works with
`EXIT SECTION` when the terminator sits in the first paragraph of a
`PERFORM`ed `SECTION` — but it was scoped out of v1 because distinguishing
"the section's first paragraph, reached via `PERFORM <section-name>`" (safe,
matches the spike) from "a later paragraph in that section, reached only by
fall-through from an earlier one" (never verified) is real added analysis
complexity, and no real corpus example needed it.

Today, `mockymock/analysis/refusal.py`'s `find_terminator_plans` refuses
**any** terminator whose own paragraph belongs to a `SECTION`
(`paragraph_name not in top_level_names`), and separately refuses **any**
terminator whose case-level reachable chain merely touches a `SECTION` name
at all (`chain_section_names`) — even when the terminator itself has no real
dependency on that section. Both checks are blanket refusals with no
attempt to distinguish safe shapes from unsafe ones.

## Scope decision

Three shapes exist under the "SECTION-scoped" umbrella, ordered by how much
new verification each needs:

1. **First paragraph of a section, entered only via `PERFORM
   <section-name>`.** Mechanism already verified safe (spike #5). No new
   spike needed — the only work is a whole-program static safety check
   (below), which is the same *kind* of check the existing `GO TO`
   exclusion already does.
2. **A later paragraph in a section, reached only by fall-through** after
   `PERFORM <section-name>` lands on an earlier paragraph. Requires a new
   Docker/GnuCOBOL spike to confirm `EXIT SECTION` still resolves the
   correct return point when triggered mid-fall-through. No corpus example
   needs it yet.
3. **A specific paragraph inside a section, entered by directly `PERFORM`ing
   that paragraph's own name** (not the section name) — behaves like a
   top-level `PERFORM`+`EXIT PARAGRAPH` chain that merely happens to be
   lexically nested under a `SECTION` header. Needs its own spike to confirm
   `EXIT PARAGRAPH` behaves identically inside a section, plus a
   whole-program "single entry mode" check so a paragraph reachable both
   ways (some callers using the section name, others naming it directly)
   safely refuses instead of guessing the wrong `EXIT` verb.

**This iteration builds shape 1 only.** Shapes 2 and 3 remain refused,
exactly as they are refused today, and are documented below as future work.

## Detection: whole-program safe-section-entry analysis

New function in `refusal.py`:

```
_safe_section_entry_points(program) -> dict[str, str]
```

Maps `section_name -> first_paragraph_name` for every `SECTION` in the
`PROCEDURE DIVISION` where **all** of the following hold:

- The section has at least one paragraph.
- Neither the section's own name nor its first paragraph's name is ever a
  `GO TO` target anywhere in the program (reuses the existing
  `_go_to_targets(program)`).
- The first paragraph's name is never itself named as a `PERFORM` target —
  plain or `THRU`, unconditional or not, top-level or nested inside an
  `IF`/`EVALUATE`/loop — **anywhere** in the whole program. This is
  deliberately maximally inclusive: any second way to enter that paragraph
  is a standing risk regardless of whether any one test's execution happens
  to take it, the same reasoning already applied to the `GO TO` exclusion.
  Implemented with a new whole-program scan reusing the existing
  `_find_statements_of_type`/`_all_paragraphs` helpers (already proven
  recursive — they walk into `IF`/`EVALUATE`/`SEARCH` branches and inline
  `PERFORM` bodies for the `GO TO` scan today).

A section that fails any of these is simply absent from the map. Every
caller treats "absent" identically to how it treats any other unresolvable
`PERFORM` target today — nothing about currently-refused shapes gets
weaker.

## Wiring into the safe-chain BFS

`_plain_perform_edges_from(program, start)` currently resolves `PERFORM`
targets only against `by_name` (top-level paragraphs). Any name it can't
resolve there — including every `SECTION` name — is a dead end: the raw,
unresolved name still lands in the returned `seen` set (so it can be
detected as "a section was touched"), but the BFS never continues through
it.

It gains a new `safe_section_entries` parameter (computed once in
`find_terminator_plans`, the same way `go_to_targets` already is) and a
`resolve(name)` step:

- If `name` matches a top-level paragraph, resolve as today.
- Else if `name` is a key in `safe_section_entries`, resolve to that
  section's first-paragraph name and continue the BFS from *that
  paragraph's own statements* — so the first paragraph can still chain
  forward into further plain top-level `PERFORM`s exactly like any other
  paragraph, and the name that lands in `seen` is the **first paragraph's
  name**, not the section's name (this is what makes `site.paragraph_name`
  checks downstream line up correctly).
- Else, dead end — unchanged from today.

This applies uniformly whether the section-name `PERFORM` is:

- **The test's own `perform_target`** (the DSL's `PERFORM_TARGET` names the
  section directly) — zero intermediate hops, exactly mirroring how a
  terminator sitting directly in a top-level `perform_target` needs no
  `chain_performs` today (`TerminatorPlan.chain_performs == []`).
- **An intermediate hop partway down the chain** — the section-name
  `PERFORM` statement is still appended to `chain_performs` like any other
  edge, so it still gets the standard post-`PERFORM`
  `IF UT-EARLY-EXIT = "Y" EXIT PARAGRAPH END-IF` check inserted after it,
  completely unchanged from today's mechanism.

Two existing checks in `find_terminator_plans` relax accordingly, both
gaining a `| safe_section_first_names` (the set of values of
`_safe_section_entry_points`, computed once):

- `if paragraph_name not in top_level_names:` → also allow
  `paragraph_name in safe_section_first_names`.
- `chain_section_names = safe_names - top_level_names` → becomes
  `safe_names - (top_level_names | safe_section_first_names)`.

### Consequence: an existing test becomes more permissive, correctly

`tests/unit/test_terminators.py::test_section_scoped_terminator_refuses`
(`SECTION_UNSAFE_SOURCE`: `0000-MAIN-PROCESS` performs `1000-SECTION`, *then*
does `STOP RUN` itself — the terminator is never inside the section at all)
currently refuses solely because of today's blanket "any section reference
anywhere in the case's reachable chain is unsafe" check. Once
`1000-SECTION`'s entry is provably safe (its one paragraph, `1000-DO-WORK`,
is never `GO TO`'d or directly `PERFORM`'d elsewhere), this case has no real
hazard — the terminator doesn't depend on the section's internals at all —
and correctly produces a plan instead of a refusal.

This test will be updated to assert a plan is produced, and a new test
added in its place asserting the true unsafe case still refuses (a section
whose first paragraph is *also* directly `PERFORM`'d elsewhere in the
program, so `_safe_section_entry_points` correctly excludes it).

`test_section_own_paragraph_terminator_refuses`
(`SECTION_OWN_PARAGRAPH_UNSAFE_SOURCE`) is unaffected and continues to
refuse: its terminator's own paragraph is the test's `perform_target`
*directly by paragraph name*, not via the enclosing section's name — shape
3 above, still out of scope.

## Splice mechanics

`TerminatorPlan` (in `refusal.py`) gains a new field:

```python
@dataclass
class TerminatorPlan:
    site: BoundarySite
    chain_performs: list = field(default_factory=list)
    exit_kind: str = "PARAGRAPH"
```

`find_terminator_plans` sets `exit_kind = "SECTION"` when the terminator's
own paragraph is in `safe_section_first_names`, else leaves the existing
default `"PARAGRAPH"`.

`mockymock/splicer/injector.py`'s `build_terminator_neutralization()` takes
`exit_kind` and emits `EXIT SECTION` in place of `EXIT PARAGRAPH` when
`exit_kind == "SECTION"`:

```python
def build_terminator_neutralization(exit_kind: str = "PARAGRAPH") -> list[str]:
    return [
        '           MOVE "Y" TO UT-EARLY-EXIT',
        f"           EXIT {exit_kind}",
    ]
```

`mockymock/splicer/orchestrator.py`'s one call site passes
`plan.exit_kind` through. `build_chain_check()` (the intermediate
post-`PERFORM` flag check) is untouched — it is always `EXIT PARAGRAPH`
regardless of what kind of terminator it's propagating toward, since
intermediate hops are themselves top-level paragraphs, never inside the
neutralized section.

## Testing

**Unit** (`tests/unit/test_terminators.py`,
`tests/unit/test_terminator_reachability.py`):

- New fixture: terminator in a section's first paragraph, entered only via
  `PERFORM <section-name>`, with a second paragraph in the section that
  must not run — asserts a `TerminatorPlan` with `exit_kind == "SECTION"`
  is produced (not refused).
- Same shape but with the section named directly as the test's
  `perform_target` (zero-chain case) — asserts `chain_performs == []`.
- Updated `test_section_scoped_terminator_refuses` (now asserts a plan, per
  the consequence above) plus a new test for the genuinely-unsafe variant
  (first paragraph also directly `PERFORM`'d elsewhere → still refuses).
- `test_section_own_paragraph_terminator_refuses` unchanged (already
  covers shape 3, still refused).

**Integration** (`tests/integration/test_terminator_support.py`,
`@requires_docker`): promotes spike #5's exact shape to a permanent
regression fixture — real GnuCOBOL 3.2 compile-and-run, asserting the
section's second paragraph did not run and the suite completed normally.
This is the one spike shape from the original design that was never
committed as a test, since the feature was deferred at the time.

## Docs sync

- `docs/2026-07-08-goback-stop-run-support-design.md`: "Design consequence
  of #5" section gets a note that shape 1 is now implemented, linking here.
- `.okf/analysis.md` / `.okf/splicer.md`: concept rows describing
  `_safe_section_entry_points` and the `exit_kind`-driven splice.
- `docs/2026-07-06-real-world-readiness-audit.md`: Finding 3 note updated.
- `.okf/log.md`: dated entry.

## Out of scope (this iteration)

- **Shape 2** — a later paragraph in a section reached only by fall-through
  after `PERFORM <section-name>` lands on an earlier paragraph. Needs a new
  spike verifying `EXIT SECTION` still resolves correctly when triggered
  mid-fall-through. No corpus example needs it yet.
- **Shape 3** — a section-member paragraph entered by directly `PERFORM`ing
  its own paragraph name (not the section name). Needs its own spike for
  `EXIT PARAGRAPH` semantics inside a section, plus a whole-program
  "single entry mode" check for paragraphs reachable both ways.
- Everything already out of scope for Approach B generally (`STOP RUN
  GIVING`/`GOBACK RETURNING` return-code capture, `GO TO`-reachable
  terminators, conditionally-nested intermediate `PERFORM`s, terminators
  reachable only through a looping `PERFORM`).
