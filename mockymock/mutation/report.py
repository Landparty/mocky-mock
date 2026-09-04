"""Mutation outcome model and formatters (console + JSON)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from mockymock.mutation.operators import Mutant

MutantStatus = Literal["killed", "survived", "stillborn", "timeout"]

#: Why a mutant never reached a scorable run. Reported per mutant and
#: summarized in the console report, because "stillborn" alone cannot be
#: acted on: a `refused` mutant broke a mockymock precondition (the mutated
#: source no longer satisfies a static gate -- often an equivalent-mutant
#: signal you can ignore), while a `compile_error` mutant was rejected by
#: GnuCOBOL itself (usually an operator producing invalid COBOL -- a gap in
#: the mutation engine, not in your suite). A cluster of either on lines
#: your suite does not reach is a REAL coverage gap that the mutation score
#: cannot show you, since stillborn mutants are excluded from it entirely.
StillbornReason = Literal["refused", "compile_error"]

STILLBORN_REASON_LABELS: dict[str, str] = {
    "refused": (
        "mockymock refused the mutated program (a static gate no longer "
        "holds on it) -- often an equivalent mutant, never a suite verdict"
    ),
    "compile_error": (
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
    #: stillborn; empty otherwise.
    detail: str = ""
    #: Set only when `status == "stillborn"`: which of the two ways a
    #: mutant can be stillborn this one was. `None` for every other status
    #: -- and never inferred from `detail` text, which is a raw compiler/
    #: gate line and not a classification.
    stillborn_reason: StillbornReason | None = None


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

    @property
    def timeouts(self) -> int:
        return self._count("timeout")

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
                "reason not recorded -- this mutant's status was set " "without one",
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
                "stillbornReason": r.stillborn_reason,
            }
            for r in outcome.results
        ],
    }
