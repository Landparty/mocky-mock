"""Resource-mock bug hunt (2026-11-05): a mocked statement answers like the
real one when the mock body leaves the outcome alone.

- SQLSTALE: an empty `MOCK SQL` reports SQLCODE 0. It used to leave the
  100 a cursor loop ended on, so the CLOSE after the loop failed.
- DLISTALE: an empty `MOCK DLI` reports a blank DIBSTAT, not the GB a
  get-next loop ended on.
- RCCALL: a mocked CALL (static or dynamic) sets RETURN-CODE to 0, as a
  real CALL does when the callee sets none; it used to keep the caller's
  own earlier value.
- KEYEND: a keyed (random) READ whose ROWS run out reports 23 and runs
  its INVALID KEY clause; it used to report end of file (10), which ran
  neither INVALID KEY nor NOT INVALID KEY. With no FILE STATUS and no
  TERMINAL group, the lifted INVALID KEY clause is accepted as the end
  of the rows (it used to refuse UNRESOLVED_FILE_STATUS_TARGET).
- DYNTAB: `USE REAL CALL` on a dynamic `CALL WS-ENT(WS-I)` tests the entry
  the subscript selects; it used to test `FUNCTION UPPER-CASE(WS-ENT)`,
  the table's first entry, and mocked a call that should have run real.
- CICSCOND: `CONDITION IS NOTFND` sets EIBRESP to 13 before the HANDLE
  CONDITION label (or the IGNORE) takes over; EIBRESP used to read NORMAL.

Fixtures: tests/fixtures/resource_mocks/."""

from pathlib import Path

import pytest

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent.parent / "fixtures" / "resource_mocks"


@requires_docker
@pytest.mark.parametrize(
    ("name", "cases"),
    [
        ("SQLSTALE", 2),
        ("DLISTALE", 1),
        ("RCCALL", 3),
        ("KEYEND", 3),
        ("DYNTAB", 1),
        ("CICSCOND", 2),
    ],
)
def test_resource_mock_answers_like_the_real_statement(name, cases, tmp_path, capsys):
    for source in FIXTURES.glob(f"{name}.*"):
        (tmp_path / source.name).write_text(source.read_text())
    if name == "DYNTAB":
        (tmp_path / "DYNSUB.cbl").write_text((FIXTURES / "DYNSUB.cbl").read_text())
    rc = main(
        ["run", str(tmp_path / f"{name}.cbl"), "--cut", str(tmp_path / f"{name}.cut")]
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    assert f"{cases} run, 0 failed" in out
