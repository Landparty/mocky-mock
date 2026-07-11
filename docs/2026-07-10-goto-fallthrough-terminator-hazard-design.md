# GO TO Fall-Through Terminator Hazard — Design

Date: 2026-07-10
Status: design approved, ready for implementation planning

## Problem

`mockymock/analysis/refusal.py`'s module docstring (added by the 2026-07-09
final branch review of `docs/2026-07-08-goback-stop-run-support-design.md`)
documents a gap the reachability BFS does not model: a `GO TO` that jumps
into a paragraph which itself falls through — off its own end, by ordinary
sequential execution, with no `PERFORM`/`GO TO`/`GOBACK`/`STOP RUN` of its
own — into the next paragraph in source order. `_go_to_targets(program)`
only records paragraphs that are *themselves* named by a `GO TO`; the
paragraph merely fallen into afterward is invisible to it.

That fallen-into paragraph carries the exact same hazard spike #4 proved for
a direct `GO TO` target: the runtime frame-stack context never went through
a genuine `PERFORM` call, so `EXIT PARAGRAPH` there does not reliably return
to the real caller (docs/2026-07-08-goback-stop-run-support-design.md).
Concretely:

- Before any test case has neutralized the physical terminator sitting in
  that fallen-into paragraph: harmless today — the real `STOP RUN`/`GOBACK`
  still fires and exits the binary. Loud, no different from pre-feature
  behavior.
- After a *different* test case has legitimately neutralized that same
  physical terminator via its own safe plain chain: a case reaching it
  through this unmodeled path instead hits the substituted `EXIT PARAGRAPH`
  from a paragraph never entered via `PERFORM` — per spike #4, "just stops,
  no crash, no return." Silent, worse than the crash it replaces.

Today this is only documented, not guarded against. This design adds a
static check that converts it into the same kind of loud, fail-closed
refusal every other unsafe shape in this file already gets.

## Why no new spike is needed

This change only ever *adds* a refusal — it can never cause `find_terminator_plans`
to produce a *wrong* transform, only to decline one it previously would have
allowed. Spike #4 already established the runtime failure mode for
GO-TO-entered paragraphs; this design makes no new runtime claim, it only
widens which paragraphs are recognized as sharing that same hazard. Verified
by unit tests against the AST, matching how `UNSUPPORTED_DECLARATIVES` and
`UNSUPPORTED_ALTER` are already verified — categorical, structural checks
with no GnuCOBOL compile/run step.

## Detection: `_falls_through` and `_go_to_fallthrough_targets`

Two new functions in `refusal.py`, next to `_go_to_targets`:

```python
def _falls_through(paragraph) -> bool:
    ...

def _go_to_fallthrough_targets(program, go_to_targets: set[str]) -> dict[str, str]:
    ...
```

**`_falls_through(paragraph)`** — `True` unless the paragraph's last
top-level (non-nested) statement provably diverts control away:

- `GobackStatement` — always unconditional.
- `StopStatement` with `stop_type == "RUN"` — the `STOP <literal>` form is
  explicitly excluded: it only pauses for operator input and resumes, it
  does not terminate control flow.
- `GoStatement` with `depending_on_variable is None` — a plain, single-target
  `GO TO` always transfers control. A computed `GO TO ... DEPENDING ON` is
  explicitly excluded even though it's still a `GoStatement`: GnuCOBOL falls
  through to the next statement when the subscript is out of range, so it is
  *not* a guaranteed unconditional transfer.
- `ExitStatement` with `exit_type` in `{"PARAGRAPH", "SECTION", "PROGRAM"}` —
  a bare `EXIT.`/`EXIT PERFORM` does not qualify (the former is a no-op
  placeholder, the latter exits an in-line loop body, not the paragraph).

An empty paragraph (no statements — just a label) trivially falls through.
Everything else — `MOVE`, `DISPLAY`, `PERFORM` (control returns, then still
falls off the end), a trailing `IF`/`EVALUATE` whose branches might or might
not all terminate — is conservatively "may fall through," matching this
module's existing posture of never trying to prove branch coverage (see
`_check_unsupported_control_flow`'s treatment of `DECLARATIVES`/`ALTER`).

**`_go_to_fallthrough_targets(program, go_to_targets)`** — for every name in
`go_to_targets`, walks `_source_ordered_paragraphs(procedure)` forward from
that target's position, adding each subsequent paragraph to the result while
`_falls_through` holds for the one just checked, stopping (inclusive of the
paragraph that finally terminates) once it doesn't. A `GO TO` targeting a
`SECTION` name is seeded from that section's *first* paragraph (looked up the
same way `_reachable_paragraphs` already builds `section_members` — fall
through is transparent to `SECTION` boundaries, a header doesn't stop it; the
section's own member paragraphs are naturally covered by the walk since
`_source_ordered_paragraphs` includes them).

