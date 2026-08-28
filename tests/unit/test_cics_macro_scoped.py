"""Paragraph-scoped narrowing of `UNSUPPORTED_CICS_MACRO`.

`DFHRESP(...)`/`DFHVALUE(...)` used to refuse the whole file the moment
the text appeared anywhere in it, however unrelated the paragraph holding
it was to the paragraphs a `.cut` actually tests -- blocking every test
case in a real CICS program over one screen-handling paragraph nothing
under test performs. It now travels the same held-back path
PARSE_WARNING and UNRESOLVED_COPYBOOK already do (see
tests/unit/test_scoped_refusals.py): refused only when some selected test
case can execute the paragraph holding the call, and otherwise waived
with a note -- plus a width-preserving rewrite of the call itself, since
cobc has no CICS translator and could not compile the unexpanded macro
even in code that never runs.

`UNSUPPORTED_CICS_DFHCOMMAREA` deliberately does NOT get this treatment:
it reports a missing declaration, not unsupported code, so reachability
cannot make it irrelevant.
"""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.refusal import (
    CICS_MACRO_PLACEHOLDER,
    check_cics_eib_layout,
    check_cics_eib_layout_scoped,
)
from mockymock.cli.checks import run_static_checks
from mockymock.splicer.stub_writer import replace_columns

# 2000-MAIN performs only 2100-WORK; 2900-LIRE-ECRAN (the DFHRESP holder)
# is reachable from nothing -- the shape of the real CICS program this
# narrowing was written for, where the macro sits in a screen-handling
# paragraph none of the tested validation paragraphs reaches.
UNREACHED_MACRO_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSSCOPE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP             PIC S9(8) COMP VALUE 0.
       01  WS-FLAG             PIC X VALUE SPACE.

       PROCEDURE DIVISION.
       2000-MAIN.
           PERFORM 2100-WORK
           GOBACK.

       2100-WORK.
           MOVE "Y" TO WS-FLAG.

       2900-LIRE-ECRAN.
           IF WS-RESP = DFHRESP(MAPFAIL)
               MOVE "M" TO WS-FLAG
           END-IF.
"""

MAIN_ONLY_CUT = """\
TESTSUITE "cics macro scoping"

TESTCASE "performs only the clean paragraph"
    PERFORM 2000-MAIN
"""

MACRO_PARAGRAPH_CUT = """\
TESTSUITE "cics macro scoping"

TESTCASE "performs the macro paragraph itself"
    PERFORM 2900-LIRE-ECRAN
"""

# The macro sits in the DATA DIVISION, so no paragraph body owns it.
DATA_DIVISION_MACRO_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSDATA.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NOTE             PIC X(30) VALUE "DFHRESP(NORMAL)".

       PROCEDURE DIVISION.
       2000-MAIN.
           DISPLAY WS-NOTE.
"""

# `DFHRESP` and its argument split across two lines: the detector still
# fires (the joined text matches), but no single-line span covers the
# call, so it must stay a whole-program refusal.
CONTINUED_MACRO_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSCONT.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP             PIC S9(8) COMP VALUE 0.
       01  WS-FLAG             PIC X VALUE SPACE.

       PROCEDURE DIVISION.
       2000-MAIN.
           MOVE "Y" TO WS-FLAG.

       2900-LIRE-ECRAN.
           IF WS-RESP = DFHRESP
              (MAPFAIL)
               MOVE "M" TO WS-FLAG
           END-IF.
"""

UNDECLARED_DFHCOMMAREA_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSCOMM.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG             PIC X VALUE SPACE.

       PROCEDURE DIVISION.
       2000-MAIN.
           MOVE "Y" TO WS-FLAG.

       2900-LIRE-ECRAN.
           MOVE DFHCOMMAREA TO WS-FLAG.
"""


def _parse(source: str):
    result = parse_cobol(source, filename="CICS.cbl")
    assert result.success, result.errors
    return result.ast, normalize_fixed_format(source.splitlines()).splitlines()


def _write(tmp_path, source: str, cut: str):
    cbl = tmp_path / "CICS.cbl"
    cbl.write_text(source)
    cut_path = tmp_path / "CICS.cut"
    cut_path.write_text(cut)
    return cbl, cut_path


