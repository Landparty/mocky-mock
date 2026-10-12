"""Unit tests for the bundle-driven half of `dsl.generator.scaffold_cut`
(`mockymock generate --with-data`, Phase 8 of the gen-fixtures initiative).
See docs/plans/2026-08-02-program-data-generation-implementation.md and
cobol-parser's docs/fixture-bundle-schema.md."""

import re
from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.generators import ProgramFixtureGenerator
from cobolparser.generators.data.options import DataGeneratorOptions

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
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

FIXTURES_EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "fixtures"

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


def _surface_and_bundle(source, filename, seed=7, rows=None):
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
    generator = (
        ProgramFixtureGenerator()
        if rows is None
        else ProgramFixtureGenerator(DataGeneratorOptions(rows=rows))
    )
    cp_bundle = generator.generate(result.ast, index, report, seed=seed)
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


def test_out_direction_write_stub_reaches_the_generated_file():
    """The WRITE boundary's own tier-3 stub expectation (ref
    "WRITE:RPT-REC") used to be dropped outright on the reasoning that the
    same boundary's `call_count` VERIFY already covered it -- but no such
    VERIFY exists for an OUT-direction WRITE, so the bundle knew something
    the generated `.cut` never said. It is now surfaced as a `*> STUB
    EXPECT` comment (inert, so it can never break the file) carrying the
    bundle's own note."""
    surface, bundle = _surface_and_bundle(MULTI_FILE_SOURCE, "multifile.cbl")
    text = scaffold_cut("MULTIFILE", surface, bundle)
    assert (
        "*> STUB EXPECT WRITE RPT-REC -- value produced by the program "
        "under test" in text
    )
    # Rendered the way a MOCK/VERIFY for that boundary reads, never as the
    # raw `CATEGORY:KEY` bundle ref.
    assert "WRITE:RPT-REC" not in text
    assert "EXPECT WRITE:RPT-REC" not in text


def test_boundary_level_stub_is_ignored_by_the_record_expectations_scanner():
    """`*> STUB EXPECT <data-name>` is a real feature -- `run
    --record-expectations` rewrites those into `EXPECT` lines. A
    boundary-level stub names a boundary, not a data item, so it must not
    be picked up as one; its two-token shape simply does not match the
    scanner's data-name grammar."""
    from mockymock.analysis.stub_expectations import scan_stub_expectations

    surface, bundle = _surface_and_bundle(MULTI_FILE_SOURCE, "multifile.cbl")
    text = scaffold_cut("MULTIFILE", surface, bundle)
    scan = scan_stub_expectations(text, parse_cut(text))
    assert [s.data_name for s in scan.stubs] == []
    assert scan.skipped == []


def test_boundary_level_stub_is_dropped_when_a_real_verify_covers_it():
    """The original reasoning still applies where it is actually true: a
    boundary this TESTCASE does emit a live `VERIFY ... WAS CALLED` for
    needs no stub comment as well."""
    from mockymock.dsl.generator import _render_expectation

    stub = Expectation(kind="stub", ref="READ:INV-FILE", note="n")
    declared = {(MockCategory.READ, "INV-FILE")}
    counted = {(MockCategory.READ, "INV-FILE")}
    assert _render_expectation(stub, declared, {}, counted) == []
    # ... and is kept when no such VERIFY was rendered.
    assert _render_expectation(stub, declared, {}, set()) == [
        "*> STUB EXPECT READ INV-FILE -- n"
    ]


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


def test_read_at_end_clause_replicated_when_no_status_field_exists():
    """MULTI_FILE_SOURCE's INV-FILE has no FILE STATUS clause at all --
    fixture.terminal is correctly None (see cobol-parser's
    _resolve_status_field), but the program's own `AT END MOVE "Y" TO
    WS-EOF` still needs replicating, or the READ mock's EVALUATE gets no
    WHEN OTHER branch at all and the program's own PERFORM ... UNTIL
    WS-EOF loop never terminates -- an infinite loop found empirically via
    a real Docker run against examples/invupdt/'s own --with-data output,
    not by lint (see the module docstring on _read_body)."""
    surface, bundle = _surface_and_bundle(MULTI_FILE_SOURCE, "multifile.cbl")
    read_fixture = next(
        f
        for f in bundle.scenarios[0].fixtures
        if f.category == "READ" and f.key == "INV-FILE"
    )
    assert read_fixture.terminal is None  # ground the test's own premise
    text = scaffold_cut("MULTIFILE", surface, bundle)
    assert "WHEN OTHER" in text
    assert 'MOVE "Y" TO WS-EOF' in text


MULTI_FILE_SOURCE_WITH_STATUS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTIFILESTATUS.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INV-FILE ASSIGN TO "INV.DAT"
               FILE STATUS IS WS-INV-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  INV-FILE.
       01  INV-REC.
           05  INV-QTY        PIC 9(4).

       WORKING-STORAGE SECTION.
       01  WS-INV-STATUS       PIC XX.
       01  WS-EOF              PIC X VALUE "N".

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT INV-FILE.
           READ INV-FILE
               AT END MOVE "Y" TO WS-EOF
           END-READ.
           CLOSE INV-FILE.
