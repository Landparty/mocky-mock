"""Unit tests for mutation site discovery -- pure text level, no Docker."""

from mockymock.mutation.operators import generate_mutants


def _procedure(*statements: str) -> list[str]:
    return [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. SAMPLE.",
        "       PROCEDURE DIVISION.",
        "       MAIN-PARA.",
        *statements,
    ]


def _ops(mutants):
    return sorted({m.operator for m in mutants})


def test_no_mutants_before_procedure_division():
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. SAMPLE.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        "       01 WS-A PIC 9(4) VALUE 3.",
    ]
    assert generate_mutants(lines) == []


def test_rel_swap_in_condition_line():
    mutants = generate_mutants(_procedure("           PERFORM CALC UNTIL WS-I > 4"))
    swaps = [m for m in mutants if m.operator == "rel-swap"]
    assert len(swaps) == 1
    assert swaps[0].mutated == "           PERFORM CALC UNTIL WS-I >= 4"
    assert swaps[0].line == 5


def test_compound_symbol_not_double_mutated():
    mutants = generate_mutants(_procedure("           IF WS-I >= 4"))
    swaps = [m for m in mutants if m.operator == "rel-swap"]
    # `>=` -> `>` only; the bare-`>` swap must not also fire on the same
    # characters and produce `>>=`.
    assert [m.mutated for m in swaps] == ["           IF WS-I > 4"]


def test_rel_symbol_outside_condition_context_is_ignored():
    # No IF/UNTIL/WHEN on the line: nothing to swap even though `>` occurs.
    mutants = generate_mutants(_procedure('           DISPLAY "A > B"'))
    assert [m for m in mutants if m.operator == "rel-swap"] == []


def test_literal_and_inline_comment_are_not_sites():
    mutants = generate_mutants(
        _procedure('           IF WS-MSG = "X > Y" *> checks > marker')
    )
    assert [m for m in mutants if m.operator == "rel-swap"] == []


def test_arith_verb_swap_rewrites_preposition():
    mutants = generate_mutants(_procedure("           ADD 2 TO WS-TOTAL"))
    swaps = [m for m in mutants if m.operator == "arith-verb-swap"]
    assert [m.mutated for m in swaps] == ["           SUBTRACT 2 FROM WS-TOTAL"]


def test_divide_with_remainder_is_not_swapped_to_multiply():
    # `MULTIPLY 3 BY WS-A GIVING WS-B REMAINDER WS-C` is a GnuCOBOL syntax
    # error ("unexpected REMAINDER"): the swap was a stillborn every time,
    # whether the phrase sat on the DIVIDE line or on a later one.
    mutants = generate_mutants(
        _procedure(
            "           DIVIDE 3 INTO WS-A GIVING WS-B REMAINDER WS-C.",
            "           DIVIDE 3 INTO WS-A GIVING WS-B",
            "               REMAINDER WS-C",
            "           DIVIDE 3 INTO WS-A GIVING WS-B.",
            '           DISPLAY "REMAINDER".',
        )
    )
    swaps = [m for m in mutants if m.operator == "arith-verb-swap"]
    assert [(m.line, m.mutated) for m in swaps] == [
        (8, "           MULTIPLY 3 BY WS-A GIVING WS-B.")
    ]


def test_move_integer_literal_is_incremented():
    mutants = generate_mutants(_procedure("           MOVE 0 TO WS-TOTAL."))
    moves = [m for m in mutants if m.operator == "move-literal"]
    assert [m.mutated for m in moves] == ["           MOVE 1 TO WS-TOTAL."]


def test_boundary_literal_incremented_in_condition():
    mutants = generate_mutants(_procedure("           PERFORM CALC UNTIL WS-I > 4"))
    boundaries = [m for m in mutants if m.operator == "boundary-literal"]
    assert [m.mutated for m in boundaries] == ["           PERFORM CALC UNTIL WS-I > 5"]


def test_statement_deletion_preserves_indent_and_period():
    mutants = generate_mutants(_procedure("           MOVE 0 TO WS-TOTAL."))
    deletions = [m for m in mutants if m.operator == "stmt-delete"]
    assert [m.mutated for m in deletions] == ["           CONTINUE."]


def test_statement_without_period_deletes_without_period():
    mutants = generate_mutants(_procedure("               ADD 2 TO WS-TOTAL"))
    deletions = [m for m in mutants if m.operator == "stmt-delete"]
    assert [m.mutated for m in deletions] == ["               CONTINUE"]


