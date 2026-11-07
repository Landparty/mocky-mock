"""Bug hunt of 2026-11-05 on the .cut suite language and the CLI (analysis
side; tests/integration/test_bug_hunt_20261105_cut_language.py compiles
the same cases on GnuCOBOL).

1. A TESTSUITE / TESTCASE name (or a MOCK SQL key in a VERIFY failure
   message) of a few hundred characters was written into one DISPLAY
   literal: past cobc -free's 512 bytes the line was truncated and the
   instrumented program failed to compile, reported as a mockymock bug.
2. `.cut` text was split with `str.splitlines()`: a form feed (or VT,
   NEL, U+2028) inside a `*>` comment cut the comment in two, its tail
   became an "unrecognized statement", and every later line number was
   one off in lint, stub scanning and the --record-expectations rewrite.
3. An EXPECT / MOVE name declared in two groups (one copybook COPYed
   twice with REPLACING) and not qualified, or qualified by a group it is
   not in, passed lint; cobc then rejected the driver ("ambiguous; needs
   qualification") and mockymock blamed itself.
4. `--coverage-fail-under nan` never failed, `mutate --fail-under nan`
   crashed after the whole run, 150 was accepted; the runner took a
   negative `--poll-interval` (crash on the first idle sleep) or 0.
5. `run --coverage` on a cobc without `--coverage` (GnuCOBOL 3.1) was
   diagnosed as "the code mockymock added broke the compile".
6. A no-break space (pasted from a chat or a document) in a MOCK body line
   was spliced as is: lint passed, cobc failed, mockymock blamed itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mockymock.analysis.cut_names import check_cut_data_names, data_item_paths
from mockymock.analysis.stub_expectations import scan_stub_expectations
from mockymock.cli.checks import run_static_checks
from mockymock.cli.discovery import read_program_line
from mockymock.cli.main import _compile_failure_diagnosis, main
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.driver import build_driver
from mockymock.splicer.naming import TallyRegistry

# --- 1. long names -----------------------------------------------------------

LONG = "n" * 1000


def _driver_lines(cut_text: str) -> list[str]:
    suite = parse_cut(cut_text)
    artifact = build_driver(suite, [], TallyRegistry(suite))
    return artifact.working_storage_lines + artifact.procedure_lines


def test_a_long_testsuite_and_testcase_name_keep_every_line_under_512():
    lines = _driver_lines(
        f'TESTSUITE "{LONG}"\n'
        f'TESTCASE "{LONG}"\n'
        "    PERFORM MAIN-PARA\n"
        "    EXPECT WS-B TO BE 1\n"
    )
    assert max(len(line) for line in lines) < 512
    # The marker still carries the whole name, as concatenated operands.
    start = next(i for i, line in enumerate(lines) if "START: " in line)
    shown = "".join(
        line.strip().removeprefix("DISPLAY ").strip('"')
        for line in lines[start : start + 20]
        if line.strip().startswith(('DISPLAY "', '"'))
    )
    assert LONG in shown


def test_a_long_mock_key_in_a_verify_failure_message_is_split():
    key = "SELECT " + "X" * 600
    lines = _driver_lines(
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        f'    MOCK SQL "{key}"\n'
        "        MOVE 0 TO SQLCODE\n"
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
        f'    VERIFY SQL "{key}" WAS CALLED ONCE\n'
    )
    assert max(len(line) for line in lines) < 512
    assert any("FUNCTION TRIM(UT-TALLY-EDITED)" in line for line in lines)


def test_a_short_name_still_displays_on_one_line():
    lines = _driver_lines('TESTSUITE "s"\nTESTCASE "it\'s ok"\n    PERFORM P\n')
    assert '           DISPLAY "__MOCKYMOCK__ TESTSUITE: s"' in lines
    assert '           DISPLAY "__MOCKYMOCK__ CASE 001 START: it\'s ok"' in lines


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


def test_a_no_break_space_outside_a_literal_becomes_a_blank():
    """6. A no-break space pasted into a MOCK body line was spliced as is;
    cobc read `MOVE<NBSP>7` as one word and the compile failed after lint
    passed. Inside a literal it is data and stays."""
    suite = parse_cut(
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOCK CALL "SUB"\n'
        "        MOVE\u00a07 TO WS-B\u2003\n"
        '        MOVE "a\u00a0b" TO WS-A\n'
        "    END-MOCK\n"
        "    PERFORM\u00a0MAIN-PARA\n"
    )
    body = suite.test_cases[0].mocks[0].body_lines
    assert body == ["MOVE 7 TO WS-B", 'MOVE "a\u00a0b" TO WS-A']
    assert suite.test_cases[0].perform_target == "MAIN-PARA"


# --- 3. ambiguous / wrongly qualified names ---------------------------------

TWICE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWICE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CUST-REC.
           05  CUST-ID        PIC 9(5).
               88 CUST-OK     VALUE 1.
       01  OUTER.
           05  CUST-ID        PIC 9(5).
               88 CUST-OK     VALUE 1.
           05  ONLY-HERE      PIC 9.
       01  WS-B               PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO CUST-ID OF CUST-REC
           GOBACK.
"""


def _problems(tmp_path: Path, cut_text: str, program: str = TWICE) -> list[str]:
    source = tmp_path / "TWICE.cbl"
    source.write_text(program)
    cut = tmp_path / "TWICE.cut"
    cut.write_text(cut_text)
    return run_static_checks(source, cut, None).problems


