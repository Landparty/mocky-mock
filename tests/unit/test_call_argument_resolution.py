"""CALL mocks the scaffold used to leave incomplete.

- A CALL argument cobol-parser's layout index cannot hold (a group below
  level 01, one element of a table) got a "not resolvable" note and no
  value; `fill_call_arguments` lays it out from the DATA DIVISION.
- A dynamic `CALL WS-PGM-NAME` mock answered every target program the same
  way; when the identifier's possible values are known, the body branches
  on them (`_per_target_body`).
"""

from __future__ import annotations

import pytest

from mockymock.cli.main import main
from mockymock.dsl.call_arguments import fill_call_arguments, is_non_data_argument

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARGPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-PARMS.
               10  WS-CUST-ID     PIC 9(6).
               10  WS-CUST-NAME   PIC X(20).
           05  WS-RC              PIC 9(4).
       01  WS-CODES.
           05  WS-CODE            PIC X(2) OCCURS 5 TIMES.
       01  WS-KEY                 PIC X(8).
       01  WS-I                   PIC 9 VALUE 1.
       01  WS-OUT                 PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           CALL 'RATECALC' USING WS-PARMS WS-CODE(WS-I).
           MOVE WS-CUST-NAME TO WS-OUT.
           IF WS-RC > 0
               DISPLAY 'ERR'
           END-IF.
           GOBACK.
