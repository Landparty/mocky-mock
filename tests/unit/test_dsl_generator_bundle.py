"""Unit tests for the bundle-driven half of `dsl.generator.scaffold_cut`
(`mockymock generate --with-data`, Phase 8 of the gen-fixtures initiative).
See docs/plans/2026-08-02-program-data-generation-implementation.md and
cobol-parser's docs/fixture-bundle-schema.md."""

from cobolparser import parse_cobol
from cobolparser.generators import ProgramFixtureGenerator

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.fixture_bundle import (
    BoundaryFixture,
    Expectation,
    FieldSpec,
    FixtureBundle,
    Scenario,
    load_fixture_bundle,
)
from mockymock.dsl.generator import scaffold_cut
from mockymock.dsl.model import MockCategory
from mockymock.dsl.parser import parse_cut

# --- real, end-to-end bundles via cobol-parser's own API ---------------------

ORDRPROC_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDRPROC.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       PROCESS-ORDER.
           CALL "DISCRATE" USING WS-AMOUNT WS-RATE.
"""

MULTI_FILE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTIFILE.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INV-FILE ASSIGN TO "INV.DAT".
           SELECT RPT-FILE ASSIGN TO "RPT.DAT".

       DATA DIVISION.
       FILE SECTION.
       FD  INV-FILE.
       01  INV-REC.
           05  INV-QTY        PIC 9(4).
       FD  RPT-FILE.
       01  RPT-REC             PIC X(20).

       WORKING-STORAGE SECTION.
       01  WS-EOF              PIC X VALUE "N".

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT INV-FILE OUTPUT RPT-FILE.
           READ INV-FILE
               AT END MOVE "Y" TO WS-EOF
           END-READ.
           WRITE RPT-REC.
           CLOSE INV-FILE RPT-FILE.
"""


def _surface_and_bundle(source, filename, seed=7):
    """Build mockymock's own surface and a real cobol-parser bundle from
    the SAME parsed AST, independently -- generate() (not
    generate_from_file, which needs a real path on disk) over an AST built
    the ordinary way, so these tests don't need temp files."""
    result = parse_cobol(source, filename=filename)
    assert result.success, result.errors
    surface = analyze(result.ast)

    from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
    from cobolparser.generators.data.program_layout import ProgramLayoutIndex

    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    cp_bundle = ProgramFixtureGenerator().generate(result.ast, index, report, seed=seed)
    return surface, load_fixture_bundle(cp_bundle.to_dict())


def test_one_testcase_per_scenario_named_from_the_scenario():
    surface, bundle = _surface_and_bundle(ORDRPROC_SOURCE, "ordrproc.cbl")
    text = scaffold_cut("ORDRPROC", surface, bundle)
    suite = parse_cut(text)
    assert len(suite.test_cases) == 1
    assert suite.test_cases[0].name == "happy path"
    assert suite.test_cases[0].perform_target == "PROCESS-ORDER"


def test_generated_cut_is_valid_syntax_and_lints_clean():
    from mockymock.analysis.refusal import check_test_case

    surface, bundle = _surface_and_bundle(ORDRPROC_SOURCE, "ordrproc.cbl")
    result = parse_cobol(ORDRPROC_SOURCE, filename="ordrproc.cbl")
    text = scaffold_cut("ORDRPROC", surface, bundle)
    suite = parse_cut(text)
    for case in suite.test_cases:
        assert check_test_case(surface, result.ast, case) == [], case.name


def test_call_fixture_moves_every_layout_field():
    surface, bundle = _surface_and_bundle(ORDRPROC_SOURCE, "ordrproc.cbl")
    text = scaffold_cut("ORDRPROC", surface, bundle)
    assert "MOVE" in text
    assert "TO WS-AMOUNT" in text
    assert "TO WS-RATE" in text


def test_call_count_verify_matches_the_actual_sequence():
    surface, bundle = _surface_and_bundle(ORDRPROC_SOURCE, "ordrproc.cbl")
    text = scaffold_cut("ORDRPROC", surface, bundle)
    assert 'VERIFY CALL "DISCRATE" WAS CALLED 1 TIMES' in text


def test_bidirectional_call_arguments_become_stub_comments():
    surface, bundle = _surface_and_bundle(ORDRPROC_SOURCE, "ordrproc.cbl")
    text = scaffold_cut("ORDRPROC", surface, bundle)
    assert "*> STUB EXPECT WS-AMOUNT" in text
    assert "*> STUB EXPECT WS-RATE" in text


