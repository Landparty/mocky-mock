# Corpus Sweep Report

## 2026-07-17 re-sweep — 34/34 clean again after three PARSE_WARNING regressions

Re-swept against current cobolparser `main`. Since the 2026-07-14 pin
(`b3e81ed`), upstream's silent-drop remediation grew two new warning
sources (the lexer's unterminated-string-at-end-of-line warning and the
data-item clause parser's unparsed-token warning), and they exposed **3
programs whose content was being silently corrupted** — previously
invisible because the drops produced no signal at all. mockymock's
fail-closed PARSE_WARNING gate caught all three (5 warnings total):

1. **`cobol/EODPROC.cbl`** — two distinct problems:
   - `05 FILLER PIC X(133) VALUE ALL '='.` (the report-separator idiom):
     cobolparser consumed `ALL` as a complete figurative-constant value
     and dropped the `'='` literal as an unparsed token. **Fixed
     upstream** in cobolparser (`parse_value_clause` now returns
     `ALL "="`, round-trippable into `MOVE ... TO ...`; regression suite
     `tests/regression/test_value_all_clause.py`, pinned below).
   - The report-header `VALUE 'FIRST NATIONAL BANK - END OF DAY
     PROCESSING REPORT'.` line ended at column 74 — the closing quote and
     sentence period sat in the ignored identification area, so
     fixed-format normalization truncated the literal (a real mainframe
     compiler would reject this line too). **Fixed in the corpus**
     (legacy-application) by re-indenting the continuation line.
2. **`cobol/ACCTMNT.cbl`** — `05 HV-RATE-IND PIC X(01) INDICATOR IS
   HV-RATE-IND-IND.`: `INDICATOR` is not a data-description clause in IBM
   Enterprise COBOL (or GnuCOBOL) — the tokens were dropped. **Fixed in
   the corpus** by removing the invalid clause (the separate
   `HV-RATE-IND-IND` half-word item already models the SQL indicator
   convention).
3. **`tests/integration/fixtures/walking_skeleton.cbl`** — line 7 was 80
   characters, so column-72 clipping cut the closing quote off the CASE
   marker string. **Fixed in this repo** by shortening the display text
   (the integration test only asserts on the `__MOCKYMOCK__ CASE 001
   START:` prefix).

The truncation hunt also surfaced **silent** column-72 clips that emitted
no warning at all and produced corrupted content (all fixed in
legacy-application): the `END),` tails of eight `SUM(CASE ...)` lines in
EODPROC's daily-totals `SELECT` were missing from the captured SQL text;
ACCTMNT's dormancy `DISPLAY` truncated the operand `WS-PARM-DORM-DAYS` to
the (undeclared) name `WS-PARM-DORM-D`; and CTRRPT.cbl / copybook
MQMSG.cpy each lost a sentence-terminating period at column 73. A
whole-corpus scan for code lines extending past column 72 now comes back
empty (the NIST `.CBL` examples carry classic sequence numbers in columns
73–80, which is legitimate fixed format, not truncation).

Two more closures in the same pass:

- `scripts/corpus_sweep.py` now also sweeps `examples/**/*.CBL` — `rglob`
  is case-sensitive on Linux, so the four NIST CCVS85 examples were
  silently absent from every prior Linux sweep.
- The 2026-07-14 log's follow-up flag on `IC101A`/`IC116M` (VALUE literal
  on the line after the `VALUE` keyword parsed as `value_clause=None`) is
  resolved at current cobolparser main — both now generate clean, as the
  table shows.

Result at cobolparser main + these corpus/fixture fixes:

Swept 34 COBOL program(s) with `mockymock generate` (parse-and-analyze only, no Docker/compile).

