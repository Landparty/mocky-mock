"""CLI behavior around the Docker toolchain, with the toolchain mocked --
these tests must pass without Docker installed."""

import json
from pathlib import Path
from unittest import mock

import pytest

from mockymock.cli.main import main
from mockymock.runtime.docker_toolchain import DockerNotAvailableError


def test_setup_reports_container_and_cobc_version(capsys):
    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain") as ensure,
        mock.patch(
            "mockymock.runtime.docker_toolchain.cobc_version",
            return_value="cobc (GnuCOBOL) 3.2.0",
        ),
    ):
        exit_code = main(["setup"])
    assert exit_code == 0
    ensure.assert_called_once()
    out = capsys.readouterr().out
    assert "mockymock-cobc" in out
    assert "cobc (GnuCOBOL) 3.2.0" in out


def test_setup_fails_loudly_when_docker_unavailable(capsys):
    with mock.patch(
        "mockymock.runtime.docker_toolchain.ensure_toolchain",
        side_effect=DockerNotAvailableError("Docker is required: start Docker Desktop"),
    ):
        exit_code = main(["setup"])
    assert exit_code == 1
    assert "Docker is required" in capsys.readouterr().out


# --- audit 4.9: run's --*-xml/--*-json/--*-out writes report a bad target
# instead of tracebacking after an otherwise-successful run -----------------


def test_write_report_file_reports_oserror_instead_of_tracebacking(tmp_path, capsys):
    from mockymock.cli.main import _write_report_file

    bad_target = tmp_path / "does-not-exist" / "report.xml"
    ok = _write_report_file("run", "--junit-xml", str(bad_target), "<testsuite/>")
    assert ok is False
    assert not bad_target.exists()
    out = capsys.readouterr().out
    assert "could not write --junit-xml" in out
    assert str(bad_target) in out


def test_write_report_file_writes_content_on_success(tmp_path):
    from mockymock.cli.main import _write_report_file

    target = tmp_path / "report.xml"
    ok = _write_report_file("run", "--junit-xml", str(target), "<testsuite/>")
    assert ok is True
    assert target.read_text() == "<testsuite/>"


def test_run_reports_static_problems_without_needing_docker(tmp_path, capsys):
    """Static checks run BEFORE ensure_toolchain (see the lint design doc):
    a program with parse errors surfaces its real problem even when Docker
    is down, instead of a misleading Docker message."""
    program = tmp_path / "PROG.cbl"
    program.write_text("dummy\n")
    cut = tmp_path / "PROG.cut"
    cut.write_text('TESTSUITE "x"\n')
    with mock.patch(
        "mockymock.runtime.docker_toolchain.ensure_toolchain",
        side_effect=DockerNotAvailableError("Docker is required: start Docker Desktop"),
    ) as ensure:
        exit_code = main(["run", str(program), "--cut", str(cut)])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "Docker is required" not in out
    assert "refused" in out
    ensure.assert_not_called()


def test_run_fails_loudly_when_docker_unavailable_and_inputs_clean(capsys):
    """Once the static checks pass, a Docker-unavailable environment still
    surfaces the actionable toolchain message before any sandbox work."""
    example = Path(__file__).resolve().parents[2] / "examples" / "ordrproc"
    program = example / "ORDRPROC.cbl"
    cut = example / "ORDRPROC.cut"
    with mock.patch(
        "mockymock.runtime.docker_toolchain.ensure_toolchain",
        side_effect=DockerNotAvailableError("Docker is required: start Docker Desktop"),
    ):
        exit_code = main(["run", str(program), "--cut", str(cut)])
    assert exit_code == 1
    assert "Docker is required" in capsys.readouterr().out


def test_run_reports_missing_input_files_before_touching_docker(tmp_path, capsys):
    """Nonexistent program/--cut paths must produce a clean per-file error
    and exit 1 without ever calling ensure_toolchain -- never a
    FileNotFoundError traceback after a multi-minute image build."""
    with mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain") as ensure:
        exit_code = main(
            ["run", str(tmp_path / "NOPE.cbl"), "--cut", str(tmp_path / "NOPE.cut")]
        )
    assert exit_code == 1
    ensure.assert_not_called()
    out = capsys.readouterr().out
    assert f"mockymock run: no such file: {tmp_path / 'NOPE.cbl'}" in out
    assert f"mockymock run: no such file: {tmp_path / 'NOPE.cut'}" in out


