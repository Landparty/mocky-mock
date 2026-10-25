"""mockymock.analysis.assertion_labels: which EXPECT/VERIFY lines carry an
INTENT or CHARACTERIZATION label, and which rule ids an INTENT label cites."""

from mockymock.analysis.assertion_labels import (
    CHARACTERIZATION,
    INTENT,
    orphan_label_warnings,
    scan_assertion_labels,
    scan_label_placement,
    summarize_labels,
)

CUT = """\
TESTSUITE "S"

TESTCASE "first"
    PERFORM CALC
    *> INTENT: BR-001 and br-7 net is gross minus discount (P.cbl:12)
    *> 100.00 - 10% = 90.00
    EXPECT WS-NET TO BE 90.00
    VERIFY "DISCRATE" WAS CALLED ONCE
    *> CHARACTERIZATION: recorded
    EXPECT WS-COUNT TO BE 1

    EXPECT WS-AFTER-BLANK TO BE 2

TESTCASE "second"
    *> intent: lower-case label works too
    MOVE 1 TO WS-A
    EXPECT WS-A TO BE 1
"""


def _by_text():
    return {a.text: a for a in scan_assertion_labels(CUT)}


def test_label_covers_the_assertions_below_it_until_another_label():
    items = _by_text()
    net = items["EXPECT WS-NET TO BE 90.00"]
    assert net.label == INTENT
    assert net.case_name == "first"
    assert net.line == 7
    assert net.label_line == 5
    assert items['VERIFY "DISCRATE" WAS CALLED ONCE'].label == INTENT
    assert items["EXPECT WS-COUNT TO BE 1"].label == CHARACTERIZATION


def test_plain_comments_between_label_and_assertion_do_not_end_it():
    assert _by_text()["EXPECT WS-NET TO BE 90.00"].note.startswith("BR-001")


def test_a_blank_line_ends_a_label():
    assert _by_text()["EXPECT WS-AFTER-BLANK TO BE 2"].label is None


def test_a_label_ended_before_any_assertion_labels_the_whole_case():
    """Issue #346: a label at the top of the case used to cover nothing."""
    item = _by_text()["EXPECT WS-A TO BE 1"]
    assert item.label == INTENT
    assert item.label_line == 15
    assert item.label_scope == "case"
    assert _by_text()["EXPECT WS-NET TO BE 90.00"].label_scope == "adjacent"


def test_rule_ids_are_collected_upper_cased_and_sorted():
    assert _by_text()["EXPECT WS-NET TO BE 90.00"].rule_ids == ["BR-001", "BR-7"]


def test_summary_counts_each_label():
    counts = summarize_labels(scan_assertion_labels(CUT))
    assert counts == {
        "total": 5,
        INTENT: 3,
        CHARACTERIZATION: 1,
        "unlabelled": 1,
    }


def test_assertions_outside_a_testcase_are_ignored():
    assert scan_assertion_labels("EXPECT WS-A TO BE 1\n") == []


def test_to_dict_is_json_ready():
    item = scan_assertion_labels(CUT)[0].to_dict()
    assert item["label"] == "intent"
    assert item["ruleIds"] == ["BR-001", "BR-7"]
    assert item["case"] == "first"


TOP_OF_CASE = """\
TESTSUITE "S"

*> INTENT: BR-9 above the TESTCASE line
TESTCASE "above"
    MOCK CALL "X"
        MOVE 1 TO WS-B
    END-MOCK
    PERFORM CALC
    EXPECT WS-A TO BE 1
    *> CHARACTERIZATION: this one is recorded
    EXPECT WS-B TO BE 2

TESTCASE "mocks first"
    *> INTENT: BR-3 above the MOCK blocks
    MOCK CALL "X"
        MOVE 1 TO WS-B
    END-MOCK
    PERFORM CALC
    EXPECT WS-A TO BE 1
    VERIFY "X" WAS CALLED ONCE
    *> INTENT: after every assertion
"""


def test_labels_above_the_mock_blocks_cover_the_case():
    """The DEPTMQC shape from the field run: 0 intent, 170 unlabelled."""
    items, _ = scan_label_placement(TOP_OF_CASE)
    mocks_first = [a for a in items if a.case_name == "mocks first"]
    assert [(a.label, a.rule_ids) for a in mocks_first] == [
        (INTENT, ["BR-3"]),
        (INTENT, ["BR-3"]),
    ]


