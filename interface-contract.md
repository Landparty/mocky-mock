# Interface Contract: mockymock ↔ cobolparser

mockymock depends on cobolparser; cobolparser has no knowledge of mockymock.
This documents exactly which cobolparser exports mockymock relies on, so a
cobolparser change that breaks one of these is a breaking change for
mockymock too.

- `cobolparser.parse_cobol(source: str, filename: str) -> ParseResult`
  - `.ast: CobolProgram | None`, `.success: bool`, `.errors: list[ParseError]`,
    `.warnings: list[str]` — since cobolparser's 2026-07-07 silent-drop
    remediation (upstream PR #77), a warning on an otherwise clean parse
    (`success=True, errors=0`) is the only signal that content was dropped
    from the AST (unsupported verbs like INVOKE/EXHIBIT, unparsed clause
    leftovers, multi-program compilation units whose extra programs land in
    `ast.contained_programs` — a place mockymock's splicer and reachability
    BFS never look). `refusal.check_whole_program` refuses per warning
    (PARSE_WARNING), fail-closed.
- `cobolparser.expand_copybooks` / `cobolparser.parse_cobol_with_expansion`
- `cobolparser.preprocess.models.ExpansionStatistics.warnings: list[str]`
  (via `CopybookExpansion.statistics`) — entries containing
  `"Lossy decode of"` mean U+FFFD replacement characters were substituted
  into the expanded source; `refusal.check_expansion_warnings` refuses those
  (EXPANSION_WARNING). The same list carries advisory lint heuristics
  ("may be missing terminating period", "contains only comments") that
  false-positive on valid copybooks and are deliberately not refused.
- `cobolparser.preprocess.normalize_fixed_format(lines: list[str]) -> str`
  — mockymock splices THIS output, not the original file. See Global
  Constraints in the implementation plan for why.
- `cobolparser.CobolProgram.get_division(name: str) -> CobolDivision | None`
- `cobolparser.models.program.CobolDivision.paragraphs: list[CobolParagraph]`
  and `._sections: dict[str, CobolSection]` (each section has `.paragraphs`,
  `.section_name`, and `.location.line` — the header line the flow-mock
  splice (`MOCK SECTION`) replaces and `collect_boundaries` treats as a span
  boundary; like paragraph locations it indexes the NORMALIZED text)
- `cobolparser.models.program.CobolParagraph.paragraph_name: str`,
  `.statements: list[CobolStatement]`, `.location: SourceLocation`
- `cobolparser.models.ast_base.SourceLocation.line: int` — refers to lines
  in the NORMALIZED free-form text, not the original file.
- `cobolparser.models.statements.call.CallStatement.called_program: str | None`,
  `.is_dynamic: bool` (property), `.on_exception`/`.not_on_exception`/`.on_overflow: list[CobolStatement] | None`
  — when `.is_dynamic` is True, `.called_program` holds the *identifier
  name* the CALL goes through (verified empirically: `CALL WS-PGM-NAME`
  yields `called_program == "WS-PGM-NAME"`); dynamic-CALL mocking keys on
  this.
- `cobolparser.models.statements.control.PerformStatement.target_paragraph: str | None`,
  `.inline_statements: list[CobolStatement]` (populated for inline `PERFORM ... END-PERFORM`)
- `cobolparser.models.statements.control.IfStatement.then_statements`/`.else_statements: list[CobolStatement]`
- `cobolparser.models.statements.control.EvaluateStatement.when_clauses: list[WhenClause]`,
  `.default_when: WhenClause | None`; `WhenClause.statements: list[CobolStatement]`
- `cobolparser.models.statements.io.*` IO statement clause bodies: `.at_end_clause`,
  `.not_at_end_clause`, `.invalid_key_clause`, `.not_invalid_key_clause`,
  `.at_eop_clause: list[CobolStatement] | None`
- `cobolparser.models.statements.io.{IOOpenStatement,IOCloseStatement,IOReadStatement,
  IOWriteStatement,IORewriteStatement,IODeleteStatement,IOStartStatement,
  IOUnlockStatement}` — `mock_surface.py` uses
  direct `isinstance` checks against these, not `cobolparser.IOLogger`
  (verified `IOLogger` doesn't detect EXEC CICS/DLI at all, so it couldn't have
  satisfied this module's requirements regardless of preference).
- `cobolparser.models.statements.misc.{SortStatement,MergeStatement,
  ReleaseStatement,ReturnStatement}` — SORT/MERGE read and write real files
  (USING/GIVING and the SD sort file); RELEASE/RETURN are the sort-file
  write/read verbs. All four are classified as file I/O by `mock_surface.py`.
- `cobolparser.models.statements.io.IOAcceptStatement.from_source: str | None`
  — `None` (plain `ACCEPT x`) or any source outside the known
  non-interactive set (DATE/DAY/DAY-OF-WEEK/TIME/COMMAND-LINE/ENVIRONMENT/
  ENVIRONMENT-VALUE/ARGUMENT-NUMBER/ARGUMENT-VALUE) is treated as console
  input and gates the UNMOCKED_CONSOLE_ACCEPT refusal, fail-closed.
- `cobolparser.models.sql_statements.ExecSQLStatement` — **not** detectable via
  `node_type` (that's hardcoded to `"Statement"` on the `CobolStatement` base
  class; the `"EXEC-SQL"` string lands in `.statement_type` instead). Detect via
  `isinstance(statement, ExecSQLStatement)`.
- `cobolparser.parsers.statements.ibm_exec_statements.ExecCicsStatement`
  (`node_type == "EXEC_CICS"`), `.ExecImsStatement` (`node_type == "EXEC_IMS"`,
  covers both EXEC IMS and EXEC DLI syntax — there is no separate `"EXEC_DLI"`
  node type). Both extend `ASTNode` directly, not `CobolStatement`, so their
  `node_type` check works, unlike `ExecSQLStatement`'s.
- `cobolparser.models.statements.control.PerformStatement.thru_paragraph: str | None`
  — a set value triggers the UNSUPPORTED_PERFORM_THRU refusal.
- `cobolparser.models.data_items.CobolDataItem.name`, `.level` (top-level
  reset targets are level 1 AND level 77), `.picture_clause: PictureClause | None`,
  `.value_clause: str | None`, `.usage`, `.children: list` — NOTE: `children`
  mixes clause nodes (e.g. `PictureClause`) with subordinate data items;
  `reset.py` treats only children carrying a `level` attribute as data items
  when deciding group vs elementary.
- `cobolparser.models.data_items.PictureClause.pattern: str`
- Requires cobolparser >= the numeric-VALUE-clause fix (upstream
  `tests/regression/test_numeric_value_clause.py`): before it, `VALUE 5`,
  `VALUE IS <n>`, and `VALUE -5` parsed as `value_clause=None`, which made
  `reset.py` silently reset to the type default instead of the declared value.
- Requires cobolparser >= the VALUE-ALL fix (upstream
  `tests/regression/test_value_all_clause.py`): before it, `VALUE ALL '='`
  parsed as `value_clause="ALL"` and dropped the literal with a content-drop
  warning, so any program using the report-separator idiom refused
  PARSE_WARNING. Now `value_clause='ALL "="'`, which `reset.py` splices as
  legal COBOL (`MOVE ALL "=" TO <item>`).
- `cobolparser.lexer.CobolLexer(text, free_form=True)` + `TokenType.COPY` —
  `refusal.py` re-lexes the raw source to detect unresolved COPY statements
  (they leave zero trace in the AST).
- `cobolparser.analysis.DynamicCallAnalyzer().analyze(ast)`
- `cobolparser.models.program.CobolProgram.get_entry_statements() -> list[EntryStatement]`
  — every `ENTRY` statement in the program; each has `.entry_name: str | None`
  and `.location.line`. Used by `analysis.linkage.linkage_plan` to detect the
  ENTRY/LINKAGE-SECTION shape `splicer.linkage` neutralizes (see
  docs/2026-07-08-ims-linkage-support-design.md).
- `cobolparser.models.program.CobolDivision._sections: dict[str, CobolSection]`
  for the **DATA** division too, not just PROCEDURE (already pinned above):
  keys observed are `"FILE"`, `"WORKING-STORAGE"`, `"LINKAGE"`; each
  `CobolSection.data_items: list[CobolDataItem]` holds that section's
  top-level (01/77) items directly (not mixed with clause nodes the way
  `.children` is). **`CobolSection.location.line` for a DATA DIVISION
  section is NOT reliable** — verified empirically it reports the enclosing
  DATA DIVISION's own line for every section, not each section's own header
  line; `analysis.linkage.linkage_plan` derives the LINKAGE SECTION header
  line as `(first LINKAGE item).location.line - 1` instead, and
  `refusal.check_linkage_layout` verifies that line textually before ever
  commenting it out.

## v2 (mock-all-boundaries) additions

- `cobolparser.models.statements.io.IOOpenStatement.file_names: list[str]`
  and `IOCloseStatement.file_names: list[str]` — OPEN/CLOSE mock keys match
  against any listed file. **Requires cobol-parser at or after PR #68**
  (`fix/open-multi-mode-file-capture`, merged to `main` 2026-07-05): before
  it, `OPEN INPUT A OUTPUT B` silently dropped every file after the second
  mode keyword, so `MOCK OPEN B` could never match.
- `IOReadStatement.file_name`, `IODeleteStatement.file_name`,
  `IOStartStatement.file_name`, `IOUnlockStatement.file_name` — file-keyed
  mock matching.
- `IOWriteStatement.record_name`, `IORewriteStatement.record_name` —
  WRITE/REWRITE mock keys name the record (matching COBOL's own syntax).
- `IOAcceptStatement.target: str | None` — `MOCK ACCEPT <target>` matching.
- `cobolparser.models.sql_statements.ExecSQLStatement.sql_text: str` —
  `MOCK SQL "<prefix>"` prefix-matches its normalized (uppercased,
  whitespace-collapsed) form.
- `ExecCicsStatement.cics_command: str` / `.cics_text: str` and
  `ExecImsStatement.ims_command: str` / `.ims_text: str` — CICS/DLI prefix
  matching runs against `f"{command} {text}"` normalized (the parser
  consumes the command token before collecting the rest, so the command is
  not repeated inside the text).
- **Phantom "." paragraphs**: cobolparser emits a paragraph literally named
  `"."` for the sentence-terminating period line after an
  `EXEC ... END-EXEC` block. `source_map.collect_boundaries` filters them
  (a boundary there would cut the EXEC statement's splice span one line
  short of its END-EXEC).
- `PerformStatement.target_paragraph` is also populated for
  `PERFORM <para> UNTIL <cond>` — the reachability BFS and the INVUPDT
  example's read loop rely on this.
