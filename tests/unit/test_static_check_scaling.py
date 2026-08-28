"""Equivalence tests for the indexed/precomputed replacements of the
static-check pass's linear scans.

Each helper here used to be a full scan of the scope map (or a fresh
`_falls_through` evaluation) per query, which made the whole pass
quadratic in program size -- `annotate_nested_sites` queries once per
boundary site, and the GO-TO fall-through closures walk forward from
every GO TO target inside a fixpoint loop. The replacements are pure
speedups, so what these tests pin is that they answer *exactly* what the
naive scan answered, including on the shapes that made the scan
expensive (a long chain of paragraphs none of which provably diverts, so
every walk runs to end of program).
"""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.refusal import (
    _falls_through,
    _fallthrough_flags,
    _first_non_fallthrough,
    _go_to_fallthrough_targets,
    _go_to_targets,
    _source_ordered_paragraphs,
)
from mockymock.splicer.source_map import (
    ScopeBoundary,
    ScopeMap,
    _exec_line_index,
    _inside_exec_range,
    collect_scope_map,
)


def _build(source: str):
    result = parse_cobol(source, filename="SCALE.cbl")
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    return result.ast, lines


def _fallthrough_chain_source(paragraphs: int) -> str:
    """A program in the shared-exit-label shape: every paragraph ends in a
    plain MOVE (so `_falls_through` is True for all of them) and every
    paragraph GO TOs the same exit label, so the naive closure walks from
    each target to the end of the program."""
    body = "\n".join(
        f"       {i:04d}-PARA.\n"
        f"           MOVE {i % 9} TO WS-A\n"
        f"           IF WS-A > 5\n"
        f"               GO TO 9999-EXIT\n"
        f"           END-IF\n"
        f"           MOVE {i % 7} TO WS-A."
        for i in range(paragraphs)
    )
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. CHAIN.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A                PIC 9 VALUE 0.\n"
        "       PROCEDURE DIVISION.\n"
        f"{body}\n"
        "       9999-EXIT.\n"
        "           MOVE 0 TO WS-A.\n"
    )


EXEC_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXECSCAN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           IF WS-A = 1
               EXEC SQL
                   SELECT A INTO :WS-A FROM T
               END-EXEC
           END-IF
           IF WS-A = 2
               EXEC SQL SELECT B INTO :WS-A FROM T END-EXEC
           END-IF
           MOVE 0 TO WS-A.