| Program | Parsed OK? | Generate Exit | Refusal Codes | Unmockable Boundaries (by category) |
|---|---|---|---|---|
| cobol/ACCTMNT.cbl | yes | 0 | - | - |
| cobol/ACCTPRG.cbl | yes | 0 | - | - |
| cobol/ACHPROC.cbl | yes | 0 | - | - |
| cobol/CHKCLR.cbl | yes | 0 | - | - |
| cobol/CTRRPT.cbl | yes | 0 | - | - |
| cobol/DEPTBMP.cbl | yes | 0 | - | - |
| cobol/DEPTIMSM.cbl | yes | 0 | - | - |
| cobol/DEPTMQC.cbl | yes | 0 | - | - |
| cobol/DEPTMQP.cbl | yes | 0 | - | - |
| cobol/DORMACCT.cbl | yes | 0 | - | - |
| cobol/EODPROC.cbl | yes | 0 | - | - |
| cobol/FNDTXFR.cbl | yes | 0 | - | - |
| cobol/GLRECON.cbl | yes | 0 | - | - |
| cobol/INTCALC.cbl | yes | 0 | - | - |
| cobol/LNRECOV.cbl | yes | 0 | - | - |
| cobol/LOANPMT.cbl | yes | 0 | - | - |
| cobol/STMTGEN.cbl | yes | 0 | - | - |
| tests/integration/fixtures/copybook_example/MAINPGM.cbl | yes | 0 | - | - |
| tests/integration/fixtures/dynamic_call.cbl | yes | 0 | - | - |
| tests/integration/fixtures/nested_boundaries.cbl | yes | 0 | - | - |
| tests/integration/fixtures/sql_cursor_example/CUSTPROG.cbl | yes | 0 | - | - |
| tests/integration/fixtures/thru_boundaries.cbl | yes | 0 | - | - |
| tests/integration/fixtures/walking_skeleton.cbl | yes | 0 | - | - |
| examples/custinq/CUSTINQ.cbl | yes | 0 | - | - |
| examples/invupdt/INVUPDT.cbl | yes | 0 | - | - |
| examples/nist-cobol85/IC101A.CBL | yes | 0 | - | - |
| examples/nist-cobol85/IC116M.CBL | yes | 0 | - | - |
| examples/nist-cobol85/IC117M.CBL | yes | 0 | - | - |
| examples/nist-cobol85/OBIC1A.CBL | yes | 0 | - | - |
| examples/ordrproc/ORDRPROC.cbl | yes | 0 | - | - |
| examples/raterte/RATERTE.cbl | yes | 0 | - | - |
| examples/real-world/ACCTPRG/ACCTPRG.cbl | yes | 0 | - | - |
| examples/real-world/DEPTMQC/DEPTMQC.cbl | yes | 0 | - | - |
| examples/real-world/DEPTMQP/DEPTMQP.cbl | yes | 0 | - | - |

Totals: 34 swept, 34 parsed OK, 34 generate exit 0, 0 exceptions, zero
refusal codes, zero unmockable-boundary categories. The 2026-07-07
caveat still applies unchanged: this measures `generate` only, not the
runtime per-`TESTCASE` refusal taxonomy.

## 2026-07-08 addendum — the "no new mockymock engine feature" line below was incomplete

This report's clean `generate` result for `ACCTPRG`/`DEPTBMP`/`DEPTIMSM`/
`FNDTXFR`/`LNRECOV` measures parse + static whole-program/boundary analysis
only (see the caveat already in this report) — it never actually ran a
`.cut` against them. Doing so surfaced a real runtime crash: each has a
named `ENTRY 'DLITCBL' USING <linkage-group>` alongside a bare default
entry, and mockymock's PERFORM-only driver never binds the LINKAGE storage
that `USING` clause would — verified live against the real GnuCOBOL
toolchain, SIGSEGV (exit 139), not a hypothetical.

**Fixed, not just refused**: `mockymock/analysis/linkage.py` +
`mockymock/splicer/linkage.py` neutralize this shape (comment out the ENTRY
statement(s) and the `LINKAGE SECTION.` header line — GnuCOBOL folds the
data items into WORKING-STORAGE once the header's gone; no relocation
needed), gated by `refusal.check_linkage_layout`
(`UNSUPPORTED_LINKAGE_LAYOUT`) for the structurally-unsafe shapes this
transform hasn't been verified against. `CALL 'CBLTDLI'` needed no new
mocking primitive — already an ordinary `MockCategory.CALL` boundary. See
[docs/2026-07-08-ims-linkage-support-design.md](2026-07-08-ims-linkage-support-design.md)
and `examples/real-world/ACCTPRG/` for a full worked, passing example.

All five programs still `generate` clean today (`check_linkage_layout`'s
guardrails hold for all of them) — the difference is what happens when a
`.cut` is actually run against them, which is exactly the gap this
addendum closes.

## Findings (refreshed 2026-07-07, second pass)