"""


def test_read_at_end_clause_replicated_alongside_a_real_status_field():
    """Unlike MULTI_FILE_SOURCE, this file DOES declare FILE STATUS --
    both the status-field MOVE and the replicated AT END MOVE must
    appear, in that order, in the same WHEN OTHER branch."""
    surface, bundle = _surface_and_bundle(
        MULTI_FILE_SOURCE_WITH_STATUS, "multifilestatus.cbl"
    )
    read_fixture = next(
        f
        for f in bundle.scenarios[0].fixtures
        if f.category == "READ" and f.key == "INV-FILE"
    )
    assert read_fixture.terminal == {"WS-INV-STATUS": "10"}
    text = scaffold_cut("MULTIFILESTATUS", surface, bundle)
    when_other = text.split("WHEN OTHER", 1)[1]
    status_index = when_other.index('MOVE "10" TO WS-INV-STATUS')
    eof_index = when_other.index('MOVE "Y" TO WS-EOF')
    assert status_index < eof_index


IDENTIFIER_SOURCED_AT_END_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IDENTSRC.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INV-FILE ASSIGN TO "INV.DAT".

       DATA DIVISION.
       FILE SECTION.
       FD  INV-FILE.
       01  INV-REC.
           05  INV-QTY        PIC 9(4).

       WORKING-STORAGE SECTION.
       01  WS-DONE-FLAG        PIC X VALUE "N".
       01  WS-EOF              PIC X VALUE "N".

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT INV-FILE.
           READ INV-FILE
               AT END MOVE WS-DONE-FLAG TO WS-EOF
           END-READ.
           CLOSE INV-FILE.
"""


def test_read_at_end_clause_with_identifier_source_gets_a_todo_comment():
    """MOVE WS-DONE-FLAG TO WS-EOF -- an identifier source, not a literal
    -- cannot be safely replicated (WS-DONE-FLAG's value in the mock's
    own splice-time context is not the real program's runtime state), so
    a TODO comment flags the gap instead of silently emitting an
    EVALUATE with no WHEN OTHER effect at all."""
    surface, bundle = _surface_and_bundle(
        IDENTIFIER_SOURCED_AT_END_SOURCE, "identsrc.cbl"
    )
    text = scaffold_cut("IDENTSRC", surface, bundle)
    assert "WHEN OTHER" in text
    assert "TODO" in text
    assert "WS-DONE-FLAG" not in text  # never blindly copied


SET_CONDITION_NAME_AT_END_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SETEOF.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INV-FILE ASSIGN TO "INV.DAT"
               FILE STATUS IS WS-INV-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  INV-FILE.
       01  INV-REC.
           05  INV-QTY        PIC 9(4).

       WORKING-STORAGE SECTION.
       01  WS-INV-STATUS       PIC XX.
       01  WS-EOF-FLAG         PIC X VALUE "N".
           88  WS-EOF-REACHED  VALUE "Y".

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT INV-FILE.
           READ INV-FILE
               AT END SET WS-EOF-REACHED TO TRUE
           END-READ.
           CLOSE INV-FILE.
