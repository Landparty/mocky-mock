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
  `.is_dynamic: bool` (property)
- `cobolparser.models.statements.control.PerformStatement.target_paragraph: str | None`
- `cobolparser.models.data_items.CobolDataItem.name`, `.level`,
  `.picture_clause: PictureClause | None`, `.value_clause: str | None`, `.usage`
- `cobolparser.models.data_items.PictureClause.pattern: str`
- `cobolparser.analysis.DynamicCallAnalyzer().analyze(ast)`
- `cobolparser.HostVariableResolver`, `cobolparser.IMSSegmentAnalyzer`,
  `cobolparser.IOLogger` — used by `mock_surface.py` to detect (not mock)
  EXEC SQL/CICS/DLI and file I/O for the refusal gate.
