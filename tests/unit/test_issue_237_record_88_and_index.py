"""Issue #237: `run --record-expectations` on a stub naming a level-88
condition-name emitted `DISPLAY F-YES` (the whole recording failed to
compile), and on an INDEXED BY index-name wrote a quoted golden
(`EXPECT WS-IDX TO BE "+000000003"`) that failed to compile next run."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock.analysis.stub_expectations import scan_stub_expectations
from mockymock.dsl.parser import parse_cut
from mockymock.report.record_rewrite import (
    build_recording_report,
    condition_names,
    rewrite_cut_text,
)
from mockymock.report.results import TestResult as _TestResult
from mockymock.report.results import TestSuiteResult as _TestSuiteResult
from mockymock.splicer.driver import build_driver
from mockymock.splicer.naming import TallyRegistry

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NP2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG             PIC X VALUE "N".
           88 F-YES            VALUE "Y".
       01  WS-TBL.
           05 WS-ENT PIC X(3) OCCURS 5 TIMES INDEXED BY WS-IDX.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "Y" TO WS-FLAG
           SET WS-IDX TO 3
           GOBACK.
"""

CUT = """\
TESTSUITE "s"
TESTCASE "c"
    PERFORM MAIN-PARA
    *> STUB EXPECT F-YES
    *> STUB EXPECT WS-IDX
"""


def test_condition_names_lists_level_88_items() -> None:
    assert condition_names(parse_cobol(PROGRAM, filename="np2.cbl").ast) == {"F-YES"}


def test_driver_records_an_88_as_its_truth_value() -> None:
    suite = parse_cut(CUT)
    artifact = build_driver(
        suite,
        [],
        TallyRegistry(suite),
        record_targets={1: ["F-YES", "WS-IDX"]},
        condition_names={"F-YES"},
    )
    joined = "\n".join(artifact.procedure_lines)
    assert 'DISPLAY "__MOCKYMOCK__ RECORD 001 F-YES: " F-YES' not in joined
    assert "IF F-YES" in joined
    assert 'DISPLAY "__MOCKYMOCK__ RECORD 001 F-YES: TRUE"' in joined
    assert 'DISPLAY "__MOCKYMOCK__ RECORD 001 F-YES: FALSE"' in joined
    assert 'DISPLAY "__MOCKYMOCK__ RECORD 001 WS-IDX: " WS-IDX' in joined


def test_recorded_88_and_index_render_as_compilable_goldens() -> None:
    scan = scan_stub_expectations(CUT, parse_cut(CUT))
    suite_result = _TestSuiteResult(
        suite_name="s",
        results=[
            _TestResult(
                case_id="001",
                case_name="c",
                recorded=[("F-YES", "TRUE"), ("WS-IDX", "+000000003")],
            )
        ],
    )
    report = build_recording_report(
        scan, suite_result, condition_names={"F-YES"}, index_names={"WS-IDX"}
    )
    assert report.skipped == []
    rewritten = rewrite_cut_text(CUT, report)
    assert rewritten is not None
    assert "EXPECT F-YES TO BE TRUE" in rewritten
    assert "EXPECT WS-IDX TO BE 3" in rewritten
    assert '"+000000003"' not in rewritten