def test_an_unqualified_name_declared_twice_is_refused_at_its_cut_line(tmp_path):
    problems = _problems(
        tmp_path,
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        "    MOVE CUST-ID TO WS-B\n"
        "    PERFORM MAIN-PARA\n"
        "    EXPECT CUST-ID TO BE 1\n"
        "    EXPECT CUST-OK TO BE TRUE\n",
    )
    ambiguous = [p for p in problems if "AMBIGUOUS_DATA_NAME" in p]
    assert ambiguous == [
        "refused (AMBIGUOUS_DATA_NAME): .cut line 3: MOVE value CUST-ID is "
        "ambiguous in TWICE -- CUST-ID is declared 2 times; qualify it, e.g. "
        "CUST-ID OF CUST-REC or CUST-ID OF OUTER",
        "refused (AMBIGUOUS_DATA_NAME): .cut line 5: EXPECT CUST-ID is "
        "ambiguous in TWICE -- CUST-ID is declared 2 times; qualify it, e.g. "
        "CUST-ID OF CUST-REC or CUST-ID OF OUTER",
        "refused (AMBIGUOUS_DATA_NAME): .cut line 6: EXPECT CUST-OK is "
        "ambiguous in TWICE -- CUST-OK is declared 2 times; qualify it, e.g. "
        "CUST-OK OF CUST-REC or CUST-OK OF OUTER",
    ]


def test_a_qualifier_the_name_is_not_inside_is_refused(tmp_path):
    problems = _problems(
        tmp_path,
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        "    MOVE 4 TO ONLY-HERE OF CUST-REC\n"
        "    PERFORM MAIN-PARA\n"
        "    EXPECT CUST-ID OF WS-B TO BE 1\n",
    )
    ambiguous = [p for p in problems if "AMBIGUOUS_DATA_NAME" in p]
    assert len(ambiguous) == 2
    assert (
        ".cut line 3: MOVE target ONLY-HERE OF CUST-REC names no data item"
        in (ambiguous[0])
    )
    assert "it is declared as ONLY-HERE OF OUTER" in ambiguous[0]
    assert ".cut line 5: EXPECT CUST-ID OF WS-B names no data item" in ambiguous[1]


def test_well_qualified_names_pass(tmp_path):
    problems = _problems(
        tmp_path,
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        "    MOVE 3 TO CUST-ID IN OUTER\n"
        "    MOVE CUST-ID OF CUST-REC TO WS-B\n"
        "    PERFORM MAIN-PARA\n"
        "    EXPECT CUST-ID OF CUST-REC TO BE 1\n"
        "    EXPECT CUST-OK OF CUST-ID OF OUTER TO BE FALSE\n"
        "    EXPECT ONLY-HERE TO BE 0\n"
        "    EXPECT ONLY-HERE OF OUTER TO BE 0\n",
    )
    assert problems == []


def test_a_contained_program_or_an_fd_qualifier_is_left_to_cobc():
    nested = TWICE.replace(
        "           GOBACK.\n",
        "           GOBACK.\n"
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. INNER.\n"
        "       END PROGRAM INNER.\n",
    )
    from cobolparser import parse_cobol

    suite = parse_cut(
        'TESTSUITE "s"\nTESTCASE "c"\n    PERFORM MAIN-PARA\n'
        "    EXPECT CUST-ID TO BE 1\n"
        "    EXPECT CUST-ID OF CUST-REC OF IN-FILE TO BE 1\n"
    )
    single = parse_cobol(TWICE, filename="TWICE.cbl").ast
    reasons = check_cut_data_names(suite, nested.splitlines(), "TWICE", single)
    assert not [r for r in reasons if r.code == "AMBIGUOUS_DATA_NAME"]
    reasons = check_cut_data_names(suite, TWICE.splitlines(), "TWICE", single)
    assert [r.message for r in reasons if r.code == "AMBIGUOUS_DATA_NAME"] == [
        ".cut line 4: EXPECT CUST-ID is ambiguous in TWICE -- CUST-ID is "
        "declared 2 times; qualify it, e.g. CUST-ID OF CUST-REC or "
        "CUST-ID OF OUTER"
    ]
    assert data_item_paths(single)["CUST-OK"] == [
        ("CUST-ID", "CUST-REC"),
        ("CUST-ID", "OUTER"),
    ]


# --- 4. percent and seconds flags -------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "P.cbl", "--coverage-fail-under", "nan"],
        ["run", "P.cbl", "--coverage-fail-under", "150"],
        ["run", "P.cbl", "--coverage-fail-under", "-1"],
        ["mutate", "P.cbl", "--fail-under", "nan"],
        ["mutate", "P.cbl", "--fail-under", "inf"],
        ["runner", "--poll-interval", "-1"],
        ["runner", "--poll-interval", "0"],
        ["runner", "--suite-timeout", "nan"],
    ],
)
def test_out_of_range_numeric_flags_are_refused_up_front(argv, capsys):
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert "must be" in err and argv[-1] in err


def test_a_nan_report_mutation_threshold_is_refused(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "P.cbl").write_text(TWICE)
    (tmp_path / "P.cut").write_text(
        'TESTSUITE "s"\nTESTCASE "c"\n    PERFORM MAIN-PARA\n'
    )
    assert main(["report", "P.cbl", "--mutation-threshold", "nan"]) == 1
    assert "--mutation-threshold must be between 0 and 100" in capsys.readouterr().out


# --- 5. a compile flag the cobc does not know --------------------------------


def test_an_unrecognized_cobc_option_is_not_blamed_on_mockymock(tmp_path):
    class NeverCalled:
        @staticmethod
        def compile_source(path):  # pragma: no cover - must not be reached
            raise AssertionError("the probe compile is not needed")

    diagnosis = _compile_failure_diagnosis(
        NeverCalled,  # type: ignore[arg-type]
        tmp_path,
        ["       PROCEDURE DIVISION."],
        "/opt/gc/bin/cobc: unrecognized option '--coverage'\n",
    )
    assert diagnosis is not None
    assert "does not support --coverage" in diagnosis
    assert "mockymock bug" not in diagnosis
