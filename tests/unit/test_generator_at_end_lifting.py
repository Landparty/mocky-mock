"""A scaffolded `MOCK READ`'s exhaustion branch carries the program's own
`AT END` imperative, lifted verbatim.

The splicer replaces the WHOLE `READ` statement, which deletes its `AT END`
clause with it. A generated mock that moves only the FILE STATUS field
therefore never runs the program's own end-of-data handling, and a
`PERFORM ... UNTIL <eof-flag>` loop keyed on that handling spins until the
executor timeout -- a 30-second hang with no diagnosis.

`_replicated_at_end_statements` covers the two idioms it can prove safe from
the AST (a literal-sourced MOVE, a constant-valued SET). Everything else used
to become a `*> TODO` comment, which is not a visible gap so much as a
silently hanging test. The lifted text closes that: it is a slice of the
program's own source -- exactly the text the splice is about to delete --
rather than a re-render limited to the shapes an AST walk knows about.

Since issue #209 the splice itself re-runs a READ's clause bodies whenever
it can lift them exactly (`analysis.clause_bodies`), and the scaffold then
only reports end of file. The copying covered here is the fallback for a
clause the splice cannot lift; the `splice_cannot_lift` fixture stands in
for one.
"""

import pytest
from cobolparser import parse_cobol
from cobolparser.generators import ProgramFixtureGenerator
from cobolparser.generators.data.options import DataGeneratorOptions

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.fixture_bundle import load_fixture_bundle
from mockymock.dsl.generator import (
    ProgramContext,
    _extract_at_end_imperative,
    scaffold_cut,
)
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

# An AT END clause the AST-driven replication cannot touch: an
# identifier-sourced MOVE (not a literal) followed by an ADD.
IDENTIFIER_AT_END_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RDLOOP.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INV-FILE ASSIGN TO "INV.DAT".

       DATA DIVISION.
       FILE SECTION.
       FD  INV-FILE.
       01  INV-REC.
           05  INV-QTY        PIC 9(4).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG        PIC X VALUE "N".
       01  WS-END-MARKER      PIC X VALUE "Y".
       01  WS-TOTAL           PIC 9(6) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT INV-FILE
           PERFORM READ-ONE UNTIL WS-EOF-FLAG = "Y"
           CLOSE INV-FILE.

       READ-ONE.
           READ INV-FILE
               AT END
                   MOVE WS-END-MARKER TO WS-EOF-FLAG
                   ADD 1 TO WS-TOTAL
           END-READ.
