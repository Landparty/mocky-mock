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
