"""Unit tests for SORT/MERGE mocking across all three grammar shapes:

1. Plain file form (`SORT/MERGE ... USING ... GIVING ...`, no procedure
   clause): mockable as a single boundary statement (MockCategory.SORT/
   MERGE).
2. Pure procedure form (SORT only -- `INPUT PROCEDURE ... OUTPUT
   PROCEDURE ...`, no USING/GIVING at all): the SORT statement itself is
   left real/unspliced (not even recorded as a boundary site); its own
   RELEASE/RETURN statements are independently mockable
   (MockCategory.RELEASE/RETURN). The reachability BFS must model the
   SORT's INPUT/OUTPUT PROCEDURE names as an implicit PERFORM edge or
   these sites are invisible to the fail-closed gate -- see
   `test_pure_procedure_reachability_edge_is_modeled`, the load-bearing
   correctness test in this file.
3. Mixed form (a USING/GIVING file paired with a procedure clause on the
   other side): stays unmockable, category=None, UNSUPPORTED_SORT_MERGE
   -- covers classification (mock_surface.py), grammar (dsl/parser.py),
   reachability (analysis/refusal.py's _reachable_paragraphs), refusal-gate
   behavior (analysis/refusal.py's check_test_case), scaffolding
   (dsl/generator.py), and splicing (splicer/orchestrator.py +
   splicer/injector.py) for all three shapes.
"""

import pytest
from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze, analyze_file_status_fields
from mockymock.analysis.refusal import (
    _reachable_paragraphs,
    check_test_case,
    directive_matches_site,
)
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

# Pure procedure form: INPUT PROCEDURE + OUTPUT PROCEDURE, no USING/GIVING
# at all. Touches no physical file -- the SORT statement itself is left
# real/unspliced (not recorded as a boundary site); RELEASE/RETURN are
# independently mockable. WS-EOF-FLAG exists so a MOCK RETURN ... ROWS
# TERMINAL group has somewhere real to signal exhaustion.
PURE_PROCEDURE_SORT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTPROC.

       DATA DIVISION.
       FILE SECTION.
       SD  SORT-FILE.
       01  SORT-REC.
           05  SORT-KEY       PIC X(10).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG        PIC X VALUE "N".

       PROCEDURE DIVISION.
       MAIN-PARA.
           SORT SORT-FILE ON ASCENDING KEY SORT-KEY
               INPUT PROCEDURE IS FEED-PARA
               OUTPUT PROCEDURE IS EMIT-PARA.
           STOP RUN.
       FEED-PARA.
           RELEASE SORT-REC.
       EMIT-PARA.
           RETURN SORT-FILE AT END MOVE "Y" TO WS-EOF-FLAG.
