"""Unit tests for mockymock.cli.mainframe_export -- the export-only text
transforms that make the instrumented source z/OS-compilable. See
docs/2026-08-03-mainframe-export-command-design.md for the empirical basis
(spiked against a real cobolparser install and a real GnuCOBOL container
before this code was written)."""

import random

from mockymock.cli.mainframe_export import (
    build_provenance_header,
    fit_within_columns,
    insert_provenance_header,
    restore_fixed_format_columns,
    wrap_long_display_lines,
    wrap_long_literal_lines,
)


def test_restore_fixed_format_columns_prepends_seven_spaces():
    lines = ["IDENTIFICATION DIVISION.", "", "PROGRAM-ID. X."]
    result = restore_fixed_format_columns(lines)
    assert result == [
        "       IDENTIFICATION DIVISION.",
        "       ",
        "       PROGRAM-ID. X.",
    ]


def test_restore_fixed_format_columns_preserves_line_count():
    lines = ["A"] * 50
    assert len(restore_fixed_format_columns(lines)) == 50


def test_provenance_header_lines_all_fit_within_72_columns():
    header = build_provenance_header("PROG.cbl", "PROG.cut")
    assert all(len(line) <= 72 for line in header)


def test_provenance_header_names_source_files_by_basename_only():
    header = build_provenance_header(
        "C:/very/deeply/nested/workspace/path/PROG.cbl",
        "C:/very/deeply/nested/workspace/path/PROG.cut",
    )
    joined = "\n".join(header)
    assert "PROG.cbl" in joined
    assert "PROG.cut" in joined
    assert "very/deeply/nested" not in joined


def test_provenance_header_mentions_mock_only_and_finding_1():
    header = "\n".join(build_provenance_header("P.cbl", "P.cut"))
    assert "MOCK-ONLY" in header
    assert "real-world-readiness-audit" in header


def test_insert_provenance_header_lands_before_identification_division():
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. X.",
    ]
    header = ["      *> header line 1", "      *> header line 2", ""]
    result = insert_provenance_header(lines, header)
    assert result == [
        "      *> header line 1",
        "      *> header line 2",
        "",
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. X.",
    ]


def test_insert_provenance_header_lands_after_a_preserved_directive():
    """PROCESS/CBL directives must precede IDENTIFICATION DIVISION -- the
    header must not be inserted between a preserved directive and it."""
    lines = [
        "       CBL APOST",
        "       IDENTIFICATION DIVISION.",
    ]
    header = ["      *> header", ""]
    result = insert_provenance_header(lines, header)
    assert result == [
        "       CBL APOST",
        "      *> header",
        "",
        "       IDENTIFICATION DIVISION.",
    ]


# The five lines below are the ACTUAL over-72-column lines produced by
# splicing examples/custprog/CUSTPROG.cbl + CUSTPROG.cut (captured during
# design, before this module existed) -- driver.py/injector.py DISPLAY
# calls, not user-authored text.
REAL_OVERFLOW_LINES = [
    '               DISPLAY "__MOCKYMOCK__ CASE 001 FAIL: VERIFY SQL FETCH CUST_CURSOR WAS CALLED 3 TIMES, got " FUNCTION TRIM(UT-TALLY-EDITED)',
    '               DISPLAY "__MOCKYMOCK__ CASE 001 FAIL: expected WS-ROW-COUNT = 2, got " WS-ROW-COUNT',
    '           DISPLAY "__MOCKYMOCK__ CASE 001 START: fetches two customers then exhausts"',
    '                   DISPLAY "__MOCKYMOCK__ ERROR: SQL boundary (line 18) reached "',
    '           DISPLAY "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=" UT-FAIL-COUNT',
]


def test_short_lines_pass_through_unchanged():
    lines = ['           DISPLAY "short"', "some other line"]
    result, problems = wrap_long_display_lines(lines)
    assert result == lines
    assert problems == []


def test_real_overflow_lines_all_wrap_under_72_with_no_problems():
    result, problems = wrap_long_display_lines(REAL_OVERFLOW_LINES)
    assert problems == []
    assert all(len(line) <= 72 for line in result)
    # Each original line's overflow produced at least 2 output lines.
    assert len(result) > len(REAL_OVERFLOW_LINES)


def test_wrap_preserves_leading_indentation_on_every_fragment():
    line = (
        '                   DISPLAY "__MOCKYMOCK__ ERROR: SQL boundary '
        '(line 18) reached "'
    )
    result, problems = wrap_long_display_lines([line])
    assert problems == []
    assert all(frag.startswith("                   DISPLAY") for frag in result)


