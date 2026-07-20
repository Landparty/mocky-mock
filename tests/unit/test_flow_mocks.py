"""Flow-target mocks (MOCK PARAGRAPH / MOCK SECTION): DSL parsing, tally
naming, per-case refusal-gate behavior (reachability exclusion, entry-point
overlap, UNMATCHED), the program-wide plan finder's fail-closed hazard
refusals, and the header-dispatch splice itself."""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.flow_mocks import (
    check_flow_mocks,
    find_flow_mock_plans,
    resolved_flow_targets,
)
from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import check_test_case, find_terminator_plans
from mockymock.dsl.model import MockCategory, MockDirective, MockTestCase
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import (
    annotate_nested_sites,
    collect_boundaries,
    collect_scope_map,
)

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FLOWDEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TOTAL       PIC 9(4) VALUE 0.
       01  WS-RC          PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           PERFORM CALC-TOTALS
           ADD 1 TO WS-TOTAL.
       CALC-TOTALS.
           CALL "RATECALC" USING WS-RC
           ADD 5 TO WS-TOTAL.
"""

SECTION_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECDEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TOTAL       PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN SECTION.
       MAIN-PROCESS.
           PERFORM REPORTING
           ADD 1 TO WS-TOTAL.
       REPORTING SECTION.
       RPT-HEADER.
           DISPLAY "HEADER".
       RPT-BODY.
           ADD 5 TO WS-TOTAL.
"""


def _prepared(source):
    result = parse_cobol(source, filename="test.cbl")
    assert result.success, (result.errors, result.warnings)
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    return result.ast, surface, lines, scope_map


def _case(perform_target, mocks, thru=None):
    return MockTestCase(
        name="case", mocks=mocks, perform_target=perform_target, perform_thru=thru
    )


def _paragraph_mock(key, body=()):
    return MockDirective(
        category=MockCategory.PARAGRAPH, key=key, body_lines=list(body)
    )


def _section_mock(key, body=()):
    return MockDirective(category=MockCategory.SECTION, key=key, body_lines=list(body))


class TestDslParsing:
    def test_mock_paragraph_and_verify_parse(self):
        suite = parse_cut(
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK PARAGRAPH calc-totals\n"
            "        MOVE 1 TO WS-X\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n"
            "    VERIFY PARAGRAPH CALC-TOTALS WAS PERFORMED ONCE\n"
        )
        directive = suite.test_cases[0].mocks[0]
        assert directive.category is MockCategory.PARAGRAPH
        assert directive.key == "CALC-TOTALS"  # bare keys are upper-cased
        assert directive.body_lines == ["MOVE 1 TO WS-X"]
        verification = suite.test_cases[0].verifications[0]
        assert verification.category is MockCategory.PARAGRAPH
        assert verification.key == "CALC-TOTALS"
        assert directive.describe() == "PARAGRAPH CALC-TOTALS"

    def test_mock_section_parses(self):
        suite = parse_cut(
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK SECTION REPORTING\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n"
            "    VERIFY SECTION REPORTING WAS CALLED NEVER\n"
        )
        directive = suite.test_cases[0].mocks[0]
        assert directive.category is MockCategory.SECTION
        assert directive.describe() == "SECTION REPORTING"

    def test_paragraph_and_section_keys_do_not_collide(self):
        suite = parse_cut(
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK PARAGRAPH X\n"
            "    END-MOCK\n"
            "    MOCK SECTION X\n"
            "    END-MOCK\n"
            "    PERFORM MAIN\n"
        )
        assert len(suite.test_cases[0].mocks) == 2

    def test_tally_names_are_category_prefixed(self):
        suite = parse_cut(
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK PARAGRAPH CALC\n"
            "    END-MOCK\n"
            "    MOCK SECTION RPT\n"
            "    END-MOCK\n"
            "    PERFORM MAIN\n"
        )
        registry = TallyRegistry(suite)
        assert (
            registry.name(MockCategory.PARAGRAPH, "CALC") == "UT-PARAGRAPH-CALC-TALLY"
        )
        assert registry.name(MockCategory.SECTION, "RPT") == "UT-SECTION-RPT-TALLY"


