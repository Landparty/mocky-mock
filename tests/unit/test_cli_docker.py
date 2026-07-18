"""CLI behavior around the Docker toolchain, with the toolchain mocked --
these tests must pass without Docker installed."""

from unittest import mock

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


def test_run_fails_loudly_before_parsing_when_docker_unavailable(tmp_path, capsys):
    """ensure_toolchain runs before any parse work or sandbox creation:
    just the actionable message. Only the cheap input-existence check
    precedes it, so the input files must exist here."""
    program = tmp_path / "PROG.cbl"
    program.write_text("dummy\n")
    cut = tmp_path / "PROG.cut"
    cut.write_text('TESTSUITE "x"\n')
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

from pathlib import Path

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

    def fake_compile(source_path: Path, coverage: bool = False) -> CompileResult:
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

    def fake_compile(source_path: Path, coverage: bool = False) -> CompileResult:
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

COVERAGE_GCOV_TEXT = (
    "        -:    0:Source:ORDRPROC.cbl\n"
    "       1*:    1:PROCESS-ORDER.\n"
    '       1*:    2:    CALL "DISCRATE" USING WS-AMOUNT.\n'
    "    #####:    3:    DISPLAY 'UNREACHED'.\n"
)


def _run_cli_with_coverage(
    tmp_path, executed: ExecutionResult, gcov_result: GcovResult
):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)

    def fake_compile(source_path: Path, coverage: bool = False) -> CompileResult:
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
        ) as gcov_mock,
    ):
        exit_code = main(["run", str(program), "--cut", str(cut), "--coverage"])
    return exit_code, gcov_mock


def test_run_coverage_prints_summary_and_uncovered_lines(tmp_path, capsys):
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    gcov_result = GcovResult(success=True, gcov_text=COVERAGE_GCOV_TEXT, stderr="")
    exit_code, gcov_mock = _run_cli_with_coverage(tmp_path, executed, gcov_result)
    assert exit_code == 0
    gcov_mock.assert_called_once()
    out = capsys.readouterr().out
    assert "coverage: 66.67% lines executed (2/3)" in out
    assert "3:     DISPLAY 'UNREACHED'." in out


def test_run_coverage_without_flag_never_calls_gcov(tmp_path, capsys):
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)

    def fake_compile(source_path: Path, coverage: bool = False) -> CompileResult:
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
    gcov_result = GcovResult(success=True, gcov_text=COVERAGE_GCOV_TEXT, stderr="")
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)
    out_path = tmp_path / "coverage.txt"

    def fake_compile(source_path: Path, coverage: bool = False) -> CompileResult:
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
    assert "66.67% lines executed (2/3)" in out_path.read_text()


def test_run_coverage_reports_missing_data_without_failing_the_run(tmp_path, capsys):
    """gcov failing (e.g. no .gcda because the binary timed out) must not
    change the pass/fail exit code -- coverage is purely additive."""
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    gcov_result = GcovResult(
        success=False, gcov_text="", stderr="mockymock: no coverage data produced\n"
    )
    exit_code, _ = _run_cli_with_coverage(tmp_path, executed, gcov_result)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "coverage: mockymock: no coverage data produced" in out
