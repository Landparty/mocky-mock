# PERFORM ... THRU Support — Design

Date: 2026-07-06
Status: awaiting review

## Problem

Any test case whose reachable paragraphs contain a `PERFORM A THRU B` is
refused today (`UNSUPPORTED_PERFORM_THRU`), because the refusal gate's
reachability BFS follows only `PerformStatement.target_paragraph` edges
and deliberately does not range-expand A..B ("range expansion needs
source-order guarantees this module doesn't verify"). The `.cut` DSL has
the matching gap on the driver side: `_PERFORM_RE` accepts only
`PERFORM <one-word>`, so a test case cannot use `PERFORM A THRU B` as its
entry point.

PERFORM THRU is idiomatic in real mainframe code — typically
`MAIN-PROCESS ... GO TO MAIN-EXIT ... MAIN-EXIT. EXIT.` — so the refusal
blocks a large class of programs. Goal: support PERFORM THRU both inside
the program under test (reachability) and as a `.cut` entry point
(driver), keeping narrowed fail-closed refusals for degenerate ranges.

Crucially, `PERFORM ... THRU` is **not a boundary statement — nothing
needs splicing**. Its only effect on mockymock is reachability: the range
A..B executes every paragraph from A to B in source order (fall-through
included), so the gate must treat all boundary sites in that range as
reachable. Matching, splicing, tallies, and reset are untouched.

## Key facts (verified empirically against cobolparser 1.2.0)

1. `PerformStatement.thru_paragraph` is populated correctly for
   `PERFORM A THRU B` in both plain and sectioned PROCEDURE DIVISIONs
   (also covered by cobol-parser's own contract test
   `test_perform_thru_paragraph_exists`).
2. `CobolParagraph` carries `location.line` (it extends `ASTNode`), and
   `_all_paragraphs` returns paragraphs whose lines are **strictly
   increasing** — source order — in both plain and sectioned programs.
   (Verified by parsing sample programs and checking the sequence; lines
   index the normalized text, the same coordinate space the splicer
   already trusts for spans.)
3. Phantom `"."` paragraphs (statements after a sentence-ending period,
   e.g. a trailing `STOP RUN`) appear in `_all_paragraphs` **interleaved
   at their true source position**, all sharing the name `"."`. One can
   therefore sit *inside* a THRU range, and its statements do execute as
   part of the fall-through.
4. cobolparser's `ProgramFlowAnalyzer._range_members` implements the same
   first-occurrence, source-order slice semantics (order[i..j] inclusive,
   best-effort endpoints when out of order) — confirming the expansion
   semantics, though mockymock does not depend on it (see approaches).

## Approaches considered

**A. Range expansion inside mockymock's own BFS (chosen).** Order
paragraphs by `location.line` (verifying strict increase at runtime —
the previously-missing "source-order guarantee" becomes a checked
precondition, not an assumption), slice A..B positionally, and push every
member onto the existing BFS stack. Local, ~30 lines, keeps the module's
policy of depending only on a small set of individually verified AST
attributes (adds one: `CobolParagraph.location.line`).

**B. Reuse cobolparser's `ProgramFlowAnalyzer` PERFORM_THRU edges /
`_range_members`.** Avoids duplicating the slice logic but pulls the
whole flow analyzer into the gate's dependency surface, against
refusal.py's stated policy ("not cobolparser's ProgramFlowAnalyzer …
keeps this module's correctness checkable against the same small set of
verified attributes"). Rejected.

**C. Reachability-only (no `.cut` driver THRU).** Smaller, but
THRU-shaped paragraphs themselves would stay untestable: a plain
`PERFORM MAIN-PROCESS` of a paragraph that ends in `GO TO MAIN-EXIT`
jumps outside the perform range — undefined/wrong behavior — so
analysis-only support is incomplete in exactly the programs that need
THRU. Rejected (user chose full support).

## Design (approach A)

### Range expansion in `_reachable_paragraphs`

- Build `ordered = _all_paragraphs(procedure)` sorted by
  `location.line`; verify the resulting line sequence is strictly
  increasing. If verification fails (a parser regression — fact 2 says
  it holds today), every THRU expansion in the program refuses
  fail-closed rather than guessing at an order.
- BFS unchanged for plain PERFORMs. When a reachable statement has
  `thru_paragraph`, compute the range: first occurrence of the target and
  of the thru name in `ordered`, slice inclusive, push every member's
  name onto the stack (phantom `"."` members included — see caveat).
  Members' own PERFORMs are then followed transitively by the existing
  loop.
- The function's second return value changes from "paragraph names
  containing a THRU" to a list of range problems (paragraph name +
  reason), which `check_test_case` turns into refusals.

