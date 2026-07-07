"""Unit tests for the generalized splice orchestrator."""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.model import MockCategory, MockDirective, MockTestCase, MockTestSuite
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import collect_boundaries

SOURCE = """\
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
       01  WS-EOF             PIC X VALUE "N".
       01  WS-CUST-ID         PIC 9(5).

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE.
           READ IN-FILE
               AT END MOVE "Y" TO WS-EOF
           END-READ.
           CLOSE IN-FILE.

       SQL-PARA.
           EXEC SQL
               UPDATE ORDERS SET STATUS = 'Y' WHERE ID = :WS-CUST-ID
           END-EXEC.

       UNREACHED-SQL.
           EXEC SQL
               DELETE FROM AUDIT WHERE ID = :WS-CUST-ID
           END-EXEC.

       CALL-PARA.
           CALL "DISCRATE" USING WS-CUST-ID.
"""


def _splice(suite):
    result = parse_cobol(SOURCE, filename="allbound.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    normalized = normalize_fixed_format(SOURCE.splitlines())
    lines = normalized.splitlines()
    boundaries = collect_boundaries(result.ast)
    return splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))


def _file_suite():
    case = MockTestCase(
        name="file case",
        mocks=[
            MockDirective(MockCategory.OPEN, "IN-FILE"),
            MockDirective(MockCategory.READ, "IN-FILE", ['MOVE "Y" TO WS-EOF']),
            MockDirective(MockCategory.CLOSE, "IN-FILE"),
            MockDirective(MockCategory.SQL, "UPDATE ORDERS", ["MOVE 0 TO SQLCODE"]),
        ],
        perform_target="MAIN-PARA",
    )
    return MockTestSuite(name="S", test_cases=[case])


def test_mocked_file_statements_are_commented_and_replaced():
    lines = _splice(_file_suite())
    joined = "\n".join(lines)
    assert "      *>     OPEN INPUT IN-FILE." in joined
    assert "      *>     READ IN-FILE" in joined
    # READ's AT END clause is inside the replaced span
    assert '      *>         AT END MOVE "Y" TO WS-EOF' in joined
    assert "      *>     CLOSE IN-FILE." in joined
    assert "ADD 1 TO UT-OPEN-IN-FILE-TALLY" in joined
    assert "ADD 1 TO UT-READ-IN-FILE-TALLY" in joined


def test_mocked_sql_statement_gets_dispatch():
    lines = _splice(_file_suite())
    joined = "\n".join(lines)
    assert "ADD 1 TO UT-SQL-UPDATE-ORDERS-TALLY" in joined
    assert "MOVE 0 TO SQLCODE" in joined


def test_unmocked_exec_sql_is_trap_stubbed_program_wide():
    lines = _splice(_file_suite())
    joined = "\n".join(lines)
    # the unreached DELETE is commented out and trapped, even though no case
    # mocks or reaches it (cobc cannot compile a raw EXEC block)
    assert "      *>     EXEC SQL" in joined
    live_sql = [
        ln
        for ln in lines
        if "DELETE FROM AUDIT" in ln and not ln.strip().startswith("*>")
    ]
    assert live_sql == []
    assert "unmocked EXEC SQL reached" in joined


def test_unmocked_call_is_left_in_place():
    lines = _splice(_file_suite())
    assert any(
        'CALL "DISCRATE"' in ln and not ln.strip().startswith("*>") for ln in lines
    )


def test_sentence_terminating_period_is_preserved():
    lines = _splice(_file_suite())
    # CLOSE IN-FILE. was the last statement of MAIN-PARA -- its replacement
    # block must end with a period so the sentence terminates before SQL-PARA.
    close_idx = next(
        i for i, ln in enumerate(lines) if ln.startswith("      *>     CLOSE IN-FILE.")
    )
    block_end = next(
        i
        for i in range(close_idx + 1, len(lines))
        if lines[i].strip().startswith("END-EVALUATE")
    )
    assert lines[block_end].rstrip().endswith(".")


# --- nested-site splicing ---------------------------------------------------

import pytest

from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

NESTED_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTSPLICE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X.
       01  WS-AMT             PIC 9(5).

       PROCEDURE DIVISION.
       NEST-PARA.
           IF WS-FLAG = "Y"
               CALL "NESTED"
                   USING WS-AMT
           END-IF.
           IF WS-FLAG = "P"
               CALL "PERIODIC" USING WS-AMT.
           IF WS-FLAG = "L"
               CALL "LONELY" USING WS-AMT
           END-IF.
           IF WS-FLAG = "S"
               EXEC SQL
                   UPDATE ORDERS SET STATUS = 'Y' WHERE ID = :WS-AMT
               END-EXEC
           END-IF.
           STOP RUN.
