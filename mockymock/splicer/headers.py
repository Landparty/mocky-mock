"""Division and section headers whose words a program splits over lines.

COBOL lets a header's words sit on separate lines: NIST CCVS85 NC113M
writes its PROCEDURE DIVISION header as

    PROCEDURE
      DIVISION
               .

A splicer stage that looked for `PROCEDURE DIVISION` on one line missed
that header: the test driver was never placed after it, so the program ran
its own main line, outside every test case, with real file I/O (2026-11-02,
"file not open (status = 42)"). Every stage that places code relative to a
header asks `starts_header` instead of matching one line.
"""

from __future__ import annotations


def _code_words(line: str) -> list[str]:
    """The words of `line`'s code, before a `*>` comment."""
    return line.split("*>", 1)[0].split()


def starts_header(lines: list[str], index: int, first: str, second: str) -> bool:
    """Whether a `FIRST SECOND` header (`PROCEDURE DIVISION`,
    `WORKING-STORAGE SECTION`, ...) starts on `lines[index]`: both words on
    that line, or `FIRST` alone on it and `SECOND` opening the next line
    that holds code."""
    words = _code_words(lines[index])
    if not words or words[0].upper() != first:
        return False
    if len(words) > 1:
        return words[1].upper().rstrip(".") == second
    for later in lines[index + 1 :]:
        following = _code_words(later)
        if following:
            return following[0].upper().rstrip(".") == second
    return False


def is_procedure_division(lines: list[str], index: int) -> bool:
    return starts_header(lines, index, "PROCEDURE", "DIVISION")


def is_data_division(lines: list[str], index: int) -> bool:
    return starts_header(lines, index, "DATA", "DIVISION")


def is_working_storage(lines: list[str], index: int) -> bool:
    return starts_header(lines, index, "WORKING-STORAGE", "SECTION")