def test_wrap_uses_with_no_advancing_on_every_fragment_but_the_last():
    result, problems = wrap_long_display_lines([REAL_OVERFLOW_LINES[0]])
    assert problems == []
    for fragment in result[:-1]:
        assert fragment.endswith("WITH NO ADVANCING")
    assert not result[-1].endswith("WITH NO ADVANCING")


def test_wrap_reconstructs_the_exact_original_literal_and_trailing_expr():
    """Concatenating every fragment's literal text (in order) plus the
    final fragment's trailing expression/period must exactly reproduce
    what the single unwrapped DISPLAY would have printed."""
    import re

    display_re = re.compile(r"^(?P<indent>\s*)DISPLAY\s+(?P<rest>.+)$", re.IGNORECASE)

    def parse_args(rest):
        pos, length, chunks, found = 0, len(rest), [], False
        while pos < length:
            while pos < length and rest[pos] == " ":
                pos += 1
            if pos >= length or rest[pos] != '"':
                break
            found = True
            pos += 1
            piece = []
            while True:
                if rest[pos] == '"':
                    if pos + 1 < length and rest[pos + 1] == '"':
                        piece.append('"')
                        pos += 2
                        continue
                    pos += 1
                    break
                piece.append(rest[pos])
                pos += 1
            chunks.append("".join(piece))
        if not found:
            return None
        return "".join(chunks), rest[pos:].strip()

    for original in REAL_OVERFLOW_LINES:
        wrapped, problems = wrap_long_display_lines([original])
        assert problems == []

        literal_parts = []
        trailing_expr = ""
        for i, fragment in enumerate(wrapped):
            rest = display_re.match(fragment).group("rest")
            is_last = i == len(wrapped) - 1
            if not is_last:
                assert rest.endswith(" WITH NO ADVANCING")
                rest = rest[: -len(" WITH NO ADVANCING")]
            lit, trailing = parse_args(rest)
            literal_parts.append(lit)
            if is_last:
                trailing_expr = trailing

        orig_rest = display_re.match(original).group("rest")
        orig_literal, orig_trailing = parse_args(orig_rest)
        assert "".join(literal_parts) == orig_literal
        assert trailing_expr == orig_trailing


def test_wrap_handles_a_trailing_period():
    line = (
        '           DISPLAY "__MOCKYMOCK__ CASE 001 END: this is a '
        'deliberately very long case-end marker for testing purposes here".'
    )
    result, problems = wrap_long_display_lines([line])
    assert problems == []
    assert all(len(frag) <= 72 for frag in result)
    assert result[-1].endswith(".")
    assert not any(frag.endswith(".") for frag in result[:-1])


def test_wrap_never_splits_an_escaped_doubled_quote():
    line = (
        '           DISPLAY "__MOCKYMOCK__ CASE 001 START: a case name with '
        'an embedded ""quoted phrase"" right in the middle of it"'
    )
    result, problems = wrap_long_display_lines([line])
    assert problems == []
    for fragment in result:
        # An odd number of quote characters means a doubled pair was
        # bisected -- each fragment's literal must be independently
        # well-formed (an even count of quote chars inside the outer
        # delimiters).
        inner = fragment[fragment.index('"') + 1 : fragment.rindex('"')]
        assert inner.count('"') % 2 == 0


def test_unwrappable_line_is_reported_not_silently_kept_long():
    line = "           MOVE " + "X" * 80 + " TO SOME-FIELD"
    result, problems = wrap_long_display_lines([line])
    assert len(problems) == 1
    assert "line 1" in problems[0]
    assert result == [line]


def test_comment_line_overflow_is_not_reported_as_a_problem():
    """A `*>`-prefixed full-line comment -- the shape
    splicer/stub_writer.py's comment_and_replace produces when it preserves
    an original boundary statement's text behind the dispatch it inserts --
    that runs past column 72 is harmless: columns 73+ are the
    identification field under fixed-format rules, always ignored by the
    compiler regardless of content, so an overflowing comment can never be
    truncated into something that changes meaning the way an overflowing
    DISPLAY statement could. Refusing on it would be a false positive.
    Found empirically via examples/claimseg (the repo's only EXEC DLI
    example): its commented-out, deeply indented `ISRT SEGMENT(...)` line
    is 75 columns wide after restore_fixed_format_columns's 7-space
    prefix, and previously tripped the COLUMN_OVERFLOW refusal even though
    nothing about it can miscompile."""
    line = (
        "      *>                    ISRT SEGMENT(PAYMENT-SEG) " "FROM(WS-CLAIM-AMOUNT)"
    )
    assert len(line) > 72
    result, problems = wrap_long_display_lines([line])
    assert problems == []
    assert result == [line]


