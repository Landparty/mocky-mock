"""CAPTURE_ARG_OUT_OF_RANGE: a MOCK CALL's CAPTURE ARG <n> must not exceed
the real USING-parameter count of every site it matches ANYWHERE in the
program -- not just the ones reachable from its own test case, because
splice_program matches directives to sites by category+key alone and will
emit this directive's CAPTURE MOVEs into an unreachable site's dispatch
block too. Mirrors test_refusal_file_status.py's structure for the sibling
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

# The same program with NO narrower site anywhere: the only CALL "VALIDATE"
# takes two USING parameters, so CAPTURE ARG 2 is in range program-wide.
# Needed because the check is whole-program -- proving "an in-range capture
# does not over-refuse" requires a program where no matching site is too
# narrow, not merely one where the narrow site is unreachable.
WIDE_ONLY_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CAPWIDE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A            PIC 9(5).
       01  WS-B            PIC 9(5).
       01  WS-CAPTURED     PIC 9(5).

       PROCEDURE DIVISION.
       TWO-ARG-SITE.
           CALL "VALIDATE" USING WS-A WS-B.
"""


def _reasons_for(cut_text: str, source: str = SOURCE):
    result = parse_cobol(source, filename="capchk.cbl")
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


def test_index_within_range_of_every_site_in_the_program_does_not_refuse():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "VALIDATE"
        CAPTURE ARG 2 INTO WS-CAPTURED
    END-MOCK
    PERFORM TWO-ARG-SITE
"""
    reasons = _reasons_for(cut, WIDE_ONLY_SOURCE)
    assert not any(r.code == "CAPTURE_ARG_OUT_OF_RANGE" for r in reasons)


def test_index_exceeding_an_UNREACHABLE_matching_sites_arg_count_refuses():
    """The whole-branch review bug: this case only PERFORMs TWO-ARG-SITE, so
    ONE-ARG-SITE is unreachable from it -- but splice_program matches this
    directive against ONE-ARG-SITE anyway (category+key only, no reachability
    filter) and build_site_dispatch would raise ValueError emitting
    `CAPTURE ARG 2` there. The gate must refuse first."""
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "VALIDATE"
        CAPTURE ARG 2 INTO WS-CAPTURED
    END-MOCK
    PERFORM TWO-ARG-SITE
"""
    reasons = _reasons_for(cut)
    matches = [r for r in reasons if r.code == "CAPTURE_ARG_OUT_OF_RANGE"]
    assert len(matches) == 1
    assert "ONE-ARG-SITE" in matches[0].message
    assert "1 USING parameter" in matches[0].message


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


# `USING OMITTED WS-B`: the first position passes nothing at all.
# cobolparser reports it as a parameter named OMITTED, so the splice used to
# emit `MOVE OMITTED TO WS-CAPTURED` -- lint-clean, a cobc syntax error.
OMITTED_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CAPOMIT.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-B            PIC 9(5).
       01  WS-CAPTURED     PIC 9(5).

       PROCEDURE DIVISION.
       OMIT-SITE.
           CALL "VALIDATE" USING OMITTED WS-B.
"""


def test_capture_of_an_omitted_argument_refuses():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "VALIDATE"
        CAPTURE ARG 1 INTO WS-CAPTURED
    END-MOCK
    PERFORM OMIT-SITE
"""
    reasons = _reasons_for(cut, OMITTED_SOURCE)
    refused = [r for r in reasons if r.code == "CAPTURE_ARG_OUT_OF_RANGE"]
    assert len(refused) == 1
    assert "is OMITTED" in refused[0].message


def test_capture_of_the_argument_after_an_omitted_one_does_not_refuse():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "VALIDATE"
        CAPTURE ARG 2 INTO WS-CAPTURED
    END-MOCK
    PERFORM OMIT-SITE
"""
    reasons = _reasons_for(cut, OMITTED_SOURCE)
    assert not any(r.code == "CAPTURE_ARG_OUT_OF_RANGE" for r in reasons)
