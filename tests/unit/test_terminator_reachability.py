"""Unit tests for the two new reachability primitives Approach B's
safe-chain check depends on: which paragraphs are EVER a GO TO target
anywhere in the program, and which paragraphs are reachable from a given
start paragraph via ONLY plain, unconditional, top-level PERFORM
statements. See docs/2026-07-08-goback-stop-run-support-design.md.
"""

from cobolparser import parse_cobol

from mockymock.analysis.refusal import _go_to_targets, _plain_perform_edges_from

CHAIN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CHAINTEST.

       PROCEDURE DIVISION.
       TARGET-PARA.
           PERFORM LEVEL1-PARA.

       LEVEL1-PARA.
           PERFORM LEVEL2-PARA.

       LEVEL2-PARA.
           DISPLAY "REACHED".

       UNRELATED-PARA.
           GO TO LEVEL1-PARA.

       THRU-CALLER.
           PERFORM LEVEL2-PARA THRU LEVEL2-PARA.

       CONDITIONAL-CALLER.
           IF 1 = 1
               PERFORM LEVEL2-PARA
           END-IF.
"""


def _program():
    result = parse_cobol(CHAIN_SOURCE, filename="chaintest.cbl")
    assert result.success, result.errors
    return result.ast


def test_go_to_targets_finds_every_go_to_target_in_whole_program():
    targets = _go_to_targets(_program())
    assert targets == {"LEVEL1-PARA"}


def test_plain_perform_edges_from_walks_the_chain():
    seen, edges = _plain_perform_edges_from(_program(), "TARGET-PARA")
    assert seen == {"TARGET-PARA", "LEVEL1-PARA", "LEVEL2-PARA"}
    assert len(edges) == 2
    assert {e.target_paragraph for e in edges} == {"LEVEL1-PARA", "LEVEL2-PARA"}


def test_plain_perform_edges_from_ignores_thru_and_conditional_and_goto():
    """THRU-CALLER's PERFORM...THRU, CONDITIONAL-CALLER's nested PERFORM,
    and UNRELATED-PARA's GO TO must never contribute edges -- none of them
    are plain, unconditional, top-level PERFORM statements."""
    seen, edges = _plain_perform_edges_from(_program(), "THRU-CALLER")
    assert seen == {"THRU-CALLER"}
    assert edges == []

    seen, edges = _plain_perform_edges_from(_program(), "CONDITIONAL-CALLER")
    assert seen == {"CONDITIONAL-CALLER"}
    assert edges == []

    seen, edges = _plain_perform_edges_from(_program(), "UNRELATED-PARA")
    assert seen == {"UNRELATED-PARA"}
    assert edges == []