Returns `{hazard_paragraph_name: originating_go_to_target_name}` — a dict,
not a set, so refusal messages can name the specific `GO TO` target whose
fall-through chain caused the hazard (diagnosability, matching every other
message in this file).

**Known residual gap, not fixed by this change:** if
`_source_ordered_paragraphs` returns `None` (source order isn't strictly
increasing — an existing parser-regression signal), this returns `{}`. That
is the same pre-existing blind spot that already limits other checks in this
module — e.g. `_expand_thru_range` only refuses the specific `THRU` range it
was asked about when this happens, not every reachability question in the
file. Not introduced by this change; not closed by it either.

## Wiring into `find_terminator_plans`

`_go_to_targets` itself is unchanged — computed once, same as today. The new
hazard map is computed alongside it:

```python
go_to_targets = _go_to_targets(program)
go_to_fallthrough = _go_to_fallthrough_targets(program, go_to_targets)
```

Two new `elif` branches, each placed immediately after its existing `GO TO`
counterpart so the direct-target message (more specific) always wins when
both could apply:

- Per-terminator check: after `elif paragraph_name in go_to_targets:`, add
  `elif paragraph_name in go_to_fallthrough:` with a message naming the
  originating `GO TO` target paragraph/section.
- Per-chain check: after `chain_go_to_names = safe_names & go_to_targets`,
  add `chain_fallthrough_names = safe_names & go_to_fallthrough.keys()`, and
  after the existing `elif chain_go_to_names:` branch, add
  `elif chain_fallthrough_names:` with an analogous message.

Both refuse with the existing `UNSUPPORTED_TERMINATOR_LAYOUT` code — this is
the same fundamental hazard class as the existing GO-TO checks, just a
previously-invisible instance of it, not a new category of unsafety.

## Docs sync

- `refusal.py`'s module docstring: the "GO TO" bullet's parenthetical
  currently says this shape "is not modeled" and is merely "documented here
  rather than silently assumed harmless." Update it to say it now IS
  modeled and refused, describing `_go_to_fallthrough_targets` in the same
  register as the rest of the docstring.
- `docs/2026-07-06-real-world-readiness-audit.md`: Finding 3's "one
  documented-but-unmodeled edge case remains" sentence gets updated to say
  it's now guarded (refused), not merely documented.

## Testing

Unit tests in `tests/unit/test_terminators.py`, following its existing
`_analyze`/`_suite` helpers and fixture-per-shape style:

- A `GO TO` target paragraph that falls through (no terminating last
  statement) into a following paragraph containing a terminator — refuses
  with a message naming the fall-through path.
- The same shape but the `GO TO` target paragraph's last statement IS one of
  the terminating forms (`GOBACK`/`STOP RUN`/plain `GO TO`/`EXIT PARAGRAPH`)
  — negative control: the terminator in the *following* paragraph is
  unaffected (no false-positive refusal of an ordinary safe program).
- A `GO TO ... DEPENDING ON` (computed, multi-target) as a target paragraph's
  last statement — must NOT stop propagation (falls through is `True`),
  distinguishing it from a plain single-target trailing `GO TO`.
- `GO TO` targeting a `SECTION` name whose members fall through into a
  following top-level paragraph's terminator — seeded from the section's
  first paragraph, propagates across the section boundary.
- Chain-level variant: the fallen-into paragraph is an intermediate
  `chain_performs` link rather than the terminator's own paragraph.
- `STOP` with a literal operand (`STOP "MSG"`, not `STOP RUN`) as a target
  paragraph's last statement does not stop propagation (still "falls
  through," since it only pauses).

## Out of scope

- Anything already out of scope for Approach B generally (`STOP RUN GIVING`/
  `GOBACK RETURNING` return-code capture, direct `GO TO`-reachable
  terminators — already refused and confirmed permanent by
  `docs/2026-07-10-goto-reachable-terminators-design.md` — conditionally-
  nested intermediate `PERFORM`s, terminators reachable only through a
  looping `PERFORM`).
- Precise control-flow analysis proving a trailing `IF`/`EVALUATE`'s
  branches all terminate. Rejected as a more-precise alternative: real added
  complexity for a shape (two coincidences: this exact idiom, plus a
  different test case legitimately neutralizing the same physical
  terminator first) rare enough that no corpus example has ever needed it,
  and it would contradict this file's established preference for simple,
  provably conservative structural checks over deep analysis (see
  `_check_unsupported_control_flow`'s treatment of `DECLARATIVES`/`ALTER`).
  An over-inclusive refusal here is an accepted usability cliff, the same
  trade-off `find_terminator_plans`' docstring already accepts for the
  whole-chain `GO TO`/`SECTION` checks.
- The pre-existing `_source_ordered_paragraphs() is None` blind spot noted
  above.
