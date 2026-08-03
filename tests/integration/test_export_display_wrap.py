"""Docker-gated regression guard for the empirical finding behind
mockymock.cli.mainframe_export.wrap_long_display_lines (see
docs/2026-08-03-mainframe-export-command-design.md, Adjustment 2b):
splitting a long generated DISPLAY into `WITH NO ADVANCING` fragments
must not change what actually prints, or the __MOCKYMOCK__ stdout
protocol silently breaks."""

from mockymock.cli.mainframe_export import wrap_long_display_lines
from mockymock.runtime import docker_toolchain
from mockymock.runtime.sandbox import sandbox_dir_maybe_kept
from tests.integration._docker import requires_docker

UNWRAPPED_LINE = (
    '           DISPLAY "__MOCKYMOCK__ CASE 001 FAIL: VERIFY SQL FETCH '
    'CUST_CURSOR WAS CALLED 3 TIMES, got " FUNCTION TRIM(UT-TALLY-EDITED)'
)


@requires_docker
def test_wrapped_display_produces_byte_identical_stdout():
    wrapped_lines, problems = wrap_long_display_lines([UNWRAPPED_LINE])
    assert not problems
    assert len(wrapped_lines) > 1  # actually exercised the wrap, not a no-op
    assert all(len(line) <= 72 for line in wrapped_lines)

    program_lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. WRAPCHK.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        "       01  UT-TALLY-EDITED        PIC Z(8)9.",
        "       PROCEDURE DIVISION.",
        "       MAIN-PARA.",
        "           MOVE 3 TO UT-TALLY-EDITED",
        '           DISPLAY "===UNWRAPPED==="',
        UNWRAPPED_LINE,
        '           DISPLAY "===WRAPPED==="',
        *wrapped_lines,
        '           DISPLAY "===END==="',
        "           STOP RUN.",
    ]
    source = "\n".join(program_lines) + "\n"

    docker_toolchain.ensure_toolchain()
    with sandbox_dir_maybe_kept(root=docker_toolchain.WORK_ROOT, keep=False) as tmp:
        src = tmp / "WRAPCHK.cbl"
        src.write_text(source, encoding="utf-8", newline="\n")
        compiled = docker_toolchain.compile_source(src)
        assert compiled.success, compiled.stderr
        executed = docker_toolchain.run_binary(compiled.binary_path)
        assert executed.exit_code == 0

    stdout_lines = executed.stdout.splitlines()
    unwrapped_out = stdout_lines[stdout_lines.index("===UNWRAPPED===") + 1]
    wrapped_out = stdout_lines[stdout_lines.index("===WRAPPED===") + 1]
    assert wrapped_out == unwrapped_out
