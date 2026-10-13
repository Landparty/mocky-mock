"""COBOL names are case-insensitive. cobol-parser upper-cases paragraph and
section names but keeps PERFORM / GO TO targets as written, so a program in
lowercase (`perform read-one`) had every control-flow edge refused as
UNRESOLVED_FLOW_TARGET, every mock as UNMATCHED_MOCK and every terminator
as UNSUPPORTED_TERMINATOR_LAYOUT -- all 17 real-world suites, lowercased,
were refused. `normalize_flow_targets` upper-cases the targets once, right
after parsing."""

from __future__ import annotations

from pathlib import Path

from cobolparser import parse_cobol

from mockymock.analysis.flow_targets import normalize_flow_targets
from mockymock.cli.main import main

_PROGRAM = """\
       identification division.
       program-id. lower.
       environment division.
       input-output section.
       file-control.
           select in-file assign to indd
               file status is ws-fs.
       data division.
       file section.
       fd  in-file.
       01  in-rec.
           05  in-amt          pic 9(5).
       working-storage section.
       01  ws-fs               pic xx.
       01  ws-total            pic 9(7) value 0.
       01  ws-step             pic 9 value 1.
       procedure division.
       main-para.
           perform read-one
           perform tally-section
           perform read-one thru read-one-exit
           goback.
       read-one.
           read in-file
           if ws-fs not = "00"
               go to read-one-exit
           end-if
           add in-amt to ws-total.
       read-one-exit.
           exit.
       tally-section section.
       tally-para.
           add 1 to ws-total.
"""

_CUT = """\
TESTSUITE "lowercase source"
TESTCASE "a lowercase program, upper-case names in the .cut"
    MOCK READ IN-FILE
        MOVE 5 TO IN-AMT
    END-MOCK
    PERFORM MAIN-PARA
    EXPECT WS-TOTAL TO BE 11
"""


def _write(tmp_path: Path) -> tuple[Path, Path]:
    program = tmp_path / "LOWER.cbl"
    program.write_text(_PROGRAM)
    cut = tmp_path / "LOWER.cut"
    cut.write_text(_CUT)
    return program, cut


def test_lint_resolves_lowercase_perform_and_go_to_targets(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    program, cut = _write(tmp_path)

    assert main(["lint", str(program), "--cut", str(cut)]) == 0, capsys.readouterr()


def test_generate_with_data_on_a_lowercase_program_lints_clean(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    program, _ = _write(tmp_path)
    generated = tmp_path / "GEN.cut"

    assert main(["generate", str(program), "--with-data", "-o", str(generated)]) == 0
    capsys.readouterr()
    assert (
        main(["lint", str(program), "--cut", str(generated)]) == 0
    ), capsys.readouterr()


def test_normalize_flow_targets_upper_cases_every_target_field():
    ast = parse_cobol(
        _PROGRAM.replace(
            "       tally-section section.",
            "       done-para.\n"
            "           go to read-one-exit depending on ws-step.\n"
            "       tally-section section.",
        )
    ).ast

    normalize_flow_targets(ast)

    performs = ast.find_all_by_type("PerformStatement")
    gos = ast.find_all_by_type("GoStatement")
    assert [p.target_paragraph for p in performs] == [
        "READ-ONE",
        "TALLY-SECTION",
        "READ-ONE",
    ]
    assert performs[2].thru_paragraph == "READ-ONE-EXIT"
    targets = [list(g.target_paragraphs) or [g.target_paragraph] for g in gos]
    assert targets == [["READ-ONE-EXIT"], ["READ-ONE-EXIT"]]


def test_lint_resolves_lowercase_perform_names_written_in_the_cut(
    tmp_path, monkeypatch, capsys
):
    """Issue #164: the names in the .cut itself are case-insensitive too, as
    they are to cobc -- `PERFORM read-one thru read-one-exit` finds the
    paragraphs, not UNKNOWN_PARAGRAPH."""
    monkeypatch.chdir(tmp_path)
    program, cut = _write(tmp_path)
    cut.write_text(
        _CUT.replace("PERFORM MAIN-PARA", "PERFORM main-para")
        + 'TESTCASE "a lowercase THRU range"\n'
        "    MOCK READ in-file\n"
        "        MOVE 5 TO IN-AMT\n"
        "    END-MOCK\n"
        "    PERFORM read-one THRU Read-One-Exit\n"
        "    EXPECT WS-TOTAL TO BE 5\n"
    )

    assert main(["lint", str(program), "--cut", str(cut)]) == 0, capsys.readouterr()
