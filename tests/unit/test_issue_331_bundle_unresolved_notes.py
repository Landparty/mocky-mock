"""Issue #331: the fixture bundle's own `unresolved` entries (bundle-level
and per fixture) were parsed and then dropped, so a header/detail FD
generated through its first 01 record only produced a scaffold -- and
recorded goldens -- with no hint that the detail layout was never
exercised. They are now written as `*> NOTE:` comments and printed."""

import json
from pathlib import Path

from mockymock.cli.main import main
from mockymock.dsl.parser import parse_cut

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTI.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  HDR-REC.
           05  HDR-TYPE        PIC X.
           05  HDR-DATE        PIC 9(8).
       01  DTL-REC.
           05  DTL-TYPE        PIC X.
           05  DTL-AMT         PIC S9(7)V99 COMP-3.
       WORKING-STORAGE SECTION.
       01  WS-FS               PIC XX.
       01  WS-EOF              PIC X VALUE "N".
       01  WS-TOTAL            PIC S9(9)V99 VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           READ IN-FILE AT END MOVE "Y" TO WS-EOF END-READ
           IF HDR-TYPE NOT = "H"
               ADD DTL-AMT TO WS-TOTAL
           END-IF
           GOBACK.
"""

FIXTURE_NOTE = (
    "READ IN-FILE: the FD has 2 01 records sharing one record area; "
    "alternate view(s) not generated: DTL-REC"
)
SUITE_NOTE = "CONSOLE: something the bundle could not resolve"


def test_bundle_and_fixture_unresolved_are_written_and_printed(tmp_path: Path, capsys):
    cbl = tmp_path / "MULTI.cbl"
    cbl.write_text(PROGRAM)
    bundle_path = tmp_path / "b.json"
    assert main(["fixtures", str(cbl), "--seed", "3"]) == 0
    bundle = json.loads(capsys.readouterr().out)
    bundle["unresolved"] = [SUITE_NOTE, FIXTURE_NOTE]
    for scenario in bundle["scenarios"]:
        for fixture in scenario["fixtures"]:
            if fixture["category"] == "READ":
                fixture["unresolved"] = [FIXTURE_NOTE]
    bundle_path.write_text(json.dumps(bundle))

    out = tmp_path / "M.cut"
    assert (
        main(["generate", str(cbl), "--fixtures", str(bundle_path), "-o", str(out)])
        == 0
    )
    err = capsys.readouterr().err
    assert FIXTURE_NOTE in err and SUITE_NOTE in err

    lines = out.read_text().splitlines()
    assert f"*> NOTE: {SUITE_NOTE}" in lines[:4]
    assert f"*> NOTE: {FIXTURE_NOTE}" not in lines[:4]
    note_at = lines.index(f"    *> NOTE: {FIXTURE_NOTE}")
    assert lines[note_at + 1].strip() == "MOCK READ IN-FILE"
    parse_cut(out.read_text())
