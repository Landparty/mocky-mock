"""Behaviour baselines end to end (docs/2026-11-01-baseline-design.md): a
baseline recorded from the ordmod load module, compared with an unchanged
copy and with one whose nested subprogram changed a value it writes --
a change no EXPECT in the suite looks at."""

import json
from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

ORDMOD_DIR = Path(__file__).parent.parent.parent / "examples" / "ordmod"


def _copy(target: Path) -> Path:
    target.mkdir()
    for source in ORDMOD_DIR.iterdir():
        if source.is_file():
            (target / source.name).write_text(source.read_text())
    return target


def _run(directory: Path, *extra: str) -> int:
    return main(
        [
            "run",
            str(directory / "ORDMAIN.cbl"),
            "--cut",
            str(directory / "ORDMAIN.cut"),
            "--copybook-path",
            str(directory),
            *extra,
        ]
    )


@requires_docker
def test_baseline_records_and_matches_an_unchanged_module(tmp_path: Path, capsys):
    baseline = tmp_path / "ordmain.json"
    assert _run(ORDMOD_DIR, "--record-baseline", str(baseline)) == 0
    document = json.loads(baseline.read_text())
    first = document["cases"][0]
    labels = [event["label"] for event in first["events"]]
    assert labels[:3] == ["CALL DATEUTL", "OPEN ORDER-FILE", "READ ORDER-FILE"]
    assert "CALL ORDVAL" not in labels  # real calls stay inside the module
    log_lines = [
        e["data"][0] for e in first["events"] if e["label"] == "WRITE LOG-LINE"
    ]
    assert bytes.fromhex(log_lines[1]).decode().startswith("O00002 OVER CREDIT LIMIT")
    assert first["return_code"] is not None
    assert set(document["inputs"]) == {
        "cut",
        "program",
        "real:ORDLOG",
        "real:ORDPUB",
        "real:ORDVAL",
    }

    capsys.readouterr()
    assert _run(_copy(tmp_path / "same"), "--baseline", str(baseline)) == 0
    assert "baseline: 3 same, 0 differ" in capsys.readouterr().out


@requires_docker
def test_baseline_catches_a_change_no_expect_checks(tmp_path: Path, capsys):
    baseline = tmp_path / "ordmain.json"
    assert _run(ORDMOD_DIR, "--record-baseline", str(baseline)) == 0
    changed = _copy(tmp_path / "changed")
    validate = changed / "ORDVAL.cbl"
    validate.write_text(
        validate.read_text().replace('"OVER CREDIT LIMIT"', '"OVER LIMIT"')
    )
    report = tmp_path / "compare.json"
    capsys.readouterr()
    exit_code = _run(
        changed, "--baseline", str(baseline), "--baseline-json", str(report)
    )
    out = capsys.readouterr().out
    assert exit_code == 1, out
    assert "3 run, 0 failed" in out  # every EXPECT still passes
    assert "[DIFFERS] orders under the limit" in out
    assert "WRITE LOG-LINE" in out
    assert '"O00002 OVER CREDIT LIMIT' in out
    comparison = json.loads(report.read_text())
    assert comparison["counts"] == {"same": 2, "differs": 1, "new": 0, "not-run": 0}
    assert comparison["changed_inputs"] == ["real:ORDVAL"]
