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


CURSOR_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CURS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A               PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL FETCH C1 INTO :WS-A END-EXEC.
           EXEC SQL FETCH C10 INTO :WS-A END-EXEC.
           EXEC CICS READ FILE('F') INTO(WS-A) END-EXEC.
           EXEC CICS READQ TS QUEUE('Q') INTO(WS-A) END-EXEC.
"""


def _cursor_sites():
    result = parse_cobol(CURSOR_SOURCE, filename="curs.cbl")
    assert result.success, result.errors
    sites = analyze(result.ast).boundary_sites
    return {s.match_text: s for s in sites if s.label in ("SQL", "CICS")}


def _site(sites, start):
    (site,) = [s for text, s in sites.items() if text.startswith(start + " ")]
    return site


def test_key_does_not_match_a_longer_name_it_is_a_character_prefix_of():
    """`MOCK SQL "FETCH C1"` used to mock `FETCH C10` too (char prefix):
    the other cursor ran on this directive's ROWS instead of refusing
    UNMOCKED_SQL, and mocking both cursors refused AMBIGUOUS_MOCK."""
    sites = _cursor_sites()
    c1, c10 = _site(sites, "FETCH C1"), _site(sites, "FETCH C10")
    fetch_c1 = MockDirective(MockCategory.SQL, "FETCH C1")
    fetch_c10 = MockDirective(MockCategory.SQL, "FETCH C10")
    assert directive_matches_site(fetch_c1, c1)
    assert not directive_matches_site(fetch_c1, c10)
    assert directive_matches_site(fetch_c10, c10)
    assert not directive_matches_site(fetch_c10, c1)
    # A whole-word prefix still matches, and so does one ending on punctuation.
    assert directive_matches_site(MockDirective(MockCategory.SQL, "FETCH"), c10)
    assert directive_matches_site(
        MockDirective(MockCategory.SQL, "FETCH C1 INTO :WS-A"), c1
    )


def test_cics_read_key_does_not_match_readq():
    sites = _cursor_sites()
    read, readq = _site(sites, "READ"), _site(sites, "READQ")
    key = MockDirective(MockCategory.CICS, "READ")
    assert directive_matches_site(key, read)
    assert not directive_matches_site(key, readq)
    assert directive_matches_site(MockDirective(MockCategory.CICS, "READ FILE("), read)
