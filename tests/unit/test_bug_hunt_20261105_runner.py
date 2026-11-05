"""Fixes from the 2026-11-05 bug hunt in running suites: crash reruns
picked by position, bounded memory for a case looping over a DISPLAY,
and a runner that survives a non-JSON answer, a corrupt pack and keeps
a timed-out step's stderr."""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

from mockymock.cli.checks import filter_suite_cases
from mockymock.dsl.parser import parse_cut
from mockymock.report import results
from mockymock.report.json_report import (
    not_run_case_positions,
    report_case_positions,
)
from mockymock.report.results import parse_stdout
from mockymock.runner import RunnerClient, RunnerClientError, extract_pack
from mockymock.runner.jobs import JobPackError, _run_step
from mockymock.runtime import native_toolchain

DUPLICATE_NAMES = """\
TESTSUITE "dup"
TESTCASE "same"
    PERFORM A
TESTCASE "same"
    PERFORM B
TESTCASE "other"
    PERFORM B
"""

# --- crash reruns pick cases by position ------------------------------------


def test_case_positions_pick_one_of_two_cases_sharing_a_name() -> None:
    suite = parse_cut(DUPLICATE_NAMES)
    assert filter_suite_cases(suite, None, None, [2, 3]) == []
    assert [case.line for case in suite.test_cases] == [4, 6]


def test_not_run_cases_are_named_by_position() -> None:
    suite = parse_cut(DUPLICATE_NAMES)
    ran = parse_stdout(
        "__MOCKYMOCK__ TESTSUITE: dup\n__MOCKYMOCK__ CASE 001 START: same\n"
    )
    assert not_run_case_positions(ran, suite) == [2, 3]
    assert report_case_positions(ran, suite) == [1, 2, 3]


# --- a looping DISPLAY: bounded case output ---------------------------------


def _case_output(lines: list[str]) -> list[str]:
    stdout = "__MOCKYMOCK__ CASE 001 START: loop\n" + "".join(
        f"{line}\n" for line in lines
    )
    return parse_stdout(stdout).results[0].output


def test_case_output_past_the_cap_is_counted_and_hashed(monkeypatch) -> None:
    monkeypatch.setattr(results, "MAX_CASE_OUTPUT_LINES", 3)
    output = _case_output(["L1", "L2", "L3", "L4", "L5"])
    assert output[:3] == ["L1", "L2", "L3"]
    assert output[3].startswith("(mockymock: 3 more output line(s) not kept, sha256 ")
    # A baseline still tells two outputs apart past the cap.
    other = _case_output(["L1", "L2", "L3", "L4", "XX"])
    assert other[3] != output[3]
    assert _case_output(["L1", "L2", "L3", "L4", "L5"]) == output


def test_case_output_under_the_cap_is_kept_whole() -> None:
    assert _case_output(["A", "B"]) == ["A", "B", ""]


def test_capped_stdout_keeps_only_marker_lines_past_the_limit() -> None:
    capped = native_toolchain._CappedStdout(limit=10, marker_limit=1000)
    capped.feed(b"0123456789")
    capped.feed(b"noise\n__MOCKYMOCK__ CASE 001 E")
    capped.feed(b"ND\nmore noise\n__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0")
    out = capped.result()
    assert out == (
        b"0123456789"
        b"__MOCKYMOCK__ CASE 001 END\n"
        b"__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0"
    )
    assert capped.dropped == len(b"noise\nmore noise\n")


def test_capped_stdout_bounds_marker_lines_too() -> None:
    capped = native_toolchain._CappedStdout(limit=0, marker_limit=30)
    capped.feed(b"__MOCKYMOCK__ MOCK: CALL X\n" * 5)
    assert capped.result() == b"__MOCKYMOCK__ MOCK: CALL X\n"
    assert capped.dropped == 4 * len(b"__MOCKYMOCK__ MOCK: CALL X\n")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_run_capped_keeps_memory_bounded_and_the_markers(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(native_toolchain, "STDOUT_CAPTURE_BYTES", 1000)
    script = (
        "import sys\n"
        "sys.stdout.write('x' * 100 + '\\n')\n"
        "sys.stdout.write(('noise' * 20 + '\\n') * 20000)\n"
        "sys.stdout.write('__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\\n')\n"
    )
    code, stdout, _, dropped = native_toolchain._run_capped(
        [sys.executable, "-c", script], cwd=tmp_path, env={}, timeout=30
    )
    assert code == 0
    assert len(stdout) < 1200
    assert stdout.endswith(b"__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n")
    assert dropped > 1_000_000
    assert "more bytes of output" in native_toolchain._not_kept_note(dropped)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_run_capped_times_out_with_what_was_printed(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(native_toolchain, "STDOUT_CAPTURE_BYTES", 100)
    script = (
        "import sys\n"
        "sys.stdout.write('__MOCKYMOCK__ CASE 001 START: loop\\n')\n"
        "while True: sys.stdout.write('spam\\n')\n"
    )
    with pytest.raises(Exception) as caught:
        native_toolchain._run_capped(
            [sys.executable, "-c", script], cwd=tmp_path, env={}, timeout=1
        )
    exc = caught.value
    assert exc.__class__.__name__ == "TimeoutExpired"
    assert exc.stdout.startswith(b"__MOCKYMOCK__ CASE 001 START: loop\n")
    assert len(exc.stdout) <= 100 + 4096
    assert exc.not_kept > 0


# --- the runner -------------------------------------------------------------


def test_client_refuses_a_body_that_is_not_json(monkeypatch) -> None:
    """A proxy's HTML page answered with 200 raised a bare ValueError out
    of `serve`, which stops the runner instead of retrying."""
    client = RunnerClient("http://backend", "token")
    monkeypatch.setattr(
        client, "_request", lambda *a, **k: (200, b"<html>bad gateway</html>")
    )
    with pytest.raises(RunnerClientError, match="not JSON"):
        client.claim("r1")
    with pytest.raises(RunnerClientError, match="not JSON"):
        client.report("j1", {"suites": []})


def test_a_pack_with_a_corrupt_member_is_a_pack_error(tmp_path: Path) -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("oracle.json", "{}")
        archive.writestr("src/PROG.cbl", "PROGRAM TEXT")
    data = bytearray(out.getvalue())
    at = data.find(b"PROGRAM TEXT")
    data[at] = ord("X")  # the stored CRC no longer matches
    with pytest.raises(JobPackError, match="cannot be read"):
        extract_pack(bytes(data), tmp_path)


def test_a_timed_out_step_keeps_its_stderr(tmp_path: Path) -> None:
    script = (
        "import sys, time\n"
        "sys.stderr.write('Traceback: the reason\\n')\n"
        "sys.stderr.flush()\n"
        "time.sleep(30)\n"
    )
    step = _run_step([sys.executable, "-c", script], [], tmp_path, timeout=1)
    assert step.timed_out
    assert "Traceback: the reason" in step.log
    assert "timed out after" in step.log
