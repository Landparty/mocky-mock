"""Gaps the cobol-test run on PAYMAIN + PAYCALC found (2026-11-06), the
parts that need no compiler: lint and generate agreeing on cases that only
hold `*> STUB EXPECT` comments, `run --trace` collapsing a spliced
statement and labelling a USE REAL CALL as real, and a filled CALL fixture
carrying a direction. tests/integration/test_open_gaps_2026_11_06.py runs
the same programs through GnuCOBOL."""

import json
import shutil
from pathlib import Path

from mockymock.cli.checks import (
    cases_asserting_nothing,
    no_assertion_warnings,
    stub_case_lines,
)
from mockymock.cli.main import main
from mockymock.dsl.call_arguments import _add_fields
from mockymock.dsl.parser import parse_cut
from mockymock.report.trace import (
    TraceEntry,
    format_trace_console,
    format_trace_json,
)
from mockymock.splicer.injector import REAL_SUFFIX

FIXTURES = Path(__file__).parent.parent / "fixtures" / "open_gaps_2026_11_06"

CUT = """TESTSUITE "T"

TESTCASE "stubbed"
    PERFORM 0000-MAIN
    *> STUB EXPECT WS-A -- set by the program
    *> STUB EXPECT WS-B

TESTCASE "empty"
    PERFORM 0000-MAIN

TESTCASE "asserted"
    PERFORM 0000-MAIN
    EXPECT WS-A TO BE "X"
"""


def test_stub_case_lines_counts_each_case_block():
    suite = parse_cut(CUT)
    assert stub_case_lines(CUT, suite) == {3: 2}


def test_lint_names_the_pending_stubs_generate_leaves_out():
    suite = parse_cut(CUT)
    warnings = no_assertion_warnings(suite, CUT)
    assert len(warnings) == 2
    assert 'TESTCASE "stubbed" asserts nothing yet' in warnings[0]
    assert "2 `*> STUB EXPECT` comment(s)" in warnings[0]
    assert "--record-expectations" in warnings[0]
    assert 'TESTCASE "empty" asserts nothing --' in warnings[1]
    # generate's count: the stubbed case is left out, as before.
    assert cases_asserting_nothing(CUT, stubs_count=True) == [
        '.cut line 8: TESTCASE "empty"'
    ]
    # Without the text (older callers) the wording is unchanged.
    assert all("yet" not in w for w in no_assertion_warnings(suite))


def test_generate_and_lint_counts_now_add_up(tmp_path, monkeypatch, capsys):
    shutil.copy(FIXTURES / "PAYMAIN.cbl", tmp_path / "PAYMAIN.cbl")
    monkeypatch.chdir(tmp_path)
    assert main(["generate", "PAYMAIN.cbl", "--per-paragraph"]) == 0
    out = capsys.readouterr().out
    assert "1 test case(s) assert nothing" in out
    assert "2 test case(s) have no EXPECT yet, only `*> STUB EXPECT`" in out
    main(["lint", "PAYMAIN.cbl"])
    lint = capsys.readouterr().out
    assert lint.count("warning (NO_ASSERTION)") == 3
    assert lint.count("asserts nothing yet") == 2


def _entry(line, statement=None, paragraph=None):
    return TraceEntry(line=line, statement=statement, paragraph=paragraph)


def test_trace_collapses_a_spliced_statement_into_one_entry():
    # Instrumented lines 10-14 are the dispatch block replacing source line
    # 3 (a CALL); 20 is the next statement, line 4.
    entries = [
        _entry(9, paragraph="MAIN"),
        _entry(10, "EVALUATE"),
        _entry(11, "WHEN"),
        _entry(12, "ADD"),
        _entry(13, "DISPLAY"),
        _entry(14, "CALL"),
        _entry(20, "MOVE"),
        _entry(10, "EVALUATE"),  # the same block, run again
        _entry(11, "WHEN"),
    ]
    line_map = {9: 2, 10: 3, 11: 3, 12: 3, 13: 3, 14: 3, 20: 4}
    original = [
        "       MAIN.",
        "       MAIN.",
        "           CALL 'PAYCALC' USING PAY-AREA",
        "           MOVE 1 TO X",
    ]
    payload = json.loads(
        format_trace_json(
            entries,
            line_map,
            ["CALL PAYCALC" + REAL_SUFFIX, "READ F"],
            "c",
            1,
            "t.cut",
            "p.cbl",
            original_lines=original,
        )
    )
    assert payload["path"] == [
        {"line": 2, "paragraph": "MAIN"},
        {"line": 3, "statement": "CALL", "spliced": True},
        {"line": 4, "statement": "MOVE"},
        {"line": 3, "statement": "CALL", "spliced": True},
    ]
    assert payload["mocks"] == [
        {"order": 1, "label": "CALL PAYCALC", "real": True},
        {"order": 2, "label": "READ F"},
    ]
    console = format_trace_console(payload)
    assert "mocks and real calls, in order:" in console
    assert "1. CALL PAYCALC (real program, not mocked)" in console
    assert "CALL (mocked or linked by mockymock)" in console


def test_trace_keeps_plain_statements_on_one_line_apart():
    # Two statements on one instrumented line are two entries, as before.
    entries = [_entry(5, "MOVE"), _entry(5, "MOVE")]
    payload = json.loads(
        format_trace_json(entries, {5: 7}, [], "c", None, "t.cut", "p.cbl")
    )
    assert payload["path"] == [
        {"line": 7, "statement": "MOVE"},
        {"line": 7, "statement": "MOVE"},
    ]
    assert "mocks fired: none" in format_trace_console(payload)


class _Factory:
    def __init__(self, *_):
        pass

    def value_for(self, *_):
        return "1"


def _spec(name):
    from types import SimpleNamespace

    qualified = f"PAY-AREA.{name}"
    return SimpleNamespace(
        column=name,
        qualified_name=qualified,
        to_dict=lambda: {"column": name, "qualified_name": qualified},
    )


def test_filled_call_fixture_gets_a_direction(monkeypatch):
    import cobolparser.generators.data.values as values

    monkeypatch.setattr(values, "ValueFactory", _Factory)
    bundle = {"scenarios": [{"name": "s", "fixtures": []}]}
    assert _add_fields(bundle, "CALL", "PAYCALC", "A", [_spec("A")], 1, "IN")
    fixture = bundle["scenarios"][0]["fixtures"][0]
    assert fixture["direction"] == "IN"
    # An older bundle's "" is filled with the argument's direction ...
    fixture["direction"] = ""
    assert _add_fields(bundle, "CALL", "PAYCALC", "B", [_spec("B")], 1, "OUT")
    assert fixture["direction"] == "OUT"
    # ... and an argument going the other way makes it BIDIRECTIONAL.
    assert _add_fields(bundle, "CALL", "PAYCALC", "C", [_spec("C")], 1, "IN")
    assert fixture["direction"] == "BIDIRECTIONAL"