def test_multi_file_open_close_gets_exactly_one_mock_directive_each():
    """A physical OPEN INPUT A OUTPUT B is one BoundarySite with two keys
    (see mock_surface._file_op_keys) even though cobol-parser's
    BoundaryInventoryAnalyzer reports one Boundary per file -- declaring a
    MOCK for both would double-match the one physical site and refuse
    AMBIGUOUS_MOCK."""
    surface, bundle = _surface_and_bundle(MULTI_FILE_SOURCE, "multifile.cbl")
    text = scaffold_cut("MULTIFILE", surface, bundle)
    assert text.count("MOCK OPEN") == 1
    assert text.count("MOCK CLOSE") == 1


def test_multi_file_open_close_still_lints_clean():
    from mockymock.analysis.refusal import check_test_case

    surface, bundle = _surface_and_bundle(MULTI_FILE_SOURCE, "multifile.cbl")
    result = parse_cobol(MULTI_FILE_SOURCE, filename="multifile.cbl")
    suite = parse_cut(scaffold_cut("MULTIFILE", surface, bundle))
    for case in suite.test_cases:
        assert check_test_case(surface, result.ast, case) == [], case.name


def test_out_direction_write_gets_a_placeholder_mock():
    """WRITE is OUT-direction -- the bundle carries no fixture for it, only
    a boundary-level stub expectation -- but it's still reachable from
    MAIN-PROCESS, so it needs SOME mock or run/lint refuses it unmocked."""
    surface, bundle = _surface_and_bundle(MULTI_FILE_SOURCE, "multifile.cbl")
    text = scaffold_cut("MULTIFILE", surface, bundle)
    assert "MOCK WRITE RPT-REC" in text


def test_out_direction_write_has_no_duplicate_verify_or_expect():
    """The WRITE boundary's own stub expectation (ref="WRITE:RPT-REC") is a
    boundary-level ref, not a data-name -- it must not turn into a bogus
    `EXPECT WRITE:RPT-REC ...` or `*> STUB EXPECT WRITE:RPT-REC` line."""
    surface, bundle = _surface_and_bundle(MULTI_FILE_SOURCE, "multifile.cbl")
    text = scaffold_cut("MULTIFILE", surface, bundle)
    assert "WRITE:RPT-REC" not in text


def test_read_multi_row_sequence_uses_tally_branching_evaluate():
    surface, bundle = _surface_and_bundle(MULTI_FILE_SOURCE, "multifile.cbl", seed=7)
    text = scaffold_cut("MULTIFILE", surface, bundle)
    assert "EVALUATE TRUE" in text
    assert "UT-READ-INV-FILE-TALLY = 1" in text
    assert "END-EVALUATE" in text


def test_read_terminal_moves_the_terminal_field_in_when_other():
    surface, bundle = _surface_and_bundle(MULTI_FILE_SOURCE, "multifile.cbl")
    text = scaffold_cut("MULTIFILE", surface, bundle)
    read_fixture = next(
        f
        for f in bundle.scenarios[0].fixtures
        if f.category == "READ" and f.key == "INV-FILE"
    )
    if read_fixture.terminal:
        field_name = next(iter(read_fixture.terminal))
        assert "WHEN OTHER" in text
        assert f'MOVE "10" TO {field_name}' in text


# --- hand-built bundles for isolated logic -----------------------------------


def _field(name, category="numeric"):
    return FieldSpec(
        name=name,
        column=name,
        qualified_name=name,
        level=5,
        picture="9(3)" if category == "numeric" else "X(10)",
        usage="DISPLAY",
        category=category,
        size=3,
        integer_digits=3,
        decimal_digits=0,
        is_signed=False,
    )


def _simple_call_surface_and_case_source():
    return """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STATUSTEST.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO "F1.DAT"
               FILE STATUS IS WS-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC              PIC X(10).

       WORKING-STORAGE SECTION.
       01  WS-STATUS           PIC XX.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT F1.
           CLOSE F1.
"""


def test_status_only_with_default_status_has_empty_body():
    surface, bundle = _surface_and_bundle(
        _simple_call_surface_and_case_source(), "statustest.cbl", seed=1
    )
    suite = parse_cut(scaffold_cut("STATUSTEST", surface, bundle))
    open_mock = next(
        m for m in suite.test_cases[0].mocks if m.category is MockCategory.OPEN
    )
    assert open_mock.body_lines == []


