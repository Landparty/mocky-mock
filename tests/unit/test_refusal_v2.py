"""v2 refusal gate: mocked boundaries pass, unmocked ones refuse per
category, ambiguity and VERIFY-without-MOCK are caught, nested EXEC is a
whole-program refusal."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import check_nested_exec, check_test_case
from mockymock.dsl.model import (
    MockCategory,
    MockDirective,
    MockTestCase,
    VerifyDirective,
)

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
       01  WS-CHOICE          PIC X.
       01  WS-CUST-ID         PIC 9(5).

       PROCEDURE DIVISION.
       DO-FILE-WORK.
           OPEN INPUT IN-FILE OUTPUT OUT-FILE.
           READ IN-FILE.
           WRITE OUT-REC.
           CLOSE IN-FILE OUT-FILE.

       DO-SQL.
           EXEC SQL
               UPDATE ORDERS SET STATUS = 'Y' WHERE ID = :WS-CUST-ID
           END-EXEC.

       DO-TWO-SQL.
           EXEC SQL
               UPDATE ORDERS SET STATUS = 'Y' WHERE ID = :WS-CUST-ID
           END-EXEC.
           EXEC SQL
               UPDATE CUSTOMERS SET ACTIVE = 'N' WHERE ID = :WS-CUST-ID
           END-EXEC.

       ASK-USER.
           ACCEPT WS-CHOICE.
"""

NESTED_EXEC_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTEXEC.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X VALUE "Y".
       01  WS-CUST-ID         PIC 9(5).

       PROCEDURE DIVISION.
       MAYBE-SQL.
           IF WS-FLAG = "Y"
               EXEC SQL
                   SELECT CUST_ID INTO :WS-CUST-ID FROM CUSTOMERS
               END-EXEC
           END-IF.

       UNRELATED.
           MOVE "N" TO WS-FLAG.
