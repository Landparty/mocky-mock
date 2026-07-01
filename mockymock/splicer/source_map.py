"""Statement span detection on cobolparser's normalized free-form text.

cobolparser's SourceLocation gives only a statement's start line. A
statement's span end is derived as "one line before whatever comes next":
the next statement in the same paragraph, or the next paragraph's header
if this is the last statement in its paragraph, or end-of-file if it's the
very last paragraph's last statement.
"""

from __future__ import annotations

from cobolparser.models.program import CobolDivision, CobolParagraph


def collect_boundaries(program) -> list[int]:
    """Every paragraph-header and statement-start line, sorted ascending."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return []
    lines: set[int] = set()
    for paragraph in _all_paragraphs(procedure):
        lines.add(paragraph.location.line)
        for statement in paragraph.statements:
            lines.add(statement.location.line)
    return sorted(lines)


def statement_span(statement, boundaries: list[int], last_line: int) -> tuple[int, int]:
    """Return (start_line, end_line), both 1-indexed and inclusive."""
    start = statement.location.line
    later = [b for b in boundaries if b > start]
    end = (later[0] - 1) if later else last_line
    return start, end


def _all_paragraphs(procedure_division: CobolDivision) -> list[CobolParagraph]:
    paragraphs = list(procedure_division.paragraphs)
    for section in procedure_division._sections.values():
        paragraphs.extend(section.paragraphs)
    return paragraphs