class TestResolution:
    def test_resolved_flow_targets_ignores_unknown_names(self):
        ast, _, _, _ = _prepared(SOURCE)
        case = _case(
            "MAIN-PROCESS", [_paragraph_mock("NOPE"), _paragraph_mock("CALC-TOTALS")]
        )
        paragraphs, sections = resolved_flow_targets(ast, case)
        assert paragraphs == {"CALC-TOTALS"}
        assert sections == set()

    def test_unknown_paragraph_refuses_unresolved(self):
        ast, _, lines, _ = _prepared(SOURCE)
        suite = parse_cut(
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK PARAGRAPH NOPE\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n"
        )
        reasons = check_flow_mocks(ast, suite, lines)
        assert [r.code for r in reasons] == ["UNRESOLVED_FLOW_MOCK_TARGET"]

    def test_section_name_mocked_as_paragraph_hints_other_kind(self):
        ast, _, lines, _ = _prepared(SECTION_SOURCE)
        suite = parse_cut(
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK PARAGRAPH REPORTING\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n"
        )
        reasons = check_flow_mocks(ast, suite, lines)
        assert reasons[0].code == "UNRESOLVED_FLOW_MOCK_TARGET"
        assert "MOCK SECTION" in reasons[0].message

    def test_paragraph_name_mocked_as_section_hints_other_kind(self):
        ast, _, lines, _ = _prepared(SOURCE)
        suite = parse_cut(
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK SECTION CALC-TOTALS\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n"
        )
        reasons = check_flow_mocks(ast, suite, lines)
        assert reasons[0].code == "UNRESOLVED_FLOW_MOCK_TARGET"
        assert "MOCK PARAGRAPH" in reasons[0].message


class TestPerCaseGate:
    def test_boundary_inside_mocked_paragraph_needs_no_mock(self):
        ast, surface, _, _ = _prepared(SOURCE)
        case = _case("MAIN-PROCESS", [_paragraph_mock("CALC-TOTALS")])
        assert check_test_case(surface, ast, case) == []

    def test_unmocked_call_still_refuses_without_the_flow_mock(self):
        ast, surface, _, _ = _prepared(SOURCE)
        case = _case("MAIN-PROCESS", [])
        codes = [r.code for r in check_test_case(surface, ast, case)]
        assert codes == ["UNMOCKED_CALL"]

    def test_unreachable_flow_mock_is_unmatched(self):
        ast, surface, _, _ = _prepared(SOURCE)
        # CALC-TOTALS itself reaches no PERFORM edge back to MAIN-PROCESS.
        case = _case(
            "CALC-TOTALS",
            [
                _paragraph_mock("MAIN-PROCESS"),
                MockDirective(category=MockCategory.CALL, key="RATECALC"),
            ],
        )
        codes = [r.code for r in check_test_case(surface, ast, case)]
        assert codes == ["UNMATCHED_MOCK"]

    def test_mocking_own_entry_point_refuses(self):
        ast, surface, _, _ = _prepared(SOURCE)
        case = _case("CALC-TOTALS", [_paragraph_mock("CALC-TOTALS")])
        codes = [r.code for r in check_test_case(surface, ast, case)]
        assert "UNSUPPORTED_FLOW_MOCK_TARGET" in codes

    def test_unresolved_flow_mock_not_double_reported_per_case(self):
        ast, surface, _, _ = _prepared(SOURCE)
        case = _case(
            "MAIN-PROCESS",
            [
                _paragraph_mock("NOPE"),
                MockDirective(category=MockCategory.CALL, key="RATECALC"),
            ],
        )
        codes = [r.code for r in check_test_case(surface, ast, case)]
        # UNRESOLVED_FLOW_MOCK_TARGET comes from check_flow_mocks; the
        # per-case gate must not bury it under a generic UNMATCHED_MOCK.
        assert codes == []

    def test_terminator_inside_mocked_paragraph_is_exempt_for_that_case(self):
        source = SOURCE.replace(
            '           CALL "RATECALC" USING WS-RC\n',
            '           CALL "RATECALC" USING WS-RC\n           STOP RUN\n',
        )
        ast, surface, lines, scope_map = _prepared(source)
        suite = parse_cut(
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK PARAGRAPH CALC-TOTALS\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n"
        )
        plans, reasons = find_terminator_plans(surface, ast, suite, scope_map, lines)
        assert plans == []
        assert reasons == []