def test_a_label_above_the_testcase_line_labels_that_case():
    items, _ = scan_label_placement(TOP_OF_CASE)
    above = [a for a in items if a.case_name == "above"]
    assert [(a.label, a.label_scope) for a in above] == [
        (INTENT, "case"),
        (CHARACTERIZATION, "adjacent"),
    ]


def test_a_label_that_covers_nothing_is_an_orphan():
    _, orphans = scan_label_placement(TOP_OF_CASE)
    assert [(o.line, o.case_name) for o in orphans] == [(21, "mocks first")]
    (warning,) = orphan_label_warnings(TOP_OF_CASE)
    assert "ORPHAN_ASSERTION_LABEL" in warning
    assert ".cut line 21" in warning


def test_a_label_mid_case_before_a_directive_is_an_orphan():
    cut = (
        'TESTSUITE "S"\n'
        'TESTCASE "c"\n'
        "    EXPECT WS-A TO BE 1\n"
        "    *> INTENT: too late, a MOVE follows\n"
        "    MOVE 2 TO WS-A\n"
        "    EXPECT WS-A TO BE 2\n"
    )
    items, orphans = scan_label_placement(cut)
    assert [a.label for a in items] == [None, None]
    assert [o.line for o in orphans] == [4]


def test_a_second_label_at_the_top_replaces_the_first():
    cut = (
        'TESTSUITE "S"\n'
        'TESTCASE "c"\n'
        "    *> INTENT: first\n"
        "\n"
        "    *> CHARACTERIZATION: second\n"
        "    MOVE 2 TO WS-A\n"
        "    EXPECT WS-A TO BE 2\n"
    )
    items, orphans = scan_label_placement(cut)
    assert [a.label for a in items] == [CHARACTERIZATION]
    assert [o.line for o in orphans] == [3]


def test_a_label_above_the_testcase_counts_across_blank_lines():
    cut = (
        'TESTSUITE "S"\n'
        "*> INTENT: BR-7 rejected accounts are skipped\n"
        "\n"
        'TESTCASE "c"\n'
        "    PERFORM P\n"
        "    EXPECT WS-A TO BE 1\n"
    )
    items, orphans = scan_label_placement(cut)
    assert [(a.label, a.label_scope, a.rule_ids) for a in items] == [
        (INTENT, "case", ["BR-7"])
    ]
    assert orphans == []


def test_a_label_before_a_blank_line_and_a_mock_still_covers_nothing():
    cut = (
        'TESTSUITE "S"\n'
        "*> INTENT: dangling\n"
        "\n"
        "MOVE 1 TO WS-A\n"
        'TESTCASE "c"\n'
        "    EXPECT WS-A TO BE 1\n"
    )
    items, orphans = scan_label_placement(cut)
    assert [a.label for a in items] == [None]
    assert [o.line for o in orphans] == [2]


SUITE_LABEL = (
    'TESTSUITE "S"\n'
    "BEFORE-EACH\n"
    "    *> CHARACTERIZATION: recorded from the March batch run\n"
    '    MOCK CALL "X"\n'
    "    END-MOCK\n"
    "END-BEFORE\n"
    "\n"
    'TESTCASE "plain"\n'
    "    PERFORM P\n"
    "    EXPECT WS-A TO BE 1\n"
    "\n"
    'TESTCASE "own label"\n'
    "    PERFORM P\n"
    "    *> INTENT: BR-2\n"
    "    EXPECT WS-B TO BE 2\n"
    "    EXPECT WS-C TO BE 3\n"
    "AFTER-EACH\n"
    "    PERFORM CLEANUP\n"
    "END-AFTER\n"
)


def test_a_before_each_label_covers_the_suite():
    items, orphans = scan_label_placement(SUITE_LABEL)
    assert [(a.case_name, a.label, a.label_scope) for a in items] == [
        ("plain", CHARACTERIZATION, "suite"),
        ("own label", INTENT, "adjacent"),
        ("own label", INTENT, "adjacent"),
    ]
    assert orphans == []


def test_assertions_after_a_hook_are_not_given_to_the_previous_case():
    cut = SUITE_LABEL.replace("    PERFORM CLEANUP\n", "    EXPECT WS-Z TO BE 0\n")
    items, _ = scan_label_placement(cut)
    assert [a.case_name for a in items] == ["plain", "own label", "own label"]
