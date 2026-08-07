"""Paragraph-scoped narrowing of the last two whole-program refusals.

PARSE_WARNING and UNRESOLVED_COPYBOOK used to refuse unconditionally,
program-wide. `check_whole_program_scoped` / `check_unresolved_copybooks_scoped`
now hold back the one provably-narrow shape -- evidence confined to a single
PROCEDURE DIVISION paragraph's own body -- and `run_static_checks` refuses it
only when the union of every SELECTED test case's reachable set (GO TO
fall-through closed) says that paragraph could execute. Everything else stays
whole-program, fail closed, and `generate`/`fixtures` (no test cases to scope
by) keep the plain unconditional entry points. See the module docstring of
mockymock/analysis/refusal.py.
"""

from types import SimpleNamespace

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.refusal import (
    _WARNING_LINE_RE,
    _has_unaccounted_label,
    _paragraph_owning_line,
    check_unresolved_copybooks,
    check_unresolved_copybooks_scoped,
    check_whole_program,
    check_whole_program_scoped,
    union_executed_paragraphs,
)
from mockymock.cli.checks import run_static_checks
from mockymock.dsl.parser import parse_cut

# An INVOKE statement parses "clean" (success=True) but is dropped from the
# AST with only a ParseResult.warnings entry. Here it sits in a paragraph
# (DIRTY-PARA) no edge from CLEAN-PARA ever reaches.
UNREACHED_INVOKE_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCOPEDW.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X                PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       CLEAN-PARA.
           MOVE 1 TO WS-X.

       DIRTY-PARA.
           INVOKE SOME-OBJECT "someMethod".
           DISPLAY "done".
"""

CLEAN_ONLY_CUT = """\
TESTSUITE "scoped warnings"

TESTCASE "clean paragraph only"
    PERFORM CLEAN-PARA
    EXPECT WS-X TO BE 1
"""

DIRTY_CUT = """\
TESTSUITE "scoped warnings"

TESTCASE "reaches the dirty paragraph"
    PERFORM DIRTY-PARA