"""


def test_read_at_end_set_condition_name_is_replicated():
    """The condition-name spelling of the EOF-flag idiom -- `AT END SET
    WS-EOF-REACHED TO TRUE` against an 88 -- must be replicated exactly
    like `AT END MOVE "Y" TO WS-EOF` is. It parses to a SetStatement, not
    a MoveStatement, so the original MOVE-only replication skipped it and
    emitted only the FILE STATUS move plus a TODO: the application flag
    was never flipped and the program's own PERFORM UNTIL loop spun
    forever (the same infinite loop the MOVE case already fixed, reached
    by a different-but-equally-common spelling)."""
    surface, bundle = _surface_and_bundle(
        SET_CONDITION_NAME_AT_END_SOURCE, "seteof.cbl"
    )
    text = scaffold_cut("SETEOF", surface, bundle)
    assert "WHEN OTHER" in text
    assert "SET WS-EOF-REACHED TO TRUE" in text
    assert "TODO" not in text


def test_read_at_end_set_replicated_after_the_status_field_move():
    """Same ordering guarantee `test_read_at_end_clause_replicated_
    alongside_a_real_status_field` pins for MOVE: the terminal FILE
    STATUS move comes first, the replicated loop guard after it."""
    surface, bundle = _surface_and_bundle(
        SET_CONDITION_NAME_AT_END_SOURCE, "seteof.cbl"
    )
    text = scaffold_cut("SETEOF", surface, bundle)
    when_other = text.split("WHEN OTHER", 1)[1]
    assert when_other.index('MOVE "10" TO WS-INV-STATUS') < when_other.index(
        "SET WS-EOF-REACHED TO TRUE"
    )


SET_UP_BY_AT_END_SOURCE = (
    SET_CONDITION_NAME_AT_END_SOURCE.replace(
        "PROGRAM-ID. SETEOF.", "PROGRAM-ID. SETUPBY."
    )
    .replace("AT END SET WS-EOF-REACHED TO TRUE", "AT END SET WS-IDX UP BY 1")
    .replace(
        "       01  WS-INV-STATUS       PIC XX.",
        "       01  WS-INV-STATUS       PIC XX.\n       01  WS-IDX              PIC 9(4) VALUE 1.",
    )
)


def test_read_at_end_set_replicated_in_the_empty_sequence_body():
    """The hang fix has to hold on all THREE paths that share
    `_read_exhaustion_lines`, not just the multi-row `WHEN OTHER` branch.
    With an empty `sequence` (`--rows 0`, or a bundle's own "empty input"
    scenario family) every READ is immediately exhausted, so the
    exhaustion content fires directly with no EVALUATE -- and it must
    still carry the loop guard, or the program's PERFORM UNTIL loop hangs
    on its very first READ."""
    surface, bundle = _surface_and_bundle(
        SET_CONDITION_NAME_AT_END_SOURCE, "seteof.cbl", rows=0
    )
    read_fixture = next(f for f in bundle.scenarios[0].fixtures if f.category == "READ")
    assert read_fixture.sequence == []  # ground the test's own premise
    text = scaffold_cut("SETEOF", surface, bundle)
    assert "EVALUATE TRUE" not in text  # no row-selecting branch at all
    assert "SET WS-EOF-REACHED TO TRUE" in text
    assert "TODO" not in text


def test_read_at_end_set_replicated_in_the_placeholder_downgrade():
    """Third path: a `--placeholder`-downgraded READ reuses the same
    helper to emit an "immediately at end" body. Dropping the loop guard
    here would hang exactly like the other two, and `--placeholder` is
    not allowed to trade away the "every generated .cut is runnable by
    construction" invariant (see
    test_placeholder_downgrades_read_boundary_to_an_immediately_at_end_body)."""
    surface, bundle = _surface_and_bundle(
        SET_CONDITION_NAME_AT_END_SOURCE, "seteof.cbl"
    )
    text = scaffold_cut(
        "SETEOF",
        surface,
        bundle,
        placeholder_keys=frozenset({("READ", "INV-FILE")}),
    )
    assert "MOCK READ INV-FILE" in text
    assert "EVALUATE TRUE" not in text  # downgraded: no tally branching
    assert 'MOVE "10" TO WS-INV-STATUS' in text  # fixture.terminal
    assert "SET WS-EOF-REACHED TO TRUE" in text  # replicated loop guard
    assert "TODO" not in text


def test_read_at_end_non_constant_set_gets_a_todo_comment():
    """`SET ... UP BY 1` is not a constant assignment to a condition
    name -- it reads the target's own runtime value, which the mock's
    splice-time context does not have. Left unreplicated, with the TODO
    flagging the gap, exactly like an identifier-sourced MOVE."""
    surface, bundle = _surface_and_bundle(SET_UP_BY_AT_END_SOURCE, "setupby.cbl")
    text = scaffold_cut("SETUPBY", surface, bundle)
    assert "WHEN OTHER" in text
    assert "TODO" in text
    assert "UP BY" not in text  # never blindly copied


def test_multi_group_set_is_not_partially_replicated():
    """A multi-group `SET A TO TRUE B TO FALSE` carries its second group
    in `groups`, which this generator has no way to render. Replicating
    only the first group would be a SILENT PARTIAL replication -- worse
    than none, since the TODO comment would not be emitted to flag it --
    so the whole statement is skipped."""
    from mockymock.dsl.generator import _replicated_set_lines

    class _FakeSet:
        def __init__(self):
            self.set_type = "TRUE"
            self.targets = ["WS-EOF-REACHED"]
            self.groups = [{"targets": ["WS-OTHER"], "set_type": "FALSE"}]

    fake = _FakeSet()
    fake.__class__.__name__ = "SetStatement"
    assert _replicated_set_lines(fake) == []

    fake.groups = []
    assert _replicated_set_lines(fake) == ["SET WS-EOF-REACHED TO TRUE"]


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


FIELD_EQUALS_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CODE            PIC X(5).
       01  WS-TXT             PIC X(5).
       01  WS-AMT             PIC S9(3)V99.
       01  WS-CNT             PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "-3" TO WS-CODE.
           MOVE "1.5" TO WS-TXT.
           MOVE -3.5 TO WS-AMT.
           MOVE 7 TO WS-CNT.
           DISPLAY WS-CODE WS-TXT WS-AMT WS-CNT.
"""