"""


def _naive_go_to_fallthrough(program, go_to_targets):
    """`_go_to_fallthrough_targets`' body exactly as it was before the
    precomputed-flags rewrite."""
    procedure = program.get_division("PROCEDURE")
    ordered = _source_ordered_paragraphs(procedure)
    index_by_name = {p.paragraph_name: i for i, p in enumerate(ordered)}
    section_members: dict[str, list[str]] = {}
    for section_name, section in getattr(procedure, "_sections", {}).items():
        if not section_name:
            continue
        section_members.setdefault(
            section_name, [p.paragraph_name for p in section.paragraphs]
        )
    hazard: dict[str, str] = {}
    for name in go_to_targets:
        start = index_by_name.get(name)
        if start is None:
            members = section_members.get(name)
            if not members:
                continue
            start = index_by_name.get(members[0])
            if start is None:
                continue
        cursor = start
        while _falls_through(ordered[cursor]) and cursor + 1 < len(ordered):
            cursor += 1
            hazard.setdefault(ordered[cursor].paragraph_name, name)
    return hazard


def test_fallthrough_flags_match_per_paragraph_evaluation():
    program, _ = _build(_fallthrough_chain_source(12))
    ordered = _source_ordered_paragraphs(program.get_division("PROCEDURE"))
    assert _fallthrough_flags(ordered) == [_falls_through(p) for p in ordered]


def test_first_non_fallthrough_matches_forward_search():
    falls = [True, True, False, True, False, True, True]
    expected = [
        next((j for j in range(i, len(falls)) if not falls[j]), None)
        for i in range(len(falls))
    ]
    assert _first_non_fallthrough(falls) == expected


def test_first_non_fallthrough_all_falling_is_all_none():
    assert _first_non_fallthrough([True, True, True]) == [None, None, None]


def test_go_to_fallthrough_targets_match_the_naive_walk():
    # The shape the rewrite exists for: nothing on the chain diverts, so
    # every target's walk ran to end of program in the naive version.
    program, _ = _build(_fallthrough_chain_source(40))
    targets = _go_to_targets(program)
    assert targets, "fixture must produce at least one GO TO target"
    assert _go_to_fallthrough_targets(program, targets) == _naive_go_to_fallthrough(
        program, targets
    )


def test_go_to_fallthrough_targets_stop_at_a_diverting_paragraph():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STOPCHAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           GO TO 0020-TARGET.
       0010-BEFORE.
           MOVE 1 TO WS-A.
       0020-TARGET.
           MOVE 2 TO WS-A.
       0030-FALLEN.
           GOBACK.
       0040-AFTER.
           MOVE 4 TO WS-A.
"""
    program, _ = _build(source)
    targets = _go_to_targets(program)
    hazard = _go_to_fallthrough_targets(program, targets)
    # 0030-FALLEN is fallen into; it GOBACKs, so the walk stops there and
    # 0040-AFTER is never reached. 0010-BEFORE precedes the target.
    assert set(hazard) == {"0030-FALLEN"}
    assert hazard == _naive_go_to_fallthrough(program, targets)


def test_scope_map_at_line_matches_a_full_scan():
    program, lines = _build(EXEC_SOURCE)
    scope_map = collect_scope_map(program, lines)
    assert scope_map.boundaries
    for line in range(1, len(lines) + 1):
        assert scope_map.at_line(line) == [
            b for b in scope_map.boundaries if b.line == line
        ]


def test_scope_map_iter_after_line_matches_a_full_scan():
    program, lines = _build(EXEC_SOURCE)
    scope_map = collect_scope_map(program, lines)
    for line in range(0, len(lines) + 2):
        assert list(scope_map.iter_after_line(line)) == [
            b for b in scope_map.boundaries if b.line > line
        ]


def test_scope_map_index_can_be_invalidated():
    scope_map = ScopeMap([ScopeBoundary(3, 1, "", top_level=True)])
    assert scope_map.at_line(3)
    assert scope_map.at_line(9) == []
    scope_map.boundaries.append(ScopeBoundary(9, 1, "END-IF"))
    scope_map.invalidate()
    assert [b.word for b in scope_map.at_line(9)] == ["END-IF"]
    assert [b.word for b in scope_map.iter_after_line(3)] == ["END-IF"]


def test_exec_line_index_matches_the_linear_range_scan():
    ranges = [(10, 13, 22), (20, 20, 40), (13, 15, 8)]

    def naive(line: int, column: int) -> bool:
        for start, end, end_column in ranges:
            if start <= line < end:
                return True
            if line == end and column <= end_column:
                return True
        return False

    index = _exec_line_index(ranges)
    for line in range(8, 24):
        for column in range(1, 45):
            assert _inside_exec_range(index, line, column) == naive(line, column)


def test_collect_scope_map_still_excludes_scope_words_inside_exec_blocks():
    program, lines = _build(EXEC_SOURCE)
    scope_map = collect_scope_map(program, lines)
    exec_lines = {
        i for i, text in enumerate(lines, start=1) if "EXEC SQL" in text.upper()
    }
    assert exec_lines
    # No scope word (END-IF and friends) is ever recorded from inside an
    # EXEC block: embedded SQL may legally contain such words.
    for boundary in scope_map.boundaries:
        if boundary.word and boundary.line in exec_lines:
            raise AssertionError(f"scope word {boundary.word} taken from an EXEC line")