def test_sql_single_row_uses_plain_body_not_rows_sugar():
    fixture = BoundaryFixture(
        category="SQL",
        key="SELECT",
        paragraph="P",
        line=1,
        direction="IN",
        layout=[_field("CUST-ID")],
        sequence=[{"CUST-ID": "42"}],
        status={"SQLCODE": "0"},
    )
    from mockymock.dsl.generator import _single_row_body, _sql_wants_rows

    assert _sql_wants_rows(fixture) is False
    body = _single_row_body(fixture)
    assert "MOVE 42 TO CUST-ID" in body
    assert "MOVE 0 TO SQLCODE" in body


def test_sql_multi_row_default_status_wants_rows_sugar():
    fixture = BoundaryFixture(
        category="SQL",
        key="SELECT",
        paragraph="P",
        line=1,
        direction="IN",
        layout=[_field("CUST-ID")],
        sequence=[{"CUST-ID": "1"}, {"CUST-ID": "2"}],
        status={"SQLCODE": "0"},
    )
    from mockymock.dsl.generator import _sql_wants_rows

    assert _sql_wants_rows(fixture) is True


def test_sql_multi_row_with_status_override_does_not_want_rows_sugar():
    """ROWS sugar hardcodes SQLCODE 0/100 -- it cannot express an
    error-status override, so a scenario pinning one must fall back to a
    plain body with an explicit MOVE instead."""
    fixture = BoundaryFixture(
        category="SQL",
        key="SELECT",
        paragraph="P",
        line=1,
        direction="IN",
        layout=[_field("CUST-ID")],
        sequence=[{"CUST-ID": "1"}, {"CUST-ID": "2"}],
        status={"SQLCODE": "-911"},
    )
    from mockymock.dsl.generator import _sql_wants_rows

    assert _sql_wants_rows(fixture) is False


def test_bundle_rendered_value_quotes_alphanumeric_and_bares_numeric():
    from mockymock.dsl.generator import _bundle_rendered_value

    assert _bundle_rendered_value("42", "numeric") == "42"
    assert _bundle_rendered_value("SMITH", "alphanumeric") == '"SMITH"'
    assert _bundle_rendered_value('O"BRIEN', "alphanumeric") == '"O""BRIEN"'


def test_boundary_level_ref_detection():
    from mockymock.dsl.generator import _is_boundary_level_ref

    assert _is_boundary_level_ref("READ:INFILE") is True
    assert _is_boundary_level_ref("CALL:DISCRATE") is True
    assert _is_boundary_level_ref("WS-NET-TOTAL") is False
    assert _is_boundary_level_ref("NOT-A-CATEGORY:X") is False


def test_zero_scenarios_produces_a_bare_testsuite():
    bundle = FixtureBundle(bundle_version=1, program_name="EMPTY", seed=1, scenarios=[])
    surface, _ = _surface_and_bundle(ORDRPROC_SOURCE, "ordrproc.cbl")
    text = scaffold_cut("EMPTY", surface, bundle)
    suite = parse_cut(text)
    assert suite.test_cases == []


def test_scenario_with_no_entry_is_skipped_not_crashed():
    bundle = FixtureBundle(
        bundle_version=1,
        program_name="X",
        seed=1,
        scenarios=[Scenario(name="no entry", entry=None)],
    )
    surface, _ = _surface_and_bundle(ORDRPROC_SOURCE, "ordrproc.cbl")
    text = scaffold_cut("X", surface, bundle)
    suite = parse_cut(text)
    assert suite.test_cases == []


def test_field_equals_expectation_becomes_expect_line():
    surface, _ = _surface_and_bundle(ORDRPROC_SOURCE, "ordrproc.cbl")
    bundle = FixtureBundle(
        bundle_version=1,
        program_name="ORDRPROC",
        seed=1,
        scenarios=[
            Scenario(
                name="happy path",
                entry="PROCESS-ORDER",
                fixtures=[],
                expectations=[
                    Expectation(kind="field_equals", ref="WS-TOTAL", value="1244")
                ],
            )
        ],
    )
    text = scaffold_cut("ORDRPROC", surface, bundle)
    assert "EXPECT WS-TOTAL TO BE 1244" in text
