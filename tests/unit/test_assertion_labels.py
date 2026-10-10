"""mockymock.analysis.assertion_labels: which EXPECT/VERIFY lines carry an
INTENT or CHARACTERIZATION label, and which rule ids an INTENT label cites."""

from mockymock.analysis.assertion_labels import (
    CHARACTERIZATION,
    INTENT,
    scan_assertion_labels,
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


def test_any_other_directive_ends_a_label():
    assert _by_text()["EXPECT WS-A TO BE 1"].label is None


def test_rule_ids_are_collected_upper_cased_and_sorted():
    assert _by_text()["EXPECT WS-NET TO BE 90.00"].rule_ids == ["BR-001", "BR-7"]


def test_summary_counts_each_label():
    counts = summarize_labels(scan_assertion_labels(CUT))
    assert counts == {
        "total": 5,
        INTENT: 2,
        CHARACTERIZATION: 1,
        "unlabelled": 2,
    }


def test_assertions_outside_a_testcase_are_ignored():
    assert scan_assertion_labels("EXPECT WS-A TO BE 1\n") == []


def test_to_dict_is_json_ready():
    item = scan_assertion_labels(CUT)[0].to_dict()
    assert item["label"] == "intent"
    assert item["ruleIds"] == ["BR-001", "BR-7"]
    assert item["case"] == "first"
