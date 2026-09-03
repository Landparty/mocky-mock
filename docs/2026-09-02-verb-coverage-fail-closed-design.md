# Every COBOL dependency mockable or refused (2026-09-02)

## Problem

cobol-parser's 2026-09-02 statement-coverage work gave every COBOL verb a
real AST node. mocky-mock's fail-closed guarantee had silently leaned on
the opposite: a verb with no parser produced a `ParseResult.warnings`
entry, and `check_whole_program` refused any warning as `PARSE_WARNING`.
Once INVOKE, CHAIN, SEND/RECEIVE/ENABLE/DISABLE/PURGE, INITIATE/GENERATE/
TERMINATE and `STOP <literal>` parsed cleanly, `mock_surface.analyze` did
not classify them, the reachability gate saw no site, and a test case
reaching one of them passed with the dependency left real.

## Decisions

1. **Closed over statement type.** `mock_surface._PASSTHROUGH_STATEMENT_NAMES`
   is an explicit by-name allowlist of classes that touch nothing outside
   the program. Anything not on it and not claimed by a boundary branch is
   a `category=None` site labelled `"unsupported statement"`, refused as
   `UNSUPPORTED_STATEMENT` when reachable. A future cobol-parser node class
   therefore shows up as a refusal, never as a silent pass. The allowlist
   was validated by sweeping 582 COBOL files across both repos.
2. **Dedicated refusals where the verb is a known external dependency:**
   `UNSUPPORTED_INVOKE`, `UNSUPPORTED_CHAIN`, `UNSUPPORTED_COMMUNICATION`,
   `UNSUPPORTED_STOP_LITERAL` (a console read, like an unmocked ACCEPT).
   Each message suggests `MOCK PARAGRAPH` or performing a caller that never
   reaches the site. These are not made mockable: object-oriented COBOL,
   Micro Focus CHAIN and the Communication Module have no place in the
   GnuCOBOL toolchain mocky-mock compiles with, so a mock category would
   promise a run that cannot happen.
3. **Report Writer is mockable.** `INITIATE`/`GENERATE`/`TERMINATE` become
   `MockCategory` members keyed by report name (bare word), spliced out
   like any other boundary statement; the RD/FD stay declared and the
   report file is never touched. This needed upstream REPORT SECTION
   parsing (added in cobol-parser in the same change), because the
   previous "REPORT SECTION not supported" warning refused every Report
   Writer program before a directive was ever considered.
4. **`XML PARSE ... PROCESSING PROCEDURE` is a flow edge.** Modeled in
   `_reachable_paragraphs` exactly like a SORT's INPUT/OUTPUT PROCEDURE,
   with THRU expansion; fails closed (`UNRESOLVED_FLOW_TARGET`) on a
   cobol-parser that only keeps the clause as text. XML/JSON `ON
   EXCEPTION` bodies are now real statement lists upstream and are walked
   through the existing `on_exception` attribute names.
5. **Version tolerance.** The new node classes are imported through
   `_optional_statement_types` (importlib, empty tuple when absent), so
   mocky-mock still imports and its suite still passes on the released
   cobol-parser the CI compat lane installs -- there the verbs still warn,
   so `PARSE_WARNING` keeps the same fail-closed outcome.

## Verification

* `tests/unit/test_verb_coverage_fail_closed.py`: classification, refusal
  code, no over-refusal (unreachable / flow-mocked), catch-all, allowlist
  integrity, Report Writer end-to-end through `lint` + `export`, XML PARSE
  edge (structured and text-only), `examples/**` corpus sweep.
* Docker-free `mockymock lint` over all 43 example `.cut`/`.cbl` pairs:
  output byte-identical before and after.
* Not verified: running a spliced Report Writer program under GnuCOBOL
  (no Docker daemon in the authoring environment). The splice is the same
  whole-statement replacement every other category uses.