def test_generate_reports_missing_program_cleanly(tmp_path, capsys):
    exit_code = main(["generate", str(tmp_path / "NOPE.cbl")])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert f"mockymock generate: no such file: {tmp_path / 'NOPE.cbl'}" in out


def test_generate_describes_future_neutralization_not_past_tense(tmp_path, capsys):
    """`generate` never applies `splicer.linkage.neutralize` -- it only
    scaffolds a `.cut` from the AST -- so its message must describe what a
    later `run` will do, not claim an edit that didn't happen on this path."""
    program = tmp_path / "LKGSAMP.cbl"
    program.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. LKGSAMP.\n"
        "\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-DONE PIC X VALUE 'N'.\n"
        "\n"
        "       LINKAGE SECTION.\n"
        "       01  CUST-PCB-LNK.\n"
        "           05  CUST-STATUS       PIC X(02).\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       ENTRY 'DLITCBL' USING CUST-PCB-LNK.\n"
        "       0000-MAIN.\n"
        "           CALL 'CBLTDLI' USING CUST-PCB-LNK\n"
        "           STOP RUN.\n"
    )
    exit_code = main(["generate", str(program), "-o", str(tmp_path / "out.cut")])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "will neutralize ENTRY statement(s) ('DLITCBL')" in out
    assert "neutralized ENTRY statement(s)" not in out


def test_run_parser_accepts_keep_sandbox_and_verbose():
    from mockymock.cli.main import build_parser

    args = build_parser().parse_args(
        ["run", "P.cbl", "--cut", "P.cut", "--keep-sandbox", "--verbose"]
    )
    assert args.keep_sandbox is True
    assert args.verbose is True


# --- full `run` pipeline with the Docker toolchain mocked --------------------
#
# These drive _cmd_run end to end (real parse, refusal gate, splice, driver
# build) and fake only the container: compile always succeeds, and run_binary
# returns a canned ExecutionResult. This is what pins finding 4.2: stderr,
# the exit-124 timeout hint, and nonzero binary exit codes must all reach the
# user instead of being silently discarded.


from mockymock.runtime.compiler import CompileResult
from mockymock.runtime.executor import TIMEOUT_EXIT_CODE, ExecutionResult

RUN_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDRPROC.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.

       PROCEDURE DIVISION.
       PROCESS-ORDER.
           CALL "DISCRATE" USING WS-AMOUNT.
"""

RUN_CUT = """\
TESTSUITE "ORDRPROC"

TESTCASE "calls discrate"
    MOCK CALL "DISCRATE"
        MOVE 0 TO RETURN-CODE
    END-MOCK
    PERFORM PROCESS-ORDER
    VERIFY "DISCRATE" WAS CALLED ONCE
