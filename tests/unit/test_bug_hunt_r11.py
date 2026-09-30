"""Regression tests for bug hunt round 11. Each test reproduces one defect
found (and fixed) in this round; see the commit message for the list."""

from __future__ import annotations

import io
import subprocess
from unittest import mock
from xml.etree import ElementTree

import pytest

from mockymock.cli.mainframe_export import (
    SourceAttribution,
    fit_within_columns,
    wrap_long_display_lines,
)
from mockymock.debug.adapter import DapAdapter, DebugSession
from mockymock.debug.call_stack import ParagraphIndex
from mockymock.debug.gdb_session import (
    AsyncRecord,
    GdbCommandError,
    ProgramOutput,
    ResultRecord,
    _stop_event_from_payload,
    parse_mi_line,
)
from mockymock.debug.line_map import LineMap
from mockymock.dsl.fixture_bundle import MalformedBundleError, load_fixture_bundle
from mockymock.dsl.parser import CutParseError, parse_cut
from mockymock.mutation.operators import generate_mutants
from mockymock.report import results as report_results
from mockymock.report.formatters import format_junit_xml
from mockymock.runtime import docker_toolchain
from tests.unit.test_adapter import _drain, _frame, _request

# --- mutation: boundary-literal inside a hyphenated data name -------------

_MUTATION_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       PROCEDURE DIVISION.
           IF X = 100-LIMIT
              DISPLAY 1
           END-IF
       >>IF DEBUG > 1
           DISPLAY 2
       >>END-IF
           IF Y = 100
              DISPLAY 3
           END-IF
