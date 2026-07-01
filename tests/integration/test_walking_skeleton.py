import shutil
from pathlib import Path

import pytest

from mockymock.runtime.compiler import compile_source
from mockymock.runtime.executor import run_binary
from mockymock.runtime.sandbox import sandbox_dir

FIXTURE = Path(__file__).parent / "fixtures" / "walking_skeleton.cbl"

requires_gnucobol = pytest.mark.skipif(
    shutil.which("cobc") is None, reason="GnuCOBOL (cobc) not installed"
)


@requires_gnucobol
def test_walking_skeleton_compiles_and_runs():
    with sandbox_dir() as tmp:
        source_copy = tmp / "walking_skeleton.cbl"
        source_copy.write_text(FIXTURE.read_text())

        compiled = compile_source(source_copy)
        assert compiled.success, compiled.stderr

        executed = run_binary(compiled.binary_path)

    assert executed.exit_code == 0
    assert "__MOCKYMOCK__ TESTSUITE: walking skeleton" in executed.stdout
    assert "__MOCKYMOCK__ CASE 001 START:" in executed.stdout
    assert "__MOCKYMOCK__ CASE 001 END" in executed.stdout
    assert "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0" in executed.stdout