def test_field_equals_on_an_alphanumeric_field_is_quoted_from_its_picture():
    # A folded "-3" / "1.5" held in a PIC X field used to render bare
    # (`EXPECT WS-CODE TO BE -3`), a comparison GnuCOBOL makes as text and
    # finds unequal: the generated test failed on its very first run.
    from mockymock.dsl.generator import ProgramContext

    result = parse_cobol(FIELD_EQUALS_SOURCE, filename="fe.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = FIELD_EQUALS_SOURCE.splitlines()
    bundle = FixtureBundle(
        bundle_version=1,
        program_name="FE",
        seed=1,
        scenarios=[
            Scenario(
                name="happy path",
                entry="MAIN-PARA",
                expectations=[
                    Expectation(kind="field_equals", ref="WS-CODE", value="-3"),
                    Expectation(kind="field_equals", ref="WS-TXT", value="1.5"),
                    Expectation(kind="field_equals", ref="WS-AMT", value="-3.50"),
                    Expectation(kind="field_equals", ref="WS-CNT", value="7"),
                ],
            )
        ],
    )
    text = scaffold_cut(
        "FE",
        surface,
        bundle,
        source=ProgramContext.build(result.ast, lines, surface),
    )
    assert 'EXPECT WS-CODE TO BE "-3"' in text
    assert 'EXPECT WS-TXT TO BE "1.5"' in text
    assert "EXPECT WS-AMT TO BE -3.50" in text
    assert "EXPECT WS-CNT TO BE 7" in text
    parse_cut(text)


# --- `--placeholder`: downgrade a matched fixture's body (Task 4 of the
# unify-with-data reconciliation plan) -----------------------------------


def _fixturedemo_surface_and_bundle():
    """FIXTUREDEMO.cbl/.bundle.json (examples/fixtures/) are the checked-in
    Phase 9 worked example -- reused here (not a hand-built bundle) because
    it already has a real, generator-produced READ boundary (multi-row,
    tally-branching EVALUATE) AND a real EXEC SQL boundary (single-row) in
    one program, exactly the two categories the --placeholder tests below
    need. See tests/integration/test_fixturedemo_golden.py, which loads
    the same pair the same way."""
    from mockymock.dsl.fixture_bundle import load_fixture_bundle_file

    program_path = FIXTURES_EXAMPLE_DIR / "FIXTUREDEMO.cbl"
    bundle = load_fixture_bundle_file(FIXTURES_EXAMPLE_DIR / "FIXTUREDEMO.bundle.json")
    result = parse_cobol(
        program_path.read_text(encoding="utf-8"), filename=program_path.name
    )
    assert result.success, result.errors
    surface = analyze(result.ast)
    return surface, bundle


def test_placeholder_keys_defaults_to_empty_and_changes_nothing():
    """The no-new-flags invocation of `generate --with-data` must stay
    byte-identical -- an explicit empty `placeholder_keys` must produce the
    exact same text as omitting the parameter entirely."""
    surface, bundle = _fixturedemo_surface_and_bundle()
    assert scaffold_cut("FIXTUREDEMO", surface, bundle) == scaffold_cut(
        "FIXTUREDEMO", surface, bundle, placeholder_keys=frozenset()
    )


def test_placeholder_downgrades_read_boundary_to_an_immediately_at_end_body():
    """Fix round 1 (unify-with-data Task 4): READ has no entry in
    _PLACEHOLDER_BODIES (see _directive_for), so a NAIVE downgrade to the
    ordinary category-generic placeholder body would be completely empty
    -- dropping the whole tally-branching EVALUATE, the generated row
    data, AND the replicated AT END/status handling (_read_body). On
    FIXTUREDEMO specifically, whose own PERFORM READ-ORDERS UNTIL
    WS-EOF = "Y" loop depends on that handling to terminate (see
    _read_body's own docstring and commit 3ad3378), an empty downgraded
    READ mock would hang if actually run under Docker -- the base
    engine's "every generated .cut is runnable by construction" invariant
    is a hard requirement, not something --placeholder is allowed to
    trade away. The correct downgrade instead reuses
    _read_exhaustion_lines (the SAME helper _read_body's own WHEN OTHER
    branch and empty-sequence case use) to emit an "immediately at end"
    body: the real terminal status MOVE and the real replicated AT END
    MOVE, just with no row data and no EVALUATE wrapper -- the fixture
    stays MOCKED (still a MOCK READ directive) and the program's loop
    still terminates on its very first READ. Never wire a
    --placeholder'd FIXTUREDEMO.cut into the Docker-gated
    test_committed_fixturedemo_example_passes or the lint-gate corpus
    (this program's own scenario is now built to terminate immediately,
    which is a different program behavior than the golden's, not a bug
    but also not something those tests are pinning)."""
    surface, bundle = _fixturedemo_surface_and_bundle()
    text = scaffold_cut(
        "FIXTUREDEMO",
        surface,
        bundle,
        placeholder_keys=frozenset({("READ", "ORDER-FILE")}),
    )
    assert "MOCK READ ORDER-FILE" in text
    assert "ORD001" not in text  # no seeded row data
    assert "EVALUATE TRUE" not in text  # no tally-branching -- one shot
    # the actual loop-termination MOVEs, not an empty body:
    assert 'MOVE "10" TO WS-ORDER-STATUS' in text  # fixture.terminal
    assert 'MOVE "Y" TO WS-EOF' in text  # replicated AT END clause
    # every other boundary stays data-driven -- only the named pair downgrades
    assert "CHARLES GARCIA" in text


def test_placeholder_downgrades_sql_single_row_boundary():
    surface, bundle = _fixturedemo_surface_and_bundle()
    text = scaffold_cut(
        "FIXTUREDEMO",
        surface,
        bundle,
        placeholder_keys=frozenset({("SQL", "SELECT")}),
    )
    assert 'MOCK SQL "SELECT"' in text
    assert "CHARLES GARCIA" not in text
    assert "MOVE 0 TO SQLCODE" in text  # SQL's own ordinary placeholder body
    # the READ boundary stays data-driven -- only the named pair downgrades
    assert "ORD001" in text


def test_placeholder_downgraded_cut_still_round_trips_through_parse_cut():
    surface, bundle = _fixturedemo_surface_and_bundle()
    text = scaffold_cut(
        "FIXTUREDEMO",
        surface,
        bundle,
        placeholder_keys=frozenset({("READ", "ORDER-FILE"), ("SQL", "SELECT")}),
    )
    suite = parse_cut(text)
    assert len(suite.test_cases) == 1


def test_placeholder_downgrades_sql_rows_sugar_to_an_exhausted_placeholder_body():
    """Fix round 1 (unify-with-data Task 4): the ROWS-sugar path
    (_sql_wants_rows) is the SECOND case (besides READ) where a downgrade
    must preserve loop-termination machinery, not just change the
    DIRECTIVE LINE. An un-downgraded multi-row SQL fixture with default
    status emits `MOCK SQL "..." ROWS`, whose splice-time exhaustion
    branch (splicer/injector.py's build_rows_block) hardcodes `MOVE 100
    TO SQLCODE` once the cursor's rows run out. A NAIVE downgrade to the
    ordinary category-generic SQL placeholder body (`MOVE 0 TO SQLCODE`,
    permanent "more rows available") would hang a program's own `PERFORM
    UNTIL SQLCODE = 100` cursor-fetch loop forever -- the SQL analogue of
    an empty READ body. The correct downgrade drops the `ROWS` suffix
    (there is no seeded row data left to enumerate) but keeps the SAME
    `MOVE 100 TO SQLCODE` exhaustion signal the ROWS form's own splice-time
    machinery would have produced (`_SQL_ROWS_EXHAUSTED_BODY`) --
    exercised directly against _bundle_directive_for since FIXTUREDEMO's
    own SQL fixture is single-row and never reaches this branch."""
    from mockymock.dsl.generator import (
        CallCountOverride,
        _bundle_directive_for,
        _mockymock_boundary_keys,
    )
    from mockymock.dsl.model import MockTestSuite
    from mockymock.splicer.naming import TallyRegistry

    surface, _ = _surface_and_bundle(ORDRPROC_SOURCE, "ordrproc.cbl")
    # ORDRPROC_SOURCE has no EXEC SQL of its own; borrow a real CALL site's
    # surface machinery isn't enough here -- _bundle_directive_for only
    # needs `mockymock_keys` to resolve a site for its header, and EXEC
    # categories key on `_unique_prefix` text rather than a parsed name, so
    # a hand-built surface with one EXEC SQL statement is the direct route.
    sql_source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLROWS.

       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               SELECT CUST_ID FROM CUSTOMERS
           END-EXEC.
"""
    result = parse_cobol(sql_source, filename="sqlrows.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    mockymock_keys = _mockymock_boundary_keys(surface)
    registry = TallyRegistry(MockTestSuite(name="_shadow"))

    fixture = BoundaryFixture(
        category="SQL",
        key="SELECT",
        paragraph="MAIN-PARA",
        line=1,
        direction="IN",
        layout=[_field("CUST-ID")],
        sequence=[{"CUST-ID": "1"}, {"CUST-ID": "2"}],
        status={"SQLCODE": "0"},
    )

    result_without = _bundle_directive_for(fixture, mockymock_keys, registry)
    assert result_without is not None
    without_placeholder, override_without = result_without
    assert 'MOCK SQL "SELECT" ROWS' in without_placeholder[0]
    assert override_without is None  # bundle's own call_count is still exact

    result_with = _bundle_directive_for(
        fixture,
        mockymock_keys,
        registry,
        placeholder_keys=frozenset({("SQL", "SELECT")}),
    )
    assert result_with is not None
    with_placeholder, override_with = result_with
    joined = "\n".join(with_placeholder)
    assert with_placeholder[0] == 'MOCK SQL "SELECT"'  # no ROWS suffix
    assert "ROWS" not in joined
    assert "MOVE 100 TO SQLCODE" in joined  # exhausted, not permanent success
    assert "MOVE 0 TO SQLCODE" not in joined
    assert "MOVE 1 TO CUST-ID" not in joined  # generated row data is gone
    # fix round 2: the downgraded body fires its exhaustion MOVE
    # unconditionally on the very first call, so the real call count is
    # exactly 1 -- not the un-downgraded bundle's original multi-row count
    assert override_with == CallCountOverride(count=1)


def test_placeholder_on_secondary_grouped_key_still_downgrades():
    """A multi-file OPEN's non-primary file (see _bundle_directive_for_group
    -- one physical BoundarySite, one fixture per file from cobol-parser's
    own BoundaryInventoryAnalyzer) must still trigger the downgrade when
    the user names the SECONDARY file's key: the shared MOCK OPEN
    directive is keyed on the primary fixture only, so a placeholder that
    checked only the primary key would silently no-op for anyone naming
    the other one -- exactly the "matched no fixture" case the CLI's own
    unmatched-placeholder warning must never wrongly fire for, since a
    fixture genuinely exists at that key."""
    from mockymock.dsl.generator import (
        _bundle_directive_for_group,
        _mockymock_boundary_keys,
    )
    from mockymock.dsl.model import MockTestSuite
    from mockymock.splicer.naming import TallyRegistry

    surface, _ = _surface_and_bundle(MULTI_FILE_SOURCE, "multifile.cbl")
    mockymock_keys = _mockymock_boundary_keys(surface)
    registry = TallyRegistry(MockTestSuite(name="_shadow"))

    inv_fixture = BoundaryFixture(
        category="OPEN",
        key="INV-FILE",
        paragraph="MAIN-PROCESS",
        line=1,
        direction="STATUS_ONLY",
        status={"WS-INV-STATUS": "00"},
    )
    rpt_fixture = BoundaryFixture(
        category="OPEN",
        key="RPT-FILE",
        paragraph="MAIN-PROCESS",
        line=1,
        direction="STATUS_ONLY",
        status={"WS-RPT-STATUS": "35"},
    )

    result_without = _bundle_directive_for_group(
        [inv_fixture, rpt_fixture], mockymock_keys, registry
    )
    assert result_without is not None
    without_placeholder, override_without = result_without
    assert 'FILE-STATUS IS "35"' in "\n".join(without_placeholder)
    assert override_without is None

    result_with = _bundle_directive_for_group(
        [inv_fixture, rpt_fixture],
        mockymock_keys,
        registry,
        placeholder_keys=frozenset({("OPEN", "RPT-FILE")}),
    )
    assert result_with is not None
    with_placeholder, override_with = result_with
    assert 'FILE-STATUS IS "35"' not in "\n".join(with_placeholder)
    # STATUS_ONLY has no loop-termination concept -- no override needed
    # even when downgraded, per fix round 2's category-scoped fix
    assert override_with is None


# --- fix round 2: recomputed VERIFY call_count for a downgraded boundary ----


def test_placeholder_downgraded_read_gets_a_corrected_verify_count():
    """Critical bug found in review, empirically reproduced: a downgraded
    READ fires its exhaustion MOVEs unconditionally on the very first
    call (no EVALUATE/tally branching left, see the previous test) --
    FIXTUREDEMO's own PERFORM READ-ORDERS UNTIL WS-EOF = "Y" loop calls
    READ exactly ONCE at runtime, not the bundle's original un-downgraded
    11 (10 data rows + 1 exhaustion read). Rendering the bundle's stale
    `VERIFY READ ORDER-FILE WAS CALLED 11 TIMES` unchanged pins an
    assertion the generated .cut cannot itself satisfy -- a deterministic
    self-inflicted test failure. The whole generated file must be
    runnable by construction, assertions included, not just the mock
    bodies."""
    surface, bundle = _fixturedemo_surface_and_bundle()
    text = scaffold_cut(
        "FIXTUREDEMO",
        surface,
        bundle,
        placeholder_keys=frozenset({("READ", "ORDER-FILE")}),
    )
    assert "VERIFY READ ORDER-FILE WAS CALLED 11 TIMES" not in text
    assert "VERIFY READ ORDER-FILE WAS CALLED 1 TIMES" in text


def test_placeholder_downgraded_sql_rows_gets_a_corrected_verify_count():
    """Same class of bug as the READ case above, exercised through the
    full scaffold_cut pipeline (not just _bundle_directive_for's return
    value) for the SQL ROWS-sugar path: a downgraded multi-row SQL
    fixture's real call count is 1 (exhaustion on the first FETCH), not
    the bundle's original multi-row count."""
    surface, _ = _surface_and_bundle(ORDRPROC_SOURCE, "ordrproc.cbl")
    sql_source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLROWS.

       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               SELECT CUST_ID FROM CUSTOMERS
           END-EXEC.