def test_atomic_units_keeps_doubled_quote_pairs_together():
    from mockymock.cli.mainframe_export import _atomic_units

    units = _atomic_units('AB""CD""""EF')
    assert units == ["A", "B", '""', "C", "D", '""', '""', "E", "F"]
    assert "".join(units) == 'AB""CD""""EF'


def test_chunk_units_never_splits_a_unit_and_clamps_non_positive_budget():
    from mockymock.cli.mainframe_export import _atomic_units, _chunk_units

    units = _atomic_units('AB""CD')
    for budget in (-5, 0, 1, 2, 3, 10):
        chunks = _chunk_units(units, budget)
        assert "".join(chunks) == 'AB""CD'
        for chunk in chunks:
            assert chunk.count('"') % 2 == 0


def test_wrap_refuses_cleanly_when_clustered_escapes_leave_no_valid_cut():
    """White-box regression guard for the deep-indentation edge case
    found during design (a 20,000-case randomized stress test): when the
    wrap budget is squeezed down to ~1 character by deep indentation and
    a run of escaped quotes clusters right at the only available split
    point, no chunking can produce a fragment within max_col without
    bisecting a doubled-quote pair. This must REFUSE (fail closed, named
    COLUMN_OVERFLOW by the caller), not silently ship an over-length
    fragment -- not reachable by any current mockymock-generated shape
    (needs ~43 columns of indentation), but the function's contract
    (every returned line fits, or the line is in problems) must hold for
    any input."""
    indent = " " * 43
    literal = '""' * 18  # a long run of escaped-quote pairs
    line = f'{indent}DISPLAY "{literal}"'
    assert len(line) > 72

    result, problems = wrap_long_display_lines([line])
    assert len(problems) == 1
    assert "could not wrap under column 72" in problems[0]
    assert result == [line]


# --- fixed-format literal continuation (wrap_long_literal_lines) -------
#
# The generated reset MOVE that motivated this: splicer/reset.py
# re-serializes every WORKING-STORAGE VALUE clause into
# UT-RESET-WORKING-STORAGE, so a program declaring a wide storage-dump
# marker field (`DEBUT-WORKING-STORAGE` / `FIN-WORKING-STORAGE`, standard
# practice in IBM shops) produces a MOVE that overflows on its own --
# nothing the `.cut` file can shorten, and a flat export refusal before
# these lines could be continued.
MARKER_MOVE = (
    '           MOVE "***** DEBUT WORKING-STORAGE DTBC7D01 ******" '
    "TO DEBUT-WORKING-STORAGE"
)


def _read_back_continuation(lines):
    """Rebuild the single logical line a fixed-format compiler reads from
    `lines`, applying the continuation rules literally: on a continued
    line every character THROUGH COLUMN 72 belongs to the open literal
    (trailing blanks included -- confirmed empirically against GnuCOBOL
    4.0, which is why every continued line must be filled exactly), and a
    continuation line contributes everything after the quotation mark
    that must be its first nonblank character in Area B."""
    logical = lines[0].ljust(72)
    for continuation in lines[1:]:
        assert continuation[6] == "-", f"no indicator-area hyphen: {continuation!r}"
        assert continuation[:6].strip() == "", f"sequence area used: {continuation!r}"
        area_b = continuation[7:]
        assert area_b.lstrip()[0] in ('"', "'"), f"no re-opened literal: {area_b!r}"
        quote_column = 8 + (len(area_b) - len(area_b.lstrip()))
        assert quote_column >= 12, f"literal starts in Area A: {continuation!r}"
        piece = area_b.lstrip()[1:]
        is_last = continuation is lines[-1]
        logical += piece if is_last else piece.ljust(72 - quote_column)
    return logical


