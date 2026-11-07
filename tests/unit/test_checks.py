"""Unit tests for the shared static-check pipeline (`mockymock.cli.checks`)
extracted per docs/2026-07-18-cut-lint-command-design.md."""

from pathlib import Path

from mockymock.cli.checks import (
    extra_working_storage,
    filter_suite_cases,
    run_static_checks,
)
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.linkage import DISCARD_POINTER
from mockymock.splicer.reset import reset_move_lines

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


def test_circular_copybook_reports_a_problem_instead_of_raising(tmp_path):
    """Audit finding F6: expand_copybooks() genuinely raises for realistic
    inputs (a copybook that COPYs itself, an oversized/deeply-nested
    chain, a mis-encoded file) -- CircularReferenceError,
    NestingDepthError, TotalExpansionSizeExceededError, EncodingError.
    Unguarded here, any of those propagated as a raw Python traceback on
    six subcommands (run/lint/debug/export/mutate share this pipeline,
    generate has its own copy of the same call)."""
    (tmp_path / "SELFREF.cpy").write_text("           COPY SELFREF.\n")
    program = tmp_path / "P.cbl"
    program.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       COPY SELFREF.\n"
    )
    cut = tmp_path / "P.cut"
    cut.write_text('TESTSUITE "s"\n')

    result = run_static_checks(program, cut, [str(tmp_path)])

    assert not result.ok
    assert any("Circular copybook dependency" in p for p in result.problems)


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
        'TESTSUITE "s"\nTESTCASE "a" TAGS "slow"\nPERFORM P\nTESTCASE "b"\nPERFORM P\n'
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


def test_preserve_compiler_directives_keeps_them_in_lines(tmp_path):
    """export needs the real PROCESS/CBL directives kept intact (GnuCOBOL
    can't compile them, but a real IBM compiler expects them) -- opt-in
    via preserve_compiler_directives, default False leaves run/lint
    unaffected (see test_precompiler_directives_stripped_before_lines_
    reach_the_compiler above)."""
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

    stripped = run_static_checks(cbl, cut, None)
    assert stripped.ok
    assert "PROCESS" not in stripped.lines[0]

    preserved = run_static_checks(cbl, cut, None, preserve_compiler_directives=True)
    assert preserved.ok
    assert preserved.lines[0] == "PROCESS APOST,TRUNC(OPT)"
    assert preserved.lines[1] == "CBL ARITH(EXTEND)"
    # Line count (and every later AST-derived line number) must match
    # the stripped variant exactly -- same invariant, opposite content.
    assert len(preserved.lines) == len(stripped.lines)
    assert preserved.lines[2] == stripped.lines[2] == "IDENTIFICATION DIVISION."


# The two compile-blocking shapes the 2026-08-28 fixes address, together in
# one program, laid out the way the real-world corpus has them: a DFHAID-style
# VALUE-less group whose children carry their own VALUE clauses (one of them a
# lone double quote), a CICS `DFHCOMMAREA` LINKAGE SECTION, an undeclared EIB
# reference, and a DL/I `7000-SCHEDULE-PSB` paragraph rebinding every PCB/DIB
# mask. Before the fixes GnuCOBOL rejected this with `invalid symbol '%'` in
# UT-RESET-WORKING-STORAGE plus one `cannot change address of 'X', which is
# not BASED or a LINKAGE item` per SET; after them it compiles and runs clean
# (verified against real GnuCOBOL 4.0).
CORPUS_SHAPED_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HY0900IC.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DFHAID.
           02  DFHMSRE   PIC X VALUE IS 'x'.
           02  DFHTRIG   PIC X VALUE IS '"'.
           02  DFHPA1    PIC X VALUE IS '%'.
       01  CST-NON       PIC X VALUE 'N'.

       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  COM-ZONE            PIC X(10).
       01  LK-UIB.
           05  LK-UIB-DIB-LIST-PTR USAGE POINTER.
       01  LK-DIB-LIST.
           05  LK-DIB-PTR-HY7000-01 USAGE POINTER.
       01  HY7000-DIB.
           05  HY7000-STATUS       PIC X(2).

       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 7000-SCHEDULE-PSB
           DISPLAY 'EIBCALEN=' EIBCALEN
           DISPLAY 'TRIG=' DFHTRIG
           STOP RUN.

       7000-SCHEDULE-PSB.
           CALL 'CBLTDLI' USING CST-NON LK-UIB
           SET ADDRESS OF LK-DIB-LIST   TO LK-UIB-DIB-LIST-PTR.
           SET ADDRESS OF HY7000-DIB    TO LK-DIB-PTR-HY7000-01.
