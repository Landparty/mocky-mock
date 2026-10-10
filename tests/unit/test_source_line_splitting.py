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

from mockymock._lines import PARSER_SPLITS_ON_RECORD_DELIMITERS, split_source_lines
from mockymock.cli.checks import run_static_checks
from mockymock.cli.main import main

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


needs_record_splitting_parser = pytest.mark.skipif(
    not PARSER_SPLITS_ON_RECORD_DELIMITERS,
    reason="installed cobolparser numbers lines the str.splitlines() way",
)


@needs_record_splitting_parser
@pytest.mark.parametrize("sep", NON_RECORD_BREAKS)
def test_split_source_lines_keeps_non_record_breaks_inside_the_line(sep):
    assert split_source_lines(f"a{sep}b\nc") == [f"a{sep}b", "c"]


@pytest.mark.parametrize("sep", NON_RECORD_BREAKS)
def test_split_source_lines_agrees_with_the_installed_parser(sep):
    # An older cobolparser (no `cobolparser._lines`) numbers records the
    # str.splitlines() way itself; mockymock must follow whichever it is.
    text = f"a{sep}b\nc"
    expected = (
        [f"a{sep}b", "c"] if PARSER_SPLITS_ON_RECORD_DELIMITERS else text.splitlines()
    )
    assert split_source_lines(text) == expected


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


@needs_record_splitting_parser
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
