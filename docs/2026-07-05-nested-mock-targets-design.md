# Nested Mock Targets — Design

Date: 2026-07-05
Status: approved for implementation

## Problem

Every boundary statement nested inside a conditional/loop body (IF/ELSE
branches, EVALUATE WHEN branches, inline PERFORM bodies) is currently
refused when mocked (`UNSUPPORTED_NESTED_MOCK_TARGET`), and a nested EXEC
SQL/CICS/DLI anywhere refuses the whole file (`NESTED_EXEC`). The stated
reason: cobolparser's AST records only statement *start* locations, so the
splicer cannot know where a nested statement's replacement span ends —
the span would swallow its enclosing block's terminator (END-IF,
END-EVALUATE, ...) and corrupt control flow (verified by an earlier failed
attempt; see the orchestrator module docstring).

Real programs bury boundary statements inside conditionals constantly, so
this refusal blocks mocking for a large class of programs. Goal: make
nested boundary statements of **all** categories (CALL/MQ, the eight
file-op verbs, EXEC SQL/CICS/DLI, console ACCEPT) mockable wherever that
can be done *provably safely*, and keep a narrowed, precisely-worded
refusal for the layouts where it cannot.

## Key facts (verified empirically against cobolparser)

1. Nested statements carry accurate `location.line`/`location.column`
   values indexed into the *normalized* text — the same text the splicer
   edits. (Verified: CALL inside IF/ELSE/WHEN/inline-PERFORM all report
   correct 1-indexed line and column.)
2. `CobolLexer` over the normalized text yields located tokens for every
   scope word the AST lacks: `ELSE`, `WHEN`, `END-IF`, `END-EVALUATE`,
   `END-PERFORM`, `OTHERWISE` are dedicated token types, and every other
   `END-<verb>` word (END-READ, END-CALL, END-WRITE, ...) lexes as an
   IDENTIFIER whose value is the word itself, with line/column.
3. cobolparser does **not** populate IO-statement clause bodies: a
   `READ ... AT END CALL "X"` yields `at_end_clause == []` and the inner
   CALL appears nowhere in the AST. Statements inside IO clause bodies are
   therefore invisible to analysis (they are, however, physically removed
   whenever the enclosing IO statement is spliced, so they can never
   execute behind a mock).
4. `CALL ... ON EXCEPTION` bodies *are* populated — over-eagerly: the
   parser can misattribute statements that follow END-CALL into the
   exception body, marking genuinely top-level statements as nested. Those
   statements are refused today and remain refused under this design
   (fail-closed, no regression).

## Approaches considered

**A. Scope-token span map (chosen).** Build an augmented boundary map for
nested spans: all statement start lines at every depth (from the AST walk)
plus all scope-token lines (from the lexer), excluding tokens inside
`EXEC ... END-EXEC` ranges (embedded SQL/CICS text may contain WHEN/ELSE/
END-... words). A nested statement's span runs from its start line to the
line before the next boundary. Strict layout preconditions (below) make
the span provably safe or the site stays refused. Local to mockymock,
incremental, fail-closed.

**B. Replace nested statements with a one-line `PERFORM UT-MOCK-n` to an
appended dispatch paragraph.** Rejected: it still requires exactly the
same span detection to remove the original statement; the only gain is a
smaller inline replacement, which buys nothing (an EVALUATE block is legal
at any nesting depth).

**C. Extend cobolparser to record block-terminator/end locations.**
Cleanest long-term, but a cross-repo parser change with vendor-sync
implications, and fact 3 shows clause bodies are unpopulated too — full
fidelity is a parser project of its own. Rejected for this iteration.

## Design (approach A)

### Spliceability rules for a nested site

A nested `BoundarySite` is spliceable iff **all** hold:

1. **Control-flow ancestry only.** No ancestor statement is itself a
   boundary statement (CALL, file-op, EXEC, ACCEPT, SORT/MERGE family).
   Ancestors must be pure control flow: IF, EVALUATE, inline PERFORM.
   (A site inside a mocked outer statement's clause would be commented out
   together with it — its directive could never fire.)
2. **No clause bodies of its own.** `_nested_statement_lists(stmt)` is
   empty — a nested READ with its own AT END body has internal boundaries
   that would truncate the span. (Given fact 3 this mostly guards CALL
   ON EXCEPTION/OVERFLOW handlers today, plus any future parser upgrades.)
