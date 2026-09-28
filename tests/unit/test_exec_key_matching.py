"""SQL/CICS/DLI mock keys prefix-match a site's EXEC text independently of
the token spacing cobolparser puts into `sql_text` -- which differs between
releases (the published 1.8.x renders `BANK.TRANSACTION_HIST` as
`BANK. TRANSACTION_HIST`) and never matches the source's own spelling of
`(A, B)` / `INTO :WS-A`."""

import pytest
from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import directive_matches_site
from mockymock.dsl.model import MockCategory, MockDirective

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLKEY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A               PIC X(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               INSERT INTO BANK.TRANSACTION_HIST (A, B)
               VALUES (:WS-A, 1)
           END-EXEC.
           EXEC SQL SELECT T.A INTO :WS-A FROM S.T T END-EXEC.
"""


def _sites():
    result = parse_cobol(SOURCE, filename="sqlkey.cbl")
    assert result.success, result.errors
    return [s for s in analyze(result.ast).boundary_sites if s.label == "SQL"]


@pytest.mark.parametrize(
    "key",
    [
        # Spelled exactly as in the program source.
        "INSERT INTO BANK.TRANSACTION_HIST (A, B)",
        "INSERT INTO BANK.TRANSACTION_HIST",
        # Spelled the way cobol-parser 1.8.x renders it (the committed
        # examples/real-world/DEPTMQC.cut has this form).
        "INSERT INTO BANK. TRANSACTION_HIST",
        "insert into bank.transaction_hist ( a, b ) values (:ws-a",
    ],
)
def test_insert_key_matches_whatever_the_token_spacing(key):
    insert, _select = _sites()
    assert directive_matches_site(MockDirective(MockCategory.SQL, key), insert)


@pytest.mark.parametrize(
    "key", ["SELECT T.A INTO :WS-A", "SELECT T. A INTO:WS-A FROM S.T"]
)
def test_select_key_matches_whatever_the_token_spacing(key):
    _insert, select = _sites()
    assert directive_matches_site(MockDirective(MockCategory.SQL, key), select)


def test_a_different_statement_still_does_not_match():
    insert, select = _sites()
    directive = MockDirective(MockCategory.SQL, "INSERT INTO BANK.OTHER")
    assert not directive_matches_site(directive, insert)
    assert not directive_matches_site(directive, select)
