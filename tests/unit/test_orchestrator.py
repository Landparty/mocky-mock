"""Unit tests for the generalized splice orchestrator."""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.model import MockCategory, MockDirective, MockTestCase, MockTestSuite
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import collect_boundaries

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALLBOUND.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC             PIC X(20).

       WORKING-STORAGE SECTION.
       01  WS-EOF             PIC X VALUE "N".
       01  WS-CUST-ID         PIC 9(5).

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE.
           READ IN-FILE
               AT END MOVE "Y" TO WS-EOF
           END-READ.
           CLOSE IN-FILE.

       SQL-PARA.
           EXEC SQL
               UPDATE ORDERS SET STATUS = 'Y' WHERE ID = :WS-CUST-ID
           END-EXEC.

       UNREACHED-SQL.
           EXEC SQL
               DELETE FROM AUDIT WHERE ID = :WS-CUST-ID
           END-EXEC.

       CALL-PARA.
           CALL "DISCRATE" USING WS-CUST-ID.
"""


def _splice(suite):
    result = parse_cobol(SOURCE, filename="allbound.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    normalized = normalize_fixed_format(SOURCE.splitlines())
    lines = normalized.splitlines()
    boundaries = collect_boundaries(result.ast)
    return splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))


def _file_suite():
    case = MockTestCase(
        name="file case",
        mocks=[
            MockDirective(MockCategory.OPEN, "IN-FILE"),
            MockDirective(MockCategory.READ, "IN-FILE", ['MOVE "Y" TO WS-EOF']),
            MockDirective(MockCategory.CLOSE, "IN-FILE"),
            MockDirective(MockCategory.SQL, "UPDATE ORDERS", ["MOVE 0 TO SQLCODE"]),
        ],
        perform_target="MAIN-PARA",
    )
    return MockTestSuite(name="S", test_cases=[case])


def test_mocked_file_statements_are_commented_and_replaced():
    lines = _splice(_file_suite())
    joined = "\n".join(lines)
    assert "      *>     OPEN INPUT IN-FILE." in joined
    assert "      *>     READ IN-FILE" in joined
    # READ's AT END clause is inside the replaced span
    assert '      *>         AT END MOVE "Y" TO WS-EOF' in joined
    assert "      *>     CLOSE IN-FILE." in joined
    assert "ADD 1 TO UT-OPEN-IN-FILE-TALLY" in joined
    assert "ADD 1 TO UT-READ-IN-FILE-TALLY" in joined


def test_mocked_sql_statement_gets_dispatch():
    lines = _splice(_file_suite())
    joined = "\n".join(lines)
    assert "ADD 1 TO UT-SQL-UPDATE-ORDERS-TALLY" in joined
    assert "MOVE 0 TO SQLCODE" in joined


def test_unmocked_exec_sql_is_trap_stubbed_program_wide():
    lines = _splice(_file_suite())
    joined = "\n".join(lines)
    # the unreached DELETE is commented out and trapped, even though no case
    # mocks or reaches it (cobc cannot compile a raw EXEC block)
    assert "      *>     EXEC SQL" in joined
    live_sql = [
        ln
        for ln in lines
        if "DELETE FROM AUDIT" in ln and not ln.strip().startswith("*>")
    ]
    assert live_sql == []
    assert "unmocked EXEC SQL reached" in joined


def test_unmocked_call_is_left_in_place():
    lines = _splice(_file_suite())
    assert any(
        'CALL "DISCRATE"' in ln and not ln.strip().startswith("*>") for ln in lines
    )


def test_sentence_terminating_period_is_preserved():
    lines = _splice(_file_suite())
    # CLOSE IN-FILE. was the last statement of MAIN-PARA -- its replacement
    # block must end with a period so the sentence terminates before SQL-PARA.
    close_idx = next(
        i for i, ln in enumerate(lines) if ln.startswith("      *>     CLOSE IN-FILE.")
    )
    block_end = next(
        i
        for i in range(close_idx + 1, len(lines))
        if lines[i].strip().startswith("END-EVALUATE")
    )
    assert lines[block_end].rstrip().endswith(".")


# --- nested-site splicing ---------------------------------------------------

import pytest

from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

NESTED_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTSPLICE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X.
       01  WS-AMT             PIC 9(5).

       PROCEDURE DIVISION.
       NEST-PARA.
           IF WS-FLAG = "Y"
               CALL "NESTED"
                   USING WS-AMT
           END-IF.
           IF WS-FLAG = "P"
               CALL "PERIODIC" USING WS-AMT.
           IF WS-FLAG = "L"
               CALL "LONELY" USING WS-AMT
           END-IF.
           IF WS-FLAG = "S"
               EXEC SQL
                   UPDATE ORDERS SET STATUS = 'Y' WHERE ID = :WS-AMT
               END-EXEC
           END-IF.
           STOP RUN.
"""


