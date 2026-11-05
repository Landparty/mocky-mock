"""Bug hunt 2026-11-05 (round 2): where the runner meets the LegacyLens
backend -- a recording that recorded nothing, and a result the backend could
not take at the first try."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from mockymock.runner import RunnerClientError, extract_pack, serve
from mockymock.runner.jobs import REPORT_RETRY_DELAYS, _report, run_pack
from tests.unit.test_runner import (  # noqa: F401 - fixture
    FakeClient,
    _manifest,
    _pack_files,
    _zip,
    fake_command,
)


def test_a_record_step_that_did_not_compile_is_not_a_recording(
    tmp_path: Path, fake_command  # noqa: F811
) -> None:
    """`recorded` was set whatever --record-expectations did: a suite that
    did not compile was played, reported recorded with its STUB EXPECT
    placeholders, and the backend kept that .cut as the module's tests."""
    files = _pack_files(
        _manifest("tests", record=True),
        **{"tests/PAYMAIN.cut": "TESTSUITE\n*> NOCOMPILE\n*> STUB EXPECT X\n"},
    )
    pack = extract_pack(_zip(files), tmp_path)
    (suite,) = run_pack(pack, command=fake_command)["suites"]
    assert suite.get("recorded") is not True
    assert "report" not in suite
    assert suite["error"].startswith("mockymock run --record-expectations recorded")
    assert suite["exit_code"] == 1
    assert "compile failed" in suite["log"]
    assert "STUB EXPECT X" in suite["cut_text"]


class _Flaky(FakeClient):
    def __init__(self, errors: list[RunnerClientError], jobs=None, packs=None):
        super().__init__(jobs or [], packs or {})
        self.errors = errors
        self.tries = 0

    def report(self, job_id: str, payload: dict) -> dict:
        self.tries += 1
        if self.errors:
            raise self.errors.pop(0)
        return super().report(job_id, payload)


def test_report_retries_a_backend_that_is_down_or_failing() -> None:
    client = _Flaky(
        [RunnerClientError("refused"), RunnerClientError("HTTP 502", status=502)]
    )
    sleeps: list[float] = []
    summary = _report(client, "j1", {"suites": []}, sleeps.append, logging.getLogger())  # type: ignore[arg-type]
    assert summary == {"status": "succeeded"}
    assert client.tries == 3 and sleeps == list(REPORT_RETRY_DELAYS[:2])


def test_report_does_not_retry_a_refusal() -> None:
    client = _Flaky([RunnerClientError("HTTP 409", status=409)])
    sleeps: list[float] = []
    with pytest.raises(RunnerClientError):
        _report(client, "j1", {}, sleeps.append, logging.getLogger())  # type: ignore[arg-type]
    assert client.tries == 1 and sleeps == []


def test_report_gives_up_after_the_last_retry() -> None:
    errors = [RunnerClientError("down") for _ in range(len(REPORT_RETRY_DELAYS) + 1)]
    client = _Flaky(errors)
    sleeps: list[float] = []
    with pytest.raises(RunnerClientError):
        _report(client, "j1", {}, sleeps.append, logging.getLogger())  # type: ignore[arg-type]
    assert client.tries == len(REPORT_RETRY_DELAYS) + 1
    assert sleeps == list(REPORT_RETRY_DELAYS)


def test_serve_reports_once_the_backend_is_back(
    tmp_path: Path, fake_command  # noqa: F811
) -> None:
    client = _Flaky(
        [RunnerClientError("connection refused")],
        jobs=[{"id": "j1", "kind": "baseline"}],
        packs={"j1": _zip(_pack_files(_manifest()))},
    )
    sleeps: list[float] = []
    ran = serve(
        client,  # type: ignore[arg-type]
        runner_name="r1",
        once=True,
        command=fake_command,
        work_dir=tmp_path,
        log=lambda _: None,
        sleep=sleeps.append,
    )
    assert ran == 1
    ((job_id, payload),) = client.reports
    assert job_id == "j1" and payload["suites"][0]["baseline"]
    assert sleeps == [REPORT_RETRY_DELAYS[0]]


def test_docker_exec_output_is_read_in_bounded_memory(monkeypatch) -> None:
    """The Docker backend's run_binary held all of a test binary's stdout
    (400 MB of DISPLAY output peaked at 1.2 GB): it now goes through the
    native backend's capped reader, keeping the driver's marker lines."""
    import sys

    from mockymock.runtime import native_toolchain
    from mockymock.runtime.docker_toolchain import _exec_binary

    monkeypatch.setattr(native_toolchain, "STDOUT_CAPTURE_BYTES", 1000)
    script = (
        "import sys\n"
        "for _ in range(5000): sys.stdout.write('X' * 99 + '\\n')\n"
        "sys.stdout.write('__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\\n')\n"
    )
    result = _exec_binary([sys.executable, "-c", script], timeout=60)
    assert result.returncode == 0
    assert len(result.stdout) < 2000
    assert result.stdout.endswith(b"__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n")
    assert b"more bytes of output than" in result.stderr
