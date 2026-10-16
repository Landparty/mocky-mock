"""Issue #284: a paragraph name defined in two SECTIONs. Every analysis
keys paragraphs by bare name, so the reachability walk followed only the
first definition's body: a CALL only the second one reaches ran for real
after a clean lint, and the right MOCK was refused UNMATCHED_MOCK. Until
name resolution is section-aware, a case reaching such a name is refused
AMBIGUOUS_PARAGRAPH, and `generate --per-paragraph` does not scaffold it."""

import pytest
from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import check_test_case, duplicated_paragraph_names
from mockymock.dsl.generator import ProgramContext, scaffold_cut
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DP3.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       S0 SECTION.
       P-MAIN.
           PERFORM S1
           PERFORM S2.
       P-MAIN-EXIT.
           EXIT.
       S1 SECTION.
       P-INIT.
           CALL "LOG1" USING WS-A.
       S1-EXIT.
           EXIT.
       S2 SECTION.
       P-INIT.
           ADD 10 TO WS-A
           PERFORM S3.
       S2-EXIT.
           EXIT.
       S3 SECTION.
       H3.
           CALL "AUDITLOG" USING WS-A.
       S3-EXIT.
           EXIT.
"""


def _program():
    result = parse_cobol(SOURCE, filename="DP3.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(SOURCE.splitlines()).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    return result.ast, surface, lines


def _case(body: str):
    return parse_cut(f'TESTSUITE "s"\nTESTCASE "c"\n{body}').test_cases[0]


def test_duplicated_paragraph_names():
    program, _, _ = _program()
    assert duplicated_paragraph_names(program) == {"P-INIT"}


@pytest.mark.parametrize(
    "body",
    [
        # The second P-INIT reaches AUDITLOG; the walk used to follow S1's.
        '    MOCK CALL "AUDITLOG"\n        CONTINUE\n    END-MOCK\n    PERFORM S2\n',
        "    PERFORM S2\n",
        # The first P-INIT's LOG1 was demanded for a case that never runs it.
        '    MOCK CALL "LOG1"\n        CONTINUE\n    END-MOCK\n    PERFORM S1\n',
        "    PERFORM P-MAIN\n",
    ],
)
def test_case_reaching_a_duplicated_name_is_refused(body):
    program, surface, _ = _program()
    reasons = check_test_case(surface, program, _case(body))
    assert [reason.code for reason in reasons] == ["AMBIGUOUS_PARAGRAPH"]
    assert "'P-INIT'" in reasons[0].message


def test_case_clear_of_duplicated_names_is_checked_as_usual():
    program, surface, _ = _program()
    case = _case(
        '    MOCK CALL "AUDITLOG"\n        CONTINUE\n    END-MOCK\n    PERFORM S3\n'
    )
    assert check_test_case(surface, program, case) == []
    unmocked = check_test_case(surface, program, _case("    PERFORM S3\n"))
    assert [reason.code for reason in unmocked] == ["UNMOCKED_CALL"]


def test_per_paragraph_scaffold_skips_a_duplicated_name():
    program, surface, lines = _program()
    context = ProgramContext.build(program, lines, surface)
    text = scaffold_cut("DP3", surface, None, frozenset(), context)
    assert "PERFORM P-INIT" not in text
    assert "*>   P-INIT" in text
    assert "PERFORM H3" in text