"""

CORPUS_SHAPED_CUT = """\
TESTSUITE "HY0900IC schedule"

TESTCASE "psb scheduling"
    MOCK CALL "CBLTDLI"
        MOVE "OK" TO HY7000-STATUS
    END-MOCK
    PERFORM 0000-MAIN
    EXPECT HY7000-STATUS TO BE "OK"
"""


def _corpus_checked(tmp_path):
    program = tmp_path / "HY0900IC.cbl"
    program.write_text(CORPUS_SHAPED_PROGRAM)
    cut = tmp_path / "HY0900IC.cut"
    cut.write_text(CORPUS_SHAPED_CUT)
    return run_static_checks(program, cut, None)


def test_corpus_shaped_dli_program_passes_the_static_checks(tmp_path):
    checked = _corpus_checked(tmp_path)
    assert checked.problems == []
    assert checked.ok
    assert checked.linkage is not None


def test_corpus_shaped_program_rewrites_every_receiving_set_address_of(tmp_path):
    checked = _corpus_checked(tmp_path)
    assert checked.lines is not None
    body = "\n".join(checked.lines)
    # Every rebind of a folded item is gone -- each one was a hard cobc error.
    assert "ADDRESS OF LK-DIB-LIST" not in body
    assert "ADDRESS OF HY7000-DIB" not in body
    assert body.count("SET " + DISCARD_POINTER) == 2
    assert [site.item_name for site in checked.linkage_address_of] == [
        "LK-DIB-LIST",
        "HY7000-DIB",
    ]
    # The pointer operands, and the statements' own periods, survive untouched.
    assert "TO LK-UIB-DIB-LIST-PTR." in body
    assert "TO LK-DIB-PTR-HY7000-01." in body


def test_corpus_shaped_program_declares_the_sink_alongside_the_eib_block(tmp_path):
    """Both extra-WORKING-STORAGE sources reach `build_driver` through the one
    merged helper, so a program needing both gets both."""
    checked = _corpus_checked(tmp_path)
    declared = extra_working_storage(checked)
    assert declared is not None
    assert any(DISCARD_POINTER in line for line in declared)
    assert any("DFHEIBLK" in line for line in declared)


def test_corpus_shaped_program_resets_the_quote_literal_validly(tmp_path):
    checked = _corpus_checked(tmp_path)
    assert checked.parse_result is not None
    reset = reset_move_lines(checked.parse_result.ast)
    # Four quote characters, not three: the three-quote form is an
    # unterminated literal that desynchronizes cobc for the rest of the file,
    # reported lines later as `invalid symbol '%'` against the NEXT reset line.
    assert 'MOVE """" TO DFHTRIG OF DFHAID' in reset
    assert 'MOVE "%" TO DFHPA1 OF DFHAID' in reset


FREE_FORMAT_PROGRAM = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. FN.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-X PIC 9(3) VALUE 0.
PROCEDURE DIVISION.
MAIN-PARA.
    PERFORM ADD-PARA
    GOBACK.
ADD-PARA.
    ADD 5 TO WS-X
    ADD 1 TO WS-X.
"""


def test_free_format_program_is_refused_not_column_chopped(tmp_path):
    # Issue #210: the splicer's text is cut to columns 8-72, so a
    # free-format program linted clean and then failed in cobc on garbage.
    program = tmp_path / "FN.cbl"
    program.write_text(FREE_FORMAT_PROGRAM)
    cut = tmp_path / "FN.cut"
    cut.write_text('TESTSUITE "s"\nTESTCASE "add"\n    PERFORM ADD-PARA\n')
    result = run_static_checks(program, cut, None)
    assert not result.ok
    assert result.problems[0].startswith("refused (UNSUPPORTED_SOURCE_FORMAT)")


def test_fixed_format_program_is_not_refused_as_free_format():
    result = run_static_checks(ORDRPROC_CBL, ORDRPROC_CUT, None)
    assert not any("UNSUPPORTED_SOURCE_FORMAT" in p for p in result.problems)
