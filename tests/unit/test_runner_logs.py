"""The runner's job log (posted with each result) and its process log."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

from mockymock.cli.main import main
from mockymock.runner import logs as runner_logs
from mockymock.runner import run_job, serve
from mockymock.runner.logs import JobLog, JsonFormatter, configure_logging
from tests.unit.test_runner import (
    FAKE_MOCKYMOCK,
    FakeClient,
    _manifest,
    _pack_files,
    _zip,
)


@pytest.fixture
def fake_command(tmp_path: Path) -> list[str]:
    script = tmp_path / "fake_mockymock.py"
    script.write_text(FAKE_MOCKYMOCK)
    return [sys.executable, str(script)]


def test_a_job_log_records_every_step_with_its_fields(tmp_path: Path, fake_command):
    payload = run_job(
        _zip(_pack_files(_manifest())),
        fake_command,
        work_dir=tmp_path,
        job_log=JobLog("j1"),
    )

    log = payload["log"]
    for step in (
        "pack unpacked",
        "manifest read",
        "suite started",
        "generate finished",
        "run finished",
        "suite finished",
        "job finished",
    ):
        assert step in log, step
    assert "entry=PAYMAIN" in log
    assert 'result="baseline recorded"' in log
    assert payload["suites"][0]["duration_ms"] >= 0


def test_a_failed_suite_is_logged_as_a_warning_with_its_error(
    tmp_path: Path, fake_command
):
    manifest = _manifest("compare", baseline="baselines/PAYMAIN.json")

    payload = run_job(_zip(_pack_files(manifest)), fake_command, work_dir=tmp_path)

    assert "WARNING suite failed" in payload["log"]
    assert "no baseline for this suite" in payload["log"]
    assert "failed_suites=1" in payload["log"]


def test_an_unusable_pack_still_posts_its_log(tmp_path: Path):
    payload = run_job(b"not a zip", work_dir=tmp_path)

    assert "pack is not a zip" in payload["error"]
    assert "ERROR   job cannot run" in payload["log"]


def test_serve_posts_the_job_log_and_reports_a_crash(tmp_path: Path, fake_command):
    class Crashing(FakeClient):
        def download_pack(self, job: dict) -> bytes:
            if job["id"] == "boom":
                raise RuntimeError("disk full")
            return super().download_pack(job)

    client = Crashing(
        [{"id": "j1", "kind": "baseline", "load_module_id": "LM1"}, {"id": "boom"}],
        {"j1": _zip(_pack_files(_manifest()))},
    )
    serve(client, once=True, command=fake_command, work_dir=tmp_path)  # type: ignore[arg-type]

    (_, ok), (_, crashed) = client.reports
    assert "job claimed" in ok["log"] and "load_module_id=LM1" in ok["log"]
    assert "environment" in ok["log"] and "mockymock=" in ok["log"]
    assert "pack downloaded" in ok["log"]
    assert "the runner crashed: RuntimeError('disk full')" == crashed["error"]
    assert "runner crashed while running the job" in crashed["log"]


def test_a_long_job_log_keeps_its_tail(monkeypatch):
    monkeypatch.setattr(runner_logs, "MAX_JOB_LOG_CHARS", 200)
    log = JobLog("j1", logger=logging.getLogger("test.quiet"))
    for index in range(50):
        log.event("step", index=index)

    text = log.text()
    assert text.startswith("(earlier lines cut)")
    assert "index=49" in text and "index=0 " not in text


def test_json_log_lines_carry_the_step_fields():
    record = logging.LogRecord(
        "mockymock.runner", logging.INFO, "", 0, "run finished", None, None
    )
    record.job_id = "j1"
    record.exit_code = 0
    record.module_name = "x"

    line = json.loads(JsonFormatter().format(record))

    assert line["message"] == "run finished"
    assert line["level"] == "INFO"
    assert line["job_id"] == "j1" and line["exit_code"] == 0


def test_a_field_named_like_a_log_record_attribute_does_not_raise():
    log = JobLog("j1", logger=logging.getLogger("test.quiet"))
    log.event("step", module="PAYMAIN", name="x")
    assert "module=PAYMAIN" in log.text()


def test_configure_logging_writes_json_lines_to_a_file(tmp_path: Path):
    target = tmp_path / "runner.log"
    handler = configure_logging("INFO", "json", str(target))
    try:
        JobLog("j9").event("job claimed", kind="compare")
    finally:
        handler.close()
        runner_logs.LOGGER.handlers = []
    line = json.loads(target.read_text().splitlines()[-1])
    assert line == line | {"message": "job claimed", "job_id": "j9", "kind": "compare"}


def test_runner_cli_refuses_a_log_file_it_cannot_open(tmp_path: Path, capsys):
    code = main(
        ["runner", "--log-file", str(tmp_path / "no" / "such" / "dir" / "x.log")]
    )
    assert code == 2
    assert "cannot open the log" in capsys.readouterr().out
    runner_logs.LOGGER.handlers = []