"""
    result = parse_cobol(sql_source, filename="sqlrows.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)

    bundle = FixtureBundle(
        bundle_version=1,
        program_name="SQLROWS",
        seed=1,
        scenarios=[
            Scenario(
                name="happy path",
                entry="MAIN-PARA",
                fixtures=[
                    BoundaryFixture(
                        category="SQL",
                        key="SELECT",
                        paragraph="MAIN-PARA",
                        line=1,
                        direction="IN",
                        layout=[_field("CUST-ID")],
                        sequence=[{"CUST-ID": "1"}, {"CUST-ID": "2"}],
                        status={"SQLCODE": "0"},
                    )
                ],
                expectations=[
                    Expectation(kind="call_count", ref="SQL:SELECT", value=3)
                ],
            )
        ],
    )
    text = scaffold_cut(
        "SQLROWS", surface, bundle, placeholder_keys=frozenset({("SQL", "SELECT")})
    )
    assert 'VERIFY SQL "SELECT" WAS CALLED 3 TIMES' not in text
    assert 'VERIFY SQL "SELECT" WAS CALLED 1 TIMES' in text


def test_placeholder_downgraded_non_loop_category_verify_is_unchanged():
    """A downgraded CALL's VERIFY is program-flow-driven (how many times
    the PROCEDURE DIVISION reaches that CALL statement), entirely
    unaffected by which data the mock body happens to carry -- unlike
    READ/SQL-ROWS, no recomputation is needed or correct here."""
    surface, bundle = _fixturedemo_surface_and_bundle()
    text = scaffold_cut(
        "FIXTUREDEMO",
        surface,
        bundle,
        placeholder_keys=frozenset({("CALL", "LOGALERT")}),
    )
    assert 'VERIFY CALL "LOGALERT" WAS CALLED 1 TIMES' in text
    assert "MOVE 0 TO RETURN-CODE" in text  # CALL's own ordinary placeholder body


def test_placeholder_downgraded_read_with_no_termination_signal_demotes_verify():
    """When a downgraded READ's exhaustion body carries NO real MOVE at
    all (no FILE STATUS field, and the source AT END clause's own MOVE
    could not be safely replicated -- IDENTIFIER_SOURCED_AT_END_SOURCE's
    `MOVE WS-DONE-FLAG TO WS-EOF` is exactly this shape), the real call
    count is genuinely unknowable by construction: emitting a speculative
    VERIFY number would be worse than the original bug, since it LOOKS
    exact but isn't. The VERIFY is demoted to a `*>` comment naming why
    instead. Also confirms the demoted output is not itself a NEW way to
    produce a broken .cut: the MOCK READ body is a comment-only `*> TODO`
    line (not truly empty text), which parse_cut accepts and lint does
    not flag as UNMOCKED/VERIFY_WITHOUT_MOCK -- the demoted VERIFY comment
    is not a real directive lint would try to match against a MOCK at all."""
    from mockymock.analysis.refusal import check_test_case

    surface, bundle = _surface_and_bundle(
        IDENTIFIER_SOURCED_AT_END_SOURCE, "identsrc.cbl"
    )
    result = parse_cobol(IDENTIFIER_SOURCED_AT_END_SOURCE, filename="identsrc.cbl")
    text = scaffold_cut(
        "IDENTSRC",
        surface,
        bundle,
        placeholder_keys=frozenset({("READ", "INV-FILE")}),
    )
    # no real (numeric, assertable) VERIFY line for READ -- only the
    # demoted comment naming why one can't be emitted
    assert not re.search(r"^\s*VERIFY READ INV-FILE WAS CALLED \d", text, re.MULTILINE)
    assert "*> VERIFY READ INV-FILE WAS CALLED" in text
    assert "not exact by construction" in text
    # the demoted output round-trips and still lints clean
    suite = parse_cut(text)
    assert len(suite.test_cases) == 1
    assert check_test_case(surface, result.ast, suite.test_cases[0]) == []


READ_LOOP_WITH_INLINE_CALL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. READLOOP.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INV-FILE ASSIGN TO "INV.DAT"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  INV-FILE.
       01  INV-REC.
           05  INV-QTY        PIC 9(4).

       WORKING-STORAGE SECTION.
       01  WS-STATUS          PIC XX.
       01  WS-EOF             PIC X VALUE "N".

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT INV-FILE.
           PERFORM READ-LOOP UNTIL WS-EOF = "Y".
           CLOSE INV-FILE.

       READ-LOOP.
           READ INV-FILE
               AT END MOVE "Y" TO WS-EOF
           END-READ.
           IF WS-EOF = "N"
               CALL "LOGROW" USING INV-QTY
           END-IF.
"""


