---
type: Module
title: Analysis
description: mock_surface.py finds every mockable boundary statement in a COBOL program; the refusal/ package decides, per test case, what must be refused fail-closed; stub_expectations.py backs run --record-expectations.
tags: [analysis, reachability, refusal, fail-closed]
timestamp: 2026-10-16T20:00:00Z
---

# Overview

Cooperating modules under `mockymock/analysis/`:

| Module | Job |
|--------|-----|
| `mock_surface.py` | Walk `PROCEDURE DIVISION`, classify every statement that touches an external resource into a `BoundarySite`/`CallSite`. Whole-program, category-generic, no knowledge of any test case. Also `analyze_file_status_fields(program)`: a separate ENVIRONMENT DIVISION walk (FILE-CONTROL SELECT entries) that maps each uppercased file name to its declared `FILE STATUS IS <field>` -- qualified as written (`FS-CODE OF CUST-STAT`, from `SelectStatement.file_status_qualifiers`, issue #266: the bare name was ambiguous when one copybook's status group is declared per file) -- feeding both `refusal.check_test_case`'s `UNRESOLVED_FILE_STATUS_TARGET` check and `splicer.injector.build_site_dispatch`'s default-success MOVE (see [dsl](dsl.md)'s `FILE-STATUS IS` section and [splicer](splicer.md)). |
| `refusal/` | Package re-exporting whole-program checks (parse errors, unresolved COPY, nested EXEC, CICS EIB/CICS macro layout) + per-`MockTestCase` checks (reachability via BFS, directive-to-site matching, fail-closed refusals). |
| `linkage.py` | `linkage_plan(program)`: detects a program's unbound LINKAGE SECTION shape (any non-empty LINKAGE SECTION, `ENTRY` statements optional) for `splicer.linkage.neutralize`. See [splicer](splicer.md)'s "ENTRY/LINKAGE Neutralization" section. |
| `cics_eib.py` | `cics_eib_plan(program, lines)`: detects a program referencing CICS EIB fields (`EIBCALEN`, `EIBAID`, ...)/`DFHEIBLK` without declaring them, for `splicer.cics_eib`'s synthesis. See [splicer](splicer.md)'s "CICS EIB Field Synthesis" section and docs/2026-08-27-cics-eib-linkage-support-design.md. |
| `flow_mocks.py` | Flow-target mocks (`MOCK PARAGRAPH`/`MOCK SECTION`): resolves keys to paragraphs/sections, refuses every entry path the header-dispatch splice can't handle soundly (UNRESOLVED_FLOW_MOCK_TARGET / UNSUPPORTED_FLOW_MOCK_TARGET), and emits `FlowMockPlan`s the splicer consumes — the plan-or-refusal shape `find_terminator_plans` established. `resolved_flow_targets` feeds `check_test_case`/`find_terminator_plans` the per-case `skip_traversal` sets. A `MOCK SECTION` whose paragraphs the program names qualified by the section (`PERFORM P2 OF CALC` / `IN CALC`, found by `_qualified_reference_problem` in the PROCEDURE DIVISION text) is refused UNSUPPORTED_FLOW_MOCK_TARGET: the splice moves those paragraphs under the relocated `UT-REAL-n-` section, and the qualified reference stopped compiling after a clean lint (#293; refusing rather than rewriting the references). A target inside a THRU range is refused whatever names the range: a program `PERFORM A THRU B`, a case's driver range, or a SORT/MERGE INPUT/OUTPUT PROCEDURE / XML PARSE PROCESSING PROCEDURE `A THRU B` (issue #261 -- before it, those implicit-PERFORM ranges were not collected, so the mock body and the relocated real body both ran); those procedure names also count as flow targets. See docs/2026-07-20-paragraph-section-mocks-design.md. |
| `stub_expectations.py` | Backs `mockymock run --record-expectations` only — orthogonal to the refusal-gate pipeline above, not part of it. Raw-text-scans the `.cut` file (not the parsed AST/suite) for `*> STUB EXPECT <name> [-- <note>]` comments and attributes each to its owning TESTCASE's runtime case id. See below and [splicer](splicer.md)/[report](report.md) for the rest of the mechanism, and docs/2026-08-04-record-expectations-design.md for the full design. |

```
CobolProgram
   |
   v
mock_surface.analyze()  --------------> MockSurface
   walks PROCEDURE DIVISION              - call_sites: list[CallSite]      (v1 shape, kept)
   recurses into nested bodies           - boundary_sites: list[BoundarySite]
   (IF/EVALUATE/inline PERFORM/          - file_io_paragraphs / exec_paragraphs /
    IO clause bodies)                      console_accept_paragraphs (v1 sets, kept)
   |
   v
refusal.check_whole_program()      -> PARSE_ERROR / PARSE_WARNING /
                                       UNSUPPORTED_NESTED_PROGRAM /
                                       UNSUPPORTED_DECLARATIVES / UNSUPPORTED_ALTER
refusal.check_expansion_warnings() -> EXPANSION_WARNING      (lossy copybook decode only)
refusal.check_unresolved_copybooks() -> UNRESOLVED_COPYBOOK  (textual, re-lexes raw source)
refusal.check_nested_exec()        -> NESTED_EXEC / UNSPLICEABLE_EXEC (program-wide, ignores reachability)
refusal.check_linkage_layout()     -> UNSUPPORTED_LINKAGE_LAYOUT (guards splicer.linkage.neutralize)
                                       UNSUPPORTED_LINKAGE_ADDRESSING (guards
                                       splicer.linkage.redirect_address_of)
refusal.check_cics_eib_layout()    -> UNSUPPORTED_CICS_MACRO / UNSUPPORTED_CICS_DFHCOMMAREA
                                       (guards splicer.cics_eib synthesis; see below.
                                        run/lint/export/debug use the _scoped variant,
                                        which holds a paragraph-local DFHRESP/DFHVALUE
                                        call back for the reachability-union gate)
   |
   v
per MockTestCase:
refusal.check_test_case(surface, program, case, file_status_fields)
   (file_status_fields comes from mock_surface.analyze_file_status_fields
    (program) -- computed once per program by the caller, not per case --
    and maps each uppercased file name to its declared FILE STATUS IS
    <field>, read from the ENVIRONMENT DIVISION's FILE-CONTROL SELECT
    entries; a file with no FILE STATUS clause has no entry)
   1. _reachable_paragraphs(program, case.perform_target, case.perform_thru,
      skip_traversal=<this case's resolved MOCK PARAGRAPH/SECTION names>,
      neutralized_goto=<neutralized_goto_targets(program, scope_map, lines)>)
      (BFS over PERFORM + GO TO edges, THRU expansion, section fall-through,
      closed over GO TO fall-through -- see the Gotcha below;
      a flow-mocked name is recorded as reached but never traversed into --
      its body is replaced by the mock dispatch for this case, so the
      boundaries/terminators inside it need no mocks on this case's account;
      a GO TO fully covered by a GotoExitPlan is not an edge and its
      exit-label target is dropped from the fall-through closure's seeds --
      see "GO-TO-exit reachability narrowing" below)
   2. surface.sites_in(reachable - mocked_flow_names) -> match against
      case.mocks via directive_matches_site; a flow directive matches when
      the BFS reached its key, refuses UNSUPPORTED_FLOW_MOCK_TARGET when it
      names the case's own PERFORM entry point
   3. emit UNMOCKED_*/AMBIGUOUS_MOCK/UNSUPPORTED_NESTED_MOCK_TARGET/
      UNSUPPORTED_MOCK_TARGET_LAYOUT/UNMATCHED_MOCK/VERIFY_WITHOUT_MOCK/UNMOCKED_CANCEL
   4. final pass over case.mocks, two UNRESOLVED_FILE_STATUS_TARGET
      triggers sharing one `missing_status_field = directive.key.upper()
      not in file_status_fields` root-cause check, the second an `elif`
      of the first since 2026-08-10 (audit finding F27 -- previously two
      independent `if`s, so a directive using BOTH FILE-STATUS IS sugar
      AND a `MOCK READ ... ROWS` with no TERMINAL on a file missing from
      file_status_fields fired the same code twice): (a) any directive
      with FILE-STATUS IS sugar (`directive.file_status is not None`) and
      `missing_status_field` (no WORKING-STORAGE field exists to move the
      status into -- fail closed rather than silently drop the
      directive's status); (b) *elif* a `MOCK READ ... ROWS` directive
      (`directive.rows is not None`) with no `TERMINAL` group
      (`directive.terminal_row is None`) and `missing_status_field` --
      the rows-exhausted branch would have no way to signal end-of-data
      at all, so the read loop this mocks can never terminate; add a
      TERMINAL group or a FILE STATUS field before this refuses
whole-suite (plan-or-refusal, like find_terminator_plans):
flow_mocks.find_flow_mock_plans(program, suite, lines)
   -> FlowMockPlan per safe MOCK PARAGRAPH/SECTION key, or
      UNRESOLVED_FLOW_MOCK_TARGET / UNSUPPORTED_FLOW_MOCK_TARGET
```

**2026-07-07 reachability-hole remediation (audit findings 1.1-1.7, 2.1-2.2):**
the BFS previously traversed only `PerformStatement` edges and its name
table held paragraphs only, so three idiomatic constructs made a boundary
statement reachable-in-fact but invisible to the gate: `GO TO`, `PERFORM
<section-name>`, and `SEARCH ... WHEN` bodies. All three are now modeled
(see below); `DECLARATIVES` and `ALTER` are structurally unmodelable by
any static edge-following BFS and are refused outright instead. The
splicer's top-level "owns its line" guard (`UNSUPPORTED_MOCK_TARGET_LAYOUT`
/ `UNSPLICEABLE_EXEC`) and `collect_boundaries`'s SECTION-header omission
are splicer-side companions to this remediation — see
[splicer](splicer.md).

**Name case (2026-10-11).** cobolparser upper-cases paragraph and section names but keeps a `PERFORM`/`GO TO` target as written, so a lowercase program (`perform read-one`) had every edge refused `UNRESOLVED_FLOW_TARGET`. Every parse site (`run_static_checks`, `generate`, `fixtures`, `_collect_boundaries`, `report`) calls `analysis/flow_targets.normalize_flow_targets(ast)` right after `parse_cobol`, which upper-cases `target_paragraph`, `thru_paragraph` and `target_paragraphs` in place; every name lookup downstream stays an exact comparison. A new parse site must call it too.

Both modules depend only on the small set of cobolparser attributes pinned in [integration](integration.md) — not on cobolparser's own `ProgramFlowAnalyzer` or `DynamicCallAnalyzer` for the reachability/classification paths, specifically so this module's correctness stays checkable against attributes mockymock has independently verified (see Gotchas).

# mock_surface.py — What Counts as a Boundary

`analyze(program)` returns a `MockSurface`. It fetches `PROCEDURE DIVISION`, gathers every paragraph via `_all_paragraphs` (top-level + every section's paragraphs — mirrors `CoverageAnalyzer._analyze_paragraphs`), and calls `_walk_statements` per paragraph.

## Categories classified (`_classify_statement`)

| Statement type | `MockCategory` | Keys captured | Notes |
|---|---|---|---|
| `CallStatement`, static | `CALL` | called program literal | `is_mq` flag set if name in `MQ_API_NAMES` (MQCONN, MQGET, MQPUT, …) |
| `CallStatement`, dynamic, identifier captured | `DYNCALL` | uppercased identifier name | `called_program` holds the *identifier*, not a resolved target — splicer never needs to resolve it |
| `CallStatement`, dynamic, identifier empty | `None` (detected, unmockable) | — | label `"dynamic CALL"`; fail-closed — gates `DYNAMIC_CALL` refusal |
| `IOOpenStatement` / `IOCloseStatement` | `OPEN` / `CLOSE` | every name in `.file_names` | multi-file OPEN/CLOSE both keyed |
| `IOReadStatement` / `IODeleteStatement` / `IOStartStatement` / `IOUnlockStatement` | `READ`/`DELETE`/`START`/`UNLOCK` | `.file_name` | one file each |
| `IOWriteStatement` / `IORewriteStatement` | `WRITE`/`REWRITE` | `.record_name`, first word | keyed by **record**, not FD — matches COBOL's own syntax. A record qualified by its file (`WRITE PRINT-REC IN PRINT-FILE`, NIST SQ207M) keys on `PRINT-REC`: the whole phrase made generate write a `MOCK` the .cut grammar cannot parse (2026-11-02) |
| `SortStatement`/`MergeStatement`, plain file form (`input_procedure is None and output_procedure is None` — `USING ... GIVING ...`, no procedure clause; `MergeStatement` has no `input_procedure` attribute at all, so `_is_plain_sort_merge` reads it via `getattr(..., None)`) | `MockCategory.SORT`/`MockCategory.MERGE` | `.file_name` (the SD, uppercased) | label `"SORT"`/`"MERGE"`; bare-word key (`FILE_OP_CATEGORIES` membership), same shape as READ/DELETE/START/UNLOCK — not in `FILE_STATUS_CATEGORIES` (no FILE STATUS clause on an SD) |
| `SortStatement`, pure procedure form (`_is_pure_procedure_sort`: `input_procedure is not None and output_procedure is not None and not using_files and not giving_files` — SORT only, MERGE has no `input_procedure` clause) | **not recorded as a `BoundarySite` at all** | — | touches no physical file; left real/unspliced like `DISPLAY`. `refusal.py`'s `_reachable_paragraphs` models the implicit PERFORM its `input_procedure`/`output_procedure` names represent (with `input_procedure_thru`/`output_procedure_thru` range-expanded via `_expand_thru_range`, same as `PERFORM ... THRU`) so RELEASE/RETURN inside those paragraphs are reachable |
| `ReleaseStatement` | `MockCategory.RELEASE` | `.record_name` (uppercased) | label `"RELEASE"`; WRITE-shaped — keyed by record, not the SD file name. Only ever appears inside a SORT's INPUT PROCEDURE, but mockability no longer depends on the enclosing SORT/MERGE's shape (see mixed-form row below) |
| `ReturnStatement` | `MockCategory.RETURN` | `.file_name` (the SD, uppercased) | label `"RETURN"`; READ-shaped — its `.at_end_clause`/`.not_at_end_clause` are already covered by `_NESTED_STATEMENT_ATTRS`. `ROWS`/`TERMINAL` sugar reused from READ (`_MOCK_BARE_RE`'s rows group, `build_rows_block`), but RETURN is **not** in `FILE_STATUS_CATEGORIES` (no implicit default-success/end-of-file MOVE), so a `MOCK RETURN ... ROWS` always needs its own `TERMINAL ( ... )` group — see `refusal.py`'s `UNRESOLVED_FILE_STATUS_TARGET` check, widened from READ-only to `(READ, RETURN)` |
| `SortStatement`/`MergeStatement`, mixed form (a `USING`/`GIVING` file paired with a procedure clause on the *other* side — e.g. `USING ... OUTPUT PROCEDURE ...`) | `None` (detected, unmockable) | — | label `"SORT/MERGE"`; gates `UNSUPPORTED_SORT_MERGE` — touches a physical file mockymock cannot seed/read AND runs a procedure whose other logic a whole-statement mock would silently skip, so neither of the other two strategies is safe |
| `CancelStatement` | `None` (detected, never spliced) | `.program_names` (all names on the statement) | label `"CANCEL"`; not "unmockable" like SORT/MERGE — `refusal.py` treats it as covered when every name is also mocked via `MOCK CALL`/dynamic-CALL identifier in the same test case (a mocked CALL never loads a real module, so CANCEL of that program is a guaranteed no-op), else `UNMOCKED_CANCEL` (audit finding 1.6) |
| `StopStatement` (stop_type == "RUN") / `GobackStatement` / `ExitStatement` (exit_type == "PROGRAM") | `None` (detected, neutralized when found on a safe plain-PERFORM chain) | — | label `"STOP RUN"`/`"GOBACK"`/`"EXIT PROGRAM"` (`_TERMINATOR_LABELS`; EXIT PROGRAM since issue #212 -- the driver makes the program under test the run unit's main program, where EXIT PROGRAM is a no-op, while in the called subprogram it is written for it returns to the caller, so left alone it silently fell through); see [splicer](splicer.md) and [docs/2026-07-08-goback-stop-run-support-design.md](../docs/2026-07-08-goback-stop-run-support-design.md) -- unlike CANCEL/SORT-MERGE this category IS spliced, via a dedicated path (`refusal.find_terminator_plans` / `injector.build_terminator_neutralization`/`build_chain_check`), not `directive_matches_site` |
| `ExecSQLStatement` (incl. subclasses: DeclareCursor, Fetch, DynamicSQL, …) | `SQL` | `match_text` = normalized `sql_text` | detected via `isinstance`, not `node_type` (base `CobolStatement.node_type` is hardcoded `"Statement"`) |
| `ExecCicsStatement` | `CICS` | `match_text` = normalized `f"{cics_command} {cics_text}"` | RETURN/XCTL/ABEND (`CICS_TERMINATOR_COMMANDS`) are also terminators (`is_terminator_site`, issue #215): the mock body runs, then the run under test ends -- see [splicer](splicer.md) |
| `ExecImsStatement` | `DLI` | `match_text` = normalized `f"{ims_command} {ims_text}"` | covers both `EXEC IMS` and `EXEC DLI` syntax; no separate DLI node type |
| `IOAcceptStatement`, source not in `_NON_INTERACTIVE_ACCEPT_SOURCES` | `ACCEPT` | `accept_key(.target)`: the target's data-name alone, cut at a subscript/refmod `(` and before `OF`/`IN` (`WS-ENT ( WS-I )` -> `WS-ENT`, `FLD OF REC-B` -> `FLD`), like a dynamic CALL's identifier; the whole text stays on `site.accept_target` for the scaffold's `MOVE SPACES TO <target>` body (#311 -- the full-text key could not be written as `MOCK ACCEPT`, so lint's suggestion, `--fill` and `generate` wrote unparsable lines; `generate` maps the bundle's full-text ACCEPT keys the same way, `_with_accept_keys`) | fail-closed: no FROM, `FROM CONSOLE`, or unrecognized mnemonic all count as console input |
| `IOAcceptStatement`, source in `_NON_INTERACTIVE_ACCEPT_SOURCES` | not recorded at all | — | DATE/DAY/DAY-OF-WEEK/TIME/COMMAND-LINE/ENVIRONMENT/ENVIRONMENT-VALUE/ARGUMENT-NUMBER/ARGUMENT-VALUE never touch stdin |
| `InitiateStatement` / `TerminateStatement` (Report Writer, cobol-parser ≥ the 2026-09-02 verb-coverage release) | `INITIATE` / `TERMINATE` | every name in `.report_names`, uppercased | one site, one key per report -- like a multi-file OPEN/CLOSE. Splicing the statement out is the whole mock: the RD/FD stay declared, the report file is never touched (cobol-parser parses the REPORT SECTION warning-free since the same release; before it, the "REPORT SECTION not supported" warning refused the whole program as PARSE_WARNING) |
| `GenerateStatement` | `GENERATE` | `.report_name` (the report or detail-group name), uppercased | label `"GENERATE"`; same splice-only mock. `REPORT_WRITER_CATEGORIES` in `dsl/model.py` -- bare-word keys, no ROWS/TERMINAL/FILE-STATUS sugar (an RD has no status field) |
| `StopStatement`, `stop_type != "RUN"` (`STOP "literal"`, `STOP ZERO`, ...) | `None` (detected, unmockable) | the operand text | label `"STOP literal"`: displays the operand and waits for the operator on the console -- a console read, gated like an unmocked ACCEPT (`UNSUPPORTED_STOP_LITERAL`) |
| `InvokeStatement` | `None` (detected, unmockable) | object name, method name | label `"INVOKE"` -- `UNSUPPORTED_INVOKE` |
| `ChainStatement` (Micro Focus) | `None` (detected, unmockable) | program literal/identifier | label `"CHAIN"` -- `UNSUPPORTED_CHAIN` |
| `SendStatement` / `ReceiveStatement` / `EnableStatement` / `DisableStatement` / `PurgeStatement` (Communication Module) | `None` (detected, unmockable) | `.cd_name`, uppercased | label `"communication"` -- `UNSUPPORTED_COMMUNICATION`. RECEIVE's `no_data_clause`/`with_data_clause` bodies are walked (added to `_NESTED_STATEMENT_ATTRS`) and marked `nested_in_boundary` |
| `XmlJsonStatement` | not recorded (acts on WORKING-STORAGE only) | — | an XML PARSE's `PROCESSING PROCEDURE` is a flow edge `_reachable_paragraphs` models (see below); its `on_exception`/`not_on_exception` bodies are walked via the CALL-shaped attribute names already in `_NESTED_STATEMENT_ATTRS`. Fail closed on a cobol-parser that keeps either as text only (`clause_text` mentions EXCEPTION without an `on_exception` attribute, or PROCESSING PROCEDURE without `processing_procedure`): recorded as an `"unsupported statement"` site |
| **any other statement class** not in `_PASSTHROUGH_STATEMENT_NAMES` | `None` (detected, unmockable) | the statement's `statement_type` | label `UNSUPPORTED_STATEMENT_LABEL` (`"unsupported statement"`) -- the fail-closed catch-all, `UNSUPPORTED_STATEMENT`. See "Fail-closed over statement types" below |

`normalize_exec_text` uppercases and collapses whitespace — the form all SQL/CICS/DLI keys prefix-match against.

`DISPLAY` is not classified at all — passthrough forever, not a boundary.

## Fail-closed over statement types (2026-09-02)

cobol-parser's 2026-09-02 statement-coverage work gave every COBOL verb its
own AST node (INITIATE/TERMINATE/SUPPRESS, SEND/RECEIVE/ENABLE/DISABLE/
PURGE, EXHIBIT/EXAMINE/TRANSFORM, ENTER, NOTE, CHAIN, READY/RESET TRACE,
SERVICE, TITLE, RAISE/RESUME/VALIDATE; INVOKE had one already). Before it,
those verbs were warned-and-discarded and `check_whole_program`'s
PARSE_WARNING refused the program; after it they parse cleanly, so a verb
`mock_surface` did not classify would have walked straight past the gate
-- an external dependency (INVOKE, CHAIN, a message queue) silently left
real. Confirmed against the sibling checkout before fixing: the 16 unit
failures mocky-mock had against that cobol-parser were all fixtures that
relied on EXHIBIT/TRANSFORM warning (now `RECOVER`, one of the three
verb-shaped words still in `UNSUPPORTED_VERBS`) or on the standalone
`END-ADD.` phantom paragraph the same release fixed (tests now accept
either outcome; the guard stays for the released cobol-parser the CI
compat lane installs).

The classification is therefore closed over statement TYPE, not just over
the boundary verbs it knows: `_PASSTHROUGH_STATEMENT_NAMES` is the
by-name allowlist of classes verified to touch nothing outside the program
(MOVE/IF/EVALUATE/PERFORM/GO TO/arithmetic/STRING/INSPECT/SET/DISPLAY/
EXIT/CONTINUE/COMMIT/ROLLBACK/ALLOCATE/FREE, the compiler-directing and
legacy no-op verbs, XML/JSON, ALTER and USE which are refused elsewhere,
...). `_classify_statement` records anything outside it that no boundary
branch claimed as a `category=None`, `label="unsupported statement"` site
whose `keys[0]` is the verb; `check_test_case` refuses it as
`UNSUPPORTED_STATEMENT` when reachable (never when unreachable or inside a
flow-mocked paragraph -- no over-refusal). Swept 2026-09-02 across every
COBOL file in both repos (582 programs, the NIST suite included): the only
classes outside the allowlist and the boundary branches were the
Communication Module, Report Writer and STOP-literal ones, each of which
got its own branch; `tests/unit/test_verb_coverage_fail_closed.py`'s corpus
test pins that no `examples/**/*.cbl` yields a catch-all site, and
`test_every_passthrough_name_is_a_real_cobolparser_statement_class` pins
that the allowlist has no typos. The new node classes are imported through
`_optional_statement_types` (importlib, empty tuple when absent) so the
module still imports on the released cobol-parser the CI compat lane
installs -- where those verbs still warn, so PARSE_WARNING covers them.

The label -> refusal-code table for detected-unmockable sites lives in
`refusal/_types.py`'s `_UNSUPPORTED_SITE_CODES` (INVOKE ->
`UNSUPPORTED_INVOKE`, CHAIN -> `UNSUPPORTED_CHAIN`, communication ->
`UNSUPPORTED_COMMUNICATION`, STOP literal -> `UNSUPPORTED_STOP_LITERAL`,
unsupported statement -> `UNSUPPORTED_STATEMENT`), each with the
explanation its message carries; `check_test_case` dispatches on it after
the CANCEL / dynamic-CALL / terminator branches, and asserts the only
remaining `category=None` label is `"SORT/MERGE"`.

## Walking nested bodies

`_nested_statement_lists(statement)` returns every nested `list[CobolStatement]` hanging off one statement, by `getattr`-ing a fixed attribute tuple (`_NESTED_STATEMENT_ATTRS`): `then_statements`, `else_statements`, `inline_statements` (inline `PERFORM…END-PERFORM`), `at_end_clause`/`not_at_end_clause`, `invalid_key_clause`/`not_invalid_key_clause`, `at_eop_clause`/`not_at_eop_clause`, `on_exception`/`not_on_exception`, `on_overflow`/`not_on_overflow`, `on_size_error`/`not_on_size_error`. `EvaluateStatement` is special-cased outside that tuple: every `when_clauses[].statements` and `default_when.statements` is appended too. `SearchStatement` is likewise special-cased (2026-07-07 fix, audit finding 1.3): `SearchStatement.when_clauses` is a `list[dict]` with a `"statements"` key — a different shape from `EvaluateStatement`'s `WhenClause` AST nodes — so it needs its own branch; `at_end_clause` is already covered by the attribute tuple. Before this fix a `CALL`/file-op/EXEC/`ACCEPT` statement inside `SEARCH ... WHEN` produced **zero** boundary sites — invisible to both `mock_surface` and `refusal.py`'s reachability BFS (which reuses this same function via `_find_flow_statements`/`_find_statements_of_type`).

`on_size_error`/`not_on_size_error` (2026-08-10 audit Finding 1, fixed same day) were the same class of gap: absent from the tuple, a `CALL`/file-op/EXEC/`ACCEPT`/`PERFORM` nested inside `ADD`/`SUBTRACT`/`MULTIPLY`/`DIVIDE`/`COMPUTE`'s `ON SIZE ERROR` clause was invisible to `mock_surface` *and* to the reachability BFS — an unmocked boundary there produced a silent `PASS`, not a refusal, the exact failure class the fail-closed gate exists to prevent. Confirmed both the direct-detection gap and the BFS blind spot (a paragraph reachable only via `PERFORM` inside `ON SIZE ERROR`) with a controlled contrast against the identical construct nested in `IF`, at the pinned cobolparser commit, then end-to-end against real GnuCOBOL. Fix was the two attribute names; regression tests in `tests/unit/test_mock_surface.py` (detection) and `tests/unit/test_refusal.py` (refusal-gate: unmocked refuses `UNMOCKED_CALL`, mocked correctly falls back to `UNSUPPORTED_NESTED_MOCK_TARGET` like any other unsplicable nested clause body). See `docs/2026-08-10-framework-audit-and-roadmap.md` for the full repro.

The 2026-08-12 audit (Finding 3) swept the same class again against cobolparser's own `_CLAUSE_BODY_ATTRS` enumeration at the pinned commit and found two more missing halves, both fixed same day: `not_at_eop_clause` (`WRITE ... NOT AT END-OF-PAGE`) and `not_on_overflow` (`STRING`/`UNSTRING ... NOT ON OVERFLOW` — their positive `ON OVERFLOW` bodies share `CallStatement`'s `on_overflow` name, which was already covered). Both confirmed hiding a nested `CALL` from `static_call_sites()` before the fix; parametrized regression tests cover both halves of each clause across `WRITE`/`STRING`/`UNSTRING` in `tests/unit/test_mock_surface.py`.

The same audit's Finding 2 fixed a THRU-seed hole in `_reachable_paragraphs`: the driver-side `PERFORM <start> THRU <thru>` expansion was guarded by `start in by_name` (paragraphs only), so a **section-named** start silently skipped both the range expansion and its fail-closed refusal — `thru` was dropped while the compiled driver still executes the full fall-through range. Now any driver-side THRU whose either endpoint names a section refuses `UNSUPPORTED_PERFORM_THRU` with a section-specific message; a section target *without* THRU stays supported (BFS member expansion, unchanged).

**Separate, still-open gap in the same neighborhood:** `refusal.py`'s `_check_unsupported_control_flow` (whole-program, AST-based, alongside `UNSUPPORTED_DECLARATIVES`/`UNSUPPORTED_ALTER`) now also refuses `UNSUPPORTED_PHANTOM_PARAGRAPH` when a paragraph is named exactly `END-ADD`/`END-SUBTRACT`/`END-MULTIPLY`/`END-DIVIDE`/`END-COMPUTE` — the pinned cobolparser fails to consume these as their arithmetic statement's own scope terminator when written alone on its own line, instead parsing them as paragraph names and silently reparenting every following statement (same bug class as the fixed `ROUNDED`-after-`GIVING` phantom paragraph). This is a defense-in-depth guard in mockymock, not a fix to the root cause — the real fix belongs upstream in cobol-parser. The guard matches the five exact reserved names, not a `^END-[A-Z]+$` pattern, since that would also refuse legitimate paragraph names like `END-OF-JOB`/`END-RUN` (verified against the full example/test corpus with zero collisions before shipping the exact-name form).

`_walk_statements` recurses depth-first over these lists:
- **`nested` flag**: every recursive call passes `nested=True` literally, not the parent's value — so a site is `nested=True` at *every* depth ≥ 1, while only true top-level statements stay `nested=False`.
- **`in_boundary` flag is sticky**: `child_in_boundary = in_boundary or isinstance(statement, _BOUNDARY_STATEMENT_TYPES)`. Once recursion enters a boundary statement's own clause body (e.g. inside a CALL's `ON EXCEPTION`, or a READ's `AT END`), every site found below is `nested_in_boundary=True` forever, regardless of further nesting shape — because splicing the *enclosing* boundary statement removes that whole clause body wholesale, so a site inside it can never be spliced independently no matter what directive matches it. (Since 2026-10-29 the flag no longer means unspliceable on its own: `source_map.annotate_nested_sites` still gives a CALL / file-op / RELEASE / RETURN / ACCEPT site a span when every enclosing boundary is a READ / RETURN / WRITE / REWRITE / DELETE / START / CALL, whose clause bodies the splice lifts and re-runs -- see [splicer](splicer.md#boundaries-inside-clause-bodies-2026-10-29).)

`_BOUNDARY_STATEMENT_TYPES` = `CallStatement` + all 8 file-op types + the 4 SORT/MERGE types (`SortStatement`/`MergeStatement`/`ReleaseStatement`/`ReturnStatement` — regardless of whether a given SORT/MERGE site turns out mockable or not) + `ExecSQLStatement`/`ExecCicsStatement`/`ExecImsStatement` + `IOAcceptStatement`.

Paragraph attribution is depth-independent: nested statements stay attributed to the *enclosing paragraph name*, since that's the granularity the refusal gate's reachability check cares about.

## `clause_bodies.py` — a mocked statement's own clause bodies (issue #209)

`clause_bodies_liftable(statement)` (AST only) and
`lift_clause_bodies(statement, lines)` (positional slice of the normalized
source) decide whether the splicer re-runs a mocked READ / RETURN / WRITE /
REWRITE / DELETE / START / CALL's clause bodies after the mock, guarded by
the mocked outcome in `UT-MOCK-STATUS`. Fail closed: a mocked site whose
bodies they cannot lift exactly is refused, `UNLIFTABLE_CLAUSE_BODY`
(`clause_lift_problem` + `refusal.check_clause_bodies`, issue #319; before,
the bodies were silently deleted with the statement). Reachability needed
no change: the BFS already followed PERFORMs and GO TOs inside boundary
clause bodies (the `in_boundary` skip applies only to terminator chain
edges and GO TO exit plans; a body holding a terminator is never lifted,
and a lifted GO TO keeps its target, so declining its exit plan is the
safe direction). See
[splicer](splicer.md#clause-bodies-re-run-after-the-mock-issue-209-2026-10-16).
`scan_words` (words outside quoted literals, plus sentence periods) moved
here from `dsl.generator`, which still uses it for its own AT END lift. It
skips an inline `*>` comment (outside a literal) to the end of its line
(#327): before, a period in the comment read as the sentence end and an
apostrophe opened a literal, so the body was refused or cut short.

## `BoundarySite` fields relevant to refusal

`category` (None for detected-but-unmockable), `label` (message string), `keys` (candidate match tuple), `match_text` (normalized EXEC text), `nested`, `nested_in_boundary`, and two fields **not set by mock_surface.py** — filled in later by the splicer's `source_map.annotate_nested_sites`: `span: tuple[int,int] | None` (validated replacement span, nested sites only) and `unspliceable_reason: str | None`. Since the 2026-07-07 fix, `annotate_nested_sites` stamps `unspliceable_reason` on **top-level** sites too (leaving their `span` at `None` — top-level replacement spans still come from `source_map.statement_span`, not this field) when the statement does not own its source line(s); see [splicer](splicer.md#top-level-own-line-guard).

# refusal/ — What Gets Refused, and Why

Split into a package on 2026-08-30: `_types.py` (codes and `Refusal`,
plus `suggested_fix`), `_gates.py` (the whole-program and per-case
checks), `_reachability.py` (the BFS and its fall-through closures),
`_plans.py` (terminator / GO-TO-exit plan derivation), and
`_explanations.py` (the prose behind `mockymock explain`), all re-exported
from `refusal/__init__.py`. **This file still writes `refusal.py` in
running prose** for the module as a whole — read it as "the refusal
package"; the import path callers use (`from mockymock.analysis.refusal
import ...`) never changed.

**Every code below has a prose explanation in `_explanations.py`'s
`REFUSAL_EXPLANATIONS`** (2026-09-15), backing `mockymock explain <CODE>`
and, transitively, `mocky-mock-vscode`'s planned refusal-code hover.
`tests/unit/test_refusal_explanations.py` cross-checks the dict against a
regex scan of the whole package in both directions, so a code added to a
gate here without a matching explanation entry fails CI. See
docs/2026-09-15-cut-editor-intelligence-design.md and `.okf/cli.md`'s
`mockymock explain` section.

## Whole-program checks (independent of any test case)

| Check | Code | Trigger |
|---|---|---|
| `check_source_format` | `UNSUPPORTED_SOURCE_FORMAT` | the program's own source (before copybook expansion) is free-format by cobol-parser's `detect_fixed_format` -- the same decision `parse_cobol` parses with. Checked right after a successful parse (so unparseable text still reports `PARSE_ERROR`), in `run_static_checks` (run/lint/debug/export/mutate/report) and `generate`: every text the splicer edits and cobc compiles goes through `normalize_fixed_format`, which keeps only columns 8-72, so a free-format program parsed correctly but was spliced and compiled as column-chopped garbage (issue #210, 2026-10-16). `cobol.yml` `source_format` is not read |
| `check_whole_program` | `PARSE_ERROR` | `parse_result.success is False` |
| `check_whole_program` | `PARSE_WARNING` | each `ParseResult.warnings` entry — since cobolparser's 2026-07-07 silent-drop remediation, a warning on a "clean" parse (`success=True, errors=0`) is the only signal that content was dropped from the AST: unsupported verbs (EXHIBIT, TRANSFORM, ...), unparsed clause leftovers, multi-program compilation units (`ast.contained_programs` — the splicer/BFS only see the first program). `INVOKE` moved off this list: cobolparser now parses it into its own `InvokeStatement` AST node (no longer a dropped/warned statement) as of the commit `tests/integration`'s pin points at — `tests/unit/test_scoped_refusals.py`'s `UNREACHED_INVOKE_CBL` fixture was updated 2026-08-10 (audit finding F-0b) to a still-genuinely-unsupported verb once INVOKE stopped producing the warning the test needed. An incomplete AST would splice into a program that silently skips real behavior, so every warning refuses fail-closed. **Narrowed for `run`/`lint`/`export`/`debug`** (via `check_whole_program_scoped`, used by `run_static_checks`): a warning whose text carries a line number (`_WARNING_LINE_RE`) that `_paragraph_owning_line` proves strictly inside one PROCEDURE DIVISION paragraph's own body is held back as a `ParagraphScopedRefusal` and refused only when `union_executed_paragraphs` (union of every SELECTED case's reachability BFS, closed over the GO TO fall-through hazard; `None` = trust nothing) says that paragraph could execute; otherwise waived with a printed note. Anything unlocatable/unclassifiable — no line, on a header line, before the first paragraph, multi-program unit, phantom-`.` attribution — stays whole-program. A warning's line only proves where a drop *starts*, not its full extent, and mockymock cannot see cobolparser's error-recovery internals to rule out recovery having skipped past a real paragraph header while resynchronizing (silently merging that paragraph into the one being attributed and erasing it from the AST's own paragraph list) — so `_paragraph_owning_line` additionally requires `_has_unaccounted_label` to find nothing shaped like an unrecognized paragraph/SECTION header (a bare identifier, optionally `... SECTION`, alone on its own line) anywhere inside the candidate owner's body; any match vetoes classification (fail closed — an accepted false positive on a bare scope terminator like `END-IF.`/`EXIT.` costs a classification, never an unsound one). `generate`/`fixtures` keep the unscoped entry point (no cases to scope by). **Not refused:** cobol-parser's "REPLACE statement set was still active at end of source" warning (issue #272) -- a REPLACE in force to the end of the unit is standard COBOL, applied through EOF exactly as cobc does, so nothing was dropped; the "REPLACE statement could not be parsed and was ignored" warning still refuses |
| `check_whole_program` (via `_check_unsupported_control_flow`) | `UNSUPPORTED_DECLARATIVES` | program contains a DECLARATIVES block — detected (2026-09-15) from cobol-parser's modelled flag first: every section between `DECLARATIVES.` and `END DECLARATIVES.` carries `CobolSection.is_declarative` (metadata `declarative`), and the two marker lines no longer leave a paragraph behind. The older signals stay as fallbacks for an older pin: a paragraph literally named `DECLARATIVES` (the artifact pre-2026-09-15 parsers emitted) and any `UseStatement` (legal nowhere else). Since 2026-11-03 a flagged block refuses only for a USE form that cannot run under mocks (`declaratives.unsupported_use`: USE BEFORE REPORTING, a USE AFTER naming no file/mode or a file of no SELECT); USE AFTER EXCEPTION/ERROR procedures run after a mocked file statement's exception outcome and the BFS follows each file statement to its USE section(s) (see "DECLARATIVES under mocks" below). The two fallback signals (older pin) still refuse unconditionally |
| `check_whole_program` | `UNSUPPORTED_NESTED_PROGRAM` | the parse carries cobol-parser's "Compilation unit contains N program units" warning: nested or stacked `PROGRAM-ID`s, or an object-oriented `CLASS-ID` with its FACTORY/OBJECT/METHOD-ID units. The AST is *complete* (every unit is in `contained_programs`); what is missing is mockymock's support — the splicer and the reachability BFS only see the outermost unit, so a contained unit's boundaries would go unmocked. Refused under its own code (2026-09-15) instead of as a `PARSE_WARNING`, whose "AST is missing content" message was wrong for this case. `tests/unit/test_enterprise_corpus.py` pins the outcome of every program type in `tests/fixtures/enterprise/` (mirrors cobol-parser's `tests/samples/enterprise/`) |
| `check_whole_program` (via `_check_unsupported_control_flow`) | `UNSUPPORTED_ALTER` | any `AlterStatement` anywhere in PROCEDURE DIVISION (found via `_find_statements_of_type`, which reuses `_nested_statement_lists`) — ALTER rewrites another paragraph's GO TO target at runtime, so no static edge set the BFS computes is ever sound while one exists (audit finding 1.5) |
| `check_expansion_warnings` | `EXPANSION_WARNING` | any `CopybookExpansion.statistics.warnings` entry containing `"Lossy decode of"` — U+FFFD replacement characters are already substituted into the expanded source the run would compile. The same channel carries advisory lint heuristics ("may be missing terminating period", "contains only comments", "possible unbalanced quotes") that false-positive on valid copybooks (verified against `tests/integration/fixtures/copybook_example`), so ONLY the lossy-decode class refuses |
| `check_unresolved_copybooks` | `UNRESOLVED_COPYBOOK` | raw source, re-lexed with `CobolLexer(free_form=True)`, still contains a `TokenType.COPY` token. **Narrowed for `run`/`lint`/`export`/`debug`** (via `check_unresolved_copybooks_scoped`): a COPY token inside one paragraph's own body (a procedural copybook) whose line `_copy_own_line_span` verifies textually as the single-line `COPY MEMBER.` layout owning its whole line (starts with COPY, ends with its terminating period, no other period — the lexer exposes no PERIOD token type, so this is text, not tokens) is held back and refused only when the paragraph is in `union_executed_paragraphs`; when waived, `run_static_checks` comments the line out of `lines` (`comment_and_replace`, count-preserving) because the raw COPY text would otherwise still reach cobc, which cannot compile an unresolvable COPY. DATA DIVISION COPYs, sibling-sharing lines, and multi-line COPY ... REPLACING stay whole-program |
| `check_nested_exec` | `NESTED_EXEC` | any EXEC (SQL/CICS/DLI) site with `nested=True` and `span is None` — **regardless of reachability** |
| `check_nested_exec` | `UNSUPPORTED_SQL_WHENEVER` | an `EXEC SQL WHENEVER` (`MockSurface.whenever_sites`, issue #195) whose action is not CONTINUE / GO TO <paragraph> for SQLERROR / SQLWARNING / NOT FOUND (`analysis.sql_whenever.parse_whenever`): WHENEVER is emulated, not mocked (see [splicer](splicer.md)), and an unreadable one can neither be emulated nor dropped without changing control flow -- whole-program |
| `check_nested_exec` | `UNSPLICEABLE_EXEC` | any EXEC site with `nested=False` and a non-`None` `unspliceable_reason` — a top-level EXEC that does not own its source line(s); every EXEC must be stubbed program-wide (unmocked ones get `build_exec_trap`) so this is whole-program too, not per-case (audit finding 2.1) |
| `check_linkage_layout` | `UNSUPPORTED_LINKAGE_LAYOUT` | `linkage.linkage_plan` finds a named `ENTRY` + non-empty LINKAGE SECTION (the IMS `ENTRY 'DLITCBL'` shape), but one of three guardrails fails: the default entry's header can't be delimited (`CHAINING`, or a `USING`/`RETURNING` list with no closing period -- a delimitable `USING` is blanked by `neutralize` since 2026-10-10); LINKAGE SECTION isn't the last DATA DIVISION section; or the computed header line doesn't textually verify. `[]` (no refusal) when there's nothing to do (`linkage_plan` is `None`) or the shape is safe — in the safe case, `splicer.linkage.neutralize` runs instead of any refusal. See [splicer](splicer.md#entrylinkage-neutralization-linkagepy) and [docs/2026-07-08-ims-linkage-support-design.md](../docs/2026-07-08-ims-linkage-support-design.md) |
| `check_linkage_layout` | `UNSUPPORTED_LINKAGE_ADDRESSING` | a `SET ADDRESS OF <folded LINKAGE item>` occurrence that `linkage.address_of_sites` cannot express as a single-line column span — a receiving `ADDRESS OF <item>` split across lines. Classification is per statement (2026-09-28): `CALL ... USING ADDRESS OF X`, value-side `SET p TO ADDRESS OF X` and `EXEC ... END-EXEC` operands are legal after the fold and never refuse, wherever their line breaks fall. Folding the LINKAGE SECTION into WORKING-STORAGE gives those items real storage, which is exactly what makes rebinding their address illegal (GnuCOBOL: `cannot change address of 'X', which is not BASED or a LINKAGE item`), so an occurrence left in place is a hard compile error, not a fidelity nicety. The ordinary single-line shape is **not** refused — `splicer.linkage.redirect_address_of` rewrites it to a scratch pointer. Detection is textual because cobolparser's `SetStatement` drops the target-side `ADDRESS OF` (`SET ADDRESS OF X TO Y` and `SET X TO Y` both arrive as `targets=["X"]`). See [splicer](splicer.md#set-address-of-on-a-folded-item-2026-08-28-fix) |
| `check_cics_eib_layout` | `UNSUPPORTED_CICS_MACRO` | **Since 2026-09-28:** `splicer.cics_resp.expand_dfhresp` runs first (in `run_static_checks` step 5b and in `generate`) and rewrites every single-line `DFHRESP(<condition>)` outside a string literal to its EIBRESP number from `DFHRESP_VALUES` (IBM's table, values confirmed by two sources only; width-preserving), exactly the translator's substitution — so only DFHVALUE, an unknown condition, or a split call reaches this gate. The gate also blanks every `EXEC ... END-EXEC` block and string literal first (`_mask_exec_blocks`, line/column-preserving): a call inside an EXEC block never reaches cobc (spliced away wholesale), and one inside a string is text. Otherwise: the normalized text contains a `DFHRESP(...)`/`DFHVALUE(...)` call (`_DFHRESP_MACRO_RE`, COBOL-aware word boundaries, case-insensitive) — CICS-translator macro-functions expanding to literal response codes out of a large, translator-version-sensitive condition table, which mockymock has no translator to expand. **Narrowed for `run`/`lint`/`export`/`debug`** (via `check_cics_eib_layout_scoped`): a call `_paragraph_owning_line` proves to sit inside exactly one PROCEDURE DIVISION paragraph's own body, and whose whole call text `_CICS_MACRO_CALL_RE` spans on a single line, is held back as a `ParagraphScopedRefusal` and refused only when `union_executed_paragraphs` says that paragraph could execute. This one is scopable because an unexpanded macro is a property of the *code that evaluates it*, not of the program's storage layout. When waived, `run_static_checks` overwrites the call's own columns with `CICS_MACRO_PLACEHOLDER` (`-1`, space-padded to the identical width via `stub_writer.replace_columns`, so no line or column any AST location indexes into moves) — cobc has no CICS translator and could not compile the macro even in dead code, exactly the reason a waived `UNRESOLVED_COPYBOOK`'s line gets commented out. `-1` is not a value any real CICS condition expands to, so every comparison against it is deterministically false. The attribution passes `label_scan_to_line=True`: unlike a PARSE_WARNING (whose line proves only where a drop *starts*), a macro call's extent is exactly its own line, so an unrecognized label AFTER it cannot change ownership — scanning the whole body would veto essentially every real case, since the `IF ... DFHRESP(...) ... END-IF.` idiom's own bare `END-IF.` matches `_CANDIDATE_LABEL_RE`. Anything unlocalizable — a DATA DIVISION occurrence, a call continued across lines, an argument that is not a single COBOL word, a span too short to hold the placeholder — stays whole-program, fail closed, and any mismatch between detected and classified counts refuses everything. `generate`/`fixtures` keep the unscoped entry point (no cases to scope by) |
| `check_cics_eib_layout` | `UNSUPPORTED_CICS_DFHCOMMAREA` | `DFHCOMMAREA` referenced in the normalized text but not among `collect_declared_items`' names — unknowable size/layout. **Never scoped**, unlike the macro check above: this reports a missing *declaration*, and mockymock would have to synthesize storage for it however unreachable its references are |

**Why `UNRESOLVED_COPYBOOK` is textual, not AST-based:** cobolparser's `parse_cobol` does *not* raise a parse error for an unresolved `COPY` statement — verified empirically: raw source containing `COPY ORDREC.` yields `result.success is True` and an empty `data_items` list. Worse, the AST node class `CopyStatement` is never instantiated by any parser path, so an unresolved COPY leaves **zero trace in the AST**. The only reliable signal is textual: re-lex `raw_source` (with `free_form=True` — fixed-format column rules would garble already-normalized text) and look for a `TokenType.COPY` token, rather than a substring search that could false-positive on the word "COPY" inside a comment or string literal.

**Why `NESTED_EXEC` is whole-program, not per-case:** GnuCOBOL cannot compile a raw `EXEC SQL`/`EXEC CICS`/`EXEC DLI` block at all — every EXEC site must be stubbed out program-wide for `cobc` to compile, independent of whether any test case reaches it. A nested EXEC with no validated splice span therefore refuses the whole file by its mere existence anywhere in the program, not by being on some case's reachable path.

## Per-test-case checks (`check_test_case`)

Reachability is computed by `_reachable_paragraphs`, a **self-contained BFS over `PerformStatement` AND `GoStatement` edges, plus a SORT/MERGE's implicit INPUT/OUTPUT PROCEDURE edge** (2026-07-07 fix, audit findings 1.1/1.2; SORT/MERGE edge added 2026-08-17) — deliberately *not* cobolparser's `ProgramFlowAnalyzer` — so this module's correctness stays checkable against the same small verified-attribute set the rest of mockymock depends on (`CobolParagraph.statements`, `.location.line`, `PerformStatement.target_paragraph`/`.thru_paragraph`, `GoStatement.target_paragraphs`, `SortStatement`/`MergeStatement.input_procedure`/`.output_procedure`/`.input_procedure_thru`/`.output_procedure_thru`). **A CALL is a leaf**: never traversed into, since the called program's source isn't part of the compilation unit.

**Flow-edge model:**
- `PERFORM <paragraph>` pushes that paragraph, as before.
- `PERFORM <section>` (audit finding 1.2 — previously silently `continue`d) pushes every paragraph of that section: a performed section executes all of them by fall-through. `_reachable_paragraphs` builds a `section_members: dict[str, list[str]]` map from `procedure._sections`; when a pushed name resolves to a section instead of a paragraph, the BFS marks the section name `seen` and pushes its member paragraph names.
- `GO TO <target>` (audit finding 1.1 — previously not traversed at all) pushes every name in `GoStatement.target_paragraphs` — for `GO TO A B C DEPENDING ON X` that is all three, not just `target_paragraph` (the first one). Targets may themselves be paragraphs or sections, handled identically to PERFORM targets.
- **A `SortStatement`/`MergeStatement`'s `input_procedure`/`output_procedure`** (2026-08-17, SORT/MERGE mocking) pushes each named paragraph exactly like a PERFORM target, with `input_procedure_thru`/`output_procedure_thru` range-expanded via `_expand_thru_range` exactly like `PERFORM ... THRU` — modeled via `_find_sort_merge_statements` (a `_find_statements_of_type` reuse, mirroring `_find_flow_statements`) inside the same per-paragraph loop, unconditionally for ANY SORT/MERGE with a procedure clause (both the now-mockable pure-procedure form and the still-refused mixed form). No `PerformStatement` AST node exists for this edge — a SORT/MERGE statement itself is not one — so without this, a RELEASE/RETURN (or any other boundary statement) reachable only through an INPUT/OUTPUT PROCEDURE paragraph would be invisible to the fail-closed gate, exactly the hazard class the 2026-07-07 remediation and the GO-TO-fall-through closure below both exist to prevent. Confirmed as a real, not just theoretical, gap: `tests/unit/test_sort_merge_mocking.py`'s `test_pure_procedure_reachability_edge_is_modeled` demonstrates the empty reachable set without this edge and the correct one with it.
- **An `XML PARSE`'s `PROCESSING PROCEDURE p [THRU q]`** (2026-09-02) is the same implicit-PERFORM shape: `_find_xml_parse_statements` (a `_find_statements_of_type` reuse over `XmlJsonStatement` with `action == "PARSE"`) pushes `processing_procedure` like a PERFORM target and range-expands `processing_procedure_thru` via `_expand_thru_range`. A cobol-parser that keeps the clause as text only (no `processing_procedure` attribute but `clause_text` matching `XML_PROCESSING_PROCEDURE_RE`) refuses `UNRESOLVED_FLOW_TARGET` rather than silently dropping the edge. Pinned by `test_verb_coverage_fail_closed.py`'s XML PARSE tests.
- Any PERFORM/GO TO/SORT-procedure/XML-PARSE-procedure target that resolves to **neither** a paragraph nor a section refuses `UNRESOLVED_FLOW_TARGET` instead of being silently skipped (the pre-fix `PERFORM <section>` bug) — fail closed: an edge the model cannot resolve means the reachable set cannot be trusted. The BFS seed (`case.perform_target`) is exempt from this and reports `UNKNOWN_PARAGRAPH` instead (a `.cut` author's typo, distinct from an in-program flow-target problem).
- A paragraph name defined in more than one SECTION (`duplicated_paragraph_names`; COBOL resolves it by section, `X IN S` qualifies it) refuses `AMBIGUOUS_PARAGRAPH` in `check_test_case` whenever the case's reachable set contains it, before any boundary-site matching (issue #284). Every map here (`by_name`, `index_by_name`, `_plain_perform_edges_from`'s) keys paragraphs by bare name, so the walk followed one definition's body and sites matched in both -- a CALL only the other body made ran for real after a clean lint, and the right MOCK was refused `UNMATCHED_MOCK`. This is the fail-closed stopgap; section-aware `(section, name)` resolution is the real fix and is not implemented. `generate --per-paragraph` lists such names under a `Not scaffolded` comment instead of emitting an unqualified `PERFORM` cobc rejects.

For every `BoundarySite` in the reachable set:

| Condition | Code | Why |
|---|---|---|
| `category is None`, label `"dynamic CALL"` | `DYNAMIC_CALL` | identifier cobolparser failed to capture — no static match key exists at all |
| `category is None`, label `"SORT/MERGE"` | `UNSUPPORTED_SORT_MERGE` | only a **mixed-form** SORT/MERGE (a USING/GIVING file paired with a procedure clause on the other side) reaches this row — it touches a physical file mockymock cannot seed/read AND runs a procedure whose other logic a whole-statement mock would silently skip. A plain-file-form SORT/MERGE has `category` set (`MockCategory.SORT`/`MERGE`); a pure-procedure-form SORT is never recorded as a site at all (left real); RELEASE/RETURN always have `category` set (`MockCategory.RELEASE`/`RETURN`) regardless of the enclosing SORT/MERGE's shape — all three fall through to the ordinary rows below like any other file-op site |
| `category is None`, label `"CANCEL"` | `UNMOCKED_CANCEL` (unless covered) | see the CANCEL subsection below |
| terminator site (`StopStatement`(RUN-form)/`GobackStatement`/EXIT PROGRAM, or an EXEC CICS RETURN/XCTL/ABEND -- `is_terminator_site`, issue #215) found unsafe by `find_terminator_plans` | `UNSUPPORTED_TERMINATOR_LAYOUT` | evaluated by `check_terminator_layout`, run alongside `check_test_case` in the CLI's refusal loop, not as one of `check_test_case`'s own per-site conditions above -- see [splicer](splicer.md#terminator-neutralization-gobackstop-run-approach-b). A SECTION member is safe when it is entered one way only (`_section_member_modes`, 2026-10-27): inside a `PERFORM <section-name>` range (first paragraph, or reached from it by fall-through: `EXIT SECTION`) or PERFORMed only by its own name (`EXIT PARAGRAPH`); a member entered both ways, inside a THRU range, or a GO TO target falls back to a GOBACK to the test from the driver's call frame (`exit_kind` "RETURN", 2026-11-03), and refuses only when that cannot work either (EXEC CICS, a SORT/MERGE or XML PARSE procedure, an unspliceable line, a hook PERFORM) — see `docs/2026-10-27-section-member-terminators-design.md` and [splicer](splicer.md) |
| `category is None`, label `"INVOKE"` / `"CHAIN"` / `"communication"` / `"STOP literal"` / `"unsupported statement"` | `UNSUPPORTED_INVOKE` / `UNSUPPORTED_CHAIN` / `UNSUPPORTED_COMMUNICATION` / `UNSUPPORTED_STOP_LITERAL` / `UNSUPPORTED_STATEMENT` | see "Fail-closed over statement types" above; the message names the paragraph, line and verb and suggests `MOCK PARAGRAPH` or performing a caller that never reaches it |
| zero directives match | `UNMOCKED_CALL`/`UNMOCKED_FILE_OP`/`UNMOCKED_SQL`/`UNMOCKED_CICS`/`UNMOCKED_DLI`/`UNMOCKED_CONSOLE_ACCEPT`/`UNMOCKED_REPORT_WRITER` | unmocked CALL has nowhere to link; unmocked file I/O (including a plain-file-form SORT/MERGE and a RELEASE/RETURN, all of which share `UNMOCKED_FILE_OP` via `_UNMOCKED_CODES`'s per-category default) hits a nonexistent sandbox file; unmocked EXEC can't compile; unmocked console ACCEPT reads whatever stdin is attached. This is the one row whose `RefusalReason` also carries `suggested_fix` (2026-09-15): `dsl.generator.directive_snippet(site, surface)` renders the exact `MOCK ... END-MOCK` block that would resolve it -- the same renderer `generate`'s own scaffold uses (`_directive_for`), so a suggestion can never disagree with what a fresh scaffold would produce for the same site. `None` when `directive_snippet` itself declines (an unparsed CALL literal, an unrepresentable quote in a key/prefix). `mockymock lint`/`run`/etc. print it as an indented "Add to this TESTCASE:" block after the reason; `mockymock generate --fill CUT_FILE` inserts it directly into the file (`checks.StaticCheckResult.unmocked_reasons`, keyed by TESTCASE name, is how `--fill` gets at the raw reasons without re-running `check_test_case` itself). See docs/2026-09-15-actionable-refusals-and-fill-design.md. |
| 2+ directives match | `AMBIGUOUS_MOCK` | fail closed rather than pick one -- except one directive per file of a multi-file OPEN/CLOSE (or per report of INITIATE/TERMINATE), `per_file_matches`, issue #348. The message names the actual clash (a key mocked twice, or several MOCKs on a one-key statement) instead of "make the keys unambiguous" |
| exactly 1 match, `site.nested and site.span is None` | `UNSUPPORTED_NESTED_MOCK_TARGET` | no validated replacement span — splicing could swallow a block terminator and corrupt control flow (an earlier attempt without the scope map did exactly that) |
| exactly 1 match, `not site.nested and site.unspliceable_reason` | `UNSUPPORTED_MOCK_TARGET_LAYOUT` (2026-07-07, audit finding 2.1) | a top-level statement that does not own its source line(s) — sibling code before it, a one-line paragraph header, or another statement sharing the line — would have its whole-line splice delete that sibling code. Code before it that ends a sentence (`PERFORM A. CLOSE F.`) does not count since 2026-11-02: the splice keeps it (`span_lead`, see splicer.md) |
| a mocked READ/RETURN/WRITE/REWRITE/DELETE/START/CALL whose clause bodies `clause_bodies.clause_lift_problem` cannot lift | `UNLIFTABLE_CLAUSE_BODY` (issue #319) | evaluated by `check_clause_bodies`, run after `check_terminator_layout` in the CLI's step 8, program-wide like the splicer's own matching (a nested site with no span is left to `UNSUPPORTED_NESTED_MOCK_TARGET`); the splice replaces the whole statement, so every body would be deleted with it -- see [splicer](splicer.md#clause-bodies-re-run-after-the-mock-issue-209-2026-10-16) |
| a `CAPTURE ARG <n>` directive matches a site whose real `CallStatement.using_parameters` has fewer than `n` entries | `CAPTURE_ARG_OUT_OF_RANGE` | the splicer would resolve `<n>` against nothing -- checked against *every* matching site **program-wide, not reachability-filtered** (see below), so refuses even if only one of several sites sharing the mocked key is too narrow (fail closed over partial safety); also when position `n` is `OMITTED` at any matching site (`USING OMITTED B`, reported by cobolparser as a parameter named OMITTED), whose splice `MOVE OMITTED TO <target>` passed lint and failed cobc (2026-10-13) |

**These same three conditions are re-checked a second time, program-wide (2026-08-11 fix):** immediately after the reachable-set loop above, `check_test_case` runs a second pass over `surface.boundary_sites` unfiltered — skipping any site the first pass already visited — matching each remaining site against this case's own `case.mocks` the same way. Reason: `splicer.orchestrator.splice_program` does not filter by reachability at all — it walks every `surface.boundary_sites` entry and splices any one `directive_matches_site` matches for any directive of any case, category/key (or normalized-text) only, and *not* narrowed by `mocked_flow_names` either (splice_program does not skip boundary sites inside a flow-mocked paragraph's body — body lines never move, see [splicer](splicer.md)). So a directive whose owning case never reaches some OTHER physical site sharing its key/category can still get that site spliced against it: `injector.build_site_dispatch` re-derives AMBIGUOUS_MOCK itself (raising `ValueError` when 2+ of that case's directives match one physical site), and `orchestrator.splice_program`'s own defensive invariant checks re-derive the nested/layout conditions the same way, against the same unfiltered site set. Confirmed concretely: a multi-file `OPEN INPUT A OUTPUT B` in a paragraph no test case's PERFORM ever reaches, mocked incidentally by one case's `MOCK OPEN A` + `MOCK OPEN B` (each individually matching that case's own reachable single-file sites elsewhere, so nothing looked ambiguous within the reachable set) — `mockymock lint` reported no problems; `export`/`run` then died with `injector.py`'s unhandled `"...refusal gate should have caught this (AMBIGUOUS_MOCK)"` `ValueError`. Same underlying invariant `CAPTURE_ARG_OUT_OF_RANGE`'s own whole-program check documents wherever that feature has landed: for any refusal-gate check whose violation the splicer treats as "should have been refused already," the gate's site set must be a true superset of the splicer's site set — reachability was never the operative filter for what the splicer processes. See `tests/unit/test_cli.py`'s `test_lint_refuses_ambiguous_mock_against_a_site_unreachable_by_any_case`/`test_export_refuses_the_ambiguous_mock_shape_instead_of_raising` (CLI-level, the layer the bug escaped through) and `tests/unit/test_refusal.py`'s `test_per_case_check_refuses_nested_mock_target_matched_program_wide` (confirms `UNSUPPORTED_NESTED_MOCK_TARGET` had the identical gap).

After the site loop: any directive in `case.mocks` never matched → `UNMATCHED_MOCK` — except a `MOCK ACCEPT` whose key names an `ACCEPT <target> FROM DATE/TIME/DAY/COMMAND-LINE/...` (`surface.non_interactive_accepts`, recorded by `mock_surface` for exactly this purpose), which refuses `UNMOCKABLE_ACCEPT_SOURCE` instead: those ACCEPTs read a system register rather than the console, so `mock_surface` deliberately makes no boundary site for them and there is nothing a mock could intercept. Reporting that as `UNMATCHED_MOCK` (“does not match any boundary site reachable from …”) reads as a call-graph reachability bug and sends the author off verifying reachability by hand; it is a different problem and gets its own code and message. **Clock ACCEPTs are the exception (#240):** `ACCEPT x FROM DATE/TIME/DAY/DAY-OF-WEEK` (`CLOCK_ACCEPT_SOURCES`) reads the system clock, so a test can only pin it by mocking it. `mock_surface.promote_clock_accepts(surface, mocks)`, called by `run_static_checks` right after `analyze`, turns every clock ACCEPT some MOCK names into an **opt-in** `BoundarySite` (`opt_in=True`) and drops it from `non_interactive_accepts`. An opt-in site no MOCK in this case matches is skipped by the unmocked gate, and the splicer's dispatch runs the real statement in its `WHEN OTHER` (`build_site_dispatch(passthrough=...)`) instead of the error trap. A clock ACCEPT no MOCK names is never promoted, so such programs splice exactly as before; `generate`/`report` (which never promote) are unaffected. Any `VERIFY` whose `(category, key)` isn't in `{(m.category, m.key) for m in case.mocks}` → `VERIFY_WITHOUT_MOCK` (its tally counter would be undeclared/stale). Then a final pass over `case.mocks` checks two conditions sharing one `missing_status_field` root cause, both refusing the same `UNRESOLVED_FILE_STATUS_TARGET` code, the second an `elif` of the first since 2026-08-10 (audit finding F27 — previously independent `if`s, so a directive that was both FILE-STATUS IS sugar and a `MOCK READ ... ROWS` with no TERMINAL, on a file missing from `file_status_fields`, refused the same code twice): (a) `FILE-STATUS IS` sugar -- any directive with `.file_status is not None` and `missing_status_field` → refused (the file's `SELECT` entry has no `FILE STATUS IS <field>` clause, so there is nowhere to move the status); (b) *elif* `MOCK READ ... ROWS` with no `TERMINAL` group -- any directive with `.rows is not None and .terminal_row is None` and `missing_status_field` → refused (splicer's `build_rows_block`'s rows-exhausted branch would have no status field to default to AND no `TERMINAL` group to fall back on -- the generated READ loop could never signal end-of-data, see [dsl](dsl.md)'s `ROWS`/`TERMINAL` grammar and [splicer](splicer.md)'s `ROWS` dispatch) -- **unless** every site the directive matches has an `AT END` clause `clause_bodies_liftable` accepts (`_gates._at_end_ends_rows`, issue #341): since #209 the exhausted branch moves `"10"` to `UT-MOCK-STATUS`, which runs that lifted clause, and that clause is what ends the loop in the real program too. Applies to READ and RETURN alike; an SD can never declare FILE STATUS, so before #341 every `MOCK RETURN ... ROWS` without `TERMINAL` was refused.

**Why `CAPTURE_ARG_OUT_OF_RANGE` is evaluated program-wide even though it lives in `check_test_case` (2026-08-11, final whole-branch review):** the directive belongs to exactly one test case, so the *check* is per-case — but its *site set* must not be. `splicer.orchestrator.splice_program` iterates every `surface.boundary_sites` entry with no reachability filter at all, and splices any site for which `directive_matches_site` returns True for **any** directive of **any** case in the suite (pure category+key matching, deliberately blind to which case is being spliced — that's what lets one directive cover several physical sites sharing a key). `injector.build_site_dispatch` then emits that directive's `CAPTURE ARG` `MOVE`s into that site's `WHEN` branch and raises `ValueError` if the index exceeds its `USING` count. Filtering the gate by the owning case's `reachable` set therefore left a hole: a program with `CALL "X" USING A B` in one paragraph and `CALL "X" USING A` in another, mocked by two independent cases where only the first `CAPTURE ARG 2`, passed `lint` clean and then crashed `export`/`run` with an unhandled `ValueError`. Same reasoning as [`NESTED_EXEC` being whole-program](#whole-program-checks-independent-of-any-test-case): the gate's site set must be a superset of what the splicer actually processes. Regression coverage: `tests/unit/test_cli.py::test_lint_refuses_capture_arg_against_a_site_only_another_case_reaches` (CLI-level, the layer the bug actually escaped through) plus `tests/unit/test_refusal_capture.py`.

**CANCEL as a covered-not-mocked site (audit finding 1.6):** `CancelStatement` is detected by `mock_surface.py` with `category=None`, `label="CANCEL"`, and `keys` set to every name on the statement (`.program_names`) — but unlike SORT/MERGE it is never *unconditionally* unmockable. `check_test_case` treats it as covered when, for **every** name in `site.keys`, the test case has a matching `MOCK CALL` (static, exact key) or dynamic-CALL directive (uppercased identifier match) — a mocked CALL never loads a real module, so cancelling it is a guaranteed GnuCOBOL no-op, and the covering directives are added to `matched_directives` (so the CALL mock is not spuriously flagged `UNMATCHED_MOCK` if its only reachable use is covering the CANCEL). Any uncovered name refuses `UNMOCKED_CANCEL`. `CANCEL` is never spliced regardless (`category is None` keeps it out of `splice_program`'s loop) — it is always left in place as plain COBOL.

`directive_matches_site` matching rules:
1. `site.category is not directive.category` → never matches (this is what keeps a quoted static-CALL directive from ever cross-matching a dynamic-CALL site, and vice versa — category identity alone does the work).
2. `EXEC_CATEGORIES` (SQL/CICS/DLI): normalized-prefix match against `site.match_text`, both sides passed through `_exec_match_form` (normalize + drop the whitespace around `. , ( ) :`). The site text is cobolparser's `sql_text`, which rejoins tokens with spacing the source never had and that differs by release (published 1.8.x: `BANK. TRANSACTION_HIST`; later: `BANK.TRANSACTION_HIST`; both: `( A, B )`, `INTO:WS-A`) -- comparing raw made a key copied from the source UNMATCHED_MOCK and a `.cut` break across cobol-parser releases (2026-09-28). `match_text` itself is unchanged (it is still what messages and `generate` show). The prefix must also end on a name boundary (`_exec_prefix_matches`, round 7): a key ending in a name character never matches a site whose text continues that name, so `MOCK SQL "FETCH C1"` no longer mocks `FETCH C10` (silently serving it C1's ROWS, or refusing AMBIGUOUS_MOCK when both were mocked), nor `MOCK CICS "READ"` `READQ TS`, nor `MOCK DLI "GN"` `GNP`.
3. `MockCategory.CALL`: exact match, `directive.key in site.keys`.
4. Everything else (file ops, ACCEPT, DYNCALL): `directive.key.upper() in site.keys`.

## `real_programs.py` -- USE REAL CALL programs (2026-11-01)

Step 7a of `cli/checks.py` (`_check_real_programs`), so `lint` and `run`
agree: `collect_real_specs` (FROM file exists, one file per program:
`REAL_SOURCE_NOT_FOUND`, `CONFLICTING_REAL_SOURCE`), `prepare_real_program`
(parse, whole-program refusals, `REAL_PROGRAM_ID_MISMATCH`, surface,
nested-site spans; LINKAGE is **not** neutralized, the program is CALLed),
`check_real_program` (every boundary site of the real program must be
matched in every case that makes it real -- no reachability narrowing;
`GOBACK` / `EXIT PROGRAM` / `CANCEL` / `STOP RUN` run as written, `STOP RUN`
warns `REAL_PROGRAM_STOP_RUN`). Data names in the mocks answering a real
program are checked against it (`program_only_view`); the entry program's
own checks then run on `entry_program_view` (directives matching only
real-program sites, and their VERIFYs, removed) while `out.suite` keeps
the full suite for the driver. Design: [docs/2026-11-01-real-call-integration-design.md](../docs/2026-11-01-real-call-integration-design.md).
A dynamic CALL can reach a real program (2026-11-02): `check_test_case`
marks the case's USE REAL CALLs used when it reaches a `DYNCALL` site, and
`matched_directive_ids` counts them for any surface with one
([docs/2026-11-02-real-dynamic-call-design.md](../docs/2026-11-02-real-dynamic-call-design.md)).

## Dynamic CALL as its own category (`DYNCALL`)

A dynamic `CALL WS-PGM-NAME` is mockable because mockymock never *links* a mocked CALL — the splicer comments out the whole statement and replaces it with an EVALUATE dispatch block, so nothing at runtime needs to resolve a program name. What the machinery needs is a static match key, and the identifier the CALL goes through is exactly that (`CallStatement.called_program == "WS-PGM-NAME"` when `is_dynamic` is True — verified against cobolparser 1.1.0/1.2.0).

`DYNCALL` is a category distinct from `CALL`, not a flag on it, because:
- Matching semantics genuinely differ: quoted keys match a static site's literal **exactly** (case-sensitive as written); bare keys match the dynamic site's **uppercased** identifier.
- A flag would force `MOCK CALL "X"` and `MOCK CALL X` to collide into one tally/verify slot, or change the `(category, key)` tuple shape used throughout (`TallyRegistry`, `all_mock_keys()`, the driver's declared-set check).
- With a distinct category, `directive_matches_site`'s existing default branch (`key.upper() in site.keys`) already implements dynamic matching for free — no special-casing needed.
- Fail-closed cross-matching falls out for free: category mismatch alone guarantees a quoted directive can never match a dynamic site.

Matching is **per-identifier, not per-target-program**: two dynamic sites calling through the same identifier are both satisfied by one directive (same as two `OPEN INFILE` sites today); sites through different identifiers need their own directives. `_UNMOCKED_CODES[MockCategory.DYNCALL] = "UNMOCKED_CALL"` — same code as static CALL; the message's `"dynamic CALL"` label and identifier key are what distinguish it in output.

## PERFORM THRU range expansion (reachability only — never a splice target)

`PERFORM A THRU B` is **not a boundary statement**; it only affects which paragraphs are reachable. Fall-through means the range A..B executes every paragraph in source order — idiomatic mainframe shape is `MAIN-PROCESS ... GO TO MAIN-EXIT ... MAIN-EXIT. EXIT.`

`_source_ordered_paragraphs(procedure)`: all paragraphs sorted by `location.line`, or `None` if the sorted line sequence is **not strictly increasing** (a parser regression trips this — every expansion in the program then refuses fail-closed rather than guessing an order). This differs deliberately from cobolparser's own `ProgramFlowAnalyzer._range_members`, which degrades to best-effort `[start, end]` endpoints on a malformed range — the refusal gate must never do that.

`_expand_thru_range(ordered, start, thru, origin, missing_code)` returns either the inclusive name-slice `[start..thru]` (phantom `"."` paragraphs ride along inertly — see Gotchas) or a `RefusalReason` for a degenerate range:

| Degenerate case | Code | Detail |
|---|---|---|
| `ordered is None` | `UNSUPPORTED_PERFORM_THRU` | order verification failed |
| endpoint name count == 0 | `missing_code` (`UNSUPPORTED_PERFORM_THRU` for in-program PERFORMs, `UNKNOWN_PARAGRAPH` for the test case's own driver-side range) | endpoint not found |
| endpoint name count > 1 | `UNSUPPORTED_PERFORM_THRU` | ambiguous — could silently cover the wrong slice |
| `thru` index < `start` index | `UNSUPPORTED_PERFORM_THRU` | backwards range, runtime behavior is implementation-defined |

`_reachable_paragraphs` seeds the BFS stack with the test case's own `perform_target`/`perform_thru` range (missing driver-side endpoints are the `.cut` author's typo → `UNKNOWN_PARAGRAPH`), then for every reachable paragraph's `PerformStatement`s with a `thru_paragraph`, expands and pushes that range too (`_expand_thru_range` reused, default `missing_code="UNSUPPORTED_PERFORM_THRU"` since these are in-program). `_find_flow_statements` (formerly `_find_performs`) recursively collects `PerformStatement`s (and `GoStatement`s) from nested bodies too, reusing `mock_surface._nested_statement_lists` rather than reimplementing nested traversal.

A THRU range covering a paragraph with an unspliceable nested site just makes that site reachable — `UNSUPPORTED_NESTED_MOCK_TARGET` fires through the ordinary per-site path, no special casing needed.

# stub_expectations.py — `*> STUB EXPECT` Scanner

`scan_stub_expectations(cut_text, suite) -> StubScanResult` finds every
`*> STUB EXPECT <data-name> [-- <note>]` comment in the raw `.cut` text and
attributes each one to the TESTCASE it's written inside, by that case's
1-based position in `suite.test_cases` — the exact case id
`splicer.driver.build_driver` will assign it (`UT-TESTCASE-{index:03d}`).

This is a raw-text scanner, not a grammar addition to `dsl/parser.py`: a
stub comment is an ordinary `*>` comment as far as `parse_cut()` is
concerned (zero parser changes needed), and `mockymock collect` parses
`.cut` files with no `.cbl` at all, so teaching the shared grammar/model
about stubs would mean every other subcommand learns to ignore a field
that matters to exactly one of them. See
docs/2026-08-04-record-expectations-design.md's "Why a raw-text scanner,
not a grammar addition" section for the full argument.

Two things this scanner deliberately does NOT attempt, each producing a
`SkippedStub` (reported, never silently dropped) instead of a guess:

- **A stub inside a `PROVIDER`-templated `TESTCASE`.** One physical
  template block expands into *N* independently-lined runtime cases
  (`.line` points at each row's own line, not the shared header — see
  [dsl](dsl.md)) — a shape this scanner's line-span model cannot represent
  (a stub inside the template would need *N* different recorded values,
  one per row).
- **A stub whose owning `TESTCASE` was excluded by `--case`/`--tag` this
  run.** Callers must pass the POST-filter `suite`
  (`checks.filter_suite_cases` already applied) — the scanner
  cross-references its own raw-text `TESTCASE` header positions against
  `suite.test_cases` by exact line number, so an excluded case (removed
  from `suite.test_cases` entirely) simply has no match and its stub is
  reported skipped rather than misattributed to whichever case now
  occupies its old index.
- **A stub inside a `PROVIDER` data block** (among its `HEADER`/`ROW`
  lines). The parser closes the preceding `TESTCASE` when a `PROVIDER`
  opens, so a `PROVIDER` line bounds attribution like a `TESTCASE`
  header does; such a stub used to be credited to the previous case.
- **A stub above its `TESTCASE`'s `PERFORM`** (or in a case with no
  `PERFORM`). The recorded value is the post-`PERFORM` state and the
  rewrite replaces the stub line in place, so it became an `EXPECT` above
  the `PERFORM`, which the parser refuses (issue #150): the rewritten
  `.cut` no longer ran. The skip reason says to move the stub below it.

A lightweight `MOCK`/`END-MOCK` open/close tracker (not a real parser)
guards the scan against a stub-shaped comment written *inside* a mock
body — inert free-form COBOL to the real parser, and must stay inert here
too, since treating it as a real stub risks the rewrite step later
injecting an `EXPECT` line into the middle of a `MOCK` body. Safe only
because callers are expected to run this against a `.cut` file that
already passed `parse_cut()` — every `MOCK`/`END-MOCK` pair is therefore
already known to be balanced.

`report.record_rewrite` (see [report](report.md)) is the next stage:
matching each `StubExpectation` against a recorded test run and rewriting
the `.cut` file.

# Gotchas

**Phantom `"."` paragraphs are inert but change reachability tracking, not classification.** cobolparser emits a paragraph literally named `"."` for the sentence-terminating period line after an `EXEC ... END-EXEC` block (or after any PERFORM/PERFORM THRU/DISPLAY sentence followed by another statement). They are empty artifacts — no boundary site is ever attributed to `"."` in any verified layout — but a THRU range slice includes them positionally by name. If a future cobolparser version ever attributed real statements to one, every `"."` site program-wide would become reachable at once — an over-approximation in the fail-closed direction (spurious `UNMOCKED_*`, never a silently-unmocked boundary). `source_map.collect_boundaries` separately filters `"."` paragraphs when computing splice spans, because a boundary there would cut an EXEC statement's span one line short of its `END-EXEC`.

**`ExecSQLStatement` is not detectable via `node_type`.** Its base class `CobolStatement` hardcodes `node_type == "Statement"`; the `"EXEC-SQL"` string lands in `.statement_type` instead. `mock_surface.py` uses `isinstance` checks for this reason — which also transparently catches every `ExecSQLStatement` subclass (`DeclareCursorStatement`, `FetchStatement`, `DynamicSQLStatement`, …) without hardcoding each one's `node_type`. `ExecCicsStatement`/`ExecImsStatement` extend `ASTNode` directly (not `CobolStatement`), so their `node_type` (`"EXEC_CICS"`/`"EXEC_IMS"`) works fine as a discriminator — but isinstance is used uniformly anyway.

**OPEN/CLOSE multi-file capture required a cobolparser fix.** Before branch `fix/open-multi-mode-file-capture`, `OPEN INPUT A OUTPUT B` silently dropped every file after the second mode keyword, so `MOCK OPEN B` could never match. mockymock's `_file_op_keys` depends on the fixed `file_names` list capturing all of them.

**An earlier nested-splice attempt corrupted control flow.** Before `source_map.annotate_nested_sites` existed to validate replacement spans, a nested site's splice could swallow a block terminator it had no location data for. `UNSUPPORTED_NESTED_MOCK_TARGET` / `NESTED_EXEC` now refuse fail-closed (`span is None`) rather than risk repeating that.

**`_source_ordered_paragraphs` returning `None` fails every THRU expansion in the program, not just the offending one** — there's no per-range fallback once order can't be verified.

**`DECLARATIVES` detection relies on cobolparser emitting it as a paragraph name — with a fallback since GH issue #106.** Verified empirically: a `DECLARATIVES ... END DECLARATIVES` block parses warning-free into a paragraph literally named `"DECLARATIVES"` (a reserved word no valid user paragraph can be named), which `_check_unsupported_control_flow` scans for directly — no cobolparser-side "is this a declaratives section" flag exists. That artifact is coincidental, not modeled, and issue #106 (a real IMS DL/I program with `DECLARATIVES` + `USE FOR DEBUGGING`) reported it being spliced and compiled with no refusal at all — most likely because something upstream of that paragraph (unrelated dropped content elsewhere in a much larger real file) resynchronized cobolparser's error recovery in a way that swallowed it, the same failure mode `_CANDIDATE_LABEL_RE`'s docstring already documents for ordinary paragraphs. `_check_unsupported_control_flow` now also scans for a bare `UseStatement` node anywhere in PROCEDURE DIVISION as an independent, structural fallback: `USE` is legal nowhere outside a `DECLARATIVES` section, so its presence alone proves one exists even if the named-paragraph artifact is lost. Pinned by `tests/unit/test_refusal.py::test_whole_program_check_refuses_declaratives_via_use_statement_fallback`, which simulates the loss directly (renaming the AST paragraph) since the pinned cobolparser reliably leaves the artifact behind for every shape tried so far.

**GO TO fall-through IS modeled by the general reachability BFS (fixed 2026-08-12).** An earlier revision of this doc claimed the opposite — that treating every `GoStatement` target as terminal "matches real COBOL control flow, so no under-approximation results" — and that claim was wrong in exactly the way it sounds safe: `GO TO` does transfer unconditionally, but the *target paragraph's own body* then falls through — by ordinary sequential execution, not a flow edge — into the next paragraph in source order whenever `_falls_through` can't prove it diverts. A `CALL`/file-op/`ACCEPT` in that fallen-into paragraph passed every per-case mock gate unmocked, survived splicing verbatim (unmocked non-EXEC sites are deliberately left in place), and executed for real at runtime. `_reachable_paragraphs` now walks source order forward from every reached GO TO target via `_falls_through` and feeds each fallen-into paragraph back into the BFS to a fixpoint — the same closure `union_executed_paragraphs` already applied for warning-waiving — failing closed (`UNRESOLVED_FLOW_TARGET`) when source order is unverifiable or a GO TO target can't be anchored in it. Pinned by `tests/unit/test_refusal_goto_fallthrough.py`.

**A boundary reached only through that closure warns instead of refusing (issue #351).** The closure is a deliberate over-approximation, and in the field it demanded a MOCK for every boundary downstream of any GO TO target -- blanket `BEFORE-EACH` mock lists that said nothing about what a case touches. `_reachable_paragraphs(direct_out=...)` now hands back the set reached by PERFORM / GO TO / implicit-PERFORM edges alone (the first BFS pass, before the closure adds anything); `check_test_case(warnings_out=..., traps_out=...)` reports an unmocked, spliceable site whose paragraph is in `reachable - direct` as `FALLTHROUGH_BOUNDARY` (a warning, deduplicated per boundary in `run_static_checks`) and puts its statement id in `StaticCheckResult.fallthrough_traps`. Every splicing pipeline passes that to `splice_program(fallthrough_traps=...)`, which replaces each such statement with `injector.build_unmocked_trap` -- a `CASE <id> FAIL: unmocked <label> boundary (line N) reached -- add a MOCK for it` marker plus `ADD 1 TO UT-FAIL-COUNT` -- so the boundary never runs for real: a case that does reach it fails, naming it. The `WHEN OTHER` trap of a site another case mocks emits the same FAIL marker (its old `ERROR:` line names no case the result parser can attribute). Callers that pass no `warnings_out` keep the fail-closed refusal. Not covered (still refused): CANCEL, an unresolved dynamic CALL, unsupported statements, and a site that cannot be spliced where it stands. Pinned by `tests/unit/test_refusal_goto_fallthrough.py` and `tests/integration/test_fallthrough_boundary.py`. Follow-up (2026-10-25): `check_test_case(direct_matched_out=...)` collects the directives matched at a site outside that closure; `run_static_checks` warns `FALLTHROUGH_ONLY_MOCK` for each BEFORE-EACH/BEFORE-ALL mock some case matches but none matches directly, so the blanket hook lists the old refusal forced can be pruned.

**The terminator-safety layer guards its own instance of the same hazard, separately.** A GO TO target paragraph whose own body has no unconditional exit (see `_falls_through`) really does fall through — via ordinary sequential execution, not a flow edge — into the next paragraph in source order at runtime. A paragraph reached that way was never PERFORMed either, so it shares the exact EXIT PARAGRAPH hazard spike #4 found for a direct GO TO target (docs/2026-07-08-goback-stop-run-support-design.md): silently halting instead of returning, once some other test case has neutralized the terminator it falls into. `find_terminator_plans` computes `_go_to_fallthrough_targets` (walking source order forward from every GO TO target until `_falls_through` says stop) and refuses `UNSUPPORTED_TERMINATOR_LAYOUT` for any terminator or chain paragraph inside that hazard zone — closed 2026-07-10, see [docs/2026-07-10-goto-fallthrough-terminator-hazard-design.md](../docs/2026-07-10-goto-fallthrough-terminator-hazard-design.md). Since 2026-10-25 that walk takes the same closed-PERFORM-range stop `_reachable_paragraphs` uses (`_closed_perform_ranges`, built per case entry point): a `GO TO X-EXIT` inside `PERFORM X THRU X-EXIT`, whose every PERFORM and GO TO stays inside the range, returns from that PERFORM and never falls past X-EXIT, so a terminator whose chain passes through a paragraph physically after X-EXIT is no longer refused (LEDGRPT, CHKCLR). A walk from outside a range that reaches its first paragraph drops the range and redoes the walks, as in `_reachable_paragraphs`. Pinned by `tests/integration/test_thru_exit_goto.py`.

**GO-TO-to-EXIT-PARAGRAPH simplification narrows the GO-TO hazard set itself (2026-08-17, STATUS: implemented, not yet verified against real GnuCOBOL).** `find_terminator_plans`'s own `UNSUPPORTED_TERMINATOR_LAYOUT` message for a GO-TO-target/fall-through hazard already suggests the fix: *"if it exists purely as an early exit, an `EXIT PARAGRAPH` in its place usually removes the need for the jump entirely."* `refusal.find_goto_exit_plans(program, scope_map, lines)` automates exactly that, whole-program and unconditional on any test case (like `NESTED_EXEC`'s reasoning, but "plan or silently skip" — declining it is always safe): for a `GO TO` into a provably no-op paragraph (`_is_exit_only_paragraph` — one bare `EXIT.` statement and nothing else) whose enclosing paragraph is itself safe (top-level, not a GO TO target, not a fall-through hazard) AND is the exit-only paragraph's immediate predecessor in source order, the `GO TO` is spliced directly into `EXIT PARAGRAPH` at its own call site — never physically transferring control to the target, so the "entered via GO TO" hazard the two rejected candidates in [docs/2026-07-10-goto-reachable-terminators-design.md](../docs/2026-07-10-goto-reachable-terminators-design.md) tried and failed to fix at the *target* never applies. All-or-nothing per target paragraph (a whole-program property can't be partially neutralized; a computed/multi-target GO TO merely *naming* the target, even one this loop can't resolve to a site, disqualifies it too — `_go_statement_raw_targets`). `find_terminator_plans` narrows its own `_go_to_targets` by every fully-neutralized target before deriving `_go_to_fallthrough_targets`, so a terminator chain whose only obstacle was this exact idiom now qualifies too — and `mockymock mutate` (`mutation/runner.py`) applies the same `goto_exit_plans` alongside `run`/`debug`/`export`.

**Cost model: the static-check pass is linear in program size (2026-08-28).**
It used not to be, and on a real 16.9k-line CICS program that showed up as
minutes of CPU per `lint`. Three scans were quadratic and all three are now
indexed or precomputed; anything added here should keep that property.
(a) `ScopeMap` queries (`splicer.source_map`) were full linear scans of
`boundaries`, two of them materializing a filtered copy of the whole list
first, and `annotate_nested_sites` runs one per boundary site — now a
lazily-built line index (`at_line`/`iter_after_line`; call `invalidate()`
if you ever mutate `boundaries`). (b) `collect_scope_map` re-scanned the
EXEC-block range list per lexed token — now flattened once by
`_exec_line_index` into covered-lines/end-column form. (c) `_falls_through`
was re-evaluated for every paragraph on every GO TO target's walk — 4.4M
calls on a 53k-line program in the shared-exit-label shape, where nothing
on the chain provably diverts so each walk runs to end of program. Now
`_fallthrough_flags` answers it once per paragraph, `_first_non_fallthrough`
gives each walk its stop index directly, `_go_to_fallthrough_targets` breaks
on an already-walked index (sound because two walks that both pass through
an index provably share a stop index), and the precomputed flags are threaded
into `_walk_fallthrough_from`'s two fixpoint call sites. Measured on a
53k-line CICS-shaped program: 14.2s -> 5.5s, with linear rather than
quadratic growth. All three are pure speedups — `lint` output is
byte-identical — and `tests/unit/test_static_check_scaling.py` pins each
against the naive scan it replaced.

**GO-TO-exit reachability narrowing (2026-08-25).** The splice above made `run`/`export`/`debug`/`mutate` compile a program with no `GO TO <exit-label>` edge, and `find_terminator_plans` already narrowed its hazard sets by the plans — but `check_test_case`/`_reachable_paragraphs` still modeled the spliced-away GO TO as a live edge. Consequence, seen on a real CICS program: any paragraph using the `GO TO <own-adjacent-EXIT-label>` early-return idiom pulled its bare-`EXIT.` landing pad into `go_to_targets`, whose fall-through walk then cascaded through every paragraph from the exit label to the end of the program — dozens of spurious `UNMOCKED_*`/`UNSUPPORTED_TERMINATOR_LAYOUT` refusals for boundaries the compiled test can never execute. Now: `neutralized_goto_targets(program, scope_map, lines)` (the fully-neutralized target names, all-or-nothing per target exactly as `find_goto_exit_plans` guarantees) is threaded by `cli.checks.run_static_checks` step 8 into every `check_test_case` call, and inside `_reachable_paragraphs` it (a) skips pushing a single-target unconditional GO TO whose target is neutralized and (b) subtracts the neutralized names from the fall-through closure's seed set. A computed/multi-target GO TO can never name a neutralized target (its existence disqualifies the target upstream), which is what makes (a)'s single-target check sufficient. `union_executed_paragraphs` (warning-waiving, step 4b) deliberately stays un-narrowed — it runs before `lines`/`scope_map` exist, and un-narrowed only ever waives *fewer* warnings. Flip side, intentional: a `.cut` that previously mocked cascade boundaries because the old model demanded them now refuses `UNMATCHED_MOCK` on those stale directives — delete them. Pinned by `tests/unit/test_reachability_goto_exit.py`.

**Section-scoped GO TO fall-through closure, gate-only (2026-08-26).** The 2026-08-25 narrowing above only helps when `find_goto_exit_plans` actually neutralizes the target, and that function's own adjacency precondition (immediately below) can only ever match ONE enclosing paragraph — so the equally idiomatic "several validation paragraphs in one SECTION each `GO TO` a shared, section-scoped exit label" shape (e.g. `2211-VALIDER-HYP-TERME`/`2212-...` both jumping to `2200-EXIT`, the section's own last paragraph) still gets declined all-or-nothing, and every case that reaches it inherited the full un-neutralized cascade — dozens to thousands of spurious `UNMOCKED_*` refusals cascading to the end of the program, seen on a real program where even the simplest test case (performing one such validation paragraph's own SECTION) failed this way. Fixed on the *gate* side only, never touching what `find_goto_exit_plans`/`find_terminator_plans` splice: `_fallthrough_safe_sections(program)` proves a SECTION is entered ONLY via `PERFORM <section-name>` — stricter than `_safe_section_entry_points` (checked here for every member paragraph, not just the first, and an internal GO TO/PERFORM between two members of the SAME section is explicitly not disqualifying, since that's the idiom itself) — and `_walk_fallthrough_from` (the shared walk `_reachable_paragraphs`/`union_executed_paragraphs` now both call, replacing their previously-duplicated inline loops) stops the moment it would cross past such a section's own last paragraph, since that exact point is where GnuCOBOL's implicit `PERFORM`-range return fires regardless of whether reached by fall-through or an internal GO TO. Guards the one remaining unsoundness this introduces (the equivalent of `find_terminator_plans`' own documented, unverified "shape 3"): a `.cut` case's PERFORM target/thru — DSL content, invisible to the whole-program AST scan — naming a section member directly instead of the section itself bypasses the `PERFORM <section-name>` guarantee, so `_paragraph_safe_section_map` excludes that section entirely for that specific caller (`_reachable_paragraphs` via its own `start`/`thru`; `union_executed_paragraphs` via every selected case's seeds, since its closure runs on the union rather than one case at a time). Because this only ever *shrinks* what the fall-through walk marks reachable, it can only reduce refusals (or correctly stop waiving a scoped warning less often), never introduce a new unmocked-boundary miss on its own. Pinned by `tests/unit/test_reachability_goto_exit_section_scoped.py`. 2026-10-27: a safe section can still be entered by falling off the end of the code before it (the section before it was not PERFORMed, e.g. a case PERFORMing NIST's OPEN-FILES, whose `GO TO CCVS1-EXIT` falls through every later section); then its end is no return point. `_exposed_sections` drops every safe section whose first paragraph a walk reached, and all three walkers (`_reachable_paragraphs`, `union_executed_paragraphs`, `_go_to_fallthrough_targets`) walk again without it -- before, lint passed and the unmocked boundaries after it ran for real (91 of 459 NIST `init` scaffolds crashed).

**Terminator planner honours the section-end stop (2026-10-16, issue #259).** The 2026-08-26 fix above was gate-only, so the two analyses disagreed: `find_terminator_plans` still built its hazard map from the stop-free `_go_to_fallthrough_targets`, and in IBM section style (a main SECTION that PERFORMs other SECTIONs and ends in GOBACK, each section's paragraphs `GO TO <section-exit>`) it refused every GOBACK with `UNSUPPORTED_TERMINATOR_LAYOUT`, naming a paragraph of the NEXT section as "reached by falling through" past the exit label. `_go_to_fallthrough_targets` now takes an optional `paragraph_safe_section` map and stops a walk at the last paragraph of the origin's safe section, exactly like `_walk_fallthrough_from`; `find_terminator_plans` builds that map per case with `_paragraph_safe_section_map(..., {perform_target, perform_thru})` (cached per entry set), so a case naming a member paragraph directly still gets the stop-free walk for that section. Its linear-time early break now compares the end index of the walk that recorded an index, since a section stop can end an earlier walk sooner. `find_goto_exit_plans` and `flow_mocks` keep the whole-program, stop-free map. Pinned by `tests/unit/test_terminators.py::test_terminator_after_a_section_scoped_go_to_exit_is_planned`.

**Closed PERFORM-range stop (2026-09-28).** The same false cascade for the CCVS / `PERFORM X THRU X-EXIT` idiom: `PERFORM BAIL-OUT THRU BAIL-OUT-EX` whose body does `GO TO BAIL-OUT-WRITE` (a member falling into BAIL-OUT-EX) walked on past BAIL-OUT-EX to the end of the program -- the committed NIST IC101A example refused an unmocked CLOSE and a SECTION-scoped STOP RUN for a case that PERFORMs one CALL test. `_closed_perform_ranges` finds ranges `(A, B)` -- every program `PERFORM A THRU B` / plain `PERFORM A`, plus the case's own driver range -- that control can only be inside while a PERFORM of exactly that range is active: every PERFORM naming a member is exactly that range, every GO TO naming a member sits inside it, no SORT/MERGE/XML procedure names a member, no referenced SECTION holds a member, no `.cut` seed names a member (except the driver range itself); any unreadable flow reference disables it. `_walk_fallthrough_from(range_of=...)` stops a walk whose ORIGIN is a member at B. The one entry route the static scan cannot rule out -- fall-through into A from the paragraph before it -- is closed dynamically in `_reachable_paragraphs`: a walk from outside a range that reaches A drops that range and every walk is redone. Gate-only (`union_executed_paragraphs` and the splicer's own hazard sets are unchanged) and shrink-only. Phantom `"."` paragraphs (the END-EXEC period nodes) are ignored by its duplicate-name check -- counting them switched the optimization off for any program with two `EXEC ... END-EXEC.` blocks (round 7: the ACCTMNT example's 2000-PROCESS-PARM-CARDS cases refused a CLOSE in 3000-FINALIZE). Pinned by `tests/unit/test_reachability_closed_perform_range.py`.

**`find_goto_exit_plans` itself now resolves a transitive top-level chain to a fixpoint, not just one target at a time (2026-08-26).** The 2026-08-26 section-scoped fix above only covers several validation paragraphs sharing ONE section-scoped exit label; a distinct, purely top-level shape survived: back-to-back paragraphs each with their OWN adjacent bare-EXIT label (`2211-VALIDER-MNT`/`2211-EXIT`, immediately followed by `2212-VALIDER-HYP-TERME`/`2212-EXIT`, `2213-...`, ..., `CAPITAL`, chaining transitively through roughly 20 paragraphs on a real program). Neutralizing `2211-EXIT`'s GO TO removes it from `_go_to_targets`, which is exactly what un-marks `2212-VALIDER-HYP-TERME` as a `_go_to_fallthrough_targets` hazard (it was only "reached by falling through past a GO TO target" because of `2211-EXIT`) — unblocking `2212`'s own GO TO in turn, and so on. But the function computed `_go_to_targets`/`_go_to_fallthrough_targets` ONCE, up front, from the raw whole-program GO TO set, then evaluated every candidate target against that same static snapshot — so the very first paragraph's still-live-at-evaluation-time GO TO made the entire chain look hazardous simultaneously, and every one of them was declined together with one "reached only by falling through" note apiece. Fixed by turning the single pass into a loop: each round narrows `_go_to_targets` (`base_go_to_targets - confirmed`) by every target CONFIRMED in an EARLIER round, re-derives `_go_to_fallthrough_targets` from that narrowed set, and re-evaluates every still-undecided candidate — repeating until a round confirms nothing new. Monotonic (confirmed targets are never revisited) and therefore terminates in at most `len(by_target)` rounds; a target that never becomes safe still gets exactly one final note, from its last-evaluated problems. Pinned by `tests/unit/test_goto_exit.py::test_find_goto_exit_plans_resolves_a_transitive_fallthrough_chain`.

**`immediately_follows` didn't tolerate a phantom `"."` paragraph between enclosing and target (2026-08-27).** cobolparser inserts an empty-artifact paragraph literally named `"."` for a bare `.` line sitting on its own between a paragraph's last statement and the next paragraph's header (a stray period, not a real code line) — `_expand_thru_range` already tolerates this ("phantom '.' members ride along; they are empty artifacts"), but `find_goto_exit_plans`'s own `immediately_follows(enclosing_name, target_name)` required `target_idx == enclosing_idx + 1` exactly, so a phantom sitting between an otherwise-adjacent `GO TO`'s enclosing paragraph and its exit-only target (e.g. `2212-VALIDER-MNT-CAPITAL` / phantom `.` / `2212-EXIT`) broke the adjacency check and cascaded into declining that target and every paragraph transitively chained after it (the 2026-08-26 fixpoint loop above narrows `_go_to_targets` only by targets it actually confirms). Fixed: `immediately_follows` now accepts any run of ONLY phantom `"."` paragraphs strictly between `enclosing_idx` and `target_idx`, not just a literal `+ 1` gap. Pinned by `tests/unit/test_goto_exit.py::test_find_goto_exit_plans_tolerates_a_phantom_paragraph_before_the_target`.

SECTION-scoped enclosing paragraphs are declined, not supported: an independent code review (same day, before Docker verification) found the first shipped version applied `EXIT SECTION` unsoundly — skipping a cleanup paragraph that followed the exit-only paragraph inside the same section, and applying the splice even in `find_terminator_plans`' own unverified "shape 3" (a `.cut` `perform_target` naming the section's first paragraph directly). The same review found the adjacency requirement above was undocumented-only in the first version, not enforced — a `PERFORM ... THRU <exit-paragraph>` range covering a real intermediate paragraph got a clean plan and a silently changed early-exit path. See [splicer](splicer.md#go-to-to-exit-paragraph-simplification) for the span-computation subtlety this feature's first implementation also got wrong (a nested GO TO needs `nested_statement_span`, not `statement_span`, or it silently swallows the enclosing `END-IF`) and `docs/2026-08-17-goto-exit-paragraph-simplification-design.md`'s two Revision notes for the full account and current verification status.

## Looped sites (`analysis/loops.py`, 2026-10-05)

`looped_paragraphs_and_statements(program)` returns the paragraphs
reachable from a looping PERFORM's target (UNTIL/VARYING/TIMES) and the
ids of statements inside a looping inline PERFORM body; `site_in_loop`
tests one `BoundarySite`. Used by the bundle scaffold (#141, #142, #145)
to decide when a call count is exact. It imports the refusal package's
`_reachability` lazily (refusal imports the generator, which imports this).

## Assertion labels and dialect risk (2026-10-04)

Two small modules feeding `mockymock report` (see [report](report.md)),
neither part of the refusal gate:

- `assertion_labels.py` -- `scan_assertion_labels(cut_text)` attaches the
  nearest `*> INTENT: ...` / `*> CHARACTERIZATION: ...` comment above each
  EXPECT/VERIFY line. A label covers lines until a blank line, the next
  label, a TESTCASE, or any other directive; `BR-\d+` ids in the note
  become `rule_ids`. `RECORDED_LABEL` is what `record_rewrite` inserts.
  Since issue #346 (2026-10-22) a label that ends before reaching any
  assertion while still at the top of its case (directly above the
  TESTCASE line, or above the MOCK blocks/setup) becomes the case's label
  and covers every assertion that has no adjacent label
  (`label_scope == "case"`); `scan_label_placement` also returns the
  labels that still cover nothing (`OrphanLabel`), which `lint` warns
  about (`ORPHAN_ASSERTION_LABEL`, `orphan_label_warnings`) and the
  report's inventory step names by line. Since 2026-10-25 a label
  separated from the TESTCASE line below it by blank lines still labels
  that case (`detached`), a label inside BEFORE-EACH is the suite's label
  (`label_scope == "suite"`, applied after the scan to every assertion
  still unlabelled), and a hook block (BEFORE-*/AFTER-* ... END-*) clears
  the current case, so an AFTER-EACH's EXPECTs are no longer counted as
  the preceding case's.
- `dialect_risk.py` -- `find_dialect_risks(ast, original_lines,
  line_map=None)` lists statements whose result can differ between
  GnuCOBOL and IBM Enterprise COBOL: HEX_LITERAL (high, a source scan of
  PROCEDURE DIVISION lines); EBCDIC/SORT/SEARCH ALL collation, sign
  overpunch, intermediate precision (COMPUTE with division/exponent),
  clock-dependent (medium); binary truncation, numeric-edited, intrinsic
  FUNCTIONs (low). `BLOCKING_SEVERITIES` (high, medium) is what keeps a
  case from L3. Heuristic by design: a finding is a place to look, not a
  proven divergence. Each risk's `paragraph` is the last paragraph OR
  section header at or above it, so a statement written directly under a
  `SECTION` header (cobol-parser's unnamed paragraph) belongs to that
  section, not to the previous section's last paragraph (issue #292).

# See Also

- [splicer](splicer.md) — consumes `BoundarySite`/`CallSite` to compute and validate replacement spans (`annotate_nested_sites` fills in `span`/`unspliceable_reason`), then emits the EVALUATE dispatch blocks; `build_driver`'s `record_targets` param and the `RECORD` marker codegen `stub_expectations.py` feeds.
- [dsl](dsl.md) — `MockCategory`, `MockDirective`, `MockTestCase` (including `perform_target`/`perform_thru`) that `refusal.py` matches sites against; the `*> STUB EXPECT` comment convention.
- [report](report.md) — `record_rewrite.py`, the stage after `stub_expectations.py` that matches a scan against a recorded run and rewrites the `.cut` file.
- [integration](integration.md) — the exact cobolparser AST fields both modules key on, and the empirically-verified facts (dynamic CALL identifier capture, OPEN/CLOSE fix requirement, numeric VALUE clause fix) this module's correctness depends on.


## DECLARATIVES under mocks (2026-11-03)

`analysis.declaratives.use_procedures(program)` reads every USE AFTER
EXCEPTION/ERROR statement of a section cobol-parser flags `is_declarative`
into `UseProcedures`: `by_file` (a USE naming the file), `by_mode` (`ON
INPUT` / `OUTPUT` / `I-O` / `EXTEND`), the FD record -> file map, and the
declarative paragraph names. `MockSurface.use_procedures` carries it.

- Which procedure applies: the file's own, else its open mode's. An OPEN
  names its mode; every other statement reads the mode the last mocked
  OPEN recorded in `UT-OPEN-MODE-<n>` (n = position of the file among the
  sorted SELECT names; declared and reset per case through
  `cli.checks.extra_working_storage` / `extra_reset_lines_for`).
- The splice (`splicer.orchestrator._with_use_procedures`) adds a lifted
  clause with guard `declaratives.USE_GUARD` (outcome not SPACES, first
  character not "0") after the statement's own clauses, so AT END /
  INVALID KEY handle "1x" / "2x" first, exactly as at run time. A file
  statement inside DECLARATIVES gets none (no re-entry).
- Reachability: `_reachable_bfs` pushes `UseProcedures.sections_for(file)`
  for every file statement of a reached paragraph.
- USE FOR DEBUGGING: never runs; test binaries get `COB_SET_DEBUG=N`.
- Exact counts: none in a program with USE procedures
  (`exact_counts.exact_count_scope` returns an empty scope; generate
  demotes every VERIFY count with `_USE_PROCEDURE_REASON`).
- A terminator inside DECLARATIVES never ends a main-line case with `GO TO
  UT-PROGRAM-END` (`_plans._main_line_end_problem`): the USE section runs
  under the splice's PERFORM, and no GO TO may leave DECLARATIVES.
