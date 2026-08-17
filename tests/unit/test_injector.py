"""Unit tests for the mock injector (per-site dispatch, v2)."""

import pytest
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.call import CallStatement

from mockymock.analysis.mock_surface import BoundarySite
from mockymock.dsl.model import (
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
)
from mockymock.splicer.injector import (
    build_chain_check,
    build_exec_trap,
    build_goto_exit_replacement,
    build_rows_block,
    build_site_dispatch,
    build_terminator_neutralization,
)
from mockymock.splicer.naming import TallyRegistry


def _site(
    category=MockCategory.CALL, label="CALL", keys=("DISCRATE",), match_text=None
):
    return BoundarySite(
        category=category,
        label=label,
        keys=keys,
        match_text=match_text,
        paragraph_name="P",
        line=10,
        nested=False,
        statement=object(),
    )


def _call_site(using_names, key="DISCRATE"):
    """A BoundarySite whose .statement is a real CallStatement with the
    given USING parameter names, in order -- what CAPTURE codegen reads."""
    statement = CallStatement(SourceLocation(line=10, column=1))
    statement.set_called_program(key)
    for name in using_names:
        statement.add_using_parameter(name)
    return BoundarySite(
        category=MockCategory.CALL,
        label="CALL",
        keys=(key,),
        match_text=None,
        paragraph_name="P",
        line=10,
        nested=False,
        statement=statement,
    )


def _suite() -> MockTestSuite:
    case_one = MockTestCase(name="10% discount")
    case_one.mocks.append(
        MockDirective(
            MockCategory.CALL, "DISCRATE", body_lines=["MOVE 0.10 TO WS-DISCOUNT-PCT"]
        )
    )

    case_two = MockTestCase(name="Zero discount")
    case_two.mocks.append(
        MockDirective(
            MockCategory.CALL, "DISCRATE", body_lines=["MOVE 0.00 TO WS-DISCOUNT-PCT"]
        )
    )

    return MockTestSuite(name="ORDRPROC", test_cases=[case_one, case_two])


def _dispatch(suite, site=None):
    return build_site_dispatch(site or _site(), suite, TallyRegistry(suite))


def test_dispatch_increments_tally_inside_when_branch():
    lines = _dispatch(_suite())
    when_001 = lines.index('               WHEN "001"')
    assert lines[when_001 + 1].strip() == "ADD 1 TO UT-DISCRATE-TALLY"


def test_dispatch_has_one_when_branch_per_test_case():
    joined = "\n".join(_dispatch(_suite()))
    assert 'WHEN "001"' in joined
    assert 'WHEN "002"' in joined
    assert "MOVE 0.10 TO WS-DISCOUNT-PCT" in joined
    assert "MOVE 0.00 TO WS-DISCOUNT-PCT" in joined


def test_dispatch_has_when_other_error_fallback():
    joined = "\n".join(_dispatch(_suite()))
    assert "WHEN OTHER" in joined
    assert "CALL boundary (line 10) reached" in joined
    assert "ADD 1 TO UT-FAIL-COUNT" in joined


def test_dispatch_excludes_test_cases_that_dont_mock_this_site():
    suite = _suite()
    suite.test_cases.insert(0, MockTestCase(name="unrelated"))
    joined = "\n".join(_dispatch(suite))
    assert 'WHEN "001"' not in joined
    assert 'WHEN "002"' in joined
    assert 'WHEN "003"' in joined


def test_same_site_matched_via_different_keys_credits_each_cases_tally():
    """Case 1 mocks OPEN IN-FILE, case 2 mocks OPEN OUT-FILE; both match the
    one OPEN statement, and each WHEN branch increments its own tally."""
    site = _site(MockCategory.OPEN, "OPEN", keys=("IN-FILE", "OUT-FILE"))
    case_one = MockTestCase(
        name="a", mocks=[MockDirective(MockCategory.OPEN, "IN-FILE")]
    )
    case_two = MockTestCase(
        name="b", mocks=[MockDirective(MockCategory.OPEN, "OUT-FILE")]
    )
    suite = MockTestSuite(name="S", test_cases=[case_one, case_two])
    joined = "\n".join(_dispatch(suite, site))
    assert "ADD 1 TO UT-OPEN-IN-FILE-TALLY" in joined
    assert "ADD 1 TO UT-OPEN-OUT-FILE-TALLY" in joined


