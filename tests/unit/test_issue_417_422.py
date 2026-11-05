"""Issue #417: a KSDS read both by key and by a `READ NEXT` browse that ends
on its FILE STATUS gets the browse's "10" end-of-file terminal, and the
split `<file> KEY` mock still answers "23" when the file is empty.

Issue #422: a screen DISPLAY / `STOP <literal>` nested in an IF arm is
answered with CONTINUE through its span, not refused; one inside another
boundary's clause body still is."""

from __future__ import annotations

import pytest
from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock._lines import split_source_lines
from mockymock.analysis.mock_surface import (
    analyze,
    analyze_file_status_fields,
    is_answered_site,
)
from mockymock.analysis.refusal import check_test_case
from mockymock.dsl.model import MockTestCase
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import (
    annotate_nested_sites,
    collect_boundaries,
    collect_scope_map,
)
from tests.unit.test_bug_hunt_m1_fixes import _generate

DYN_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYN3.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO CUSTF
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS CUST-KEY
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-REC.
           05  CUST-KEY    PIC X(5).
           05  CUST-NAME   PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-FS           PIC XX.
       01  WS-COUNT        PIC 9(4) VALUE 0.
       LINKAGE SECTION.
       01  LK-ID           PIC X(5).
       01  LK-OUT          PIC X(10).
       01  LK-CNT          PIC 9(4).
       PROCEDURE DIVISION USING LK-ID LK-OUT LK-CNT.
           OPEN INPUT CUST-FILE
           MOVE LK-ID TO CUST-KEY
           READ CUST-FILE KEY IS CUST-KEY
           END-READ
           IF WS-FS = '00'
               MOVE CUST-NAME TO LK-OUT
           END-IF
           START CUST-FILE KEY NOT LESS THAN CUST-KEY
           END-START
           PERFORM UNTIL WS-FS = '10'
               READ CUST-FILE NEXT RECORD
               IF WS-FS = '00'
                   ADD 1 TO WS-COUNT
               END-IF
           END-PERFORM
           MOVE WS-COUNT TO LK-CNT
           CLOSE CUST-FILE
           GOBACK.
"""

#: The keyed lookup through INVALID KEY instead of `KEY IS`.
DYNRD_CBL = DYN_CBL.replace(
    "           READ CUST-FILE KEY IS CUST-KEY\n",
    "           READ CUST-FILE\n               INVALID KEY MOVE SPACES TO LK-OUT\n",
)


def _mock(case: str, key: str) -> str:
    start = case.index(f"MOCK READ {key}\n")
    return case[start : case.index("END-MOCK", start)]


def _case(cut: str, name: str) -> str:
    start = cut.index(f'TESTCASE "{name}"')
    end = cut.find("TESTCASE", start + 1)
    return cut[start : end if end > 0 else len(cut)]


def test_417_the_browse_of_a_split_file_ends_on_status_10(tmp_path) -> None:
    cut = _generate(tmp_path, "DYN3", DYN_CBL, "--seed", "3", "--scenarios", "all")
    happy = _case(cut, "happy path")
    browse = _mock(happy, "CUST-FILE NEXT")
    assert "WHEN OTHER" in browse
    assert 'MOVE "10" TO WS-FS' in browse
    assert 'MOVE "10"' not in _mock(happy, "CUST-FILE KEY")
    assert 'MOVE "10" TO WS-FS' in _mock(_case(cut, "empty input"), "CUST-FILE NEXT")


def test_417_an_empty_split_keyed_read_answers_23(tmp_path) -> None:
    cut = _generate(tmp_path, "DYNRD", DYNRD_CBL, "--seed", "3", "--scenarios", "all")
    empty = _case(cut, "empty input")
    assert '"23"' in _mock(empty, "CUST-FILE KEY")
    assert 'MOVE "10" TO WS-FS' in _mock(empty, "CUST-FILE NEXT")


SCREEN_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A        PIC X(5) VALUE 'HELLO'.
       01  WS-N        PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY WS-A AT LINE 3 COLUMN 10 WITH HIGHLIGHT
           IF WS-N > 5
               DISPLAY 'BIG' LINE 4 COL 1 BLANK SCREEN
               ADD 10 TO WS-N
           ELSE
               STOP 'SMALL'
               ADD 1 TO WS-N
           END-IF
           DISPLAY 'Z' AT 0505
           GOBACK.
"""


def _parses_screen_displays() -> bool:
    """cobol-parser marks a screen DISPLAY (`is_screen_display`) only from
    3.4 on; the compat lane runs the published release, which does not."""
    program = parse_cobol(SCREEN_CBL).ast
    return any(
        getattr(node, "is_screen_display", False)
        for node in program.find_all_by_type("DisplayStatement")
    )


screen_displays = pytest.mark.skipif(
    not _parses_screen_displays(), reason="cobol-parser has no screen DISPLAY"
)


def _analyzed(source: str):
    program = parse_cobol(source).ast
    lines = split_source_lines(normalize_fixed_format(split_source_lines(source)))
    surface = analyze(program)
    annotate_nested_sites(surface, collect_scope_map(program, lines), lines)
    return program, lines, surface


def _codes(program, surface) -> set[str]:
    case = MockTestCase(name="t", perform_target="MAIN-PARA", mocks=[])
    return {
        r.code
        for r in check_test_case(
            surface, program, case, analyze_file_status_fields(program)
        )
    }


@screen_displays
def test_422_nested_answered_sites_are_not_refused() -> None:
    program, _, surface = _analyzed(SCREEN_CBL)
    answered = [s for s in surface.boundary_sites if is_answered_site(s)]
    assert sorted(s.line for s in answered) == [9, 11, 14, 17]
    codes = _codes(program, surface)
    assert "UNSUPPORTED_SCREEN_DISPLAY" not in codes
    assert "UNSUPPORTED_STOP_LITERAL" not in codes


@screen_displays
def test_422_nested_answered_sites_are_spliced_to_continue() -> None:
    program, lines, surface = _analyzed(SCREEN_CBL)
    suite = parse_cut('TESTSUITE "s"\nTESTCASE "t"\n    PERFORM MAIN-PARA\n')
    spliced = splice_program(
        lines, collect_boundaries(program), surface, suite, TallyRegistry(suite)
    )
    code = [line for line in spliced if not line.lstrip().startswith("*>")]
    text = "\n".join(code)
    assert "BLANK SCREEN" not in text
    assert "STOP 'SMALL'" not in text
    assert "AT 0505" not in text
    # The IF's other statements and its scope terminator survive.
    assert "ADD 10 TO WS-N" in text and "ADD 1 TO WS-N" in text
    assert "END-IF" in text


def test_422_an_answered_site_in_a_boundary_clause_is_still_refused() -> None:
    source = SCREEN_CBL.replace(
        "           DISPLAY 'Z' AT 0505\n",
        "           CALL 'SUB' ON EXCEPTION STOP 'NO SUB' END-CALL\n",
    )
    program, _, surface = _analyzed(source)
    (stop,) = [s for s in surface.boundary_sites if s.keys == ("NO SUB",)]
    assert stop.nested_in_boundary and not is_answered_site(stop)
    assert "UNSUPPORTED_STOP_LITERAL" in _codes(program, surface)


@screen_displays
def test_422_generate_does_not_list_answered_sites_as_unmockable(
    tmp_path, capsys
) -> None:
    _generate(tmp_path, "SCR", SCREEN_CBL)
    assert "not mockable" not in capsys.readouterr().out
