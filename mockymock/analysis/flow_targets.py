"""Upper-case the PERFORM / GO TO targets of a parsed program.

COBOL names are case-insensitive. cobol-parser upper-cases paragraph and
section names (`CobolParagraph.paragraph_name`, the PROCEDURE DIVISION's
`_sections` keys) but keeps a PERFORM or GO TO target as written, so in a
lowercase program `perform read-one` names `read-one` while the paragraph
is `READ-ONE`. Every name lookup in mockymock's analysis (reachability,
terminator chains, flow mocks, loops) compares the two directly, which
refused every such program. Normalizing the targets once, right after
parsing, keeps all of those lookups exact.

It also names an unnamed main line (#385): statements straight after the
PROCEDURE DIVISION header sit in a paragraph cobol-parser names `""`. The
splicer gives that code the header `UT-ORIGINAL-ENTRY` in the compiled
source, so the parsed program carries the same name and a test case can
`PERFORM UT-ORIGINAL-ENTRY` like any other paragraph.
"""

from __future__ import annotations

_FLOW_STATEMENT_TYPES = ("PerformStatement", "GoStatement")

#: The paragraph header the splicer gives a PROCEDURE DIVISION main line
#: that has no paragraph name of its own, and the name a test case uses
#: to PERFORM it.
ORIGINAL_ENTRY_PARAGRAPH = "UT-ORIGINAL-ENTRY"


def name_unnamed_main_line(program) -> bool:
    """Give the unnamed main line of *program* (a leading paragraph named
    `""` directly under the PROCEDURE DIVISION, outside any SECTION) the
    name `ORIGINAL_ENTRY_PARAGRAPH`, in place. True when it did. Left
    alone when the program already has a paragraph of that name."""
    if program is None:
        return False
    division = program.get_division("PROCEDURE")
    if division is None or not division.children:
        return False
    first = next(
        (
            c
            for c in division.children
            if type(c).__name__ in ("CobolParagraph", "CobolSection")
        ),
        None,
    )
    if first is None or type(first).__name__ != "CobolParagraph":
        return False
    if (first.paragraph_name or "").strip("."):
        return False
    # Only ENTRY statements (an IMS `ENTRY 'DLITCBL' USING ...` before the
    # first paragraph): nothing to run, so the scaffolder keeps falling
    # back to the first named paragraph (#150).
    if not any(type(c).__name__ != "EntryStatement" for c in first.children):
        return False
    for paragraph in program.find_all_by_type("CobolParagraph"):
        if (paragraph.paragraph_name or "").upper() == ORIGINAL_ENTRY_PARAGRAPH:
            return False
    first.paragraph_name = ORIGINAL_ENTRY_PARAGRAPH
    return True


def normalize_flow_targets(program) -> None:
    """Upper-case, in place, every PERFORM/GO TO target name of *program*
    (`target_paragraph`, `thru_paragraph`, `target_paragraphs`)."""
    if program is None:
        return
    name_unnamed_main_line(program)
    for type_name in _FLOW_STATEMENT_TYPES:
        for statement in program.find_all_by_type(type_name):
            for attr in ("target_paragraph", "thru_paragraph"):
                value = getattr(statement, attr, None)
                if isinstance(value, str):
                    setattr(statement, attr, value.upper())
            targets = getattr(statement, "target_paragraphs", None)
            if targets:
                statement.target_paragraphs = [
                    t.upper() if isinstance(t, str) else t for t in targets
                ]
