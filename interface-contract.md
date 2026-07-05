# Interface Contract: mockymock ↔ cobolparser

mockymock depends on cobolparser; cobolparser has no knowledge of mockymock.
This documents exactly which cobolparser exports mockymock relies on, so a
cobolparser change that breaks one of these is a breaking change for
mockymock too.

- `cobolparser.parse_cobol(source: str, filename: str) -> ParseResult`
  - `.ast: CobolProgram | None`, `.success: bool`, `.errors: list[ParseError]`
- `cobolparser.expand_copybooks` / `cobolparser.parse_cobol_with_expansion`
- `cobolparser.preprocess.normalize_fixed_format(lines: list[str]) -> str`
  — mockymock splices THIS output, not the original file. See Global
  Constraints in the implementation plan for why.
- `cobolparser.CobolProgram.get_division(name: str) -> CobolDivision | None`
- `cobolparser.models.program.CobolDivision.paragraphs: list[CobolParagraph]`
  and `._sections: dict[str, CobolSection]` (each section has `.paragraphs`)
- `cobolparser.models.program.CobolParagraph.paragraph_name: str`,
  `.statements: list[CobolStatement]`, `.location: SourceLocation`
- `cobolparser.models.ast_base.SourceLocation.line: int` — refers to lines
  in the NORMALIZED free-form text, not the original file.
- `cobolparser.models.statements.call.CallStatement.called_program: str | None`,
  `.is_dynamic: bool` (property), `.on_exception`/`.not_on_exception`/`.on_overflow: list[CobolStatement] | None`
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
- `cobolparser.lexer.CobolLexer(text, free_form=True)` + `TokenType.COPY` —
  `refusal.py` re-lexes the raw source to detect unresolved COPY statements
  (they leave zero trace in the AST).
- `cobolparser.analysis.DynamicCallAnalyzer().analyze(ast)`
