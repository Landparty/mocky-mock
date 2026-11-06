"""`run --trace` and `mutate` on a load-module suite (PAYMAIN with the real
PAYCALC), against real GnuCOBOL: the gaps the cobol-test run found on
2026-11-06. The unit side is tests/unit/test_open_gaps_2026_11_06.py."""

import json
import shutil
from pathlib import Path

import pytest

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent.parent / "fixtures" / "open_gaps_2026_11_06"


@pytest.fixture
def module_suite(tmp_path, monkeypatch):
    for name in ("PAYMAIN.cbl", "PAYCALC.cbl"):
        shutil.copy(FIXTURES / name, tmp_path / name)
    monkeypatch.chdir(tmp_path)
    assert (
        main(
            [
                "generate",
                "PAYMAIN.cbl",
                "--name",
                "module",
                "--real",
                "PAYCALC.cbl",
                "--seed",
                "1",
            ]
        )
        == 0
    )
    return tmp_path / "tests" / "PAYMAIN.module.cut"


@requires_docker
def test_trace_marks_the_real_call_and_hides_the_splice(module_suite, capsys):
    capsys.readouterr()
    out = module_suite.parent / "trace.json"
    main(
        [
            "run",
            "PAYMAIN.cbl",
            "--cut",
            str(module_suite),
            "--case",
            "happy path",
            "--trace-json",
            str(out),
        ]
    )
    console = capsys.readouterr().out
    payload = json.loads(out.read_text(encoding="utf-8"))
    real = [m for m in payload["mocks"] if m.get("real")]
    assert real and {m["label"] for m in real} == {"CALL PAYCALC"}
    assert not any(
        m["label"] == "CALL PAYCALC" and not m.get("real") for m in payload["mocks"]
    )
    assert "CALL PAYCALC (real program, not mocked)" in console
    # Each spliced statement is one entry: no EVALUATE/WHEN of the
    # dispatch block on PAYMAIN's CALL (line 42) or READ (line 36).
    statements = {
        e["line"]: e["statement"]
        for e in payload["path"]
        if "statement" in e and e.get("spliced")
    }
    assert statements[42] == "CALL"
    assert statements[36] == "READ"
    assert not any(
        e.get("line") in (36, 42) and e.get("statement") in ("EVALUATE", "WHEN")
        for e in payload["path"]
    )


@requires_docker
def test_mutate_says_why_it_refuses_a_real_call_suite(module_suite, capsys):
    capsys.readouterr()
    assert main(["mutate", "PAYMAIN.cbl", "--cut", str(module_suite)]) == 1
    out = capsys.readouterr().out
    assert "USE REAL CALL" in out
    assert "not green" not in out
    assert "fix the suite first" not in out
