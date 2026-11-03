"""GnuCOBOL quirks a z/OS program must get past (2026-11-03, NIST ST115A,
ST137A and four more ST programs)."""

from pathlib import Path

from mockymock.runtime.reserved_words import (
    not_reserved_flags,
    prepare_free_source,
    shield_column_7,
)

DOLLAR = chr(36)


def test_char_declared_as_a_data_name_is_freed():
    source = "01  WRK.\n    02 CHAR PIC X OCCURS 51 TIMES.\n"
    assert not_reserved_flags(source) == ["-fnot-reserved=CHAR"]


def test_char_stays_reserved_when_the_program_calls_function_char():
    source = "    02 CHAR PIC X.\n    MOVE FUNCTION CHAR(66) TO X.\n"
    assert not_reserved_flags(source) == []


def test_char_inside_a_literal_or_comment_is_not_a_declaration():
    source = '    DISPLAY "02 CHAR".\n*> 02 CHAR PIC X\n    MOVE CHARS TO X.\n'
    assert not_reserved_flags(source) == []


def test_a_dollar_in_column_7_is_shifted_right():
    line = f'    " {DOLLAR}{DOLLAR}()*+".'
    assert line[6] == DOLLAR
    shielded = shield_column_7(f"01 X PIC X(8) VALUE\n{line}\n")
    moved = shielded.split("\n")[1]
    assert moved[6] != DOLLAR
    assert moved.strip() == line.strip()


def test_other_lines_are_left_as_they_are():
    text = f'01 X PIC X VALUE "{DOLLAR}".\n'
    assert shield_column_7(text) is text


def test_prepare_free_source_rewrites_the_file(tmp_path: Path):
    path = tmp_path / "P.cbl"
    path.write_text(f'    " {DOLLAR}".\n')
    assert prepare_free_source(path)[6] != DOLLAR
    assert path.read_text()[6] != DOLLAR
    assert prepare_free_source(tmp_path / "missing.cbl") == ""