"""

DYNAMIC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PGM-NAME        PIC X(8) VALUE SPACES.
       01  WS-ONE-PGM         PIC X(8) VALUE 'CUSTLKUP'.
       01  WS-RC              PIC 9(4) VALUE 0.
       01  WS-TOTAL           PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           MOVE "PGMA" TO WS-PGM-NAME.
           CALL WS-PGM-NAME USING WS-RC.
           ADD WS-RC TO WS-TOTAL.
           MOVE "PGMB" TO WS-PGM-NAME.
           CALL WS-PGM-NAME USING WS-RC.
           ADD WS-RC TO WS-TOTAL.
           CALL WS-ONE-PGM USING WS-RC.
           GOBACK.
"""


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    (tmp_path / "ARGPROG.cbl").write_text(PROGRAM, encoding="utf-8")
    (tmp_path / "DYNPROG.cbl").write_text(DYNAMIC, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _bundle(*notes: str, fixtures=None) -> dict:
    return {
        "seed": 7,
        "unresolved": list(notes),
        "scenarios": [
            {
                "name": "happy path",
                "entry": "MAIN-PROCESS",
                "fixtures": fixtures or [],
                "expectations": [],
            }
        ],
    }


def test_generate_fills_a_group_and_a_table_element(workdir, capsys):
    assert main(["generate", "ARGPROG.cbl", "-o", "ARGPROG.cut"]) == 0
    text = (workdir / "ARGPROG.cut").read_text(encoding="utf-8")
    err = capsys.readouterr().err
    assert "not resolvable" not in text
    assert "not resolvable" not in err
    # The CALL used to fall back to a placeholder with a key-mismatch warning.
    assert "boundary key mismatch" not in err
    assert "argument WS-PARMS filled from the program's DATA DIVISION" in err
    mock = text[text.index('MOCK CALL "RATECALC"') : text.index("END-MOCK")]
    assert " TO WS-CUST-ID\n" in mock
    assert " TO WS-CUST-NAME\n" in mock
    # Through the argument's own subscript: the element the CALL passes.
    assert " TO WS-CODE(WS-I)\n" in mock
    assert "*> STUB EXPECT WS-PARMS" in text
    assert main(["lint", "ARGPROG.cbl", "--cut", "ARGPROG.cut"]) == 0


def test_existing_fixture_gets_the_fields_added(workdir):
    fixture = {
        "category": "CALL",
        "key": "RATECALC",
        "direction": "",
        "layout": [],
        "sequence": [{}],
        "unresolved": [],
    }
    note = "CALL RATECALC: argument WS-PARMS not resolvable in layout index"
    out, filled = fill_call_arguments(
        _bundle(note, fixtures=[fixture]), "ARGPROG.cbl", None
    )
    assert filled == [
        "CALL RATECALC: argument WS-PARMS filled from the program's DATA DIVISION"
    ]
    assert out["unresolved"] == []
    [only] = out["scenarios"][0]["fixtures"]
    assert [spec["qualified_name"] for spec in only["layout"]] == [
        "WS-AREA.WS-PARMS.WS-CUST-ID",
        "WS-AREA.WS-PARMS.WS-CUST-NAME",
    ]
    assert set(only["sequence"][0]) == {"WS-CUST-ID", "WS-CUST-NAME"}
    # Deterministic for a seed.
    again, _ = fill_call_arguments(
        _bundle(note, fixtures=[dict(fixture, layout=[], sequence=[{}])]),
        "ARGPROG.cbl",
        None,
    )
    assert again["scenarios"][0]["fixtures"][0]["sequence"] == only["sequence"]


def test_cobol_parser_31_note_wording_is_read_too(workdir):
    note = (
        "CALL RATECALC: argument WS-CODE ( WS-I ) is subscripted or "
        "reference-modified -- only part of the item is passed, so no value "
        "is generated for it"
    )
    out, filled = fill_call_arguments(_bundle(note), "ARGPROG.cbl", None)
    assert len(filled) == 1
    [fixture] = out["scenarios"][0]["fixtures"]
    assert [spec["column"] for spec in fixture["layout"]] == ["WS-CODE(WS-I)"]


@pytest.mark.parametrize(
    "argument",
    [
        "WS-KEY ( 1 : 4 )",  # reference modification: part of one item
        "WS-NOWHERE",  # not declared
        "WS-CODE",  # a whole table needs no subscript, but an element does
    ],
)
def test_arguments_that_cannot_be_laid_out_keep_their_note(workdir, argument):
    note = f"CALL RATECALC: argument {argument} not resolvable in layout index"
    out, filled = fill_call_arguments(_bundle(note), "ARGPROG.cbl", None)
    assert filled == []
    assert out["unresolved"] == [note]
    assert out["scenarios"][0]["fixtures"] == []


@pytest.mark.parametrize(
    "argument",
    ["'ABC'", "42", "SPACES", "OMITTED", "LENGTH OF WS-KEY", "ADDRESS OF WS-KEY"],
)
def test_non_data_arguments(argument):
    assert is_non_data_argument(argument)


@pytest.mark.parametrize("argument", ["WS-KEY", "WS-CODE ( WS-I )", "A OF B"])
def test_data_arguments(argument):
    assert not is_non_data_argument(argument)


def test_a_literal_argument_note_is_dropped(workdir):
    note = "CALL RATECALC: argument 'ABC' not resolvable in layout index"
    out, filled = fill_call_arguments(_bundle(note), "ARGPROG.cbl", None)
    assert filled == []
    assert out["unresolved"] == []


def test_a_name_declared_twice_is_not_guessed(tmp_path):
    source = PROGRAM.replace(
        "       01  WS-KEY ",
        "       01  WS-OTHER.\n           05  WS-PARMS PIC X(4).\n       01  WS-KEY ",
    )
    path = tmp_path / "TWICE.cbl"
    path.write_text(source, encoding="utf-8")
    note = "CALL RATECALC: argument WS-PARMS not resolvable in layout index"
    out, filled = fill_call_arguments(_bundle(note), str(path), None)
    assert filled == []
    assert out["unresolved"] == [note]


def test_unreadable_program_leaves_the_bundle_alone(tmp_path):
    note = "CALL RATECALC: argument WS-PARMS not resolvable in layout index"
    bundle = _bundle(note)
    out, filled = fill_call_arguments(bundle, str(tmp_path / "MISSING.cbl"), None)
    assert filled == []
    assert out["unresolved"] == [note]


def test_dynamic_call_branches_on_its_known_targets(workdir):
    for mode in ([], ["--per-paragraph"]):
        assert (
            main(["generate", "DYNPROG.cbl", "-o", "DYNPROG.cut", "--force", *mode])
            == 0
        )
        text = (workdir / "DYNPROG.cut").read_text(encoding="utf-8")
        mock = text[text.index("MOCK CALL WS-PGM-NAME") :]
        mock = mock[: mock.index("END-MOCK")]
        assert '*> WS-PGM-NAME can name "PGMA", "PGMB"' in mock
        assert "EVALUATE WS-PGM-NAME" in mock
        # SPACES is the "no program" sentinel, not a target.
        assert mock.index('WHEN "PGMA"') < mock.index('WHEN "PGMB"')
        assert 'WHEN " "' not in mock
        assert "WHEN OTHER" in mock
        assert mock.rstrip().endswith("END-EVALUATE")
        # One known target: named, not branched on.
        single = text[text.index("MOCK CALL WS-ONE-PGM") :]
        single = single[: single.index("END-MOCK")]
        assert '*> WS-ONE-PGM can name "CUSTLKUP"' in single
        assert "EVALUATE" not in single
        assert main(["lint", "DYNPROG.cbl", "--cut", "DYNPROG.cut"]) == 0


def test_dynamic_call_with_unknown_targets_is_unchanged(tmp_path, monkeypatch):
    source = (
        DYNAMIC.replace('MOVE "PGMA" TO', "MOVE WS-ONE-PGM TO")
        .replace('MOVE "PGMB" TO', "MOVE WS-ONE-PGM TO")
        .replace("VALUE SPACES", "")
    )
    (tmp_path / "UNK.cbl").write_text(source, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["generate", "UNK.cbl", "-o", "UNK.cut", "--per-paragraph"]) == 0
    text = (tmp_path / "UNK.cut").read_text(encoding="utf-8")
    mock = text[text.index("MOCK CALL WS-PGM-NAME") :]
    assert "EVALUATE" not in mock[: mock.index("END-MOCK")]