"""


def _invoke_result():
    result = parse_cobol(UNREACHED_INVOKE_CBL, filename="scopedw.cbl")
    assert result.success, result.errors
    assert result.warnings  # precondition: the INVOKE drop is warned about
    return result


def test_dropped_content_warnings_carry_a_locatable_line_number():
    """The narrowing's load-bearing assumption about cobolparser: every
    dropped-content warning names the (normalized-text) line it dropped
    content from, in a form _WARNING_LINE_RE can find, and that line maps
    into the paragraph the content sits in. If this fails, the feature
    silently degrades to today's whole-program behavior -- safe, but then
    this pin makes the degradation loud."""
    result = _invoke_result()
    for warning in result.warnings:
        match = _WARNING_LINE_RE.search(str(warning))
        assert match is not None, result.warnings
        assert (
            _paragraph_owning_line(result.ast, int(match.group(1))) == "DIRTY-PARA"
        ), result.warnings


def test_plain_check_whole_program_still_refuses_every_warning():
    """generate/fixtures have no test cases to scope by -- the unscoped
    entry point must keep refusing paragraph-local warnings too."""
    reasons = check_whole_program(_invoke_result())
    assert any(r.code == "PARSE_WARNING" for r in reasons)


def test_scoped_variant_holds_back_a_paragraph_local_warning():
    whole, scoped = check_whole_program_scoped(_invoke_result(), UNREACHED_INVOKE_CBL)
    assert whole == []
    assert scoped
    assert {item.paragraph_name for item in scoped} == {"DIRTY-PARA"}
    for item in scoped:
        assert item.reason.code == "PARSE_WARNING"
        assert "DIRTY-PARA" in item.reason.message
        assert "DIRTY-PARA" in item.waiver_note


def test_warning_without_a_line_number_stays_whole_program():
    real = _invoke_result()
    fake = SimpleNamespace(
        success=True,
        errors=[],
        warnings=["content was dropped somewhere unlocatable"],
        ast=real.ast,
    )
    whole, scoped = check_whole_program_scoped(fake, UNREACHED_INVOKE_CBL)
    assert scoped == []
    assert any(r.code == "PARSE_WARNING" for r in whole)


def test_multi_program_unit_disables_classification():
    """Warning lines in a multi-program compilation unit can index a
    contained program the first program's paragraph map knows nothing
    about -- classification must fail closed for the whole unit."""

    class _FakeMultiProgram:
        contained_programs = [object()]

        def get_division(self, name):
            return None

    fake = SimpleNamespace(
        success=True,
        errors=[],
        warnings=["Unparsed tokens starting at 'X' at line 10 dropped"],
        ast=_FakeMultiProgram(),
    )
    whole, scoped = check_whole_program_scoped(fake, "IDENTIFICATION DIVISION.\n")
    assert scoped == []
    assert any(r.code == "PARSE_WARNING" for r in whole)


def test_run_static_checks_waives_warning_in_unreached_paragraph(tmp_path):
    cbl = tmp_path / "SCOPEDW.cbl"
    cbl.write_text(UNREACHED_INVOKE_CBL)
    cut = tmp_path / "SCOPEDW.cut"
    cut.write_text(CLEAN_ONLY_CUT)
    result = run_static_checks(cbl, cut, None)
    assert result.ok, result.problems
    assert any("waived" in note and "DIRTY-PARA" in note for note in result.notes)


def test_run_static_checks_refuses_warning_in_performed_paragraph(tmp_path):
    cbl = tmp_path / "SCOPEDW.cbl"
    cbl.write_text(UNREACHED_INVOKE_CBL)
    cut = tmp_path / "SCOPEDW.cut"
    cut.write_text(DIRTY_CUT)
    result = run_static_checks(cbl, cut, None)
    assert not result.ok
    assert any("PARSE_WARNING" in p for p in result.problems)
    assert result.notes == []


# The reachability BFS does not model falling off the end of a GO TO target
# into the next paragraph in source order -- but that paragraph executes, so
# the union gate must close over it (the same hazard shape
# _go_to_fallthrough_targets guards terminators against).
GOTO_FALLTHROUGH_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FALLW.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X                PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-X
           GO TO HOP-PARA.

       HOP-PARA.
           MOVE 2 TO WS-X.

       DIRTY-PARA.
           INVOKE SOME-OBJECT "someMethod".
"""

# Same shape, except HOP-PARA ends in an unconditional GO TO, so nothing
# ever falls through into DIRTY-PARA.
GOTO_NO_FALLTHROUGH_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOFALLW.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X                PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-X
           GO TO HOP-PARA.

       HOP-PARA.
           MOVE 2 TO WS-X
           GO TO TAIL-PARA.

       DIRTY-PARA.
           INVOKE SOME-OBJECT "someMethod".

       TAIL-PARA.
           MOVE 3 TO WS-X.
"""

MAIN_ONLY_CUT = """\
TESTSUITE "fall-through"

TESTCASE "main"
    PERFORM MAIN-PARA
