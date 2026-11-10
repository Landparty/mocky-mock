"""#240: `ACCEPT x FROM DATE/TIME/DAY/DAY-OF-WEEK` reads the system clock,
so it could not be pinned (MOCK ACCEPT on it was refused, its message
calling it "deterministic"), and `--record-expectations` recorded today's
value as a golden that failed on a later run.

Option 3 of the issue: such an ACCEPT is an opt-in mockable site (spliced
only when a MOCK names it; an unmocked case runs the real statement), and
recording skips a stub on a clock-filled item its case does not pin."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze, promote_clock_accepts
from mockymock.analysis.refusal import check_test_case
from mockymock.analysis.stub_expectations import StubExpectation, StubScanResult
from mockymock.dsl.model import MockCategory, MockDirective, MockTestCase, MockTestSuite
from mockymock.engine.checks import run_static_checks
from mockymock.report import results as run_results
from mockymock.report.record_rewrite import (
    build_recording_report,
    clock_value_fields,
)
from mockymock.splicer.injector import build_site_dispatch
from mockymock.splicer.naming import TallyRegistry

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLK.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-D   PIC 9(8).
       01 WS-T   PIC 9(8).
       01 WS-NOW PIC X(21).
       01 WS-IN  PIC X(4).
       PROCEDURE DIVISION.
       0000-MAIN.
           ACCEPT WS-D FROM DATE YYYYMMDD
           ACCEPT WS-T FROM TIME
           MOVE FUNCTION CURRENT-DATE TO WS-NOW
           ACCEPT WS-IN
           GOBACK.
"""


def _case(name, *mocks):
    return MockTestCase(name=name, mocks=list(mocks), perform_target="0000-MAIN")


def test_mocked_clock_accept_becomes_an_opt_in_site():
    ast = parse_cobol(SOURCE, filename="CLK.cbl").ast
    surface = analyze(ast)
    mock_d = MockDirective(MockCategory.ACCEPT, "WS-D", body_lines=["MOVE 1 TO WS-D"])
    mock_in = MockDirective(MockCategory.ACCEPT, "WS-IN")
    promoted = promote_clock_accepts(surface, [mock_d, mock_in])
    assert [(s.keys, s.opt_in) for s in promoted] == [(("WS-D",), True)]
    # WS-T is not named by any MOCK: it stays an ordinary statement.
    assert [a.target for a in surface.non_interactive_accepts] == ["WS-T"]
    # A case mocking it is clean, and so is one that does not: that one
    # runs the real ACCEPT.
    assert check_test_case(surface, ast, _case("pinned", mock_d, mock_in)) == []
    assert check_test_case(surface, ast, _case("real", mock_in)) == []

    suite = MockTestSuite(
        name="s",
        test_cases=[_case("pinned", mock_d, mock_in), _case("real", mock_in)],
    )
    dispatch = build_site_dispatch(
        promoted[0],
        suite,
        TallyRegistry(suite),
        passthrough=["ACCEPT WS-D FROM DATE YYYYMMDD"],
    )
    text = "\n".join(dispatch)
    other = text.split("WHEN OTHER", 1)[1]
    assert "ACCEPT WS-D FROM DATE YYYYMMDD" in other
    assert "ERROR" not in other
    assert "MOVE 1 TO WS-D" in text.split("WHEN OTHER", 1)[0]


def test_static_checks_accept_a_mocked_clock_accept(tmp_path):
    cbl = tmp_path / "CLK.cbl"
    cbl.write_text(SOURCE)
    cut = tmp_path / "CLK.cut"
    cut.write_text(
        'TESTSUITE "s"\n'
        'TESTCASE "pinned"\n'
        "    MOCK ACCEPT WS-D\n"
        "        MOVE 20260101 TO WS-D\n"
        "    END-MOCK\n"
        "    MOCK ACCEPT WS-IN\n"
        "    END-MOCK\n"
        "    PERFORM 0000-MAIN\n"
        "    EXPECT WS-D TO BE 20260101\n"
        'TESTCASE "real"\n'
        "    MOCK ACCEPT WS-IN\n"
        "    END-MOCK\n"
        "    PERFORM 0000-MAIN\n"
    )
    checked = run_static_checks(cbl, cut, [])
    assert checked.problems == []


def test_recording_skips_clock_filled_items_a_case_does_not_pin():
    ast = parse_cobol(SOURCE, filename="CLK.cbl").ast
    clock = clock_value_fields(ast)
    assert set(clock) == {"WS-D", "WS-T", "WS-NOW"}
    stubs = [
        StubExpectation(line=10, data_name="WS-D", note=None, case_index=1),
        StubExpectation(line=11, data_name="WS-T", note=None, case_index=1),
        StubExpectation(line=12, data_name="WS-NOW", note=None, case_index=1),
        StubExpectation(line=13, data_name="WS-IN", note=None, case_index=1),
    ]
    result = run_results.TestSuiteResult(
        suite_name="s",
        results=[
            run_results.TestResult(
                case_id="001",
                case_name="c",
                recorded=[
                    ("WS-D", "20260101"),
                    ("WS-T", "05030074"),
                    ("WS-NOW", "2026101605030074+0000"),
                    ("WS-IN", "ABCD"),
                ],
            )
        ],
    )
    report = build_recording_report(
        StubScanResult(stubs=stubs, skipped=[]),
        result,
        clock_fields=clock,
        clock_pinned={(1, "WS-D")},
    )
    assert [r.stub.data_name for r in report.recorded] == ["WS-D", "WS-IN"]
    skipped = {s.data_name: s.reason for s in report.skipped}
    assert set(skipped) == {"WS-T", "WS-NOW"}
    assert "ACCEPT WS-T FROM TIME" in skipped["WS-T"]
    assert "FUNCTION CURRENT-DATE" in skipped["WS-NOW"]
