"""Baseline version 2 on the oraclemix sample: a cursor's DECLARE host
variables are recorded at OPEN, and a CICS LINK target's COMMAREA is
recorded as what it returns (docs/2026-11-01-baseline-design.md)."""

import json
import shutil
from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

SRC = Path(__file__).parent.parent.parent / "examples" / "oraclemix" / "src"


def _record(tmp_path: Path, program: str) -> dict:
    work = tmp_path / program
    work.mkdir()
    for name in (f"{program}.cbl", "CUSTREC.cpy"):
        shutil.copy(SRC / name, work / name)
    cut = work / f"{program}.cut"
    source = str(work / f"{program}.cbl")
    assert main(["generate", source, "--copybook-path", str(work), "-o", str(cut)]) == 0
    baseline = work / "baseline.json"
    code = main(
        [
            "run",
            source,
            "--cut",
            str(cut),
            "--copybook-path",
            str(work),
            "--record-baseline",
            str(baseline),
        ]
    )
    assert code == 0
    return json.loads(baseline.read_text())


@requires_docker
def test_cursor_open_records_the_declare_host_variables(tmp_path: Path):
    document = _record(tmp_path, "DB2RPT")
    assert document["version"] >= 2
    events = document["cases"][0]["events"]
    labels = [event["label"] for event in events]
    opened = labels.index("SQL OPEN")
    assert labels[opened + 1] == "SQL CURSOR CUSTCUR"
    assert bytes.fromhex(events[opened + 1]["data"][0]) == b"EAST"


@requires_docker
def test_a_link_target_records_the_commarea_it_returns(tmp_path: Path):
    document = _record(tmp_path, "CUSTVAL")
    events = document["cases"][0]["events"]
    assert events[-1]["label"] == "RETURNED LINKAGE"
    returned = bytes.fromhex(events[-1]["data"][0])
    assert len(returned) == 8 and returned[6:] in (b"OK", b"NO")