"""


def test_union_includes_paragraph_fallen_into_past_a_go_to_target():
    result = parse_cobol(GOTO_FALLTHROUGH_CBL, filename="fallw.cbl")
    assert result.success, result.errors
    suite = parse_cut(MAIN_ONLY_CUT)
    union = union_executed_paragraphs(result.ast, suite)
    assert union is not None
    assert "DIRTY-PARA" in union


def test_go_to_fallthrough_into_dirty_paragraph_refuses(tmp_path):
    cbl = tmp_path / "FALLW.cbl"
    cbl.write_text(GOTO_FALLTHROUGH_CBL)
    cut = tmp_path / "FALLW.cut"
    cut.write_text(MAIN_ONLY_CUT)
    result = run_static_checks(cbl, cut, None)
    assert not result.ok
    assert any("PARSE_WARNING" in p for p in result.problems)


def test_no_fallthrough_path_waives_dirty_paragraph(tmp_path):
    result = parse_cobol(GOTO_NO_FALLTHROUGH_CBL, filename="nofallw.cbl")
    assert result.success, result.errors
    union = union_executed_paragraphs(result.ast, parse_cut(MAIN_ONLY_CUT))
    assert union is not None
    assert "DIRTY-PARA" not in union

    cbl = tmp_path / "NOFALLW.cbl"
    cbl.write_text(GOTO_NO_FALLTHROUGH_CBL)
    cut = tmp_path / "NOFALLW.cut"
    cut.write_text(MAIN_ONLY_CUT)
    checked = run_static_checks(cbl, cut, None)
    assert checked.ok, checked.problems
    assert any("waived" in note for note in checked.notes)


# --- unresolved COPY statements confined to one paragraph's body -----------

SCOPED_COPY_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCOPEDCPY.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X                PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       CLEAN-PARA.
           MOVE 1 TO WS-X.

       DIRTY-PARA.
           COPY MISSING1.

       TAIL-PARA.
           MOVE 2 TO WS-X.
"""

COPY_LINE = 13  # the `COPY MISSING1.` line above (1-based, normalized text)

COPY_CLEAN_CUT = """\
TESTSUITE "scoped copy"

TESTCASE "clean paragraph only"
    PERFORM CLEAN-PARA
    EXPECT WS-X TO BE 1
"""

COPY_DIRTY_CUT = """\
TESTSUITE "scoped copy"

TESTCASE "reaches the copy"
    PERFORM DIRTY-PARA
"""


def test_plain_check_unresolved_copybooks_still_refuses():
    reasons = check_unresolved_copybooks(SCOPED_COPY_CBL)
    assert [r.code for r in reasons] == ["UNRESOLVED_COPYBOOK"]


def test_scoped_variant_holds_back_a_paragraph_local_copy():
    result = parse_cobol(SCOPED_COPY_CBL, filename="scopedcpy.cbl")
    assert result.success, result.errors
    whole, scoped = check_unresolved_copybooks_scoped(SCOPED_COPY_CBL, result.ast)
    assert whole == []
    assert len(scoped) == 1
    item = scoped[0]
    assert item.paragraph_name == "DIRTY-PARA"
    assert item.reason.code == "UNRESOLVED_COPYBOOK"
    assert item.blank_span == (COPY_LINE, COPY_LINE)


def test_run_static_checks_waives_and_comments_out_unreached_copy(tmp_path):
    cbl = tmp_path / "SCOPEDCPY.cbl"
    cbl.write_text(SCOPED_COPY_CBL)
    cut = tmp_path / "SCOPEDCPY.cut"
    cut.write_text(COPY_CLEAN_CUT)
    result = run_static_checks(cbl, cut, None)
    assert result.ok, result.problems
    assert any("waived" in note and "COPY" in note for note in result.notes)
    # The raw COPY must never reach cobc: its line is commented out,
    # count-preservingly (no downstream line number may shift).
    blanked = result.lines[COPY_LINE - 1]
    assert blanked.lstrip().startswith("*>")
    assert "COPY MISSING1" in blanked
    assert len(result.lines) == len(SCOPED_COPY_CBL.splitlines())


def test_run_static_checks_refuses_copy_in_performed_paragraph(tmp_path):
    cbl = tmp_path / "SCOPEDCPY.cbl"
    cbl.write_text(SCOPED_COPY_CBL)
    cut = tmp_path / "SCOPEDCPY.cut"
    cut.write_text(COPY_DIRTY_CUT)
    result = run_static_checks(cbl, cut, None)
    assert not result.ok
    assert any("UNRESOLVED_COPYBOOK" in p for p in result.problems)


