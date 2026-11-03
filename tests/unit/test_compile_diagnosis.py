"""Whose compile failure it is (2026-11-03, sample sweep): a program plain
GnuCOBOL rejects is not a mockymock bug, and run says which it is."""

from pathlib import Path
from types import SimpleNamespace

from mockymock.cli.main import _compile_failure_diagnosis


def _toolchain(success: bool, stderr: str = ""):
    calls: list[Path] = []

    def compile_source(path: Path):
        calls.append(path)
        return SimpleNamespace(success=success, stderr=stderr)

    return SimpleNamespace(compile_source=compile_source), calls


LINES = ["       PROCEDURE DIVISION.", "           ADD CORRESPONDING A TO B."]


def test_the_program_itself_does_not_compile(tmp_path: Path):
    toolchain, calls = _toolchain(
        False, f"{tmp_path}/UTPROBE/PROBE.cbl:2: error: 'B' is not a group name\n"
    )
    message = _compile_failure_diagnosis(toolchain, tmp_path, LINES)
    assert message is not None
    assert "does not compile under GnuCOBOL even without" in message
    assert "(line 2: error: 'B' is not a group name)" in message
    assert calls[0].read_text().splitlines() == LINES


def test_the_program_compiles_alone_so_mockymock_broke_it(tmp_path: Path):
    toolchain, _ = _toolchain(True)
    message = _compile_failure_diagnosis(toolchain, tmp_path, LINES)
    assert message is not None and "mockymock bug" in message


def test_no_verdict_for_a_program_with_exec_blocks(tmp_path: Path):
    toolchain, calls = _toolchain(False)
    lines = [*LINES, "           EXEC SQL SELECT 1 INTO :X END-EXEC."]
    assert _compile_failure_diagnosis(toolchain, tmp_path, lines) is None
    assert calls == []


def test_a_check_that_cannot_run_says_nothing(tmp_path: Path):
    def compile_source(path: Path):
        raise OSError("no cobc")

    toolchain = SimpleNamespace(compile_source=compile_source)
    assert _compile_failure_diagnosis(toolchain, tmp_path, LINES) is None
