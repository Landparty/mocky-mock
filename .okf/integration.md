---
type: Contract
title: cobolparser Interface Contract
description: The exact cobolparser AST surface (ParseResult, statement node fields, node_type quirks) that mockymock depends on.
tags: [integration, cobolparser, contract]
timestamp: 2026-10-04T00:00:00Z
---

# Overview

mockymock is a one-way consumer of `cobolparser`: mockymock depends on cobolparser,
cobolparser has zero knowledge of mockymock. Since cobol-parser started
publishing to PyPI as `cobol-parser` (see [publishing.md](publishing.md);
first as closed-source wheels, source-visible since its 2026-10-03
relicense to AGPL-3.0-or-later),
`cobolparser` resolves as an ordinary versioned PyPI dependency
(`pyproject.toml`'s `dependencies`: currently `cobol-parser>=3.1.1,<4`) — no sibling
checkout, no separate CI cross-repo checkout step, one place to bump. That
pin is a floor, not a substitute for the interface contract below — any
change to a symbol below is still a breaking change for this repo even
though the pin only catches it once re-bumped. A local editable sibling
checkout (`pip install -e ../cobol-parser`) still works for day-to-day
cobol-parser development that needs to be exercised against mockymock
before its own release ships, but is no longer required or documented as
the default setup.

**Two kinds of dependency, since Phase 8 of the gen-fixtures initiative**:
this file's table below covers the low-level AST surface `mock_surface.py`
/ `refusal.py` / `reset.py` / the splicer walk directly (statement classes,
`ParseResult`, division/paragraph structure). `generate --with-data`
(`dsl/generator/`'s bundle-driven scaffold, `dsl/fixture_bundle.py`'s
loader) depends on a *different*, higher-level surface instead: cobol-parser's
`ProgramFixtureGenerator.generate_with_scenarios_from_file(...)` (called
directly, no subprocess) and the JSON shape of the `FixtureBundle` it
returns. mockymock deliberately never imports cobol-parser's `FixtureBundle`/
`Scenario`/`BoundaryFixture` *classes* — only `.to_dict()`'s JSON, re-parsed
into mockymock-local dataclasses by `fixture_bundle.py` — so the contract is
the serialized form, documented in cobol-parser's own
`docs/fixture-bundle-schema.md`, not repeated here. See `dsl.md`'s
"Bundle-driven scaffold" section for how mockymock consumes it.

```
cobolparser.parse_cobol(source, filename) -> ParseResult
        │
        ├─ .ast: CobolProgram | None ── .get_division(name) -> CobolDivision | None
        │                                     │
        │                                     ├─ .paragraphs: list[CobolParagraph]
        │                                     └─ ._sections: dict[str, CobolSection]
        │                                            └─ .paragraphs
        │
        ├─ .success: bool
        ├─ .errors: list[ParseError]
        └─ .warnings: list[str]   ── dropped-content signal (refused fail-closed)

CobolParagraph.paragraph_name / .statements / .location(SourceLocation.line)
        └─ statements are CobolStatement subclasses inspected by mock_surface.py / refusal.py
```

# Public API Surface Depended On

| Symbol | mockymock use |
|---|---|
| `cobolparser.parse_cobol(source, filename) -> ParseResult` | entry point; `.ast`, `.success`, `.errors`, `.warnings` (PARSE_WARNING refusal per entry — see Gotchas) |
| `CopybookExpansion.statistics.warnings: list[str]` | lossy-decode entries (`"Lossy decode of"`) gate the EXPANSION_WARNING refusal; advisory lint entries in the same list are ignored |
| `cobolparser.preprocess.expand_copybooks` (+ `CopybookNotFoundError`) | copybook-expanded parse path (mockymock expands, then calls `parse_cobol` itself; it never calls `parse_cobol_with_expansion`) |
| `cobolparser.preprocess.strip_compiler_directives(raw_source)` | `run_static_checks` / `generate` strip leading `PROCESS`/`CBL` compiler-option cards (line numbers preserved) before splitting source lines |
| `cobolparser.preprocess.normalize_fixed_format(lines) -> str` | **splicer input** — see Gotchas |
| `CobolProgram.get_division(name)` → `CobolDivision` | division lookup |
| `CobolDivision.paragraphs` / `._sections: dict[str, CobolSection]` | paragraph enumeration (sections also have `.paragraphs`) |
| `CobolParagraph.paragraph_name`, `.statements`, `.location.line` | reachability graph, splice targeting |
| `CallStatement.called_program: str \| None`, `.is_dynamic` (property) | dynamic-CALL mocking keys on `called_program` when `is_dynamic` |
| `CallStatement.using_parameters: list[CallParameter]`, `CallParameter.name: str` | `CAPTURE ARG <n> INTO <target>` resolves `<n>` against this list (1-based) at splice time, for both static CALL and DYNCALL sites |
| `CallStatement.on_exception` / `.not_on_exception` / `.on_overflow` | exception-branch statement lists |
| `PerformStatement.target_paragraph`, `.thru_paragraph`, `.inline_statements` | reachability BFS; THRU triggers a refusal (see Gotchas) |
| `IfStatement.then_statements` / `.else_statements` | branch traversal |
| `EvaluateStatement.when_clauses`, `.default_when`; `WhenClause.statements` | branch traversal |
| IO clause bodies: `.at_end_clause`, `.not_at_end_clause`, `.invalid_key_clause`, `.not_invalid_key_clause`, `.at_eop_clause` | branch traversal into IO fallback paths |
| `IOOpenStatement`, `IOCloseStatement`, `IOReadStatement`, `IOWriteStatement`, `IORewriteStatement`, `IODeleteStatement`, `IOStartStatement`, `IOUnlockStatement` | `mock_surface.py` does direct `isinstance` checks (not `cobolparser.IOLogger` — see Gotchas) |
| `SortStatement`, `MergeStatement`, `ReleaseStatement`, `ReturnStatement` | classified as file I/O by `mock_surface.py` (SORT/MERGE touch real USING/GIVING/SD files; RELEASE/RETURN are the sort-file write/read verbs) |
| `IOAcceptStatement.from_source`, `.target` | console-input detection, `MOCK ACCEPT` target matching |
| `ExecSQLStatement.sql_text` | `MOCK SQL "<prefix>"` matching (normalized: uppercased, whitespace-collapsed) |
| `ExecCicsStatement.cics_command`/`.cics_text`, `ExecImsStatement.ims_command`/`.ims_text` | CICS/DLI prefix matching against `f"{command} {text}"` |
| `CobolDataItem.name`, `.level`, `.picture_clause`, `.value_clause`, `.usage`, `.children` | `reset.py` VALUE-clause resets |
| `PictureClause.pattern` | reset default-value derivation |
| `CobolLexer(text, free_form=True)` + `TokenType.COPY` | `refusal.py` re-lexes raw source to catch unresolved COPY (invisible to the AST) |
| `cobolparser.analysis.unused_variables.collect_declared_items(program)` | declared-name set for the CICS EIB check (`analysis/cics_eib.py`) and the matching gate in `refusal/_gates.py` |
| `cobolparser.generators.data.layout_offsets.compute_program_data_items(program)` | per-item layout facts (usage, length) behind `CAPTURE` source checks and `UT-CAP-` target sizing (`splicer/captures.py`) |
| `cobolparser.generators.ProgramFixtureGenerator`, `DataGeneratorOptions` | `generate --with-data` / `fixtures` (serialized `FixtureBundle` JSON only -- see Overview) |
| `cobolparser.analysis.value_tracker.DynamicCallAnalyzer().analyze(program)` → `CallStatement.possible_values`, metadata `possible_values_incomplete` | the program names a dynamic CALL's identifier can hold, which `generate` branches the `MOCK CALL <identifier>` body on (`generator._dynamic_call_targets`) |
| `ProgramLayoutIndex.from_file`, `BoundaryInventoryAnalyzer().analyze(ast, index)` (`Boundary.call_args[].name/.direction/.provenance`), `generators.data.layout.flatten_record`, `generators.data.values.ValueFactory` | `dsl/call_arguments.py` lays out a CALL argument the fixture bundle reported unresolvable (see [cli](cli.md)) |
| `cobolparser.config.load_project_config`, `ConfigError` | the universal `cobol.yml` (soft-imported in `cli/config.py`; absent from every tagged release up to v1.9.0 -- see [cli](cli.md)) |
| `cobolparser.cli.parse.main` | `mockymock analyze` delegates in-process, `sys.argv` patched around the call |
| (v2) `IOOpenStatement.file_names` / `IOCloseStatement.file_names` | multi-file OPEN/CLOSE mock key matching |
| (v2) `IOReadStatement.file_name`, `IODeleteStatement.file_name`, `IOStartStatement.file_name`, `IOUnlockStatement.file_name` | file-keyed mock matching |
| (v2) `IOWriteStatement.record_name`, `IORewriteStatement.record_name` | record-keyed mock matching (mirrors COBOL's own WRITE/REWRITE syntax) |
| `CobolProgram.get_entry_statements() -> list[EntryStatement]` | `analysis.linkage.linkage_plan` detects the ENTRY/LINKAGE-SECTION shape `splicer.linkage` neutralizes; each has `.entry_name`, `.location.line` |
| `InitiateStatement.report_names` / `TerminateStatement.report_names` / `GenerateStatement.report_name` (cobol-parser ≥ the 2026-09-02 verb-coverage release; imported via `mock_surface._optional_statement_types`, absent = not classified) | Report Writer mock keys |
| `InvokeStatement.object_name` / `.method_name`, `ChainStatement.program`, `SendStatement`/`ReceiveStatement`/`EnableStatement`/`DisableStatement`/`PurgeStatement.cd_name`, `ReceiveStatement.no_data_clause` / `.with_data_clause`, `StopStatement.stop_type` (`"RUN"` or the operand text) | detected-unmockable sites (fail-closed refusals) -- see [analysis](analysis.md) |
| `XmlJsonStatement.action`, `.processing_procedure`, `.processing_procedure_thru`, `.on_exception` / `.not_on_exception`, `.clause_text` | XML PARSE flow edge in the reachability BFS and handler-body walking; `clause_text` is only read to fail closed when the structured fields are absent |
| every `CobolStatement` subclass NAME (`type(statement).__name__`) | `mock_surface._PASSTHROUGH_STATEMENT_NAMES` -- the by-name allowlist behind the `UNSUPPORTED_STATEMENT` catch-all; a renamed node class shows up as a refusal, never as a silent pass |
| `CobolDivision._sections["LINKAGE"].data_items` (DATA division) | non-empty LINKAGE SECTION detection; same `._sections` access `reset.py` already uses for WORKING-STORAGE, generalized to DATA-division sections other than WORKING-STORAGE |

# Gotchas

**Splicer operates on `normalize_fixed_format`'s OUTPUT, not the original file.** Every `SourceLocation.line` (and thus every splice point mockymock computes) refers to line numbers in the *normalized free-form text* cobolparser produces, not the programmer's original source file. Any code path that maps a splice back to disk must go through the same normalization, never re-derive offsets from the raw file. See [splicer](splicer.md).

**`ExecSQLStatement` is not detectable via `node_type`.** `node_type` is hardcoded to `"Statement"` on the `CobolStatement` base class, and the `"EXEC-SQL"` string lands in `.statement_type` instead. Detection must be `isinstance(statement, ExecSQLStatement)`. By contrast `ExecCicsStatement` (`node_type == "EXEC_CICS"`) and `ExecImsStatement` (`node_type == "EXEC_IMS"`, covering *both* EXEC IMS and EXEC DLI — there is no separate `"EXEC_DLI"` node type) keep their own `node_type`, so that check does work. (They extended `ASTNode` directly in older releases; current cobol-parser makes them `CobolStatement` subclasses with the same `node_type`, so `get_all_statements()` returns them too. mockymock uses `isinstance` for all three, which works either way.) Three EXEC dialects, three different detection idioms — see [analysis](analysis.md) / `mock_surface.py`.

**`IOLogger` was considered and rejected.** `mock_surface.py` uses direct `isinstance` checks against the `IOOpenStatement`/`IOCloseStatement`/etc. classes instead of `cobolparser.IOLogger`, because `IOLogger` doesn't detect EXEC CICS/DLI at all — it structurally could not have satisfied mockymock's IO-boundary requirements.

**Phantom `"."` paragraphs after `EXEC ... END-EXEC`.** cobolparser emits a paragraph literally named `"."` for the sentence-terminating period line following an EXEC block. `source_map.collect_boundaries` must filter these out — treating one as a real boundary would cut the EXEC statement's splice span one line short of its `END-EXEC`.

**`PerformStatement.thru_paragraph` gates a refusal.** A non-null `thru_paragraph` used to trigger `UNSUPPORTED_PERFORM_THRU` unconditionally; this has since been narrowed to degenerate ranges only (see `mocky-mock` git history: "range-expand PERFORM THRU in reachability"). `target_paragraph` is also populated for `PERFORM <para> UNTIL <cond>` loop form — the reachability BFS and the INVUPDT read-loop example depend on that.

**`ACCEPT` fail-closed console-input gate.** `IOAcceptStatement.from_source` of `None` (plain `ACCEPT x`) or any source string outside the known non-interactive allowlist (`DATE`, `DAY`, `DAY-OF-WEEK`, `TIME`, `COMMAND-LINE`, `ENVIRONMENT`, `ENVIRONMENT-VALUE`, `ARGUMENT-NUMBER`, `ARGUMENT-VALUE`) is treated as interactive console input and gates the `UNMOCKED_CONSOLE_ACCEPT` refusal — fail-closed by design, not an oversight.

**`CobolDataItem.children` mixes clause nodes with data items.** It holds both subordinate `CobolDataItem`s and clause nodes like `PictureClause` in the same list. `reset.py` disambiguates by checking for a `.level` attribute — only nodes carrying one are treated as data items when deciding group vs. elementary reset behavior. Top-level reset targets are level 1 **and** level 77.

**Upstream numeric-VALUE-clause bug (now fixed, version-gated).** Before cobolparser's numeric-VALUE-clause fix (pinned by upstream `tests/regression/test_numeric_value_clause.py`), `VALUE 5`, `VALUE IS <n>`, and `VALUE -5` all parsed with `value_clause=None`. This silently made `reset.py` fall back to the type default instead of the declared VALUE — mockymock requires a cobolparser build at or after that fix.

**v2 OPEN/CLOSE multi-file capture bug (fixed upstream, version-gated).** Before cobol-parser PR #68 (`fix/open-multi-mode-file-capture`, merged to `main` 2026-07-05), `OPEN INPUT A OUTPUT B` silently dropped every file listed after the second mode keyword, so `MOCK OPEN B` could never match. `IOOpenStatement.file_names`/`IOCloseStatement.file_names` matching requires a cobolparser build at or after that merge.

**`CobolSection.location.line` is unreliable for a DATA DIVISION section.** Verified empirically: every section under one DATA DIVISION (`FILE`/`WORKING-STORAGE`/`LINKAGE`) reports that DIVISION's own line, not its own header line — unlike PROCEDURE DIVISION's `_sections`, which do report correct per-section header lines (`source_map.collect_boundaries` depends on that). `analysis.linkage.linkage_plan` works around this by deriving the LINKAGE SECTION header line as `(first LINKAGE item).location.line - 1`, and `refusal.check_linkage_layout` verifies that line's text before ever commenting it out.

**`ParseResult.warnings` is a dropped-content signal, not advice (cobolparser ≥ the 2026-07-07 silent-drop remediation, PR #77).** A "clean" parse (`success=True, errors=0`) can still be missing statements: unsupported verbs (INVOKE, EXHIBIT, ...), unparsed clause leftovers, and multi-program compilation units (everything after the first `END PROGRAM` lands in `ast.contained_programs`, which the splicer and reachability BFS never look at) are reported ONLY through `.warnings`. `check_whole_program` therefore refuses per warning (PARSE_WARNING). Known upstream residual: an unknown verb directly following a period-less statement (e.g. `MOVE 1 TO X` newline `INVOKE ...`) can still be swallowed by the preceding statement's parser with no warning — period-terminated statements (the normal layout) are covered.

**Every warning is dropped content, so an upstream verb gaining a parser moves the burden here (2026-09-02).** cobol-parser's statement-coverage release turned 22 warned-and-discarded verbs into real nodes. Each of those used to be refused by `PARSE_WARNING`; once they parse cleanly, only `mock_surface`'s classification stands between an external dependency and a silent `[PASS]`. `mock_surface` is now closed over statement type (see [analysis](analysis.md), "Fail-closed over statement types"); when cobol-parser adds a node class, mockymock refuses it as `UNSUPPORTED_STATEMENT` until someone classifies it -- the safe direction.

**REPORT SECTION.** Releases before 2026-09-02 skip it with a "REPORT SECTION ... is not supported" warning, so every Report Writer program refuses `PARSE_WARNING` and the `INITIATE`/`GENERATE`/`TERMINATE` categories can never fire on them; from that release on the section parses (RD clauses and report groups as `CobolDataItem`s under a `CobolSection("REPORT")`, with `metadata["rd_report_name"]`/`["rd_clauses"]`/`["report_clauses"]`). `reset.py` only resets WORKING-STORAGE, so report groups are never reset.

**cobol-parser's `expand_copybooks` does not resolve DCLGEN-style `EXEC SQL INCLUDE <member> END-EXEC`.** Only plain `COPY <member>` is expanded; an `EXEC SQL INCLUDE` member (e.g. `examples/custprog/copybooks/CUSTREC.CPY`) is left untouched in cobol-parser's own parse, so any host variable it declares never becomes a real `CobolDataItem` in cobol-parser's AST. `ProgramFixtureGenerator` correctly reports the gap via `bundle.unresolved` rather than guessing, but this means a boundary whose only host variables live in such an include (custprog's SQL FETCH) is silently absent from the bundle entirely — it never gets a fixture *or* an expectation, so it cannot even be *detected* as unresolved by scanning the bundle's own `unresolved` list keyed by boundary; only the free-text reason string says so. mockymock's own splicer resolves this same construct independently, via its own copybook-path search purely for compiling test runs (`splicer/sqlca.py`) — the two tools' preprocessing pipelines are not unified here, which is exactly why `test_fixture_bundle_contract.py` carries one documented `xfail` for `custprog`.

**The floor is the oldest release CI runs, and nothing below it is shimmed (2026-11-07).** Until 3.1.1 the floor sat at 1.7.7 while every environment (lockfile, CI, local) installed the newest release, so 14 `ImportError`/`AttributeError` fallbacks (`mock_surface._optional_statement_types`, `config._universal_values`, `_lines.PARSER_SPLITS_ON_RECORD_DELIMITERS`, `test_report`'s `LEADING_SENTENCES_NODE`/`BusinessRuleExtractor`) carried code paths nothing exercised. The 2026-11-06 tech-debt audit (`docs/2026-11-06-tech-debt-audit.md`, item 2) raised the floor to the locked version and deleted them. The nightly `cobol-parser-range` CI job now runs the unit tier at both ends of the range (`COBOL_PARSER_FLOOR` in `ci.yml` must match `pyproject.toml`). Capability probes in tests remain only for behavior that is newer than *any* published release (screen DISPLAY, file-status scenario families, OPEN modes on statement sites) -- they skip on PyPI and run against cobol-parser `main`.

Review history kept from the old `pyproject.toml` comment: 1.8.2's wheel raised "Expected type, got ABCMeta" from `BoundaryInventoryAnalyzer._classify` (1.8.0/1.8.4 fine); 2.x reviewed 2026-10-14 and 3.0 on 2026-10-15 (its only breaking change, the `decode --view` column set, is unused here); 3.1 (2026-10-29) made the bundle's tier-1 `call_count` one per (category, key) and only when exact (cobol-parser #363, handled by `generate`'s `_with_site_call_counts`), kept quotes on literal CALL USING arguments (`injector.reported_literal`), and stopped stubbing entry parameters set only through their 88s (`add_entry_parameters` tops them up).

# See Also
- [analysis](analysis.md)
- [splicer](splicer.md)

# Citations
- [../interface-contract.md](../interface-contract.md) — canonical, line-by-line interface contract this concept summarizes.
