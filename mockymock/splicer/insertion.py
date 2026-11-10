"""Driver insertion: put the generated test driver into a copy of the
program under test.

`insert_driver` adds the driver's WORKING-STORAGE fields and its
PROCEDURE DIVISION paragraphs to spliced source lines; the helpers below
it are the small COBOL rewrites that insertion needs (marking the program
RECURSIVE for a call-frame driver, commenting out obsolete comment
entries, the end-of-program trap). Every pipeline that builds an
instrumented program goes through here, via `engine.build`."""

from __future__ import annotations

import re

from mockymock.analysis.flow_targets import ORIGINAL_ENTRY_PARAGRAPH
from mockymock.splicer.headers import (
    is_data_division,
    is_procedure_division,
    is_working_storage,
)


def insert_driver(lines: list[str], artifact) -> list[str]:
    """Insert WORKING-STORAGE additions after that section's header, and
    procedure_lines right after the PROCEDURE DIVISION header."""
    return insert_driver_with_origins(lines, artifact)[0]


def insert_driver_with_origins(
    lines: list[str], artifact
) -> tuple[list[str], set[int]]:
    """`insert_driver`, plus the 0-based indices of the lines it inserted.

    `export` needs those indices to say truthfully where an over-long line
    came from: mockymock's own generated driver (notably the
    WORKING-STORAGE reset, which re-serializes a long VALUE clause onto one
    line) is a routine overflow source, and it is not something any `.cut`
    edit can fix. Knowing the exact inserted range is what keeps that
    attribution a fact rather than a guess."""
    lines = comment_out_comment_entries(lines)
    if getattr(artifact, "call_frame", False):
        lines = mark_recursive(lines)
    result: list[str] = []
    inserted: set[int] = set()
    inserted_ws = False
    inserted_proc = False

    def extend(new_lines) -> None:
        for new_line in new_lines:
            inserted.add(len(result))
            result.append(new_line)

    ws_lines = [f"       {ws_line}" for ws_line in artifact.working_storage_lines]
    # A program with no WORKING-STORAGE SECTION of its own (a subprogram
    # with only a LINKAGE or LOCAL-STORAGE SECTION, or no DATA DIVISION at
    # all) still needs the driver's fields declared -- without them every
    # UT-CURRENT-CASE / UT-FAIL-COUNT / tally reference is undefined and
    # the instrumented program cannot compile. Such a section is then
    # synthesized where WORKING-STORAGE belongs: before the first section
    # that must follow it, or before the PROCEDURE DIVISION.
    has_ws = any(
        is_working_storage(lines, index)
        for index in range(_first_procedure_index(lines))
    )
    seen_data_division = False
    entry_check_at: int | None = None
    after_declaratives: bool | None = None
    header_open = False
    header_ws = False

    for index, line in enumerate(lines):
        if index == entry_check_at and _starts_unnamed_code(lines, index):
            # Statements straight after the PROCEDURE DIVISION header, with
            # no paragraph name of their own, would otherwise read as more
            # sentences of the last UT-TESTCASE paragraph -- the main line
            # (and its STOP RUN) ran after the last case and SUMMARY never
            # printed (issue #264). A header makes them a paragraph nothing
            # performs.
            extend([f"       {_ORIGINAL_ENTRY_PARAGRAPH}."])
        if not inserted_ws and not has_ws:
            if is_data_division(lines, index):
                seen_data_division = True
            elif (
                seen_data_division and _AFTER_WS_SECTION_RE.match(line)
            ) or is_procedure_division(lines, index):
                if not seen_data_division:
                    extend(["       DATA DIVISION."])
                extend(["       WORKING-STORAGE SECTION."])
                extend(ws_lines)
                inserted_ws = True
        result.append(line)
        if not inserted_ws and is_working_storage(lines, index):
            header_ws = True
        if header_ws and not inserted_ws and _ends_sentence(line):
            # After the header's period: `WORKING-STORAGE` / `SECTION.`
            # split over lines (see splicer.headers).
            extend(ws_lines)
            inserted_ws = True
        if not inserted_proc and is_procedure_division(lines, index):
            # Also a header whose words sit on separate lines
            # (`PROCEDURE` / `DIVISION` / `.`, NIST NC113M): missing it left
            # the program running its own main line outside every case.
            header_open = True
        if header_open and not inserted_proc and _ends_sentence(line):
            if after_declaratives is None:
                after_declaratives = _opens_declaratives(lines, index + 1)
            if after_declaratives and not _END_DECLARATIVES_RE.search(
                line.split("*>", 1)[0]
            ):
                # DECLARATIVES must open the PROCEDURE DIVISION: the driver
                # goes after `END DECLARATIVES.` (2026-11-03).
                continue
            # After the header's period, not its first line: a header
            # wrapped onto later lines (`PROCEDURE DIVISION` / `USING
            # LK-A.`) had the driver spliced into it (cobc: syntax error).
            extend([""])
            extend(artifact.procedure_lines)
            inserted_proc = True
            entry_check_at = index + 1
    if inserted_proc:
        _insert_end_of_program_trap(
            result, inserted, program_end=getattr(artifact, "program_end", False)
        )
    return result, inserted