"""


@pytest.fixture
def splice_cannot_lift(monkeypatch):
    import mockymock.dsl.generator as generator

    monkeypatch.setattr(generator, "lift_clause_bodies", lambda *_: None)


def _scaffold(source: str, name: str, rows: int = 3, with_source: bool = True) -> str:
    from cobolparser.preprocess import normalize_fixed_format

    result = parse_cobol(source, filename=name)
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
    from cobolparser.generators.data.program_layout import ProgramLayoutIndex

    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    bundle = load_fixture_bundle(
        ProgramFixtureGenerator(DataGeneratorOptions(rows=rows))
        .generate(result.ast, index, report, seed=7)
        .to_dict()
    )
    context = ProgramContext.build(result.ast, lines, surface) if with_source else None
    return scaffold_cut(result.ast.program_name, surface, bundle, frozenset(), context)


def test_when_other_carries_the_programs_own_at_end_statements(splice_cannot_lift):
    text = _scaffold(IDENTIFIER_AT_END_SOURCE, "rdloop.cbl")
    assert "WHEN OTHER" in text
    assert "MOVE WS-END-MARKER TO WS-EOF-FLAG" in text
    assert "ADD 1 TO WS-TOTAL" in text
    assert "TODO" not in text


def test_the_lifted_text_says_where_it_came_from(splice_cannot_lift):
    """A generated file a human reads should not silently contain code it
    did not derive from the fixture data."""
    text = _scaffold(IDENTIFIER_AT_END_SOURCE, "rdloop.cbl")
    assert "replicated verbatim from this program's own READ ... AT END" in text
    assert "(line 27)" in text


def test_the_generated_cut_still_parses_and_lints_clean(splice_cannot_lift):
    from mockymock.analysis.refusal import check_test_case

    text = _scaffold(IDENTIFIER_AT_END_SOURCE, "rdloop.cbl")
    result = parse_cobol(IDENTIFIER_AT_END_SOURCE, filename="rdloop.cbl")
    surface = analyze(result.ast)
    suite = parse_cut(text)
    for case in suite.test_cases:
        assert check_test_case(surface, result.ast, case) == [], case.name


def test_without_a_source_context_the_todo_comment_is_still_emitted(splice_cannot_lift):
    """The lift is an enhancement layered on the existing behavior, not a
    replacement -- a caller that cannot supply the program text still gets
    the honest TODO rather than an empty exhaustion branch."""
    text = _scaffold(IDENTIFIER_AT_END_SOURCE, "rdloop.cbl", with_source=False)
    assert "TODO: this program's AT END clause could not be auto-replicated" in text
    assert "MOVE WS-END-MARKER TO WS-EOF-FLAG" not in text


def test_ast_replication_still_wins_where_it_applies(splice_cannot_lift):
    """The proven AST path is unchanged: a literal-sourced MOVE is still
    replicated from the AST, with no lifted-text comment attached."""
    source = IDENTIFIER_AT_END_SOURCE.replace(
        "                   MOVE WS-END-MARKER TO WS-EOF-FLAG\n"
        "                   ADD 1 TO WS-TOTAL\n",
        '                   MOVE "Y" TO WS-EOF-FLAG\n',
    )
    text = _scaffold(source, "rdloop.cbl")
    assert 'MOVE "Y" TO WS-EOF-FLAG' in text
    assert "replicated verbatim" not in text


# --- _extract_at_end_imperative, directly -----------------------------------


def test_extract_handles_a_single_line_read():
    text = 'READ INV-FILE AT END MOVE "Y" TO WS-EOF END-READ'
    assert _extract_at_end_imperative(text) == 'MOVE "Y" TO WS-EOF'


def test_extract_stops_at_not_at_end():
    text = (
        "READ INV-FILE\n"
        "    AT END\n"
        "        MOVE WS-M TO WS-EOF\n"
        "    NOT AT END\n"
        "        ADD INV-QTY TO WS-TOTAL\n"
        "END-READ"
    )
    lifted = _extract_at_end_imperative(text)
    assert lifted is not None
    assert "MOVE WS-M TO WS-EOF" in lifted
    assert "ADD INV-QTY" not in lifted


def test_extract_stops_at_a_sentence_terminating_period():
    text = "READ INV-FILE AT END MOVE WS-M TO WS-EOF."
    assert _extract_at_end_imperative(text) == "MOVE WS-M TO WS-EOF"


def test_extract_ignores_at_end_inside_a_literal():
    """Positional word scanning, outside quoted literals -- a DISPLAY of the
    words "AT END" must not be mistaken for the clause."""
    text = 'READ INV-FILE INTO WS-REC END-READ\nDISPLAY "AT END OF FILE"'
    assert _extract_at_end_imperative(text) is None


def test_extract_does_not_mistake_a_decimal_point_for_a_terminator():
    text = "READ INV-FILE AT END MOVE 1.5 TO WS-RATE END-READ"
    assert _extract_at_end_imperative(text) == "MOVE 1.5 TO WS-RATE"


def test_a_period_terminates_the_clause_rather_than_being_lifted_into_it():
    """A sentence-terminating period ends the READ sentence, so what follows
    it is the NEXT sentence and no part of the AT END imperative. The lifted
    text stops there -- and so can never carry a period into the spliced
    EVALUATE branch, where it would close the enclosing sentence early and
    silently restructure the generated program's control flow."""
    from mockymock.analysis.mock_surface import BoundarySite
    from mockymock.dsl.generator import _lifted_at_end_lines
    from mockymock.dsl.model import MockCategory

    site = BoundarySite(
        category=MockCategory.READ,
        label="READ",
        keys=("INV-FILE",),
        match_text=None,
        paragraph_name="READ-ONE",
        line=1,
        nested=False,
        statement=object(),
    )
    context = ProgramContext(
        lines=["READ INV-FILE AT END MOVE WS-M TO WS-EOF. ADD 1 TO WS-N"],
        statement_starts=[1],
    )
    lifted = _lifted_at_end_lines(site, context)
    assert lifted[1:] == ["MOVE WS-M TO WS-EOF"]
    assert not any("ADD 1 TO WS-N" in line for line in lifted)


