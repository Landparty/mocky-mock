"""Issue #311: an ACCEPT into a subscripted or qualified item was keyed on
the whole target (`WS-ENT ( WS-I )`, `FLD OF REC-B`), which `MOCK ACCEPT`
cannot spell, so lint's suggestion, --fill and generate all wrote an
unparsable MOCK line. The key is now the data-name alone."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import accept_key, analyze

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TBL.
           05 WS-ENT    PIC X(5) OCCURS 3 TIMES.
       01  WS-I         PIC 9 VALUE 2.
       01  REC-A.
           05 FLD       PIC X(5).
       01  REC-B.
           05 FLD       PIC X(5).
       01  WS-OUT       PIC X(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-ENT(WS-I)
           ACCEPT FLD OF REC-B
           MOVE WS-ENT(2) TO WS-OUT
           GOBACK.
"""


def test_accept_key_is_the_data_name() -> None:
    assert accept_key("WS-ENT ( WS-I )") == "WS-ENT"
    assert accept_key("WS-ENT(WS-I)") == "WS-ENT"
    assert accept_key("FLD OF REC-B") == "FLD"
    assert accept_key("FLD IN REC-B") == "FLD"
    assert accept_key("WS-X") == "WS-X"


def test_accept_sites_are_keyed_on_the_data_name() -> None:
    surface = analyze(parse_cobol(PROGRAM, filename="acc.cbl").ast)
    sites = [s for s in surface.boundary_sites if s.label == "ACCEPT"]
    assert [s.keys for s in sites] == [("WS-ENT",), ("FLD",)]
    assert [s.accept_target for s in sites] == ["WS-ENT ( WS-I )", "FLD OF REC-B"]


def test_generated_scaffolds_parse_and_lint_clean(tmp_path) -> None:
    from mockymock.cli.main import main

    source = tmp_path / "ACC.cbl"
    source.write_text(PROGRAM)
    for flags in ([], ["--per-paragraph"]):
        out = tmp_path / "ACC.cut"
        assert main(["generate", str(source), *flags, "-o", str(out), "--force"]) == 0
        cut = out.read_text()
        assert "MOCK ACCEPT WS-ENT\n" in cut
        assert "MOCK ACCEPT FLD\n" in cut
        assert "INITIALIZE WS-ENT ( WS-I )" in cut  # #330 + #311
        assert main(["lint", str(source), "--cut", str(out)]) == 0
