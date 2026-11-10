"""SORT/MERGE procedures under mocks (2026-11-03, NIST ST/SM/SG).

MIXSORT: a SORT reading a file (USING) and writing through an OUTPUT
PROCEDURE is mocked on its file side, and the splice PERFORMs the
procedure after the mock, so its own logic runs over the mocked RETURN
rows. PURESORT: a SORT with both procedures is left real. In both, a STOP
RUN reached inside the procedure GOBACKs to the test out of the driver's
call frame, and the next case runs from the start."""

from pathlib import Path

import pytest

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sort_merge"


@requires_docker
@pytest.mark.parametrize("name", ["MIXSORT", "PURESORT"])
def test_procedure_logic_and_its_stop_run_run_under_mocks(name, tmp_path, capsys):
    for suffix in (".cbl", ".cut"):
        (tmp_path / f"{name}{suffix}").write_text(
            (FIXTURES / f"{name}{suffix}").read_text()
        )
    rc = main(
        ["run", str(tmp_path / f"{name}.cbl"), "--cut", str(tmp_path / f"{name}.cut")]
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "3 run, 0 failed" in out


@requires_docker
def test_the_mixed_sort_really_runs_its_output_procedure(tmp_path, capsys):
    """Had the mock skipped the OUTPUT PROCEDURE, WS-COUNT would stay 0."""
    (tmp_path / "MIXSORT.cbl").write_text((FIXTURES / "MIXSORT.cbl").read_text())
    cut = (FIXTURES / "MIXSORT.cut").read_text()
    (tmp_path / "MIXSORT.cut").write_text(
        cut.replace("EXPECT WS-COUNT TO BE 2", "EXPECT WS-COUNT TO BE 0", 1)
    )
    rc = main(
        ["run", str(tmp_path / "MIXSORT.cbl"), "--cut", str(tmp_path / "MIXSORT.cut")]
    )
    assert rc == 1
    assert "expected WS-COUNT = 0, got 2" in capsys.readouterr().out
