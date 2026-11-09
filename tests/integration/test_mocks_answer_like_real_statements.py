"""CICS / file / MQ / SQL cursor mock bug hunt (2026-11-05, round 2): a
mocked statement answers like the real one.

- RESPEIB: a mock body (or ROWS row / TERMINAL group) that sets a CICS
  command's RESP field leaves EIBRESP equal to it (and RESP2 / EIBRESP2),
  as real CICS does; EIBRESP used to read NORMAL. The other way round too.
- MQOK: an MQI call's CompCode and Reason (its last two USING arguments)
  answer MQCC_OK / MQRC_NONE unless the mock sets them, for `MOCK MQ` and
  for a dynamic CALL that can only reach MQI entry points; they used to
  keep the program's own initial value, so an empty MQOPEN mock took the
  "open failed" exit and MQGET ROWS never counted a message.
- REOPEN: CLOSE then OPEN starts a READ ROWS mock again at its first row,
  and an EXEC SQL OPEN a FETCH ROWS mock of that cursor; the second pass
  used to get end of data at once.
- HANDRET: an EXEC CICS XCTL / RETURN in a HANDLE CONDITION handler (a
  GO TO target) ends the case with GOBACK, as a STOP RUN there does; it
  used to be refused UNSUPPORTED_TERMINATOR_LAYOUT.

Fixtures: tests/fixtures/cics_file_mocks/."""

from pathlib import Path

import pytest

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cics_file_mocks"


@requires_docker
@pytest.mark.parametrize(
    ("name", "cases"),
    [("RESPEIB", 3), ("MQOK", 4), ("REOPEN", 2), ("HANDRET", 3)],
)
def test_mock_answers_like_the_real_statement(name, cases, tmp_path, capsys):
    for source in FIXTURES.glob(f"{name}.*"):
        (tmp_path / source.name).write_text(source.read_text())
    rc = main(
        ["run", str(tmp_path / f"{name}.cbl"), "--cut", str(tmp_path / f"{name}.cut")]
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    assert f"{cases} run, 0 failed" in out
