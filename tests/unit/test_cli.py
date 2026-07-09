"""CLI behavior tests (non-Docker-specific)."""

from mockymock.cli.main import main


def test_generate_reports_terminators_separately_from_unmockable(tmp_path, capsys):
    cbl = tmp_path / "TERMDEMO.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TERMDEMO.\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        "           STOP RUN.\n"
    )
    exit_code = main(["generate", str(cbl)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "STOP RUN/GOBACK site(s) detected" in out
    assert "will be refused" not in out
