# Corpus Sweep Report

## Findings

**Scope of the 17 real-world programs** (`../legacy-application/cobol/*.cbl`): **12/17 parse** (no parse error, no exception) and **12/17 also generate cleanly** (exit 0) — every program that parses also generates cleanly; nothing that parses hits a whole-program refusal or an unmockable-boundary detection. The other **5/17 fail to parse**: ACCTPRG, DEPTBMP, DEPTIMSM, FNDTXFR, LNRECOV.

**There is exactly one refusal code in this corpus, not three: `PARSE_ERROR` (5 programs, one per blocked file).** No `UNRESOLVED_COPYBOOK`, no whole-program or per-boundary refusal of any other kind fires anywhere in the swept corpus (all 26 files, including fixtures/examples). The brief asks for "the 3 most common" — there is only one to report; padding to three would misrepresent the data.

**Root cause of all 5 parse failures is a single cobolparser bug, not a mockymock gap.** Every failure is the identical message, `WHEN clause must have at least one selector`, on an `EVALUATE` construct — 2 to 4 occurrences per file, always the same shape. This is a `cobolparser` defect (outside mockymock's own code) that happens to gate 29% of the real-world corpus. Fixing it in `cobolparser` is very likely the single highest-leverage next step for corpus coverage — higher leverage than any Tier-4 mockymock engine feature, since it unblocks 5 programs at once with no mockymock-side work.

**The 5 blocked programs are exactly the IMS/DL-I programs, and that is a blind spot in this report, not a zero.** Grepping the 5 blocked `.cbl` files directly (since mockymock's own analysis never runs on them) shows every one of them calls `CBLTDLI` (the classic IMS DL/I call interface) 3-6 times each — ACCTPRG (3x), DEPTBMP (5x, incl. a CHKP checkpoint call), DEPTIMSM (4x), FNDTXFR (6x), LNRECOV (3x) — and **zero** occurrences of `EXEC CICS`, `EXEC SQL`, `EXEC DLI`, `SORT`, or `MERGE` in any of them. `CBLTDLI` is invoked as an ordinary static `CALL 'CBLTDLI' USING ...`, which the existing `MockCategory.CALL` boundary already covers structurally — so once the EVALUATE parse bug is fixed, these 5 programs likely need **no new mockymock engine feature** to become mockable, just parseable. This reclassifies "DLI support" from an open question to a probable non-issue, but it is a grep-based estimate on unparsed source, not a verified `mock_surface` result — treat it as directional, not final, until the parser bug is fixed and these 5 are re-swept.

**Among the 12/17 that do parse, and across all 26 files swept (17 real-world + 5 fixtures + 4 examples), `generate` detected zero unmockable boundary points of any category** — no SORT/MERGE, no identifier-less dynamic CALL, no unspliceable nested EXEC/CALL/file-op site. If a Tier-4 category shows zero occurrences here, per Step 5 of the brief, this is the evidence: on the currently-parseable slice of the corpus, none of SORT/MERGE, DYNAMIC_CALL (unmockable form), NESTED_EXEC, CICS, or DLI (as `EXEC DLI`) appear at all. Static `CALL 'CBLTDLI'` sites (the actual DLI-access pattern in this corpus) are not in this "unmockable" list because they're already structurally mockable as CALL sites — they simply never got analyzed due to the parse failure above.

**Important caveat on what this sweep measures.** `mockymock generate` only exercises three signal sources: parse errors, `UNRESOLVED_COPYBOOK` (via `check_unresolved_copybooks`), and the detected-but-unmockable boundary list (SORT/MERGE family, identifier-less dynamic CALL, unspliceable nested sites). It does **not** exercise the runtime-only refusal taxonomy that only `mockymock run` triggers per test case — `NESTED_EXEC`, `UNMOCKED_*`, `AMBIGUOUS_MOCK`, `UNSUPPORTED_NESTED_MOCK_TARGET`, `UNSUPPORTED_PERFORM_THRU`, `UNKNOWN_PARAGRAPH`, `UNMATCHED_MOCK`, `VERIFY_WITHOUT_MOCK`. Absence of those codes here is not evidence of their absence in the corpus; it only means this sweep never asked the question (no `.cut` test cases were run against these programs). Two positive controls were run to confirm the harness's own detectors are not silently failing to match: (1) running `ACCTMNT.cbl` with no `--copybook-path` correctly tallies `UNRESOLVED_COPYBOOK` x3; (2) a synthetic boundary-block string with a top-level and a `nested` finding line is correctly bucketed by category. Both passed, so the "(none)" totals below are a genuine finding, not a broken regex.

Swept 26 COBOL program(s) with `mockymock generate` (parse-and-analyze only, no Docker/compile).

| Program | Parsed OK? | Generate Exit | Refusal Codes | Unmockable Boundaries (by category) |
|---|---|---|---|---|
| cobol/ACCTMNT.cbl | yes | 0 | - | - |
| cobol/ACCTPRG.cbl | no | 1 | PARSE_ERROR x3 | - |
| cobol/ACHPROC.cbl | yes | 0 | - | - |
| cobol/CHKCLR.cbl | yes | 0 | - | - |
| cobol/CTRRPT.cbl | yes | 0 | - | - |
| cobol/DEPTBMP.cbl | no | 1 | PARSE_ERROR x2 | - |
| cobol/DEPTIMSM.cbl | no | 1 | PARSE_ERROR x3 | - |
| cobol/DEPTMQC.cbl | yes | 0 | - | - |
| cobol/DEPTMQP.cbl | yes | 0 | - | - |
| cobol/DORMACCT.cbl | yes | 0 | - | - |
| cobol/EODPROC.cbl | yes | 0 | - | - |
| cobol/FNDTXFR.cbl | no | 1 | PARSE_ERROR x4 | - |
| cobol/GLRECON.cbl | yes | 0 | - | - |
| cobol/INTCALC.cbl | yes | 0 | - | - |
| cobol/LNRECOV.cbl | no | 1 | PARSE_ERROR x3 | - |
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
- Parsed OK (no parse error, no exception): 21
- Generate exited 0 (clean): 21
- Raised an uncaught exception: 0

### Refusal codes across corpus

| Code | Count |
|---|---|
| PARSE_ERROR | 5 |

### Unmockable-boundary categories across corpus

(none)

