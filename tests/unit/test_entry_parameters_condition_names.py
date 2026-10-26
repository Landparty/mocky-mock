"""A subprogram that hands its return code back only through level-88
`SET ... TO TRUE` writes that field all the same: the scaffold stubs it
for an EXPECT, where it used to stub only the fields MOVEd or COMPUTEd
into (xref files the SET under the 88's name, not its variable's)."""

from mockymock.cli.main import main
from mockymock.dsl.entry_parameters import add_entry_parameters

SUBP = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RATE                PIC 9V999 VALUE 0.050.
       LINKAGE SECTION.
       01  LK-AMOUNT              PIC S9(7)V99 COMP-3.
       01  LK-RESULT.
           05  LK-INTEREST        PIC S9(7)V99.
           05  LK-CODE            PIC X(2).
               88  LK-OK          VALUE "00".
               88  LK-NEG         VALUE "99".
       PROCEDURE DIVISION USING LK-AMOUNT LK-RESULT.
       0000-MAIN.
           IF LK-AMOUNT < 0
               SET LK-NEG TO TRUE
               MOVE 0 TO LK-INTEREST
           ELSE
               SET LK-OK TO TRUE
               COMPUTE LK-INTEREST ROUNDED = LK-AMOUNT * WS-RATE
           END-IF
           GOBACK.
"""


def test_a_field_set_through_its_88s_is_stubbed(tmp_path):
    program = tmp_path / "SUBP.cbl"
    program.write_text(SUBP, encoding="utf-8")
    bundle = {
        "seed": 1,
        "scenarios": [{"name": "happy path", "entry": "0000-MAIN"}],
    }
    out = add_entry_parameters(bundle, str(program), None)
    refs = [e["ref"] for e in out["scenarios"][0]["expectations"]]
    assert refs == ["LK-RESULT.LK-INTEREST", "LK-RESULT.LK-CODE"]


def test_generate_writes_the_stub(tmp_path, monkeypatch):
    (tmp_path / "SUBP.cbl").write_text(SUBP, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["generate", "SUBP.cbl", "-o", "SUBP.cut"]) == 0
    text = (tmp_path / "SUBP.cut").read_text(encoding="utf-8")
    assert "*> STUB EXPECT LK-CODE" in text
    assert "STUB EXPECT LK-AMOUNT" not in text
