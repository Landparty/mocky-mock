"""mockymock's public Python API.

Everything importable from this module is supported for library use and
changes only with a deprecation period. Every other module under
`mockymock` is internal: importable, but free to move or change in any
release (the `mockymock` command line is the other supported surface).

    from mockymock.api import BuildOptions, build_instrumented, run_static_checks

    checked = run_static_checks(program, cut, copybook_paths=None)
    if not checked.problems:
        program_lines = build_instrumented(checked, BuildOptions()).source()

Typical uses:

* parse a `.cut` suite: `parse_cut(text) -> MockTestSuite`;
* run the same static checks `mockymock lint` / `run` start with:
  `run_static_checks(program, cut, copybook_paths) -> StaticCheckResult`;
* build the instrumented COBOL a run compiles:
  `build_instrumented(checked, BuildOptions(...)) -> InstrumentedProgram`;
* read a test binary's output back: `parse_stdout(stdout) -> TestSuiteResult`;
* read the project config: `load_config(start_dir) -> MockymockConfig`.
"""

from __future__ import annotations

from mockymock import __version__
from mockymock.dsl.model import MockDirective, MockTestCase, MockTestSuite
from mockymock.dsl.parser import parse_cut
from mockymock.engine.build import BuildOptions, InstrumentedProgram, build_instrumented
from mockymock.engine.checks import StaticCheckResult, run_static_checks
from mockymock.project.config import ConfigError, MockymockConfig, load_config
from mockymock.report.results import TestResult, TestSuiteResult, parse_stdout

__all__ = [
    "BuildOptions",
    "ConfigError",
    "InstrumentedProgram",
    "MockDirective",
    "MockTestCase",
    "MockTestSuite",
    "MockymockConfig",
    "StaticCheckResult",
    "TestResult",
    "TestSuiteResult",
    "__version__",
    "build_instrumented",
    "load_config",
    "parse_cut",
    "parse_stdout",
    "run_static_checks",
]
