"""Dynamic CALL mocking: a `CALL identifier` site is keyed by the
identifier name and mocked/verified with the bare-word form
(`MOCK CALL WS-PGM-NAME`), while quoted keys keep meaning static call
literals. See docs/2026-07-06-dynamic-call-mocks-design.md."""

import pytest
from cobolparser import parse_cobol
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.call import CallStatement

from mockymock.analysis.mock_surface import (
    CallKind,
    MockSurface,
    _classify_statement,
    analyze,
)
from mockymock.analysis.refusal import check_test_case
from mockymock.dsl.generator import scaffold_cut
from mockymock.dsl.model import (
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
    VerifyDirective,
)
from mockymock.dsl.parser import CutParseError, parse_cut
from mockymock.splicer.driver import build_driver
from mockymock.splicer.injector import build_site_dispatch
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

DYNAMIC_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNPGM.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PGM-NAME        PIC X(8) VALUE "DISCRATE".
       01  WS-AMOUNT          PIC 9(5)V99.

       PROCEDURE DIVISION.
       DYNAMIC-PARAGRAPH.
           CALL WS-PGM-NAME USING WS-AMOUNT.

       STATIC-PARAGRAPH.
           CALL "DISCRATE" USING WS-AMOUNT.
"""

NESTED_DYNAMIC_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTDYN.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X VALUE "Y".
       01  WS-PGM-NAME        PIC X(8) VALUE "DISCRATE".
       01  WS-AMOUNT          PIC 9(5)V99.

       PROCEDURE DIVISION.
       START-HERE.
           IF WS-FLAG = "Y"
               CALL WS-PGM-NAME USING WS-AMOUNT
           END-IF.
"""


def _surface_and_ast(source=DYNAMIC_SOURCE):
    result = parse_cobol(source, filename="dyn.cbl")
    assert result.success, result.errors
    return analyze(result.ast), result.ast


def _dynamic_site(surface):
    sites = [s for s in surface.boundary_sites if s.category is MockCategory.DYNCALL]
    assert len(sites) == 1
    return sites[0]


# --- .cut grammar ---------------------------------------------------------

DYN_CUT = """\
TESTSUITE "dyn"
TESTCASE "c"
    MOCK CALL ws-pgm-name
        MOVE 0 TO WS-AMOUNT
    END-MOCK
    PERFORM DYNAMIC-PARAGRAPH
    VERIFY CALL WS-PGM-NAME WAS CALLED 2 TIMES
"""


def test_bare_mock_call_parses_as_dynamic_with_uppercased_key():
    mock = parse_cut(DYN_CUT).test_cases[0].mocks[0]
    assert mock.category is MockCategory.DYNCALL
    assert mock.key == "WS-PGM-NAME"
    assert mock.body_lines == ["MOVE 0 TO WS-AMOUNT"]


def test_bare_verify_call_parses_as_dynamic():
    verification = parse_cut(DYN_CUT).test_cases[0].verifications[0]
    assert verification.category is MockCategory.DYNCALL
    assert verification.key == "WS-PGM-NAME"
    assert verification.expectation == "2 TIMES"


def test_quoted_mock_call_stays_static():
    cut = 'TESTSUITE "x"\nTESTCASE "y"\n    MOCK CALL "PGMA"\n    END-MOCK\n    PERFORM p\n'
    mock = parse_cut(cut).test_cases[0].mocks[0]
    assert mock.category is MockCategory.CALL
    assert mock.key == "PGMA"


def test_bare_mock_mq_is_still_rejected():
    with pytest.raises(CutParseError):
        parse_cut(
            'TESTSUITE "x"\nTESTCASE "y"\n    MOCK MQ MQPUT\n    END-MOCK\n    PERFORM p\n'
        )


# --- model cosmetics ------------------------------------------------------


def test_dyncall_describe_uses_cut_syntax():
    assert MockDirective(MockCategory.DYNCALL, "WS-PGM-NAME").describe() == (
        "CALL WS-PGM-NAME"
    )


def test_dyncall_keyword_is_call():
    assert MockCategory.DYNCALL.keyword == "CALL"
    assert MockCategory.READ.keyword == "READ"
    assert MockCategory.CALL.keyword == "CALL"


