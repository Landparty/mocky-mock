"""`mockymock runner` end to end on a LegacyLens-shaped pack of the ordmod
load module: a baseline job scaffolds the suite and records it, then a
compare job with the frozen .cut catches a change in a nested subprogram."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from mockymock.runner import run_job
from tests.integration._docker import requires_docker

ORDMOD_DIR = Path(__file__).parent.parent.parent / "examples" / "ordmod"
ROOT = "ORDMAIN-integration-tests"
GENERATE = (
    "mockymock generate src/ORDMAIN.cbl --real src/ORDVAL.cbl "
    "--real src/ORDPUB.cbl --real src/ORDLOG.cbl"
)


def _pack(kind: str, extra: dict[str, str], ordlog: str | None = None) -> bytes:
    suite = {
        "entry": "ORDMAIN",
        "program": "src/ORDMAIN.cbl",
        "cut": "tests/ORDMAIN.cut",
        "generate": GENERATE,
        "baseline": "baselines/ORDMAIN.json" if kind == "compare" else None,
    }
    manifest = {
        "version": 1,
        "kind": kind,
        "load_module": "ORDMAIN",
        "copybook_path": "copybooks",
        "suites": [suite],
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for source in ORDMOD_DIR.glob("*.cbl"):
            text = source.read_text()
            if source.name == "ORDLOG.cbl" and ordlog is not None:
                text = ordlog
            archive.writestr(f"{ROOT}/src/{source.name}", text)
        archive.writestr(
            f"{ROOT}/copybooks/ORDREC.cpy", (ORDMOD_DIR / "ORDREC.cpy").read_text()
        )
        archive.writestr(f"{ROOT}/oracle.json", json.dumps(manifest))
        for path, text in extra.items():
            archive.writestr(f"{ROOT}/{path}", text)
    return out.getvalue()


@requires_docker
def test_runner_records_then_compares_a_load_module(tmp_path: Path):
    recorded = run_job(_pack("baseline", {}), work_dir=tmp_path)
    (suite,) = recorded["suites"]
    assert "error" not in suite, suite["log"]
    assert suite["baseline"]["cases"], suite["log"]
    assert "USE REAL CALL" in suite["cut_text"]
    frozen = {
        "tests/ORDMAIN.cut": suite["cut_text"],
        "baselines/ORDMAIN.json": json.dumps(suite["baseline"]),
    }

    same = run_job(_pack("compare", frozen), work_dir=tmp_path)
    assert same["suites"][0]["comparison"]["matches"] is True, same["suites"][0]["log"]

    ordlog = (ORDMOD_DIR / "ORDLOG.cbl").read_text()
    changed_source = ordlog.replace('" " DELIMITED BY SIZE', '"-" DELIMITED BY SIZE')
    assert changed_source != ordlog
    changed = run_job(
        _pack("compare", frozen, ordlog=changed_source), work_dir=tmp_path
    )
    comparison = changed["suites"][0]["comparison"]
    assert comparison["matches"] is False
    assert comparison["changed_inputs"] == ["real:ORDLOG"]
    assert changed["suites"][0]["exit_code"] == 1