_PROGRAM_ID_RE = re.compile(
    r'(PROGRAM-ID\s*\.\s*)("[^"]*"|\'[^\']*\'|[A-Z0-9][A-Z0-9_-]*)(\s*\.)',
    re.IGNORECASE,
)


_PROGRAM_ID_NAME_LINE_RE = re.compile(
    r'^(\s*)("[^"]*"|\'[^\']*\'|[A-Z0-9][A-Z0-9_-]*)(\s*\.)', re.IGNORECASE
)


def mark_recursive(lines: list[str]) -> list[str]:
    """`lines` with the first PROGRAM-ID marked `IS RECURSIVE`: a
    call-frame driver CALLs the program's own entry for every case
    (`driver.call_frame_lines`), and a program that is not RECURSIVE may
    not be CALLed while it runs. An INITIAL or already RECURSIVE program
    is left as it is."""
    result = list(lines)
    for index, line in enumerate(lines):
        code = line.split("*>", 1)[0]
        if "PROGRAM-ID" not in code.upper():
            continue
        if re.search(r"\b(RECURSIVE|INITIAL)\b", code, re.IGNORECASE):
            return result
        if _PROGRAM_ID_RE.search(line):
            result[index] = _PROGRAM_ID_RE.sub(r"\1\2 IS RECURSIVE\3", line, count=1)
            return result
        # `PROGRAM-ID.` with the name on a line of its own (NIST IC222A).
        for after in range(index + 1, min(index + 4, len(lines))):
            following = lines[after].split("*>", 1)[0]
            if not following.strip():
                continue
            if re.search(r"\b(RECURSIVE|INITIAL)\b", following, re.IGNORECASE):
                return result
            result[after] = _PROGRAM_ID_NAME_LINE_RE.sub(
                r"\1\2 IS RECURSIVE\3", lines[after], count=1
            )
            return result
        return result
    return result


_DECLARATIVES_RE = re.compile(r"^\s*DECLARATIVES\s*\.", re.IGNORECASE)


_END_DECLARATIVES_RE = re.compile(r"\bEND\s+DECLARATIVES\s*\.", re.IGNORECASE)


def _opens_declaratives(lines: list[str], start: int) -> bool:
    """Whether the first code line at or after `start` is `DECLARATIVES.`."""
    for line in lines[start:]:
        code = line.split("*>", 1)[0]
        if not code.strip() or (
            len(line) > 6 and line[6] in "*/" and not line[:6].strip()
        ):
            continue
        return _DECLARATIVES_RE.match(code) is not None
    return False


#: An IDENTIFICATION DIVISION paragraph whose body is a comment-entry.
_COMMENT_ENTRY_RE = re.compile(
    r"^(\s*)(AUTHOR|INSTALLATION|DATE-WRITTEN|DATE-COMPILED|SECURITY|REMARKS)" r"\s*\.",
    re.IGNORECASE,
)


def comment_out_comment_entries(lines: list[str]) -> list[str]:
    """`lines` with the continuation lines of every comment-entry (`AUTHOR.`
    / `INSTALLATION.` / ... followed by free text in Area B, NIST SG101A's
    `FEDERAL COMPILER TESTING CENTER.`) turned into `*>` comments, line for
    line. A fixed-format compiler ends a comment-entry at the next Area A
    word; in the free-form source mockymock compiles, cobc read the text
    as code. A continuation line is one indented deeper than its header,
    up to the first that is not; only the IDENTIFICATION DIVISION (before
    the first other DIVISION header) is looked at."""
    result = list(lines)
    header_indent: int | None = None
    for index, line in enumerate(lines):
        code = line.split("*>", 1)[0]
        if not code.strip():
            continue
        indent = len(code) - len(code.lstrip())
        if header_indent is not None and indent > header_indent:
            # Division headers too: NIST OBNC1M writes a whole program in
            # Area B of its SECURITY paragraph.
            if len(line) > 6 and line[6] in "*/" and not line[:6].strip():
                continue  # a fixed-format comment line already
            result[index] = "      *> " + line.strip()
            continue
        if re.search(r"\b(ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", code, re.I):
            break
        header_indent = None
        match = _COMMENT_ENTRY_RE.match(code)
        if match is not None:
            header_indent = len(match.group(1))
    return result


def _ends_sentence(line: str) -> bool:
    """Whether `line`'s code (before a `*>` comment) holds a period that
    ends a sentence."""
    return re.search(r"\.(?=\s|$)", line.split("*>", 1)[0]) is not None


