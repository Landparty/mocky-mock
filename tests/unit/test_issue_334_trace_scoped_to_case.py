"""Issue #334: `run --trace` read the whole binary's trace file, so the
statements BEFORE-ALL ran before the case and AFTER-ALL ran after it were
reported as the case's path, and a MOCK: fired by AFTER-ALL was charged to
the last case. The path is now cut to the case's own driver paragraph, and
a MOCK: between cases belongs to no case."""

from mockymock.report.results import parse_stdout
from mockymock.report.trace import case_entries, parse_trace

# Instrumented source: user paragraphs at 1-7, the driver from 9 on.
INSTRUMENTED = [
    "       INIT-PARA.",  # 1
    "           MOVE 100 TO WS-M",  # 2
    "           MOVE 1 TO WS-N.",  # 3
    "       MAIN-PARA.",  # 4
    "           ADD 1 TO WS-N.",  # 5
    "       CLEANUP-PARA.",  # 6
    "           MOVE 0 TO WS-M.",  # 7
    "",  # 8
    "       UT-TESTSUITE-TR.",  # 9
    "           PERFORM INIT-PARA",  # 10
    "           PERFORM UT-TESTCASE-001",  # 11
    "           PERFORM CLEANUP-PARA",  # 12
    "           STOP RUN.",  # 13
    "       UT-TESTCASE-001.",  # 14
    '           MOVE "001" TO UT-CURRENT-CASE',  # 15
    "           PERFORM MAIN-PARA",  # 16
    '           DISPLAY "__MOCKYMOCK__ CASE 001 END".',  # 17
]

TRACE = """\
Source: 'TR.cbl'
Program-Id: TR
Program-Id: TR       | Entry:     TR             | 9
Program-Id: TR       | Paragraph: UT-TESTSUITE-TR | 9
Program-Id: TR       | PERFORM                    | 10
Program-Id: TR       | Paragraph: INIT-PARA       | 1
Program-Id: TR       | MOVE                       | 2
Program-Id: TR       | MOVE                       | 3
Program-Id: TR       | PERFORM                    | 11
Program-Id: TR       | Paragraph: UT-TESTCASE-001 | 14
Program-Id: TR       | MOVE                       | 15
Program-Id: TR       | PERFORM                    | 16
Program-Id: TR       | Paragraph: MAIN-PARA       | 4
Program-Id: TR       | ADD                        | 5
Program-Id: TR       | DISPLAY                    | 17
Program-Id: TR       | PERFORM                    | 12
Program-Id: TR       | Paragraph: CLEANUP-PARA    | 6
Program-Id: TR       | MOVE                       | 7
Program-Id: TR       | STOP RUN                   | 13
"""


def test_trace_is_cut_to_the_case_paragraph():
    scoped = case_entries(parse_trace(TRACE), INSTRUMENTED, "001")
    user_lines = [entry.line for entry in scoped if entry.line <= 7]
    assert user_lines == [4, 5]


def test_unknown_case_id_falls_back_to_the_first_case_paragraph():
    scoped = case_entries(parse_trace(TRACE), INSTRUMENTED, None)
    assert [entry.line for entry in scoped if entry.line <= 7] == [4, 5, 6, 7]
    assert scoped[0].paragraph == "UT-TESTCASE-001"


def test_a_case_that_never_started_has_no_path():
    assert case_entries(parse_trace(TRACE), INSTRUMENTED, "002") == []


def test_after_all_mocks_are_not_charged_to_the_last_case():
    stdout = "\n".join(
        [
            "__MOCKYMOCK__ TESTSUITE: tr",
            "__MOCKYMOCK__ MOCK: CALL 'INIT' (before-all)",
            "__MOCKYMOCK__ CASE 001 START: a",
            "__MOCKYMOCK__ MOCK: CALL 'X'",
            "__MOCKYMOCK__ CASE 001 END",
            "__MOCKYMOCK__ MOCK: CALL 'CLEANUP' (after-all)",
            "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0",
        ]
    )
    result = parse_stdout(stdout)
    assert result.results[0].mock_hits == ["CALL 'X'"]