""".splitlines()


def test_boundary_literal_never_mutates_the_digits_of_a_data_name():
    mutated = [m.mutated for m in generate_mutants(_MUTATION_SOURCE) if m.line == 4]
    assert not any("101-LIMIT" in text for text in mutated)
    # A real integer literal is still a boundary-literal site.
    assert any(
        m.line == 10 and m.operator == "boundary-literal"
        for m in generate_mutants(_MUTATION_SOURCE)
    )


def test_compiler_directive_lines_are_never_mutated():
    assert [m for m in generate_mutants(_MUTATION_SOURCE) if m.line in (7, 9)] == []


# --- export: UPON clause on every DISPLAY fragment -------------------------


def test_wrapped_display_keeps_upon_device_on_every_fragment():
    line = '           DISPLAY "' + "A" * 70 + '" UPON SYSERR.'
    wrapped, problems = wrap_long_display_lines([line])
    assert problems == []
    assert len(wrapped) > 1
    assert all("UPON SYSERR" in fragment for fragment in wrapped)
    assert all(len(fragment) <= 72 for fragment in wrapped)
    # The literal's content is unchanged across the fragments.
    text = "".join(fragment.split('"')[1] for fragment in wrapped)
    assert text == "A" * 70


# --- export: inline comment and attribution after a wrap -------------------


def test_fit_within_columns_moves_an_inline_comment_off_the_code_line():
    line = (
        "                          MOVE WS-ALPHA-FIELD TO WS-BETA-FIELD "
        '*> copy the "alpha" value over now'
    )
    fitted, problems = fit_within_columns([line])
    assert problems == []
    code_lines = [f for f in fitted if not f.lstrip().startswith("*>")]
    assert [c.strip() for c in code_lines] == ["MOVE WS-ALPHA-FIELD TO WS-BETA-FIELD"]
    assert any("copy the" in f and f.lstrip().startswith("*>") for f in fitted)


def test_fit_within_columns_attributes_by_instrumented_index_after_a_wrap():
    display = '           DISPLAY "' + "A" * 70 + '".'
    unbreakable = "           MOVE WS-" + "A" * 80 + "-B"
    attribution = SourceAttribution({1}, "t.cut", "", "p.cbl", "")
    _, problems = fit_within_columns([display, unbreakable], attribution=attribution)
    assert len(problems) == 1
    assert "line 2 " in problems[0]
    assert "generated test-driver code" in problems[0]


# --- DSL refusals -----------------------------------------------------------


def _parse_case(body: str):
    return parse_cut('TESTSUITE "S"\nTESTCASE "C"\n' + body)


@pytest.mark.parametrize("line", ["PERFORM P.", "PERFORM P THRU Q."])
def test_perform_target_with_sentence_period_is_refused(line):
    with pytest.raises(CutParseError, match="period"):
        _parse_case(line + "\n")


def test_expect_not_after_to_be_is_refused():
    with pytest.raises(CutParseError, match="malformed EXPECT comparison"):
        _parse_case("EXPECT WS-X TO BE NOT 5\n")
    # A value that merely starts with NOT- is still an ordinary value.
    suite = _parse_case("EXPECT WS-X TO BE NOT-FOUND\n")
    assert suite.test_cases[0].expectations[0].expected_value == "NOT-FOUND"


def test_rows_line_with_two_groups_is_refused():
    with pytest.raises(CutParseError, match="malformed ROWS row"):
        _parse_case("MOCK READ F ROWS\n( A = 1 ) ( B = 2 )\nEND-MOCK\n")


def test_terminal_line_with_two_groups_is_refused():
    with pytest.raises(CutParseError, match="malformed TERMINAL group"):
        _parse_case(
            "MOCK READ F ROWS\n( A = 1 )\nTERMINAL ( A = 1 ) ( B = 2 )\nEND-MOCK\n"
        )


def test_rows_with_parenthesized_value_and_quoted_paren_still_parse():
    suite = _parse_case(
        'MOCK READ F ROWS\n( A = FUNCTION MAX(1, 2), B = ")" )\nEND-MOCK\n'
    )
    assert suite.test_cases[0].mocks[0].rows == [
        [("A", "FUNCTION MAX(1, 2)"), ("B", '")"')]
    ]


# --- JUnit attribute whitespace ----------------------------------------------


def test_junit_attribute_keeps_tabs_and_newlines():
    reason = "expected\t5\ngot 6"
    suite = report_results.TestSuiteResult(
        suite_name="S",
        results=[
            report_results.TestResult(
                case_id="001", case_name="C", failure_reasons=[reason], ended=True
            )
        ],
        tests_run=1,
        failures=1,
    )
    root = ElementTree.fromstring(format_junit_xml(suite))
    failure = root.find("testcase/failure")
    assert failure is not None
    assert failure.get("message") == reason


# --- fixture bundle: non-object rows -----------------------------------------


@pytest.mark.parametrize("row", ["abc", "AB", ["A", "1"]])
def test_fixture_bundle_non_object_sequence_row_is_a_typed_error(row):
    data = {
        "bundle_version": 1,
        "seed": 1,
        "scenarios": [
            {
                "name": "s",
                "fixtures": [
                    {
                        "category": "READ",
                        "key": "F",
                        "direction": "IN",
                        "sequence": [row],
                    }
                ],
            }
        ],
    }
    with pytest.raises(MalformedBundleError):
        load_fixture_bundle(data)


# --- gdb/MI parsing -----------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    ["*stopped by operator", "^done with the batch", '^done,value="1" junk'],
)
def test_program_output_that_starts_like_an_mi_record_is_program_output(line):
    assert parse_mi_line(line) == ProgramOutput(line)


def test_real_mi_records_still_parse():
    assert parse_mi_line("^done") == ResultRecord("done", {})
    assert parse_mi_line('*stopped,reason="exited-normally"') == AsyncRecord(
        "stopped", {"reason": "exited-normally"}
    )


@pytest.mark.parametrize("raw, expected", [("01", 1), ("010", 8), ("0377", 255)])
def test_exit_code_is_read_as_gdb_octal(raw, expected):
    event = _stop_event_from_payload({"reason": "exited", "exit-code": raw})
    assert event.reason == "exited"
    assert event.exit_code == expected


# --- DAP setBreakpoints: partial failure keeps inserted breakpoints tracked ---


class _RefusingGdb:
    def __init__(self):
        self.live: set[int] = set()
        self._next = 0

    def set_output_handler(self, on_output):
        pass

    def set_breakpoint(self, file, line):
        if line == 13:
            raise GdbCommandError("No line 13 in file")
        self._next += 1
        self.live.add(self._next)
        return {"number": str(self._next)}

    def delete_breakpoint(self, number):
        self.live.discard(number)

    def close(self):
        pass


def test_set_breakpoints_partial_failure_leaves_no_untracked_breakpoint():
    gdb = _RefusingGdb()
    identity = {i: i for i in range(1, 30)}

    def launch(arguments):
        return DebugSession(
            gdb=gdb,
            line_map=LineMap(_to_original=identity, _to_instrumented=identity),
            variable_table={},
            generated_c_lines=[],
            paragraph_index=ParagraphIndex(paragraph_starts=[], section_starts=[]),
            instrumented_file="fixture.cbl",
        )

    source = {"path": "/x/fixture.cbl"}
    requests = [
        _request(1, "initialize"),
        _request(2, "launch", {}),
        _request(
            3,
            "setBreakpoints",
            {"source": source, "breakpoints": [{"line": 12}, {"line": 13}]},
        ),
        # The editor clears every breakpoint in the file.
        _request(4, "setBreakpoints", {"source": source, "breakpoints": []}),
    ]
    output = io.BytesIO()
    adapter = DapAdapter(
        io.BytesIO(b"".join(_frame(r) for r in requests)), output, launch
    )
    adapter.run()
    responses = [m for m in _drain(output) if m.get("type") == "response"]
    assert [r["success"] for r in responses if r["command"] == "setBreakpoints"] == [
        False,
        True,
    ]
    assert gdb.live == set()


# --- run_binary: non-UTF-8 and CR bytes in the program's stdout ---------------


def test_run_binary_decodes_non_utf8_stdout_without_newline_translation(tmp_path):
    work = tmp_path / "work"
    sandbox = work / "mockymock-x"
    sandbox.mkdir(parents=True)
    binary = sandbox / "PROG"
    stdout = b"__MOCKYMOCK__ CASE 001 FAIL: got A\xffB\rC\n"

    def fake_run(argv, **kwargs):
        if kwargs.get("text"):
            # What text=True would have done with these bytes.
            raise UnicodeDecodeError("utf-8", stdout, 34, 35, "invalid start byte")
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = docker_toolchain.run_binary(binary)
    assert result.stdout == "__MOCKYMOCK__ CASE 001 FAIL: got A�B\rC\n"
    assert result.stderr == ""


# --- lossy copybook decode refusal is still live -------------------------------


def test_cp1252_copybook_is_decoded_losslessly_and_not_refused(tmp_path):
    """The round-10 finding: cobol-parser now decodes a non-UTF-8 byte near
    the top of a copybook as cp1252 (lossless), so no EXPANSION_WARNING
    must fire for it; the refusal stays pinned by
    test_refusal.py::test_expansion_warnings_refuse_lossy_copybook_decode
    for the case that is still lossy."""
    from cobolparser.preprocess import expand_copybooks

    from mockymock.analysis.refusal import check_expansion_warnings
    from tests.unit.test_refusal import COPY_PROGRAM_SOURCE

    (tmp_path / "BADREC.CPY").write_bytes(
        b"       01  BAD-FIELD PIC X(5) VALUE 'ab\xffcd'.\n"
    )
    expansion = expand_copybooks(COPY_PROGRAM_SOURCE, copybook_paths=[str(tmp_path)])
    assert "abÿcd" in expansion.expanded_source
    assert check_expansion_warnings(expansion) == []
