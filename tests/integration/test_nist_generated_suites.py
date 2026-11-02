"""LegacyLens "Create tests" over a NIST CCVS85 sample, end to end.

For each program under ``examples/nist-cobol85/generated/`` this does what
the runner's ``tests`` job does for a load module (scaffold the suite with
``mockymock generate --scenarios all``, fill its expected values with
``--record-expectations``, play it), then plays the recorded suite again
the way "Run tests" does. A program expected green must pass every case
both times; a program expected refused must stay refused with the same
codes, and nothing may compile or run. ``scripts/nist_cobol85.py check``
runs the same thing over the whole suite.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tests.integration._docker import requires_docker

ROOT = Path(__file__).parent.parent.parent
SAMPLE = ROOT / "examples" / "nist-cobol85" / "generated"
EXPECTED: dict[str, dict] = json.loads((SAMPLE / "expected.json").read_text())


def _script():
    spec = importlib.util.spec_from_file_location(
        "nist_cobol85", ROOT / "scripts" / "nist_cobol85.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@requires_docker
@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_generated_suite_is_created_and_replays(name: str, tmp_path: Path):
    expected = EXPECTED[name]
    result = _script().check_program(SAMPLE, name, tmp_path, timeout=600)
    if expected["verdict"] == "refused":
        assert result["refused"] == expected["refused"], result
        assert not result["create"].get("passed"), result
        return
    assert result["error"] is None, result
    assert result["refused"] == [], result
    assert result["create"] == {"passed": expected["cases"]}, result
    assert result["replay"] == result["create"], result
    created = json.loads((tmp_path / name / "result.json").read_text())
    assert created["recorded"] is True
    if expected["cases"] > 1:
        # No two generated cases may be the same test under two names.
        bodies = [
            tuple(
                line.strip()
                for line in block.splitlines()[1:]
                if line.strip() and not line.strip().startswith("*>")
            )
            for block in created["cut_text"].split("\nTESTCASE ")[1:]
        ]
        assert len(bodies) == len(set(bodies))


def test_expansion_matches_the_committed_sample(tmp_path: Path):
    """The committed sample is what `expand` makes of cobol-parser's raw
    population entries, so the whole-suite check and this sample agree."""
    raw = ROOT.parent / "cobol-parser" / "examples" / "cobol"
    if not raw.is_dir():
        pytest.skip("no ../cobol-parser checkout next to this repo")
    script = _script()
    script.expand(raw, tmp_path)
    for program in SAMPLE.glob("*.C[BP][LY]"):
        assert (tmp_path / program.name).read_text() == program.read_text()
