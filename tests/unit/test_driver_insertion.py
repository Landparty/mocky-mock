"""Where `insert_driver` puts the generated driver into the program:
WORKING-STORAGE fields (declaring the section when there is none),
the PROCEDURE DIVISION header however it is spelled or wrapped, and
a synthetic paragraph header for an unnamed main line.

Regression: bug hunt round 10 (splicer / export / captures).
A program with no WORKING-STORAGE SECTION got no driver fields at
all (UT-CURRENT-CASE, UT-FAIL-COUNT, the tallies were never declared)."""

import re

import pytest

from mockymock.cli.main import main
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.driver import build_driver
from mockymock.splicer.insertion import insert_driver
from mockymock.splicer.naming import TallyRegistry

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
    data = _data_division(insert_driver(lines, _driver_artifact()))
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
    instrumented = [line.strip() for line in insert_driver(lines, _driver_artifact())]
    ws = instrumented.index(f"WORKING-STORAGE{gap}SECTION.")
    proc = instrumented.index(f"PROCEDURE{gap}DIVISION.")
    assert instrumented.count("WORKING-STORAGE SECTION.") == 0
    assert any(line.startswith("01  UT-CURRENT-CASE") for line in instrumented[ws:proc])
    assert any(line.startswith("UT-TESTCASE-") for line in instrumented[proc:])


def _after_driver(lines: list[str]) -> list[str]:
    """The instrumented lines after the last generated UT-TESTCASE body."""
    instrumented = [line.strip() for line in insert_driver(lines, _driver_artifact())]
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
    instrumented = [line.strip() for line in insert_driver(lines, _driver_artifact())]
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
        data = _data_division(insert_driver(lines, _driver_artifact()))
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
    data = _data_division(insert_driver(lines, _driver_artifact()))
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


# Regression: LegacyLens "Create tests" (generate, record, play) over the
# NIST CCVS85 suite, 2026-11-02 (examples/nist-cobol85/generated/README.md).
from mockymock.splicer.headers import (
    is_data_division,
    is_procedure_division,
    is_working_storage,
    starts_header,
)

# --- headers whose words sit on separate lines (NIST NC113M) --------------


def _nist_driver_artifact():
    suite = parse_cut(
        'TESTSUITE "S"\n\nTESTCASE "one"\n    MOCK CALL "SUBPGM"\n'
        "        CONTINUE\n    END-MOCK\n    PERFORM P1\n"
    )
    return build_driver(suite, [], TallyRegistry(suite))


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["PROCEDURE DIVISION."], True),
        (["PROCEDURE  DIVISION USING A."], True),
        (["PROCEDURE", "  DIVISION", "  ."], True),
        (["PROCEDURE", "", "  DIVISION."], True),
        (["PROCEDURE *> note", "DIVISION."], True),
        (["PROCEDURE", "  P1."], False),
        (["*> PROCEDURE DIVISION."], False),
        (["MOVE PROCEDURE-X TO Y."], False),
        (["PROCEDURE"], False),
    ],
)
def test_starts_header_accepts_words_on_separate_lines(lines, expected):
    assert is_procedure_division(lines, 0) is expected


def test_other_headers_split_over_lines():
    assert is_data_division(["  DATA", "  DIVISION."], 0)
    assert is_working_storage(["WORKING-STORAGE", "    SECTION."], 0)
    assert not starts_header(["FILE SECTION."], 0, "WORKING-STORAGE", "SECTION")


def test_driver_goes_after_a_procedure_header_split_over_lines():
    """NC113M writes `PROCEDURE` / `DIVISION` / `.` on three lines: the
    driver was never inserted, so the program ran its own main line outside
    every case and a real CLOSE failed with status 42."""
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. PROG.",
        "  DATA",
        "   DIVISION.",
        "WORKING-STORAGE",
        "   SECTION.",
        "01  WS-A PIC X.",
        "   PROCEDURE",
        "     DIVISION",
        "              .",
        "P1.",
        '    CALL "SUBPGM".',
    ]
    instrumented = [
        line.strip() for line in insert_driver(lines, _nist_driver_artifact())
    ]
    period = instrumented.index(".")
    p1 = instrumented.index("P1.")
    assert any(line.startswith("UT-TESTSUITE-") for line in instrumented[period:p1])
    ws = instrumented.index("SECTION.")
    proc = instrumented.index("PROCEDURE")
    assert any(line.startswith("01  UT-CURRENT-CASE") for line in instrumented[ws:proc])
    assert instrumented.count("WORKING-STORAGE SECTION.") == 0
