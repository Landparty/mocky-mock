"""Issue #351: a boundary a case reaches only by GO TO fall-through is a
lint warning, not a refusal -- and a case that does reach it fails,
naming the boundary, instead of running it for real."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"
CBL = FIXTURES / "fallthrough_boundary.cbl"
CUT = FIXTURES / "fallthrough_boundary.cut"

FALLS_THROUGH = """
TESTCASE "the skip path falls through into the report CALL"
    MOVE 1 TO WS-X
    MOVE 0 TO WS-Y
    MOCK CALL "CALC"
    END-MOCK
    PERFORM PROCESS-REC
    EXPECT WS-Y TO BE 1
"""


def test_lint_warns_instead_of_refusing(capsys):
    assert main(["lint", str(CBL), "--cut", str(CUT)]) == 0
    out = capsys.readouterr().out
    assert "warning (FALLTHROUGH_BOUNDARY)" in out
    assert "refused" not in out


@requires_docker
def test_a_case_that_never_falls_through_passes():
    assert main(["run", str(CBL), "--cut", str(CUT)]) == 0


@requires_docker
def test_a_case_that_falls_through_fails_naming_the_boundary(tmp_path, capsys):
    cut = tmp_path / "fallthrough_boundary.cut"
    cut.write_text(CUT.read_text() + FALLS_THROUGH)
    assert main(["run", str(CBL), "--cut", str(cut)]) == 1
    out = capsys.readouterr().out
    assert "[PASS] the ordinary path needs only the CALL it makes" in out
    assert "unmocked CALL boundary (line 20) reached -- add a MOCK for it" in out
