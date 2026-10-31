"""Issue #384: `--record-expectations` recorded a CAPTURE target's initial
value as "the argument passed" for a mocked CALL that never ran."""

from __future__ import annotations

from mockymock.analysis.stub_expectations import scan_stub_expectations
from mockymock.dsl.parser import parse_cut
from mockymock.report.record_rewrite import build_recording_report
from mockymock.report.results import parse_stdout
from mockymock.splicer.driver import build_driver
from mockymock.splicer.naming import TallyRegistry

CUT = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "EOFHOOK"
        CAPTURE ARG 1 INTO UT-CAP-EOFHOOK-1
    END-MOCK
    MOCK CALL "RECHOOK"
        CAPTURE ARG 1 INTO UT-CAP-RECHOOK-1
    END-MOCK
    PERFORM MAIN-PARA
    *> STUB EXPECT UT-CAP-EOFHOOK-1
    *> STUB EXPECT UT-CAP-RECHOOK-1
    *> STUB EXPECT WS-CNT
"""


def test_driver_guards_a_capture_record_with_the_mock_tally() -> None:
    suite = parse_cut(CUT)
    registry = TallyRegistry(suite)
    artifact = build_driver(
        suite,
        [],
        registry,
        record_targets={1: ["UT-CAP-EOFHOOK-1", "UT-CAP-RECHOOK-1", "WS-CNT"]},
    )
    joined = "\n".join(artifact.procedure_lines)
    from mockymock.dsl.model import MockCategory

    tally = registry.name(MockCategory.CALL, "EOFHOOK")
    base = registry.base_name(MockCategory.CALL, "EOFHOOK")
    assert f"IF {tally} = {base}" in joined
    assert '"__MOCKYMOCK__ UNREACHED 001 UT-CAP-EOFHOOK-1"' in joined
    # A plain field is recorded unguarded.
    assert "UNREACHED 001 WS-CNT" not in joined


def test_unreached_capture_is_skipped_not_recorded() -> None:
    suite = parse_cut(CUT)
    scan = scan_stub_expectations(CUT, suite)
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: s\n"
        "__MOCKYMOCK__ CASE 001 START: c\n"
        "__MOCKYMOCK__ UNREACHED 001 UT-CAP-EOFHOOK-1\n"
        "__MOCKYMOCK__ RECORD 001 UT-CAP-RECHOOK-1: ABC\n"
        "__MOCKYMOCK__ VALUE-END\n"
        "__MOCKYMOCK__ RECORD 001 WS-CNT: 001\n"
        "__MOCKYMOCK__ VALUE-END\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
    )
    report = build_recording_report(scan, parse_stdout(stdout))
    assert [r.stub.data_name for r in report.recorded] == [
        "UT-CAP-RECHOOK-1",
        "WS-CNT",
    ]
    (skipped,) = report.skipped
    assert skipped.data_name == "UT-CAP-EOFHOOK-1"
    assert "not reached in this case" in skipped.reason
