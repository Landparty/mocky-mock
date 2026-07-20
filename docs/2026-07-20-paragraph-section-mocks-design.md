# Paragraph and Section Mocks (`MOCK PARAGRAPH` / `MOCK SECTION`)

2026-07-20.

## Problem

Every mock category so far replaces an external *boundary statement*
(CALL, file I/O, EXEC, ACCEPT). Users also want to isolate a test's entry
point from its *internal collaborators* — "when MAIN-PROCESS performs
CALC-TOTALS, don't run the real CALC-TOTALS" — the feature cobol-check
calls paragraph mocking. That also gives an escape hatch for paragraphs
whose contents are individually unmockable (e.g. a SORT): mock the whole
paragraph away instead.

## Constraints inherited from the architecture

1. **One compiled binary serves the whole TESTSUITE.** A case that mocks
   paragraph P and a case that doesn't share one physical copy of P, so
   the real body must still exist and run for the non-mocking cases —
   dispatch has to happen at runtime on `UT-CURRENT-CASE`. The boundary
   mocks' `WHEN OTHER` is an error trap; a flow mock's `WHEN OTHER` must
   instead run the real code.
2. **Every splice span is derived from `SourceLocation.line` against the
   normalized text, all computed up front and applied bottom-up.** Any
   design that *moves* the paragraph's body lines (e.g. relocating them
   into a renamed paragraph elsewhere) would invalidate every other span
   inside that body — boundary dispatch blocks, terminator
   neutralization, chain-check insertions.

## Design: header dispatch, body left in place

Replace ONLY the paragraph/section **header line**:

```
P.                                     P.
    <body>                =>              EVALUATE UT-CURRENT-CASE
                                              WHEN "001"
                                                  ADD 1 TO UT-PARAGRAPH-P-TALLY
                                                  <mock body>
                                              WHEN OTHER
                                                  PERFORM UT-REAL-1-P
                                          END-EVALUATE.
                                      UT-REAL-1-P.
                                          <body -- original lines, unmoved>
```

(`X SECTION.` headers get the same treatment with `UT-REAL-n-X SECTION.`,
and `PERFORM` of that section name runs all of its paragraphs.)

Properties that make this sound:

- `PERFORM P` now executes only the dispatch sentence (P ends at the
  `UT-REAL-1-P` header). Mocking cases run the mock body; everyone else
  performs the relocated real body and returns. A looping
  `PERFORM P ... TIMES/UNTIL/VARYING` re-enters the dispatch per
  iteration, so the tally counts iterations — the semantics a `.cut`
  author expects.
- The body lines keep their exact line numbers (the splice grows the file
  *above* them only after their own spans were applied — the
  orchestrator's existing bottom-up ordering), so every other splice
  inside the body stays valid.
- Terminator neutralization composes: a `STOP RUN` in the body becomes
  `MOVE "Y" TO UT-EARLY-EXIT` + `EXIT PARAGRAPH`, which now exits
  `UT-REAL-1-P`, returns to the dispatch's `PERFORM`, falls off the end
  of P (nothing follows the EVALUATE), and propagates through the
  existing chain checks unchanged. Same for the SECTION-scoped
  `EXIT SECTION` shape.
- `EXIT PARAGRAPH` in a relocated paragraph body exits `UT-REAL-1-P` and
  then immediately ends P — observably identical to exiting P directly.
- The flow-mock spans bypass the orchestrator's trailing-period
  propagation: a header line always ends with `.` and the replacement is
  already sentence-complete, so propagation would emit `UT-REAL-1-P..`.

## Fail-closed refusals

The rewrite is only sound when the target is entered **exclusively
through its header via PERFORM**. Any other entry runs the dispatch and
the relocated body back to back (fall-through off the dispatch's end), or
bypasses the dispatch entirely. `analysis/flow_mocks.find_flow_mock_plans`
therefore refuses, program-wide (mirroring `find_terminator_plans`'
plan-or-refusal shape):

- `UNRESOLVED_FLOW_MOCK_TARGET` — key names no paragraph/section, names
  more than one, or names the other kind (message hints the right
  keyword).
- `UNSUPPORTED_FLOW_MOCK_TARGET` —
  - target is a GO TO target anywhere (GO TO doesn't return; control
    falls off P's end into the relocated body);
  - target lies inside any `PERFORM ... THRU` range (in-program or a test
    case's driver-side range): the range walk falls through the dispatch
    AND the relocated body. For a SECTION this checks member names plus a
    straddle test on the range's line span (covers a section whose named
    members a malformed/empty membership wouldn't reveal); a range that
    fails to expand refuses too, fail-closed;
  - target is reached by falling through past a GO TO target
    (`_go_to_fallthrough_targets` — same never-PERFORMed hazard the
    terminator feature guards);
  - a mocked PARAGRAPH belongs to a SECTION that is itself performed or
    jumped to anywhere (a performed section executes its members by
    fall-through, straight through the dispatch) — mocking *the section*
    is the supported alternative;
  - the header doesn't own its line (`P1. MOVE ...` one-liners) or the
    text at `location.line` isn't the expected bare header (positional
    trust is verified textually, like the linkage transform does);
  - per-case: the target is the case's own `PERFORM` entry point (the
    dispatch would replace the very code under test).

## Reachability integration

`_reachable_paragraphs` gained a `skip_traversal` set: a flow-mocked
target is recorded as *reached* (so the directive matches and
`UNKNOWN_PARAGRAPH` still works) but its body is never traversed — no
statements walked, no section members expanded. Consequences:

- Boundary statements inside a mocked body need no mocks for that case
  (that is the point of the feature); other cases still gate them.
- A directive whose target no reachable PERFORM/GO TO edge ever enters is
  `UNMATCHED_MOCK`, same as a boundary directive matching nothing.
- `find_terminator_plans` applies the same per-case exclusion, so a
  terminator inside a mocked body demands neither a plan nor a refusal on
  that case's account.

Directly performing a paragraph *inside* a mocked section is allowed and
runs the real paragraph: the mock intercepts only entries through the
section header, and the member keeps its name inside the relocated
section. (Same reasoning as GO TO *into* a section body pre-dating this
feature.)

## Naming

`TallyRegistry` already handles the new categories generically:
`UT-PARAGRAPH-<KEY>-TALLY` / `UT-SECTION-<KEY>-TALLY` (sanitized, capped,
collision-suffixed). Relocated bodies are `UT-REAL-<n>[-<KEY≤18>]` with
`<n>` the key's first-appearance index — unique by construction, capped
well under GnuCOBOL's 63-char word limit.

## Verified end-to-end

Against the real `mockymock-cobc` container (GnuCOBOL 3.2.0):
mock replaces paragraph and section bodies per case; unmocked cases run
the relocated real bodies (including a boundary CALL dispatch inside a
relocated body); `VERIFY PARAGRAPH ... WAS PERFORMED 3 TIMES` counts loop
iterations of `PERFORM ... 3 TIMES`. See
`tests/integration/test_flow_mock_example.py` and `examples/flowmock/`.

One user-facing sharp edge found while building the example: section
names that are COBOL reserved words (`REPORTING`) fail at compile time
with a GnuCOBOL syntax error, unrelated to mocking — the example README
warns about it.
