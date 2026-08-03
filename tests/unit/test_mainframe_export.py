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
