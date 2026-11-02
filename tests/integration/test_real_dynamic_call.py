"""A dynamic CALL reaches a USE REAL CALL program (docs/2026-11-02-real-
dynamic-call-design.md): DYNDRV's `CALL WS-RATE-PGM` runs RATECALC for real
when WS-RATE-PGM names it, so a change to RATECALC changes the baseline."""

import json
import shutil
from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

SRC = Path(__file__).parent.parent.parent / "examples" / "oraclemix" / "src"


def _run(work: Path, *extra: str) -> int:
    return main(
        [
            "run",
            str(work / "DYNDRV.cbl"),
            "--cut",
            str(work / "DYNDRV.cut"),
            "--copybook-path",
            str(work),
            *extra,
        ]
    )


@requires_docker
def test_a_real_program_reached_by_a_dynamic_call_runs(tmp_path: Path):
    for name in ("DYNDRV.cbl", "RATECALC.cbl"):
        shutil.copy(SRC / name, tmp_path / name)
    cut = tmp_path / "DYNDRV.cut"
    code = main(
        [
            "generate",
            str(tmp_path / "DYNDRV.cbl"),
            "--real",
            str(tmp_path / "RATECALC.cbl"),
            "-o",
            str(cut),
        ]
    )
    assert code == 0
    text = cut.read_text()
    assert 'USE REAL CALL "RATECALC"' in text
    assert "MOCK CALL WS-RATE-PGM" in text
    cut.write_text(
        text.replace(
            "    PERFORM 0000-MAIN",
            '    PERFORM 0000-MAIN\n    VERIFY CALL "RATECALC" WAS CALLED 10 TIMES',
        )
    )
    baseline = tmp_path / "baseline.json"
    assert _run(tmp_path, "--record-baseline", str(baseline)) == 0
    written = [
        bytes.fromhex(event["data"][0])
        for event in json.loads(baseline.read_text())["cases"][0]["events"]
        if event["label"] == "WRITE INV-OUT-REC"
    ]
    # RATECALC's 15%, not the mock's placeholder tax.
    amount, tax = int(written[0][6:15]), int(written[0][15:24])
    assert tax == (amount * 15 + 50) // 100

    source = tmp_path / "RATECALC.cbl"
    source.write_text(source.read_text().replace("0.15", "0.16"))
    compared = tmp_path / "compare.json"
    assert _run(tmp_path, "--baseline", str(baseline), "--baseline-json", str(compared))
    assert json.loads(compared.read_text())["counts"]["differs"] == 1
