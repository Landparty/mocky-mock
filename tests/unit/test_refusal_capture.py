"""CAPTURE_ARG_OUT_OF_RANGE: a MOCK CALL's CAPTURE ARG <n> must not exceed
the real USING-parameter count of every reachable site it matches. Mirrors
test_refusal_file_status.py's structure for the sibling
UNRESOLVED_FILE_STATUS_TARGET check."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import check_test_case
from mockymock.dsl.parser import parse_cut

# ONE-ARG-SITE and TWO-ARG-SITE both CALL "VALIDATE", with different
# USING-parameter counts, exactly the "two physical sites sharing one
# mocked key with different arg counts" shape the design doc's "Multi-site
# nuance" section describes. BOTH-SITES PERFORMs both, giving a third,
# combined reachable set for the partial-safety test below.
SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CAPCHK.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A            PIC 9(5).
       01  WS-B            PIC 9(5).
       01  WS-CAPTURED     PIC 9(5).

       PROCEDURE DIVISION.
       BOTH-SITES.
           PERFORM ONE-ARG-SITE.
           PERFORM TWO-ARG-SITE.
       ONE-ARG-SITE.
           CALL "VALIDATE" USING WS-A.
       TWO-ARG-SITE.
           CALL "VALIDATE" USING WS-A WS-B.
"""


def _reasons_for(cut_text: str):
    result = parse_cobol(SOURCE, filename="capchk.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    suite = parse_cut(cut_text)
    case = suite.test_cases[0]
    return check_test_case(surface, result.ast, case)


def test_index_within_range_of_the_only_reachable_site_does_not_refuse():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "VALIDATE"
        CAPTURE ARG 1 INTO WS-CAPTURED
    END-MOCK
    PERFORM ONE-ARG-SITE
"""
    reasons = _reasons_for(cut)
    assert not any(r.code == "CAPTURE_ARG_OUT_OF_RANGE" for r in reasons)


def test_index_within_range_of_a_two_arg_site_does_not_refuse():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "VALIDATE"
        CAPTURE ARG 2 INTO WS-CAPTURED
    END-MOCK
    PERFORM TWO-ARG-SITE
"""
    reasons = _reasons_for(cut)
    assert not any(r.code == "CAPTURE_ARG_OUT_OF_RANGE" for r in reasons)


def test_index_exceeding_the_only_reachable_sites_arg_count_refuses():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "VALIDATE"
        CAPTURE ARG 2 INTO WS-CAPTURED
    END-MOCK
    PERFORM ONE-ARG-SITE
"""
    reasons = _reasons_for(cut)
    matches = [r for r in reasons if r.code == "CAPTURE_ARG_OUT_OF_RANGE"]
    assert len(matches) == 1
    assert "ONE-ARG-SITE" in matches[0].message
    assert "1 USING parameter" in matches[0].message


def test_shared_key_partial_safety_refuses_for_the_narrower_site():
    """Both ONE-ARG-SITE and TWO-ARG-SITE are reachable and both match the
    one MOCK CALL "VALIDATE" directive -- CAPTURE ARG 2 is valid for
    TWO-ARG-SITE but exceeds ONE-ARG-SITE's single USING parameter, so
    this must refuse (fail closed over "safe for some sites")."""
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "VALIDATE"
        CAPTURE ARG 2 INTO WS-CAPTURED
    END-MOCK
    PERFORM BOTH-SITES
"""
    reasons = _reasons_for(cut)
    matches = [r for r in reasons if r.code == "CAPTURE_ARG_OUT_OF_RANGE"]
    assert len(matches) == 1
    assert "ONE-ARG-SITE" in matches[0].message


def test_directive_with_no_captures_never_refuses():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "VALIDATE"
        MOVE 0 TO RETURN-CODE
    END-MOCK
    PERFORM BOTH-SITES
"""
    reasons = _reasons_for(cut)
    assert not any(r.code == "CAPTURE_ARG_OUT_OF_RANGE" for r in reasons)
