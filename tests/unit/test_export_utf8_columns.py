"""#298: `export` measured column 72 in characters, so a non-ASCII TESTCASE
name, EXPECT or MOVE literal produced lines past column 72 bytes -- the unit
a fixed-format compiler actually counts."""

from mockymock.cli.main import main
from mockymock.engine.mainframe_export import COLUMN_LIMIT, fit_within_columns


def _byte_width(line: str) -> int:
    return len(line.encode("utf-8"))


def test_fit_within_columns_measures_bytes_not_characters():
    lines = [
        '           MOVE "' + "é" * 60 + '" TO WS-NAME.',
        '           DISPLAY "' + "Résumé de l’opération " * 3 + '"',
    ]
    fitted, problems = fit_within_columns(lines)
    assert problems == []
    assert all(_byte_width(line) <= COLUMN_LIMIT for line in fitted)
    # A continued line must sit EXACTLY on the limit, in bytes, or the
    # compiler pads the literal with blanks.
    continued = [line for line in fitted if '"ééé' in line and not line.endswith(".")]
    assert continued and all(_byte_width(line) == COLUMN_LIMIT for line in continued)
    # Nothing was lost or split mid-character.
    assert "".join(fitted).count("é") >= 60


def test_export_with_accented_testcase_and_literals_fits_72_bytes(tmp_path):
    cbl = tmp_path / "PROG.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROG.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-NAME PIC X(120).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PROCESS.\n"
        '           DISPLAY "HI".\n',
        encoding="utf-8",
    )
    cut = tmp_path / "PROG.cut"
    accented = "Vérification de l’intégrité des données reçues é"
    cut.write_text(
        'TESTSUITE "s"\n'
        f'TESTCASE "{accented}"\n'
        f'    MOVE "{accented}" TO WS-NAME\n'
        "    PERFORM MAIN-PROCESS\n"
        f'    EXPECT WS-NAME TO BE "{accented}"\n',
        encoding="utf-8",
    )
    out = tmp_path / "out.cbl"
    assert main(["export", str(cbl), "--cut", str(cut), "--output", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "é" in text
    over = [line for line in text.splitlines() if _byte_width(line) > COLUMN_LIMIT]
    over = [line for line in over if not line.lstrip().startswith("*>")]
    assert over == []