3. **Owns its start line.** Nothing but whitespace precedes the statement
   on its start line, and no other boundary sits on that line
   (`IF X CALL "F"` and `WHEN "A" CALL "F"` single-liners are refused).
   Own-verb terminators (END-CALL for a CALL site, END-READ for READ, ...)
   are exempt — they belong to the statement.
4. **Clean next boundary.** A next boundary exists on a later line and
   nothing but whitespace precedes it on its line (refuses e.g. a
   trailing `... END-IF` glued to the statement's last line).
5. **EXEC only:** the span's text contains `END-EXEC` (otherwise the
   splice would leave a dangling terminator).

Span = `[start_line, next_boundary_line - 1]` where the boundary search
ignores own-verb terminator tokens (so an explicit END-CALL/END-READ line
is *included* in the span). The orchestrator's existing trailing-period
rule applies unchanged: a period on the span's last line re-attaches to
the replacement's last line, preserving the enclosing sentence exactly.

### Component changes

- **`analysis/mock_surface.py`** — `_walk_statements` tracks whether the
  recursion entered a *boundary* statement's clause body and sets a new
  `BoundarySite.nested_in_boundary` flag. Two new annotation fields on
  `BoundarySite` (filled later by the splicer layer): `span` and
  `unspliceable_reason`.
- **`splicer/source_map.py`** — new `collect_scope_map(program, lines)`
  (AST statement starts at all depths + lexer scope tokens, EXEC ranges
  excluded, phantom-"." paragraphs excluded as today) and
  `annotate_nested_sites(surface, scope_map, lines)` which stamps every
  nested site with either a validated `span` or an `unspliceable_reason`
  string per the rules above. Top-level `collect_boundaries` /
  `statement_span` are untouched (no behavior change for top-level sites).
- **`analysis/refusal.py`** — `check_test_case`: the
  `UNSUPPORTED_NESTED_MOCK_TARGET` branch fires only when the matched
  nested site has `unspliceable_reason`, and the message cites that
  reason. `check_nested_exec`: refuses only nested EXEC sites with
  `unspliceable_reason` (still whole-program: every EXEC must be stubbed
  for cobc to compile). Both now require annotation to have run; nested
  sites left unannotated are treated as unspliceable (fail closed).
- **`splicer/orchestrator.py`** — nested sites are no longer skipped:
  a mocked nested site gets the same EVALUATE dispatch block, an unmocked
  nested EXEC gets the trap stub, both at `site.span`; an unmocked nested
  non-EXEC site is left in place as before. A nested site reaching the
  splicer without a span raises (the gate should have refused it).
- **`dsl/generator.py` + `cli/main.py`** — `generate` now normalizes the
  source, builds the scope map, and annotates the surface, so the
  scaffold includes spliceable nested sites; `_report_unsupported_
  boundaries` lists only genuinely unspliceable ones, citing the reason.
  `run` builds normalized lines/scope map before the refusal checks
  (minor reorder) and passes the annotated surface through.

### Failure modes

- Every unsupported layout keeps a refusal with a message naming the
  exact precondition that failed — no silent skips.
- Residual risk: text invisible to both the AST and the scope-token scan
  (e.g. an IF/END-IF pair inside an unpopulated IO clause body of a
  *nested* IO statement) can truncate a span. The leftover fragment is a
  dangling scope terminator, which GnuCOBOL rejects at compile time — a
  loud failure, never a silently wrong test result. Same fidelity
  assumption the top-level splicer already makes.

### Testing

- Unit (`test_mock_surface*`): `nested_in_boundary` set for CALL-handler
  bodies, unset for IF/EVALUATE/PERFORM nesting.
- Unit (`test_source_map`): scope-map contents; spans for nested sites in
  IF-then, ELSE, WHEN, WHEN OTHER, inline PERFORM; own-verb terminator
  inclusion; refusal reasons for each precondition (same-line nesting,
  glued terminator, clause bodies, boundary ancestry, missing END-EXEC).
- Unit (`test_refusal*`): narrowed `UNSUPPORTED_NESTED_MOCK_TARGET` /
  `NESTED_EXEC` — spliceable nested sites pass the gate, unspliceable
  ones still refuse.
- Unit (`test_orchestrator`): spliced output for a mocked nested CALL
  (dispatch inside the IF body, END-IF untouched, period preserved) and
  a nested unmocked EXEC trap.
- Unit (`test_dsl_generator`): scaffold covers spliceable nested sites.
- Integration: a fixture program with nested CALL + nested EXEC SQL
  through `mockymock run` end-to-end (compile + execute in Docker),
  asserting PASS and tally verification.