"""

CLEAN_STDOUT = (
    "__MOCKYMOCK__ TESTSUITE: ORDRPROC\n"
    "__MOCKYMOCK__ CASE 001 START: calls discrate\n"
    "__MOCKYMOCK__ CASE 001 END\n"
    "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
)


def _run_cli(tmp_path, executed: ExecutionResult, extra_args=()):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)

    def fake_compile(
        source_path: Path, coverage: bool = False, trace: bool = False
    ) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")

    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=fake_compile,
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_binary", return_value=executed
        ),
    ):
        return main(["run", str(program), "--cut", str(cut), *extra_args])


def test_run_exits_zero_and_writes_junit_xml_on_clean_pass(tmp_path, capsys):
    junit_path = tmp_path / "out" / "report.xml"
    junit_path.parent.mkdir()
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    exit_code = _run_cli(tmp_path, executed, ["--junit-xml", str(junit_path)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[PASS] calls discrate" in out
    xml_text = junit_path.read_text()
    assert '<testsuite name="ORDRPROC"' in xml_text
    assert 'failures="0"' in xml_text


def test_run_surfaces_timeout_hint_and_fails_on_exit_124(tmp_path, capsys):
    """The exit-124 infinite-loop hint that run_binary attaches to stderr
    must reach CLI output, the crash must be framed as a timeout (not the
    STOP RUN hypothesis), and the run must exit nonzero."""
    truncated = (
        "__MOCKYMOCK__ TESTSUITE: ORDRPROC\n"
        "__MOCKYMOCK__ CASE 001 START: calls discrate\n"
    )
    hint = (
        "mockymock: binary timed out after 30s (a mocked CALL may have "
        "removed a loop's terminating condition, producing an infinite loop)\n"
    )
    junit_path = tmp_path / "report.xml"
    executed = ExecutionResult(
        exit_code=TIMEOUT_EXIT_CODE, stdout=truncated, stderr=hint
    )
    exit_code = _run_cli(tmp_path, executed, ["--junit-xml", str(junit_path)])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "a mocked CALL may have removed a loop's terminating" in out
    assert "binary timed out (exit 124)" in out
    assert "STOP RUN" not in out
    xml_text = junit_path.read_text()
    assert "binary timed out (exit 124)" in xml_text
    assert "STOP RUN" not in xml_text


def test_run_surfaces_stderr_and_fails_on_nonzero_exit_after_summary(tmp_path, capsys):
    """A libcob abort after the SUMMARY line printed used to exit 0 with its
    stderr discarded; both the exit code and the evidence must surface."""
    executed = ExecutionResult(
        exit_code=134,
        stdout=CLEAN_STDOUT,
        stderr="libcob: error: numeric overflow\n",
    )
    exit_code = _run_cli(tmp_path, executed)
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "libcob: error: numeric overflow" in out


def test_run_zero_exit_crash_keeps_stop_run_hypothesis(tmp_path, capsys):
    """When the binary exits 0 but a case never printed its END marker, the
    STOP RUN hypothesis is the honest guess (STOP RUN exits 0) and stays."""
    truncated = (
        "__MOCKYMOCK__ TESTSUITE: ORDRPROC\n"
        "__MOCKYMOCK__ CASE 001 START: calls discrate\n"
    )
    junit_path = tmp_path / "report.xml"
    executed = ExecutionResult(exit_code=0, stdout=truncated, stderr="")
    exit_code = _run_cli(tmp_path, executed, ["--junit-xml", str(junit_path)])
    assert exit_code == 1  # all_passed is False: no SUMMARY line
    assert "STOP RUN?" in junit_path.read_text()


def test_run_zero_exit_crash_gives_a_reason_on_console_and_in_json(tmp_path, capsys):
    """Issue #238: a GO TO out of the PERFORMed range runs off the end of the
    program and exits 0 -- the [CRASH] line and crashDetail must say why
    instead of being blank/null."""
    truncated = (
        "__MOCKYMOCK__ TESTSUITE: ORDRPROC\n"
        "__MOCKYMOCK__ CASE 001 START: calls discrate\n"
    )
    json_path = tmp_path / "report.json"
    executed = ExecutionResult(exit_code=0, stdout=truncated, stderr="")
    assert _run_cli(tmp_path, executed, ["--json-report", str(json_path)]) == 1
    out = capsys.readouterr().out
    assert "control never returned to the test driver" in out
    (case,) = json.loads(json_path.read_text())["cases"][:1]
    assert "GO TO left the PERFORMed range" in case["crashDetail"]


def test_run_reports_cut_parse_error_cleanly(tmp_path, capsys):
    """A .cut syntax error must print the parser's line-numbered message and
    exit 1 -- not a raw CutParseError traceback (finding 3.4)."""
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "BAD.cut"
    cut.write_text('TESTSUITE "x"\nNOT-A-DIRECTIVE\n')
    with mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"):
        exit_code = main(["run", str(program), "--cut", str(cut)])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert f"mockymock run: invalid .cut file {cut}" in out
    assert "line 2" in out


# --- ENTRY/LINKAGE neutralization plumbing (Docker toolchain mocked) --------
#
# docs/2026-07-08-ims-linkage-support-design.md. These pin the CLI wiring
# (transparency message, no crash/exception through the pipeline) with the
# real GnuCOBOL toolchain faked; the real-compile proof lives in
# tests/integration/test_realworld_acctprg_example.py (@requires_docker).

LINKAGE_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LKGSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DONE PIC X VALUE 'N'.

       LINKAGE SECTION.
       01  CUST-PCB-LNK.
           05  CUST-DBD-NAME     PIC X(08).
           05  CUST-STATUS       PIC X(02).

       PROCEDURE DIVISION.
       ENTRY 'DLITCBL' USING CUST-PCB-LNK.
       0000-MAIN.
           CALL 'CBLTDLI' USING CUST-PCB-LNK
           DISPLAY CUST-STATUS
           STOP RUN.
"""

