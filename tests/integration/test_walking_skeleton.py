from pathlib import Path

from mockymock.runtime.docker_toolchain import (
    WORK_ROOT,
    compile_source,
    ensure_toolchain,
    run_binary,
)
from mockymock.runtime.sandbox import sandbox_dir
from tests.integration._docker import requires_docker

FIXTURE = Path(__file__).parent / "fixtures" / "walking_skeleton.cbl"


@requires_docker
def test_walking_skeleton_compiles_and_runs():
    ensure_toolchain()
    with sandbox_dir(root=WORK_ROOT) as tmp:
        source_copy = tmp / "walking_skeleton.cbl"
        source_copy.write_text(FIXTURE.read_text(), newline="\n")

        compiled = compile_source(source_copy)
        assert compiled.success, compiled.stderr

        executed = run_binary(compiled.binary_path)

    assert executed.exit_code == 0
    assert "__MOCKYMOCK__ TESTSUITE: walking skeleton" in executed.stdout
    assert "__MOCKYMOCK__ CASE 001 START:" in executed.stdout
    assert "__MOCKYMOCK__ CASE 001 END" in executed.stdout
    assert "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0" in executed.stdout