def _assert_same_statement(original, wrapped):
    """The wrapped form must read back as the original statement. Only
    whitespace between the prefix and the opening delimiter may differ:
    that is the padding that fills a continued line to exactly column 72,
    and extra spaces before a literal are separators in COBOL."""
    from mockymock.cli.mainframe_export import _find_single_literal

    rebuilt = _read_back_continuation(wrapped)
    was = _find_single_literal(original)
    now = _find_single_literal(rebuilt)
    assert now is not None
    assert now[0].rstrip() == was[0].rstrip()  # prefix, modulo fill padding
    assert now[1:] == was[1:]  # delimiter, literal body, trailing text


def test_long_generated_move_is_continued_instead_of_refused():
    """The `DEBUT-WORKING-STORAGE` shape from the bug report: a reset MOVE
    whose VALUE literal pushes it past column 72."""
    assert len(MARKER_MOVE) > 72
    result, problems = wrap_long_literal_lines([MARKER_MOVE])
    assert problems == []
    assert len(result) > 1
    assert all(len(line) <= 72 for line in result)
    assert result[0].lstrip().startswith("MOVE")
    assert all(line[6] == "-" for line in result[1:])
    _assert_same_statement(MARKER_MOVE, result)


def test_every_continued_line_is_filled_to_exactly_the_column_limit():
    """Not cosmetic: a continued line's trailing blanks through column 72
    are part of the literal, so a short one silently pads the value with
    spaces (reproduced against GnuCOBOL 4.0 while fixing this)."""
    result, problems = wrap_long_literal_lines([MARKER_MOVE])
    assert problems == []
    assert all(len(line) == 72 for line in result[:-1])
    assert len(result[-1]) <= 72


def test_continuation_preserves_a_trailing_period_and_escaped_quotes():
    line = (
        '           MOVE "***** MARKER WITH AN ""EMBEDDED QUOTED PHRASE"" '
        'INSIDE IT *****" TO WS-A-MARKER-FIELD.'
    )
    result, problems = wrap_long_literal_lines([line])
    assert problems == []
    assert all(len(fragment) <= 72 for fragment in result)
    assert result[-1].endswith(".")
    _assert_same_statement(line, result)


def test_continuation_handles_an_apostrophe_delimited_literal():
    """mockymock generates only `"` literals, but a `.cut` MOCK body or a
    preserved line of the original program may use `'`."""
    line = (
        "           MOVE '***** DEBUT WORKING-STORAGE DTBC7D01 ******' "
        "TO DEBUT-WORKING-STORAGE"
    )
    result, problems = wrap_long_literal_lines([line])
    assert problems == []
    assert all(line[7:].lstrip().startswith("'") for line in result[1:])
    _assert_same_statement(line, result)


def test_original_source_line_with_a_collapsed_literal_is_continued():
    """normalize_fixed_format merges a literal the ORIGINAL source already
    continued back onto one free-form line, which
    restore_fixed_format_columns then pushes 7 columns further right --
    the second routine way a program with no long `.cut` text at all used
    to hit a flat COLUMN_OVERFLOW refusal."""
    line = (
        '       01  WS-BANNER  PIC X(60) VALUE "***** DTBC7D01 STORAGE '
        'DUMP BOUNDARY MARKER *****".'
    )
    assert len(line) > 72
    result, problems = wrap_long_literal_lines([line])
    assert problems == []
    assert all(len(fragment) <= 72 for fragment in result)
    _assert_same_statement(line, result)


def test_line_with_no_literal_is_still_reported():
    """The refusal path stays honest: nothing to continue, nothing to
    silently ship long."""
    line = "           MOVE WS-A-VERY-LONG-SOURCE-FIELD-NAME-HERE TO " + "Y" * 30
    result, problems = wrap_long_literal_lines([line])
    assert len(problems) == 1
    assert "line 1" in problems[0]
    assert "no single quoted literal to split" in problems[0]
    assert result == [line]


def test_line_with_two_literals_is_reported_not_guessed_at():
    line = (
        '           STRING "FIRST LITERAL HERE" "SECOND LITERAL HERE" '
        "DELIMITED BY SIZE INTO WS-TARGET-FIELD"
    )
    result, problems = wrap_long_literal_lines([line])
    assert len(problems) == 1
    assert result == [line]


def test_trailing_text_too_long_to_fit_is_reported():
    """A literal split cannot rescue a line whose NON-literal text alone
    overflows -- the final continuation line still has to carry it. The
    message must say that, not claim the line holds no literal: it holds
    one, and reading "no literal" against your own MOVE is worse than no
    message at all."""
    line = '           MOVE "SHORT" TO ' + "W" * 60
    assert len(line) > 72
    result, problems = wrap_long_literal_lines([line])
    assert len(problems) == 1
    assert "the rest of the line does not fit" in problems[0]
    assert "no single quoted literal" not in problems[0]
    assert result == [line]