LINKAGE_CUT = """\
TESTSUITE "LKGSAMP"

TESTCASE "0000-MAIN reads CUST-STATUS after CBLTDLI"
    MOCK CALL "CBLTDLI"
        MOVE SPACES TO CUST-STATUS
    END-MOCK
    PERFORM 0000-MAIN
    VERIFY CALL "CBLTDLI" WAS CALLED ONCE
"""

LINKAGE_CLEAN_STDOUT = (
    "__MOCKYMOCK__ TESTSUITE: LKGSAMP\n"
    "__MOCKYMOCK__ CASE 001 START: 0000-MAIN reads CUST-STATUS after CBLTDLI\n"
    "__MOCKYMOCK__ CASE 001 END\n"
    "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
)


def test_run_neutralizes_entry_linkage_and_reports_it(tmp_path, capsys):
    program = tmp_path / "LKGSAMP.cbl"
    program.write_text(LINKAGE_PROGRAM)
    cut = tmp_path / "LKGSAMP.cut"
    cut.write_text(LINKAGE_CUT)

    def fake_compile(
        source_path: Path, coverage: bool = False, trace: bool = False
    ) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")

    executed = ExecutionResult(exit_code=0, stdout=LINKAGE_CLEAN_STDOUT, stderr="")
    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=fake_compile,
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_binary", return_value=executed
        ),
    ):
        exit_code = main(["run", str(program), "--cut", str(cut)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "neutralized ENTRY statement(s) ('DLITCBL')" in out
    assert "folded LINKAGE SECTION into WORKING-STORAGE (CUST-PCB-LNK)" in out


# --- --coverage flag (docs/2026-07-17-coverage-reporting-design.md) --------

from mockymock.runtime.docker_toolchain import GcovResult


def _gcov_side_effect(*uncovered_substrings: str):
    """A `run_gcov` stand-in that produces gcov text for the REAL
    instrumented file mockymock just wrote, marking every line containing
    one of `uncovered_substrings` as never-executed and every other
    non-blank, non-comment line as executed once.

    Deriving the gcov text from the actual instrumented source (rather
    than a hand-written blob with invented line numbers) is what makes the
    instrumented -> original remap under test meaningful here: the line
    numbers gcov reports are line numbers that really exist in the file
    the remap aligns against, so an assertion about an ORIGINAL line
    number is an assertion about the remap, not about a coincidence.
    """

    def side_effect(instrumented_path, *args, **kwargs):
        lines = instrumented_path.read_text(encoding="utf-8").splitlines()
        rendered = [f"        -:    0:Source:{instrumented_path.name}"]
        for number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("*>"):
                marker = "        -"
            elif any(needle in line for needle in uncovered_substrings):
                marker = "    #####"
            else:
                marker = "        1"
            rendered.append(f"{marker}:{number:5d}:{line}")
        return GcovResult(success=True, gcov_text="\n".join(rendered) + "\n", stderr="")

    return side_effect


def _run_cli_with_coverage(tmp_path, executed: ExecutionResult, gcov_side_effect):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)

    def fake_compile(
        source_path: Path, coverage: bool = False, trace: bool = False
    ) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")

    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=fake_compile,
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_binary", return_value=executed
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_gcov",
            side_effect=gcov_side_effect,
        ) as gcov_mock,
    ):
        exit_code = main(["run", str(program), "--cut", str(cut), "--coverage"])
    return exit_code, gcov_mock