def test_scoped_holds_back_a_paragraph_local_macro_call():
    program, lines = _parse(UNREACHED_MACRO_CBL)
    reasons, scoped = check_cics_eib_layout_scoped(program, lines)
    assert reasons == []
    assert len(scoped) == 1
    item = scoped[0]
    assert item.paragraph_name == "2900-LIRE-ECRAN"
    assert item.reason.code == "UNSUPPORTED_CICS_MACRO"
    assert item.neutralize_span is not None
    macro_line, start, end = item.neutralize_span
    assert lines[macro_line - 1][start:end] == "DFHRESP(MAPFAIL)"


def test_the_held_back_span_rewrites_without_moving_anything():
    program, lines = _parse(UNREACHED_MACRO_CBL)
    _, scoped = check_cics_eib_layout_scoped(program, lines)
    macro_line, start, end = scoped[0].neutralize_span
    rewritten = replace_columns(lines, macro_line, start, end, CICS_MACRO_PLACEHOLDER)
    assert len(rewritten) == len(lines)
    assert len(rewritten[macro_line - 1]) == len(lines[macro_line - 1])
    assert "DFHRESP" not in rewritten[macro_line - 1]
    assert CICS_MACRO_PLACEHOLDER in rewritten[macro_line - 1]
    # Nothing but the macro's own columns changed.
    assert rewritten[macro_line - 1][:start] == lines[macro_line - 1][:start]
    assert rewritten[macro_line - 1][end:] == lines[macro_line - 1][end:]


def test_unscoped_entry_point_still_refuses_whole_program():
    # generate/fixtures have no test cases to scope by and keep refusing.
    program, lines = _parse(UNREACHED_MACRO_CBL)
    reasons = check_cics_eib_layout(program, lines)
    assert [r.code for r in reasons] == ["UNSUPPORTED_CICS_MACRO"]


def test_macro_outside_any_paragraph_body_stays_whole_program():
    program, lines = _parse(DATA_DIVISION_MACRO_CBL)
    reasons, scoped = check_cics_eib_layout_scoped(program, lines)
    assert scoped == []
    assert [r.code for r in reasons] == ["UNSUPPORTED_CICS_MACRO"]


def test_macro_continued_across_lines_stays_whole_program():
    program, lines = _parse(CONTINUED_MACRO_CBL)
    reasons, scoped = check_cics_eib_layout_scoped(program, lines)
    assert scoped == []
    assert [r.code for r in reasons] == ["UNSUPPORTED_CICS_MACRO"]


def test_undeclared_dfhcommarea_is_never_scoped():
    program, lines = _parse(UNDECLARED_DFHCOMMAREA_CBL)
    reasons, scoped = check_cics_eib_layout_scoped(program, lines)
    assert scoped == []
    assert [r.code for r in reasons] == ["UNSUPPORTED_CICS_DFHCOMMAREA"]


def test_run_static_checks_waives_an_unreached_macro(tmp_path):
    cbl, cut = _write(tmp_path, UNREACHED_MACRO_CBL, MAIN_ONLY_CUT)
    result = run_static_checks(cbl, cut, None)
    assert result.ok, result.problems
    assert any("waived" in note and "2900-LIRE-ECRAN" in note for note in result.notes)
    # The waived call is gone from the lines the splicer/compiler see, and
    # the line it was on is exactly as long as it was.
    assert result.lines is not None
    assert not any("DFHRESP" in line for line in result.lines)
    original = normalize_fixed_format(UNREACHED_MACRO_CBL.splitlines()).splitlines()
    assert len(result.lines) == len(original)
    assert [len(line) for line in result.lines] == [len(line) for line in original]


def test_run_static_checks_refuses_a_reachable_macro(tmp_path):
    cbl, cut = _write(tmp_path, UNREACHED_MACRO_CBL, MACRO_PARAGRAPH_CUT)
    result = run_static_checks(cbl, cut, None)
    assert not result.ok
    assert any("UNSUPPORTED_CICS_MACRO" in problem for problem in result.problems)
    assert any("2900-LIRE-ECRAN" in problem for problem in result.problems)
    assert result.notes == []


def test_run_static_checks_refuses_a_macro_it_cannot_localize(tmp_path):
    cbl, cut = _write(tmp_path, CONTINUED_MACRO_CBL, MAIN_ONLY_CUT)
    result = run_static_checks(cbl, cut, None)
    assert not result.ok
    assert any("UNSUPPORTED_CICS_MACRO" in problem for problem in result.problems)
