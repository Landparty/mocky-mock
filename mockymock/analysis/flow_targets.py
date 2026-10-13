"""Upper-case the PERFORM / GO TO targets of a parsed program.

COBOL names are case-insensitive. cobol-parser upper-cases paragraph and
section names (`CobolParagraph.paragraph_name`, the PROCEDURE DIVISION's
`_sections` keys) but keeps a PERFORM or GO TO target as written, so in a
lowercase program `perform read-one` names `read-one` while the paragraph
is `READ-ONE`. Every name lookup in mockymock's analysis (reachability,
terminator chains, flow mocks, loops) compares the two directly, which
refused every such program. Normalizing the targets once, right after
parsing, keeps all of those lookups exact.
"""

from __future__ import annotations

_FLOW_STATEMENT_TYPES = ("PerformStatement", "GoStatement")


def normalize_flow_targets(program) -> None:
    """Upper-case, in place, every PERFORM/GO TO target name of *program*
    (`target_paragraph`, `thru_paragraph`, `target_paragraphs`)."""
    if program is None:
        return
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