def _splice_nested(suite, annotate=True):
    result = parse_cobol(NESTED_SOURCE, filename="nestsplice.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    normalized = normalize_fixed_format(NESTED_SOURCE.splitlines())
    lines = normalized.splitlines()
    if annotate:
        annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    boundaries = collect_boundaries(result.ast)
    return splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))


def _nested_suite(mocks):
    case = MockTestCase(name="nested", mocks=mocks, perform_target="NEST-PARA")
    return MockTestSuite(name="N", test_cases=[case])


def test_mocked_nested_call_is_spliced_and_end_if_survives():
    lines = _splice_nested(_nested_suite([MockDirective(MockCategory.CALL, "NESTED")]))
    joined = "\n".join(lines)
    assert '      *>         CALL "NESTED"' in joined
    assert "      *>             USING WS-AMT" in joined
    assert "ADD 1 TO UT-NESTED-TALLY" in joined
    # the enclosing block's words are untouched
    assert sum(1 for line in lines if line.strip() == "END-IF.") >= 1
    assert not any(line.startswith('      *>     IF WS-FLAG = "Y"') for line in lines)


def test_nested_span_trailing_period_reattaches():
    lines = _splice_nested(
        _nested_suite([MockDirective(MockCategory.CALL, "PERIODIC")])
    )
    commented = next(line for line in lines if 'CALL "PERIODIC"' in line)
    assert commented.startswith("      *>")
    replacement_end = next(
        line
        for line in lines
        if line.strip().startswith("END-EVALUATE") and line.rstrip().endswith(".")
    )
    assert replacement_end  # dispatch block re-terminates the sentence


def test_unmocked_nested_call_is_left_alone():
    lines = _splice_nested(_nested_suite([MockDirective(MockCategory.CALL, "NESTED")]))
    lonely = next(line for line in lines if 'CALL "LONELY"' in line)
    assert not lonely.startswith("      *>")


def test_unmocked_nested_exec_gets_trap_and_end_exec_commented():
    lines = _splice_nested(_nested_suite([MockDirective(MockCategory.CALL, "NESTED")]))
    joined = "\n".join(lines)
    assert "      *>         EXEC SQL" in joined
    assert "      *>         END-EXEC" in joined
    assert "unmocked EXEC SQL reached" in joined


def test_mocked_nested_site_without_span_raises():
    with pytest.raises(ValueError, match="without a validated span"):
        _splice_nested(
            _nested_suite([MockDirective(MockCategory.CALL, "NESTED")]),
            annotate=False,
        )


# --- SECTION headers survive splicing (audit 2.2) ----------------------------

SECTION_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECSPLICE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMT             PIC 9(5).

       PROCEDURE DIVISION.
       MAIN-SEC SECTION.
       MAIN-PARA.
           CALL "LASTCALL" USING WS-AMT.

       NEXT-SEC SECTION.
       NEXT-PARA.
           DISPLAY "NEXT".