"""


def _surface_and_ast(source=SOURCE):
    result = parse_cobol(source, filename="x.cbl")
    assert result.success, result.errors
    return analyze(result.ast), result.ast


def _file_mocks():
    return [
        MockDirective(MockCategory.OPEN, "IN-FILE"),
        MockDirective(MockCategory.READ, "IN-FILE"),
        MockDirective(MockCategory.WRITE, "OUT-REC"),
        MockDirective(MockCategory.CLOSE, "IN-FILE"),
    ]


def test_fully_mocked_file_paragraph_passes():
    surface, ast = _surface_and_ast()
    case = MockTestCase(name="c", mocks=_file_mocks(), perform_target="DO-FILE-WORK")
    assert check_test_case(surface, ast, case) == []


def test_partially_mocked_file_paragraph_refuses_the_missing_op():
    surface, ast = _surface_and_ast()
    mocks = _file_mocks()[:-1]  # drop CLOSE
    case = MockTestCase(name="c", mocks=mocks, perform_target="DO-FILE-WORK")
    reasons = check_test_case(surface, ast, case)
    assert len(reasons) == 1
    assert reasons[0].code == "UNMOCKED_FILE_OP"
    assert "CLOSE" in reasons[0].message


def test_open_site_matches_by_either_file_name():
    surface, ast = _surface_and_ast()
    mocks = _file_mocks()
    mocks[0] = MockDirective(MockCategory.OPEN, "OUT-FILE")  # second file of the OPEN
    case = MockTestCase(name="c", mocks=mocks, perform_target="DO-FILE-WORK")
    assert check_test_case(surface, ast, case) == []


def test_ambiguous_open_mock_refuses():
    surface, ast = _surface_and_ast()
    mocks = _file_mocks() + [MockDirective(MockCategory.OPEN, "OUT-FILE")]
    case = MockTestCase(name="c", mocks=mocks, perform_target="DO-FILE-WORK")
    reasons = check_test_case(surface, ast, case)
    assert any(r.code == "AMBIGUOUS_MOCK" for r in reasons)


def test_mocked_sql_passes_and_unmocked_sql_refuses():
    surface, ast = _surface_and_ast()
    good = MockTestCase(
        name="c",
        mocks=[MockDirective(MockCategory.SQL, "UPDATE ORDERS")],
        perform_target="DO-SQL",
    )
    assert check_test_case(surface, ast, good) == []

    bad = MockTestCase(name="c", mocks=[], perform_target="DO-SQL")
    reasons = check_test_case(surface, ast, bad)
    assert [r.code for r in reasons] == ["UNMOCKED_SQL"]


def test_sql_prefix_distinguishes_two_statements():
    surface, ast = _surface_and_ast()
    case = MockTestCase(
        name="c",
        mocks=[
            MockDirective(MockCategory.SQL, "UPDATE ORDERS"),
            MockDirective(MockCategory.SQL, "UPDATE CUSTOMERS"),
        ],
        perform_target="DO-TWO-SQL",
    )
    assert check_test_case(surface, ast, case) == []


def test_too_broad_sql_prefix_is_ambiguous():
    surface, ast = _surface_and_ast()
    case = MockTestCase(
        name="c",
        mocks=[
            MockDirective(MockCategory.SQL, "UPDATE"),
            MockDirective(MockCategory.SQL, "UPDATE ORDERS"),
        ],
        perform_target="DO-TWO-SQL",
    )
    reasons = check_test_case(surface, ast, case)
    assert any(r.code == "AMBIGUOUS_MOCK" for r in reasons)


def test_mocked_console_accept_passes():
    surface, ast = _surface_and_ast()
    case = MockTestCase(
        name="c",
        mocks=[MockDirective(MockCategory.ACCEPT, "WS-CHOICE")],
        perform_target="ASK-USER",
    )
    assert check_test_case(surface, ast, case) == []


def test_unmocked_console_accept_refuses():
    surface, ast = _surface_and_ast()
    case = MockTestCase(name="c", mocks=[], perform_target="ASK-USER")
    reasons = check_test_case(surface, ast, case)
    assert [r.code for r in reasons] == ["UNMOCKED_CONSOLE_ACCEPT"]


def test_verify_without_mock_refuses():
    surface, ast = _surface_and_ast()
    case = MockTestCase(
        name="c",
        mocks=[MockDirective(MockCategory.ACCEPT, "WS-CHOICE")],
        perform_target="ASK-USER",
        verifications=[VerifyDirective(MockCategory.READ, "IN-FILE", "ONCE")],
    )
    reasons = check_test_case(surface, ast, case)
    assert any(r.code == "VERIFY_WITHOUT_MOCK" for r in reasons)


def test_verify_with_matching_mock_passes():
    surface, ast = _surface_and_ast()
    case = MockTestCase(
        name="c",
        mocks=[MockDirective(MockCategory.ACCEPT, "WS-CHOICE")],
        perform_target="ASK-USER",
        verifications=[VerifyDirective(MockCategory.ACCEPT, "WS-CHOICE", "ONCE")],
    )
    assert check_test_case(surface, ast, case) == []


def test_unmatched_file_mock_refuses():
    surface, ast = _surface_and_ast()
    case = MockTestCase(
        name="c",
        mocks=[MockDirective(MockCategory.ACCEPT, "WS-CHOICE"),
               MockDirective(MockCategory.READ, "NO-SUCH-FILE")],
        perform_target="ASK-USER",
    )
    reasons = check_test_case(surface, ast, case)
    assert any(r.code == "UNMATCHED_MOCK" for r in reasons)


def test_nested_exec_is_whole_program_refusal():
    surface, _ = _surface_and_ast(NESTED_EXEC_SOURCE)
    reasons = check_nested_exec(surface)
    assert len(reasons) == 1
    assert reasons[0].code == "NESTED_EXEC"
    assert "MAYBE-SQL" in reasons[0].message


def test_clean_program_has_no_nested_exec():
    surface, _ = _surface_and_ast()
    assert check_nested_exec(surface) == []
