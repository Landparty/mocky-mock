"""Executed regressions for the 2026-10-09 nightly bug hunt. Unit-level
counterparts live in the unit feature files (each block marked `# Regression:`)."""

from __future__ import annotations

from pathlib import Path

from tests.integration._docker import requires_docker
from tests.integration.test_issues_139_to_150 import _generate_and_run


@requires_docker
def test_generated_priming_read_suite_terminates_and_passes(
    tmp_path: Path, capsys
) -> None:
    from tests.unit.test_generator_read_loop_end import PRIME_CBL

    exit_code = _generate_and_run(
        tmp_path, "PRIME", PRIME_CBL, "--seed", "3", "--rows", "3"
    )
    out = capsys.readouterr().out
    assert exit_code == 0, out