def test_placeholder_downgraded_read_demotes_a_downstream_verify_in_the_same_loop():
    """Issue #47: a CALL made once per row inside the SAME READ-LOOP
    paragraph as a --placeholder-downgraded READ is reached a DIFFERENT
    number of times once that READ is downgraded -- here, the downgraded
    READ signals EOF unconditionally on its very first call, so the
    `IF WS-EOF = "N"` guard around the CALL never passes and it is reached
    ZERO times at runtime, not the bundle's original 2 (one per
    un-downgraded row). Rendering the bundle's stale `VERIFY CALL "LOGROW"
    WAS CALLED 2 TIMES` unchanged pins an assertion the generated .cut
    cannot itself satisfy, the exact same runnable-by-construction
    violation the READ's own VERIFY count was already fixed for. The
    downstream CALL's VERIFY must be demoted to a `*>` comment instead,
    same as an unknowable count -- the fix does not attempt to compute the
    new count (0 here), only to stop asserting the stale one."""
    result = parse_cobol(READ_LOOP_WITH_INLINE_CALL_SOURCE, filename="readloop.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = READ_LOOP_WITH_INLINE_CALL_SOURCE.splitlines()
    # the CALL is nested inside an IF, so its span -- and its key
    # eligibility -- only exists after annotate_nested_sites, as
    # cli/main.py:388 does before calling scaffold_cut.
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)

    bundle = FixtureBundle(
        bundle_version=1,
        program_name="READLOOP",
        seed=1,
        scenarios=[
            Scenario(
                name="happy path",
                entry="MAIN-PROCESS",
                fixtures=[
                    BoundaryFixture(
                        category="READ",
                        key="INV-FILE",
                        paragraph="READ-LOOP",
                        line=1,
                        direction="IN",
                        layout=[_field("INV-QTY")],
                        sequence=[{"INV-QTY": "5"}, {"INV-QTY": "12"}],
                        status={"WS-STATUS": "00"},
                    ),
                    BoundaryFixture(
                        category="CALL",
                        key="LOGROW",
                        paragraph="READ-LOOP",
                        line=2,
                        direction="OUT",
                        layout=[_field("INV-QTY")],
                        sequence=[{"INV-QTY": "5"}],
                        status={},
                    ),
                ],
                expectations=[
                    Expectation(kind="call_count", ref="READ:INV-FILE", value=3),
                    Expectation(kind="call_count", ref="CALL:LOGROW", value=2),
                ],
            )
        ],
    )

    without_placeholder = scaffold_cut("READLOOP", surface, bundle)
    assert "VERIFY READ INV-FILE WAS CALLED 3 TIMES" in without_placeholder
    assert 'VERIFY CALL "LOGROW" WAS CALLED 2 TIMES' in without_placeholder

    with_placeholder = scaffold_cut(
        "READLOOP",
        surface,
        bundle,
        placeholder_keys=frozenset({("READ", "INV-FILE")}),
    )
    # the downgraded boundary's own count is corrected, as already covered
    # by test_placeholder_downgraded_read_gets_a_corrected_verify_count
    assert "VERIFY READ INV-FILE WAS CALLED 1 TIMES" in with_placeholder
    # the downstream CALL, only reachable inside the now-shortened loop,
    # is demoted too -- not left pinned to the stale bundle count
    assert 'VERIFY CALL "LOGROW" WAS CALLED 2 TIMES' not in with_placeholder
    assert '*> VERIFY CALL "LOGROW" WAS CALLED' in with_placeholder
    assert "same paragraph as READ:INV-FILE" in with_placeholder
    # the demoted output still round-trips
    suite = parse_cut(with_placeholder)
    assert len(suite.test_cases) == 1


