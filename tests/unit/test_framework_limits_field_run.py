"""Framework limits a field run against legacy-application hit (INTCALC,
the UNRESOLVED_COPYBOOK refusal, the libxml warning):

- `generate --per-paragraph` PERFORMs a paragraph THRU the exit the
  program itself names, so the scaffold tests the flow the program runs;
- a case whose GO TO runs past the program's last paragraph fails with a
  message saying so, instead of a bare `binary exited with code 4`;
- copybook folders beside the program's folder are searched unasked;
- libxml2's version-mismatch line no longer reaches the console."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from mockymock.cli.discovery import effective_copybook_paths
from mockymock.cli.main import _insert_driver_with_origins, main
from mockymock.dsl.parser import parse_cut
from mockymock.runtime.docker_toolchain import run_binary
from mockymock.splicer.driver import END_OF_PROGRAM_TRAP
from tests.unit.test_docker_toolchain import _completed, _work

_THRU_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RC                PIC S9(4) COMP VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 2200-CALC THRU 2200-EXIT
           PERFORM 3000-FINALIZE
           STOP RUN.
       2200-CALC.
           CALL 'CALCRTN' USING WS-RC
           IF WS-RC NOT = ZERO
               GO TO 2200-EXIT
           END-IF
           DISPLAY 'CALC OK'.
       2200-EXIT.
           EXIT.
       3000-FINALIZE.
           CALL 'CLOSERTN' USING WS-RC.
"""


def _generate(tmp_path, source: str):
    program = tmp_path / "THRUPGM.cbl"
    program.write_text(source)
    cut = tmp_path / "THRUPGM.cut"
    assert main(["generate", str(program), "--per-paragraph", "-o", str(cut)]) == 0
    return parse_cut(cut.read_text())


def test_scaffold_performs_thru_the_programs_own_exit_paragraph(tmp_path):
    suite = _generate(tmp_path, _THRU_PROGRAM)
    case = next(c for c in suite.test_cases if c.perform_target == "2200-CALC")
    assert case.perform_thru == "2200-EXIT"
    # 3000-FINALIZE lies past the range, so its CALL is not mocked here.
    assert {m.key for m in case.mocks} == {"CALCRTN"}


def test_scaffold_keeps_a_bare_perform_when_the_program_performs_it_bare(
    tmp_path,
):
    suite = _generate(
        tmp_path,
        _THRU_PROGRAM.replace(
            "           PERFORM 3000-FINALIZE\n",
            "           PERFORM 3000-FINALIZE\n           PERFORM 2200-CALC\n",
        ),
    )
    case = next(c for c in suite.test_cases if c.perform_target == "2200-CALC")
    assert case.perform_thru is None


def _artifact():
    return SimpleNamespace(
        working_storage_lines=["01  UT-CURRENT-CASE PIC X(9)."],
        procedure_lines=["       UT-DRIVER.", "           STOP RUN."],
    )


def test_end_of_program_trap_follows_the_last_paragraph():
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. P.",
        "       PROCEDURE DIVISION.",
        "       A.",
        "           DISPLAY 'A'.",
        "       END PROGRAM P.",
    ]
    result, inserted = _insert_driver_with_origins(lines, _artifact())
    header = result.index(f"       {END_OF_PROGRAM_TRAP} SECTION.")
    assert result.index("           DISPLAY 'A'.") < header
    assert result[-1] == "       END PROGRAM P."
    assert "ran past the last paragraph" in " ".join(result[header:])
    # Every trap line is reported as inserted; the program's own are not.
    assert header in inserted
    assert result.index("           DISPLAY 'A'.") not in inserted
    assert len(result) - 1 not in inserted
    # A terminated last sentence gets no redundant period (cobc warns).
    assert "           ." not in result


def test_end_of_program_trap_closes_an_unterminated_last_sentence():
    lines = [
        "       PROCEDURE DIVISION.",
        "       A.",
        "           DISPLAY 'A'",
        "      *    a trailing comment line",
    ]
    result, _ = _insert_driver_with_origins(lines, _artifact())
    header = result.index(f"       {END_OF_PROGRAM_TRAP} SECTION.")
    assert "           ." in result[:header]


def test_copybook_folder_beside_the_programs_folder_is_searched(tmp_path):
    (tmp_path / "cobol").mkdir()
    (tmp_path / "copybook").mkdir()
    program = tmp_path / "cobol" / "INTCALC.cbl"
    program.write_text("")
    assert effective_copybook_paths(program, []) == [str(tmp_path / "copybook")]


def test_own_copybooks_folder_still_comes_first(tmp_path):
    (tmp_path / "cobol" / "copybooks").mkdir(parents=True)
    (tmp_path / "cpy").mkdir()
    program = tmp_path / "cobol" / "P.cbl"
    program.write_text("")
    assert effective_copybook_paths(program, ["explicit"]) == [
        "explicit",
        str(tmp_path / "cobol" / "copybooks"),
        str(tmp_path / "cpy"),
    ]


def test_run_binary_drops_the_libxml_version_warning(tmp_path):
    work, source = _work(tmp_path)
    binary = source.parent / "PROG"
    binary.write_text("")

    def fake_run(argv, **kwargs):
        return _completed(
            argv,
            stdout=b"__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n",
            stderr=(
                b"Warning: program compiled against libxml 212 using older 209\n"
                b"libcob: error: something real\n"
            ),
        )

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        executed = run_binary(binary)
    assert executed.stderr == "libcob: error: something real\n"
