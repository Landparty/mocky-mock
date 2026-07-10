"""Unit tests for the two new reachability primitives Approach B's
safe-chain check depends on: which paragraphs are EVER a GO TO target
anywhere in the program, and which paragraphs are reachable from a given
start paragraph via ONLY plain, unconditional, top-level PERFORM
statements. See docs/2026-07-08-goback-stop-run-support-design.md.
"""

from cobolparser import parse_cobol

from mockymock.analysis.refusal import (
    _go_to_targets,
    _plain_perform_edges_from,
    _safe_section_entry_points,
)

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

       LOOP-CALLER.
           PERFORM LEVEL2-PARA UNTIL 1 = 1.
"""

SAFE_SECTION_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INIT-SECTION.

       1000-INIT-SECTION SECTION.
       1000-INIT-FIRST.
           DISPLAY "FIRST".
       1000-INIT-SECOND.
           DISPLAY "SECOND".
"""

SECTION_GO_TO_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTGOTOUNSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INIT-SECTION.

       9000-ALIAS.
           GO TO 1000-INIT-FIRST.

       1000-INIT-SECTION SECTION.
       1000-INIT-FIRST.
           DISPLAY "FIRST".
"""

SECTION_DIRECT_PERFORM_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTDIRECTUNSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-INIT-SECTION.

       9000-ALSO-CALLS-DIRECTLY.
           PERFORM 1000-INIT-FIRST.

       1000-INIT-SECTION SECTION.
       1000-INIT-FIRST.
           DISPLAY "FIRST".
"""

SECTION_CONTINUES_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTCONTINUES.

       PROCEDURE DIVISION.
       TARGET-PARA.
           PERFORM SAFE-SECTION.

       LEVEL2-PARA.
           DISPLAY "REACHED FROM SECTION".

       SAFE-SECTION SECTION.
       SAFE-FIRST.
           PERFORM LEVEL2-PARA.
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


def test_plain_perform_edges_from_ignores_looping_perform():
    """A PERFORM ... UNTIL is not a plain, single-shot PERFORM: EXIT
    PARAGRAPH from its target only ends the current iteration, not the
    loop, so its target must not be treated as safely reachable --
    discovered 2026-07-09 while qualifying ACCTPRG for Task 10, fixed by
    excluding perform_type != "SIMPLE" edges (see "Out of scope", below,
    and .okf/log.md)."""
    seen, edges = _plain_perform_edges_from(_program(), "LOOP-CALLER")
    assert seen == {"LOOP-CALLER"}
    assert edges == []


def test_safe_section_entry_points_finds_a_safely_entered_section():
    program = parse_cobol(SAFE_SECTION_SOURCE, filename="sectsafe.cbl").ast
    assert _safe_section_entry_points(program) == {
        "1000-INIT-SECTION": "1000-INIT-FIRST"
    }


def test_safe_section_entry_points_excludes_a_go_to_reachable_first_paragraph():
    program = parse_cobol(SECTION_GO_TO_UNSAFE_SOURCE, filename="sectgoto.cbl").ast
    assert _safe_section_entry_points(program) == {}


def test_safe_section_entry_points_excludes_a_directly_performed_first_paragraph():
    program = parse_cobol(
        SECTION_DIRECT_PERFORM_UNSAFE_SOURCE, filename="sectdirect.cbl"
    ).ast
    assert _safe_section_entry_points(program) == {}


def test_safe_section_entry_points_empty_when_program_has_no_sections():
    assert _safe_section_entry_points(_program()) == {}


def test_plain_perform_edges_from_resolves_safe_section_entry_to_first_paragraph():
    program = parse_cobol(SAFE_SECTION_SOURCE, filename="sectsafe2.cbl").ast
    safe_entries = _safe_section_entry_points(program)
    seen, edges = _plain_perform_edges_from(program, "0000-MAIN-PROCESS", safe_entries)
    assert seen == {"0000-MAIN-PROCESS", "1000-INIT-FIRST"}
    assert len(edges) == 1
    assert edges[0].target_paragraph == "1000-INIT-SECTION"


def test_plain_perform_edges_from_continues_bfs_from_section_first_paragraph():
    program = parse_cobol(SECTION_CONTINUES_SOURCE, filename="sectcontinues.cbl").ast
    safe_entries = _safe_section_entry_points(program)
    seen, edges = _plain_perform_edges_from(program, "TARGET-PARA", safe_entries)
    assert seen == {"TARGET-PARA", "SAFE-FIRST", "LEVEL2-PARA"}
    assert {e.target_paragraph for e in edges} == {"SAFE-SECTION", "LEVEL2-PARA"}


def test_plain_perform_edges_from_still_dead_ends_on_section_without_safe_entries():
    """Regression guard: callers that don't pass safe_section_entries (the
    default, e.g. every pre-existing call site) get exactly today's
    behavior -- a SECTION name is an unresolved dead end, its raw name
    landing in `seen` but never traversed further."""
    program = parse_cobol(SAFE_SECTION_SOURCE, filename="sectsafe3.cbl").ast
    seen, edges = _plain_perform_edges_from(program, "0000-MAIN-PROCESS")
    assert seen == {"0000-MAIN-PROCESS", "1000-INIT-SECTION"}
    assert len(edges) == 1
    assert edges[0].target_paragraph == "1000-INIT-SECTION"
