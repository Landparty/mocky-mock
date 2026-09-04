"""Unit tests for mockymock.cli.mainframe_export -- the export-only text
transforms that make the instrumented source z/OS-compilable. See
docs/2026-08-03-mainframe-export-command-design.md for the empirical basis
(spiked against a real cobolparser install and a real GnuCOBOL container
before this code was written)."""

from mockymock.cli.mainframe_export import (
    build_provenance_header,
    insert_provenance_header,
    restore_fixed_format_columns,
    wrap_long_display_lines,
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


# --- General fixed-format wrapping (wrap_long_lines / _wrap_source_line) ----


def _unwrap(lines, max_col=72):
    """Reassemble what a fixed-format compiler reads back from a wrapped
    statement. A `-` in column 7 continues the previous line's open literal
    starting at the character after the first quote in Area B; a line that
    leaves a literal open contributes its content THROUGH column max_col
    (its trailing blanks are part of the literal -- IBM's own rule, and the
    reason `_split_literal_across_lines` fills every continued line
    exactly)."""

    def open_quote_after(segment, start_quote):
        index, quote = 0, start_quote
        while index < len(segment):
            char = segment[index]
            if quote is None:
                if char in ('"', "'"):
                    quote = char
                index += 1
            else:
                if char == quote:
                    if index + 1 < len(segment) and segment[index + 1] == quote:
                        index += 2
                        continue
                    quote = None
                index += 1
        return quote

    text = ""
    quote = None
    for line in lines:
        if len(line) > 6 and line[6] == "-":
            body = line[7:].lstrip(" ")
            assert body and body[0] == quote, (quote, body[:1])
            segment = body[1:]
            after = open_quote_after(segment, quote)
            text += segment if after is not None else segment.rstrip(" ")
        else:
            segment = line[7:]
            after = open_quote_after(segment, None)
            piece = segment if after is not None else segment.strip()
            text = (text + " " + piece.lstrip(" ")) if text else piece.strip()
        quote = after
    return text


def test_wrap_long_lines_breaks_a_statement_at_whitespace():
    """A COBOL statement may span as many fixed-format lines as it needs --
    only a literal broken across the boundary needs the column-7 `-`."""
    from mockymock.cli.mainframe_export import wrap_long_lines

    line = "                  MOVE WS-A-VERY-LONG-SOURCE-NAME-HERE TO WS-AN-EQUALLY-LONG-TARGET-NAME"
    assert len(line) > 72
    result, problems = wrap_long_lines([line])
    assert problems == []
    assert len(result) == 2
    assert all(len(fragment) <= 72 for fragment in result)
    # Continuation content starts in Area B, never Area A -- an Area A start
    # would be read as a new paragraph header or an 01/77 level number.
    assert len(result[1]) - len(result[1].lstrip(" ")) >= 11
    assert _unwrap(result) == line.strip()


def test_wrap_long_lines_continues_a_long_literal_with_the_column_7_hyphen():
    from mockymock.cli.mainframe_export import wrap_long_lines

    literal = "*** DEBUT DE LA WORKING STORAGE POUR LE PROGRAMME XYZ ***"
    line = f'                  MOVE "{literal}" TO DEBUT-WORKING-STORAGE.'
    assert len(line) > 72
    result, problems = wrap_long_lines([line])
    assert problems == []
    assert all(len(fragment) <= 72 for fragment in result)
    assert any(len(f) > 6 and f[6] == "-" for f in result)
    assert _unwrap(result) == line.strip()


def test_every_continued_line_runs_exactly_to_column_72():
    """IBM's continuation rule makes the trailing blanks of a continued line
    part of the literal, so a chunk that stopped short would silently pad the
    value with spaces. A randomized round-trip test found exactly that bug in
    the first version of this splitter."""
    from mockymock.cli.mainframe_export import wrap_long_lines

    for length in range(40, 200):
        line = '           MOVE "' + ("A" * length) + '" TO WS-TARGET-FIELD.'
        result, problems = wrap_long_lines([line])
        if problems:
            continue
        for index, fragment in enumerate(result[:-1]):
            # A fragment leaving the literal open must fill the line.
            if fragment.count('"') % 2 == 1:
                assert len(fragment) == 72, (length, index, fragment)
        assert _unwrap(result) == line.strip()


def test_wrap_long_lines_never_bisects_a_doubled_quote_escape():
    from mockymock.cli.mainframe_export import wrap_long_lines

    for prefix_length in range(1, 60):
        body = ("B" * prefix_length) + '""' + ("C" * 40)
        line = f'           MOVE "{body}" TO WS-TARGET-FIELD.'
        result, problems = wrap_long_lines([line])
        if problems:
            continue
        assert _unwrap(result) == line.strip()


def test_wrap_long_lines_leaves_short_and_comment_lines_alone():
    from mockymock.cli.mainframe_export import wrap_long_lines

    short = "           MOVE 1 TO WS-X."
    comment = "      *> " + "z" * 90
    result, problems = wrap_long_lines([short, comment])
    assert problems == []
    assert result == [short, comment]


def test_a_single_over_long_word_still_refuses():
    """The one shape with nothing to break: no literal to continue and no
    whitespace to break at."""
    from mockymock.cli.mainframe_export import wrap_long_lines

    line = "           MOVE " + "X" * 80
    result, problems = wrap_long_lines([line])
    assert len(problems) == 1
    assert "cannot be wrapped" in problems[0]
    assert result == [line]


def test_refusal_names_the_generated_reset_block_not_the_cut_file():
    """The misattribution this fixes: the old message asserted "this
    typically comes from a `.cut` file's MOCK body text" even when the
    offending line was mockymock's OWN reset-block re-serialization of a
    VALUE clause that exists only in the .cbl -- sending the reader to the
    wrong file first."""
    from mockymock.cli.mainframe_export import SourceAttribution, wrap_long_lines

    line = "           MOVE " + ("X" * 80) + " TO DEBUT-WORKING-STORAGE"
    attribution = SourceAttribution(
        driver_line_indices={0},
        cut_path="PROG.cut",
        cut_text='TESTSUITE "s"\n',
        program_path="PROG.cbl",
        program_text="       IDENTIFICATION DIVISION.\n",
    )
    _, problems = wrap_long_lines([line], attribution=attribution)
    assert len(problems) == 1
    assert "generated WORKING-STORAGE reset for DEBUT-WORKING-STORAGE" in problems[0]
    assert "PROG.cut" not in problems[0]


def test_refusal_names_the_cut_file_and_line_when_that_is_the_source():
    from mockymock.cli.mainframe_export import SourceAttribution, wrap_long_lines

    body = "MOVE " + ("X" * 80) + " TO WS-FIELD"
    attribution = SourceAttribution(
        driver_line_indices=set(),
        cut_path="PROG.cut",
        cut_text='TESTSUITE "s"\nTESTCASE "c"\n    MOCK CALL "S"\n        '
        + body
        + "\n    END-MOCK\n",
        program_path="PROG.cbl",
        program_text="       IDENTIFICATION DIVISION.\n",
    )
    _, problems = wrap_long_lines(
        ["                   " + body], attribution=attribution
    )
    assert len(problems) == 1
    assert "MOCK body text, PROG.cut line 4" in problems[0]


def test_attribution_names_the_program_when_the_text_is_only_in_the_cbl():
    """Completeness of the classifier, exercised directly: a preserved
    program line cannot itself overflow today (fixed-format columns 8-72 plus
    restore_fixed_format_columns's 7-space prefix is exactly 72), but the
    classifier must still answer "your program" for text that is only there
    -- never fall through to blaming the `.cut`."""
    from mockymock.cli.mainframe_export import SourceAttribution

    body = "MOVE WS-SOURCE-FIELD TO WS-TARGET-FIELD"
    attribution = SourceAttribution(
        driver_line_indices=set(),
        cut_path="PROG.cut",
        cut_text='TESTSUITE "s"\n',
        program_path="PROG.cbl",
        program_text="       IDENTIFICATION DIVISION.\n       " + body + "\n",
    )
    origin = attribution.origin(5, "           " + body)
    assert origin.kind == "program"
    assert "your program's own source, PROG.cbl line 2" in origin.detail


def test_refusal_says_so_when_the_text_is_in_neither_input():
    """Never blame a file the text is not in -- the whole point of the
    attribution."""
    from mockymock.cli.mainframe_export import SourceAttribution, wrap_long_lines

    attribution = SourceAttribution(
        driver_line_indices=set(),
        cut_path="PROG.cut",
        cut_text='TESTSUITE "s"\n',
        program_path="PROG.cbl",
        program_text="       IDENTIFICATION DIVISION.\n",
    )
    _, problems = wrap_long_lines(
        ["           MOVE " + "X" * 80], attribution=attribution
    )
    assert len(problems) == 1
    assert "neither your .cut nor your .cbl" in problems[0]
