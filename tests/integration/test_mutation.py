"""End-to-end proof for `mockymock mutate` against real GnuCOBOL: the kill
loop compiles and runs every mutant of the fixture and classifies each one.

The fixture's mutant population is pinned by
tests/unit/test_mutation_operators.py::test_fixture_yields_expected_mutant_set;
here we assert what the suite does to each of them. One mutant is a known
equivalent (deleting `MOVE 0 TO WS-TOTAL` is masked by the field's VALUE 0
plus the driver's WORKING-STORAGE reset) -- it MUST survive, which is the
honest behavior a mutation tool reports for triage rather than hiding.
"""

from __future__ import annotations

from pathlib import Path

from mockymock.mutation.runner import run_mutation
from tests.integration._docker import requires_docker

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@requires_docker
def test_mutation_kill_loop_classifies_every_mutant():
    problems, outcome, notes = run_mutation(
        FIXTURE_DIR / "mutation_target.cbl",
        FIXTURE_DIR / "mutation_target.cut",
        copybook_paths=None,
    )
    assert problems == []
    assert outcome is not None
    assert notes == []

    by_site = {(r.mutant.line, r.mutant.operator): r.status for r in outcome.results}
    assert by_site == {
        (9, "move-literal"): "killed",  # MOVE 1: total 9 != 8
        (9, "stmt-delete"): "survived",  # equivalent: VALUE 0 + driver reset
        (10, "rel-swap"): "killed",  # UNTIL >= 4: three iterations, total 6
        (10, "boundary-literal"): "killed",  # UNTIL > 5: five iterations, 10
        (11, "arith-verb-swap"): "killed",  # SUBTRACT: total -8
        (11, "stmt-delete"): "killed",  # loop body gone: total 0
    }
    assert outcome.killed == 5
    assert outcome.survived == 1
    assert outcome.stillborn == 0
    assert outcome.timeouts == 0
    assert outcome.score == 5 / 6


@requires_docker
def test_mutation_refuses_red_baseline():
    """A suite that fails on the unmutated program must abort scoring --
    every verdict would be noise."""
    wrong_cut = FIXTURE_DIR / "mutation_target_wrong.cut"
    wrong_cut.write_text(
        'TESTSUITE "wrong baseline"\n\n'
        'TESTCASE "expects the wrong total"\n'
        "    PERFORM MAIN-PARA\n"
        "    EXPECT WS-TOTAL TO BE 9\n",
        encoding="utf-8",
    )
    try:
        problems, outcome, notes = run_mutation(
            FIXTURE_DIR / "mutation_target.cbl",
            wrong_cut,
            copybook_paths=None,
        )
        assert outcome is None
        assert len(problems) == 1
        assert "baseline run is not green" in problems[0]
        assert notes == []
    finally:
        wrong_cut.unlink()
