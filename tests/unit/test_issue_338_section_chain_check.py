"""Issue #338: a chain PERFORM in a SECTION's first paragraph (entered via
PERFORM <section-name>) gets an `EXIT SECTION` early-exit check -- `EXIT
PARAGRAPH` only left that paragraph, so control fell into the section's
next paragraph after the neutralized STOP RUN."""

import pytest
from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import find_terminator_plans
from mockymock.dsl.model import MockTestCase, MockTestSuite
from mockymock.splicer.injector import build_chain_check
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import (
    annotate_nested_sites,
    collect_boundaries,
    collect_scope_map,
)

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECCH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9 VALUE 0.
       01 WS-Y PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM WORK-SEC
           GOBACK.
       ABEND-PARA.
           DISPLAY "FATAL"
           STOP RUN.
       WORK-SEC SECTION.
       W1.
           PERFORM ABEND-PARA
           MOVE 1 TO WS-X.
       W2.
           ADD 1 TO WS-Y.
"""


def _splice(target):
    result = parse_cobol(SOURCE, filename="secch.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(SOURCE.splitlines()).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    suite = MockTestSuite(
        name="T", test_cases=[MockTestCase(name="c", perform_target=target)]
    )
    plans, reasons = find_terminator_plans(surface, result.ast, suite, scope_map, lines)
    assert reasons == []
    return splice_program(
        lines,
        collect_boundaries(result.ast),
        surface,
        suite,
        TallyRegistry(suite),
        plans,
    )


def _check_exit_after(spliced, statement):
    index = next(i for i, line in enumerate(spliced) if statement in line)
    assert spliced[index + 1].strip() == 'IF UT-EARLY-EXIT = "Y"'
    return spliced[index + 2].strip()


@pytest.mark.parametrize("target", ["MAIN-PARA", "WORK-SEC"])
def test_chain_check_in_a_section_first_paragraph_exits_the_section(target):
    spliced = _splice(target)
    assert _check_exit_after(spliced, "PERFORM ABEND-PARA") == "EXIT SECTION"


def test_chain_check_in_a_top_level_paragraph_still_exits_the_paragraph():
    spliced = _splice("MAIN-PARA")
    assert _check_exit_after(spliced, "PERFORM WORK-SEC") == "EXIT PARAGRAPH"


def test_build_chain_check_defaults_to_exit_paragraph():
    assert build_chain_check()[1].strip() == "EXIT PARAGRAPH"
    assert build_chain_check("SECTION")[1].strip() == "EXIT SECTION"