def test_compiler_directive_is_reported_not_continued():
    """CBL/PROCESS are read before normal continuation rules apply."""
    line = "       CBL APOST,NOSEQ,LIB,TEST(NONE,SYM,SEPARATE)," + "X" * 40
    result, problems = wrap_long_literal_lines([line])
    assert len(problems) == 1
    assert "compiler-directing" in problems[0]
    assert result == [line]


def test_literal_pass_leaves_overlong_comment_lines_alone():
    line = "      *>                    ISRT SEGMENT(PAYMENT-SEG) FROM(WS-CLAIM-AMOUNT)"
    assert len(line) > 72
    result, problems = wrap_long_literal_lines([line])
    assert problems == []
    assert result == [line]


def test_continuation_round_trips_under_randomized_shapes():
    """The property that matters, over the shapes this actually sees:
    whatever comes back reads as the same statement, or the line is
    refused. The same generator was run through a real fixed-format
    GnuCOBOL 4.0 compile while fixing this (342 compiled cases, zero
    mismatches); this is its zero-dependency standing guard."""
    rng = random.Random(20260904)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 *-.,:/()+= "
    checked = 0
    for index in range(400):
        delimiter = rng.choice(['"', "'"])
        target_length = rng.randint(1, 180)
        pieces = []
        while len("".join(pieces)) < target_length:
            roll = rng.random()
            if roll < 0.08:
                pieces.append(delimiter * 2)  # an escaped delimiter pair
            else:
                pieces.append(rng.choice(alphabet))
        body = "".join(pieces)
        indent = " " * rng.choice([11, 12, 19, 30])
        field = f"WS-F{index:03d}" + "-X" * rng.randint(0, 8)
        line = f"{indent}MOVE {delimiter}{body}{delimiter} TO {field}"
        if rng.random() < 0.3:
            line += "."
        if len(line) <= 72:
            continue
        result, problems = wrap_long_literal_lines([line])
        if problems:
            assert result == [line]  # refused, never silently kept long
            continue
        assert all(len(fragment) <= 72 for fragment in result)
        assert all(len(fragment) == 72 for fragment in result[:-1])
        _assert_same_statement(line, result)
        checked += 1
    assert checked > 300  # the generator must actually be exercising this


def test_fit_within_columns_wraps_displays_and_continues_everything_else():
    """The order `export` relies on: a generated DISPLAY still becomes
    WITH NO ADVANCING fragments (its stdout equivalence is what the
    __MOCKYMOCK__ protocol rides on), and everything else still long is
    continued."""
    lines = [REAL_OVERFLOW_LINES[0], MARKER_MOVE, "           MOVE 0 TO WS-X"]
    result, problems = fit_within_columns(lines)
    assert problems == []
    assert all(len(line) <= 72 for line in result)
    assert any(line.endswith("WITH NO ADVANCING") for line in result)
    assert any(line[6:7] == "-" for line in result)
    assert "           MOVE 0 TO WS-X" in result


def test_fit_within_columns_reports_only_what_no_pass_can_fit():
    """A line an earlier pass declines but a later one handles must not be
    reported -- it was, in fact, fitted. Only a line NO pass can fit is a
    problem: here, one whose single over-long word leaves nothing to break
    at and no literal to continue."""
    unfittable = "           " + "Z" * 70
    result, problems = fit_within_columns([MARKER_MOVE, unfittable])
    assert len(problems) == 1
    assert repr(unfittable) in problems[0]
    assert unfittable in result


def test_a_literal_less_line_is_broken_at_whitespace_rather_than_refused():
    """`wrap_long_literal_lines` can only continue a line that HAS a literal.
    A COBOL statement may span as many fixed-format lines as it needs, so a
    literal-less overflow needs no continuation machinery at all -- just a
    break at a space, with the remainder starting in Area B so it cannot be
    read as a new paragraph header or an 01/77 level."""
    line = "           MOVE WS-SOURCE-FIELD-NAME TO " + "Z" * 40
    assert len(line) > 72
    result, problems = fit_within_columns([line])
    assert problems == []
    assert len(result) == 2
    assert all(len(fragment) <= 72 for fragment in result)
    assert len(result[1]) - len(result[1].lstrip(" ")) >= 11
    assert " ".join(part.strip() for part in result) == line.strip()
