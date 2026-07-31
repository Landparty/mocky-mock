"""Mutation outcome model and formatters (console + JSON)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from mockymock.mutation.operators import Mutant

MutantStatus = Literal["killed", "survived", "stillborn", "timeout"]


@dataclass
class MutantResult:
    mutant: Mutant
    status: MutantStatus
    #: First failure reason for a kill; first compile/refusal line for a
    #: stillborn; empty otherwise.
    detail: str = ""


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
        "mutants": [
            {
                "line": r.mutant.line,
                "operator": r.mutant.operator,
                "description": r.mutant.description,
                "original": r.mutant.original,
                "mutated": r.mutant.mutated,
                "status": r.status,
                "detail": r.detail,
            }
            for r in outcome.results
        ],
    }
