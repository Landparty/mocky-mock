"""Bug hunt of 2026-11-05 (round 2): every generated case for the loop's
EVALUATE of a DL/I program primed with the same GHN runs the arm it is
named for. The priming call used to answer the loop's status, so the loop
never ran (real-world ACCTPRG / LNRECOV, `2500-GET-NEXT-*` cases)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker
from tests.unit.test_generator_dli_end_status import PRIMED

_CASE = re.compile(r'^TESTCASE "(2000-SCAN: EVALUATE@(\d+) (WHEN [^"]+))"$', re.M)

# The first statement of each arm of 2000-SCAN's EVALUATE.
_ARM_LINE = {
    "WHEN SPACES": "DISPLAY 'NEXT ' SG-ID",
    "WHEN GB": "SET END-OF-DB TO TRUE",
    "WHEN OTHER": "SET END-OF-DB TO TRUE",
}


def _line(text: str, after: int = 0) -> int:
    return next(
        number
        for number, line in enumerate(PRIMED.splitlines(), start=1)
        if number > after and line.strip() == text
    )


@requires_docker
def test_every_loop_case_runs_its_arm(tmp_path: Path, capsys):
    program = tmp_path / "PRIMED.cbl"
    program.write_text(PRIMED)
    cut = tmp_path / "PRIMED.cut"
    argv = ["generate", str(program), "--scenarios", "all", "--seed", "1"]
    assert main([*argv, "-o", str(cut)]) == 0
    cases = _CASE.findall(cut.read_text())
    # WHEN OTHER after WHEN SPACES needs cobol-parser's round-2 fix too.
    assert {"WHEN SPACES", "WHEN GB"} <= {arm for _, _, arm in cases}, cut.read_text()
    scan = _line("2000-SCAN.")
    for case, _evaluate, arm in cases:
        trace = tmp_path / "trace.json"
        exit_code = main(
            [
                "run",
                str(program),
                "--cut",
                str(cut),
                "--case",
                case,
                "--trace",
                "--trace-json",
                str(trace),
            ]
        )
        out = capsys.readouterr().out
        assert exit_code == 0, out
        executed = {step["line"] for step in json.loads(trace.read_text())["path"]}
        evaluate = _line("EVALUATE DB-STATUS", after=scan)
        # WHEN GB and WHEN OTHER share their first statement's text: take
        # the one after the arm's own WHEN line.
        when = _line(arm.replace("WHEN GB", "WHEN 'GB'"), after=evaluate)
        wanted = _line(_ARM_LINE[arm], after=when)
        assert wanted in executed, f"{case}: line {wanted} never ran\n{out}"