"""


def test_splicing_sections_last_statement_leaves_section_header_live():
    """Audit finding 2.2: the CALL is the last statement before `NEXT-SEC
    SECTION.`; without section-header boundaries its splice span swallowed
    and commented out the header."""
    result = parse_cobol(SECTION_SOURCE, filename="secsplice.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(SECTION_SOURCE.splitlines()).splitlines()
    case = MockTestCase(
        name="sec",
        mocks=[MockDirective(MockCategory.CALL, "LASTCALL")],
        perform_target="MAIN-PARA",
    )
    suite = MockTestSuite(name="SEC", test_cases=[case])
    boundaries = collect_boundaries(result.ast)
    spliced = splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))
    commented_call = [
        ln for ln in spliced if "LASTCALL" in ln and ln.startswith("      *>")
    ]
    assert commented_call  # the CALL itself was spliced
    live_header = [
        ln
        for ln in spliced
        if "NEXT-SEC SECTION" in ln and not ln.strip().startswith("*>")
    ]
    assert live_header  # the following section header stayed live


# --- top-level own-line guard, splicer side (audit 2.1) -----------------------

SHARED_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SHARESPLICE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A               PIC 9(3).

       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A CALL "SHAREPGM" USING WS-A.
"""


def test_mocked_top_level_site_with_layout_problem_raises():
    """Defensive twin of the gate's UNSUPPORTED_MOCK_TARGET_LAYOUT: if an
    annotated shares-its-line top-level site somehow reaches the splicer,
    it raises instead of silently deleting the sibling MOVE."""
    result = parse_cobol(SHARED_LINE_SOURCE, filename="sharesplice.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(SHARED_LINE_SOURCE.splitlines()).splitlines()
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    case = MockTestCase(
        name="share",
        mocks=[MockDirective(MockCategory.CALL, "SHAREPGM")],
        perform_target="MAIN-PARA",
    )
    suite = MockTestSuite(name="SHARE", test_cases=[case])
    boundaries = collect_boundaries(result.ast)
    with pytest.raises(ValueError, match="does not start its own line"):
        splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))


from mockymock.analysis.refusal import find_terminator_plans

TERMINATOR_CHAIN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMCHAIN.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-WRAPPER
           DISPLAY "AFTER-WRAPPER".

       1000-WRAPPER.
           PERFORM 2000-INNER.
           DISPLAY "AFTER-INNER".

       2000-INNER.
           CALL "CALCPGM" USING WS-RESULT
           STOP RUN.
"""


def _terminator_chain_suite():
    case = MockTestCase(
        name="main",
        mocks=[MockDirective(MockCategory.CALL, "CALCPGM", ["MOVE 42 TO WS-RESULT"])],
        perform_target="0000-MAIN-PROCESS",
    )
    return MockTestSuite(name="T", test_cases=[case])


def _splice_terminator_chain(suite):
    result = parse_cobol(TERMINATOR_CHAIN_SOURCE, filename="termchain.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(TERMINATOR_CHAIN_SOURCE.splitlines()).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    boundaries = collect_boundaries(result.ast)
    plans, reasons = find_terminator_plans(surface, result.ast, suite, scope_map, lines)
    assert reasons == []
    return splice_program(
        lines, boundaries, surface, suite, TallyRegistry(suite), plans
    )


def test_terminator_is_replaced_with_flag_and_exit_paragraph():
    lines = _splice_terminator_chain(_terminator_chain_suite())
    joined = "\n".join(lines)
    assert "      *>     STOP RUN." in joined
    assert 'MOVE "Y" TO UT-EARLY-EXIT' in joined
    assert "EXIT PARAGRAPH" in joined


def test_intermediate_performs_get_chain_check_inserted_after():
    lines = _splice_terminator_chain(_terminator_chain_suite())
    joined = "\n".join(lines)
    # both PERFORM 1000-WRAPPER and PERFORM 2000-INNER are on the chain --
    # each must be followed by the flag check, and neither PERFORM's own
    # line is touched (still live, not commented out)
    assert "    PERFORM 1000-WRAPPER" in joined
    assert "    PERFORM 2000-INNER." in joined
    assert joined.count('IF UT-EARLY-EXIT = "Y"') == 2
    # the two DISPLAY lines that must not run past a real terminator stay
    # in the source (this test only checks the splice shape, not runtime
    # behavior -- that's the Task 7 integration test)
    assert 'DISPLAY "AFTER-WRAPPER"' in joined
    assert 'DISPLAY "AFTER-INNER"' in joined


def test_terminator_splice_coexists_with_mocked_call_splice():
    lines = _splice_terminator_chain(_terminator_chain_suite())
    joined = "\n".join(lines)
    assert "ADD 1 TO UT-CALCPGM-TALLY" in joined
    assert "MOVE 42 TO WS-RESULT" in joined
    assert '      *>     CALL "CALCPGM"' in joined


def test_no_terminator_plans_argument_leaves_existing_behavior_unchanged():
    """The old 5-positional-argument call (no terminator_plans) must still
    work exactly as before -- the regression guard for every existing
    caller of splice_program."""
    result = parse_cobol(TERMINATOR_CHAIN_SOURCE, filename="termchain.cbl")
    surface = analyze(result.ast)
    lines = normalize_fixed_format(TERMINATOR_CHAIN_SOURCE.splitlines()).splitlines()
    boundaries = collect_boundaries(result.ast)
    suite = _terminator_chain_suite()
    spliced = splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))
    joined = "\n".join(spliced)
    assert "STOP RUN." in joined
    assert "      *>     STOP RUN." not in joined
    assert "UT-EARLY-EXIT" not in joined


CHAIN_PERFORM_SOLE_STATEMENT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SOLESTMT.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-WRAPPER.

       1000-WRAPPER.
           PERFORM 2000-INNER.

       2000-INNER.
           MOVE 1 TO WS-RESULT
           STOP RUN.
"""


