"""Issue #289: a program whose file name holds a dot (PAY.V2.cbl) pairs
with the suite `generate` writes for it under tests/ (named after the
full stem, PAY.V2.cut) -- the mirror and unique rules try the full stem
before the first-dot base."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from mockymock.cli.main import main

_ORDRPROC = Path(__file__).resolve().parents[2] / "examples" / "ordrproc"


def test_generated_suite_round_trips_to_a_dotted_program(
    tmp_path, monkeypatch, capsys
) -> None:
    (tmp_path / "src" / "pay").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "mockymock.toml").write_text('test_root = "tests"\n')
    shutil.copy(_ORDRPROC / "ORDRPROC.cbl", tmp_path / "src" / "pay" / "PAY.V2.cbl")
    monkeypatch.chdir(tmp_path)

    assert main(["generate", "src/pay/PAY.V2.cbl"]) == 0
    assert (tmp_path / "tests" / "pay" / "PAY.V2.cut").is_file()
    capsys.readouterr()

    assert main(["suites", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["suites"]
    assert len(rows) == 1
    assert (
        Path(rows[0]["program"]).resolve()
        == (tmp_path / "src" / "pay" / "PAY.V2.cbl").resolve()
    )

    assert main(["lint", "src/pay/PAY.V2.cbl"]) == 0
    assert "no .cut file found" not in capsys.readouterr().out