def test_run_coverage_leads_with_the_original_programs_own_number(tmp_path, capsys):
    """The headline coverage figure names the ORIGINAL .cbl and lists the
    original file's own uncovered lines, by their original line numbers.
    The instrumented sandbox copy's number -- inflated by mockymock's
    injected dispatch/driver lines, which is exactly why it is the wrong
    number to lead with -- still appears, once, on a subordinate line that
    says so."""
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    exit_code, gcov_mock = _run_cli_with_coverage(
        tmp_path, executed, _gcov_side_effect("PROCESS-ORDER.")
    )
    assert exit_code == 0
    gcov_mock.assert_called_once()
    out = capsys.readouterr().out
    assert "coverage: 100.00% of ORDRPROC.cbl's own lines executed" not in out
    assert "of ORDRPROC.cbl's own lines executed" in out
    # PROCESS-ORDER. is line 9 of RUN_PROGRAM -- an ORIGINAL line number,
    # not the instrumented one gcov actually reported.
    assert "  9: PROCESS-ORDER." in out
    assert "instrumented sandbox copy" in out


def test_run_coverage_without_flag_never_calls_gcov(tmp_path, capsys):
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)

    def fake_compile(
        source_path: Path, coverage: bool = False, trace: bool = False
    ) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")

    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=fake_compile,
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_binary", return_value=executed
        ),
        mock.patch("mockymock.runtime.docker_toolchain.run_gcov") as gcov_mock,
    ):
        exit_code = main(["run", str(program), "--cut", str(cut)])
    assert exit_code == 0
    gcov_mock.assert_not_called()
    assert "coverage:" not in capsys.readouterr().out


def test_run_coverage_writes_coverage_out_file(tmp_path, capsys):
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)
    out_path = tmp_path / "coverage.txt"

    def fake_compile(
        source_path: Path, coverage: bool = False, trace: bool = False
    ) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")

    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=fake_compile,
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_binary", return_value=executed
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_gcov",
            side_effect=_gcov_side_effect("PROCESS-ORDER."),
        ),
    ):
        exit_code = main(
            [
                "run",
                str(program),
                "--cut",
                str(cut),
                "--coverage",
                "--coverage-out",
                str(out_path),
            ]
        )
    assert exit_code == 0
    written = out_path.read_text()
    assert "of ORDRPROC.cbl's own lines executed" in written
    assert "  9: PROCESS-ORDER." in written


def test_coverage_out_alone_implies_coverage(tmp_path, capsys):
    """Audit finding F12: --coverage-out without --coverage used to be a
    silent no-op -- exits 0, prints nothing about coverage, writes no
    file. docs/options-reference.md already documents "Implies
    --coverage" (matching --coverage-json's own precedent one line
    away); the code must match the doc."""
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)
    out_path = tmp_path / "coverage.txt"

    def fake_compile(
        source_path: Path, coverage: bool = False, trace: bool = False
    ) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")

    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=fake_compile,
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_binary", return_value=executed
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_gcov",
            side_effect=_gcov_side_effect("PROCESS-ORDER."),
        ) as gcov_mock,
    ):
        exit_code = main(
            ["run", str(program), "--cut", str(cut), "--coverage-out", str(out_path)]
        )
    assert exit_code == 0
    gcov_mock.assert_called_once()
    assert "of ORDRPROC.cbl's own lines executed" in out_path.read_text()


