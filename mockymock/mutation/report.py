"""Mutation outcome model and formatters (console + JSON)."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Literal

from mockymock.mutation.operators import Mutant

MutantStatus = Literal["killed", "survived", "stillborn", "timeout"]

#: Why a mutant never reached a scorable run -- `SuiteRun.phase`'s two
#: pre-run values, carried through to the report. Reported per mutant and
#: summarized in the console output, because "stillborn" alone cannot be
#: acted on: a `checks` mutant broke a mockymock precondition (the mutated
#: source no longer satisfies a static gate -- often an equivalent-mutant
#: signal you can ignore), while a `compile` mutant was rejected by GnuCOBOL
#: itself, which is a gap in the mutation engine rather than in your suite.
#: A cluster of either on lines your suite does not reach is a REAL coverage
#: gap the mutation score cannot show you, since stillborn mutants are
#: excluded from it entirely.
StillbornReason = Literal["checks", "compile"]

STILLBORN_REASON_LABELS: dict[str, str] = {
    "checks": (
        "mockymock refused the mutated program before any compiler ran (a "
        "static gate no longer holds on it) -- often an equivalent mutant, "
        "never a suite verdict"
    ),
    "compile": (
        "GnuCOBOL rejected the mutated program -- the mutation operator "
        "produced source this program cannot compile, so the suite never "
        "got to probe that line at all"
    ),
}


@dataclass
class MutantResult:
    mutant: Mutant
    status: MutantStatus
    #: First failure reason for a kill; first compile/refusal line for a
    #: stillborn; for a coverage-gated survivor, why it was not built.
    detail: str = ""
    #: False when the verdict came from the baseline's own coverage rather
    #: than from building and running this mutant. Such a mutant sits on a
    #: line the whole suite provably never executes, so it cannot change
    #: what any case observes -- `survived` is the answer, and compiling to
    #: confirm it is the work this flag records skipping.
    ran: bool = True
    #: Set only when `status == "stillborn"`: which of the two ways a mutant
    #: can be stillborn this one was, taken from `SuiteRun.phase`. `None` for
    #: every other status -- and never inferred from `detail` text, which is
    #: a raw compiler/gate line and not a classification.
    stillborn_reason: StillbornReason | None = None
    #: Set only on a survivor the suite probably cannot kill from the test
    #: data it uses (see `mutation.zero_baseline`): why, and what to change.
    #: Still scored as a survivor -- seeding the field is what kills it.
    hint: str = ""


@dataclass
class MutationOutcome:
    program: str
    cut: str
    results: list[MutantResult] = field(default_factory=list)

    def _count(self, status: MutantStatus) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def killed(self) -> int:
        return self._count("killed")

    @property
    def survived(self) -> int:
        return self._count("survived")

    @property
    def stillborn(self) -> int:
        return self._count("stillborn")

    def stillborn_by_reason(self) -> dict[str, list[MutantResult]]:
        """Every stillborn mutant grouped by why it was stillborn, in
        `STILLBORN_REASON_LABELS` order so the report reads the same way
        every run. A stillborn with no recorded reason (only possible for a
        `MutantResult` built by hand rather than by the runner) is grouped
        under `"unknown"` rather than dropped -- silently losing a mutant
        from the breakdown is exactly the black box this reporting exists
        to open."""
        grouped: dict[str, list[MutantResult]] = {}
        for reason in STILLBORN_REASON_LABELS:
            found = [
                r
                for r in self.results
                if r.status == "stillborn" and r.stillborn_reason == reason
            ]
            if found:
                grouped[reason] = found
        unknown = [
            r
            for r in self.results
            if r.status == "stillborn" and r.stillborn_reason is None
        ]
        if unknown:
            grouped["unknown"] = unknown
        return grouped

    @property
    def timeouts(self) -> int:
        return self._count("timeout")

    @property
    def not_compiled(self) -> int:
        """Mutants the baseline's coverage classified without building
        them. Scored like any other survivor -- the saving is wall-clock,
        not a change of verdict."""
        return sum(1 for r in self.results if not r.ran)

    @property
    def score(self) -> float | None:
        """killed / (killed + survived), with timeouts counting as kills
        (a mutant that hangs the program would absolutely be noticed) and
        stillborn mutants excluded entirely -- a mutant that does not
        compile says nothing about the test suite. None when no mutant
        survived long enough to be scored."""
        scored = self.killed + self.timeouts + self.survived
        if scored == 0:
            return None
        return (self.killed + self.timeouts) / scored

    def score_below(self, percent: float) -> bool:
        """True when the score is under `percent` (a 0-100 threshold, the
        `--fail-under` value), or when there is no score at all. Compared
        exactly, as fractions: `score * 100` divides before it multiplies,
        so 29/50 comes out as 57.99999999999999 -- printed as 58.0% and
        yet below a threshold of 58. The threshold goes through `str` so a
        typed 57.3 means the decimal 57.3, not its nearest binary float."""
        scored = self.killed + self.timeouts + self.survived
        if scored == 0:
            return True
        return Fraction(100 * (self.killed + self.timeouts), scored) < Fraction(
            str(percent)
        )


def format_console(outcome: MutationOutcome) -> str:
    lines: list[str] = []
    survivors = [r for r in outcome.results if r.status == "survived"]
    if survivors:
        lines.append("surviving mutants (the test suite never noticed these):")
        for result in survivors:
            m = result.mutant
            lines.append(f"  line {m.line} [{m.operator}] {m.description}")
            lines.append(f"    - {m.original.strip()}")
            lines.append(f"    + {m.mutated.strip()}")
            if result.hint:
                lines.append(f"    ! {result.hint}")
    # Stillborn mutants are excluded from the score, so without this
    # breakdown they are invisible: a line whose every mutant was stillborn
    # looks identical to a line with no mutants at all, and a real coverage
    # gap the engine could not probe reads as a clean score. Naming the
    # reason is what separates "equivalent mutant, ignore" from "the
    # mutation engine never got to test this line".
    stillborn_groups = outcome.stillborn_by_reason()
    if stillborn_groups:
        lines.append(
            "stillborn mutants (never scored -- these say nothing about the "
            "suite, so read them as gaps in what was PROBED):"
        )
        for reason, results in stillborn_groups.items():
            label = STILLBORN_REASON_LABELS.get(
                reason,
                "reason not recorded -- this mutant's status was set without one",
            )
            lines.append(f"  {reason} ({len(results)}): {label}")
            for result in results:
                m = result.mutant
                detail = f" -- {result.detail}" if result.detail else ""
                lines.append(
                    f"    line {m.line} [{m.operator}] {m.description}{detail}"
                )
    scored = outcome.killed + outcome.timeouts + outcome.survived
    lines.append(
        f"mutants: {len(outcome.results)} generated, {scored} scored "
        f"({outcome.killed} killed, {outcome.timeouts} timed out, "
        f"{outcome.survived} survived, {outcome.stillborn} stillborn)"
    )
    hinted = sum(1 for r in survivors if r.hint)
    if hinted:
        lines.append(
            f"{hinted} of those survivors cannot be killed from the test data "
            "as written (see the ! lines) -- change the starting values, not "
            "the assertions"
        )
    if outcome.not_compiled:
        lines.append(
            f"{outcome.not_compiled} of those survivors sit on lines the suite "
            "never executes -- decided from the baseline's coverage, never built"
        )
    score = outcome.score
    if score is not None:
        lines.append(f"mutation score: {score * 100:.1f}%")
    else:
        lines.append("mutation score: n/a (no scorable mutants)")
    return "\n".join(lines)


def to_json_dict(outcome: MutationOutcome) -> dict[str, Any]:
    return {
        "program": outcome.program,
        "cut": outcome.cut,
        "score": outcome.score,
        "totals": {
            "generated": len(outcome.results),
            "killed": outcome.killed,
            "timeouts": outcome.timeouts,
            "survived": outcome.survived,
            "stillborn": outcome.stillborn,
            "not_compiled": outcome.not_compiled,
        },
        "stillbornByReason": {
            reason: len(results)
            for reason, results in outcome.stillborn_by_reason().items()
        },
        "mutants": [
            {
                "line": r.mutant.line,
                "operator": r.mutant.operator,
                "description": r.mutant.description,
                "original": r.mutant.original,
                "mutated": r.mutant.mutated,
                "status": r.status,
                "detail": r.detail,
                "ran": r.ran,
                "stillbornReason": r.stillborn_reason,
                "hint": r.hint,
            }
            for r in outcome.results
        ],
    }