def test_chain_check_after_a_sole_period_terminated_perform_gets_its_own_period():
    """Regression test for a real (pre-existing, not SECTION-specific)
    splicer bug: when the intermediate PERFORM in a safe chain is the
    SOLE, period-terminated statement of its own paragraph, the inserted
    chain-check block must end its own sentence with a period, or the
    following paragraph header runs into an unterminated sentence and
    cobc rejects the compile (confirmed via a real GnuCOBOL compile,
    see tests/integration/test_terminator_support.py's Docker-level
    counterpart)."""
    result = parse_cobol(CHAIN_PERFORM_SOLE_STATEMENT_SOURCE, filename="solestmt.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(
        CHAIN_PERFORM_SOLE_STATEMENT_SOURCE.splitlines()
    ).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    boundaries = collect_boundaries(result.ast)
    suite = MockTestSuite(
        name="T",
        test_cases=[MockTestCase(name="main", perform_target="0000-MAIN-PROCESS")],
    )
    plans, reasons = find_terminator_plans(surface, result.ast, suite, scope_map, lines)
    assert reasons == []
    assert len(plans) == 1

    spliced = splice_program(
        lines, boundaries, surface, suite, TallyRegistry(suite), plans
    )

    # Both chain-check blocks (one after PERFORM 1000-WRAPPER, one after
    # PERFORM 2000-INNER) must each end their own sentence with a period,
    # since each of those PERFORMs is the sole statement of its paragraph.
    perform_wrapper_idx = next(
        i for i, line in enumerate(spliced) if "PERFORM 1000-WRAPPER" in line
    )
    end_if_idx = next(
        i
        for i in range(perform_wrapper_idx + 1, len(spliced))
        if "END-IF" in spliced[i]
    )
    assert spliced[end_if_idx].rstrip().endswith(".")


EARLY_MOCK_CHAIN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMCHAINEARLY.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           CALL "CALCPGM" USING WS-RESULT
           PERFORM 1000-WRAPPER.

       1000-WRAPPER.
           STOP RUN.