"""

# Same shape as PURE_PROCEDURE_SORT_SOURCE, but with THRU ranges on both
# procedure clauses -- input_procedure_thru/output_procedure_thru must be
# range-expanded via _expand_thru_range exactly like PERFORM ... THRU, so
# every paragraph in [FEED-A..FEED-B] and [EMIT-A..EMIT-B] is reachable,
# not just the named endpoint.
PURE_PROCEDURE_THRU_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTTHRU.

       DATA DIVISION.
       FILE SECTION.
       SD  SORT-FILE.
       01  SORT-REC.
           05  SORT-KEY       PIC X(10).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG        PIC X VALUE "N".

       PROCEDURE DIVISION.
       MAIN-PARA.
           SORT SORT-FILE ON ASCENDING KEY SORT-KEY
               INPUT PROCEDURE IS FEED-A THRU FEED-B
               OUTPUT PROCEDURE IS EMIT-A THRU EMIT-B.
           STOP RUN.
       FEED-A.
           CONTINUE.
       FEED-B.
           RELEASE SORT-REC.
       EMIT-A.
           CONTINUE.
       EMIT-B.
           RETURN SORT-FILE AT END MOVE "Y" TO WS-EOF-FLAG.
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


def test_pure_procedure_sort_is_not_recorded_as_a_site():
    result = _parse(PURE_PROCEDURE_SORT_SOURCE, "sortproc.cbl")
    surface = analyze(result.ast)
    # The SORT statement itself touches no physical file, so it is left
    # real/unspliced and never recorded as a BoundarySite at all -- not
    # even as an unmockable one (category=None sites are still recorded
    # for other unmockable shapes; this one isn't a boundary at all).
    assert not any(s.statement.statement_type == "SORT" for s in surface.boundary_sites)
    assert not any(s.label == "SORT/MERGE" for s in surface.boundary_sites)


def test_release_and_return_are_independently_mockable():
    result = _parse(PURE_PROCEDURE_SORT_SOURCE, "sortproc.cbl")
    surface = analyze(result.ast)
    release_sites = [s for s in surface.boundary_sites if s.label == "RELEASE"]
    return_sites = [s for s in surface.boundary_sites if s.label == "RETURN"]
    assert len(release_sites) == 1
    assert release_sites[0].category is MockCategory.RELEASE
    assert release_sites[0].keys == ("SORT-REC",)
    assert release_sites[0].paragraph_name == "FEED-PARA"
    assert len(return_sites) == 1
    assert return_sites[0].category is MockCategory.RETURN
    assert return_sites[0].keys == ("SORT-FILE",)
    assert return_sites[0].paragraph_name == "EMIT-PARA"


def test_mixed_using_and_output_procedure_is_mocked_on_its_file_side():
    """Since 2026-11-03 a mixed-form SORT is a SORT site keyed on its SD,
    carrying the procedure the splice PERFORMs after the mock."""
    result = _parse(MIXED_SORT_SOURCE, "sortmixed.cbl")
    surface = analyze(result.ast)
    sort_site = next(
        s for s in surface.boundary_sites if s.statement.statement_type == "SORT"
    )
    assert sort_site.category is MockCategory.SORT
    assert sort_site.keys == ("SORT-FILE",)
    assert sort_site.sort_procedure == ("OUTPUT", "EMIT-PARA", None)


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


def test_mock_release_parses_bare_key():
    suite = parse_cut(
        'TESTSUITE "S"\n'
        'TESTCASE "tc"\n'
        "    MOCK RELEASE SORT-REC\n"
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
    )
    directive = suite.test_cases[0].mocks[0]
    assert directive.category is MockCategory.RELEASE
    assert directive.key == "SORT-REC"


def test_mock_return_parses_bare_key():
    suite = parse_cut(
        'TESTSUITE "S"\n'
        'TESTCASE "tc"\n'
        "    MOCK RETURN SORT-FILE\n"
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
    )
    directive = suite.test_cases[0].mocks[0]
    assert directive.category is MockCategory.RETURN
    assert directive.key == "SORT-FILE"


def test_mock_return_accepts_rows_and_terminal():
    suite = parse_cut(
        'TESTSUITE "S"\n'
        'TESTCASE "tc"\n'
        "    MOCK RETURN SORT-FILE ROWS\n"
        '    (SORT-KEY = "AAA")\n'
        '    (SORT-KEY = "BBB")\n'
        '    TERMINAL (WS-EOF-FLAG = "Y")\n'
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
    )
    directive = suite.test_cases[0].mocks[0]
    assert directive.category is MockCategory.RETURN
    assert directive.rows == [
        [("SORT-KEY", '"AAA"')],
        [("SORT-KEY", '"BBB"')],
    ]
    assert directive.terminal_row == [("WS-EOF-FLAG", '"Y"')]


def test_mock_release_rejects_rows_sugar():
    with pytest.raises(CutParseError, match="ROWS is only supported"):
        parse_cut(
            'TESTSUITE "S"\n'
            'TESTCASE "tc"\n'
            "    MOCK RELEASE SORT-REC ROWS\n"
            '    (SORT-KEY = "A")\n'
            "    END-MOCK\n"
            "    PERFORM MAIN-PARA\n"
        )


def test_terminal_rejects_sql_category():
    # TERMINAL is only parsed inside an open ROWS block, and ROWS itself
    # is only accepted for SQL/READ/RETURN -- so the only reachable
    # negative case for TERMINAL's own category check (now "READ and
    # RETURN", widened from "READ" alone) is a MOCK SQL ... ROWS body.
    with pytest.raises(CutParseError, match="TERMINAL is only supported"):
        parse_cut(
            'TESTSUITE "S"\n'
            'TESTCASE "tc"\n'
            '    MOCK SQL "SELECT" ROWS\n'
            '    (COL = "A")\n'
            "    TERMINAL (X = 1)\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PARA\n"
        )


def test_verify_release_and_return_parse():
    suite = parse_cut(
        'TESTSUITE "S"\n'
        'TESTCASE "tc"\n'
        "    MOCK RELEASE SORT-REC\n"
        "    END-MOCK\n"
        "    MOCK RETURN SORT-FILE\n"
        "    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
        "    VERIFY RELEASE SORT-REC WAS CALLED ONCE\n"
        "    VERIFY RETURN SORT-FILE WAS CALLED AT LEAST ONCE\n"
    )
    verifications = suite.test_cases[0].verifications
    assert verifications[0].category is MockCategory.RELEASE
    assert verifications[1].category is MockCategory.RETURN


# --- refusal.py: reachability BFS -------------------------------------------


def test_pure_procedure_reachability_edge_is_modeled():
    """The load-bearing correctness test in this file: a SORT/MERGE
    statement is not a PerformStatement AST node, so its INPUT PROCEDURE/
    OUTPUT PROCEDURE names are invisible to the reachability BFS unless
    _reachable_paragraphs explicitly models them. Before that edge
    existed, this assertion failed -- the reachable set was only
    {"MAIN-PARA"}, silently excluding FEED-PARA/EMIT-PARA and therefore
    any boundary statement inside them (RELEASE/RETURN included)."""
    result = _parse(PURE_PROCEDURE_SORT_SOURCE, "sortproc.cbl")
    seen, reasons = _reachable_paragraphs(result.ast, "MAIN-PARA")
    assert seen == {"MAIN-PARA", "FEED-PARA", "EMIT-PARA"}
    assert reasons == []


def test_pure_procedure_thru_range_is_expanded():
    """input_procedure_thru/output_procedure_thru must range-expand every
    paragraph in [start..thru], not just the named endpoint -- the same
    treatment PERFORM ... THRU already gets."""
    result = _parse(PURE_PROCEDURE_THRU_SOURCE, "sortthru.cbl")
    seen, reasons = _reachable_paragraphs(result.ast, "MAIN-PARA")
    assert seen == {"MAIN-PARA", "FEED-A", "FEED-B", "EMIT-A", "EMIT-B"}
    assert reasons == []


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


def test_unmocked_pure_procedure_refuses_release_and_return():
    result = _parse(PURE_PROCEDURE_SORT_SOURCE, "sortproc.cbl")
    surface = analyze(result.ast)
    file_status = analyze_file_status_fields(result.ast)
    reasons = check_test_case(surface, result.ast, _case("MAIN-PARA"), file_status)
    # Both RELEASE (FEED-PARA) and RETURN (EMIT-PARA) are now reachable
    # via the implicit-PERFORM edge the SORT statement's INPUT/OUTPUT
    # PROCEDURE names represent -- UNSUPPORTED_SORT_MERGE never fires
    # here, since the SORT statement itself was never even recorded as a
    # site.
    unmocked = [r for r in reasons if r.code == "UNMOCKED_FILE_OP"]
    assert len(unmocked) == 2
    assert any("RELEASE boundary" in r.message for r in unmocked)
    assert any("RETURN boundary" in r.message for r in unmocked)
    assert not any(r.code == "UNSUPPORTED_SORT_MERGE" for r in reasons)


def test_mocked_release_and_return_clears_pure_procedure_case():
    result = _parse(PURE_PROCEDURE_SORT_SOURCE, "sortproc.cbl")
    surface = analyze(result.ast)
    file_status = analyze_file_status_fields(result.ast)
    case = _case(
        "MAIN-PARA",
        mocks=[
            MockDirective(MockCategory.RELEASE, "SORT-REC"),
            MockDirective(
                MockCategory.RETURN,
                "SORT-FILE",
                rows=[[("SORT-KEY", '"AAA"')]],
                terminal_row=[("WS-EOF-FLAG", '"Y"')],
            ),
        ],
    )
    reasons = check_test_case(surface, result.ast, case, file_status)
    assert reasons == []


def test_mock_return_rows_without_terminal_is_accepted_with_at_end():
    """Issue #341: an SD can never declare FILE STATUS, but exhausting the
    ROWS runs the RETURN's own lifted AT END clause, which ends the loop."""
    result = _parse(PURE_PROCEDURE_SORT_SOURCE, "sortproc.cbl")
    surface = analyze(result.ast)
    file_status = analyze_file_status_fields(result.ast)
    case = _case(
        "MAIN-PARA",
        mocks=[
            MockDirective(MockCategory.RELEASE, "SORT-REC"),
            MockDirective(
                MockCategory.RETURN, "SORT-FILE", rows=[[("SORT-KEY", '"AAA"')]]
            ),
        ],
    )
    reasons = check_test_case(surface, result.ast, case, file_status)
    assert not any(r.code == "UNRESOLVED_FILE_STATUS_TARGET" for r in reasons)


