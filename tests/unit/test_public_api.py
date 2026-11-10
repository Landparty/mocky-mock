"""`mockymock.api` is the supported Python surface (see its docstring and
.okf/publishing.md). Pin its names so one is never dropped or renamed by
accident: removing a name here is a breaking change and needs a
deprecation first."""

from __future__ import annotations

from pathlib import Path

import mockymock.api as api

PUBLIC = {
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
}


def test_the_public_names_are_exactly_these():
    assert set(api.__all__) == PUBLIC


def test_every_public_name_resolves():
    for name in api.__all__:
        assert getattr(api, name) is not None, name


EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "raterte"


def test_check_and_build_through_the_api():
    """The documented library flow: parse, check, build -- no toolchain."""
    cut = EXAMPLE / "RATERTE.cut"
    suite = api.parse_cut(cut.read_text(encoding="utf-8"))
    assert isinstance(suite, api.MockTestSuite)
    assert suite.test_cases

    checked = api.run_static_checks(EXAMPLE / "RATERTE.cbl", cut, None)
    assert isinstance(checked, api.StaticCheckResult)
    assert checked.problems == []

    built = api.build_instrumented(checked, api.BuildOptions())
    assert isinstance(built, api.InstrumentedProgram)
    source = built.source()
    assert any("UT-TESTCASE" in line for line in source)
