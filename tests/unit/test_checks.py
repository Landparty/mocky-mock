"""Unit tests for the shared static-check pipeline (`mockymock.cli.checks`)
extracted per docs/2026-07-18-cut-lint-command-design.md."""

from pathlib import Path

from mockymock.cli.checks import filter_suite_cases, run_static_checks
from mockymock.dsl.parser import parse_cut

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
ORDRPROC_CBL = EXAMPLES / "ordrproc" / "ORDRPROC.cbl"
ORDRPROC_CUT = EXAMPLES / "ordrproc" / "ORDRPROC.cut"


def test_clean_example_passes_and_populates_artifacts():
    result = run_static_checks(ORDRPROC_CBL, ORDRPROC_CUT, None)
    assert result.ok
    assert result.problems == []
    assert result.parse_result is not None and result.parse_result.success
    assert result.surface is not None
    assert result.suite is not None and result.suite.test_cases
    assert result.lines
    assert result.scope_map is not None


def test_parse_error_program_short_circuits_with_detail_lines(tmp_path):
    bad = tmp_path / "BAD.cbl"
    bad.write_text("this is not cobol\n")
    cut = tmp_path / "BAD.cut"
    cut.write_text('TESTSUITE "s"\n')
    result = run_static_checks(bad, cut, None)
    assert not result.ok
    assert any(p.startswith("refused (") for p in result.problems)
    # The .cut is never parsed once the program refuses.
    assert result.suite is None


def test_invalid_cut_file_reports_parse_error(tmp_path):
    cut = tmp_path / "X.cut"
    cut.write_text("NOT A DIRECTIVE\n")
    result = run_static_checks(ORDRPROC_CBL, cut, None)
    assert not result.ok
    assert any("invalid .cut file" in p for p in result.problems)


def test_case_selection_filters_suite(tmp_path):
    suite_before = parse_cut(ORDRPROC_CUT.read_text())
    keep = suite_before.test_cases[0].name
    result = run_static_checks(ORDRPROC_CBL, ORDRPROC_CUT, None, case_names=[keep])
    assert result.ok
    assert [case.name for case in result.suite.test_cases] == [keep]


def test_unknown_case_name_is_a_problem_listing_available_cases():
    result = run_static_checks(
        ORDRPROC_CBL, ORDRPROC_CUT, None, case_names=["no such case"]
    )
    assert not result.ok
    assert any("no TESTCASE named 'no such case'" in p for p in result.problems)
    assert any("available:" in p for p in result.problems)


def test_unknown_tag_is_a_problem():
    result = run_static_checks(ORDRPROC_CBL, ORDRPROC_CUT, None, tag_names=["slow"])
    assert not result.ok
    assert any("no TESTCASE carries tag 'slow'" in p for p in result.problems)


def test_filter_by_tag_keeps_only_tagged_cases():
    suite = parse_cut(
        'TESTSUITE "s"\n'
        'TESTCASE "a" TAGS "slow"\nPERFORM P\n'
        'TESTCASE "b"\nPERFORM P\n'
    )
    problems = filter_suite_cases(suite, None, ["slow"])
    assert problems == []
    assert [case.name for case in suite.test_cases] == ["a"]


def test_filter_case_and_tag_union():
    suite = parse_cut(
        'TESTSUITE "s"\n'
        'TESTCASE "a" TAGS "slow"\nPERFORM P\n'
        'TESTCASE "b"\nPERFORM P\n'
        'TESTCASE "c"\nPERFORM P\n'
    )
    problems = filter_suite_cases(suite, ["b"], ["slow"])
    assert problems == []
    assert [case.name for case in suite.test_cases] == ["a", "b"]


def test_no_filter_keeps_everything():
    suite = parse_cut('TESTSUITE "s"\nTESTCASE "a"\nPERFORM P\n')
    assert filter_suite_cases(suite, None, None) == []
    assert len(suite.test_cases) == 1


def test_checks_module_never_imports_docker_toolchain():
    """The structural guarantee from the design doc: linting must work with
    no Docker daemon, so the checks module must not even import the
    toolchain module."""
    import sys

    saved = sys.modules.pop("mockymock.runtime.docker_toolchain", None)
    try:
        run_static_checks(ORDRPROC_CBL, ORDRPROC_CUT, None)
        assert "mockymock.runtime.docker_toolchain" not in sys.modules
    finally:
        if saved is not None:
            sys.modules["mockymock.runtime.docker_toolchain"] = saved


def test_file_status_fields_populated_on_clean_run():
    result = run_static_checks(ORDRPROC_CBL, ORDRPROC_CUT, None)
    assert result.ok
    assert result.file_status_fields is not None


def test_precompiler_directives_stripped_before_lines_reach_the_compiler(tmp_path):
    """PROCESS/CBL compiler-directing statements (common on IBM mainframe
    source, always preceding IDENTIFICATION DIVISION) parse fine as far as
    cobolparser's AST is concerned -- CobolParser.parse() blanks them out
    internally -- but `result.lines` is what the splicer edits and what
    `mockymock run` eventually writes as the instrumented source for
    GnuCOBOL to compile. Left un-stripped here, they would survive into that
    file verbatim and cobc can reject options/syntax it doesn't recognize."""
    cbl = tmp_path / "PRECHK.cbl"
    cbl.write_text("""\
       PROCESS APOST,TRUNC(OPT)
       CBL ARITH(EXTEND)
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRECHK.
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           DISPLAY "HELLO".
""")
    cut = tmp_path / "PRECHK.cut"
    cut.write_text('TESTSUITE "s"\nTESTCASE "c"\n    PERFORM MAIN-PROCESS\n')
    result = run_static_checks(cbl, cut, None)
    assert result.ok
    assert result.lines is not None
    assert "PROCESS" not in result.lines[0]
    assert "CBL" not in result.lines[1]
    # Blanking, not deleting: line count (and every later line number the
    # splicer relies on) must stay unchanged.
    assert result.lines[2] == "IDENTIFICATION DIVISION."


def test_unresolved_file_status_target_surfaces_as_a_problem(tmp_path):
    cbl = tmp_path / "NOSTAT.cbl"
    cbl.write_text("""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOSTAT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT NO-STATUS ASSIGN TO "A.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  NO-STATUS.
       01  NO-STATUS-REC      PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT NO-STATUS.
""")
    cut = tmp_path / "NOSTAT.cut"
    cut.write_text("""\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN NO-STATUS
        FILE-STATUS IS SUCCESS
    END-MOCK
    PERFORM MAIN-PROCESS
""")
    result = run_static_checks(cbl, cut, None)
    assert not result.ok
    assert any("UNRESOLVED_FILE_STATUS_TARGET" in p for p in result.problems)
