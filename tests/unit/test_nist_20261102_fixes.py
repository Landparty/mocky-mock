"""Fixes found running LegacyLens "Create tests" (generate, record, play)
over the NIST CCVS85 suite on 2026-11-02 (see
examples/nist-cobol85/generated/README.md)."""

from pathlib import Path

import pytest

from mockymock.cli.main import _insert_driver, main
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.driver import build_driver
from mockymock.splicer.headers import (
    is_data_division,
    is_procedure_division,
    is_working_storage,
    starts_header,
)
from mockymock.splicer.naming import TallyRegistry

# --- headers whose words sit on separate lines (NIST NC113M) --------------


def _driver_artifact():
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
    instrumented = [line.strip() for line in _insert_driver(lines, _driver_artifact())]
    period = instrumented.index(".")
    p1 = instrumented.index("P1.")
    assert any(line.startswith("UT-TESTSUITE-") for line in instrumented[period:p1])
    ws = instrumented.index("SECTION.")
    proc = instrumented.index("PROCEDURE")
    assert any(line.startswith("01  UT-CURRENT-CASE") for line in instrumented[ws:proc])
    assert instrumented.count("WORKING-STORAGE SECTION.") == 0


# --- generate: a READ whose rows move nothing (NIST IX301M) ----------------

EMPTY_ROWS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPTYROW.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TFIL ASSIGN TO "TFIL"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS RKEY.
       DATA DIVISION.
       FILE SECTION.
       FD  TFIL.
       01  FREC.
           03 RKEY  PIC X(8).
       WORKING-STORAGE SECTION.
       01  STATE    PIC X(4) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN I-O TFIL.
           PERFORM READ-PARA 3 TIMES.
           CLOSE TFIL.
           STOP RUN.
       READ-PARA.
           READ TFIL INVALID KEY MOVE "INV" TO STATE
               NOT INVALID KEY MOVE "OK" TO STATE.
"""


def _generate(tmp_path: Path, name: str, source: str, capsys) -> tuple[str, str]:
    program = tmp_path / f"{name}.cbl"
    program.write_text(source)
    cut = tmp_path / f"{name}.cut"
    main(["generate", str(program), "-o", str(cut), "--force", "--scenarios", "all"])
    return cut.read_text(), capsys.readouterr().err


def test_read_rows_that_move_nothing_get_no_empty_when(tmp_path, capsys):
    """A keyed READ of a record holding only its key: each generated row
    moved nothing, and `WHEN tally = 1 ... WHEN tally = 10 END-EVALUATE`
    with no statement failed cobc 3.1 ("invalid expression")."""
    text, _ = _generate(tmp_path, "EMPTYROW", EMPTY_ROWS, capsys)
    assert "UT-READ-TFIL-TALLY" not in text
    for case in parse_cut(text).test_cases:
        assert case.perform_target == "MAIN-PARA"


# --- generate: identical cases (72 NIST suites) ----------------------------

FALLS_THROUGH = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FALLS.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN"
               FILE STATUS IS WS-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-CODE  PIC X.
       WORKING-STORAGE SECTION.
       01  WS-STATUS PIC XX.
       01  WS-OUT    PIC X(4).
       PROCEDURE DIVISION.
       START-UP.
           MOVE SPACES TO WS-OUT.
           OPEN INPUT IN-FILE.
       MAIN-LINE.
           READ IN-FILE.
           IF IN-CODE = "A"
               MOVE "AAAA" TO WS-OUT
           ELSE
               MOVE "BBBB" TO WS-OUT
           END-IF.
           CLOSE IN-FILE.
           STOP RUN.
"""


def test_a_first_paragraph_that_runs_on_gets_main_line_cases(tmp_path, capsys):
    """START-UP falls through into MAIN-LINE, where the IF the branch
    scenarios target sits: every case runs the main line THRU the last
    paragraph, so each branch case takes its own branch."""
    text, _ = _generate(tmp_path, "FALLS", FALLS_THROUGH, capsys)
    cases = parse_cut(text).test_cases
    assert {(c.perform_target, c.perform_thru) for c in cases} == {
        ("START-UP", "MAIN-LINE")
    }
    names = [case.name for case in cases]
    assert any("IF@" in name and "THEN" in name for name in names)
    assert any("IF@" in name and "ELSE" in name for name in names)
    assert "left out" not in text


