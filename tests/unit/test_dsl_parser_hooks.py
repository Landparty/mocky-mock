"""Suite hooks: MOVE/PERFORM steps in BEFORE-ALL/BEFORE-EACH and the
AFTER-EACH/AFTER-ALL blocks (docs/2026-10-10-suite-hooks-design.md)."""

import pytest

from mockymock.dsl.model import HookStep, MockCategory
from mockymock.dsl.parser import CutParseError, parse_cut

FULL = """\
TESTSUITE "hooks"

BEFORE-ALL
    MOCK OPEN CUST-FILE
    END-MOCK
    MOVE "Y" TO WS-FIRST-RUN
    PERFORM 0100-INIT THRU 0100-EXIT
END-BEFORE

BEFORE-EACH
    PERFORM 0200-CLEAR-TOTALS
END-BEFORE

AFTER-EACH
    MOVE SPACES TO WS-MSG
END-AFTER

AFTER-ALL
    PERFORM 9000-CLOSE
END-AFTER

TESTCASE "one"
    PERFORM 1000-MAIN
TESTCASE "two"
    PERFORM 1000-MAIN
"""


def test_steps_are_kept_in_order_with_lines():
    suite = parse_cut(FULL)
    assert suite.before_all_steps == [
        HookStep(kind="MOVE", target="WS-FIRST-RUN", value='"Y"', line=6),
        HookStep(kind="PERFORM", target="0100-INIT", thru="0100-EXIT", line=7),
    ]
    assert suite.before_each_steps == [
        HookStep(kind="PERFORM", target="0200-CLEAR-TOTALS", line=11)
    ]
    assert suite.after_each_steps == [
        HookStep(kind="MOVE", target="WS-MSG", value="SPACES", line=15)
    ]
    assert suite.after_all_steps == [
        HookStep(kind="PERFORM", target="9000-CLOSE", line=19)
    ]
    assert suite.has_suite_phase


def test_before_all_mocks_still_desugar_and_are_kept_for_the_suite_phase():
    suite = parse_cut(FULL)
    assert [(m.category, m.key) for m in suite.before_all_mocks] == [
        (MockCategory.OPEN, "CUST-FILE")
    ]
    for case in suite.test_cases:
        assert (MockCategory.OPEN, "CUST-FILE") in {
            (m.category, m.key) for m in case.mocks
        }


def test_hook_checks_cover_every_perform_step():
    suite = parse_cut(FULL)
    checks = suite.hook_checks()
    labels = [(c.hook, c.step.target, c.for_case and c.for_case.name) for c in checks]
    assert labels == [
        ("BEFORE-ALL", "0100-INIT", None),
        ("AFTER-ALL", "9000-CLOSE", None),
        ("BEFORE-EACH", "0200-CLEAR-TOTALS", "one"),
        ("BEFORE-EACH", "0200-CLEAR-TOTALS", "two"),
    ]
    before_all = checks[0].case
    assert (before_all.perform_target, before_all.perform_thru) == (
        "0100-INIT",
        "0100-EXIT",
    )
    assert [(m.category, m.key) for m in before_all.mocks] == [
        (MockCategory.OPEN, "CUST-FILE")
    ]
    # EACH hooks run with the test case's own mocks.
    assert checks[2].case.mocks is suite.test_cases[0].mocks
    assert len(suite.analysis_cases()) == 2 + 4


def test_no_hooks_means_no_suite_phase():
    suite = parse_cut('TESTSUITE "plain"\nTESTCASE "a"\n    PERFORM P\n')
    assert not suite.has_suite_phase
    assert suite.hook_checks() == []
    assert suite.analysis_cases() == suite.test_cases


@pytest.mark.parametrize("hook", ["AFTER-EACH", "AFTER-ALL"])
def test_mock_inside_after_block_is_rejected_with_where_to_put_it(hook):
    cut = f"""\
TESTSUITE "x"
{hook}
    MOCK OPEN F
    END-MOCK
END-AFTER
TESTCASE "a"
    PERFORM P
"""
    with pytest.raises(CutParseError, match=f"MOCK not allowed inside {hook}"):
        parse_cut(cut)


@pytest.mark.parametrize(
    ("opener", "closer", "message"),
    [
        ("AFTER-ALL", "END-BEFORE", "END-BEFORE closing AFTER-ALL -- use END-AFTER"),
        ("BEFORE-ALL", "END-AFTER", "END-AFTER closing BEFORE-ALL -- use END-BEFORE"),
    ],
)
def test_wrong_terminator_is_named(opener, closer, message):
    cut = f'TESTSUITE "x"\n{opener}\n    PERFORM P\n{closer}\nTESTCASE "a"\n    PERFORM P\n'
    with pytest.raises(CutParseError, match=message):
        parse_cut(cut)