**This is a re-sweep, not the original run.** The original sweep (see "Original findings" below) found 21/26 programs parsing and one blocking cobolparser bug (`EVALUATE`/`WHEN` selector parsing) gating the other 5. Both that bug and, on this re-sweep, three further cobolparser content-drop bugs it surfaced have since been fixed. **Result: 26/26 programs now parse and `generate` cleanly, with zero refusal codes and zero unmockable-boundary categories anywhere in the corpus.**

**What changed since the original sweep:**

1. **The `EVALUATE ... WHEN '  '` blank-selector bug is fixed.** The lexer strips quotes off string literals, so the IMS DL/I "call succeeded" status idiom (`WHEN '  '`) arrived as a whitespace-only token that the selector builder discarded as empty, collapsing the clause to zero selectors and reporting `WHEN clause must have at least one selector` — a false positive on valid programs. Fixed upstream (`cobolparser` commit `d8ad880`, already on `main` and already covered by this repo's CI pin at the time of this re-sweep). This alone unblocked all 5 previously-blocked IMS/DL-I programs: **ACCTPRG, DEPTBMP, DEPTIMSM, FNDTXFR, LNRECOV all now parse.**

2. **Re-running the sweep (with the EVALUATE fix in place, before the fixes below existed) surfaced three further, different content-drop bugs**, each producing a `PARSE_WARNING` (cobolparser's "AST is missing content" signal) rather than a hard parse error — meaning these three programs *appeared* to parse (`success=True`) but were silently losing statements. At that point in the investigation, mockymock's whole-program refusal gate correctly caught these `PARSE_WARNING`s and refused the programs rather than splicing an incomplete AST — the three bugs below were root-caused from those refusals, then fixed upstream and this repo's CI pin was bumped to include the fix (see cobol-parser PR #80). **The final sweep table and totals below reflect the corpus swept *after* that pin bump: all three programs now parse and generate clean, with no `PARSE_WARNING` and no refusal of any kind.**
   - **`ACCTMNT.cbl`**: `DISPLAY 'ACCTMNT: DORMANT ACCOUNTS FLAGGED=' SQLERRD(3)` — a subscripted operand (`SQLERRD` is the generated SQLCA's `OCCURS 6` array) in a `DISPLAY` item list. The parser aborted the item list at the bare `(` token, dropping the subscript and everything after it.
   - **`GLRECON.cbl`**: `WRITE GLEXCPT-RECORD FROM 'GENERAL LEDGER OUT OF BALANCE - REQUIRES '` — a `WRITE ... FROM` clause whose source is a string literal (an IBM/GnuCOBOL extension), not an identifier. The parser's `FROM` clause only accepted an identifier, leaving the literal unconsumed.
   - **`LOANPMT.cbl`**: `SUBTRACT WS-INTEREST-PORTION FROM HV-PAYMENT-AMOUNT` with `GIVING WS-PRINCIPAL-PORTION` on the next line — the 3-operand `SUBTRACT ... FROM ... GIVING` form. The `FROM` branch never checked for a trailing `GIVING` (unlike the `ADD ... TO` branch, which already did), and a deeper root cause made it worse: the shared `consume_keyword_and_operand` helper only skipped continuation-line `NEWLINE` tokens *between* a keyword and its operand, not *before* checking whether the keyword was present at all — so `GIVING` on its own line (ordinary free-form COBOL layout) was missed entirely, regardless of nesting.

   All three are fixed upstream (`cobolparser` PR #80, pinned below). Root-caused, reproduced in isolation, and regression-tested in `cobolparser`'s own suite (`tests/unit/test_display_parser.py`, `tests/unit/test_arithmetic_size_error_branches.py`, `tests/unit/io_statements/test_write_close_parsers.py`) — see that repo's CHANGELOG and `.okf/log.md` for detail. No mockymock-side change was needed; these were purely cobolparser AST-fidelity gaps.

3. **No new mockymock-side gaps found.** Across all 26 programs, `generate` detects zero unmockable-boundary categories (SORT/MERGE, identifier-less dynamic CALL, unspliceable nested sites) and zero refusal codes of any kind. The original sweep's finding that CBLTDLI (the classic IMS DL/I call interface, invoked as an ordinary static `CALL 'CBLTDLI' USING ...`) needs no new mockymock engine feature is now **confirmed directly** rather than estimated from an unparsed grep: ACCTPRG, DEPTBMP, DEPTIMSM, FNDTXFR, and LNRECOV all parse and generate clean using the existing `MockCategory.CALL` boundary.

**Caveat, unchanged from the original sweep:** this measures `mockymock generate` (parse + whole-program/static-boundary analysis) only — it does not exercise the runtime-only per-`TESTCASE` refusal taxonomy (`UNMOCKED_*`, `AMBIGUOUS_MOCK`, `UNSUPPORTED_NESTED_MOCK_TARGET`, `UNSUPPORTED_PERFORM_THRU`, `UNKNOWN_PARAGRAPH`, `UNMATCHED_MOCK`, `VERIFY_WITHOUT_MOCK`, `NESTED_EXEC`), which only fires once real `.cut` test cases are run (`mockymock run`) against a program. A clean `generate` result is necessary but not sufficient for a program to be fully testable end-to-end.

Swept 26 COBOL program(s) with `mockymock generate` (parse-and-analyze only, no Docker/compile).

| Program | Parsed OK? | Generate Exit | Refusal Codes | Unmockable Boundaries (by category) |
|---|---|---|---|---|
| cobol/ACCTMNT.cbl | yes | 0 | - | - |
| cobol/ACCTPRG.cbl | yes | 0 | - | - |
| cobol/ACHPROC.cbl | yes | 0 | - | - |
| cobol/CHKCLR.cbl | yes | 0 | - | - |
| cobol/CTRRPT.cbl | yes | 0 | - | - |
| cobol/DEPTBMP.cbl | yes | 0 | - | - |
| cobol/DEPTIMSM.cbl | yes | 0 | - | - |
| cobol/DEPTMQC.cbl | yes | 0 | - | - |
| cobol/DEPTMQP.cbl | yes | 0 | - | - |
| cobol/DORMACCT.cbl | yes | 0 | - | - |
| cobol/EODPROC.cbl | yes | 0 | - | - |
| cobol/FNDTXFR.cbl | yes | 0 | - | - |
| cobol/GLRECON.cbl | yes | 0 | - | - |
| cobol/INTCALC.cbl | yes | 0 | - | - |
| cobol/LNRECOV.cbl | yes | 0 | - | - |
| cobol/LOANPMT.cbl | yes | 0 | - | - |
| cobol/STMTGEN.cbl | yes | 0 | - | - |
| tests/integration/fixtures/copybook_example/MAINPGM.cbl | yes | 0 | - | - |
| tests/integration/fixtures/dynamic_call.cbl | yes | 0 | - | - |
| tests/integration/fixtures/nested_boundaries.cbl | yes | 0 | - | - |
| tests/integration/fixtures/thru_boundaries.cbl | yes | 0 | - | - |
| tests/integration/fixtures/walking_skeleton.cbl | yes | 0 | - | - |
| examples/invupdt/INVUPDT.cbl | yes | 0 | - | - |
| examples/ordrproc/ORDRPROC.cbl | yes | 0 | - | - |
| examples/real-world/DEPTMQC/DEPTMQC.cbl | yes | 0 | - | - |
| examples/real-world/DEPTMQP/DEPTMQP.cbl | yes | 0 | - | - |

## Totals

- Programs swept: 26
- Parsed OK (no parse error, no exception): 26
- Generate exited 0 (clean): 26
- Raised an uncaught exception: 0

### Refusal codes across corpus

(none)

### Unmockable-boundary categories across corpus

(none)

## Next steps

With the static/whole-program surface now fully clean, the highest-leverage remaining unknown is the runtime-only per-`TESTCASE` refusal taxonomy noted in the caveat above — untested by this sweep. Per the existing roadmap (`docs/superpowers/plans/2026-07-06-real-world-readiness.md`), candidates for genuinely new engine work (Tier 3/4, none yet built) include Report Writer (`REPORT SECTION`/`GENERATE`, currently unsupported), `SORT`/`MERGE` (currently a blanket refusal), and `STOP RUN`/`GOBACK` handling (needed to drive a program through its real multi-record read loop rather than a single sub-paragraph, as `examples/real-world/DEPTMQP`/`DEPTMQC` had to work around).

---

## Original findings (2026-07-06, first pass — superseded above, kept for history)

**Scope of the 17 real-world programs** (`../legacy-application/cobol/*.cbl`): **12/17 parse** (no parse error, no exception) and **12/17 also generate cleanly** (exit 0) — every program that parses also generates cleanly; nothing that parses hits a whole-program refusal or an unmockable-boundary detection. The other **5/17 fail to parse**: ACCTPRG, DEPTBMP, DEPTIMSM, FNDTXFR, LNRECOV.

**There is exactly one refusal code in this corpus, not three: `PARSE_ERROR` (5 programs, one per blocked file).** No `UNRESOLVED_COPYBOOK`, no whole-program or per-boundary refusal of any other kind fires anywhere in the swept corpus (all 26 files, including fixtures/examples). The brief asks for "the 3 most common" — there is only one to report; padding to three would misrepresent the data.

**Root cause of all 5 parse failures is a single cobolparser bug, not a mockymock gap.** Every failure is the identical message, `WHEN clause must have at least one selector`, on an `EVALUATE` construct — 2 to 4 occurrences per file, always the same shape. This is a `cobolparser` defect (outside mockymock's own code) that happens to gate 29% of the real-world corpus. Fixing it in `cobolparser` is very likely the single highest-leverage next step for corpus coverage — higher leverage than any Tier-4 mockymock engine feature, since it unblocks 5 programs at once with no mockymock-side work.

**The 5 blocked programs are exactly the IMS/DL-I programs, and that is a blind spot in this report, not a zero.** Grepping the 5 blocked `.cbl` files directly (since mockymock's own analysis never runs on them) shows every one of them calls `CBLTDLI` (the classic IMS DL/I call interface) 3-6 times each — ACCTPRG (3x), DEPTBMP (5x, incl. a CHKP checkpoint call), DEPTIMSM (4x), FNDTXFR (6x), LNRECOV (3x) — and **zero** occurrences of `EXEC CICS`, `EXEC SQL`, `EXEC DLI`, `SORT`, or `MERGE` in any of them. `CBLTDLI` is invoked as an ordinary static `CALL 'CBLTDLI' USING ...`, which the existing `MockCategory.CALL` boundary already covers structurally — so once the EVALUATE parse bug is fixed, these 5 programs likely need **no new mockymock engine feature** to become mockable, just parseable. This reclassifies "DLI support" from an open question to a probable non-issue, but it is a grep-based estimate on unparsed source, not a verified `mock_surface` result — treat it as directional, not final, until the parser bug is fixed and these 5 are re-swept.

**Among the 12/17 that do parse, and across all 26 files swept (17 real-world + 5 fixtures + 4 examples), `generate` detected zero unmockable boundary points of any category** — no SORT/MERGE, no identifier-less dynamic CALL, no unspliceable nested EXEC/CALL/file-op site. If a Tier-4 category shows zero occurrences here, per Step 5 of the brief, this is the evidence: on the currently-parseable slice of the corpus, none of SORT/MERGE, DYNAMIC_CALL (unmockable form), NESTED_EXEC, CICS, or DLI (as `EXEC DLI`) appear at all. Static `CALL 'CBLTDLI'` sites (the actual DLI-access pattern in this corpus) are not in this "unmockable" list because they're already structurally mockable as CALL sites — they simply never got analyzed due to the parse failure above.

**Important caveat on what this sweep measures.** `mockymock generate` only exercises three signal sources: parse errors, `UNRESOLVED_COPYBOOK` (via `check_unresolved_copybooks`), and the detected-but-unmockable boundary list (SORT/MERGE family, identifier-less dynamic CALL, unspliceable nested sites). It does **not** exercise the runtime-only refusal taxonomy that only `mockymock run` triggers per test case — `NESTED_EXEC`, `UNMOCKED_*`, `AMBIGUOUS_MOCK`, `UNSUPPORTED_NESTED_MOCK_TARGET`, `UNSUPPORTED_PERFORM_THRU`, `UNKNOWN_PARAGRAPH`, `UNMATCHED_MOCK`, `VERIFY_WITHOUT_MOCK`. Absence of those codes here is not evidence of their absence in the corpus; it only means this sweep never asked the question (no `.cut` test cases were run against these programs). Two positive controls were run to confirm the harness's own detectors are not silently failing to match: (1) running `ACCTMNT.cbl` with no `--copybook-path` correctly tallies `UNRESOLVED_COPYBOOK` x3; (2) a synthetic boundary-block string with a top-level and a `nested` finding line is correctly bucketed by category. Both passed, so the "(none)" totals below are a genuine finding, not a broken regex.

### Original totals

- Programs swept: 26
- Parsed OK (no parse error, no exception): 21
- Generate exited 0 (clean): 21
- Raised an uncaught exception: 0

### Original refusal codes across corpus

| Code | Count |
|---|---|
| PARSE_ERROR | 5 |

### Original unmockable-boundary categories across corpus

(none)