def test_mock_return_rows_without_terminal_or_at_end_refuses_unresolved_status():
    source = PURE_PROCEDURE_SORT_SOURCE.replace(
        'RETURN SORT-FILE AT END MOVE "Y" TO WS-EOF-FLAG.', "RETURN SORT-FILE."
    )
    assert source != PURE_PROCEDURE_SORT_SOURCE
    result = _parse(source, "sortproc.cbl")
    surface = analyze(result.ast)
    file_status = analyze_file_status_fields(result.ast)
    case = _case(
        "MAIN-PARA",
        mocks=[
            MockDirective(MockCategory.RELEASE, "SORT-REC"),
            MockDirective(
                MockCategory.RETURN, "SORT-FILE", rows=[[("SORT-KEY", '"AAA"')]]
            ),
        ],
    )
    reasons = check_test_case(surface, result.ast, case, file_status)
    assert any(r.code == "UNRESOLVED_FILE_STATUS_TARGET" for r in reasons)


def test_mixed_form_needs_its_sort_mocked():
    result = _parse(MIXED_SORT_SOURCE, "sortmixed.cbl")
    surface = analyze(result.ast)
    file_status = analyze_file_status_fields(result.ast)
    reasons = check_test_case(surface, result.ast, _case("MAIN-PARA"), file_status)
    codes = {r.code for r in reasons}
    assert "UNSUPPORTED_SORT_MERGE" not in codes
    assert "UNMOCKED_FILE_OP" in codes