def _insert_end_of_program_trap(
    result: list[str], inserted: set[int], program_end: bool = False
) -> None:
    """Put `driver.end_of_program_trap_lines()` after the program's last
    line of code: before its `END PROGRAM`, or at the end of the source.
    `inserted` is renumbered for the lines it pushes down. With
    `program_end` (`DriverArtifact.program_end`), the `UT-PROGRAM-END`
    paragraph a main-line case runs THRU goes first, so it ends the
    program's own last SECTION rather than the trap's."""
    from mockymock.splicer.driver import end_of_program_lines_for

    start = _first_procedure_index(result)
    at = len(result)
    for index in range(start, len(result)):
        # The end of this program's PROCEDURE DIVISION: its END PROGRAM, or
        # the first program nested in it (2026-11-03, NIST IC2xx).
        if _END_PROGRAM_RE.match(result[index]) or _ID_DIVISION_RE.match(result[index]):
            at = index
            break
    trap = end_of_program_lines_for(program_end)
    # A program may end on a sentence with no period (cobc accepts that at
    # the end of the source); the trap's header would then read as more of
    # that statement. Close it -- only then, as a redundant period warns.
    for line in reversed(result[start + 1 : at]):
        code = line.split("*>", 1)[0].rstrip()
        fixed_comment = len(line) > 6 and line[6] in "*/"
        if code.strip() and not fixed_comment and not code.lstrip().startswith("*"):
            if not code.endswith("."):
                trap = ["           ."] + trap
            break
    shifted = {i + len(trap) if i >= at else i for i in inserted}
    inserted.clear()
    inserted.update(shifted)
    inserted.update(range(at, at + len(trap)))
    result[at:at] = trap


#: The paragraph header `_insert_driver_with_origins` gives a PROCEDURE
#: DIVISION main line that has no paragraph name of its own; the parsed
#: program carries the same name (`name_unnamed_main_line`, #385).
_ORIGINAL_ENTRY_PARAGRAPH = ORIGINAL_ENTRY_PARAGRAPH


#: A paragraph or SECTION header: one word (or `<word> SECTION`) and a
#: period, optionally followed by the paragraph's first sentence.
_PROCEDURE_HEADER_RE = re.compile(
    r"^\s*(?P<name>[A-Z0-9][A-Z0-9-]*)(?:\s+SECTION(?:\s+\d+)?)?\s*\.(?:\s|$)",
    re.IGNORECASE,
)


#: One-word statements that look like a header: `EXIT.`, `GOBACK.`, ...
_HEADER_LOOKALIKE_VERBS = frozenset(
    {"CONTINUE", "EJECT", "EXIT", "GOBACK", "SKIP1", "SKIP2", "SKIP3"}
)


def _starts_unnamed_code(lines: list[str], index: int) -> bool:
    """Whether the first code line from `index` on (the line after the
    PROCEDURE DIVISION header) is a statement rather than a paragraph or
    SECTION header, DECLARATIVES, or END PROGRAM. A header missed here
    only costs an empty extra paragraph; a statement missed would run
    inside the last test case, so the check leans towards inserting.
    False when the header line itself had no period (a USING list still
    running onto the next lines: inserting there would split it)."""
    header = lines[index - 1].split("*>", 1)[0]
    if "." not in header:
        return False
    for line in lines[index:]:
        text = line.split("*>", 1)[0].strip()
        if not text:
            continue
        upper = text.upper()
        if upper.startswith(("DECLARATIVES", "END PROGRAM")):
            return False
        m = _PROCEDURE_HEADER_RE.match(text)
        return m is None or m.group("name").upper() in _HEADER_LOOKALIKE_VERBS
    return False


# Any whitespace may separate a header's two words (`PROCEDURE  DIVISION`,
# a tab): literal single-space checks missed them while cobc, cobolparser
# and the `has_ws` check accepted them, so the driver's fields or
# paragraphs were never inserted (issue #305).
_END_PROGRAM_RE = re.compile(r"^\s*END\s+PROGRAM\b", re.IGNORECASE)


_ID_DIVISION_RE = re.compile(r"^\s*(IDENTIFICATION|ID)\s+DIVISION\b", re.IGNORECASE)


#: DATA DIVISION sections that must come AFTER WORKING-STORAGE -- including a
#: LINKAGE SECTION header `splicer.linkage.neutralize` commented out, whose
#: items then belong to whatever section precedes them.
_AFTER_WS_SECTION_RE = re.compile(
    r"^\s*(?:\*>\s*)?(?:LOCAL-STORAGE|LINKAGE|COMMUNICATION|REPORT|SCREEN)"
    r"\s+SECTION\b",
    re.IGNORECASE,
)


def _first_procedure_index(lines: list[str]) -> int:
    for index in range(len(lines)):
        if is_procedure_division(lines, index):
            return index
    return len(lines)
