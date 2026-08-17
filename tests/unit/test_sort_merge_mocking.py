"""Unit tests for plain-file-form SORT/MERGE mocking (`SORT ... USING ...
GIVING ...` / `MERGE ... USING ... GIVING ...`, no INPUT/OUTPUT PROCEDURE):
classification (mock_surface.py), grammar (dsl/parser.py), refusal-gate
behavior (analysis/refusal.py), scaffolding (dsl/generator.py), and splicing
(splicer/orchestrator.py + injector.py). The INPUT/OUTPUT PROCEDURE form
(and RELEASE/RETURN, which only ever appear inside one) must stay
unmockable exactly as before -- see test_mock_surface.py/test_refusal.py
for that pre-existing coverage; this file only adds the newly-mockable
plain-file-form path plus regression coverage that the procedure form
didn't regress.
"""

import pytest
from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze, analyze_file_status_fields
from mockymock.analysis.refusal import check_test_case, directive_matches_site
from mockymock.dsl.generator import scaffold_cut
from mockymock.dsl.model import MockCategory, MockDirective, MockTestCase
from mockymock.dsl.parser import CutParseError, parse_cut
from mockymock.splicer import orchestrator, source_map
from mockymock.splicer.naming import TallyRegistry

PLAIN_SORT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTTEST.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "INFILE"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT OUT-FILE ASSIGN TO "OUTFILE"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       SD  SORT-FILE.
       01  SORT-REC.
           05  SORT-KEY       PIC X(10).
       FD  IN-FILE.
       01  IN-REC.
           05  IN-KEY         PIC X(10).
       FD  OUT-FILE.
       01  OUT-REC.
           05  OUT-KEY        PIC X(10).

       WORKING-STORAGE SECTION.

       PROCEDURE DIVISION.
       MAIN-PARA.
           SORT SORT-FILE ON ASCENDING KEY SORT-KEY
               USING IN-FILE
               GIVING OUT-FILE.
           STOP RUN.
"""

PLAIN_MERGE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MERGETEST.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE-1 ASSIGN TO "INFILE1"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT IN-FILE-2 ASSIGN TO "INFILE2"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT OUT-FILE ASSIGN TO "OUTFILE"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       SD  MERGE-FILE.
       01  MERGE-REC.
           05  MERGE-KEY      PIC X(10).
       FD  IN-FILE-1.
       01  IN-REC-1.
           05  IN-KEY-1       PIC X(10).
       FD  IN-FILE-2.
       01  IN-REC-2.
           05  IN-KEY-2       PIC X(10).
       FD  OUT-FILE.
       01  OUT-REC.
           05  OUT-KEY        PIC X(10).

       WORKING-STORAGE SECTION.

       PROCEDURE DIVISION.
       MAIN-PARA.
           MERGE MERGE-FILE ON ASCENDING KEY MERGE-KEY
               USING IN-FILE-1 IN-FILE-2
               GIVING OUT-FILE.
           STOP RUN.
"""

# INPUT PROCEDURE + OUTPUT PROCEDURE form, with RELEASE/RETURN -- must stay
# unmockable exactly as before this feature.
PROCEDURE_SORT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTPROC.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO "OUTFILE"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       SD  SORT-FILE.
       01  SORT-REC.
           05  SORT-KEY       PIC X(10).
       FD  OUT-FILE.
       01  OUT-REC.
           05  OUT-KEY        PIC X(10).

       WORKING-STORAGE SECTION.

       PROCEDURE DIVISION.
       MAIN-PARA.
           SORT SORT-FILE ON ASCENDING KEY SORT-KEY
               INPUT PROCEDURE IS FEED-PARA
               OUTPUT PROCEDURE IS EMIT-PARA.
           STOP RUN.
       FEED-PARA.
           RELEASE SORT-REC.
       EMIT-PARA.
           RETURN SORT-FILE AT END CONTINUE.