### Narrowed `UNSUPPORTED_PERFORM_THRU` refusal

The code survives but fires only for degenerate ranges of *in-program*
`PERFORM ... THRU` statements (driver-side ranges written in the `.cut`
use `UNKNOWN_PARAGRAPH` for missing endpoints — the author's typo — and
this code for the rest), each message naming the exact problem:

1. **Missing endpoint** — target or thru name not found in the
   PROCEDURE DIVISION.
2. **Backwards range** — the thru paragraph's first occurrence precedes
   the target's in source order (runtime behavior is
   implementation-defined; refuse rather than guess).
3. **Ambiguous endpoint** — either endpoint name occurs more than once
   among real (non-`"."`) paragraphs (the `by_name` dict silently
   collapses duplicates today; a range between ambiguous endpoints could
   silently cover the wrong slice).
4. **Order verification failed** — fact 2's strict-increase check did
   not hold for this program.

### Phantom `"."` paragraph caveat

A `"."` paragraph inside a range is included positionally, so its
boundary sites are considered reachable. Because reachability is tracked
by *name* and all phantom paragraphs share `"."`, this over-approximates:
every `"."` site program-wide becomes reachable once any one is. That is
the fail-closed direction — at worst a spurious UNMOCKED_* refusal
naming a real statement, never a silently unmocked boundary — and the
layout (a boundary statement stranded after a sentence period) is rare.
Documented in the refusal-message text when it happens.

### `.cut` driver-side THRU

- **`dsl/parser.py`** — `_PERFORM_RE` becomes
  `^PERFORM\s+(?P<target>\S+)(?:\s+(?:THRU|THROUGH)\s+(?P<thru>\S+))?$`.
- **`dsl/model.py`** — `MockTestCase` gains `perform_thru: str | None`
  (default None).
- **`splicer/driver.py`** — `_build_testcase_paragraph` emits
  `PERFORM {target} THRU {thru}` when set (GnuCOBOL executes the range
  natively; no other driver change).
- **`analysis/refusal.py`** — `check_test_case` seeds reachability with
  the driver range when `perform_thru` is set: same expansion, same
  degenerate-range refusals; `UNKNOWN_PARAGRAPH` continues to cover a
  missing target and now also a missing driver-side thru endpoint.

### Out of scope (unchanged behavior)

- **GO TO** stays invisible to reachability, as today for plain
  PERFORMs. The idiomatic in-range `GO TO <exit-para>` is covered
  positionally by the expansion; a GO TO jumping *out* of a range is the
  same pre-existing blind spot it is everywhere else.
- **`dsl/generator.py`** scaffolds stay per-paragraph
  (`PERFORM <paragraph>`); scaffolding THRU-shaped entry points from GO
  TO analysis is a possible follow-up, not this iteration.

### Failure modes

- Every degenerate range keeps a refusal naming the exact problem — no
  silent skips, no best-effort endpoint guessing (unlike cobolparser's
  flow analyzer, which returns best-effort `[start, end]`; the gate must
  not).
- Over-approximation from phantom `"."` name collision refuses loudly
  (UNMOCKED_*) rather than under-mocking.
- A THRU range covering a paragraph with an unspliceable nested site
  simply makes that site reachable — the existing
  UNSUPPORTED_NESTED_MOCK_TARGET machinery fires as usual.

### Testing

- Unit (`test_refusal*`): flip
  `test_per_case_check_refuses_reachable_perform_thru` to acceptance —
  a CALL in a mid-range paragraph is now reachable (UNMOCKED_CALL when
  unmocked, clean when mocked); new tests for each degenerate-range
  refusal (missing endpoint, backwards, ambiguous endpoint); a range
  spanning sections; a phantom `"."` paragraph inside a range; transitive
  PERFORM out of a range member.
- Unit (`test_dsl_parser*`): `PERFORM A THRU B`, `THROUGH` synonym,
  single-target unchanged, trailing junk still rejected.
- Unit (`test_driver`): emitted `PERFORM A THRU B` line; single-target
  emission unchanged.
- Integration: new fixture `thru_boundaries.cbl` + `.cut` — a
  GO-TO-exit-style paragraph invoked via driver-side
  `PERFORM ... THRU ...`, with a mocked CALL in a mid-range paragraph —
  compiled and executed in the GnuCOBOL container, asserting PASS and
  tally verification (mirrors `nested_boundaries`).
- README: move `PERFORM ... THRU` from the refused list to the supported
  list, documenting the degenerate-range refusals.