"""


def test_chain_check_survives_a_mocked_call_spliced_earlier_in_the_file():
    """Regression guard: a boundary-mock splice EARLIER in the file than
    an intermediate chain-link PERFORM must not corrupt where the
    chain-check lands. A naive two-pass design (all comment_and_replace
    spans applied first, then a separate pass of insert_lines_after using
    line numbers computed before any splicing happened) inserts the
    chain-check at the wrong, already-shifted position -- inside the
    earlier span's own replacement block -- because every span applied
    before it in the file shifts every line number after it. Confirmed
    empirically against this exact fixture before writing this test: the
    naive two-pass version corrupts the CALL mock's EVALUATE dispatch
    block, inserting `IF UT-EARLY-EXIT = "Y" ... END-IF` between `WHEN
    "001"` and its own `ADD 1 TO UT-CALCPGM-TALLY` line. The fix is a
    single, position-sorted, bottom-up pass over spans and insertions
    together (see Step 3 and the note below it)."""
    result = parse_cobol(EARLY_MOCK_CHAIN_SOURCE, filename="earlychain.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(EARLY_MOCK_CHAIN_SOURCE.splitlines()).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    boundaries = collect_boundaries(result.ast)
    suite = MockTestSuite(
        name="T",
        test_cases=[
            MockTestCase(
                name="main",
                mocks=[
                    MockDirective(
                        MockCategory.CALL, "CALCPGM", ["MOVE 42 TO WS-RESULT"]
                    )
                ],
                perform_target="0000-MAIN-PROCESS",
            )
        ],
    )
    plans, reasons = find_terminator_plans(surface, result.ast, suite, scope_map, lines)
    assert reasons == []
    spliced = splice_program(
        lines, boundaries, surface, suite, TallyRegistry(suite), plans
    )
    perform_idx = next(
        i for i, line in enumerate(spliced) if "PERFORM 1000-WRAPPER" in line
    )
    chain_check_idx = next(
        i
        for i in range(perform_idx + 1, len(spliced))
        if 'IF UT-EARLY-EXIT = "Y"' in spliced[i]
    )
    # the chain-check must land shortly after PERFORM 1000-WRAPPER -- only a
    # blank line may separate them (statement_span swallows a trailing blank
    # line into the PERFORM's own span, which is harmless: COBOL blank lines
    # have no runtime effect) -- not inside the CALL mock's EVALUATE dispatch
    # block, which is what a naive two-pass splice would corrupt
    assert chain_check_idx - perform_idx <= 2
    assert all(
        spliced[i].strip() == "" for i in range(perform_idx + 1, chain_check_idx)
    )
    # and the EVALUATE dispatch block for the mocked CALL must stay intact
    # and complete BEFORE the PERFORM, not straddling it
    joined = "\n".join(spliced)
    assert "END-EVALUATE" in joined
    evaluate_idx = next(i for i, line in enumerate(spliced) if "END-EVALUATE" in line)
    assert evaluate_idx < perform_idx


# The 2026-07-09 final branch review manually spiked these two shapes and
# found the splice correct but unguarded by any test -- given splice
# line-arithmetic is exactly what produced the ordering bug fixed above,
# these are cheap, high-value regression fixtures.

TWO_TERMINATORS_ONE_PARAGRAPH_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWOTERM.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-WRAPPER.

       1000-WRAPPER.
           DISPLAY "BEFORE"
           STOP RUN
           STOP RUN.
"""


def test_two_terminators_in_one_paragraph_are_each_neutralized_and_chain_check_deduped():
    """Both STOP RUN statements in 1000-WRAPPER get their own
    TerminatorPlan, and both share the SAME chain_performs edge (the one
    PERFORM 1000-WRAPPER statement in 0000-MAIN-PROCESS) -- the chain-check
    must be inserted only ONCE after that PERFORM, not once per plan."""
    result = parse_cobol(TWO_TERMINATORS_ONE_PARAGRAPH_SOURCE, filename="twoterm.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(
        TWO_TERMINATORS_ONE_PARAGRAPH_SOURCE.splitlines()
    ).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    boundaries = collect_boundaries(result.ast)
    suite = MockTestSuite(
        name="T",
        test_cases=[MockTestCase(name="main", perform_target="0000-MAIN-PROCESS")],
    )
    plans, reasons = find_terminator_plans(surface, result.ast, suite, scope_map, lines)
    assert reasons == []
    assert len(plans) == 2
    spliced = splice_program(
        lines, boundaries, surface, suite, TallyRegistry(suite), plans
    )
    joined = "\n".join(spliced)
    # deduped to exactly one chain-check, despite two plans sharing the edge
    assert joined.count('IF UT-EARLY-EXIT = "Y"') == 1
    # both terminators replaced independently -- 1 chain-check EXIT PARAGRAPH
    # + 2 terminator-replacement EXIT PARAGRAPHs
    assert joined.count("EXIT PARAGRAPH") == 3
    assert joined.count("*>     STOP RUN") == 2
    assert 'DISPLAY "BEFORE"' in joined


