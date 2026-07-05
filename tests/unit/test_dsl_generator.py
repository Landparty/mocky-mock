"""Tests for the .cut scaffold generator."""

from mockymock.analysis.mock_surface import CallKind, CallSite, MockSurface
from mockymock.dsl.generator import scaffold_cut
from mockymock.dsl.parser import parse_cut


def _surface() -> MockSurface:
    return MockSurface(
        call_sites=[
            CallSite(
                program_name="DISCRATE",
                kind=CallKind.STATIC,
                paragraph_name="PROCESS-ORDER",
                line=42,
            )
        ]
    )


def test_scaffold_contains_one_testcase_per_static_call_site():
    text = scaffold_cut("ORDRPROC", _surface())
    assert text.count("TESTCASE") == 1
    assert 'MOCK CALL "DISCRATE"' in text
    assert "PERFORM PROCESS-ORDER" in text


def test_scaffold_is_valid_cut_syntax():
    text = scaffold_cut("ORDRPROC", _surface())
    suite = parse_cut(text)
    assert suite.name == "ORDRPROC"
    assert len(suite.test_cases) == 1
    assert suite.test_cases[0].mocks[0].program_name == "DISCRATE"


def test_scaffold_with_no_call_sites_has_no_testcases():
    text = scaffold_cut("EMPTY", MockSurface())
    suite = parse_cut(text)
    assert suite.test_cases == []


def _two_call_surface() -> MockSurface:
    """A single paragraph with two distinct static CALLs -- the shape that
    used to walk users into an unmocked-CALL gap: one TESTCASE per site,
    each leaving the OTHER call unmocked (nowhere to link at compile time).
    """
    return MockSurface(
        call_sites=[
            CallSite(
                program_name="DISCRATE",
                kind=CallKind.STATIC,
                paragraph_name="PROCESS-ORDER",
                line=10,
            ),
            CallSite(
                program_name="TAXCALC",
                kind=CallKind.STATIC,
                paragraph_name="PROCESS-ORDER",
                line=11,
            ),
        ]
    )


def test_scaffold_groups_multi_call_paragraph_into_one_testcase():
    """A paragraph with more than one static call site must produce a single
    TESTCASE for that paragraph that mocks ALL of its call sites -- not one
    TESTCASE per site (each leaving the others unmocked and unable to
    link)."""
    text = scaffold_cut("ORDRPROC", _two_call_surface())
    assert text.count("TESTCASE") == 1
    assert 'MOCK CALL "DISCRATE"' in text
    assert 'MOCK CALL "TAXCALC"' in text
    assert text.count("PERFORM PROCESS-ORDER") == 1


def test_scaffold_multi_call_testcase_mocks_every_reachable_call_when_checked():
    """End-to-end proof that the scaffolded output no longer walks users into
    the UNMOCKED_CALL gap: parse the scaffold as a real .cut, analyze the
    same paragraph shape, and confirm check_test_case reports no
    UNMOCKED_CALL for the generated TESTCASE."""
    from cobolparser import parse_cobol

    from mockymock.analysis.mock_surface import analyze
    from mockymock.analysis.refusal import check_test_case

    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDRPROC.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       PROCESS-ORDER.
           CALL "DISCRATE" USING WS-AMOUNT WS-RATE.
           CALL "TAXCALC" USING WS-AMOUNT WS-RATE.
"""
    result = parse_cobol(source, filename="ordrproc.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)

    text = scaffold_cut("ORDRPROC", surface)
    suite = parse_cut(text)
    assert len(suite.test_cases) == 1

    case = suite.test_cases[0]
    reasons = check_test_case(surface, result.ast, case)
    assert not any(r.code == "UNMOCKED_CALL" for r in reasons)


def test_scaffold_dedupes_two_calls_to_same_program_in_one_paragraph():
    """Two CALLs to the SAME program in one paragraph (e.g. SAMEPARA's
    shape) must produce a single MOCK CALL block for that program, not a
    duplicate -- grouping is by distinct program_name within a paragraph."""
    surface = MockSurface(
        call_sites=[
            CallSite(
                program_name="DISCRATE",
                kind=CallKind.STATIC,
                paragraph_name="PARA-ONE",
                line=10,
            ),
            CallSite(
                program_name="DISCRATE",
                kind=CallKind.STATIC,
                paragraph_name="PARA-ONE",
                line=11,
            ),
        ]
    )
    text = scaffold_cut("SAMEPARA", surface)
    assert text.count("TESTCASE") == 1
    assert text.count('MOCK CALL "DISCRATE"') == 1