"""

# USING file(s) + OUTPUT PROCEDURE (mixed form) -- still unmockable: only
# the fully-plain USING ... GIVING ... shape is supported.
MIXED_SORT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTMIXED.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "INFILE"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       SD  SORT-FILE.
       01  SORT-REC.
           05  SORT-KEY       PIC X(10).
       FD  IN-FILE.
       01  IN-REC.
           05  IN-KEY         PIC X(10).

       WORKING-STORAGE SECTION.

       PROCEDURE DIVISION.
       MAIN-PARA.
           SORT SORT-FILE ON ASCENDING KEY SORT-KEY
               USING IN-FILE
               OUTPUT PROCEDURE IS EMIT-PARA.
           STOP RUN.
       EMIT-PARA.
           RETURN SORT-FILE AT END CONTINUE.
"""


def _parse(source, filename):
    result = parse_cobol(source, filename=filename)
    assert result.success, result.errors
    return result


def _case(perform_target, mocks=()):
    return MockTestCase(name="case", mocks=list(mocks), perform_target=perform_target)


# --- mock_surface.py classification ----------------------------------------


def test_plain_sort_is_mockable_keyed_by_sd_name():
    result = _parse(PLAIN_SORT_SOURCE, "sorttest.cbl")
    surface = analyze(result.ast)
    sort_sites = [s for s in surface.boundary_sites if s.label == "SORT"]
    assert len(sort_sites) == 1
    site = sort_sites[0]
    assert site.category is MockCategory.SORT
    assert site.keys == ("SORT-FILE",)
    assert not site.nested


def test_plain_sort_marks_paragraph_as_file_io():
    result = _parse(PLAIN_SORT_SOURCE, "sorttest.cbl")
    surface = analyze(result.ast)
    assert "MAIN-PARA" in surface.file_io_paragraphs


def test_plain_merge_is_mockable_keyed_by_sd_name():
    result = _parse(PLAIN_MERGE_SOURCE, "mergetest.cbl")
    surface = analyze(result.ast)
    merge_sites = [s for s in surface.boundary_sites if s.label == "MERGE"]
    assert len(merge_sites) == 1
    site = merge_sites[0]
    assert site.category is MockCategory.MERGE
    assert site.keys == ("MERGE-FILE",)


def test_procedure_form_sort_stays_unmockable():
    result = _parse(PROCEDURE_SORT_SOURCE, "sortproc.cbl")
    surface = analyze(result.ast)
    sort_merge_sites = [s for s in surface.boundary_sites if s.label == "SORT/MERGE"]
    # SORT itself, plus RELEASE and RETURN -- all three category=None.
    assert len(sort_merge_sites) == 3
    assert all(s.category is None for s in sort_merge_sites)
    assert not any(
        s.category in (MockCategory.SORT, MockCategory.MERGE)
        for s in surface.boundary_sites
    )


def test_mixed_using_and_output_procedure_stays_unmockable():
    result = _parse(MIXED_SORT_SOURCE, "sortmixed.cbl")
    surface = analyze(result.ast)
    sort_site = next(
        s for s in surface.boundary_sites if s.statement.statement_type == "SORT"
    )
    assert sort_site.category is None
    assert sort_site.label == "SORT/MERGE"


# --- dsl/parser.py grammar --------------------------------------------------


def test_mock_sort_parses_bare_key():
    suite = parse_cut(
        'TESTSUITE "S"\n'
        'TESTCASE "tc"\n'
        "    MOCK SORT SORT-FILE\n"
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
    )
    directive = suite.test_cases[0].mocks[0]
    assert directive.category is MockCategory.SORT
    assert directive.key == "SORT-FILE"


def test_mock_merge_parses_bare_key():
    suite = parse_cut(
        'TESTSUITE "S"\n'
        'TESTCASE "tc"\n'
        "    MOCK MERGE MERGE-FILE\n"
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
    )
    directive = suite.test_cases[0].mocks[0]
    assert directive.category is MockCategory.MERGE
    assert directive.key == "MERGE-FILE"