class TestPlanHazards:
    def _plans_for(self, source, cut_text):
        ast, _, lines, _ = _prepared(source)
        suite = parse_cut(cut_text)
        return find_flow_mock_plans(ast, suite, lines)

    def test_clean_paragraph_target_gets_a_plan(self):
        plans, reasons = self._plans_for(
            SOURCE,
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK PARAGRAPH CALC-TOTALS\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n",
        )
        assert reasons == []
        (plan,) = plans
        assert plan.key == "CALC-TOTALS"
        assert plan.real_name == "UT-REAL-1-CALC-TOTALS"
        assert not plan.is_section

    def test_go_to_target_refuses(self):
        source = SOURCE.replace(
            "           ADD 1 TO WS-TOTAL.",
            "           GO TO CALC-TOTALS.",
        )
        plans, reasons = self._plans_for(
            source,
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK PARAGRAPH CALC-TOTALS\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n",
        )
        assert plans == []
        assert [r.code for r in reasons] == ["UNSUPPORTED_FLOW_MOCK_TARGET"]
        assert "GO TO" in reasons[0].message

    def test_thru_range_membership_refuses(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUDEMO.
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           PERFORM STEP-A THRU STEP-C.
       STEP-A.
           CONTINUE.
       STEP-B.
           CONTINUE.
       STEP-C.
           CONTINUE.
"""
        plans, reasons = self._plans_for(
            source,
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK PARAGRAPH STEP-B\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n",
        )
        assert plans == []
        assert [r.code for r in reasons] == ["UNSUPPORTED_FLOW_MOCK_TARGET"]
        assert "THRU" in reasons[0].message

    def test_driver_thru_range_membership_refuses(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUDEMO.
       PROCEDURE DIVISION.
       STEP-A.
           CONTINUE.
       STEP-B.
           CONTINUE.
       STEP-C.
           CONTINUE.
"""
        plans, reasons = self._plans_for(
            source,
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK PARAGRAPH STEP-B\n"
            "    END-MOCK\n"
            "    PERFORM STEP-A THRU STEP-C\n",
        )
        assert plans == []
        assert [r.code for r in reasons] == ["UNSUPPORTED_FLOW_MOCK_TARGET"]

    def test_paragraph_inside_performed_section_refuses(self):
        plans, reasons = self._plans_for(
            SECTION_SOURCE,
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK PARAGRAPH RPT-BODY\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n",
        )
        assert plans == []
        assert [r.code for r in reasons] == ["UNSUPPORTED_FLOW_MOCK_TARGET"]
        assert "REPORTING" in reasons[0].message

    def test_section_target_gets_a_plan(self):
        plans, reasons = self._plans_for(
            SECTION_SOURCE,
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK SECTION REPORTING\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n",
        )
        assert reasons == []
        (plan,) = plans
        assert plan.is_section
        assert plan.real_name == "UT-REAL-1-REPORTING"

    def test_one_line_paragraph_header_refuses_layout(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ONELINE.
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           PERFORM CALC-TOTALS.
       CALC-TOTALS. CONTINUE.
"""
        plans, reasons = self._plans_for(
            source,
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK PARAGRAPH CALC-TOTALS\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n",
        )
        assert plans == []
        assert [r.code for r in reasons] == ["UNSUPPORTED_FLOW_MOCK_TARGET"]
        assert "own" in reasons[0].message


class TestSplice:
    def test_paragraph_header_dispatch_shape(self):
        ast, surface, lines, scope_map = _prepared(SOURCE)
        suite = parse_cut(
            'TESTSUITE "s"\n'
            'TESTCASE "mocked"\n'
            "    MOCK PARAGRAPH CALC-TOTALS\n"
            "        MOVE 42 TO WS-TOTAL\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n"
            'TESTCASE "real"\n'
            '    MOCK CALL "RATECALC"\n'
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n"
        )
        plans, reasons = find_flow_mock_plans(ast, suite, lines)
        assert reasons == []
        out = splice_program(
            lines,
            collect_boundaries(ast),
            surface,
            suite,
            TallyRegistry(suite),
            (),
            plans,
        )
        text = "\n".join(out)
        # Original header commented; dispatch re-opens the paragraph.
        assert "      *> CALC-TOTALS." in text
        assert "       CALC-TOTALS." in text
        assert '               WHEN "001"' in text
        assert "                   ADD 1 TO UT-PARAGRAPH-CALC-TOTALS-TALLY" in text
        assert "                   MOVE 42 TO WS-TOTAL" in text
        assert "                   PERFORM UT-REAL-1-CALC-TOTALS" in text
        assert "       UT-REAL-1-CALC-TOTALS." in text
        # The relocated body still carries the CALL's own dispatch (case 2)
        # -- body lines never move, so the boundary splice stays valid.
        assert "ADD 1 TO UT-RATECALC-TALLY" in text
        # No doubled sentence terminator after the relocated header.
        assert "UT-REAL-1-CALC-TOTALS.." not in text

    def test_section_header_dispatch_shape(self):
        ast, surface, lines, _ = _prepared(SECTION_SOURCE)
        suite = parse_cut(
            'TESTSUITE "s"\n'
            'TESTCASE "c"\n'
            "    MOCK SECTION REPORTING\n"
            "        MOVE 90 TO WS-TOTAL\n"
            "    END-MOCK\n"
            "    PERFORM MAIN-PROCESS\n"
        )
        plans, reasons = find_flow_mock_plans(ast, suite, lines)
        assert reasons == []
        out = splice_program(
            lines,
            collect_boundaries(ast),
            surface,
            suite,
            TallyRegistry(suite),
            (),
            plans,
        )
        text = "\n".join(out)
        assert "      *> REPORTING SECTION." in text
        assert "       REPORTING SECTION." in text
        assert "                   PERFORM UT-REAL-1-REPORTING" in text
        assert "       UT-REAL-1-REPORTING SECTION." in text
        # The section's real paragraphs stay in place, under the relocated
        # section header.
        assert "RPT-HEADER." in text
        assert "RPT-BODY." in text
