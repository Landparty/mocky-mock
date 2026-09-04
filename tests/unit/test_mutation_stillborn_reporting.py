"""Stillborn mutants must say WHY they were stillborn.

Stillborn mutants are excluded from the mutation score entirely (see
`MutationOutcome.score`), so without a reason they are a black box: a line
whose every mutant failed to compile reads exactly like a line with no
mutants at all, and a genuine coverage gap the engine could never probe
disappears behind a clean-looking score. `checks` (a mockymock static gate
rejected the mutated program before any compiler ran -- often an equivalent
mutant) and `compile` (GnuCOBOL rejected it -- a line never probed at all)
are different findings and are reported separately. The two names are
`SuiteRun.phase`'s own, carried straight through rather than re-derived.
"""

import json
from pathlib import Path

from mockymock.mutation.operators import Mutant
from mockymock.mutation.report import (
    MutantResult,
    MutationOutcome,
    format_console,
    to_json_dict,
)


def _mutant(line: int, description: str = "> becomes >=") -> Mutant:
    return Mutant(
        line=line,
        operator="relational",
        description=description,
        original=f"    IF WS-X > {line}",
        mutated=f"    IF WS-X >= {line}",
    )


def _outcome() -> MutationOutcome:
    return MutationOutcome(
        program="P.cbl",
        cut="P.cut",
        results=[
            MutantResult(mutant=_mutant(10), status="killed", detail="case 'a' failed"),
            MutantResult(
                mutant=_mutant(20),
                status="stillborn",
                detail="syntax error, unexpected TOKEN",
                stillborn_reason="compile",
            ),
            MutantResult(
                mutant=_mutant(30),
                status="stillborn",
                detail="UNMOCKED_CALL: CALL 'X' at line 30",
                stillborn_reason="checks",
            ),
            MutantResult(
                mutant=_mutant(40),
                status="stillborn",
                detail="syntax error, unexpected PERIOD",
                stillborn_reason="compile",
            ),
        ],
    )


def test_stillborn_by_reason_groups_every_stillborn():
    grouped = _outcome().stillborn_by_reason()
    assert set(grouped) == {"checks", "compile"}
    assert [r.mutant.line for r in grouped["compile"]] == [20, 40]
    assert [r.mutant.line for r in grouped["checks"]] == [30]


def test_stillborn_with_no_recorded_reason_is_grouped_not_dropped():
    """Losing a mutant from the breakdown would recreate the very black box
    this reporting exists to open."""
    outcome = MutationOutcome(
        program="P.cbl",
        cut="P.cut",
        results=[MutantResult(mutant=_mutant(7), status="stillborn")],
    )
    assert list(outcome.stillborn_by_reason()) == ["unknown"]


def test_console_report_names_each_stillborn_reason_and_its_mutants():
    text = format_console(_outcome())
    assert "stillborn mutants (never scored" in text
    assert "compile (2):" in text
    assert "GnuCOBOL rejected the mutated program" in text
    assert "checks (1):" in text
    assert "mockymock refused the mutated program" in text
    # The individual mutants, so a cluster on one paragraph is visible.
    assert "line 20 [relational] > becomes >= -- syntax error" in text
    assert "line 30 [relational] > becomes >= -- UNMOCKED_CALL" in text


def test_console_report_omits_the_section_when_nothing_was_stillborn():
    outcome = MutationOutcome(
        program="P.cbl",
        cut="P.cut",
        results=[MutantResult(mutant=_mutant(10), status="survived")],
    )
    assert "stillborn mutants (never scored" not in format_console(outcome)


def test_json_report_carries_the_reason_per_mutant_and_in_totals():
    payload = json.loads(json.dumps(to_json_dict(_outcome())))
    assert payload["stillbornByReason"] == {"checks": 1, "compile": 2}
    by_line = {m["line"]: m for m in payload["mutants"]}
    assert by_line[20]["stillbornReason"] == "compile"
    assert by_line[30]["stillbornReason"] == "checks"
    # Never invented for a non-stillborn mutant.
    assert by_line[10]["stillbornReason"] is None


def test_run_one_mutant_propagates_the_reason_from_the_pipeline_pass(monkeypatch):
    """The classification is made where the status is decided and carried
    through -- never re-derived later by pattern-matching `detail`, which
    is a raw compiler/gate line, not a category."""
    from mockymock.mutation import runner

    monkeypatch.setattr(
        runner,
        "_run_suite_once",
        lambda *a, **k: runner.SuiteRun(
            "stillborn", "cobc: syntax error", [], phase="compile"
        ),
    )
    result, _ = runner._run_one_mutant(
        _mutant(12), ["x"] * 20, "P.cbl", Path("P.cut"), None, 15
    )
    assert result.status == "stillborn"
    assert result.stillborn_reason == "compile"


def test_non_stillborn_statuses_never_carry_a_stillborn_reason(monkeypatch):
    from mockymock.mutation import runner

    for status, expected in (("passed", "survived"), ("failed", "killed")):
        monkeypatch.setattr(
            runner,
            "_run_suite_once",
            lambda *a, _status=status, **k: runner.SuiteRun(_status, "d", []),
        )
        result, _ = runner._run_one_mutant(
            _mutant(12), ["x"] * 20, "P.cbl", Path("P.cut"), None, 15
        )
        assert result.status == expected
        assert result.stillborn_reason is None