def test_mock_sort_rejects_rows_sugar():
    with pytest.raises(CutParseError, match="ROWS is only supported"):
        parse_cut(
            'TESTSUITE "S"\n'
            'TESTCASE "tc"\n'
            "    MOCK SORT SORT-FILE ROWS\n"
            '    (SORT-KEY = "A")\n'
            "    END-MOCK\n"
            "    PERFORM MAIN-PARA\n"
        )


def test_verify_sort_parses():
    suite = parse_cut(
        'TESTSUITE "S"\n'
        'TESTCASE "tc"\n'
        "    MOCK SORT SORT-FILE\n"
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
        "    VERIFY SORT SORT-FILE WAS CALLED ONCE\n"
    )
    verification = suite.test_cases[0].verifications[0]
    assert verification.category is MockCategory.SORT
    assert verification.key == "SORT-FILE"


def test_directive_describe_uses_bare_word_form():
    directive = MockDirective(MockCategory.SORT, "SORT-FILE")
    assert directive.describe() == "SORT SORT-FILE"


# --- refusal.py --------------------------------------------------------


def test_unmocked_plain_sort_refuses_unmocked_file_op():
    result = _parse(PLAIN_SORT_SOURCE, "sorttest.cbl")
    surface = analyze(result.ast)
    file_status = analyze_file_status_fields(result.ast)
    reasons = check_test_case(surface, result.ast, _case("MAIN-PARA"), file_status)
    assert any(r.code == "UNMOCKED_FILE_OP" for r in reasons)


def test_mocked_plain_sort_is_not_refused():
    result = _parse(PLAIN_SORT_SOURCE, "sorttest.cbl")
    surface = analyze(result.ast)
    file_status = analyze_file_status_fields(result.ast)
    case = _case("MAIN-PARA", mocks=[MockDirective(MockCategory.SORT, "SORT-FILE")])
    reasons = check_test_case(surface, result.ast, case, file_status)
    assert reasons == []


def test_ambiguous_mock_sort_refuses():
    result = _parse(PLAIN_SORT_SOURCE, "sorttest.cbl")
    surface = analyze(result.ast)
    file_status = analyze_file_status_fields(result.ast)
    case = _case(
        "MAIN-PARA",
        mocks=[
            MockDirective(MockCategory.SORT, "SORT-FILE"),
            MockDirective(MockCategory.SORT, "SORT-FILE", body_lines=["CONTINUE"]),
        ],
    )
    reasons = check_test_case(surface, result.ast, case, file_status)
    assert any(r.code == "AMBIGUOUS_MOCK" for r in reasons)


def test_mock_merge_never_matches_a_sort_site():
    result = _parse(PLAIN_SORT_SOURCE, "sorttest.cbl")
    surface = analyze(result.ast)
    sort_site = next(s for s in surface.boundary_sites if s.label == "SORT")
    directive = MockDirective(MockCategory.MERGE, "SORT-FILE")
    assert not directive_matches_site(directive, sort_site)


def test_procedure_form_sort_still_refuses_unsupported_sort_merge():
    result = _parse(PROCEDURE_SORT_SOURCE, "sortproc.cbl")
    surface = analyze(result.ast)
    file_status = analyze_file_status_fields(result.ast)
    reasons = check_test_case(surface, result.ast, _case("MAIN-PARA"), file_status)
    codes = {r.code for r in reasons}
    assert "UNSUPPORTED_SORT_MERGE" in codes
    # RELEASE (in FEED-PARA) and RETURN (in EMIT-PARA) aren't reachable
    # from MAIN-PARA by PERFORM/GO TO in this source, so only the SORT
    # statement itself is refused here.


def test_mixed_form_still_refuses_unsupported_sort_merge():
    result = _parse(MIXED_SORT_SOURCE, "sortmixed.cbl")
    surface = analyze(result.ast)
    file_status = analyze_file_status_fields(result.ast)
    reasons = check_test_case(surface, result.ast, _case("MAIN-PARA"), file_status)
    assert any(r.code == "UNSUPPORTED_SORT_MERGE" for r in reasons)


