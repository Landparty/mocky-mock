"""Issue #411: a merged `WHEN "a" THRU "b"` caught case 1000+.

Case ids are `f"{index:03d}"`, compared alphanumerically in
`UT-CURRENT-CASE PIC X(9)`, so `"1000"` sorts between `"100"` and `"101"`.
A THRU range is now cut wherever another case id of the dispatch sorts
inside it.
"""

from mockymock.splicer.injector import _case_selectors, merge_identical_branches
from tests.unit.test_stress_2026_11_02 import BODY, OTHER, _dispatch


def _selected(selector: str, case: str) -> bool:
    """Whether `selector` matches `case` in a PIC X(9) comparison."""
    value = case.ljust(9)
    parts = [p.strip('"').ljust(9) for p in selector.split(" THRU ")]
    if len(parts) == 1:
        return value == parts[0]
    return parts[0] <= value <= parts[1]


def test_case_1000_gets_its_own_branch():
    special = ["                   MOVE 1 TO X"]
    cases = [(f"{n:03d}", BODY) for n in range(1, 1002)]
    cases[999] = ("1000", special)
    merged = merge_identical_branches(_dispatch(cases))
    whens = [line.strip()[len("WHEN ") :] for line in merged if "WHEN " in line]
    whens = [w for w in whens if w != "OTHER"]
    # The first matching WHEN wins: every case must hit only its own branch.
    first_body = merged.index(BODY[0])
    shared = [w for w in whens if merged.index(f"               WHEN {w}") < first_body]
    for n in range(1, 1002):
        case = f"{n:03d}"
        hits = [w for w in whens if _selected(w, case)]
        assert len(hits) == 1, (case, hits)
        assert (hits[0] in shared) == (case != "1000"), case
    assert merged[-len(OTHER) :] == OTHER


def test_selectors_cut_at_an_outsider():
    ids = [f"{n:03d}" for n in range(1, 1000)] + ["1001"]
    all_ids = [*ids, "1000"]
    assert _case_selectors(ids, all_ids) == [
        '"001" THRU "100"',
        '"101" THRU "999"',
        '"1001"',
    ]


def test_no_outsider_keeps_one_range():
    ids = [f"{n:03d}" for n in range(1, 306)]
    assert _case_selectors(ids, [*ids, "SUITE"]) == ['"001" THRU "305"']
