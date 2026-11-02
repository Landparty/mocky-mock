"""`splicer.file_keys`: a SELECT key declared outside the file's FD
records is pointed at the FD record (RECORD KEY) or dropped (ALTERNATE
RECORD KEY), on the lines it started on."""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.splicer.file_keys import rewrite_foreign_record_keys

HEAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. KEYS.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
"""

DATA = """\
       DATA DIVISION.
       FILE SECTION.
       FD  OUT-FILE.
       01  OUT-REC                PIC X(60).
       01  OUT-REC-2.
           05  OUT-KEY            PIC 9(9).
           05  OUT-ALT            PIC X.
           05  FILLER             PIC X(50).
       FD  IN-FILE.
       01  IN-REC.
           05  IN-KEY             PIC 9(9).
           05  FILLER             PIC X(51).
       WORKING-STORAGE SECTION.
       01  WS-REC.
           05  WS-KEY             PIC 9(9).
           05  WS-ALT             PIC X.
       01  WS-ST                  PIC XX.
       01  WS-ST2                 PIC XX.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN OUTPUT OUT-FILE.
           GOBACK.
"""


def _rewrite(selects: str) -> tuple[list[str], list[str]]:
    source = HEAD + selects + DATA
    result = parse_cobol(source, filename="keys.cbl")
    assert result.ast is not None, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    return lines, rewrite_foreign_record_keys(lines, analyze(result.ast))


def test_a_record_key_in_working_storage_is_pointed_at_the_fd_record():
    before, after = _rewrite("""\
           SELECT OUT-FILE ASSIGN TO OUTF
               ORGANIZATION IS INDEXED
               ACCESS MODE IS SEQUENTIAL
               RECORD KEY IS WS-KEY
               FILE STATUS IS WS-ST.
""")
    assert len(after) == len(before)
    changed = [(b, a) for b, a in zip(before, after, strict=True) if b != a]
    assert len(changed) == 1
    assert changed[0][1].strip() == "RECORD KEY IS OUT-REC"


def test_a_qualified_key_loses_its_qualifier_too():
    _, after = _rewrite("""\
           SELECT OUT-FILE ASSIGN TO OUTF
               ORGANIZATION IS INDEXED
               RECORD KEY IS WS-KEY OF WS-REC
               FILE STATUS IS WS-ST.
""")
    assert "RECORD KEY IS OUT-REC" in "\n".join(after)
    assert "WS-REC" not in "\n".join(after[:12])


def test_a_key_split_from_its_name_across_lines_keeps_the_line_count():
    before, after = _rewrite("""\
           SELECT OUT-FILE ASSIGN TO OUTF
               ORGANIZATION IS INDEXED
               RECORD KEY IS
                   WS-KEY OF
                   WS-REC
               FILE STATUS IS WS-ST.
""")
    assert len(after) == len(before)
    text = "\n".join(after)
    assert "WS-KEY" not in text.split("DATA DIVISION")[0]
    assert "FILE STATUS IS WS-ST." in text


def test_a_foreign_alternate_key_is_dropped_and_its_own_key_kept():
    _, after = _rewrite("""\
           SELECT OUT-FILE ASSIGN TO OUTF
               ORGANIZATION IS INDEXED
               RECORD KEY IS OUT-KEY
               ALTERNATE RECORD KEY IS WS-ALT WITH DUPLICATES
               ALTERNATE RECORD KEY IS OUT-ALT
               FILE STATUS IS WS-ST.
""")
    text = "\n".join(after).split("DATA DIVISION")[0]
    assert "RECORD KEY IS OUT-KEY" in text
    assert "WS-ALT" not in text
    assert "DUPLICATES" not in text
    assert "ALTERNATE RECORD KEY IS OUT-ALT" in text


def test_keys_inside_the_fd_and_other_selects_are_left_alone():
    selects = """\
           SELECT IN-FILE ASSIGN TO INF
               ORGANIZATION IS INDEXED
               RECORD KEY IS IN-KEY
               FILE STATUS IS WS-ST2.
           SELECT OUT-FILE ASSIGN TO OUTF
               ORGANIZATION IS INDEXED
               RECORD KEY IS OUT-KEY
               FILE STATUS IS WS-ST.
"""
    before, after = _rewrite(selects)
    assert after == before


def test_a_key_of_another_files_record_is_foreign_too():
    _, after = _rewrite("""\
           SELECT IN-FILE ASSIGN TO INF
               ORGANIZATION IS INDEXED
               RECORD KEY IS OUT-KEY
               FILE STATUS IS WS-ST2.
           SELECT OUT-FILE ASSIGN TO OUTF
               ORGANIZATION IS INDEXED
               RECORD KEY IS OUT-KEY
               FILE STATUS IS WS-ST.
""")
    text = "\n".join(after)
    assert "RECORD KEY IS IN-REC" in text
    assert "RECORD KEY IS OUT-KEY" in text


def test_a_program_without_file_control_is_unchanged():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOFILES.
       PROCEDURE DIVISION.
           GOBACK.
"""
    result = parse_cobol(source, filename="nofiles.cbl")
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    assert rewrite_foreign_record_keys(lines, analyze(result.ast)) == lines