def test_mock_sort_against_procedure_form_site_is_unmatched():
    result = _parse(PROCEDURE_SORT_SOURCE, "sortproc.cbl")
    surface = analyze(result.ast)
    file_status = analyze_file_status_fields(result.ast)
    case = _case("MAIN-PARA", mocks=[MockDirective(MockCategory.SORT, "SORT-FILE")])
    reasons = check_test_case(surface, result.ast, case, file_status)
    codes = {r.code for r in reasons}
    assert "UNSUPPORTED_SORT_MERGE" in codes
    assert "UNMATCHED_MOCK" in codes


# --- dsl/generator.py scaffold ----------------------------------------------


def test_scaffold_generates_bare_mock_sort_stub():
    result = _parse(PLAIN_SORT_SOURCE, "sorttest.cbl")
    surface = analyze(result.ast)
    cut_text = scaffold_cut("SORTTEST", surface)
    assert "MOCK SORT SORT-FILE" in cut_text
    assert "END-MOCK" in cut_text


def test_scaffold_generates_bare_mock_merge_stub():
    result = _parse(PLAIN_MERGE_SOURCE, "mergetest.cbl")
    surface = analyze(result.ast)
    cut_text = scaffold_cut("MERGETEST", surface)
    assert "MOCK MERGE MERGE-FILE" in cut_text


def test_scaffold_omits_procedure_form_sort():
    result = _parse(PROCEDURE_SORT_SOURCE, "sortproc.cbl")
    surface = analyze(result.ast)
    cut_text = scaffold_cut("SORTPROC", surface)
    assert "MOCK SORT" not in cut_text
    assert "MOCK MERGE" not in cut_text


# --- splicer: orchestrator.py + injector.py --------------------------------


def test_splice_program_replaces_plain_sort_with_dispatch():
    result = _parse(PLAIN_SORT_SOURCE, "sorttest.cbl")
    surface = analyze(result.ast)
    lines = PLAIN_SORT_SOURCE.split("\n")
    cut_text = (
        'TESTSUITE "S"\n'
        'TESTCASE "tc"\n'
        "    MOCK SORT SORT-FILE\n"
        '        DISPLAY "sorted"\n'
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
    )
    suite = parse_cut(cut_text)
    scope_map = source_map.collect_scope_map(result.ast, lines)
    source_map.annotate_nested_sites(surface, scope_map, lines)
    boundaries = source_map.collect_boundaries(result.ast)
    registry = TallyRegistry(suite)
    spliced = orchestrator.splice_program(lines, boundaries, surface, suite, registry)
    spliced_text = "\n".join(spliced)
    sort_line = next(
        line for line in spliced if "SORT SORT-FILE ON ASCENDING KEY" in line
    )
    assert sort_line.lstrip().startswith("*>")  # original statement commented out
    assert "EVALUATE UT-CURRENT-CASE" in spliced_text
    assert 'DISPLAY "sorted"' in spliced_text
    assert "UT-SORT-SORT-FILE-TALLY" in spliced_text


def test_splice_program_leaves_unmocked_reachable_sort_untouched_when_not_matched():
    # An unmocked plain SORT is left as plain COBOL by the splicer itself
    # (splice_program has no reachability awareness) -- it's the refusal
    # gate's job to have refused this case before splicing is ever
    # reached; this test only pins splice_program's own behavior.
    result = _parse(PLAIN_SORT_SOURCE, "sorttest.cbl")
    surface = analyze(result.ast)
    lines = PLAIN_SORT_SOURCE.split("\n")
    suite = parse_cut('TESTSUITE "S"\nTESTCASE "tc"\n    PERFORM MAIN-PARA\n')
    scope_map = source_map.collect_scope_map(result.ast, lines)
    source_map.annotate_nested_sites(surface, scope_map, lines)
    boundaries = source_map.collect_boundaries(result.ast)
    registry = TallyRegistry(suite)
    spliced = orchestrator.splice_program(lines, boundaries, surface, suite, registry)
    spliced_text = "\n".join(spliced)
    assert "SORT SORT-FILE ON ASCENDING KEY" in spliced_text
