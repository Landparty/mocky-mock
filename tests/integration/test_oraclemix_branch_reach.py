"""Generated per-branch suites reach the code the oraclemix behaviour edits
change (2026-11-02): a CICS second screen (EIBCALEN on the path), a
COMMAREA-driven check at its limit, and the "found" path of a real
subprogram's lookup."""

import json
import shutil
from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE = Path(__file__).parent.parent.parent / "examples" / "oraclemix"
SRC = EXAMPLE / "src"
EDITS = EXAMPLE / "edits" / "2-behaviour"


def _differs(tmp_path: Path, entry: str, real: tuple[str, ...], edited: str) -> int:
    for path in SRC.iterdir():
        if path.suffix in (".cbl", ".cpy"):
            shutil.copy(path, tmp_path / path.name)
    source = str(tmp_path / f"{entry}.cbl")
    cut = str(tmp_path / f"{entry}.cut")
    args = ["generate", source, "-o", cut, "--scenarios", "branches"]
    args += ["--copybook-path", str(tmp_path), "--seed", "3"]
    for name in real:
        args += ["--real", str(tmp_path / f"{name}.cbl")]
    assert main(args) == 0
    run = ["run", source, "--cut", cut, "--copybook-path", str(tmp_path)]
    baseline = tmp_path / "baseline.json"
    assert main([*run, "--record-baseline", str(baseline)]) == 0
    shutil.copy(EDITS / f"{edited}.cbl", tmp_path / f"{edited}.cbl")
    compared = tmp_path / "compare.json"
    main([*run, "--baseline", str(baseline), "--baseline-json", str(compared)])
    return int(json.loads(compared.read_text())["counts"]["differs"])


@requires_docker
def test_a_cics_second_screen_is_reached(tmp_path: Path):
    assert _differs(tmp_path, "CUSTINQ", (), "CUSTINQ") >= 1


@requires_docker
def test_a_commarea_check_is_run_at_its_limit(tmp_path: Path):
    assert _differs(tmp_path, "CUSTVAL", (), "CUSTVAL") >= 1


@requires_docker
def test_a_real_lookup_finds_its_record(tmp_path: Path):
    assert _differs(tmp_path, "PRTINQ", ("PRTSTK", "PRTRATE"), "PRTRATE") >= 1
