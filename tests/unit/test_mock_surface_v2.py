"""v2 mock surface: per-site BoundarySite inventory across all categories."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze, normalize_exec_text
from mockymock.dsl.model import MockCategory

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALLBOUND.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT OUT-FILE ASSIGN TO "OUT.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC             PIC X(20).
       FD  OUT-FILE.
       01  OUT-REC            PIC X(20).

       WORKING-STORAGE SECTION.
       01  WS-CUST-ID         PIC 9(5).
       01  WS-CHOICE          PIC X.
       01  MQ-HCONN           PIC S9(9) COMP.

       PROCEDURE DIVISION.
       OPEN-FILES.
           OPEN INPUT IN-FILE OUTPUT OUT-FILE.

       READ-ONE.
           READ IN-FILE.

       WRITE-ONE.
           WRITE OUT-REC.

       CLOSE-FILES.
           CLOSE IN-FILE OUT-FILE.

       RUN-SQL.
           EXEC SQL
               UPDATE ORDERS SET STATUS = 'Y' WHERE ID = :WS-CUST-ID
           END-EXEC.

       RUN-CICS.
           EXEC CICS
               SEND MAP('ORDMAP')
           END-EXEC.

       RUN-DLI.
           EXEC DLI
               GU SEGMENT-NAME
           END-EXEC.

       PUT-QUEUE.
           CALL "MQPUT" USING MQ-HCONN.

       PLAIN-CALL.
           CALL "DISCRATE" USING WS-CUST-ID.

       ASK-USER.
           ACCEPT WS-CHOICE.
"""


def _surface():
    result = parse_cobol(SOURCE, filename="allbound.cbl")
    assert result.success, result.errors
    return analyze(result.ast)


def _sites(category):
    return [s for s in _surface().boundary_sites if s.category is category]


def test_open_site_carries_all_file_names():
    sites = _sites(MockCategory.OPEN)
    assert len(sites) == 1
    assert set(sites[0].keys) == {"IN-FILE", "OUT-FILE"}
    assert sites[0].paragraph_name == "OPEN-FILES"
    assert sites[0].statement is not None


def test_read_site_keys_on_file_name():
    sites = _sites(MockCategory.READ)
    assert len(sites) == 1
    assert sites[0].keys == ("IN-FILE",)


def test_write_site_keys_on_record_name():
    sites = _sites(MockCategory.WRITE)
    assert len(sites) == 1
    assert sites[0].keys == ("OUT-REC",)


def test_close_site_carries_all_file_names():
    sites = _sites(MockCategory.CLOSE)
    assert len(sites) == 1
    assert set(sites[0].keys) == {"IN-FILE", "OUT-FILE"}


def test_sql_site_match_text_is_normalized():
    sites = _sites(MockCategory.SQL)
    assert len(sites) == 1
    assert sites[0].match_text.startswith("UPDATE ORDERS SET STATUS")


def test_cics_site_match_text_includes_command():
    sites = _sites(MockCategory.CICS)
    assert len(sites) == 1
    assert sites[0].match_text.startswith("SEND MAP")


def test_dli_site_match_text_includes_function():
    sites = _sites(MockCategory.DLI)
    assert len(sites) == 1
    assert sites[0].match_text.startswith("GU")


def test_mq_call_site_is_flagged():
    calls = _sites(MockCategory.CALL)
    mq = [s for s in calls if s.is_mq]
    assert len(mq) == 1
    assert mq[0].keys == ("MQPUT",)


def test_plain_call_site_is_not_mq():
    calls = _sites(MockCategory.CALL)
    plain = [s for s in calls if not s.is_mq]
    assert len(plain) == 1
    assert plain[0].keys == ("DISCRATE",)


def test_console_accept_site_keys_on_target():
    sites = _sites(MockCategory.ACCEPT)
    assert len(sites) == 1
    assert sites[0].keys == ("WS-CHOICE",)


def test_every_boundary_site_has_statement_and_line():
    for site in _surface().boundary_sites:
        assert site.statement is not None
        assert site.line > 0


def test_normalize_exec_text_collapses_whitespace_and_uppercases():
    assert (
        normalize_exec_text("  update\n   Orders   set X = 1 ")
        == "UPDATE ORDERS SET X = 1"
    )