def test_a_partly_replicable_at_end_clause_is_lifted_whole(splice_cannot_lift):
    """Issue #217: a literal MOVE next to an identifier-sourced one used to
    be replicated alone -- `MOVE WS-READ-CNT TO WS-TRAILER-CNT` vanished
    with no TODO, and `run --record-expectations` recorded the wrong value
    as golden. Replication is all or nothing, so the whole clause is lifted."""
    source = IDENTIFIER_AT_END_SOURCE.replace(
        "                   MOVE WS-END-MARKER TO WS-EOF-FLAG\n",
        '                   MOVE "Y" TO WS-EOF-FLAG\n',
    )
    text = _scaffold(source, "rdloop.cbl", with_source=True)
    assert 'MOVE "Y" TO WS-EOF-FLAG' in text
    assert "ADD 1 TO WS-TOTAL" in text


def test_partial_replication_is_never_emitted():
    from mockymock.dsl.generator import _replicated_at_end_statements

    source = IDENTIFIER_AT_END_SOURCE.replace(
        "                   MOVE WS-END-MARKER TO WS-EOF-FLAG\n",
        '                   MOVE "Y" TO WS-EOF-FLAG\n',
    )
    result = parse_cobol(source, filename="rdloop.cbl")
    (read,) = result.ast.find_all_by_type("IOReadStatement")
    assert _replicated_at_end_statements(read) == []


def test_a_clause_the_splice_lifts_is_not_copied_into_the_mock():
    """Issue #209: the splice runs the READ's own AT END clause once the
    mocked outcome says end of file, so copying it into WHEN OTHER too
    would run it twice. With no FILE STATUS field to report through, the
    branch sets the splice's own outcome field."""
    text = _scaffold(IDENTIFIER_AT_END_SOURCE, "rdloop.cbl")
    assert "WHEN OTHER" in text
    assert 'MOVE "10" TO UT-MOCK-STATUS' in text
    assert "the splice runs this READ's own AT END clause (line 27)" in text
    assert "MOVE WS-END-MARKER TO WS-EOF-FLAG" not in text
    assert "TODO" not in text


PERFORM_AT_END_SOURCE = IDENTIFIER_AT_END_SOURCE.replace(
    "                   ADD 1 TO WS-TOTAL\n",
    "                   PERFORM WRAP-UP\n",
).replace(
    "           END-READ.\n",
    "           END-READ.\n\n       WRAP-UP.\n           ADD 1 TO WS-TOTAL.\n",
)


def test_a_clause_that_performs_a_paragraph_is_not_copied(splice_cannot_lift):
    """`AT END PERFORM WRAP-UP` copied into the mock made the whole .cut
    unreadable: the parser refuses a body PERFORM (issue #287), so lint
    reported that instead of the program's real refusals. The clause now
    becomes the TODO and the file parses (sweep of 2026-10-29)."""
    text = _scaffold(PERFORM_AT_END_SOURCE, "rdloop.cbl")
    assert "PERFORM WRAP-UP" not in text
    assert "TODO: this program's AT END clause could not be auto-replicated" in text
    parse_cut(text)
