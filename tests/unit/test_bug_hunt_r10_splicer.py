"""Bug hunt round 10 (splicer / export / captures): each test pins a defect
reproduced through the Python API before it was fixed.

- `export`'s whitespace break split a literal's type prefix off it
  (`X"00"` -> `X "00"`: the identifier X, then an alphanumeric literal).
- `export`'s literal continuation padded between that prefix and the
  opening quote (`MOVE X      "4142..."`), with the same effect.
- A mocked statement whose sentence period was followed by an inline `*>`
  comment lost the period in its replacement, so the EVALUATE ran
  unterminated into the next paragraph header.
- A program with no WORKING-STORAGE SECTION got no driver fields at all
  (UT-CURRENT-CASE, UT-FAIL-COUNT, the tallies were never declared).
- A `UT-CAP-` target for a non-ASCII literal was sized in characters, not
  the bytes PIC X counts, truncating the captured value.
- A `UT-CAP-` mirror of `PIC X(9)` was reset with `MOVE ZERO` (the repeat
  count's 9 read as a numeric symbol), so it read "000000000", not spaces.
"""

from __future__ import annotations

import re

import pytest
from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.cli.main import _insert_driver, main
from mockymock.cli.mainframe_export import COLUMN_LIMIT, fit_within_columns
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.captures import (
    _declaration_for,
    _literal_declaration,
    capture_working_storage_lines,
    plan_captures,
)
from mockymock.splicer.driver import build_driver
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import _span_ends_sentence, splice_program
from mockymock.splicer.source_map import (
    annotate_nested_sites,
    collect_boundaries,
    collect_scope_map,
)

# --- export: literal type prefixes ----------------------------------------


def test_export_whitespace_break_keeps_a_hex_literal_prefix_attached():
    line = (
        " " * 19
        + 'IF WS-RETURN-CODE-FIELD = X"00" MOVE "SUCCESSFUL" TO '
        + "WS-STATUS-MESSAGE-TEXT"
    )
    assert len(line) > COLUMN_LIMIT

    fitted, problems = fit_within_columns([line])

    assert problems == []
    assert all(len(out) <= COLUMN_LIMIT for out in fitted)
    joined = " ".join(fitted)
    assert 'X"00"' in joined
    assert 'X "00"' not in joined
    # Nothing but whitespace changed.
    assert "".join(joined.split()) == "".join(line.split())


def test_export_literal_continuation_pads_before_the_literal_prefix():
    line = " " * 19 + 'MOVE X"4142434445" TO WS-SOME-VERY-LONG-FIELD-NAME-THAT-IS-X'
    assert len(line) > COLUMN_LIMIT

    fitted, problems = fit_within_columns([line])

    assert problems == []
    assert len(fitted) > 1
    assert all(len(out) <= COLUMN_LIMIT for out in fitted)
    # The prefix letter sits directly against its opening quote.
    assert re.search(r'\bX"4142', fitted[0])
    assert not re.search(r"\bX\s+\"", fitted[0])
    # Every continued line still fills exactly to the column limit.
    assert all(len(out) == COLUMN_LIMIT for out in fitted[:-1])


# --- splice: period before an inline comment ------------------------------

INLINE_COMMENT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INLCMT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC X(5).
       01  WS-B                PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       P1.
           CALL "SUBPGM" USING WS-A. *> call it
       P2.
           ADD 1 TO WS-B.
"""

INLINE_COMMENT_CUT = """\
TESTSUITE "S"

TESTCASE "one"
    MOCK CALL "SUBPGM"
        MOVE "HELLO" TO WS-A
    END-MOCK
    PERFORM P1
    EXPECT WS-A TO BE "HELLO"