def test_sql_site_dispatch_matches_by_prefix():
    site = _site(
        MockCategory.SQL, "SQL", keys=(), match_text="UPDATE ORDERS SET STATUS = 'Y'"
    )
    case = MockTestCase(
        name="sql",
        mocks=[MockDirective(MockCategory.SQL, "UPDATE ORDERS", ["MOVE 0 TO SQLCODE"])],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    joined = "\n".join(_dispatch(suite, site))
    assert "MOVE 0 TO SQLCODE" in joined
    assert "ADD 1 TO UT-SQL-UPDATE-ORDERS-TALLY" in joined


def test_ambiguous_match_raises():
    site = _site(MockCategory.OPEN, "OPEN", keys=("IN-FILE", "OUT-FILE"))
    case = MockTestCase(
        name="a",
        mocks=[
            MockDirective(MockCategory.OPEN, "IN-FILE"),
            MockDirective(MockCategory.OPEN, "OUT-FILE"),
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    with pytest.raises(ValueError, match="AMBIGUOUS_MOCK"):
        _dispatch(suite, site)


def test_exec_trap_displays_and_fails():
    lines = build_exec_trap("SQL", 42)
    joined = "\n".join(lines)
    assert "unmocked EXEC SQL reached (line 42)" in joined
    assert "ADD 1 TO UT-FAIL-COUNT" in joined


def test_terminator_neutralization_sets_flag_and_exits_paragraph():
    lines = build_terminator_neutralization()
    assert lines == [
        '           MOVE "Y" TO UT-EARLY-EXIT',
        "           EXIT PARAGRAPH",
    ]


def test_terminator_neutralization_with_section_exit_kind_exits_section():
    lines = build_terminator_neutralization("SECTION")
    assert lines == [
        '           MOVE "Y" TO UT-EARLY-EXIT',
        "           EXIT SECTION",
    ]


def test_chain_check_exits_paragraph_when_flag_set():
    lines = build_chain_check()
    assert lines == [
        '           IF UT-EARLY-EXIT = "Y"',
        "               EXIT PARAGRAPH",
        "           END-IF",
    ]


def test_goto_exit_replacement_exits_paragraph_no_flag():
    lines = build_goto_exit_replacement()
    assert lines == ["           EXIT PARAGRAPH"]


def test_goto_exit_replacement_with_section_exit_kind_exits_section():
    lines = build_goto_exit_replacement("SECTION")
    assert lines == ["           EXIT SECTION"]


def test_rows_block_codegens_indexed_when_branches_and_exhaustion():
    lines = build_rows_block(
        "UT-SQL-FETCH-EMP-CURSOR-TALLY",
        [
            [("EMP-NAME", '"SMITH"'), ("EMP-ID", "100")],
            [("EMP-NAME", '"JONES"'), ("EMP-ID", "101")],
        ],
        row_suffix_moves=["MOVE 0 TO SQLCODE"],
        exhausted_moves=["MOVE 100 TO SQLCODE"],
    )
    assert lines == [
        "EVALUATE TRUE",
        "    WHEN UT-SQL-FETCH-EMP-CURSOR-TALLY = 1",
        '        MOVE "SMITH" TO EMP-NAME',
        "        MOVE 100 TO EMP-ID",
        "        MOVE 0 TO SQLCODE",
        "    WHEN UT-SQL-FETCH-EMP-CURSOR-TALLY = 2",
        '        MOVE "JONES" TO EMP-NAME',
        "        MOVE 101 TO EMP-ID",
        "        MOVE 0 TO SQLCODE",
        "    WHEN OTHER",
        "        MOVE 100 TO SQLCODE",
        "END-EVALUATE",
    ]


def test_read_rows_block_uses_status_field_terminal():
    lines = build_rows_block(
        "UT-TALLY-1",
        [[("ORDER-QTY", "50")], [("ORDER-QTY", "75")]],
        row_suffix_moves=[],
        exhausted_moves=['MOVE "10" TO WS-ORDER-STATUS'],
    )
    assert lines == [
        "EVALUATE TRUE",
        "    WHEN UT-TALLY-1 = 1",
        "        MOVE 50 TO ORDER-QTY",
        "    WHEN UT-TALLY-1 = 2",
        "        MOVE 75 TO ORDER-QTY",
        "    WHEN OTHER",
        '        MOVE "10" TO WS-ORDER-STATUS',
        "END-EVALUATE",
    ]


def test_sql_rows_block_unchanged():
    lines = build_rows_block(
        "UT-TALLY-1",
        [[("X", "1")]],
        row_suffix_moves=["MOVE 0 TO SQLCODE"],
        exhausted_moves=["MOVE 100 TO SQLCODE"],
    )
    assert "        MOVE 0 TO SQLCODE" in lines
    assert lines[-2] == "        MOVE 100 TO SQLCODE"


def test_dispatch_splices_rows_block_using_resolved_tally_name():
    site = _site(MockCategory.SQL, "SQL", keys=(), match_text="FETCH EMP-CURSOR")
    case = MockTestCase(
        name="cursor",
        mocks=[
            MockDirective(
                MockCategory.SQL,
                "FETCH EMP-CURSOR",
                rows=[[("EMP-NAME", '"SMITH"')]],
            )
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    joined = "\n".join(_dispatch(suite, site))
    assert "ADD 1 TO UT-SQL-FETCH-EMP-CURSOR-TALLY" in joined
    assert "EVALUATE TRUE" in joined
    assert "WHEN UT-SQL-FETCH-EMP-CURSOR-TALLY = 1" in joined
    assert 'MOVE "SMITH" TO EMP-NAME' in joined
    assert "WHEN OTHER" in joined
    assert "MOVE 100 TO SQLCODE" in joined


def test_dispatch_splices_read_rows_block_using_default_status_terminal():
    """No TERMINAL group, but the file declares a FILE STATUS field: the
    exhaustion branch defaults to MOVE "10" TO <field> and never touches
    SQLCODE."""
    site = _site(MockCategory.READ, "READ", keys=("ORDER-FILE",))
    case = MockTestCase(
        name="rows",
        mocks=[
            MockDirective(
                MockCategory.READ,
                "ORDER-FILE",
                rows=[[("ORDER-QTY", "50")]],
            )
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    lines = build_site_dispatch(
        site, suite, TallyRegistry(suite), {"ORDER-FILE": "WS-ORDER-STATUS"}
    )
    joined = "\n".join(lines)
    assert "ADD 1 TO UT-READ-ORDER-FILE-TALLY" in joined
    assert "MOVE 50 TO ORDER-QTY" in joined
    assert 'MOVE "10" TO WS-ORDER-STATUS' in joined
    assert "SQLCODE" not in joined


def test_dispatch_splices_read_rows_block_using_explicit_terminal_row():
    """A TERMINAL group wins over the status-field default, even when the
    file declares no FILE STATUS field at all."""
    site = _site(MockCategory.READ, "READ", keys=("ORDER-FILE",))
    directive = MockDirective(
        MockCategory.READ,
        "ORDER-FILE",
        rows=[[("ORDER-QTY", "50")]],
    )
    directive.terminal_row = [("WS-EOF-FLAG", '"Y"')]
    case = MockTestCase(name="rows", mocks=[directive])
    suite = MockTestSuite(name="S", test_cases=[case])
    lines = build_site_dispatch(site, suite, TallyRegistry(suite), {})
    joined = "\n".join(lines)
    assert 'MOVE "Y" TO WS-EOF-FLAG' in joined
    assert "SQLCODE" not in joined


def test_dispatch_read_rows_exhausted_branch_prepends_default_status_before_terminal_moves():
    """Fix (post-PR #46 review, Task 3): a TERMINAL group that sets an EOF
    flag but never mentions the FILE STATUS field must not silently leave
    that field at whatever the default-success MOVE "00" set on the call
    that triggered WHEN OTHER. The exhausted branch must still carry the
    implicit MOVE "10" TO <status field>, emitted BEFORE the TERMINAL
    group's own MOVEs -- same "implicit default, explicit override"
    ordering the plain FILE-STATUS default/override pair already uses."""
    site = _site(MockCategory.READ, "READ", keys=("ORDER-FILE",))
    directive = MockDirective(
        MockCategory.READ,
        "ORDER-FILE",
        rows=[[("ORDER-QTY", "50")]],
    )
    directive.terminal_row = [("WS-EOF-FLAG", '"Y"')]
    case = MockTestCase(name="rows", mocks=[directive])
    suite = MockTestSuite(name="S", test_cases=[case])
    lines = build_site_dispatch(
        site, suite, TallyRegistry(suite), {"ORDER-FILE": "WS-ORDER-STATUS"}
    )

    # Two "WHEN OTHER" branches exist: the nested one closing the rows
    # EVALUATE (rows exhausted) and the outer catch-all closing the
    # per-test-case UT-CURRENT-CASE EVALUATE (unmocked case). Isolate the
    # nested one so assertions can't accidentally match the outer branch.
    when_other_indices = [
        i for i, line in enumerate(lines) if line.strip() == "WHEN OTHER"
    ]
    assert len(when_other_indices) == 2
    exhausted = lines[when_other_indices[0] : when_other_indices[1]]
    exhausted_text = "\n".join(exhausted)

    assert 'MOVE "10" TO WS-ORDER-STATUS' in exhausted_text
    assert 'MOVE "Y" TO WS-EOF-FLAG' in exhausted_text

    default_idx = next(
        i for i, line in enumerate(exhausted) if '"10" TO WS-ORDER-STATUS' in line
    )
    terminal_idx = next(i for i, line in enumerate(exhausted) if "WS-EOF-FLAG" in line)
    assert default_idx < terminal_idx


def test_dispatch_read_rows_terminal_move_to_status_field_survives_after_default():
    """When TERMINAL DOES target the status field itself (a custom two-
    digit code), both the implicit default and the author's own MOVE
    appear in the exhausted branch, with the author's value LAST -- the
    same "later MOVE wins" ordering as the plain FILE-STATUS
    default/override pair a few lines above this dispatch block. Asserting
    both lines are present, in this order, is the ordering evidence a
    human (or a diff of the generated .cut) can check directly, since
    GnuCOBOL executes MOVEs top-to-bottom within one WHEN branch."""
    site = _site(MockCategory.READ, "READ", keys=("ORDER-FILE",))
    directive = MockDirective(
        MockCategory.READ,
        "ORDER-FILE",
        rows=[[("ORDER-QTY", "50")]],
    )
    directive.terminal_row = [("WS-ORDER-STATUS", '"92"')]
    case = MockTestCase(name="rows", mocks=[directive])
    suite = MockTestSuite(name="S", test_cases=[case])
    lines = build_site_dispatch(
        site, suite, TallyRegistry(suite), {"ORDER-FILE": "WS-ORDER-STATUS"}
    )

    when_other_indices = [
        i for i, line in enumerate(lines) if line.strip() == "WHEN OTHER"
    ]
    assert len(when_other_indices) == 2
    exhausted = lines[when_other_indices[0] : when_other_indices[1]]

    default_idx = next(
        i for i, line in enumerate(exhausted) if '"10" TO WS-ORDER-STATUS' in line
    )
    custom_idx = next(
        i for i, line in enumerate(exhausted) if '"92" TO WS-ORDER-STATUS' in line
    )
    assert default_idx < custom_idx


def test_dispatch_sql_rows_exhausted_branch_unaffected_by_read_terminal_fix():
    """SQL ROWS has no TERMINAL grammar at all -- its exhausted branch must
    stay exactly the fixed SQLCODE 100 MOVE, unaffected by the READ-only
    default-status-before-TERMINAL change above."""
    site = _site(MockCategory.SQL, "SQL", keys=(), match_text="FETCH EMP-CURSOR")
    case = MockTestCase(
        name="cursor",
        mocks=[
            MockDirective(
                MockCategory.SQL,
                "FETCH EMP-CURSOR",
                rows=[[("EMP-NAME", '"SMITH"')]],
            )
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    lines = build_site_dispatch(site, suite, TallyRegistry(suite), {})
    joined = "\n".join(lines)
    assert "MOVE 100 TO SQLCODE" in joined
    assert '"10"' not in joined


def test_dispatch_raises_for_read_rows_without_terminal_or_status_field():
    """Fail closed: this shape should have already been refused by
    refusal.check_test_case (UNRESOLVED_FILE_STATUS_TARGET); reaching the
    splicer means that gate was bypassed, so raise loudly rather than emit
    a READ loop with no way to terminate."""
    site = _site(MockCategory.READ, "READ", keys=("ORDER-FILE",))
    case = MockTestCase(
        name="rows",
        mocks=[
            MockDirective(
                MockCategory.READ,
                "ORDER-FILE",
                rows=[[("ORDER-QTY", "50")]],
            )
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    with pytest.raises(ValueError, match="UNRESOLVED_FILE_STATUS_TARGET"):
        build_site_dispatch(site, suite, TallyRegistry(suite), {})


def test_default_success_status_injected_when_file_declares_a_status_field():
    case = MockTestCase(name="c")
    case.mocks.append(MockDirective(MockCategory.OPEN, "INFILE"))
    suite = MockTestSuite(name="S", test_cases=[case])
    site = _site(category=MockCategory.OPEN, label="OPEN", keys=("INFILE",))
    lines = build_site_dispatch(
        site, suite, TallyRegistry(suite), {"INFILE": "WS-INFILE-STATUS"}
    )
    assert 'MOVE "00" TO WS-INFILE-STATUS' in "\n".join(lines)


def test_explicit_file_status_follows_the_default():
    case = MockTestCase(name="c")
    directive = MockDirective(MockCategory.OPEN, "INFILE")
    directive.file_status = "35"
    case.mocks.append(directive)
    suite = MockTestSuite(name="S", test_cases=[case])
    site = _site(category=MockCategory.OPEN, label="OPEN", keys=("INFILE",))
    lines = build_site_dispatch(
        site, suite, TallyRegistry(suite), {"INFILE": "WS-INFILE-STATUS"}
    )
    default_idx = next(
        i for i, line in enumerate(lines) if 'MOVE "00" TO WS-INFILE-STATUS' in line
    )
    override_idx = next(
        i for i, line in enumerate(lines) if 'MOVE "35" TO WS-INFILE-STATUS' in line
    )
    assert override_idx == default_idx + 1


def test_no_status_move_when_file_has_no_declared_field():
    case = MockTestCase(name="c")
    case.mocks.append(MockDirective(MockCategory.OPEN, "INFILE"))
    suite = MockTestSuite(name="S", test_cases=[case])
    site = _site(category=MockCategory.OPEN, label="OPEN", keys=("INFILE",))
    lines = build_site_dispatch(site, suite, TallyRegistry(suite), {})
    assert "STATUS" not in "\n".join(lines)


def test_no_status_move_for_a_category_outside_file_status_categories():
    case = MockTestCase(name="c")
    case.mocks.append(MockDirective(MockCategory.WRITE, "OUTREC"))
    suite = MockTestSuite(name="S", test_cases=[case])
    site = _site(category=MockCategory.WRITE, label="WRITE", keys=("OUTREC",))
    lines = build_site_dispatch(
        site, suite, TallyRegistry(suite), {"OUTREC": "WS-OUTREC-STATUS"}
    )
    assert "STATUS" not in "\n".join(lines)


def test_omitting_file_status_fields_keeps_todays_exact_output():
    lines_with_none = _dispatch(_suite())
    lines_with_empty = build_site_dispatch(
        _site(), _suite(), TallyRegistry(_suite()), {}
    )
    assert lines_with_none == lines_with_empty


# --- execution trace (docs/2026-07-21-debug-trace-design.md) ---------------


def test_dispatch_emits_mock_marker_in_trace_mode():
    """Mock firing order cannot come from the GnuCOBOL trace file -- these
    dispatch blocks are splicer-inserted, and the trace's line remap drops
    inserted lines by design. The marker carries it on stdout instead."""
    site = _site()
    lines = build_site_dispatch(site, _suite(), TallyRegistry(_suite()), trace=True)
    when_001 = lines.index('               WHEN "001"')
    assert lines[when_001 + 1].strip() == "ADD 1 TO UT-DISCRATE-TALLY"
    assert (
        lines[when_001 + 2].strip()
        == f'DISPLAY "__MOCKYMOCK__ MOCK: {site.label} DISCRATE"'
    )


def test_mock_marker_names_the_directive_key_not_just_the_verb():
    """site.label alone is a coarse verb, so two OPENs of different files
    would be indistinguishable in the firing timeline."""
    site = _site()
    lines = build_site_dispatch(site, _suite(), TallyRegistry(_suite()), trace=True)
    marker = next(line for line in lines if "__MOCKYMOCK__ MOCK:" in line)
    assert "DISCRATE" in marker


def test_dispatch_emits_one_marker_per_mocking_case():
    lines = build_site_dispatch(_site(), _suite(), TallyRegistry(_suite()), trace=True)
    assert sum(1 for line in lines if "__MOCKYMOCK__ MOCK:" in line) == 2


def test_dispatch_has_no_mock_marker_without_trace():
    """A normal run must stay byte-identical -- this is the whole reason
    the marker is gated on trace mode."""
    assert not any("__MOCKYMOCK__ MOCK:" in line for line in _dispatch(_suite()))


def _flow_suite() -> MockTestSuite:
    case = MockTestCase(name="skips the audit write")
    case.mocks.append(
        MockDirective(MockCategory.PARAGRAPH, "WRITE-AUDIT", body_lines=["CONTINUE"])
    )
    return MockTestSuite(name="ACCTPRG", test_cases=[case])


def test_flow_dispatch_emits_mock_marker_in_trace_mode():
    """A MOCK PARAGRAPH/SECTION is a declared mock too -- leaving it out
    would make the firing timeline quietly incomplete."""
    from mockymock.analysis.flow_mocks import FlowMockPlan
    from mockymock.splicer.injector import build_flow_dispatch

    suite = _flow_suite()
    plan = FlowMockPlan(
        category=MockCategory.PARAGRAPH,
        key="WRITE-AUDIT",
        header_line=20,
        real_name="WRITE-AUDIT-REAL",
    )

    lines = build_flow_dispatch(plan, suite, TallyRegistry(suite), trace=True)
    assert any('__MOCKYMOCK__ MOCK: PARAGRAPH WRITE-AUDIT"' in line for line in lines)

    plain = build_flow_dispatch(plan, suite, TallyRegistry(suite))
    assert not any("__MOCKYMOCK__ MOCK:" in line for line in plain)


# --- argument capture (docs/2026-08-11-argument-capture-design.md) -----------


def test_capture_emits_move_from_the_real_using_parameter_name():
    site = _call_site(["ORD-AMOUNT", "WS-DISCOUNT-PCT"])
    case = MockTestCase(
        name="capture",
        mocks=[
            MockDirective(
                MockCategory.CALL,
                "DISCRATE",
                body_lines=["MOVE 0.10 TO WS-DISCOUNT-PCT"],
                captures=[(1, "WS-CAPTURED-AMOUNT")],
            )
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    joined = "\n".join(_dispatch(suite, site))
    assert "MOVE ORD-AMOUNT TO WS-CAPTURED-AMOUNT" in joined


def test_capture_move_precedes_the_directives_own_body_lines():
    site = _call_site(["ORD-AMOUNT"])
    case = MockTestCase(
        name="capture",
        mocks=[
            MockDirective(
                MockCategory.CALL,
                "DISCRATE",
                body_lines=["MOVE 0.10 TO WS-DISCOUNT-PCT"],
                captures=[(1, "WS-CAPTURED-AMOUNT")],
            )
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    lines = _dispatch(suite, site)
    capture_index = next(i for i, ln in enumerate(lines) if "WS-CAPTURED-AMOUNT" in ln)
    body_index = next(
        i for i, ln in enumerate(lines) if "WS-DISCOUNT-PCT" in ln and "MOVE 0.10" in ln
    )
    assert capture_index < body_index


def test_multiple_captures_each_emit_their_own_move_in_declared_order():
    site = _call_site(["ORD-AMOUNT", "WS-DISCOUNT-PCT"])
    case = MockTestCase(
        name="capture",
        mocks=[
            MockDirective(
                MockCategory.CALL,
                "DISCRATE",
                captures=[(2, "WS-CAPTURED-PCT"), (1, "WS-CAPTURED-AMOUNT")],
            )
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    lines = _dispatch(suite, site)
    pct_index = next(i for i, ln in enumerate(lines) if "WS-CAPTURED-PCT" in ln)
    amount_index = next(i for i, ln in enumerate(lines) if "WS-CAPTURED-AMOUNT" in ln)
    assert "MOVE WS-DISCOUNT-PCT TO WS-CAPTURED-PCT" in lines[pct_index]
    assert "MOVE ORD-AMOUNT TO WS-CAPTURED-AMOUNT" in lines[amount_index]
    assert pct_index < amount_index


def test_directive_with_no_captures_emits_no_extra_move():
    """Zero-cost when absent: a directive with captures == [] (the
    default) must produce byte-for-byte the same dispatch as before this
    feature existed."""
    site = _call_site(["ORD-AMOUNT", "WS-DISCOUNT-PCT"])
    joined = "\n".join(_dispatch(_suite(), site))
    assert "CAPTURED" not in joined
