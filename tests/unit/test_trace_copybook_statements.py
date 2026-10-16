"""Issue #242: `run --trace` keeps the statements a procedure copybook
brought in, each placed in its own file and line, instead of dropping
them as splicer insertions."""

from __future__ import annotations

import json
from pathlib import Path

from mockymock._lines import read_utf8_source, split_source_lines
from mockymock.cli.checks import run_static_checks
from mockymock.report.coverage import build_copybook_line_map, build_original_line_map
from mockymock.report.trace import TraceEntry, format_trace_console, format_trace_json

_CPYPROC = Path(__file__).resolve().parents[2] / "examples" / "cpyproc"


def test_copybook_statements_appear_in_the_trace_path() -> None:
    checked = run_static_checks(
        _CPYPROC / "CPYPROC.cbl",
        _CPYPROC / "CPYPROC.cut",
        [str(_CPYPROC / "copybooks")],
    )
    assert not checked.problems
    lines = list(checked.lines)
    instrumented = ["       UT-DRIVER.", *lines]  # driver code shifts every line
    original = split_source_lines(read_utf8_source(_CPYPROC / "CPYPROC.cbl"))
    copybook_lines = build_copybook_line_map(
        instrumented, lines, checked.source_location_map
    )
    assert copybook_lines, "no line mapped to CALCPERF.CPY"
    first = min(copybook_lines)
    entries = [TraceEntry(line=first, statement=None, paragraph="CALC-DISCOUNT")]
    payload = json.loads(
        format_trace_json(
            entries,
            build_original_line_map(instrumented, lines, original),
            [],
            "direct",
            None,
            "CPYPROC.cut",
            "CPYPROC.cbl",
            copybook_lines,
        )
    )
    assert payload["path"] == [
        {"file": "CALCPERF.CPY", "line": 1, "paragraph": "CALC-DISCOUNT"}
    ]
    assert "(CALCPERF.CPY)" in format_trace_console(payload)
