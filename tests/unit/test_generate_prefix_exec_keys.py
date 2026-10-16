"""Issue #248: when one EXEC site's whole text is a prefix of another's
(SYNCPOINT / SYNCPOINT ROLLBACK, RETURN / RETURN TRANSID(...)), generate
gives both one key, so its own scaffold is not AMBIGUOUS_MOCK."""

from __future__ import annotations

import pytest

from mockymock.cli.main import main

SYN_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SYN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP              PIC S9(8) COMP VALUE 0.
       01  WS-COMM              PIC X(10) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-RESP = 0
               EXEC CICS SYNCPOINT END-EXEC
           ELSE
               EXEC CICS SYNCPOINT ROLLBACK END-EXEC
           END-IF
           IF WS-COMM = SPACES
               EXEC CICS RETURN END-EXEC
           END-IF
           EXEC CICS RETURN TRANSID('ABCD') COMMAREA(WS-COMM)
           END-EXEC.
"""


@pytest.mark.parametrize(
    "extra", [[], ["--with-data", "--seed", "1"], ["--per-paragraph"]]
)
def test_prefix_exec_sites_share_one_directive(tmp_path, capsys, extra) -> None:
    source = tmp_path / "SYN.cbl"
    source.write_text(SYN_CBL)
    cut = tmp_path / "SYN.cut"
    assert main(["generate", str(source), "-o", str(cut), *extra]) == 0
    headers = [
        line.strip() for line in cut.read_text().splitlines() if "MOCK CICS" in line
    ]
    assert sorted(set(headers)) == ['MOCK CICS "RETURN"', 'MOCK CICS "SYNCPOINT"']
    capsys.readouterr()
    assert main(["lint", str(source), "--cut", str(cut)]) == 0
    assert "AMBIGUOUS_MOCK" not in capsys.readouterr().err
