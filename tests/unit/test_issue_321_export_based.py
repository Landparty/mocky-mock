"""Issue #321: `export` must not write the GnuCOBOL / Micro Focus-only
BASED clause (or SET ADDRESS OF a WORKING-STORAGE item) that `run` uses
to keep a folded LINKAGE item's rebind (#226). It keeps the IBM-legal
UT-ADDR-SINK redirect instead, warns, and names the item in the
provenance header; `run` still models the rebind."""

from mockymock.cli.main import main
from mockymock.engine.checks import run_static_checks

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RBND.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-BUF              PIC X(10) VALUE "ABCDEFGHIJ".
       01  WS-OUT              PIC X(5).
       LINKAGE SECTION.
       01  LK-VIEW.
           05 LK-FIRST         PIC X(5).
           05 LK-REST          PIC X(5).
       PROCEDURE DIVISION.
       1000-VIEW.
           SET ADDRESS OF LK-VIEW TO ADDRESS OF WS-BUF
           MOVE LK-REST TO WS-OUT.
"""

CUT = """\
TESTSUITE "RBND"

TESTCASE "view"
    PERFORM 1000-VIEW
    EXPECT WS-OUT TO BE "FGHIJ"
"""


def _write(tmp_path):
    cbl = tmp_path / "RBND.cbl"
    cbl.write_text(PROGRAM)
    cut = tmp_path / "RBND.cut"
    cut.write_text(CUT)
    return cbl, cut


def test_export_keeps_the_ibm_legal_redirect_and_says_so(tmp_path, capsys):
    cbl, cut = _write(tmp_path)
    out_path = tmp_path / "RBND.export.cbl"
    assert main(["export", str(cbl), "--cut", str(cut), "-o", str(out_path)]) == 0
    printed = capsys.readouterr().out
    assert "warning: `SET ADDRESS OF` on LK-VIEW is not modelled" in printed
    assert "as a real rebind (BASED" not in printed
    text = out_path.read_text()
    code = [line for line in text.splitlines() if "*>" not in line]
    assert not any(" BASED" in line for line in code)
    assert not any("UT-LKB-" in line for line in code)
    assert any("SET UT-ADDR-SINK" in line for line in code)
    assert "NOT MODELLED HERE" in text
    assert "*>   LK-VIEW" in text


def test_run_still_models_the_rebind(tmp_path):
    cbl, cut = _write(tmp_path)
    checked = run_static_checks(cbl, cut, None)
    assert checked.problems == []
    assert checked.unmodelled_rebinds == []
    assert checked.lines is not None
    assert any("01  LK-VIEW BASED" in line for line in checked.lines)
