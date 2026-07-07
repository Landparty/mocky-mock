# mocky-mock OKF Bundle — Update Log

## 2026-07-07
* **Refuse on cobolparser's new dropped-content warnings**
  ([analysis](analysis.md), [cli](cli.md), [integration](integration.md)):
  cobolparser's 2026-07-07 silent-drop remediation (upstream PR #77) made
  `ParseResult.warnings` the signal for content dropped from an otherwise
  clean parse — unsupported verbs (INVOKE, EXHIBIT, ...), unparsed clause
  leftovers, and multi-program compilation units (extra programs land in
  `ast.contained_programs`, which the splicer and reachability BFS never
  look at). `check_whole_program` now emits a `PARSE_WARNING` refusal per
  warning, and both `generate` and `run` gate on the returned reasons
  instead of `result.success` alone. New `check_expansion_warnings` refuses
  (`EXPANSION_WARNING`) on lossy copybook decodes surfaced via
  `CopybookExpansion.statistics.warnings` — but only the `"Lossy decode of"`
  class: the same channel carries advisory lint heuristics ("may be missing
  terminating period") that false-positive on valid copybooks (verified
  against `tests/integration/fixtures/copybook_example`). Tests:
  `test_refusal.py` (PARSE_WARNING for INVOKE and multi-program units,
  EXPANSION_WARNING for lossy decode, advisory-lint pass-through),
  `test_cli.py` (generate + run refuse INVOKER programs),
  `test_copybook_expansion.py` (generate refuses lossy copybook).
* **Verified mockymock against cobolparser main after its audit-fix wave**
  (PRs #68–#77: OPEN multi-mode capture, IO clause bodies, EVALUATE WHEN
  children, IF-condition precedence, statement-swallow fixes,
  numeric-literal continuation, C1–C8/H3/H6b silent-drop fixes): full suite
  green (unit + Docker integration). The `task_c5e3b268` dropped-EXEC-SQL
  bug no longer reproduces (COMPUTE/statement-boundary fixes); the DEPTMQP
  xfail was already removed. Stale contract note updated: the
  `fix/open-multi-mode-file-capture` branch requirement is now "cobol-parser
  at or after PR #68 on main". Known upstream residual documented in
  [integration](integration.md): an unknown verb directly after a
  period-less statement can still be swallowed silently by the preceding
  statement's parser (no warning) — period-terminated layouts are covered.

## 2026-07-06
* **Initialization**: Established the OKF bundle for mocky-mock, matching the
  pattern used by sibling LegacyLens repos (`cobol-parser`, `backend`, etc.).
  Authored from the current source tree (`mockymock/dsl`, `splicer`,
  `runtime`, `analysis`, `report`, `cli`) plus `interface-contract.md` and the
  `docs/*-design.md` history (MVP, Docker toolchain, mock-all-boundaries,
  nested-mock-targets, dynamic-call-mocks, PERFORM THRU): [dsl](dsl.md),
  [analysis](analysis.md), [splicer](splicer.md), [runtime](runtime.md),
  [report](report.md), [cli](cli.md), [integration](integration.md),
  [testing](testing.md).
* **Fixed misleading `[PASS]` on a crashed test case** ([report](report.md)):
  a `.cut` case whose `PERFORM` target reaches `STOP RUN` (directly or
  transitively) kills the compiled test binary before that case's END marker
  (or any FAIL marker) prints, and `TestResult.passed` was defined purely as
  `not failure_reasons` — absence of a FAIL marker read as a pass even
  though the case's checks never ran. `TestResult` now tracks `ended` (set
  when `CASE <id> END` is matched) and exposes `crashed = not ended`;
  `passed` requires both no failure reasons and `not crashed`.
  `format_console`/`format_junit_xml` render crashed cases as `[CRASH]` /
  `<error>` instead of `[PASS]`. The aggregate summary line/`tests=`
  attribute also fixed: run count, `tests=`, and (console) failed count all
  fall back to values reconstructed from `suite.results` when the
  SUMMARY-derived field is 0 (SUMMARY line never printed), so the report no
  longer says "0 run"/"0 failed" underneath visibly-rendered PASS/FAIL/CRASH
  case lines. CLI exit code behavior (`all_passed`) was already correct and
  is unchanged — this fixes the human-facing console/JUnit report only.
  Found while wiring up the real-world COBOL e2e examples (see
  `docs/2026-07-06-realworld-cobol-examples-design.md`) with a DEPTMQP-based
  repro. README gained a "Known limitation" note.
* **Recognized WORKING-STORAGE `DECLARE ... CURSOR FOR SELECT` in
  `transform_data_division_exec`** ([splicer](splicer.md)):
  `mockymock/splicer/sqlca.py`'s `_handle_block` commented out `DECLARE ...
  TABLE` but not `DECLARE <cursor> CURSOR FOR SELECT ... END-EXEC`, so any
  program using the standard embedded-SQL batch idiom (cursor declared in
  WORKING-STORAGE ahead of a `PERFORM ... UNTIL SQLCODE = 100` fetch loop —
  e.g. `legacy-application/cobol/ACCTMNT.cbl`'s `ACCT_CURSOR`, and the same
  pattern in `LOANPMT.cbl`/`GLRECON.cbl`/`CTRRPT.cbl`/`DORMACCT.cbl`/
  `STMTGEN.cbl`/`INTCALC.cbl`) fell through to the fail-closed
  "unrecognized" branch and the whole program was refused with
  `UNSUPPORTED_DATA_DIVISION_EXEC` before any test case ran. Fixed by
  extending the DECLARE regex's alternation from `TABLE` to `(TABLE|CURSOR)`
  — a cursor declaration is equally purely-declarative; the actual
  OPEN/FETCH/CLOSE statements are separate PROCEDURE DIVISION EXEC SQL
  statements already handled by the existing boundary-mocking machinery.
  Added `test_declare_cursor_is_commented_out` and
  `test_declare_cursor_for_update_is_commented_out` to
  `tests/unit/test_sqlca.py`. This alone does not yet unblock an
  `ACCTMNT`-based example: a separate cobol-parser bug (task_c5e3b268) drops
  some of `ACCTMNT.cbl`'s own EXEC SQL UPDATE/INSERT statements from the
  AST, causing a different, harder compile failure upstream of this fix.