# MAIN-LINE is PERFORMed too, so its STOP RUN cannot end a main-line range,
# and sharing its line with the CLOSE it cannot be spliced into a GOBACK to
# the test either: the cases keep their bare PERFORM START-UP.
PERFORMED_TOO = (
    FALLS_THROUGH.replace(
        "           CLOSE IN-FILE.\n           STOP RUN.\n",
        "           CLOSE IN-FILE. STOP RUN.\n",
    )
    + """       RETRY-PARA.
           PERFORM MAIN-LINE.
"""
)


def test_a_performed_main_line_runs_through_when_its_stop_run_can_goback(
    tmp_path, capsys
):
    """With the STOP RUN on a line of its own, the planner GOBACKs from it to
    the test (the call frame), so the main line runs THRU the last paragraph
    and every branch case takes its own branch."""
    source = FALLS_THROUGH + """       RETRY-PARA.
           PERFORM MAIN-LINE.
"""
    text, _ = _generate(tmp_path, "FALLS", source, capsys)
    cases = parse_cut(text).test_cases
    assert {(c.perform_target, c.perform_thru) for c in cases} == {
        ("START-UP", "RETRY-PARA")
    }
    names = [case.name for case in cases]
    assert any("IF@" in name and "THEN" in name for name in names)
    assert any("IF@" in name and "ELSE" in name for name in names)


def test_scenarios_whose_case_repeats_an_earlier_one_are_left_out(tmp_path, capsys):
    """A case PERFORMs START-UP alone, so every branch case came out
    identical to the happy path under a name claiming a branch it never
    takes (NIST: IX215A ran one case 83 times)."""
    text, err = _generate(tmp_path, "FALLS", PERFORMED_TOO, capsys)
    assert {c.perform_thru for c in parse_cut(text).test_cases} == {None}
    names = [case.name for case in parse_cut(text).test_cases]
    assert "happy path" in names
    assert not any("IF@" in name for name in names)
    assert "scenario(s) left out" in text
    assert "PERFORMs START-UP alone" in err
    bodies = [
        tuple(
            line.strip()
            for line in block.splitlines()[1:]
            if line.strip() and not line.strip().startswith("*>")
        )
        for block in text.split("\nTESTCASE ")[1:]
    ]
    assert len(bodies) == len(set(bodies))


def test_distinct_branch_cases_are_all_kept(tmp_path, capsys):
    """The same program with its main line in one paragraph: every branch
    case differs from the happy path, and none is dropped."""
    source = FALLS_THROUGH.replace(
        "           OPEN INPUT IN-FILE.\n       MAIN-LINE.\n",
        "           OPEN INPUT IN-FILE.\n",
    )
    text, _ = _generate(tmp_path, "FALLS", source, capsys)
    names = [case.name for case in parse_cut(text).test_cases]
    assert any("IF@" in name and "THEN" in name for name in names)
    assert any("IF@" in name and "ELSE" in name for name in names)
    assert "left out" not in text


# --- a WRITE of a record qualified by its file (NIST SQ207M) ---------------


def test_write_of_a_qualified_record_keys_on_the_record_name(tmp_path, capsys):
    """`WRITE PRINT-REC IN PRINT-FILE` made generate write `MOCK WRITE
    PRINT-REC IN PRINT-FILE`, which the .cut grammar cannot parse: the
    whole suite failed to load."""
    source = (
        EMPTY_ROWS.replace(
            "       FD  TFIL.\n       01  FREC.\n           03 RKEY  PIC X(8).\n",
            "       FD  TFIL.\n       01  FREC.\n           03 RKEY  PIC X(8).\n"
            "       FD  PFIL.\n       01  PREC PIC X(10).\n",
        )
        .replace(
            '           SELECT TFIL ASSIGN TO "TFIL"\n',
            '           SELECT PFIL ASSIGN TO "PFIL".\n'
            '           SELECT TFIL ASSIGN TO "TFIL"\n',
        )
        .replace(
            "           CLOSE TFIL.\n",
            "           CLOSE TFIL.\n           OPEN OUTPUT PFIL.\n"
            "           WRITE PREC IN PFIL.\n           WRITE PREC OF PFIL.\n"
            "           CLOSE PFIL.\n",
        )
    )
    text, _ = _generate(tmp_path, "QUALWRT", source, capsys)
    suite = parse_cut(text)
    keys = {(d.category.value, d.key) for d in suite.test_cases[0].mocks}
    assert ("WRITE", "PREC") in keys
    assert not any(" " in key for _, key in keys)