def test_boundary_verbs_exclude_the_whole_line():
    mutants = generate_mutants(
        _procedure(
            '           CALL "SUBPGM" USING WS-TOTAL',
            "           READ INV-FILE",
            "           STOP RUN.",
            "           GOBACK.",
        )
    )
    assert mutants == []


def test_no_line_inside_a_multi_line_exec_block_is_mutated():
    # The splicer replaces a mocked EXEC wholesale, so a mutant on any of
    # its continuation lines could never be killed (issue #202).
    lines = _procedure(
        "           EXEC SQL",
        "               SELECT CASE",
        "                   WHEN BALANCE > 1000 THEN 'GOLD'",
        "                   ELSE 'STD' END",
        "               INTO :WS-TIER FROM ACCOUNTS WHERE ACCT_ID = :WS-ACCT",
        "           END-EXEC",
        "           EXEC SQL",
        "               UPDATE ACCOUNTS",
        "               SET BALANCE = 0",
        "           END-EXEC",
        "           EXEC CICS READ FILE('CUST')",
        "               SET(ADDRESS OF CUST-REC)",
        "           END-EXEC",
        "           IF WS-X > 1",
        "               MOVE 5 TO WS-Y",
        "           END-IF.",
    )
    mutants = generate_mutants(lines)
    assert {m.line for m in mutants} == {
        lines.index("           IF WS-X > 1") + 1,
        lines.index("               MOVE 5 TO WS-Y") + 1,
    }


def test_single_line_exec_does_not_swallow_the_following_lines():
    lines = _procedure(
        "           EXEC SQL COMMIT END-EXEC",
        "           IF WS-X > 1",
        "               MOVE 5 TO WS-Y",
        "           END-IF.",
    )
    assert {m.line for m in generate_mutants(lines)} == {6, 7}


def test_exec_inside_a_literal_does_not_open_a_block():
    lines = _procedure(
        '           MOVE "EXEC" TO WS-Z',
        "           IF WS-X > 1",
        "               MOVE 5 TO WS-Y",
        "           END-IF.",
    )
    assert {5, 6} <= {m.line for m in generate_mutants(lines)}


def test_hyphenated_identifier_containing_a_boundary_verb_is_not_excluded():
    """Audit finding F8: _EXCLUDED_VERBS matched with `\\bREAD\\b`, and `-`
    is not a word character in regex, so it false-matched inside
    WS-READ-COUNT -- an ordinary COBOL naming convention, not a real READ
    statement. The line must still be mutated."""
    mutants = generate_mutants(_procedure("           IF WS-READ-COUNT > 5"))
    assert [m for m in mutants if m.operator == "rel-swap"] != []


def test_hyphenated_identifier_containing_call_is_not_excluded():
    mutants = generate_mutants(_procedure("           MOVE 1 TO WS-CALL-FLAG."))
    assert [m for m in mutants if m.operator == "move-literal"] != []


def test_hyphenated_identifier_containing_scope_word_does_not_block_deletion():
    """_SCOPE_TOKENS had the same \\b-vs-hyphen bug: PERFORM inside
    WS-PERFORM-COUNT incorrectly looked like a scope-carrying line and
    blocked an otherwise-safe MOVE deletion."""
    mutants = generate_mutants(_procedure("           MOVE 1 TO WS-PERFORM-COUNT."))
    assert [m for m in mutants if m.operator == "stmt-delete"] != []


def test_scope_carrying_lines_are_never_deleted():
    mutants = generate_mutants(_procedure("           MOVE 1 TO WS-A IF WS-B > 2"))
    assert [m for m in mutants if m.operator == "stmt-delete"] == []


def test_comment_lines_are_ignored():
    mutants = generate_mutants(
        _procedure(
            "      * MOVE 0 TO WS-TOTAL.",
            "           *> MOVE 0 TO WS-TOTAL.",
        )
    )
    assert mutants == []


def test_fixture_yields_expected_mutant_set():
    """Pin the exact mutant population of the integration fixture so the
    Docker-gated kill-loop test's expectations stay explainable."""
    from pathlib import Path

    fixture = (
        Path(__file__).parent.parent
        / "integration"
        / "fixtures"
        / "mutation_target.cbl"
    )
    mutants = generate_mutants(fixture.read_text(encoding="utf-8").splitlines())
    assert [(m.line, m.operator) for m in mutants] == [
        (9, "move-literal"),
        (9, "stmt-delete"),
        (10, "rel-swap"),
        (10, "boundary-literal"),
        (11, "arith-verb-swap"),
        (11, "stmt-delete"),
    ]