"""


def test_replacement_keeps_the_sentence_period_before_an_inline_comment():
    result = parse_cobol(INLINE_COMMENT_SOURCE, filename="inlcmt.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(INLINE_COMMENT_SOURCE.splitlines()).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    suite = parse_cut(INLINE_COMMENT_CUT)

    spliced = splice_program(
        lines,
        collect_boundaries(result.ast),
        surface,
        suite,
        TallyRegistry(suite),
    )

    p2 = next(i for i, line in enumerate(spliced) if line.strip() == "P2.")
    previous_code = next(
        line
        for line in reversed(spliced[:p2])
        if line.strip() and not line.lstrip().startswith("*>")
    )
    assert previous_code.strip() == "END-EVALUATE."


def test_span_sentence_end_is_judged_on_code_not_comment_text():
    assert _span_ends_sentence(['CALL "X". *> done'], 1, 1)
    assert _span_ends_sentence(['CALL "X".', "*> trailing note"], 1, 2)
    # `*>` inside a literal is not a comment.
    assert not _span_ends_sentence(['CALL "X*>." USING WS-A'], 1, 1)
    assert not _span_ends_sentence(['CALL "X" *> note.'], 1, 1)


# --- driver: programs with no WORKING-STORAGE SECTION ---------------------


def _driver_artifact():
    suite = parse_cut(
        'TESTSUITE "S"\n\nTESTCASE "one"\n    MOCK CALL "SUBPGM"\n'
        "        CONTINUE\n    END-MOCK\n    PERFORM P1\n"
    )
    registry = TallyRegistry(suite)
    return build_driver(suite, [], registry)


def _data_division(instrumented: list[str]) -> list[str]:
    end = next(
        i
        for i, line in enumerate(instrumented)
        if line.strip().upper().startswith("PROCEDURE DIVISION")
    )
    return [line.strip() for line in instrumented[:end]]


def test_driver_fields_get_a_working_storage_section_when_there_is_none():
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. PROG.",
        "PROCEDURE DIVISION.",
        "P1.",
        '    CALL "SUBPGM".',
    ]
    data = _data_division(_insert_driver(lines, _driver_artifact()))
    assert data[2:4] == ["DATA DIVISION.", "WORKING-STORAGE SECTION."]
    assert any(line.startswith("01  UT-CURRENT-CASE") for line in data)
    assert any(line.startswith("01  UT-SUBPGM-TALLY") for line in data)


@pytest.mark.parametrize("gap", ["  ", "\t"])
def test_headers_with_any_whitespace_between_their_words_get_the_driver(gap):
    """Issue #305: `WORKING-STORAGE  SECTION` / `PROCEDURE\tDIVISION` were
    missed by literal single-space checks, so the driver fields (compile
    failure) or paragraphs (every case NOT RUN) were never inserted."""
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. PROG.",
        f"DATA{gap}DIVISION.",
        f"WORKING-STORAGE{gap}SECTION.",
        "01  WS-A PIC X.",
        f"PROCEDURE{gap}DIVISION.",
        "P1.",
        '    CALL "SUBPGM".',
    ]
    instrumented = [line.strip() for line in _insert_driver(lines, _driver_artifact())]
    ws = instrumented.index(f"WORKING-STORAGE{gap}SECTION.")
    proc = instrumented.index(f"PROCEDURE{gap}DIVISION.")
    assert instrumented.count("WORKING-STORAGE SECTION.") == 0
    assert any(line.startswith("01  UT-CURRENT-CASE") for line in instrumented[ws:proc])
    assert any(line.startswith("UT-TESTCASE-") for line in instrumented[proc:])


def _after_driver(lines: list[str]) -> list[str]:
    """The instrumented lines after the last generated UT-TESTCASE body."""
    instrumented = [line.strip() for line in _insert_driver(lines, _driver_artifact())]
    last_case = max(
        i for i, line in enumerate(instrumented) if line.startswith("UT-TESTCASE-")
    )
    return [line for line in instrumented[last_case:] if line][1:]


@pytest.mark.parametrize(
    "first",
    ["MOVE 1 TO WS-ZZ", "GOBACK.", "EXIT.", 'DISPLAY "X".', "*> note", ""],
)
def test_unnamed_main_line_gets_its_own_paragraph_header(first):
    """Issue #264: statements straight after the PROCEDURE DIVISION header
    became more sentences of the last UT-TESTCASE paragraph, so the main
    line ran after the last case and its STOP RUN hid SUMMARY."""
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. PROG.",
        "PROCEDURE DIVISION.",
        first,
        "    STOP RUN.",
        "P1.",
        '    CALL "SUBPGM".',
    ]
    after = _after_driver(lines)
    # The last case's own body, then the synthetic header before any
    # original line.
    header = after.index("UT-ORIGINAL-ENTRY.")
    original = [line for line in lines[3:] if line.strip()]
    assert after[header + 1 :][: len(original)] == [line.strip() for line in original]
    assert not any(line.strip() in after[:header] for line in original)


@pytest.mark.parametrize(
    "first",
    ["P0.", 'MAIN-PARA. DISPLAY "X".', "A000-MAIN SECTION.", "0100-START."],
)
def test_named_main_line_gets_no_synthetic_header(first):
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. PROG.",
        "PROCEDURE DIVISION.",
        "*> comment",
        first,
        "    PERFORM P1.",
        "P1.",
        '    CALL "SUBPGM".',
    ]
    assert "UT-ORIGINAL-ENTRY." not in _after_driver(lines)


@pytest.mark.parametrize(
    "header",
    [
        ["PROCEDURE DIVISION", "    USING LK-A", "    LK-B."],
        ["PROCEDURE DIVISION USING LK-A", "    LK-B."],
        ["PROCEDURE DIVISION", "    ."],
    ],
)
def test_driver_goes_after_a_wrapped_header_and_before_its_unnamed_body(header):
    """TPCTBIT1: the driver was spliced in after the header's first line,
    inside a header wrapped onto later lines (cobc: syntax error), and the
    unnamed entry body then got no paragraph of its own."""
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. PROG.",
        *header,
        "    PERFORM P1",
        "    GOBACK.",
        "P1.",
        '    CALL "SUBPGM".',
    ]
    instrumented = [line.strip() for line in _insert_driver(lines, _driver_artifact())]
    start = instrumented.index(header[0])
    end = start + len(header) - 1
    assert instrumented[start : end + 1] == [line.strip() for line in header]
    assert any(line.startswith("UT-TESTCASE-") for line in instrumented[end:])
    after = _after_driver(lines)
    assert after[after.index("UT-ORIGINAL-ENTRY.") + 1] == "PERFORM P1"


def test_procedure_division_using_list_running_on_gets_no_header():
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. PROG.",
        "PROCEDURE DIVISION USING LK-A",
        "    LK-B.",
        "P1.",
        '    CALL "SUBPGM".',
    ]
    assert "UT-ORIGINAL-ENTRY." not in _after_driver(lines)


def test_driver_working_storage_goes_before_local_storage_and_linkage():
    for later in ("LOCAL-STORAGE SECTION.", "LINKAGE SECTION.", "*> LINKAGE SECTION."):
        lines = [
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. PROG.",
            "DATA DIVISION.",
            later,
            "01  LS-A                PIC X(5).",
            "PROCEDURE DIVISION.",
            "P1.",
            '    CALL "SUBPGM".',
        ]
        data = _data_division(_insert_driver(lines, _driver_artifact()))
        assert data.count("DATA DIVISION.") == 1
        ws = data.index("WORKING-STORAGE SECTION.")
        assert ws < data.index(later)
        assert any(
            line.startswith("01  UT-CURRENT-CASE")
            for line in data[ws : data.index(later)]
        )


def test_existing_working_storage_is_still_used_as_is():
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. PROG.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01  WS-A PIC X.",
        "PROCEDURE DIVISION.",
    ]
    data = _data_division(_insert_driver(lines, _driver_artifact()))
    assert data.count("WORKING-STORAGE SECTION.") == 1
    assert data[4].startswith("01  UT-CURRENT-CASE")


def test_export_of_a_program_without_working_storage_declares_the_driver(tmp_path):
    program = tmp_path / "NOWS.cbl"
    program.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. NOWS.\n"
        "       PROCEDURE DIVISION.\n"
        "       P1.\n"
        '           CALL "SUBPGM".\n',
        encoding="utf-8",
    )
    cut = tmp_path / "NOWS.cut"
    cut.write_text(
        'TESTSUITE "S"\n\nTESTCASE "one"\n    MOCK CALL "SUBPGM"\n'
        "        CONTINUE\n    END-MOCK\n    PERFORM P1\n"
        '    VERIFY CALL "SUBPGM" WAS CALLED ONCE\n',
        encoding="utf-8",
    )
    out = tmp_path / "out.cbl"
    assert main(["export", str(program), "--cut", str(cut), "-o", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "WORKING-STORAGE SECTION." in text
    assert re.search(r"^\s+01  UT-CURRENT-CASE\s", text, re.MULTILINE)


# --- captures: synthesized field sizing and reset --------------------------


def test_a_non_ascii_literal_capture_is_sized_in_bytes():
    declaration, _ = _literal_declaration("T", '"ÉCOLE"')
    assert declaration == "01  T  PIC X(6)."


def test_a_non_ascii_literal_capture_end_to_end():
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. CAPU.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A               PIC X(5).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        '           CALL "SUBX" USING "ÉCOLE" WS-A.\n'
    )
    cut = (
        'TESTSUITE "S"\n\nTESTCASE "one"\n    MOCK CALL "SUBX"\n'
        "        CAPTURE ARG 1 INTO UT-CAP-SUBX-1\n    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
    )
    result = parse_cobol(source, filename="capu.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    plans, unresolved = plan_captures(result.ast, parse_cut(cut), surface, lines)
    assert unresolved == []
    assert capture_working_storage_lines(plans) == ["01  UT-CAP-SUBX-1  PIC X(6)."]


def test_an_alphanumeric_capture_whose_repeat_count_has_a_9_resets_to_spaces():
    for picture in ("X(9)", "X(19)", "X(90)"):
        built = _declaration_for("T", {"picture": picture, "usage": "DISPLAY"})
        assert built == (f"01  T  PIC {picture}.", "MOVE SPACES TO T")
    assert _declaration_for("T", {"picture": "9(5)", "usage": "DISPLAY"})[1] == (
        "MOVE ZERO TO T"
    )
    assert _declaration_for("T", {"picture": "ZZ9", "usage": "DISPLAY"})[1] == (
        "MOVE ZERO TO T"
    )
