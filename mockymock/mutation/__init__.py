"""Mutation testing for `.cut` suites: mutate the program under test and
check which mutants the suite kills.

See docs/2026-07-29-mutation-testing-design.md. Public surface:
`generate_mutants` (pure, Docker-free site discovery),
`run_mutation` (the compile/run kill loop), and the report model.
"""

from mockymock.mutation.operators import Mutant, generate_mutants
from mockymock.mutation.report import (
    MutantResult,
    MutationOutcome,
    format_console,
    to_json_dict,
)
from mockymock.mutation.runner import run_mutation

__all__ = [
    "Mutant",
    "MutantResult",
    "MutationOutcome",
    "format_console",
    "generate_mutants",
    "run_mutation",
    "to_json_dict",
]