DATA_DIVISION_COPY_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATACPY.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY ORDREC.

       PROCEDURE DIVISION.
       CLEAN-PARA.
           DISPLAY "hello".
"""


def test_data_division_copy_stays_whole_program(tmp_path):
    """A DATA DIVISION COPY is program-global (missing WORKING-STORAGE
    fields) -- reachability must never waive it."""
    cbl = tmp_path / "DATACPY.cbl"
    cbl.write_text(DATA_DIVISION_COPY_CBL)
    cut = tmp_path / "DATACPY.cut"
    cut.write_text('TESTSUITE "s"\nTESTCASE "c"\n    PERFORM CLEAN-PARA\n')
    result = run_static_checks(cbl, cut, None)
    assert not result.ok
    assert any("UNRESOLVED_COPYBOOK" in p for p in result.problems)


SIBLING_COPY_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SIBCPY.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X                PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       CLEAN-PARA.
           MOVE 1 TO WS-X.

       DIRTY-PARA.
           MOVE 2 TO WS-X. COPY MISSING1.

       TAIL-PARA.
           MOVE 3 TO WS-X.
"""


def test_copy_sharing_a_line_with_sibling_code_stays_whole_program():
    """Commenting the COPY's whole line would delete the sibling MOVE --
    the span cannot be verified to own its lines, so the refusal must not
    be held back even though the paragraph is classifiable."""
    result = parse_cobol(SIBLING_COPY_CBL, filename="sibcpy.cbl")
    assert result.success, result.errors
    whole, scoped = check_unresolved_copybooks_scoped(SIBLING_COPY_CBL, result.ast)
    assert scoped == []
    assert [r.code for r in whole] == ["UNRESOLVED_COPYBOOK"]


# --- _paragraph_owning_line edge cases -------------------------------------

SECTIONED_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTW.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X                PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-SEC SECTION.
       MAIN-PARA.
           MOVE 1 TO WS-X.
       NEXT-SEC SECTION.
       NEXT-PARA.
           MOVE 2 TO WS-X.
