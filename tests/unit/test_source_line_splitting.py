"""COBOL source is split into records on `\\n` / `\\r\\n` / `\\r` only.

cobolparser numbers a source's records that way (`SourceLocation.line`), but
mockymock split the same text with `str.splitlines()`, which also breaks on
form feed, vertical tab, `\\x1c`-`\\x1e`, NEL and U+2028/2029. A legacy
source carrying a page-eject form feed inside a comment line therefore had
one more line in mockymock's `lines` than in the parser's view, and every
splice after it landed one line early: `mockymock run` commented out the
statement BEFORE a mocked CALL, spliced the mock dispatch there, and left
the real `CALL "SUB"` in place to execute (reproduced against the
mockymock-cobc container: `libcob: error: module 'SUB' not found`).
"""

import pytest

from mockymock._lines import split_source_lines
from mockymock.cli.main import main
from mockymock.engine.checks import run_static_checks

SOURCE = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. FFPROG.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "      * SECTION BREAK {sep} PAGE 2\n"
    '       01 WS-A PIC X(5) VALUE "HELLO".\n'
    "       01 WS-R PIC 9(3) VALUE 0.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-PARA.\n"
    "           MOVE 1 TO WS-R\n"
    '           CALL "SUB" USING WS-A\n'
    "           MOVE 2 TO WS-R\n"
    "           GOBACK.\n"
)

CUT = (
    'TESTSUITE "FF"\n'
    'TESTCASE "calls sub"\n'
    '    MOCK CALL "SUB"\n'
    "        MOVE 0 TO RETURN-CODE\n"
    "    END-MOCK\n"
    "    PERFORM MAIN-PARA\n"
    "    EXPECT WS-R TO BE 2\n"
)

# Every character str.splitlines() treats as a line boundary that is not a
# record delimiter.
NON_RECORD_BREAKS = ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " "]


@pytest.mark.parametrize("sep", NON_RECORD_BREAKS)
def test_split_source_lines_keeps_non_record_breaks_inside_the_line(sep):
    assert split_source_lines(f"a{sep}b\nc") == [f"a{sep}b", "c"]


def test_split_source_lines_mirrors_splitlines_on_real_record_breaks():
    for text in ["", "a", "a\n", "a\nb", "a\r\nb\r\n", "a\rb", "a\n\nb\n"]:
        assert split_source_lines(text) == text.splitlines()


@pytest.mark.parametrize("sep", NON_RECORD_BREAKS)
def test_boundary_site_line_indexes_the_mocked_statement(tmp_path, sep):
    program = tmp_path / "FFPROG.cbl"
    program.write_text(SOURCE.format(sep=sep), encoding="utf-8")
    cut = tmp_path / "FFPROG.cut"
    cut.write_text(CUT, encoding="utf-8")

    checked = run_static_checks(program, cut, None)
    assert checked.ok, checked.problems
    [site] = [s for s in checked.surface.boundary_sites if s.label == "CALL"]
    # The splicer comments out lines[site.line - 1 ...]: it must be the CALL.
    assert 'CALL "SUB"' in checked.lines[site.line - 1]


def test_mutate_list_reports_original_line_numbers(tmp_path, capsys):
    program = tmp_path / "FFPROG.cbl"
    program.write_text(SOURCE.format(sep="\x0c"), encoding="utf-8")
    cut = tmp_path / "FFPROG.cut"
    cut.write_text(CUT, encoding="utf-8")

    assert main(["mutate", str(program), "--cut", str(cut), "--list"]) == 0
    out = capsys.readouterr().out
    # MOVE 1 is on record 10 and MOVE 2 on record 12 -- not 11 and 13.
    assert "line 10 [move-literal] MOVE 1 -> MOVE 2" in out
    assert "line 12 [move-literal] MOVE 2 -> MOVE 3" in out


# Regression: bug hunt of 2026-11-05 on the .cut suite language and the CLI
# (executed counterpart:
# tests/integration/test_bug_hunt_20261105_cut_language.py). `.cut` text was
# split with `str.splitlines()`: a form feed (or VT, NEL, U+2028) inside a `*>`
# comment cut the comment in two, and every later line number was one off in
# lint, stub scanning and the --record-expectations rewrite.
from mockymock.analysis.stub_expectations import scan_stub_expectations
from mockymock.dsl.parser import parse_cut
from mockymock.project.discovery import read_program_line

# --- 2. form feed inside .cut text ------------------------------------------

FF_CUT = (
    'TESTSUITE "ff"\n'
    "*> page\x0c eject and a line separator\n"
    'TESTCASE "a"\n'
    "    PERFORM MAIN-PARA\n"
    "    *> STUB EXPECT WS-B\n"
    "    EXPECT WS-B TO BE 1\n"
)


def test_a_form_feed_in_a_comment_neither_splits_it_nor_shifts_lines():
    suite = parse_cut(FF_CUT)
    case = suite.test_cases[0]
    assert case.line == 3
    assert case.expectations[0].line == 6


def test_stub_scan_and_program_directive_count_lines_the_same_way(tmp_path):
    stubs = scan_stub_expectations(FF_CUT, parse_cut(FF_CUT))
    assert [stub.line for stub in stubs.stubs] == [5]
    cut = tmp_path / "ff.cut"
    cut.write_text('*> \x0c PROGRAM "WRONG.cbl"\nTESTSUITE "s"\nPROGRAM "P.cbl"\n')
    assert read_program_line(cut) == "P.cbl"
