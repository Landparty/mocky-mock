"""End-to-end proof for `mockymock run --trace` against real GnuCOBOL.

The unit tests mock Docker away, so this is the only place the three
independently-plausible pieces are proven to actually compose: `-ftraceall`
plus `COB_SET_TRACE` really do emit a trace file into the sandbox, its
line numbers really do remap back onto the ORIGINAL .cbl, and the
`__MOCKYMOCK__ MOCK:` markers really do survive to stdout without
disturbing the protocol.

See docs/2026-07-21-debug-trace-design.md.
"""

import json
from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = (
    Path(__file__).parent.parent.parent / "examples" / "real-world" / "ACCTPRG"
)
CASE = "1000-INITIALIZE primes the first segment when CBLTDLI succeeds"


def _run_trace(tmp_path, extra=()):
    out = tmp_path / "trace.json"
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "ACCTPRG.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "ACCTPRG.cut"),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
            "--case",
            CASE,
            "--trace-json",
            str(out),
            *extra,
        ]
    )
    return exit_code, out


@requires_docker
def test_trace_reports_path_over_original_line_numbers(tmp_path):
    exit_code, out = _run_trace(tmp_path)

    assert exit_code == 0
    payload = json.loads(out.read_text())
    assert payload["version"] == 1
    assert payload["case"]["name"] == CASE
    assert payload["path"], "expected a non-empty executed path"

    # Every reported line must be a real line of the ORIGINAL .cbl. This is
    # the assertion that would catch a remap silently reporting
    # instrumented-source line numbers: the instrumented file is longer, so
    # a broken remap overruns the original's length.
    original_lines = (EXAMPLE_DIR / "ACCTPRG.cbl").read_text().splitlines()
    assert all(1 <= entry["line"] <= len(original_lines) for entry in payload["path"])


@requires_docker
def test_trace_path_lands_on_non_blank_source_lines(tmp_path):
    """A remap that is merely in-range could still be off by a constant.
    Every traced line should carry actual COBOL, not blanks or comments."""
    _, out = _run_trace(tmp_path)
    payload = json.loads(out.read_text())
    original_lines = (EXAMPLE_DIR / "ACCTPRG.cbl").read_text().splitlines()

    for entry in payload["path"]:
        text = original_lines[entry["line"] - 1]
        assert text.strip(), f"line {entry['line']} is blank"
        indicator = text[6] if len(text) > 6 else " "
        assert indicator not in ("*", "/"), f"line {entry['line']} is a comment"


@requires_docker
def test_trace_records_the_mocks_that_fired_in_order(tmp_path):
    _, out = _run_trace(tmp_path)
    payload = json.loads(out.read_text())

    assert payload["mocks"], "expected at least one mock to fire"
    assert [m["order"] for m in payload["mocks"]] == list(
        range(1, len(payload["mocks"]) + 1)
    )
    # Every fired label must be one this case actually declared.
    cut_text = (EXAMPLE_DIR / "ACCTPRG.cut").read_text()
    for mock_entry in payload["mocks"]:
        head = mock_entry["label"].split()[0]
        assert head in cut_text


@requires_docker
def test_trace_does_not_disturb_the_protocol_or_the_verdict(tmp_path):
    """The MOCK markers ride the same stdout channel the __MOCKYMOCK__
    protocol uses, so a malformed marker would corrupt parsing. The run must
    still pass exactly as it does without --trace."""
    traced_exit, _ = _run_trace(tmp_path)
    plain_exit = main(
        [
            "run",
            str(EXAMPLE_DIR / "ACCTPRG.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "ACCTPRG.cut"),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
            "--case",
            CASE,
        ]
    )
    assert traced_exit == plain_exit == 0