def test_coverage_fail_under_gates_on_the_original_programs_coverage(tmp_path, capsys):
    """`run --coverage-fail-under` is the `mutate --fail-under` counterpart
    the CLI was missing: a green suite under an unmet coverage floor must
    still exit nonzero, and the floor is judged against the ORIGINAL
    program's coverage (gating on the instrumented number would move the
    threshold whenever mockymock's own injected line count changed)."""
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)

    def fake_compile(
        source_path: Path, coverage: bool = False, trace: bool = False
    ) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")

    def run_with(threshold: str, gcov_side_effect):
        with (
            mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
            mock.patch(
                "mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"
            ),
            mock.patch(
                "mockymock.runtime.docker_toolchain.compile_source",
                side_effect=fake_compile,
            ),
            mock.patch(
                "mockymock.runtime.docker_toolchain.run_binary", return_value=executed
            ),
            mock.patch(
                "mockymock.runtime.docker_toolchain.run_gcov",
                side_effect=gcov_side_effect,
            ) as gcov_mock,
        ):
            code = main(
                [
                    "run",
                    str(program),
                    "--cut",
                    str(cut),
                    "--coverage-fail-under",
                    threshold,
                ]
            )
        return code, gcov_mock

    # Nothing uncovered -> 100%, so a 100 floor passes. The flag implies
    # --coverage on its own (no --coverage passed above).
    exit_code, gcov_mock = run_with("100", _gcov_side_effect())
    assert exit_code == 0
    gcov_mock.assert_called_once()
    assert "is below --coverage-fail-under" not in capsys.readouterr().out

    # Something uncovered -> under 100%, so the same floor now fails even
    # though the suite itself passed.
    exit_code, _ = run_with("100", _gcov_side_effect("PROCESS-ORDER."))
    assert exit_code == 1
    assert "is below --coverage-fail-under 100.0" in capsys.readouterr().out


def test_coverage_fail_under_fails_when_no_coverage_was_measured(tmp_path, capsys):
    """ "No number" must never read as "good enough": a failed gcov pass
    fails the gate rather than silently satisfying it."""
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    gcov_result = GcovResult(
        success=False, gcov_text="", stderr="mockymock: no coverage data produced\n"
    )
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)

    def fake_compile(
        source_path: Path, coverage: bool = False, trace: bool = False
    ) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")

    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=fake_compile,
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_binary", return_value=executed
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_gcov", return_value=gcov_result
        ),
    ):
        exit_code = main(
            ["run", str(program), "--cut", str(cut), "--coverage-fail-under", "50"]
        )
    assert exit_code == 1
    assert "no coverage was measured" in capsys.readouterr().out


def test_run_coverage_reports_missing_data_without_failing_the_run(tmp_path, capsys):
    """gcov failing (e.g. no .gcda because the binary timed out) must not
    change the pass/fail exit code -- coverage is purely additive."""
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    gcov_result = GcovResult(
        success=False, gcov_text="", stderr="mockymock: no coverage data produced\n"
    )
    exit_code, _ = _run_cli_with_coverage(
        tmp_path, executed, lambda *a, **k: gcov_result
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "coverage: mockymock: no coverage data produced" in out


# --- --json-report and --case/--tag selection (Docker toolchain mocked) ------

TWO_CASE_CUT = """\
TESTSUITE "ORDRPROC"

TESTCASE "calls discrate" TAGS "fast"
    MOCK CALL "DISCRATE"
        MOVE 0 TO RETURN-CODE
    END-MOCK
    PERFORM PROCESS-ORDER
    VERIFY "DISCRATE" WAS CALLED ONCE

TESTCASE "second case"
    MOCK CALL "DISCRATE"
    END-MOCK
    PERFORM PROCESS-ORDER
    VERIFY "DISCRATE" WAS CALLED ONCE
"""


def _run_cli_with_cut(tmp_path, cut_text, executed: ExecutionResult, extra_args=()):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(cut_text)

    def fake_compile(
        source_path: Path, coverage: bool = False, trace: bool = False
    ) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")

    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=fake_compile,
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_binary", return_value=executed
        ),
    ):
        return main(["run", str(program), "--cut", str(cut), *extra_args])


def test_run_writes_json_report_with_lines_and_tags(tmp_path):
    import json

    report_path = tmp_path / "report.json"
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    exit_code = _run_cli_with_cut(
        tmp_path,
        TWO_CASE_CUT,
        executed,
        ["--case", "calls discrate", "--json-report", str(report_path)],
    )
    assert exit_code == 0
    payload = json.loads(report_path.read_text())
    assert payload["suite"]["name"] == "ORDRPROC"
    assert [case["name"] for case in payload["cases"]] == ["calls discrate"]
    assert payload["cases"][0]["status"] == "passed"
    assert payload["cases"][0]["line"] == 3
    assert payload["cases"][0]["tags"] == ["fast"]


def test_run_case_selection_unknown_name_fails_before_docker(tmp_path, capsys):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(TWO_CASE_CUT)
    with mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain") as ensure:
        exit_code = main(["run", str(program), "--cut", str(cut), "--case", "nope"])
    assert exit_code == 1
    ensure.assert_not_called()
    out = capsys.readouterr().out
    assert "no TESTCASE named 'nope'" in out
    assert "available:" in out


