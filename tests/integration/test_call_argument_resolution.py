"""End to end through GnuCOBOL: the values `generate` now writes for a CALL
argument the layout index cannot hold reach the program, and a dynamic CALL
mock branched per target lets each callee answer differently."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mockymock.cli.main import main
from tests.integration._docker import requires_docker
from tests.unit.test_call_argument_resolution import DYNAMIC, PROGRAM


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    (tmp_path / "ARGPROG.cbl").write_text(PROGRAM, encoding="utf-8")
    (tmp_path / "DYNPROG.cbl").write_text(DYNAMIC, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _with_expect(cut: str, expect: str) -> str:
    return cut.replace(
        "    PERFORM MAIN-PROCESS", f"    PERFORM MAIN-PROCESS\n    {expect}", 1
    )


@requires_docker
def test_a_filled_group_argument_reaches_the_program(workdir: Path):
    assert main(["generate", "ARGPROG.cbl", "-o", "ARGPROG.cut"]) == 0
    cut = (workdir / "ARGPROG.cut").read_text(encoding="utf-8")
    name = re.search(r'MOVE (".*?") TO WS-CUST-NAME', cut)
    assert name is not None
    checked = workdir / "checked.cut"
    checked.write_text(_with_expect(cut, f"EXPECT WS-OUT TO BE {name.group(1)}"))
    assert main(["run", "ARGPROG.cbl", "--cut", str(checked)]) == 0
    checked.write_text(_with_expect(cut, 'EXPECT WS-OUT TO BE "NOT THE NAME"'))
    assert main(["run", "ARGPROG.cbl", "--cut", str(checked)]) == 1


@requires_docker
def test_each_dynamic_target_answers_on_its_own(workdir: Path):
    assert (
        main(["generate", "DYNPROG.cbl", "-o", "DYNPROG.cut", "--per-paragraph"]) == 0
    )
    cut = (workdir / "DYNPROG.cut").read_text(encoding="utf-8")
    lines: list[str] = []
    answer = None
    for line in cut.splitlines():
        if 'WHEN "PGMA"' in line:
            answer = 1
        elif 'WHEN "PGMB"' in line:
            answer = 2
        elif "WHEN OTHER" in line:
            answer = 9
        elif "END-EVALUATE" in line:
            answer = None
        if answer is not None and "TO RETURN-CODE" in line:
            line = line.replace("MOVE 0 TO RETURN-CODE", f"MOVE {answer} TO WS-RC")
        lines.append(line)
    edited = "\n".join(lines)
    assert "MOVE 1 TO WS-RC" in edited and "MOVE 2 TO WS-RC" in edited
    checked = workdir / "checked.cut"
    # PGMA answers 1, PGMB answers 2: 1 + 2.
    checked.write_text(_with_expect(edited, "EXPECT WS-TOTAL TO BE 3"))
    assert main(["run", "DYNPROG.cbl", "--cut", str(checked)]) == 0
    checked.write_text(_with_expect(edited, "EXPECT WS-TOTAL TO BE 4"))
    assert main(["run", "DYNPROG.cbl", "--cut", str(checked)]) == 1
