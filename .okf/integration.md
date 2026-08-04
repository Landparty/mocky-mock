---
type: Contract
title: cobolparser Interface Contract
description: The exact cobolparser AST surface (ParseResult, statement node fields, node_type quirks) that mockymock depends on.
tags: [integration, cobolparser, contract]
timestamp: 2026-07-09T00:00:00Z
---

# Overview

mockymock is a one-way consumer of `cobolparser`: mockymock depends on cobolparser,
cobolparser has zero knowledge of mockymock. Day-to-day contributor setup still
installs cobolparser separately, editable, from the sibling `cobol-parser`
repo (`requirements-dev.txt`: `-e ../cobol-parser`) per workspace convention —
that checkout, whatever commit it's on, always wins in a dev environment.
`pyproject.toml`'s `dependencies` now also carries a pinned git reference
(`cobolparser @ git+https://github.com/Landparty/cobol-parser.git@<sha>`, kept
in sync with `.github/workflows/ci.yml`'s `ref:`), added so `uv tool install`
can resolve a working install with no sibling checkout present (see README
"Install"). That pin is a floor for non-dev installs, not a substitute for
the interface contract below — any change to a symbol below is still a
breaking change for this repo even though the pin only catches it once
re-bumped.

**Two kinds of dependency, since Phase 8 of the gen-fixtures initiative**:
this file's table below covers the low-level AST surface `mock_surface.py`
/ `refusal.py` / `reset.py` / the splicer walk directly (statement classes,
`ParseResult`, division/paragraph structure). `generate --with-data`
(`dsl/generator.py`'s bundle-driven scaffold, `dsl/fixture_bundle.py`'s
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
| `cobolparser.expand_copybooks` / `parse_cobol_with_expansion` | copybook-expanded parse path |
| `cobolparser.preprocess.normalize_fixed_format(lines) -> str` | **splicer input** — see Gotchas |
| `CobolProgram.get_division(name)` → `CobolDivision` | division lookup |
| `CobolDivision.paragraphs` / `._sections: dict[str, CobolSection]` | paragraph enumeration (sections also have `.paragraphs`) |
| `CobolParagraph.paragraph_name`, `.statements`, `.location.line` | reachability graph, splice targeting |
| `CallStatement.called_program: str \| None`, `.is_dynamic` (property) | dynamic-CALL mocking keys on `called_program` when `is_dynamic` |
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
| `DynamicCallAnalyzer().analyze(ast)` | dynamic-call resolution feeding refusal/mock analysis |
| (v2) `IOOpenStatement.file_names` / `IOCloseStatement.file_names` | multi-file OPEN/CLOSE mock key matching |
| (v2) `IOReadStatement.file_name`, `IODeleteStatement.file_name`, `IOStartStatement.file_name`, `IOUnlockStatement.file_name` | file-keyed mock matching |
| (v2) `IOWriteStatement.record_name`, `IORewriteStatement.record_name` | record-keyed mock matching (mirrors COBOL's own WRITE/REWRITE syntax) |
| `CobolProgram.get_entry_statements() -> list[EntryStatement]` | `analysis.linkage.linkage_plan` detects the ENTRY/LINKAGE-SECTION shape `splicer.linkage` neutralizes; each has `.entry_name`, `.location.line` |
| `CobolDivision._sections["LINKAGE"].data_items` (DATA division) | non-empty LINKAGE SECTION detection; same `._sections` access `reset.py` already uses for WORKING-STORAGE, generalized to DATA-division sections other than WORKING-STORAGE |

# Gotchas

**Splicer operates on `normalize_fixed_format`'s OUTPUT, not the original file.** Every `SourceLocation.line` (and thus every splice point mockymock computes) refers to line numbers in the *normalized free-form text* cobolparser produces, not the programmer's original source file. Any code path that maps a splice back to disk must go through the same normalization, never re-derive offsets from the raw file. See [splicer](splicer.md).

**`ExecSQLStatement` is not detectable via `node_type`.** `node_type` is hardcoded to `"Statement"` on the `CobolStatement` base class, and the `"EXEC-SQL"` string lands in `.statement_type` instead. Detection must be `isinstance(statement, ExecSQLStatement)`. By contrast `ExecCicsStatement` (`node_type == "EXEC_CICS"`) and `ExecImsStatement` (`node_type == "EXEC_IMS"`, covering *both* EXEC IMS and EXEC DLI — there is no separate `"EXEC_DLI"` node type) extend `ASTNode` directly rather than `CobolStatement`, so their `node_type` check does work. Three EXEC dialects, three different detection idioms — see [analysis](analysis.md) / `mock_surface.py`.

**`IOLogger` was considered and rejected.** `mock_surface.py` uses direct `isinstance` checks against the `IOOpenStatement`/`IOCloseStatement`/etc. classes instead of `cobolparser.IOLogger`, because `IOLogger` doesn't detect EXEC CICS/DLI at all — it structurally could not have satisfied mockymock's IO-boundary requirements.

**Phantom `"."` paragraphs after `EXEC ... END-EXEC`.** cobolparser emits a paragraph literally named `"."` for the sentence-terminating period line following an EXEC block. `source_map.collect_boundaries` must filter these out — treating one as a real boundary would cut the EXEC statement's splice span one line short of its `END-EXEC`.

**`PerformStatement.thru_paragraph` gates a refusal.** A non-null `thru_paragraph` used to trigger `UNSUPPORTED_PERFORM_THRU` unconditionally; this has since been narrowed to degenerate ranges only (see `mocky-mock` git history: "range-expand PERFORM THRU in reachability"). `target_paragraph` is also populated for `PERFORM <para> UNTIL <cond>` loop form — the reachability BFS and the INVUPDT read-loop example depend on that.

**`ACCEPT` fail-closed console-input gate.** `IOAcceptStatement.from_source` of `None` (plain `ACCEPT x`) or any source string outside the known non-interactive allowlist (`DATE`, `DAY`, `DAY-OF-WEEK`, `TIME`, `COMMAND-LINE`, `ENVIRONMENT`, `ENVIRONMENT-VALUE`, `ARGUMENT-NUMBER`, `ARGUMENT-VALUE`) is treated as interactive console input and gates the `UNMOCKED_CONSOLE_ACCEPT` refusal — fail-closed by design, not an oversight.

**`CobolDataItem.children` mixes clause nodes with data items.** It holds both subordinate `CobolDataItem`s and clause nodes like `PictureClause` in the same list. `reset.py` disambiguates by checking for a `.level` attribute — only nodes carrying one are treated as data items when deciding group vs. elementary reset behavior. Top-level reset targets are level 1 **and** level 77.

**Upstream numeric-VALUE-clause bug (now fixed, version-gated).** Before cobolparser's numeric-VALUE-clause fix (pinned by upstream `tests/regression/test_numeric_value_clause.py`), `VALUE 5`, `VALUE IS <n>`, and `VALUE -5` all parsed with `value_clause=None`. This silently made `reset.py` fall back to the type default instead of the declared VALUE — mockymock requires a cobolparser build at or after that fix.

**v2 OPEN/CLOSE multi-file capture bug (fixed upstream, version-gated).** Before cobol-parser PR #68 (`fix/open-multi-mode-file-capture`, merged to `main` 2026-07-05), `OPEN INPUT A OUTPUT B` silently dropped every file listed after the second mode keyword, so `MOCK OPEN B` could never match. `IOOpenStatement.file_names`/`IOCloseStatement.file_names` matching requires a cobolparser build at or after that merge.

**`CobolSection.location.line` is unreliable for a DATA DIVISION section.** Verified empirically: every section under one DATA DIVISION (`FILE`/`WORKING-STORAGE`/`LINKAGE`) reports that DIVISION's own line, not its own header line — unlike PROCEDURE DIVISION's `_sections`, which do report correct per-section header lines (`source_map.collect_boundaries` depends on that). `analysis.linkage.linkage_plan` works around this by deriving the LINKAGE SECTION header line as `(first LINKAGE item).location.line - 1`, and `refusal.check_linkage_layout` verifies that line's text before ever commenting it out.

**`ParseResult.warnings` is a dropped-content signal, not advice (cobolparser ≥ the 2026-07-07 silent-drop remediation, PR #77).** A "clean" parse (`success=True, errors=0`) can still be missing statements: unsupported verbs (INVOKE, EXHIBIT, ...), unparsed clause leftovers, and multi-program compilation units (everything after the first `END PROGRAM` lands in `ast.contained_programs`, which the splicer and reachability BFS never look at) are reported ONLY through `.warnings`. `check_whole_program` therefore refuses per warning (PARSE_WARNING). Known upstream residual: an unknown verb directly following a period-less statement (e.g. `MOVE 1 TO X` newline `INVOKE ...`) can still be swallowed by the preceding statement's parser with no warning — period-terminated statements (the normal layout) are covered.

**The git pin is currently an interim branch pin, not a `main` commit.** As of the gen-fixtures initiative's Phase 8, `pyproject.toml`/`ci.yml` pin cobol-parser's `claude/data-generation-function-k2mbbj` branch (an exact commit SHA on it, not the branch name) because `generate --with-data` depends on that branch's `ProgramLayoutIndex`/`BoundaryInventoryAnalyzer`/`ProgramFixtureGenerator`/`ConstraintExtractor`/`ScenarioPlanner`/expectations work end to end, none of which is on cobol-parser `main` yet (see cobol-parser PR #108). Re-bump to a `main` commit once that PR merges — do not treat the branch pin as a long-term arrangement.

**cobol-parser's `expand_copybooks` does not resolve DCLGEN-style `EXEC SQL INCLUDE <member> END-EXEC`.** Only plain `COPY <member>` is expanded; an `EXEC SQL INCLUDE` member (e.g. `examples/custprog/copybooks/CUSTREC.CPY`) is left untouched in cobol-parser's own parse, so any host variable it declares never becomes a real `CobolDataItem` in cobol-parser's AST. `ProgramFixtureGenerator` correctly reports the gap via `bundle.unresolved` rather than guessing, but this means a boundary whose only host variables live in such an include (custprog's SQL FETCH) is silently absent from the bundle entirely — it never gets a fixture *or* an expectation, so it cannot even be *detected* as unresolved by scanning the bundle's own `unresolved` list keyed by boundary; only the free-text reason string says so. mockymock's own splicer resolves this same construct independently, via its own copybook-path search purely for compiling test runs (`splicer/sqlca.py`) — the two tools' preprocessing pipelines are not unified here, which is exactly why `test_fixture_bundle_contract.py` carries one documented `xfail` for `custprog`.

# See Also
- [analysis](analysis.md)
- [splicer](splicer.md)

# Citations
- [../interface-contract.md](../interface-contract.md) — canonical, line-by-line interface contract this concept summarizes.
