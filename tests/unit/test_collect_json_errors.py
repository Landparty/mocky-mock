"""Issue #309: `collect --json` reports every failure as a JSON error
object on stdout -- a missing .cut or program file, and `--boundaries`
without a program -- since the VS Code extension parses that stdout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mockymock.cli.main import main

_RATERTE = Path(__file__).resolve().parents[2] / "examples" / "raterte"


@pytest.mark.parametrize(
    ("argv", "fragment"),
    [
        (["--cut", "{tmp}/nope.cut"], "no such file"),
        (
            ["--cut", str(_RATERTE / "RATERTE.cut"), "--boundaries", "{tmp}/NOPE.cbl"],
            "no such file",
        ),
        (
            ["--cut", str(_RATERTE / "RATERTE.cut"), "--boundaries"],
            "--boundaries requires a program argument",
        ),
    ],
)
def test_collect_json_failures_are_json(tmp_path, capsys, argv, fragment) -> None:
    argv = [arg.replace("{tmp}", str(tmp_path)) for arg in argv]
    assert main(["collect", *argv, "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 1
    assert fragment in payload["error"]