# --- fixed-format column discipline -----------------------------------
#
# mockymock normalizes every source it compiles by slicing columns 8-72,
# so a mutant that pushes its own code past column 72, or that drags the
# identification area (columns 73-80) back into it, is a guaranteed
# stillborn. Traditional 80-column mainframe source -- the kind this tool
# exists for -- carries content in those columns on every line.


def _fixed(code: str, seq: str = "001000", ident: str = "NC1014.2") -> str:
    """One traditional 80-column line: sequence number in columns 1-6,
    blank indicator, program text from column 8, identification area
    pinned at column 73."""
    body = f"{seq} {code}"
    assert len(body) <= 72
    return body.ljust(72) + ident


def _fixed_procedure(*statements: str) -> list[str]:
    return [
        _fixed("IDENTIFICATION DIVISION."),
        _fixed("PROGRAM-ID. SAMPLE."),
        _fixed("PROCEDURE DIVISION."),
        _fixed("MAIN-PARA."),
        *statements,
    ]


def _code(line: str) -> str:
    return line[:72]


def test_growing_rewrite_reclaims_columns_from_interior_whitespace():
    """ADD..TO -> SUBTRACT..FROM adds seven characters. On a line that
    already reaches column 68 the rewrite would run to column 75 and lose
    its own tail to the column-72 slice; the interior run of spaces pays
    for it instead."""
    line = _fixed("    ADD     1 TO WS-DEEPLY-QUALIFIED-RUNNING-TOTAL-FIELD-NAME")
    swaps = [
        m
        for m in generate_mutants(_fixed_procedure(line))
        if m.operator == "arith-verb-swap"
    ]
    assert len(swaps) == 1
    mutated = swaps[0].mutated
    # Three of the five columns between ADD and its operand paid for the
    # seven the longer verb needed; the statement's own indent (and so its
    # Area A / Area B position) is untouched, and the identification area
    # still starts at column 73.
    assert (
        _code(mutated)
        == "001000     SUBTRACT  1 FROM WS-DEEPLY-QUALIFIED-RUNNING-TOTAL-FIELD-NAME"
    )
    assert len(_code(mutated).rstrip()) <= 72
    assert mutated[72:] == "NC1014.2"


def test_growing_rewrite_is_refused_when_no_columns_can_be_reclaimed():
    """Same line, single-spaced: there is nothing to give back, so the
    mutant is not generated at all rather than generated stillborn."""
    line = _fixed("    ADD 1 TO WS-DEEPLY-QUALIFIED-RUNNING-TOTAL-FIELD-NAME-XYZ")
    mutants = generate_mutants(_fixed_procedure(line))
    assert [m for m in mutants if m.operator == "arith-verb-swap"] == []


def test_shrinking_rewrite_keeps_the_identification_area_at_column_73():
    """SUBTRACT..FROM -> ADD..TO is seven characters shorter. Carrying the
    rest of the line along would slide `NC1014.2` from column 73 to 66 --
    inside the program text, where it becomes code."""
    line = _fixed("    SUBTRACT 1 FROM WS-RUNNING-TOTAL.")
    swaps = [
        m
        for m in generate_mutants(_fixed_procedure(line))
        if m.operator == "arith-verb-swap"
    ]
    assert len(swaps) == 1
    assert swaps[0].mutated[72:] == "NC1014.2"
    assert _code(swaps[0].mutated).strip() == "001000     ADD 1 TO WS-RUNNING-TOTAL."


def test_relational_swap_keeps_the_identification_area_at_column_73():
    line = _fixed("    IF WS-I >= 4")
    swaps = [
        m for m in generate_mutants(_fixed_procedure(line)) if m.operator == "rel-swap"
    ]
    assert [m.mutated[72:] for m in swaps] == ["NC1014.2"]
    assert _code(swaps[0].mutated).rstrip() == "001000     IF WS-I > 4"


# --- COBOL word boundaries on the arithmetic verbs ---------------------


def test_hyphenated_identifier_containing_add_is_not_an_arithmetic_site():
    """Same class of bug as audit finding F8, one module-level regex
    later: `\\bADD\\b` matches inside GRP-FOR-ADD-CORR-R, so an ordinary
    MOVE was rewritten to `MOVE GRP-FOR-SUBTRACT-CORR-R FROM ...` -- a
    stillborn, and 102 of them across the vendored NIST corpus."""
    mutants = generate_mutants(
        _procedure("           MOVE GRP-FOR-ADD-CORR-R TO COMPUTED-A.")
    )
    assert [m for m in mutants if m.operator == "arith-verb-swap"] == []


