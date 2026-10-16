"""Issue #308: an empty TESTCASE name is refused at its .cut line, and a
START marker with no name is still attributed to its case."""

import pytest

from mockymock.dsl.parser import CutParseError, parse_cut
from mockymock.report.results import parse_stdout


@pytest.mark.parametrize("name", ["", "   "])
def test_blank_testcase_name_is_refused(name: str) -> None:
    with pytest.raises(CutParseError, match=r"line 2: TESTCASE name is empty"):
        parse_cut(f'TESTSUITE "s"\nTESTCASE "{name}"\n    PERFORM P\n')


def test_a_start_marker_with_no_name_is_still_a_case() -> None:
    result = parse_stdout(
        "__MOCKYMOCK__ TESTSUITE: s\n"
        "__MOCKYMOCK__ CASE 001 START: \n"
        "__MOCKYMOCK__ CASE 001 FAIL: boom\n"
        "__MOCKYMOCK__ CASE 001 END\n"
    )
    (case,) = result.results
    assert case.case_id == "001" and case.case_name == ""
    assert case.failure_reasons == ["boom"]
    assert not result.orphan_failures