"""


def test_paragraph_owning_line_classification():
    result = parse_cobol(UNREACHED_INVOKE_CBL, filename="scopedw.cbl")
    assert result.success, result.errors
    program = result.ast
    # Inside a body: owned.
    assert _paragraph_owning_line(program, 10) == "CLEAN-PARA"
    assert _paragraph_owning_line(program, 14) == "DIRTY-PARA"
    # On a paragraph header line: not a body line.
    assert _paragraph_owning_line(program, 9) is None
    # DATA DIVISION / before the first paragraph: program-global.
    assert _paragraph_owning_line(program, 6) is None
    assert _paragraph_owning_line(program, 8) is None


def test_paragraph_owning_line_in_sections():
    result = parse_cobol(SECTIONED_CBL, filename="sectw.cbl")
    assert result.success, result.errors
    program = result.ast
    # Bodies of section-member paragraphs are owned normally.
    assert _paragraph_owning_line(program, 11) == "MAIN-PARA"
    assert _paragraph_owning_line(program, 14) == "NEXT-PARA"
    # Section header lines own no body (and must not be attributed to the
    # preceding paragraph).
    assert _paragraph_owning_line(program, 12) is None
    assert _paragraph_owning_line(program, 9) is None


# --- independent label-scan safety net (Copilot review, PR #49) -----------
#
# A warning's reported line proves only where cobolparser says the drop
# STARTS -- it says nothing about whether recovery might have skipped past
# a real paragraph header while resynchronizing, silently merging that
# paragraph's content into the one the warning is attributed to and
# erasing it from the AST's own paragraph list. mockymock has no way to
# inspect cobolparser's recovery-loop internals to rule that out, so
# instead of trusting the line number on faith, `_paragraph_owning_line`
# cross-checks the candidate owner's body against mockymock's own re-lexed
# source for anything shaped like an unrecognized header line
# (`_has_unaccounted_label`). These tests construct that hazard directly
# (an extra line, independent of anything cobolparser produced) to prove
# the veto fires -- they do not depend on reproducing the actual upstream
# recovery bug, only on this module's own defensive logic.


def test_has_unaccounted_label_detects_bare_identifier_and_section_forms():
    # `_has_unaccounted_label` is a raw range-scan primitive -- it has no
    # notion of "known header," which is why callers only ever pass it a
    # range strictly BETWEEN two already-known boundaries. Line 1 here
    # (an ordinary header shape) is deliberately excluded from every
    # range below for that reason, not because the regex treats it
    # specially.
    lines = [
        "       SOME-PARA.",
        "           MOVE 1 TO WS-X.",
        "       HIDDEN-PARA.",
        "           MOVE 2 TO WS-X.",
        "       HIDDEN-SEC SECTION.",
    ]
    assert _has_unaccounted_label(lines, 2, 2) is False  # an ordinary statement
    assert _has_unaccounted_label(lines, 3, 3) is True  # bare "IDENTIFIER."
    assert _has_unaccounted_label(lines, 5, 5) is True  # "IDENTIFIER SECTION."


def test_has_unaccounted_label_ignores_ordinary_multi_token_lines():
    lines = [
        "           MOVE 1 TO WS-X.",
        '           DISPLAY "hello".',
        "           IF WS-X > 0",
        "               PERFORM CLEAN-PARA",
        "",
    ]
    assert _has_unaccounted_label(lines, 1, len(lines)) is False


def test_has_unaccounted_label_accepted_false_positive_on_scope_terminators():
    """A bare COBOL scope terminator (END-IF./EXIT./CONTINUE.) alone on
    its own line is syntactically indistinguishable from a paragraph name
    to this deliberately conservative regex, and the module docstring
    says so explicitly: an accepted false positive, not a bug -- it costs
    a classification (falls back to whole-program, today's behavior)
    rather than ever risking an unsound one."""
    assert _has_unaccounted_label(["           END-IF."], 1, 1) is True
    assert _has_unaccounted_label(["       EXIT."], 1, 1) is True


def test_label_scan_vetoes_classification_when_body_hides_a_candidate_header():
    """The core defensive check: even though line 14 maps cleanly to
    DIRTY-PARA by header position alone (test_paragraph_owning_line_
    classification, above), a body containing what looks like an
    unrecognized paragraph header must veto classification instead of
    trusting that DIRTY-PARA's apparent body boundary is really where
    cobolparser's own recovery landed."""
    result = parse_cobol(UNREACHED_INVOKE_CBL, filename="scopedw.cbl")
    assert result.success, result.errors
    program = result.ast
    clean_lines = normalize_fixed_format(UNREACHED_INVOKE_CBL.splitlines()).splitlines()
    assert _paragraph_owning_line(program, 14, clean_lines) == "DIRTY-PARA"

    hazardous_lines = list(clean_lines)
    # DIRTY-PARA's body is its last two lines (INVOKE at 13, DISPLAY at
    # 14) with no further paragraph after it -- replace the final line
    # with something that looks like a header cobolparser's AST doesn't
    # know about, simulating a swallowed paragraph boundary.
    hazardous_lines[-1] = "       SNEAKY-PARA."
    assert _paragraph_owning_line(program, 14, hazardous_lines) is None


def test_label_scan_is_the_only_difference_from_the_unguarded_call():
    """Confirms the guard is opt-in via `normalized_lines`, not a change
    to the base attribution rule: omitting it reproduces the pre-fix
    behavior exactly (needed so callers with no source text yet, if any
    ever exist, still get a defined answer)."""
    result = parse_cobol(UNREACHED_INVOKE_CBL, filename="scopedw.cbl")
    assert result.success, result.errors
    program = result.ast
    assert _paragraph_owning_line(program, 14) == "DIRTY-PARA"