# --- tally naming ---------------------------------------------------------


def test_dyncall_tally_name_is_prefixed_and_distinct_from_static():
    suite = MockTestSuite(
        name="s",
        test_cases=[
            MockTestCase(
                name="c",
                mocks=[
                    MockDirective(MockCategory.DYNCALL, "WS-PGM-NAME"),
                    MockDirective(MockCategory.CALL, "WS-PGM-NAME"),
                ],
                perform_target="P",
            )
        ],
    )
    registry = TallyRegistry(suite)
    dynamic = registry.name(MockCategory.DYNCALL, "WS-PGM-NAME")
    static = registry.name(MockCategory.CALL, "WS-PGM-NAME")
    assert dynamic == "UT-CALL-WS-PGM-NAME-TALLY"
    assert static == "UT-WS-PGM-NAME-TALLY"
    assert dynamic != static


# --- mock surface ---------------------------------------------------------


def test_dynamic_call_site_is_mockable_and_keyed_by_identifier():
    surface, _ = _surface_and_ast()
    site = _dynamic_site(surface)
    assert site.label == "dynamic CALL"
    assert site.keys == ("WS-PGM-NAME",)
    assert site.paragraph_name == "DYNAMIC-PARAGRAPH"


def test_dynamic_call_still_recorded_as_dynamic_call_site():
    surface, _ = _surface_and_ast()
    assert len(surface.dynamic_call_sites()) == 1
    assert surface.dynamic_call_sites()[0].kind is CallKind.DYNAMIC


def test_identifier_less_dynamic_call_stays_unmockable():
    """Fail closed: if cobolparser could not capture the identifier the
    site keeps category None and the DYNAMIC_CALL refusal fires."""
    statement = CallStatement(SourceLocation(line=1, column=1))
    statement.set_called_program("", is_dynamic=True)
    surface = MockSurface()
    _classify_statement(statement, "P", surface, nested=False)
    (site,) = surface.boundary_sites
    assert site.category is None
    assert site.label == "dynamic CALL"


# --- refusal gate ---------------------------------------------------------


def test_unresolvable_dynamic_call_identifier_produces_dynamic_call_refusal():
    """Fail closed, all the way through the gate: when cobolparser cannot
    capture a dynamic CALL's target identifier at all (category None,
    see test_identifier_less_dynamic_call_stays_unmockable above), the
    site has no .cut syntax that could ever cover it -- MOCK CALL needs a
    key -- so it must refuse with DYNAMIC_CALL specifically, not silently
    pass and not fall through as the ordinary UNMOCKED_CALL an unmocked
    but *resolvable* dynamic call gets (see the mocked WS-PGM-NAME call
    below, which passes clean)."""
    surface, ast = _surface_and_ast()
    statement = CallStatement(SourceLocation(line=1, column=1))
    statement.set_called_program("", is_dynamic=True)
    _classify_statement(statement, "DYNAMIC-PARAGRAPH", surface, nested=False)

    case = MockTestCase(
        name="c",
        mocks=[MockDirective(MockCategory.DYNCALL, "WS-PGM-NAME")],
        perform_target="DYNAMIC-PARAGRAPH",
    )
    reasons = check_test_case(surface, ast, case)
    assert [r.code for r in reasons] == ["DYNAMIC_CALL"]


def test_mocked_dynamic_call_passes():
    surface, ast = _surface_and_ast()
    case = MockTestCase(
        name="c",
        mocks=[MockDirective(MockCategory.DYNCALL, "WS-PGM-NAME")],
        perform_target="DYNAMIC-PARAGRAPH",
    )
    assert check_test_case(surface, ast, case) == []


def test_unmocked_dynamic_call_refuses_unmocked_call():
    surface, ast = _surface_and_ast()
    case = MockTestCase(name="c", mocks=[], perform_target="DYNAMIC-PARAGRAPH")
    reasons = check_test_case(surface, ast, case)
    assert [r.code for r in reasons] == ["UNMOCKED_CALL"]
    assert "dynamic CALL" in reasons[0].message
    assert "WS-PGM-NAME" in reasons[0].message


