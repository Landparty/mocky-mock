"""Issue #258: a boundary statement with clause bodies of its own (READ ...
AT END ... END-READ, CALL ... ON EXCEPTION ... END-CALL) nested inside an
inline PERFORM or an IF is spliced like a top-level one when its own scope
terminator bounds it; its clause bodies are lifted and re-run after the
mock. Without that terminator its extent is unknown and it stays refused."""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock._lines import split_source_lines
from mockymock.analysis.mock_surface import analyze
from mockymock.cli.checks import run_static_checks
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RDLOOP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC      PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-EOF      PIC X VALUE "N".
           88 EOF      VALUE "Y".
       01  WS-COUNT    PIC 9(3) VALUE 0.
       01  WS-RC       PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           PERFORM UNTIL EOF
               READ IN-FILE
                   AT END SET EOF TO TRUE
                   NOT AT END ADD 1 TO WS-COUNT
               END-READ
           END-PERFORM
           CLOSE IN-FILE
           IF WS-COUNT > 0
               CALL "LOGIT" USING WS-COUNT
                   ON EXCEPTION MOVE 9 TO WS-RC
               END-CALL
           END-IF
           GOBACK.
"""

CUT = """\
TESTSUITE "rd"
TESTCASE "counts two"
    MOCK OPEN IN-FILE
    END-MOCK
    MOCK CLOSE IN-FILE
    END-MOCK
    MOCK READ IN-FILE ROWS
        (IN-REC = "A")
        (IN-REC = "B")
        TERMINAL (WS-EOF = "Y")
    END-MOCK
    MOCK CALL "LOGIT"
    END-MOCK
    PERFORM MAIN-PARA
    EXPECT WS-COUNT TO BE 2
    VERIFY CALL "LOGIT" WAS CALLED ONCE
"""


def _sites(source: str):
    program = parse_cobol(source).ast
    lines = split_source_lines(normalize_fixed_format(split_source_lines(source)))
    surface = analyze(program)
    annotate_nested_sites(surface, collect_scope_map(program, lines), lines)
    return {site.label: site for site in surface.boundary_sites}


def test_nested_read_and_call_with_own_terminators_get_spans() -> None:
    sites = _sites(PROGRAM)
    read, call = sites["READ"], sites["CALL"]
    assert read.nested and read.span == (21, 24), read.unspliceable_reason
    assert call.nested and call.span == (28, 30), call.unspliceable_reason


def test_without_its_own_terminator_the_site_stays_refused() -> None:
    sites = _sites(PROGRAM.replace("               END-READ\n", ""))
    read = sites["READ"]
    assert read.span is None
    assert "no END-READ of its own" in (read.unspliceable_reason or "")


def test_inline_read_loop_and_if_call_pass_the_static_checks(tmp_path) -> None:
    program = tmp_path / "RDLOOP.cbl"
    program.write_text(PROGRAM)
    cut = tmp_path / "RDLOOP.cut"
    cut.write_text(CUT)
    assert run_static_checks(program, cut, None).problems == []


def test_the_nested_reads_clause_bodies_are_lifted_into_the_splice() -> None:
    from mockymock.dsl.parser import parse_cut
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.source_map import collect_boundaries

    program = parse_cobol(PROGRAM).ast
    lines = split_source_lines(normalize_fixed_format(split_source_lines(PROGRAM)))
    surface = analyze(program)
    annotate_nested_sites(surface, collect_scope_map(program, lines), lines)
    suite = parse_cut(CUT)
    registry = TallyRegistry(suite)
    spliced = "\n".join(
        splice_program(lines, collect_boundaries(program), surface, suite, registry)
    )
    assert 'WHEN UT-MOCK-STATUS(1:1) = "0"' in spliced
    assert "ADD 1 TO WS-COUNT" in spliced.split("NOT AT END ADD 1 TO WS-COUNT")[-1]
    assert 'WHEN UT-MOCK-STATUS = "EX"' in spliced


def test_unmocked_site_no_mock_could_replace_offers_no_mock(tmp_path) -> None:
    # A READ nested in another READ's clause body cannot be spliced: adding
    # a MOCK for it would be refused in turn, so none is suggested.
    source = PROGRAM.replace(
        "                   NOT AT END ADD 1 TO WS-COUNT\n",
        "                   NOT AT END\n"
        "                       READ IN-FILE\n"
        "                           AT END SET EOF TO TRUE\n"
        "                       END-READ\n",
    )
    program = tmp_path / "RDLOOP.cbl"
    program.write_text(source)
    cut = tmp_path / "RDLOOP.cut"
    cut.write_text(CUT.replace("    MOCK READ IN-FILE ROWS", "    MOCK READ XX ROWS"))
    checked = run_static_checks(program, cut, None)
    reasons = [r for rs in checked.unmocked_reasons.values() for r in rs]
    unfixable = [r for r in reasons if "could not replace it" in r.message]
    assert unfixable and all(r.suggested_fix is None for r in unfixable)