def test_hyphenated_identifier_containing_to_is_not_the_preposition():
    mutants = generate_mutants(_procedure("           ADD 1 TO WS-TO-DATE-COUNT."))
    swaps = [m for m in mutants if m.operator == "arith-verb-swap"]
    assert [m.mutated for m in swaps] == [
        "           SUBTRACT 1 FROM WS-TO-DATE-COUNT."
    ]


# --- deletion only of statements that end on their own line ------------


def test_multi_line_statement_head_is_never_deleted():
    """`CONTINUE` followed by the orphaned second half of a COMPUTE is a
    compile error, not a mutant."""
    mutants = generate_mutants(
        _procedure(
            "           COMPUTE WS-AVG =",
            "               WS-TOTAL / WS-COUNT",
            "           DISPLAY WS-AVG.",
        )
    )
    assert [m for m in mutants if m.operator == "stmt-delete"] == []


def test_statement_followed_by_its_own_scope_terminator_is_never_deleted():
    """END-ADD binds to the ADD being deleted; END-IF would not."""
    mutants = generate_mutants(
        _procedure(
            "           ADD 1 TO WS-TOTAL",
            "               ON SIZE ERROR MOVE 1 TO WS-FLAG",
            "           END-ADD",
        )
    )
    assert [m for m in mutants if m.operator == "stmt-delete"] == []


def test_deletion_allowed_when_the_next_line_opens_a_new_statement():
    mutants = generate_mutants(
        _procedure(
            "           MOVE 0 TO WS-TOTAL",
            "           DISPLAY WS-TOTAL.",
        )
    )
    deletions = [m for m in mutants if m.operator == "stmt-delete"]
    assert [m.mutated for m in deletions] == ["           CONTINUE"]


def test_deletion_allowed_before_an_enclosing_scope_terminator():
    mutants = generate_mutants(
        _procedure(
            "           IF WS-FLAG = 1",
            "               MOVE 0 TO WS-TOTAL",
            "           END-IF.",
        )
    )
    deletions = [m for m in mutants if m.operator == "stmt-delete"]
    assert [m.mutated for m in deletions] == ["               CONTINUE"]


def test_dangling_preposition_blocks_deletion():
    """The operand line of a split MOVE is indistinguishable from a
    paragraph header, so the trailing `TO` is what has to decide it."""
    mutants = generate_mutants(
        _procedure(
            "           MOVE WS-A TO",
            "               WS-B.",
        )
    )
    assert [m for m in mutants if m.operator == "stmt-delete"] == []


# --- continuation lines and program boundaries -------------------------


def test_continuation_lines_are_not_mutated():
    mutants = generate_mutants(
        [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. SAMPLE.",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            '           MOVE "ABCDEF',
            '      -    "GHI" TO WS-X.',
            "           MOVE 0 TO WS-TOTAL.",
        ]
    )
    assert [m.line for m in mutants] == [7, 7]


def test_a_second_programs_data_division_is_not_mutated():
    """`in_procedure` is sticky, so without a program-boundary reset the
    next program's WORKING-STORAGE looks like procedural code."""
    mutants = generate_mutants(
        [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. FIRST.",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           MOVE 0 TO WS-TOTAL.",
            "       END PROGRAM FIRST.",
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. SECOND.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-LIMIT PIC 9(4) VALUE 5.",
        ]
    )
    assert sorted({m.line for m in mutants}) == [5]


def test_statement_deletion_fires_on_sequence_numbered_lines():
    """Columns 1-6 of a fixed-format line are a sequence number, which real
    mainframe sources routinely fill. The deletion check used to match its
    verb against the whole stripped line, so `000500     MOVE ...` never
    looked like a MOVE and stmt-delete silently produced nothing for such
    a file. The rewrite must also keep the sequence area in place."""
    lines = [
        "000100 IDENTIFICATION DIVISION.",
        "000200 PROGRAM-ID. SAMPLE.",
        "000300 PROCEDURE DIVISION.",
        "000400 MAIN-PARA.",
        "000500     MOVE 1 TO WS-A",
        "000600     ADD 2 TO WS-TOTAL.",
    ]
    deletions = [m for m in generate_mutants(lines) if m.operator == "stmt-delete"]
    assert [(m.line, m.mutated) for m in deletions] == [
        (5, "000500     CONTINUE"),
        (6, "000600     CONTINUE."),
    ]


