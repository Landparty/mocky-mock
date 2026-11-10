"""#436: COND lists with EVEN / ONLY, tests on bypassed steps, `|` and `¬`; #441: SORT framing."""

from __future__ import annotations

import pytest

from mockymock.jobstream.conditions import ConditionError, step_runs


@pytest.mark.parametrize(
    "condition, rcs, abended, bypassed, runs",
    [
        ("((4,LT,S1),EVEN)", {"S1": 0}, False, (), True),
        ("((4,LT,S1),EVEN)", {"S1": 0}, True, (), True),
        ("((4,LT,S1),EVEN)", {"S1": 8}, False, (), False),
        ("((8,LE),ONLY)", {"S1": 0}, False, (), False),
        ("((8,LE),ONLY)", {"S1": 0}, True, (), True),
        ("((4,LT),(8,GT,S1),EVEN)", {"S1": 9}, False, (), False),
        ("(EVEN,(4,LT,S1))", {"S1": 0}, True, (), True),
        ("(0,NE,S2)", {"S1": 0}, False, {"S2"}, True),
        ("((0,NE,S2),(4,LT,S1))", {"S1": 8}, False, {"S2"}, False),
        ("(S1.RC = 0 | S1.RC = 4)", {"S1": 4}, False, (), True),
        ("(S1.RC = 0 | S1.RC = 4)", {"S1": 8}, False, (), False),
        ("¬(S1.RC = 4)", {"S1": 4}, False, (), False),
        ("(S1.RC ¬= 4)", {"S1": 0}, False, (), True),
    ],
)
def test_step_runs(condition, rcs, abended, bypassed, runs):
    assert step_runs(condition, rcs, abended, bypassed=bypassed) is runs


def test_unknown_step_is_still_a_gap():
    with pytest.raises(ConditionError):
        step_runs("(0,NE,NOSUCH)", {"S1": 0}, False)


# -- #441: SORT framing comes from the data -----------------------------------


def _lines(keys):
    return b"".join(f"CUST000{k} NAME{k:03d}".encode() + b"\n" for k in keys)


def test_line_sequential_sort_ignores_the_dcb_lrecl():
    from mockymock.jobstream.utilities import sort_data

    data = _lines([8, 3, 6, 1, 7, 2, 5, 4])  # 160 bytes: a multiple of 80
    out = sort_data(data, [("SORT", "FIELDS=(1,8,CH,A)")], 80)
    assert out == _lines(range(1, 9))


def test_key_past_a_short_line_reads_blanks():
    from mockymock.jobstream.utilities import sort_data

    data = b"B\nA  X\nA\n"
    out = sort_data(data, [("SORT", "FIELDS=(1,1,CH,A,4,1,CH,A)")], 80)
    assert out == b"A\nA  X\nB\n"


def test_fixed_records_without_newlines_still_split_by_lrecl():
    from mockymock.jobstream.utilities import sort_data

    assert sort_data(b"BBAA", [("SORT", "FIELDS=(1,2,CH,A)")], 2) == b"AABB"


def test_unframed_data_with_a_stray_newline_is_a_gap():
    from mockymock.jobstream.utilities import UtilityGap, sort_data

    with pytest.raises(UtilityGap):
        sort_data(b"AB\nCD", [("SORT", "FIELDS=(1,2,CH,A)")], None)
