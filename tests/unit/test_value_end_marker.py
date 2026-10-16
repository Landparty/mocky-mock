"""Issue #285: a FAIL / RECORD value holding byte X'0A' splits its marker
across stdout lines; the driver closes each raw-value marker with
VALUE-END and parse_stdout rejoins the lines in between."""

from __future__ import annotations

from mockymock.dsl.parser import parse_cut
from mockymock.report.results import parse_stdout
from mockymock.splicer.driver import VALUE_END_MARKER, build_driver
from mockymock.splicer.naming import TallyRegistry

STDOUT = "\n".join(
    [
        "__MOCKYMOCK__ TESTSUITE: l2",
        "__MOCKYMOCK__ CASE 001 START: rec",
        "__MOCKYMOCK__ RECORD 001 WS-PARMS: AB\x00",
        "XYZ",
        VALUE_END_MARKER,
        "__MOCKYMOCK__ CASE 001 END",
        "__MOCKYMOCK__ CASE 002 START: fail",
        '__MOCKYMOCK__ CASE 002 FAIL: expected WS-PARMS = "Q", got AB\x00',
        "XYZ",
        VALUE_END_MARKER,
        "program output after the value",
        "__MOCKYMOCK__ CASE 002 END",
        "__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=1",
        "",
    ]
)


def test_parse_stdout_rejoins_a_value_split_at_lf() -> None:
    suite = parse_stdout(STDOUT)
    recorded, failed = suite.results
    assert recorded.recorded == [("WS-PARMS", "AB\x00\nXYZ")]
    assert failed.failure_reasons == ['expected WS-PARMS = "Q", got AB\x00\nXYZ']


def test_without_value_end_the_continuation_is_dropped() -> None:
    suite = parse_stdout(STDOUT.replace(VALUE_END_MARKER + "\n", ""))
    assert suite.results[0].recorded == [("WS-PARMS", "AB\x00")]


def test_driver_closes_raw_value_markers() -> None:
    suite = parse_cut(
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        "    PERFORM P\n"
        '    EXPECT WS-A TO BE "X"\n'
        "    EXPECT WS-B TO BE WS-C\n"
    )
    artifact = build_driver(
        suite, [], TallyRegistry(suite), record_targets={1: ["WS-D"]}
    )
    text = "\n".join(artifact.procedure_lines)
    assert text.count(f'DISPLAY "{VALUE_END_MARKER}"') == 3
    record_at = text.index("RECORD 001 WS-D")
    assert text.index(VALUE_END_MARKER, record_at) > record_at
