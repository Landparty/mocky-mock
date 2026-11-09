"""Docker-gated regression guard for the empirical finding behind
mockymock.engine.mainframe_export.wrap_long_literal_lines: a literal split
across fixed-format continuation lines must hold exactly the value the
unsplit literal held.

Two facts are asserted here because both were established by compiling
real COBOL (GnuCOBOL 4.0) while writing that function, and neither is
visible from reading the source:

1. An exactly-filled continued line round-trips the literal byte-for-byte.
2. A continued line left SHORT does not: every character through column 72
   -- the trailing blanks included -- belongs to the open literal, so the
   value comes back with a run of spaces injected at the split point.
   This is why _continue_literal pads each continued line to exactly the
   column limit, and the reason that padding must never be "tidied away".

`docker_toolchain.compile_source` is not used: it hardcodes `-free`,
which is all `run` ever needs, and free-form COBOL has no indicator area
and so no continuation lines at all. This test drives cobc directly, in
fixed format, rather than widening the production toolchain's API for a
test."""

import subprocess

from mockymock.engine.mainframe_export import wrap_long_literal_lines
from mockymock.runtime import docker_toolchain, native_toolchain
from mockymock.runtime.sandbox import sandbox_dir_maybe_kept
from mockymock.runtime.toolchain import active
from tests.integration._docker import requires_docker

# The shape from the bug report: splicer/reset.py re-serializes a wide
# WORKING-STORAGE marker field's VALUE clause into UT-RESET-WORKING-STORAGE
# as a single-line MOVE, which overflows column 72 on its own.
LITERAL = "***** DEBUT WORKING-STORAGE DTBC7D01 ******"
UNWRAPPED_LINE = f'           MOVE "{LITERAL}" TO WS-MARKER'


def _compile_fixed_format(source_path):
    """cobc in FIXED format (`-fixed`), the format `export` writes for."""
    if active() is native_toolchain:
        home = native_toolchain.gnucobol_home()
        assert home is not None
        return subprocess.run(
            [str(home / "bin" / "cobc"), "-x", "-fixed", "-std=mvs", source_path.name]
            + ["-o", source_path.with_suffix("").name],
            cwd=source_path.parent,
            env=native_toolchain._env(home),
            capture_output=True,
            text=True,
            check=False,
        )
    container_source = docker_toolchain.to_container_path(source_path)
    container_binary = docker_toolchain.to_container_path(source_path.with_suffix(""))
    return docker_toolchain._docker(
        "exec",
        "-w",
        container_source.rsplit("/", 1)[0],
        docker_toolchain.CONTAINER,
        "cobc",
        "-x",
        "-fixed",
        "-std=mvs",
        container_source,
        "-o",
        container_binary,
    )


@requires_docker
def test_continued_literal_holds_the_exact_original_value():
    assert len(UNWRAPPED_LINE) > 72
    wrapped, problems = wrap_long_literal_lines([UNWRAPPED_LINE])
    assert not problems
    assert len(wrapped) > 1  # actually exercised the split, not a no-op
    assert all(len(line) <= 72 for line in wrapped)

    # The same literal split at the same point but with the continued line
    # left SHORT of column 72 -- what a wrapper that treated the fill
    # padding as cosmetic would emit. Kept in the same program so one run
    # shows both the correct value and the corruption the rule prevents.
    half = len(LITERAL) // 2
    short = [
        f'           MOVE "{LITERAL[:half]}',
        f'      -    "{LITERAL[half:]}" TO WS-SHORT-FILL',
    ]
    assert len(short[0]) < 72  # the point of the comparison

    program_lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. CONTCHK.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        f"       01  WS-MARKER      PIC X({len(LITERAL)}).",
        f"       01  WS-SHORT-FILL  PIC X({len(LITERAL)}).",
        "       PROCEDURE DIVISION.",
        "       MAIN-PARA.",
        *wrapped,
        *short,
        '           DISPLAY "[" WS-MARKER "]"',
        '           DISPLAY "[" WS-SHORT-FILL "]"',
        "           STOP RUN.",
    ]
    source = "\n".join(program_lines) + "\n"

    toolchain = active()
    toolchain.ensure_toolchain()
    with sandbox_dir_maybe_kept(root=toolchain.WORK_ROOT, keep=False) as tmp:
        src = tmp / "CONTCHK.cbl"
        src.write_text(source, encoding="utf-8", newline="\n")
        compiled = _compile_fixed_format(src)
        assert compiled.returncode == 0, compiled.stderr
        executed = toolchain.run_binary(src.with_suffix(""))
        assert executed.exit_code == 0, executed.stderr

    stdout_lines = executed.stdout.splitlines()
    assert stdout_lines[0] == f"[{LITERAL}]"
    # Fact 2: the same split, left short, silently corrupts the literal.
    assert stdout_lines[1] != f"[{LITERAL}]"