ADJACENT_PERFORM_AND_TERMINATOR_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ADJACENT.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-WRAPPER
           STOP RUN.

       1000-WRAPPER.
           DISPLAY "INNER".
"""


def test_perform_immediately_followed_by_terminator_interleaves_correctly():
    """PERFORM 1000-WRAPPER and STOP RUN share one sentence (one period,
    on STOP RUN's line) -- the chain-check insertion (after the PERFORM)
    and the terminator replacement (on the very next statement) must not
    collide, and the original trailing period must end up on the LAST
    line of the terminator's replacement, not stranded on the PERFORM."""
    result = parse_cobol(
        ADJACENT_PERFORM_AND_TERMINATOR_SOURCE, filename="adjacent.cbl"
    )
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(
        ADJACENT_PERFORM_AND_TERMINATOR_SOURCE.splitlines()
    ).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    boundaries = collect_boundaries(result.ast)
    suite = MockTestSuite(
        name="T",
        test_cases=[MockTestCase(name="main", perform_target="0000-MAIN-PROCESS")],
    )
    plans, reasons = find_terminator_plans(surface, result.ast, suite, scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    spliced = splice_program(
        lines, boundaries, surface, suite, TallyRegistry(suite), plans
    )
    joined = "\n".join(spliced)
    assert joined.count('IF UT-EARLY-EXIT = "Y"') == 1
    assert "*>     STOP RUN." in joined
    perform_idx = next(
        i for i, line in enumerate(spliced) if "PERFORM 1000-WRAPPER" in line
    )
    # the PERFORM's own line must NOT carry the original trailing period --
    # it belonged to STOP RUN, on the following line
    assert not spliced[perform_idx].rstrip().endswith(".")
    # the terminator replacement's last line must carry that period instead
    last_exit_idx = max(i for i, line in enumerate(spliced) if "EXIT PARAGRAPH" in line)
    assert spliced[last_exit_idx].rstrip().endswith(".")


SECTION_TERMINATOR_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTTERM.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-TERM-SECTION
           DISPLAY "AFTER-SECTION".

       1000-TERM-SECTION SECTION.
       1000-TERM-FIRST.
           MOVE 1 TO WS-RESULT
           STOP RUN.
       1000-TERM-SECOND.
           MOVE 999 TO WS-RESULT.
"""


def test_section_scoped_terminator_is_replaced_with_exit_section():
    result = parse_cobol(SECTION_TERMINATOR_SOURCE, filename="sectterm.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(SECTION_TERMINATOR_SOURCE.splitlines()).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    boundaries = collect_boundaries(result.ast)
    suite = MockTestSuite(
        name="T",
        test_cases=[MockTestCase(name="main", perform_target="0000-MAIN-PROCESS")],
    )
    plans, reasons = find_terminator_plans(surface, result.ast, suite, scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert plans[0].exit_kind == "SECTION"

    spliced = splice_program(
        lines, boundaries, surface, suite, TallyRegistry(suite), plans
    )
    joined = "\n".join(spliced)
    assert "      *>     STOP RUN." in joined
    assert 'MOVE "Y" TO UT-EARLY-EXIT' in joined
    assert "EXIT SECTION" in joined
    # the intermediate PERFORM's own post-check is still EXIT PARAGRAPH --
    # only the terminator's own replacement uses EXIT SECTION
    assert 'IF UT-EARLY-EXIT = "Y"' in joined
    assert "EXIT PARAGRAPH" in joined
