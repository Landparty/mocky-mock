"""Executed regression for the 2026-10-13 nightly bug hunt (run 8b). The
unit-level counterpart lives in
the unit feature files (each block marked `# Regression:`)."""

from __future__ import annotations

from pathlib import Path

from tests.integration._docker import requires_docker
from tests.integration.test_issues_139_to_150 import _generate_and_run


@requires_docker
def test_generated_status_driven_read_loop_terminates_and_passes(
    tmp_path: Path, capsys
) -> None:
    from tests.unit.test_generator_read_loop_end import STATUS_LOOP_CBL

    exit_code = _generate_and_run(
        tmp_path, "STATLOOP", STATUS_LOOP_CBL, "--seed", "3", "--scenarios", "all"
    )
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "0 failed" in out
