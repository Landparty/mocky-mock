"""Executed regressions for issue #156. Unit-level counterparts live in
tests/unit/test_issue_156_loop_end_reply.py."""

from __future__ import annotations

from pathlib import Path

from tests.integration._docker import requires_docker
from tests.integration.test_bug_hunt_m1_fixes import _generate_and_run


@requires_docker
def test_generated_looped_mqget_suite_terminates_and_passes(
    tmp_path: Path, capsys
) -> None:
    from tests.unit.test_issue_156_loop_end_reply import MQ_LOOP_CBL

    exit_code = _generate_and_run(tmp_path, "MQLOOP", MQ_LOOP_CBL, "--seed", "1")
    out = capsys.readouterr().out
    assert exit_code == 0, out


@requires_docker
def test_generated_looped_cbltdli_suite_terminates_and_passes(
    tmp_path: Path, capsys
) -> None:
    from tests.unit.test_issue_156_loop_end_reply import IMS_LOOP_CBL

    exit_code = _generate_and_run(tmp_path, "IMSLOOP", IMS_LOOP_CBL, "--seed", "1")
    out = capsys.readouterr().out
    assert exit_code == 0, out