def test_run_tag_selection_runs_only_tagged_cases(tmp_path):
    import json

    report_path = tmp_path / "report.json"
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    exit_code = _run_cli_with_cut(
        tmp_path,
        TWO_CASE_CUT,
        executed,
        ["--tag", "fast", "--json-report", str(report_path)],
    )
    assert exit_code == 0
    payload = json.loads(report_path.read_text())
    assert [case["name"] for case in payload["cases"]] == ["calls discrate"]


# --- audit F10/F20: --verbose's sandbox cleanup must fire when the
# run_binary/run_gcov phase raises (previously leaked forever, silently --
# nothing prints a path to it), but must NOT fire on a compile failure,
# whose printed "instrumented source at <path>" message is retention by
# design, not a leak -- F10's fix has to preserve that documented,
# integration-tested contract while still closing the real gap ------------


def _sandbox_dirs(tmp_path):
    work = tmp_path / "work"
    if not work.exists():
        return []
    return list(work.glob("mockymock-*"))


def test_verbose_without_keep_sandbox_survives_a_compile_failure(tmp_path):
    """A compile failure prints 'instrumented source at <path>' -- that
    path must still resolve after main() returns, or the message is
    useless. This is deliberate retention, not the F10 leak: contrast
    test_verbose_without_keep_sandbox_cleans_up_after_run_binary_raises
    below, where nothing prints a path and the directory must NOT
    survive. (tests/integration/test_cli.py pins the same contract
    end-to-end against a real compile failure.)"""
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)

    def failing_compile(source_path: Path, coverage: bool = False, trace: bool = False):
        return CompileResult(success=False, binary_path=None, stdout="", stderr="err")

    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=failing_compile,
        ),
    ):
        exit_code = main(["run", str(program), "--cut", str(cut), "--verbose"])
    assert exit_code == 1
    dirs = _sandbox_dirs(tmp_path)
    assert len(dirs) == 1
    assert (dirs[0] / "ORDRPROC.cbl").exists()


def test_verbose_without_keep_sandbox_cleans_up_after_run_binary_raises(tmp_path):
    """An exception mid-run (e.g. run_binary blowing up) must not leak the
    sandbox either -- the cleanup has to run on every exit path, not just
    the ones that fall off the end of the `with` block normally."""
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)

    def fake_compile(source_path: Path, coverage: bool = False, trace: bool = False):
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")

    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=fake_compile,
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_binary",
            side_effect=RuntimeError("container vanished"),
        ),
    ):
        with pytest.raises(RuntimeError, match="container vanished"):
            main(["run", str(program), "--cut", str(cut), "--verbose"])
    assert _sandbox_dirs(tmp_path) == []


def test_keep_sandbox_retains_the_directory_after_a_clean_run(tmp_path):
    """F20: --keep-sandbox's own retention path was never exercised by a
    test -- assert the directory (and the instrumented source inside it)
    really does survive a normal, successful run."""
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    exit_code = _run_cli(tmp_path, executed, ["--keep-sandbox"])
    assert exit_code == 0
    dirs = _sandbox_dirs(tmp_path)
    assert len(dirs) == 1
    assert (dirs[0] / "ORDRPROC.cbl").exists()


# --- report files on refusal/compile failure (carried-over open item,
# 2026-08-10 audit) -----------------------------------------------------
#
# Before this, a refusal or a compile failure returned exit 1 with the
# --junit-xml/--json-report target left untouched -- a CI pipeline that
# always publishes whatever that path holds saw "no test results found"
# instead of a visible failure.


