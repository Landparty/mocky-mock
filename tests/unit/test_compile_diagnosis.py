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


def _toolchain_with_extra(success: bool, stderr: str = ""):
    calls: list[tuple[Path, list[Path]]] = []

    def compile_source(path: Path, extra_sources=()):
        calls.append((path, list(extra_sources)))
        return SimpleNamespace(success=success, stderr=stderr)

    return SimpleNamespace(compile_source=compile_source), calls


REAL = (
    "real_ORDLOG.cbl",
    "ORDLOG",
    ["       PROCEDURE DIVISION.", "           MOVE 1 TO NOPE."],
)


def test_a_real_program_that_does_not_compile_is_named(tmp_path: Path):
    """2026-11-05: an undefined name in a USE REAL CALL program was reported
    as "the program compiles on its own ... a mockymock bug"."""
    stderr = f"{tmp_path}/UTPROBE/real_ORDLOG.cbl:2: error: 'NOPE' is not defined\n"
    toolchain, calls = _toolchain_with_extra(False, stderr)
    message = _compile_failure_diagnosis(
        toolchain, tmp_path, LINES, stderr, real_programs=[REAL]
    )
    assert message is not None and "mockymock bug" not in message
    assert "the real program ORDLOG (USE REAL CALL) does not compile" in message
    assert "(line 2: error: 'NOPE' is not defined)" in message
    ((probe, extra),) = calls
    assert [p.name for p in extra] == ["real_ORDLOG.cbl"]
    assert extra[0].read_text().splitlines() == REAL[2]


def test_real_programs_that_compile_leave_the_mockymock_verdict(tmp_path: Path):
    toolchain, _ = _toolchain_with_extra(True)
    message = _compile_failure_diagnosis(
        toolchain, tmp_path, LINES, "", real_programs=[REAL]
    )
    assert message is not None and "mockymock bug" in message


def test_an_error_in_a_real_program_with_exec_blocks_gets_no_verdict(tmp_path: Path):
    toolchain, calls = _toolchain_with_extra(True)
    real = ("real_DB.cbl", "DB", ["           EXEC SQL COMMIT END-EXEC."])
    stderr = "real_DB.cbl:1: error: syntax error\n"
    assert (
        _compile_failure_diagnosis(
            toolchain, tmp_path, LINES, stderr, real_programs=[real]
        )
        is None
    )
    assert calls == []
