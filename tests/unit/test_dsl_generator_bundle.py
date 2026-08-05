"""Unit tests for the bundle-driven half of `dsl.generator.scaffold_cut`
(`mockymock generate --with-data`, Phase 8 of the gen-fixtures initiative).
See docs/plans/2026-08-02-program-data-generation-implementation.md and
cobol-parser's docs/fixture-bundle-schema.md."""

import re
from pathlib import Path

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
