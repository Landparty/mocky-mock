"""Tests for the .cut scaffold generator (all categories, v2)."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import MockSurface, analyze
from mockymock.analysis.refusal import check_test_case
from mockymock.dsl.generator import scaffold_cut
from mockymock.dsl.model import MockCategory
from mockymock.dsl.parser import parse_cut


def _surface_and_ast(source):
    result = parse_cobol(source, filename="x.cbl")
    assert result.success, result.errors
    return analyze(result.ast), result.ast


CALL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDRPROC.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       PROCESS-ORDER.
           CALL "DISCRATE" USING WS-AMOUNT WS-RATE.
           CALL "TAXCALC" USING WS-AMOUNT WS-RATE.
"""

ALL_BOUND_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALLBOUND.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC             PIC X(20).

       WORKING-STORAGE SECTION.
       01  WS-CHOICE          PIC X.
       01  WS-CUST-ID         PIC 9(5).
       01  MQ-HCONN           PIC S9(9) COMP.

       PROCEDURE DIVISION.
       FILE-PARA.
           OPEN INPUT IN-FILE.
           READ IN-FILE.
           CLOSE IN-FILE.

       SQL-PARA.
           EXEC SQL
               UPDATE ORDERS SET STATUS = 'Y' WHERE ID = :WS-CUST-ID
           END-EXEC.
           EXEC SQL
               UPDATE CUSTOMERS SET ACTIVE = 'N' WHERE ID = :WS-CUST-ID
           END-EXEC.

       MQ-PARA.
           CALL "MQPUT" USING MQ-HCONN.

       ASK-PARA.
           ACCEPT WS-CHOICE.
"""


def test_scaffold_contains_one_testcase_per_boundary_paragraph():
    surface, _ = _surface_and_ast(CALL_SOURCE)
    text = scaffold_cut("ORDRPROC", surface)
    assert text.count("TESTCASE") == 1
    assert 'MOCK CALL "DISCRATE"' in text
    assert 'MOCK CALL "TAXCALC"' in text
    assert text.count("PERFORM PROCESS-ORDER") == 1


def test_scaffold_is_valid_cut_syntax():
    surface, _ = _surface_and_ast(CALL_SOURCE)
    suite = parse_cut(scaffold_cut("ORDRPROC", surface))
    assert suite.name == "ORDRPROC"
    assert len(suite.test_cases) == 1
    assert {m.key for m in suite.test_cases[0].mocks} == {"DISCRATE", "TAXCALC"}


def test_scaffold_with_no_boundary_sites_has_no_testcases():
    text = scaffold_cut("EMPTY", MockSurface())
    suite = parse_cut(text)
    assert suite.test_cases == []


def test_scaffold_covers_file_ops():
    surface, _ = _surface_and_ast(ALL_BOUND_SOURCE)
    text = scaffold_cut("ALLBOUND", surface)
    assert "MOCK OPEN IN-FILE" in text
    assert "MOCK READ IN-FILE" in text
    assert "MOCK CLOSE IN-FILE" in text


def test_scaffold_sql_prefixes_are_unique():
    surface, _ = _surface_and_ast(ALL_BOUND_SOURCE)
    text = scaffold_cut("ALLBOUND", surface)
    assert 'MOCK SQL "UPDATE ORDERS"' in text
    assert 'MOCK SQL "UPDATE CUSTOMERS"' in text
    assert "MOVE 0 TO SQLCODE" in text


def test_scaffold_labels_mq_calls():
    surface, _ = _surface_and_ast(ALL_BOUND_SOURCE)
    text = scaffold_cut("ALLBOUND", surface)
    assert 'MOCK MQ "MQPUT"' in text


def test_scaffold_covers_console_accept():
    surface, _ = _surface_and_ast(ALL_BOUND_SOURCE)
    text = scaffold_cut("ALLBOUND", surface)
    assert "MOCK ACCEPT WS-CHOICE" in text
    assert "MOVE SPACES TO WS-CHOICE" in text


def test_scaffold_passes_refusal_gate_for_every_generated_case():
    """End-to-end: every scaffolded TESTCASE must clear check_test_case with
    zero reasons -- the scaffold must never walk users into the gate."""
    surface, ast = _surface_and_ast(ALL_BOUND_SOURCE)
    suite = parse_cut(scaffold_cut("ALLBOUND", surface))
    assert len(suite.test_cases) == 4
    for case in suite.test_cases:
        assert check_test_case(surface, ast, case) == [], case.name


def test_scaffold_dedupes_two_calls_to_same_program_in_one_paragraph():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMEPARA.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.

       PROCEDURE DIVISION.
       PARA-ONE.
           CALL "DISCRATE" USING WS-AMOUNT.
           CALL "DISCRATE" USING WS-AMOUNT.
"""
    surface, _ = _surface_and_ast(source)
    text = scaffold_cut("SAMEPARA", surface)
    assert text.count("TESTCASE") == 1
    assert text.count('MOCK CALL "DISCRATE"') == 1


def test_scaffold_mq_directive_parses_back_as_call_category():
    surface, _ = _surface_and_ast(ALL_BOUND_SOURCE)
    suite = parse_cut(scaffold_cut("ALLBOUND", surface))
    mq_case = next(c for c in suite.test_cases if "MQ-PARA" in c.name)
    assert mq_case.mocks[0].category is MockCategory.CALL
    assert mq_case.mocks[0].key == "MQPUT"