def test_run_writes_junit_xml_and_json_report_on_refusal(tmp_path, capsys):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    # PERFORMs into the CALL but never MOCKs it -> UNMOCKED_CALL refusal,
    # raised before ensure_toolchain is ever reached.
    cut.write_text(
        'TESTSUITE "ORDRPROC"\n\n'
        'TESTCASE "calls discrate"\n'
        "    PERFORM PROCESS-ORDER\n"
    )
    junit_path = tmp_path / "report.xml"
    json_path = tmp_path / "report.json"
    with mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain") as ensure:
        exit_code = main(
            [
                "run",
                str(program),
                "--cut",
                str(cut),
                "--junit-xml",
                str(junit_path),
                "--json-report",
                str(json_path),
            ]
        )
    assert exit_code == 1
    ensure.assert_not_called()
    out = capsys.readouterr().out
    assert "refused" in out

    xml_text = junit_path.read_text()
    assert 'testsuite name="ORDRPROC"' in xml_text
    assert 'failures="1"' in xml_text
    assert "refused" in xml_text

    report = json.loads(json_path.read_text())
    assert report["suite"]["name"] == "ORDRPROC"
    assert report["cases"][0]["status"] == "failed"
    assert "refused" in report["cases"][0]["failures"][0]["message"]


def test_run_writes_junit_xml_and_json_report_on_compile_failure(tmp_path, capsys):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)

    def failing_compile(
        source_path: Path, coverage: bool = False, trace: bool = False
    ) -> CompileResult:
        return CompileResult(
            success=False,
            binary_path=None,
            stdout="",
            stderr="cobc: error: syntax error, unexpected DISCRATE\n",
        )

    junit_path = tmp_path / "report.xml"
    json_path = tmp_path / "report.json"
    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=failing_compile,
        ),
    ):
        exit_code = main(
            [
                "run",
                str(program),
                "--cut",
                str(cut),
                "--junit-xml",
                str(junit_path),
                "--json-report",
                str(json_path),
            ]
        )
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "compile failed" in out

    xml_text = junit_path.read_text()
    assert 'testsuite name="ORDRPROC"' in xml_text
    assert "syntax error" in xml_text

    report = json.loads(json_path.read_text())
    assert report["suite"]["name"] == "ORDRPROC"
    assert "syntax error" in report["cases"][0]["failures"][0]["message"]


def test_run_without_report_flags_does_not_touch_the_filesystem_on_refusal(
    tmp_path, capsys
):
    """No --junit-xml/--json-report given -> nothing new is written; the
    helper must not assume either flag is set."""
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text('TESTSUITE "ORDRPROC"\n\nTESTCASE "calls discrate"\n')
    before = set(tmp_path.iterdir())
    exit_code = main(["run", str(program), "--cut", str(cut)])
    assert exit_code == 1
    assert set(tmp_path.iterdir()) == before


# --- run --timeout (mirrors mutate's own flag; F18-adjacent carried-over
# open item, 2026-08-10 audit: `run` had no way to shorten or lengthen the
# 30s default a hung mocked CALL is bound by) ----------------------------


def test_run_timeout_defaults_to_30_seconds():
    from mockymock.cli.main import build_parser

    args = build_parser().parse_args(["run", "P.cbl", "--cut", "P.cut"])
    assert args.timeout == 30


def test_run_passes_timeout_flag_through_to_run_binary(tmp_path):
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)

    def fake_compile(
        source_path: Path, coverage: bool = False, trace: bool = False
    ) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")

    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=fake_compile,
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_binary", return_value=executed
        ) as run_binary,
    ):
        exit_code = main(["run", str(program), "--cut", str(cut), "--timeout", "5"])
    assert exit_code == 0
    assert run_binary.call_args.kwargs["timeout_seconds"] == 5


def test_run_explains_an_all_pass_run_that_never_printed_summary(tmp_path, capsys):
    """Issue #264: every case printed a clean END but the binary stopped
    before its SUMMARY line; the run exits 1 and must say why."""
    executed = ExecutionResult(
        exit_code=0,
        stdout=CLEAN_STDOUT.rsplit("__MOCKYMOCK__ SUMMARY", 1)[0],
        stderr="",
    )
    assert _run_cli(tmp_path, executed) == 1
    out = capsys.readouterr().out
    assert "[PASS] calls discrate" in out
    assert "without printing its SUMMARY line" in out


def test_run_with_summary_does_not_explain_a_missing_summary(tmp_path, capsys):
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    assert _run_cli(tmp_path, executed) == 0
    assert "SUMMARY line" not in capsys.readouterr().out
