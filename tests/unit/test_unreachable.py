"""report.unreachable: which coverage points no test can reach, from
cobol-parser's InputDependenceAnalyzer and the measured outcomes."""

from cobolparser import parse_cobol

from mockymock._lines import split_source_lines
from mockymock.dsl.parser import parse_cut
from mockymock.report.branch_coverage import (
    format_branch_coverage_console,
    measure,
    program_points,
    program_report,
)
from mockymock.report.trace import TraceEntry
from mockymock.report.unreachable import (
    SCOPE_FULL,
    SCOPE_STATIC,
    classify,
    suite_entries,
)

# A is never changed by an input: `IF A = 1` always goes the same way, so
# its THEN is unreachable. B is ACCEPTed: `IF B = 1` can go either way.
# DEAD-PARA follows STOP RUN and nothing PERFORMs it.
SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC 9 VALUE 0.
       01 B PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT B
           IF A = 1
               DISPLAY "FAIL"
           END-IF
           IF B = 1
               DISPLAY "ONE"
           END-IF
           STOP RUN.
       DEAD-PARA.
           DISPLAY A.
"""

IDENTITY = {n: n for n in range(1, 40)}


def _stmt(line, verb):
    return TraceEntry(line=line, statement=verb, paragraph=None, program="P")


def _measured():
    ast = parse_cobol(SOURCE, filename="P.cbl").ast
    points = program_points(ast, split_source_lines(SOURCE))
    measure(
        points,
        [
            TraceEntry(line=8, statement=None, paragraph="MAIN-PARA", program="P"),
            _stmt(9, "ACCEPT"),
            _stmt(10, "IF"),
            _stmt(13, "IF"),
            _stmt(16, "STOP RUN"),
        ],
        IDENTITY,
    )
    return ast, points


def _suite(body):
    return parse_cut(f'TESTSUITE "P"\n\nTESTCASE "one"\n{body}')


def test_input_independent_outcome_and_dead_code_are_unreachable():
    ast, points = _measured()
    found = classify(ast, points, _suite("    PERFORM MAIN-PARA\n"))
    assert found is not None and found.scope == SCOPE_FULL
    assert "DEAD-PARA" in found.paragraphs
    assert set(found.outcomes) == {("IF", 10)}
    assert 0 in found.outcomes[("IF", 10)]  # THEN of IF A = 1
    assert 11 in found.statements and 14 not in found.statements

    report = program_report(points, "P.cbl", lambda line: (None, line), found)
    assert report["unreachableScope"] == SCOPE_FULL
    assert report["paragraphs"]["unreachable"] == 1
    assert report["branches"]["unreachable"] == 1
    if_a = report["branches"]["items"][0]
    assert "unreachable" in if_a["outcomes"][0]
    console = format_branch_coverage_console([report])
    assert "reachable" in console
    assert "DEAD-PARA" not in console  # not a gap any more
    assert "line 13" in console  # IF B = 1 never took its THEN: a real gap


def test_a_case_starting_elsewhere_keeps_only_static_claims():
    ast, points = _measured()
    found = classify(ast, points, _suite("    PERFORM DEAD-PARA\n"))
    assert found is not None and found.scope == SCOPE_STATIC
    assert "DEAD-PARA" in (found.note or "")
    assert found.outcomes == {}


def test_a_flow_mock_keeps_only_static_claims():
    ast, points = _measured()
    suite = _suite(
        "    MOCK PARAGRAPH DEAD-PARA\n    END-MOCK\n    PERFORM MAIN-PARA\n"
    )
    performs, _moves, flow = suite_entries(suite)
    assert performs == {"MAIN-PARA"} and flow
    found = classify(ast, points, suite)
    assert found is not None and found.scope == SCOPE_STATIC
    assert found.note == "a case mocks a paragraph or section"


def test_setup_moves_are_inputs():
    ast, points = _measured()
    performs, moves, _flow = suite_entries(
        _suite("    MOVE 1 TO A\n    PERFORM MAIN-PARA\n")
    )
    assert "A" in {m.upper() for m in moves}
    found = classify(ast, points, _suite("    MOVE 1 TO A\n    PERFORM MAIN-PARA\n"))
    assert found is not None and ("IF", 10) not in found.outcomes


def test_report_without_classification_has_no_unreachable_keys():
    _ast, points = _measured()
    report = program_report(points, "P.cbl", lambda line: (None, line))
    assert "unreachableScope" not in report
    assert "unreachable" not in report["branches"]


# -- #446: runs that do not start from VALUE-clause storage ---------------------


def test_case_calling_the_program_twice_drops_to_static():
    ast, points = _measured()
    found = classify(
        ast, points, _suite("    PERFORM MAIN-PARA\n    PERFORM MAIN-PARA\n")
    )
    assert found is not None and found.scope == SCOPE_STATIC
    assert found.note == "a case calls the program more than once"
    assert found.outcomes == {}


def test_before_all_running_program_code_drops_to_static():
    ast, points = _measured()
    suite = parse_cut(
        'TESTSUITE "P"\n\nBEFORE-ALL\n    PERFORM MAIN-PARA\nEND-BEFORE\n\n'
        'TESTCASE "one"\n    PERFORM MAIN-PARA\n'
    )
    found = classify(ast, points, suite)
    assert found is not None and found.scope == SCOPE_STATIC
    assert found.note == "BEFORE-ALL / AFTER-ALL runs program code"


def test_taken_outcome_is_never_reported(monkeypatch):
    import cobolparser.analysis.input_dependence as dep

    ast, points = _measured()
    branch = next(b for b in points.branches if b.line == 10)
    original = dep.InputDependenceReport.unreachable

    def unreachable(self, taken, executed_lines=None):
        found = original(self, taken, executed_lines)
        # An analysis that also prunes an outcome the run took.
        hit = next(iter(taken[(branch.kind, branch.line)]))
        found.outcomes.setdefault((branch.kind, branch.line), {})[hit] = "pruned"
        return found

    monkeypatch.setattr(dep.InputDependenceReport, "unreachable", unreachable)
    found = classify(ast, points, _suite("    PERFORM MAIN-PARA\n"))
    assert found is not None
    taken = {i for i, o in enumerate(branch.outcomes) if o.hits > 0}
    assert not taken & set(found.outcomes.get((branch.kind, branch.line), {}))
