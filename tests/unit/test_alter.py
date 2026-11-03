"""ALTER under mocks (2026-11-03): `analysis.alter`."""

from cobolparser import parse_cobol

from mockymock.analysis.alter import alter_problem, alter_reset_lines, alterations
from mockymock.analysis.flow_targets import normalize_flow_targets

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALT.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ALTER SWITCH-PARA TO PROCEED TO PATH-B
           ALTER BLANK-GO TO PROCEED TO PATH-A, SWITCH-PARA TO PATH-A
           PERFORM SWITCH-PARA THRU SWITCH-EXIT.
       SWITCH-PARA.
           GO TO PATH-A.
       BLANK-GO.
           GO TO.
       PATH-A.
           DISPLAY "A"
           GO TO SWITCH-EXIT.
       PATH-B.
           DISPLAY "B".
       SWITCH-EXIT.
           EXIT.
"""


def _program(source=SOURCE):
    result = parse_cobol(source, filename="alt.cbl")
    assert result.success, result.errors
    return result.ast


def _go_targets(program, paragraph):
    for p in program.find_all_by_type("CobolParagraph"):
        if p.paragraph_name == paragraph:
            return p.statements[0].target_paragraphs
    raise AssertionError(paragraph)


def test_alterations_collect_every_target_per_paragraph():
    assert alterations(_program()) == {
        "SWITCH-PARA": ["PATH-B", "PATH-A"],
        "BLANK-GO": ["PATH-A"],
    }


def test_the_altered_go_to_names_its_own_target_and_every_alter_target():
    program = _program()
    normalize_flow_targets(program)
    assert _go_targets(program, "SWITCH-PARA") == ["PATH-A", "PATH-B"]
    # An unaltered `GO TO.` falls into the next paragraph on GnuCOBOL.
    assert _go_targets(program, "BLANK-GO") == ["PATH-A"]
    normalize_flow_targets(program)  # idempotent
    assert _go_targets(program, "SWITCH-PARA") == ["PATH-A", "PATH-B"]


def test_each_case_starts_with_the_go_tos_as_written():
    program = _program()
    expected = [
        "ALTER SWITCH-PARA TO PROCEED TO PATH-A",
        "ALTER BLANK-GO TO PROCEED TO PATH-A",
    ]
    assert alter_reset_lines(program) == expected
    normalize_flow_targets(program)
    assert alter_reset_lines(program) == expected
    assert alter_problem(program) is None


def test_a_blank_go_to_with_nothing_after_it_refuses():
    source = SOURCE.replace(
        "       SWITCH-EXIT.\n           EXIT.\n",
        "       SWITCH-EXIT.\n           GO TO.\n",
    ).replace("PATH-A, SWITCH-PARA", "PATH-A, SWITCH-EXIT TO PATH-B, SWITCH-PARA")
    problem = alter_problem(_program(source))
    assert problem is not None and "'SWITCH-EXIT'" in problem


def test_no_alter_no_problem():
    source = SOURCE.replace(
        "           ALTER SWITCH-PARA TO PROCEED TO PATH-B\n", ""
    ).replace(
        "           ALTER BLANK-GO TO PROCEED TO PATH-A, SWITCH-PARA TO PATH-A\n", ""
    )
    program = _program(source)
    assert alterations(program) == {} and alter_reset_lines(program) == []
    assert alter_problem(program) is None