def test_debug_lines_are_not_mutated():
    """A `D` in column 7 is a debugging line: cobc (like the IBM compiler)
    treats it as a comment unless the program declares WITH DEBUGGING MODE,
    so a mutant there can never be killed and only lowers the score."""
    lines = _procedure(
        "      D    ADD 3 TO WS-C.",
        "      d    IF WS-A > 6 DISPLAY WS-A END-IF.",
    )
    assert generate_mutants(lines) == []


def test_debug_lines_are_mutated_in_debugging_mode():
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. SAMPLE.",
        "       ENVIRONMENT DIVISION.",
        "       CONFIGURATION SECTION.",
        "       SOURCE-COMPUTER. IBM-370 WITH DEBUGGING MODE.",
        "       PROCEDURE DIVISION.",
        "       MAIN-PARA.",
        "      D    ADD 3 TO WS-C.",
    ]
    assert generate_mutants(lines) != []


def test_multi_receiver_move_ending_the_sentence_is_never_deleted():
    """`WS-B.` in Area B is the MOVE's last receiver, not a paragraph
    header: deleting `MOVE 1 TO WS-A` left `CONTINUE` / `WS-B.`, which
    GnuCOBOL rejects -- a stillborn mutant every time."""
    mutants = generate_mutants(
        _procedure(
            "           MOVE 1 TO WS-A",
            "                     WS-B.",
            "           GOBACK.",
        )
    )
    assert [m for m in mutants if m.operator == "stmt-delete"] == []


def test_deletion_allowed_before_a_paragraph_header_in_area_a():
    mutants = generate_mutants(
        _procedure(
            "           MOVE 0 TO WS-TOTAL",
            "       NEXT-PARA.",
            "           GOBACK.",
        )
    )
    deletions = [m for m in mutants if m.operator == "stmt-delete"]
    assert [m.mutated for m in deletions] == ["           CONTINUE"]


def _swaps(mutants):
    return [m for m in mutants if m.operator == "arith-verb-swap"]


def test_verb_swap_rewrites_a_same_line_scope_terminator():
    """#234: `ADD ... END-ADD` swapped to `SUBTRACT ... END-ADD` never
    compiled; the terminator now follows the verb."""
    mutants = _swaps(
        generate_mutants(
            _procedure(
                "           ADD 5 TO WS-A ON SIZE ERROR CONTINUE END-ADD",
                "           MULTIPLY 3 BY WS-B END-MULTIPLY.",
            )
        )
    )
    mutated = {m.description: m.mutated for m in mutants}
    add = mutated["ADD..TO -> SUBTRACT..FROM"]
    assert "SUBTRACT 5 FROM WS-A" in add and add.rstrip().endswith("END-SUBTRACT")
    assert "END-ADD" not in add
    mul = mutated["MULTIPLY..BY -> DIVIDE..INTO"]
    assert mul.rstrip().endswith("DIVIDE 3 INTO WS-B END-DIVIDE.")


def test_verb_swap_skips_a_terminator_on_a_later_line():
    """A single-line mutant cannot rewrite an END-<verb> lines below, so the
    site is skipped rather than shipped as a guaranteed stillborn."""
    mutants = _swaps(
        generate_mutants(
            _procedure(
                "           ADD 5 TO WS-A",
                '               ON SIZE ERROR MOVE "Y" TO WS-ERR',
                "           END-ADD",
                "           MULTIPLY 3 BY WS-B",
                "               ON SIZE ERROR",
                '                   MOVE "Y" TO WS-ERR',
                "           END-MULTIPLY",
                "           ADD 1 TO WS-C.",
            )
        )
    )
    assert [m.description for m in mutants] == ["ADD..TO -> SUBTRACT..FROM"]
    assert mutants[0].line == 12  # the unterminated ADD, still mutated


def test_verb_swap_ignores_a_nested_statements_terminator():
    mutants = _swaps(
        generate_mutants(
            _procedure(
                "           ADD 1 TO WS-A ADD 2 TO WS-B ON SIZE ERROR",
                "               CONTINUE END-ADD.",
            )
        )
    )
    # Only the first ADD is a site; its END-ADD search sees the second ADD
    # open a level that END-ADD closes, so it has no terminator of its own.
    assert len(mutants) == 1
    assert "END-ADD" not in mutants[0].mutated