"""


def _splice_nested(suite, annotate=True):
    result = parse_cobol(NESTED_SOURCE, filename="nestsplice.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    normalized = normalize_fixed_format(NESTED_SOURCE.splitlines())
    lines = normalized.splitlines()
    if annotate:
        annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    boundaries = collect_boundaries(result.ast)
    return splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))


def _nested_suite(mocks):
    case = MockTestCase(name="nested", mocks=mocks, perform_target="NEST-PARA")
    return MockTestSuite(name="N", test_cases=[case])


def test_mocked_nested_call_is_spliced_and_end_if_survives():
    lines = _splice_nested(_nested_suite([MockDirective(MockCategory.CALL, "NESTED")]))
    joined = "\n".join(lines)
    assert '      *>         CALL "NESTED"' in joined
    assert "      *>             USING WS-AMT" in joined
    assert "ADD 1 TO UT-NESTED-TALLY" in joined
    # the enclosing block's words are untouched
    assert sum(1 for line in lines if line.strip() == "END-IF.") >= 1
    assert not any(line.startswith('      *>     IF WS-FLAG = "Y"') for line in lines)


def test_nested_span_trailing_period_reattaches():
    lines = _splice_nested(
        _nested_suite([MockDirective(MockCategory.CALL, "PERIODIC")])
    )
    commented = next(line for line in lines if 'CALL "PERIODIC"' in line)
    assert commented.startswith("      *>")
    replacement_end = next(
        line
        for line in lines
        if line.strip().startswith("END-EVALUATE") and line.rstrip().endswith(".")
    )
    assert replacement_end  # dispatch block re-terminates the sentence


def test_unmocked_nested_call_is_left_alone():
    lines = _splice_nested(_nested_suite([MockDirective(MockCategory.CALL, "NESTED")]))
    lonely = next(line for line in lines if 'CALL "LONELY"' in line)
    assert not lonely.startswith("      *>")


def test_unmocked_nested_exec_gets_trap_and_end_exec_commented():
    lines = _splice_nested(_nested_suite([MockDirective(MockCategory.CALL, "NESTED")]))
    joined = "\n".join(lines)
    assert "      *>         EXEC SQL" in joined
    assert "      *>         END-EXEC" in joined
    assert "unmocked EXEC SQL reached" in joined


def test_mocked_nested_site_without_span_raises():
    with pytest.raises(ValueError, match="without a validated span"):
        _splice_nested(
            _nested_suite([MockDirective(MockCategory.CALL, "NESTED")]),
            annotate=False,
        )


# --- SECTION headers survive splicing (audit 2.2) ----------------------------

SECTION_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECSPLICE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMT             PIC 9(5).

       PROCEDURE DIVISION.
       MAIN-SEC SECTION.
       MAIN-PARA.
           CALL "LASTCALL" USING WS-AMT.

       NEXT-SEC SECTION.
       NEXT-PARA.
           DISPLAY "NEXT".
"""


def test_splicing_sections_last_statement_leaves_section_header_live():
    """Audit finding 2.2: the CALL is the last statement before `NEXT-SEC
    SECTION.`; without section-header boundaries its splice span swallowed
    and commented out the header."""
    result = parse_cobol(SECTION_SOURCE, filename="secsplice.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(SECTION_SOURCE.splitlines()).splitlines()
    case = MockTestCase(
        name="sec",
        mocks=[MockDirective(MockCategory.CALL, "LASTCALL")],
        perform_target="MAIN-PARA",
    )
    suite = MockTestSuite(name="SEC", test_cases=[case])
    boundaries = collect_boundaries(result.ast)
    spliced = splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))
    commented_call = [
        ln for ln in spliced if "LASTCALL" in ln and ln.startswith("      *>")
    ]
    assert commented_call  # the CALL itself was spliced
    live_header = [
        ln
        for ln in spliced
        if "NEXT-SEC SECTION" in ln and not ln.strip().startswith("*>")
    ]
    assert live_header  # the following section header stayed live


# --- top-level own-line guard, splicer side (audit 2.1) -----------------------

SHARED_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SHARESPLICE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A               PIC 9(3).

       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A CALL "SHAREPGM" USING WS-A.
"""


def test_mocked_top_level_site_with_layout_problem_raises():
    """Defensive twin of the gate's UNSUPPORTED_MOCK_TARGET_LAYOUT: if an
    annotated shares-its-line top-level site somehow reaches the splicer,
    it raises instead of silently deleting the sibling MOVE."""
    result = parse_cobol(SHARED_LINE_SOURCE, filename="sharesplice.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(SHARED_LINE_SOURCE.splitlines()).splitlines()
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    case = MockTestCase(
        name="share",
        mocks=[MockDirective(MockCategory.CALL, "SHAREPGM")],
        perform_target="MAIN-PARA",
    )
    suite = MockTestSuite(name="SHARE", test_cases=[case])
    boundaries = collect_boundaries(result.ast)
    with pytest.raises(ValueError, match="does not start its own line"):
        splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))
