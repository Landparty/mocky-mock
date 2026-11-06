"""report.branch_coverage: coverage points from the AST, outcomes from the
trace order (no toolchain needed: traces are written by hand)."""

from cobolparser import parse_cobol

from mockymock._lines import split_source_lines
from mockymock.report.branch_coverage import (
    NO_WHEN,
    measure,
    program_points,
    program_report,
    split_by_program,
)
from mockymock.report.trace import TraceEntry, parse_trace

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF A = 1
               MOVE 2 TO A
           END-IF
           IF A = 2 MOVE 1 TO A ELSE MOVE 3 TO A END-IF
           EVALUATE A
             WHEN 1
               MOVE 4 TO A
           END-EVALUATE
           STOP RUN.
       OTHER-PARA.
           DISPLAY A.
"""


def _points():
    lines = split_source_lines(SOURCE)
    ast = parse_cobol(SOURCE, filename="P.cbl").ast
    return program_points(ast, lines)


def _stmt(line, verb):
    return TraceEntry(line=line, statement=verb, paragraph=None, program="P")


def _para(line, name):
    return TraceEntry(line=line, statement=None, paragraph=name, program="P")


IDENTITY = {n: n for n in range(1, 40)}


def test_points_cover_paragraphs_branches_and_statements():
    points = _points()
    assert [(p.name, p.line) for p in points.paragraphs] == [
        ("MAIN-PARA", 7),
        ("OTHER-PARA", 17),
    ]
    kinds = [(b.kind, b.line) for b in points.branches]
    assert kinds == [("IF", 8), ("IF", 11), ("EVALUATE", 12)]
    one_line_if = points.branches[1]
    assert one_line_if.not_measurable == "THEN and ELSE start on the same line"
    assert points.branches[2].outcomes[-1].label == NO_WHEN


def test_if_without_else_false_when_next_statement_is_after_it():
    points = _points()
    measure(
        points,
        [
            _para(7, "MAIN-PARA"),
            _stmt(8, "IF"),
            _stmt(11, "IF"),
            _stmt(12, "EVALUATE"),
            _stmt(13, "WHEN"),
            _stmt(16, "STOP RUN"),
        ],
        IDENTITY,
    )
    first, _, evaluate = points.branches
    assert [o.hits for o in first.outcomes] == [0, 1]
    # Only "no WHEN matched" has no statement: decided by elimination.
    assert [o.hits for o in evaluate.outcomes] == [0, 1]
    report = program_report(points, "P.cbl", lambda line: (None, line))
    assert report["branches"]["total"] == 4  # the one-line IF is not counted
    assert report["branches"]["notMeasurable"] == 1
    assert report["paragraphs"]["covered"] == 1
    assert {"line": 18} in report["statements"]["uncovered"]


def test_true_outcome_and_unmapped_splicer_lines_are_skipped():
    points = _points()
    to_normalized = dict(IDENTITY)
    to_normalized.pop(30)  # a splicer line between the IF and its body
    measure(
        points,
        [
            _stmt(8, "IF"),
            _stmt(30, "MOVE"),
            _stmt(9, "MOVE"),
            _stmt(12, "EVALUATE"),
            _stmt(13, "WHEN"),
            _stmt(14, "MOVE"),
        ],
        to_normalized,
    )
    first, _, evaluate = points.branches
    assert [o.hits for o in first.outcomes] == [1, 0]
    assert [o.hits for o in evaluate.outcomes] == [1, 0]


def test_trace_end_right_after_a_branch_is_unattributed():
    points = _points()
    measure(points, [_stmt(8, "IF")], IDENTITY)
    assert points.branches[0].unattributed == 1
    assert all(o.hits == 0 for o in points.branches[0].outcomes)


def test_trace_entries_keep_their_program_id():
    text = (
        "Source: 'X.cbl'\n"
        "Program-Id:  MAINP\n"
        "Program-Id:  MAINP           |           IF                  |     8\n"
        "Program-Id:  SUBP            |Paragraph: S-PARA              |     3\n"
    )
    entries = parse_trace(text)
    assert [e.program for e in entries] == ["MAINP", "SUBP"]
    split = split_by_program(entries, ["mainp", "SUBP"])
    assert [len(split["MAINP"]), len(split["SUBP"])] == [1, 1]