# --- unverified-scenario notes (cobol-parser's Scenario.verification) --------


def _scenario_with_verification(verification):
    return Scenario(
        name="CHECK-QTY: THEN",
        intent="targets branch arm",
        entry="MAIN-PROCESS",
        fixtures=[],
        expectations=[],
        verification=verification,
    )


def _bundle_of(scenario):
    return FixtureBundle(
        bundle_version=1, program_name="P", seed=7, scenarios=[scenario]
    )


def test_unverified_scenario_gets_a_comment_naming_every_reason():
    """A scenario name is a claim. cobol-parser now says whether its own
    generated data actually reaches the branch; surfacing an `unverified`
    verdict here means the reader sees the caveat next to the TESTCASE
    instead of having to run the case under `--trace` to find out."""
    surface, _ = _surface_and_bundle(ORDRPROC_SOURCE, "ordrproc.cbl")
    scenario = _scenario_with_verification(
        {
            "status": "unverified",
            "fields": [
                {
                    "field": "WS-AMOUNT",
                    "status": "violated",
                    "detail": "none of the 3 generated value(s) satisfy it",
                },
                {"field": "WS-RATE", "status": "satisfied", "detail": "row(s) 0"},
            ],
            "gaps": ["enclosing arm P@10:5/THEN has no modeled constraints"],
        }
    )
    text = scaffold_cut("ORDRPROC", surface, _bundle_of(scenario))
    assert "*> UNVERIFIED: this scenario's generated data was not confirmed" in text
    assert "WS-AMOUNT: none of the 3 generated value(s) satisfy it" in text
    assert "enclosing arm P@10:5/THEN has no modeled constraints" in text
    # A field that DID verify is not listed as a reason.
    assert "WS-RATE" not in text


