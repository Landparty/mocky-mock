"""#276: with the `ID DIVISION` abbreviation, export put its provenance
comment block ahead of the CBL/PROCESS card, which IBM requires first."""

from mockymock.cli.main import main
from mockymock.engine.mainframe_export import insert_provenance_header


def test_export_keeps_cbl_card_first_with_id_division(tmp_path):
    cbl = tmp_path / "IDDIV.cbl"
    cbl.write_text(
        "       CBL NODYNAM,LIB\n"
        "       ID DIVISION.\n"
        "       PROGRAM-ID. IDDIV.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PROCESS.\n"
        '           DISPLAY "HI".\n'
    )
    cut = tmp_path / "IDDIV.cut"
    cut.write_text('TESTSUITE "s"\nTESTCASE "c"\n    PERFORM MAIN-PROCESS\n')
    out = tmp_path / "o.cbl"
    assert main(["export", str(cbl), "--cut", str(cut), "--output", str(out)]) == 0
    code = [line for line in out.read_text().splitlines() if line.strip()]
    assert code[0].strip() == "CBL NODYNAM,LIB"
    id_index = next(i for i, line in enumerate(code) if "ID DIVISION" in line)
    assert all(line.lstrip().startswith("*>") for line in code[1:id_index])
    assert id_index > 1  # the header sits between the card and ID DIVISION


def test_header_goes_after_leading_directives_when_no_division_line():
    lines = ["       PROCESS APOST", "       CBL LIB", "       PROGRAM-ID. X."]
    result = insert_provenance_header(lines, ["      *> header"])
    assert result == [
        "       PROCESS APOST",
        "       CBL LIB",
        "      *> header",
        "       PROGRAM-ID. X.",
    ]