def test_quoted_directive_never_matches_a_dynamic_site():
    """MOCK CALL "WS-PGM-NAME" means a static literal; it must not match a
    dynamic site calling through the WS-PGM-NAME identifier."""
    surface, ast = _surface_and_ast()
    case = MockTestCase(
        name="c",
        mocks=[MockDirective(MockCategory.CALL, "WS-PGM-NAME")],
        perform_target="DYNAMIC-PARAGRAPH",
    )
    codes = {r.code for r in check_test_case(surface, ast, case)}
    assert codes == {"UNMOCKED_CALL", "UNMATCHED_MOCK"}


def test_bare_directive_never_matches_a_static_site():
    surface, ast = _surface_and_ast()
    case = MockTestCase(
        name="c",
        mocks=[MockDirective(MockCategory.DYNCALL, "DISCRATE")],
        perform_target="STATIC-PARAGRAPH",
    )
    codes = {r.code for r in check_test_case(surface, ast, case)}
    assert codes == {"UNMOCKED_CALL", "UNMATCHED_MOCK"}


def test_verify_dyncall_with_matching_mock_is_declared():
    surface, ast = _surface_and_ast()
    case = MockTestCase(
        name="c",
        mocks=[MockDirective(MockCategory.DYNCALL, "WS-PGM-NAME")],
        perform_target="DYNAMIC-PARAGRAPH",
        verifications=[VerifyDirective(MockCategory.DYNCALL, "WS-PGM-NAME", "ONCE")],
    )
    assert check_test_case(surface, ast, case) == []


# --- nested dynamic calls -------------------------------------------------


def test_nested_dynamic_call_gets_a_validated_span():
    from cobolparser.preprocess import normalize_fixed_format

    result = parse_cobol(NESTED_DYNAMIC_SOURCE, filename="nestdyn.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(NESTED_DYNAMIC_SOURCE.splitlines()).splitlines()
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    site = _dynamic_site(surface)
    assert site.nested
    assert site.unspliceable_reason is None
    assert site.span is not None
    start, end = site.span
    assert "CALL WS-PGM-NAME" in lines[start - 1]
    # END-IF stays outside the span
    assert all("END-IF" not in lines[i - 1] for i in range(start, end + 1))


# --- generator ------------------------------------------------------------


def test_scaffold_covers_dynamic_call_with_bare_key():
    surface, _ = _surface_and_ast()
    scaffold = scaffold_cut("DYNPGM", surface)
    assert "MOCK CALL WS-PGM-NAME" in scaffold
    assert "MOVE 0 TO RETURN-CODE" in scaffold
    assert 'MOCK CALL "WS-PGM-NAME"' not in scaffold


# --- codegen --------------------------------------------------------------


def _dyn_suite():
    return MockTestSuite(
        name="dyn",
        test_cases=[
            MockTestCase(
                name="c",
                mocks=[
                    MockDirective(
                        MockCategory.DYNCALL,
                        "WS-PGM-NAME",
                        body_lines=["MOVE 0 TO WS-AMOUNT"],
                    )
                ],
                perform_target="DYNAMIC-PARAGRAPH",
                verifications=[
                    VerifyDirective(MockCategory.DYNCALL, "WS-PGM-NAME", "ONCE")
                ],
            )
        ],
    )


def test_site_dispatch_tallies_and_runs_the_mock_body():
    surface, _ = _surface_and_ast()
    suite = _dyn_suite()
    lines = build_site_dispatch(_dynamic_site(surface), suite, TallyRegistry(suite))
    text = "\n".join(lines)
    assert 'WHEN "001"' in text
    assert "ADD 1 TO UT-CALL-WS-PGM-NAME-TALLY" in text
    assert "MOVE 0 TO WS-AMOUNT" in text


def test_driver_verify_message_prints_call_not_dyncall():
    suite = _dyn_suite()
    artifact = build_driver(suite, [], TallyRegistry(suite))
    text = "\n".join(artifact.procedure_lines)
    assert "VERIFY CALL WS-PGM-NAME WAS CALLED" in text
    assert "DYNCALL" not in text