def test_end_after_without_open_block():
    with pytest.raises(CutParseError, match="END-AFTER without an open AFTER-EACH"):
        parse_cut('TESTSUITE "x"\nEND-AFTER\n')


def test_unterminated_after_block_names_end_after():
    with pytest.raises(CutParseError, match="no END-AFTER"):
        parse_cut('TESTSUITE "x"\nAFTER-EACH\n    PERFORM P\n')


def test_after_block_after_a_testcase_is_rejected():
    cut = 'TESTSUITE "x"\nTESTCASE "a"\n    PERFORM P\nAFTER-ALL\n'
    with pytest.raises(CutParseError, match="AFTER-ALL must appear before"):
        parse_cut(cut)


def test_second_after_each_is_rejected():
    cut = (
        'TESTSUITE "x"\nAFTER-EACH\n    PERFORM P\nEND-AFTER\n'
        "AFTER-EACH\n    PERFORM Q\nEND-AFTER\n"
    )
    with pytest.raises(CutParseError, match="a second AFTER-EACH block"):
        parse_cut(cut)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (
            "EXPECT WS-A TO BE 1",
            r"EXPECT not allowed inside AFTER-ALL \(only MOVE and PERFORM are\)",
        ),
        ('VERIFY CALL "X" WAS CALLED ONCE', "VERIFY not allowed inside AFTER-ALL"),
        ("PERFORM 9000-CLOSE.", "ends with a period"),
    ],
)
def test_after_block_rejects_non_steps(line, message):
    cut = f'TESTSUITE "x"\nAFTER-ALL\n    {line}\nEND-AFTER\nTESTCASE "a"\n    PERFORM P\n'
    with pytest.raises(CutParseError, match=message):
        parse_cut(cut)


def test_testcase_inside_open_after_block_names_end_after():
    cut = 'TESTSUITE "x"\nAFTER-EACH\n    PERFORM P\nTESTCASE "a"\n    PERFORM P\n'
    with pytest.raises(
        CutParseError, match="TESTCASE inside AFTER-EACH -- missing END-AFTER"
    ):
        parse_cut(cut)


def test_provider_expansion_keeps_hooks():
    cut = """\
TESTSUITE "x"
BEFORE-EACH
    PERFORM 0200-CLEAR
END-BEFORE
PROVIDER P
    HEADER A
    ROW 1
    ROW 2
TESTCASE "t {A}" USING PROVIDER P
    MOVE {A} TO WS-A
    PERFORM 1000-MAIN
"""
    suite = parse_cut(cut)
    assert len(suite.test_cases) == 2
    assert len(suite.hook_checks()) == 2


@pytest.mark.parametrize(
    ("hook", "body", "line"),
    [
        ("BEFORE-EACH", "    MOVE {val} TO WS-C", 3),
        ("AFTER-EACH", "    MOVE SPACES TO {txt}", 3),
        (
            "BEFORE-ALL",
            '    MOCK CALL "X"\n        MOVE {val} TO WS-C\n    END-MOCK',
            4,
        ),
    ],
)
def test_provider_placeholder_in_a_hook_is_refused(hook, body, line):
    """Issue #227: placeholders are substituted only into a provider-bound
    case's own MOVE/EXPECT values, so one in a hook step or hook MOCK body
    reached cobc verbatim after lint passed. Refused at the hook line, even
    though the PROVIDER is declared after the hook block."""
    end = "END-BEFORE" if hook.startswith("BEFORE") else "END-AFTER"
    cut = (
        'TESTSUITE "p1"\n'
        f"{hook}\n{body}\n{end}\n"
        "PROVIDER prv\n"
        "    HEADER val, txt\n"
        '    ROW 2, "A,B"\n'
        'TESTCASE "neg" USING PROVIDER prv\n'
        "    PERFORM 1000-CALC\n"
        "    EXPECT WS-B TO BE {txt}\n"
    )
    with pytest.raises(
        CutParseError, match=rf"line {line}: placeholder .* inside {hook}"
    ):
        parse_cut(cut)


def test_brace_text_in_a_hook_without_a_matching_column_still_parses():
    cut = (
        'TESTSUITE "p1"\n'
        "BEFORE-EACH\n"
        '    MOVE "{note}" TO WS-C\n'
        "END-BEFORE\n"
        'TESTCASE "plain"\n'
        "    PERFORM 1000-CALC\n"
    )
    assert parse_cut(cut).before_each_steps[0].value == '"{note}"'