def test_a_verified_scenario_gets_no_note():
    """A note on every case would be noise, and would train people to skip
    the ones that matter."""
    surface, _ = _surface_and_bundle(ORDRPROC_SOURCE, "ordrproc.cbl")
    scenario = _scenario_with_verification({"status": "verified", "fields": []})
    text = scaffold_cut("ORDRPROC", surface, _bundle_of(scenario))
    assert "UNVERIFIED" not in text


def test_a_bundle_without_the_verification_key_is_still_read():
    """An older bundle is still a valid v1 bundle -- absent means "no verdict
    was recorded", never "unverified"."""
    surface, _ = _surface_and_bundle(ORDRPROC_SOURCE, "ordrproc.cbl")
    text = scaffold_cut(
        "ORDRPROC", surface, _bundle_of(_scenario_with_verification(None))
    )
    assert "UNVERIFIED" not in text


def test_the_unverified_note_does_not_break_parsing_or_linting():
    from mockymock.analysis.refusal import check_test_case

    surface, bundle = _surface_and_bundle(ORDRPROC_SOURCE, "ordrproc.cbl")
    bundle.scenarios[0].verification = {
        "status": "unverified",
        "fields": [{"field": "WS-AMOUNT", "status": "absent", "detail": "no fixture"}],
        "gaps": [],
    }
    text = scaffold_cut("ORDRPROC", surface, bundle)
    result = parse_cobol(ORDRPROC_SOURCE, filename="ordrproc.cbl")
    suite = parse_cut(text)
    for case in suite.test_cases:
        assert check_test_case(surface, result.ast, case) == [], case.name


def test_with_data_never_moves_into_a_pointer_or_index_argument(tmp_path):
    """A CALL argument declared USAGE PROCEDURE-POINTER / POINTER / INDEX
    came back from the bundle as a numeric field holding "0", and the mock
    body said `MOVE 0 TO WS-PROC-PTR` -- which cobc rejects ("invalid MOVE
    statement"), so the generated suite never compiled (LESERV's
    CEEHDLR handler registration). A pointer is reset with SET ... TO NULL
    (as the WORKING-STORAGE reset does); an INDEX item gets no line."""
    from mockymock.cli.main import main

    source = tmp_path / "PTRPGM.cbl"
    source.write_text(
        """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PTRPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PROC-PTR   USAGE PROCEDURE-POINTER.
       01 WS-DATA-PTR   USAGE POINTER.
       01 WS-IDX        USAGE INDEX.
       01 WS-RC         PIC S9(4) COMP VALUE 0.
       01 WS-OUT        PIC X(10) VALUE SPACES.
       PROCEDURE DIVISION.
       0000-MAIN.
           SET WS-DATA-PTR TO ADDRESS OF WS-OUT
           CALL "REGPGM" USING WS-PROC-PTR WS-DATA-PTR WS-IDX WS-RC
           IF WS-RC = 0
              MOVE "OK" TO WS-OUT
           END-IF
           GOBACK.
""",
        encoding="utf-8",
    )
    out = tmp_path / "PTRPGM.cut"
    assert (
        main(["generate", str(source), "--with-data", "--seed", "1", "-o", str(out)])
        == 0
    )
    text = out.read_text(encoding="utf-8")
    assert "MOVE 0 TO WS-PROC-PTR" not in text
    assert "MOVE 0 TO WS-IDX" not in text
    assert "TO WS-IDX" not in text
    assert "SET WS-PROC-PTR TO NULL" in text
    assert "MOVE 0 TO WS-RC" in text