def test_mock_sort_and_return_cover_a_mixed_form_site():
    result = _parse(MIXED_SORT_SOURCE, "sortmixed.cbl")
    surface = analyze(result.ast)
    file_status = analyze_file_status_fields(result.ast)
    case = _case(
        "MAIN-PARA",
        mocks=[
            MockDirective(MockCategory.SORT, "SORT-FILE"),
            MockDirective(MockCategory.RETURN, "SORT-FILE"),
        ],
    )
    reasons = check_test_case(surface, result.ast, case, file_status)
    assert not [r for r in reasons if r.code != "UNSUPPORTED_TERMINATOR_LAYOUT"]


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


def test_scaffold_omits_pure_procedure_sort_but_covers_release_and_return():
    result = _parse(PURE_PROCEDURE_SORT_SOURCE, "sortproc.cbl")
    surface = analyze(result.ast)
    cut_text = scaffold_cut("SORTPROC", surface)
    assert "MOCK SORT" not in cut_text
    assert "MOCK MERGE" not in cut_text
    assert "MOCK RELEASE SORT-REC" in cut_text
    assert "MOCK RETURN SORT-FILE" in cut_text


def test_scaffold_mocks_a_mixed_form_sort_and_its_return():
    result = _parse(MIXED_SORT_SOURCE, "sortmixed.cbl")
    surface = analyze(result.ast)
    cut_text = scaffold_cut("SORTMIXED", surface)
    assert "MOCK SORT SORT-FILE" in cut_text
    assert "MOCK RETURN SORT-FILE" in cut_text


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


def test_splice_program_leaves_pure_procedure_sort_real_and_splices_release():
    # The SORT statement itself is real/unspliced (it's not even a
    # BoundarySite); only its RELEASE gets a dispatch block.
    result = _parse(PURE_PROCEDURE_SORT_SOURCE, "sortproc.cbl")
    surface = analyze(result.ast)
    lines = PURE_PROCEDURE_SORT_SOURCE.split("\n")
    cut_text = (
        'TESTSUITE "S"\n'
        'TESTCASE "tc"\n'
        "    MOCK RELEASE SORT-REC\n"
        '        DISPLAY "released"\n'
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
    assert (
        "SORT SORT-FILE ON ASCENDING KEY" in spliced_text
    )  # SORT itself: real, untouched
    release_line = next(line for line in spliced if "RELEASE SORT-REC" in line)
    assert release_line.lstrip().startswith("*>")  # RELEASE: commented out
    assert 'DISPLAY "released"' in spliced_text
    assert "UT-RELEASE-SORT-REC-TALLY" in spliced_text


def test_splice_program_return_rows_dispatch_does_not_leak_sqlcode():
    # Regression pin: build_site_dispatch's ROWS branch was gated on
    # `directive.category is MockCategory.READ` specifically, so a MOCK
    # RETURN ... ROWS fell through to the SQL-shaped branch and emitted
    # meaningless `MOVE ... TO SQLCODE` lines instead of the ordinary
    # row-value MOVEs. Confirmed broken interactively before the
    # injector.py fix; this test pins the fix.
    result = _parse(PURE_PROCEDURE_SORT_SOURCE, "sortproc.cbl")
    surface = analyze(result.ast)
    lines = PURE_PROCEDURE_SORT_SOURCE.split("\n")
    cut_text = (
        'TESTSUITE "S"\n'
        'TESTCASE "tc"\n'
        "    MOCK RETURN SORT-FILE ROWS\n"
        '    (SORT-KEY = "AAA")\n'
        '    TERMINAL (WS-EOF-FLAG = "Y")\n'
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
    assert "SQLCODE" not in spliced_text
    assert 'MOVE "AAA" TO SORT-KEY' in spliced_text
    assert 'MOVE "Y" TO WS-EOF-FLAG' in spliced_text
