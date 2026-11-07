# mockymock MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `mockymock`, a CLI that mocks static `CALL` statements in a COBOL program, compiles the instrumented copy with GnuCOBOL, runs it, and reports pass/fail — proving the splice→compile→run→assert loop end to end on the smallest possible mocking surface.

**Architecture:** `cobolparser` (sibling, editable-installed) supplies the AST. `mockymock` composes existing `cobolparser` analyzers into a "mock surface," parses a `.cut` test file into a DSL model, splices `MOCK`/driver code into the program's *normalized free-form* source (never the original fixed-format text — see Global Constraints), compiles with `cobc -free -x`, runs the binary, and parses `__MOCKYMOCK__`-prefixed stdout lines into structured results.

**Tech Stack:** Python >=3.11, `cobolparser` (editable sibling dependency), GnuCOBOL (`cobc`, external system dependency bootstrapped by the CLI), pytest.

**Source spec:** [`docs/2026-06-30-mockymock-mvp-design.md`](../../2026-06-30-mockymock-mvp-design.md) — read it first; this plan implements it and resolves two implementation-level questions the spec deliberately left open (statement-span detection, exact stdout wire format) since those required reading `cobolparser` source to answer correctly.

## Global Constraints

- Python `>=3.11`, matching `cobolparser`'s floor.
- Zero hard PyPI runtime dependencies (matches `cobolparser`/`jclparser` convention). `cobolparser` is consumed via editable sibling install (`-e ../cobol-parser`), never listed in `[project.dependencies]`. `pytest>=7.0` and `pytest-cov>=4.0` are the only dev dependencies (matches the dev-extras pattern already used by `cobolparser`'s and `jclparser`'s own `pyproject.toml`).
- Package/CLI name: `mockymock`. Test file extension: `.cut`.
- v1 mocks **only static `CALL "LITERAL"` statements**. No file I/O mocking, no DISPLAY mocking, no EXEC SQL/CICS/DLI mocking, no dynamic-CALL mocking. The `splicer/` package is written against a category-agnostic abstraction so these can be added later without touching `stub_writer.py`.
- One compiled binary per `TESTSUITE` (all its `TESTCASE`s dispatch via a generated `EVALUATE UT-CURRENT-CASE`), not one binary per case.
- **Splice and compile the same normalized free-form text `cobolparser` parses** (`cobolparser.preprocess.normalize_fixed_format()`'s output) — never the original fixed-format file. This is required because `SourceLocation.line` (verified against `cobolparser/lexer.py` and `cobolparser/parser.py`) refers to lines in that normalized text, and `normalize_fixed_format()` drops comment lines entirely (no line-mapping back to the original exists). Compile with `cobc -free -x`. The generated artifact will not textually resemble the user's original fixed-format file (comments gone, continuations merged) — this is expected, not a bug.
- GnuCOBOL is acquired via `mockymock setup` (driving `choco`/`brew`/`apt-get`, package name `gnucobol` on all three — verified), never vendored inside the package.
- Refusal model (two granularities, both required): whole-program refusal when `cobolparser` reports parse errors; per-`TESTCASE` refusal when that case's `PERFORM` target paragraph contains a dynamic CALL, file I/O statement, or `EXEC SQL`/`EXEC CICS`/`EXEC DLI` block, or when a `.cut` file's `MOCK CALL "X"` doesn't match any static CALL site reachable from that case's target.
- stdout wire format (defines the contract between generated COBOL and `report/results.py` — see Task 4 for why this differs from the spec's illustrative `PASS:`/`FAIL:` lines):
  ```
  __MOCKYMOCK__ TESTSUITE: <suite name>
  __MOCKYMOCK__ CASE <id> START: <case name>
  __MOCKYMOCK__ CASE <id> FAIL: <reason>      (zero or more, one per failed check)
  __MOCKYMOCK__ CASE <id> END
  __MOCKYMOCK__ SUMMARY: RUN=<n> FAILURES=<n>
  ```

---

## Task 1: Repository Skeleton

**Files:**
- Create: `mocky-mock/pyproject.toml`
- Create: `mocky-mock/mockymock/__init__.py`
- Create: `mocky-mock/mockymock/cli/__init__.py`
- Create: `mocky-mock/mockymock/cli/main.py`
- Create: `mocky-mock/requirements-dev.txt`
- Create: `mocky-mock/.gitignore`
- Create: `mocky-mock/README.md`
- Create: `mocky-mock/interface-contract.md`
- Test: `mocky-mock/tests/unit/test_smoke.py`

**Interfaces:**
- Produces: `mockymock.__version__: str`; `mockymock.cli.main:main() -> int`, the `[project.scripts]` entry point every later CLI task extends.

- [ ] **Step 1: Write the failing smoke test**

```python
# tests/unit/test_smoke.py
def test_cobolparser_is_importable_and_parses():
    from cobolparser import parse_cobol

    result = parse_cobol(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. X.\n", filename="x.cbl"
    )
    assert result.ast is not None


def test_mockymock_has_a_version():
    import mockymock

    assert mockymock.__version__ == "0.1.0"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd mocky-mock && python -m pytest tests/unit/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock'` (and `cobolparser` not yet installed either).

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "mockymock"
version = "0.1.0"
description = "Mock COBOL CALL statements, compile with GnuCOBOL, run, and assert"
authors = [
    {name = "Samuel Dion"}
]
readme = "README.md"
requires-python = ">=3.11"
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Software Development :: Testing",
]
keywords = ["cobol", "mainframe", "testing", "gnucobol", "mocking"]
dependencies = []

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
]

[project.scripts]
mockymock = "mockymock.cli.main:main"

[tool.setuptools.packages.find]
include = ["mockymock*"]
```

- [ ] **Step 4: Write `mockymock/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 5: Write a minimal `mockymock/cli/main.py`**

```python
"""mockymock CLI entry point. Subcommands are added by later tasks."""

from __future__ import annotations

import argparse
import sys

from mockymock import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mockymock")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_subparsers(dest="command")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

And `mockymock/cli/__init__.py` (empty file).

- [ ] **Step 6: Write `requirements-dev.txt`**

```
-e ../cobol-parser
-e .[dev]
```

- [ ] **Step 7: Write `.gitignore`**

```
__pycache__/
*.pyc
*.egg-info/
.pytest_cache/
.coverage
htmlcov/
build/
dist/
.venv/
venv/
```

- [ ] **Step 8: Write a short `README.md`**

```markdown
# mockymock

Mocks static `CALL` statements in a COBOL program, compiles the instrumented
copy with GnuCOBOL, runs it, and reports pass/fail.

See `docs/2026-06-30-mockymock-mvp-design.md` for the design and
`docs/2026-06-30-mockymock-mvp-plan.md` for the implementation plan this
repo was built from.

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
mockymock setup           # installs GnuCOBOL if not already on PATH
python -m pytest tests/unit -v
```

`tests/integration/` additionally requires `cobc` on PATH and is skipped
automatically if it isn't found.
```

- [ ] **Step 9: Write `interface-contract.md`**

```markdown
# Interface Contract: mockymock ↔ cobolparser

mockymock depends on cobolparser; cobolparser has no knowledge of mockymock.
This documents exactly which cobolparser exports mockymock relies on, so a
cobolparser change that breaks one of these is a breaking change for
mockymock too.

- `cobolparser.parse_cobol(source: str, filename: str) -> ParseResult`
  - `.ast: CobolProgram | None`, `.success: bool`, `.errors: list[ParseError]`
- `cobolparser.expand_copybooks` / `cobolparser.parse_cobol_with_expansion`
- `cobolparser.preprocess.normalize_fixed_format(lines: list[str]) -> str`
  — mockymock splices THIS output, not the original file. See Global
  Constraints in the implementation plan for why.
- `cobolparser.CobolProgram.get_division(name: str) -> CobolDivision | None`
- `cobolparser.models.program.CobolDivision.paragraphs: list[CobolParagraph]`
  and `._sections: dict[str, CobolSection]` (each section has `.paragraphs`)
- `cobolparser.models.program.CobolParagraph.paragraph_name: str`,
  `.statements: list[CobolStatement]`, `.location: SourceLocation`
- `cobolparser.models.ast_base.SourceLocation.line: int` — refers to lines
  in the NORMALIZED free-form text, not the original file.
- `cobolparser.models.statements.call.CallStatement.called_program: str | None`,
  `.is_dynamic: bool` (property)
- `cobolparser.models.statements.control.PerformStatement.target_paragraph: str | None`
- `cobolparser.models.data_items.CobolDataItem.name`, `.level`,
  `.picture_clause: PictureClause | None`, `.value_clause: str | None`, `.usage`
- `cobolparser.models.data_items.PictureClause.pattern: str`
- `cobolparser.analysis.DynamicCallAnalyzer().analyze(ast)`
- `cobolparser.HostVariableResolver`, `cobolparser.IMSSegmentAnalyzer`,
  `cobolparser.IOLogger` — used by `mock_surface.py` to detect (not mock)
  EXEC SQL/CICS/DLI and file I/O for the refusal gate.
```

- [ ] **Step 10: Install and run the test**

Run:
```bash
cd mocky-mock
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements-dev.txt
python -m pytest tests/unit/test_smoke.py -v
```
Expected: PASS (2 passed).

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml mockymock/ requirements-dev.txt .gitignore README.md interface-contract.md tests/unit/test_smoke.py
git commit -m "feat: repository skeleton with cobolparser dependency"
```

---

## Task 2: GnuCOBOL Bootstrap

**Files:**
- Create: `mockymock/runtime/__init__.py`
- Create: `mockymock/runtime/gnucobol_bootstrap.py`
- Modify: `mockymock/cli/main.py`
- Test: `tests/unit/test_gnucobol_bootstrap.py`

**Interfaces:**
- Consumes: nothing from prior tasks beyond the package skeleton.
- Produces: `find_cobc() -> GnuCobolInfo | None`; `bootstrap(install: bool = True) -> GnuCobolInfo`; `GnuCobolNotFoundError`. Later tasks (Task 3 onward) call `find_cobc()` to skip integration tests when `cobc` is unavailable.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gnucobol_bootstrap.py
from unittest.mock import MagicMock, patch

import pytest

from mockymock.runtime.gnucobol_bootstrap import (
    GnuCobolInfo,
    GnuCobolNotFoundError,
    bootstrap,
    find_cobc,
)


def test_find_cobc_returns_none_when_not_on_path():
    with patch("shutil.which", return_value=None):
        assert find_cobc() is None


def test_find_cobc_returns_info_when_present():
    with patch("shutil.which", return_value="/usr/bin/cobc"):
        with patch(
            "subprocess.run",
            return_value=MagicMock(stdout="cobc (GnuCOBOL) 3.2.0\n"),
        ):
            info = find_cobc()
    assert info == GnuCobolInfo(
        path="/usr/bin/cobc", version="cobc (GnuCOBOL) 3.2.0"
    )


def test_bootstrap_skips_install_when_already_found():
    with patch("shutil.which", return_value="/usr/bin/cobc"):
        with patch(
            "subprocess.run",
            return_value=MagicMock(stdout="cobc (GnuCOBOL) 3.2.0\n"),
        ) as run:
            info = bootstrap()
    run.assert_called_once()
    assert info.path == "/usr/bin/cobc"


def test_bootstrap_installs_via_apt_on_linux_when_missing():
    with patch("shutil.which", side_effect=[None, "/usr/bin/cobc"]):
        with patch("platform.system", return_value="Linux"):
            with patch("subprocess.run") as run:
                run.return_value = MagicMock(stdout="cobc (GnuCOBOL) 3.2.0\n")
                info = bootstrap()
    install_call = run.call_args_list[0]
    assert install_call.args[0] == ["sudo", "apt-get", "install", "-y", "gnucobol"]
    assert info.path == "/usr/bin/cobc"


def test_bootstrap_raises_when_still_missing_after_install_attempt():
    with patch("shutil.which", return_value=None):
        with patch("platform.system", return_value="Linux"):
            with patch("subprocess.run") as run:
                run.return_value = MagicMock(stdout="", returncode=1)
                with pytest.raises(GnuCobolNotFoundError):
                    bootstrap()
    run.assert_called_once_with(
        ["sudo", "apt-get", "install", "-y", "gnucobol"], check=False
    )


def test_bootstrap_raises_immediately_when_install_false_and_missing():
    with patch("shutil.which", return_value=None):
        with pytest.raises(GnuCobolNotFoundError):
            bootstrap(install=False)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_gnucobol_bootstrap.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock.runtime'`

- [ ] **Step 3: Write `mockymock/runtime/__init__.py`** (empty file)

- [ ] **Step 4: Write `mockymock/runtime/gnucobol_bootstrap.py`**

```python
"""Detect and bootstrap a GnuCOBOL (cobc) installation.

Package name on choco/brew/apt is `gnucobol` on all three platforms
(verified against community.chocolatey.org/packages/gnucobol,
formulae.brew.sh/formula/gnucobol, and Ubuntu/Debian package listings).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass


class GnuCobolNotFoundError(RuntimeError):
    """Raised when cobc cannot be found, or installed, on this machine."""


@dataclass
class GnuCobolInfo:
    path: str
    version: str


def find_cobc() -> GnuCobolInfo | None:
    """Return GnuCobolInfo if `cobc` is on PATH, else None."""
    path = shutil.which("cobc")
    if path is None:
        return None
    result = subprocess.run(
        [path, "--version"], capture_output=True, text=True, check=False
    )
    first_line = result.stdout.splitlines()[0] if result.stdout else "unknown"
    return GnuCobolInfo(path=path, version=first_line)


_INSTALL_COMMANDS: dict[str, list[str]] = {
    "Windows": ["choco", "install", "gnucobol", "-y"],
    "Darwin": ["brew", "install", "gnucobol"],
    "Linux": ["sudo", "apt-get", "install", "-y", "gnucobol"],
}

_MANUAL_INSTALL_URL = "https://gnucobol.sourceforge.io/"


def bootstrap(install: bool = True) -> GnuCobolInfo:
    """Find cobc, installing it via the platform package manager if missing.

    Raises GnuCobolNotFoundError if cobc is still unavailable after an
    install attempt, or immediately if install=False and cobc is missing.
    """
    found = find_cobc()
    if found is not None:
        return found

    system = platform.system()
    command = _INSTALL_COMMANDS.get(system)
    if not install or command is None:
        raise GnuCobolNotFoundError(
            f"cobc not found on PATH and no install command for platform "
            f"'{system}'. Install GnuCOBOL manually: {_MANUAL_INSTALL_URL}"
        )

    print(f"mockymock: cobc not found, attempting: {' '.join(command)}")
    subprocess.run(command, check=False)

    found = find_cobc()
    if found is None:
        raise GnuCobolNotFoundError(
            f"cobc still not found on PATH after running "
            f"'{' '.join(command)}'. Install GnuCOBOL manually: "
            f"{_MANUAL_INSTALL_URL}"
        )
    return found
```

- [ ] **Step 5: Run it to verify it passes**

Run: `python -m pytest tests/unit/test_gnucobol_bootstrap.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Wire `mockymock setup` into the CLI**

Modify `mockymock/cli/main.py`:

```python
"""mockymock CLI entry point."""

from __future__ import annotations

import argparse
import sys

from mockymock import __version__


def _cmd_setup(args: argparse.Namespace) -> int:
    from mockymock.runtime.gnucobol_bootstrap import (
        GnuCobolNotFoundError,
        bootstrap,
    )

    try:
        info = bootstrap()
    except GnuCobolNotFoundError as exc:
        print(f"mockymock setup: {exc}")
        return 1
    print(f"mockymock setup: found cobc at {info.path} ({info.version})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mockymock")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")

    setup_parser = subparsers.add_parser(
        "setup", help="Detect or install GnuCOBOL (cobc)"
    )
    setup_parser.set_defaults(func=_cmd_setup)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Manually verify the CLI command**

Run: `mockymock setup`
Expected: either `mockymock setup: found cobc at ...` (exit 0) or an install attempt followed by the same line, or a clear `GnuCobolNotFoundError` message (exit 1) if the package manager isn't available. On the Windows dev machine this plan was written on, `choco install gnucobol -y` requires Chocolatey to already be installed and an elevated shell — if it fails, install GnuCOBOL manually once via the Chocolatey GUI or `choco install gnucobol -y` in an admin PowerShell, then re-run `mockymock setup` to confirm detection.

- [ ] **Step 8: Commit**

```bash
git add mockymock/runtime/ mockymock/cli/main.py tests/unit/test_gnucobol_bootstrap.py
git commit -m "feat: GnuCOBOL bootstrap and mockymock setup command"
```

---

## Task 3: Walking Skeleton — Compile and Run a Hand-Written Program

This task proves the `cobc` integration works end to end with **zero mockymock codegen involved** — a hand-written program, not a generated one. This is deliberately sequenced before the splicer/DSL work: GnuCOBOL availability and behavior on this machine is the single biggest risk in this project, and it's cheaper to find out now than after building five more modules on top of an assumption that doesn't hold.

**Files:**
- Create: `mockymock/runtime/sandbox.py`
- Create: `mockymock/runtime/compiler.py`
- Create: `mockymock/runtime/executor.py`
- Create: `tests/integration/__init__.py` (empty)
- Create: `tests/integration/fixtures/walking_skeleton.cbl`
- Test: `tests/integration/test_walking_skeleton.py`

**Interfaces:**
- Consumes: `mockymock.runtime.gnucobol_bootstrap.find_cobc` (Task 2) to decide whether to skip.
- Produces: `sandbox_dir() -> ContextManager[Path]`; `compile_source(source_path: Path, cobc_path: str = "cobc") -> CompileResult` (`.success: bool`, `.binary_path: Path | None`, `.stdout: str`, `.stderr: str`); `run_binary(binary_path: Path, timeout_seconds: int = 30) -> ExecutionResult` (`.exit_code: int`, `.stdout: str`, `.stderr: str`). Tasks 4 and 15 build directly on these.

- [ ] **Step 1: Write the hand-written fixture**

```cobol
       identification division.
       program-id. walking-skeleton.

       procedure division.
       main-para.
           display "__MOCKYMOCK__ TESTSUITE: walking skeleton"
           display "__MOCKYMOCK__ CASE 001 START: proves the runtime loop works"
           display "__MOCKYMOCK__ CASE 001 END"
           display "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0"
           stop run.
```

Save as `tests/integration/fixtures/walking_skeleton.cbl`.

- [ ] **Step 2: Write the failing test**

```python
# tests/integration/test_walking_skeleton.py
import shutil
from pathlib import Path

import pytest

from mockymock.runtime.compiler import compile_source
from mockymock.runtime.executor import run_binary
from mockymock.runtime.sandbox import sandbox_dir

FIXTURE = Path(__file__).parent / "fixtures" / "walking_skeleton.cbl"

requires_gnucobol = pytest.mark.skipif(
    shutil.which("cobc") is None, reason="GnuCOBOL (cobc) not installed"
)


@requires_gnucobol
def test_walking_skeleton_compiles_and_runs():
    with sandbox_dir() as tmp:
        source_copy = tmp / "walking_skeleton.cbl"
        source_copy.write_text(FIXTURE.read_text())

        compiled = compile_source(source_copy)
        assert compiled.success, compiled.stderr

        executed = run_binary(compiled.binary_path)

    assert executed.exit_code == 0
    assert "__MOCKYMOCK__ TESTSUITE: walking skeleton" in executed.stdout
    assert "__MOCKYMOCK__ CASE 001 START:" in executed.stdout
    assert "__MOCKYMOCK__ CASE 001 END" in executed.stdout
    assert "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0" in executed.stdout
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python -m pytest tests/integration/test_walking_skeleton.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock.runtime.sandbox'` (or skipped with "GnuCOBOL (cobc) not installed" if `cobc` genuinely isn't present yet — if so, run `mockymock setup` first, per Task 2, before continuing).

- [ ] **Step 4: Write `mockymock/runtime/sandbox.py`**

```python
"""Temporary sandbox directories for compiling and running COBOL programs."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def sandbox_dir() -> Iterator[Path]:
    """Yield a fresh temp directory, removed on exit."""
    path = Path(tempfile.mkdtemp(prefix="mockymock-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
```

- [ ] **Step 5: Write `mockymock/runtime/compiler.py`**

```python
"""Wraps `cobc` to compile a free-form COBOL source file."""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CompileResult:
    success: bool
    binary_path: Path | None
    stdout: str
    stderr: str


def compile_source(source_path: Path, cobc_path: str = "cobc") -> CompileResult:
    """Compile a free-form COBOL source file into an executable.

    Output binary is written next to source_path, same stem, with the
    platform's executable suffix (.exe on Windows, none elsewhere).
    """
    suffix = ".exe" if platform.system() == "Windows" else ""
    binary_path = source_path.with_suffix(suffix)
    result = subprocess.run(
        [cobc_path, "-free", "-x", str(source_path), "-o", str(binary_path)],
        capture_output=True,
        text=True,
        cwd=source_path.parent,
        check=False,
    )
    success = result.returncode == 0 and binary_path.exists()
    return CompileResult(
        success=success,
        binary_path=binary_path if success else None,
        stdout=result.stdout,
        stderr=result.stderr,
    )
```

- [ ] **Step 6: Write `mockymock/runtime/executor.py`**

```python
"""Runs a compiled COBOL test binary and captures its output."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str


def run_binary(binary_path: Path, timeout_seconds: int = 30) -> ExecutionResult:
    """Run a compiled binary in its own directory, capturing stdout/stderr."""
    result = subprocess.run(
        [str(binary_path)],
        capture_output=True,
        text=True,
        cwd=binary_path.parent,
        timeout=timeout_seconds,
        check=False,
    )
    return ExecutionResult(
        exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr
    )
```

- [ ] **Step 7: Run it to verify it passes**

Run: `python -m pytest tests/integration/test_walking_skeleton.py -v`
Expected: PASS (1 passed), assuming `cobc` is on PATH. If `compile_source` fails, read `compiled.stderr` — common cause on Windows is a `cobc` install that needs its MinGW/`cob` runtime DLLs on PATH too; the GnuCOBOL Windows installer/choco package handles this, but if you built from source check `gnucobol --info` output for the configured `COB_LIBRARY_PATH`.

- [ ] **Step 8: Commit**

```bash
git add mockymock/runtime/sandbox.py mockymock/runtime/compiler.py mockymock/runtime/executor.py tests/integration/
git commit -m "feat: walking skeleton proves compile+run loop against real cobc"
```

---

## Task 4: Result Parsing and Reporting

**Files:**
- Create: `mockymock/report/__init__.py`
- Create: `mockymock/report/results.py`
- Create: `mockymock/report/formatters.py`
- Test: `tests/unit/test_report.py`

**Interfaces:**
- Consumes: nothing executable from prior tasks; defines the parser for the stdout wire format Task 3's fixture already emits.
- Produces: `TestResult(case_id: str, case_name: str, failure_reasons: list[str])` with `.passed: bool` property; `TestSuiteResult(suite_name: str, results: list[TestResult], tests_run: int, failures: int)` with `.all_passed: bool` property; `parse_stdout(stdout: str) -> TestSuiteResult`; `format_console(suite: TestSuiteResult) -> str`; `format_junit_xml(suite: TestSuiteResult) -> str`. Task 15 (CLI `run` command) is the consumer.

A note on why the wire format isn't the spec's illustrative `PASS:`/`FAIL:` lines: the spec's worked example (§5.2) can emit two independent `FAIL` lines for one test case (one for `EXPECT`, one for `VERIFY`) using two different message strings, which makes per-case aggregation ambiguous from text alone. The `CASE <id> START`/`FAIL`/`END` bracketing below fixes that: a case's outcome is "any FAIL between its START and END," unambiguously, regardless of how many independent checks it has.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_report.py
from mockymock.report.formatters import format_console, format_junit_xml
from mockymock.report.results import parse_stdout

SAMPLE_STDOUT = """\
__MOCKYMOCK__ TESTSUITE: ORDRPROC discount calculation
__MOCKYMOCK__ CASE 001 START: 10% discount reduces net amount correctly
__MOCKYMOCK__ CASE 001 END
__MOCKYMOCK__ CASE 002 START: Zero discount leaves amount unchanged
__MOCKYMOCK__ CASE 002 FAIL: expected WS-NET-AMOUNT = 50.00, got 49.99
__MOCKYMOCK__ CASE 002 FAIL: VERIFY DISCRATE WAS CALLED ONCE
__MOCKYMOCK__ CASE 002 END
__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=2
"""


def test_parse_stdout_extracts_suite_name():
    suite = parse_stdout(SAMPLE_STDOUT)
    assert suite.suite_name == "ORDRPROC discount calculation"


def test_parse_stdout_extracts_summary_counts():
    suite = parse_stdout(SAMPLE_STDOUT)
    assert suite.tests_run == 2
    assert suite.failures == 2


def test_parse_stdout_groups_two_failures_under_one_case():
    suite = parse_stdout(SAMPLE_STDOUT)
    assert len(suite.results) == 2
    case_002 = suite.results[1]
    assert case_002.case_id == "002"
    assert case_002.passed is False
    assert case_002.failure_reasons == [
        "expected WS-NET-AMOUNT = 50.00, got 49.99",
        "VERIFY DISCRATE WAS CALLED ONCE",
    ]


def test_parse_stdout_case_with_no_fail_lines_passes():
    suite = parse_stdout(SAMPLE_STDOUT)
    case_001 = suite.results[0]
    assert case_001.passed is True
    assert case_001.failure_reasons == []


def test_all_passed_is_false_when_any_failure():
    suite = parse_stdout(SAMPLE_STDOUT)
    assert suite.all_passed is False


def test_all_passed_is_true_for_clean_run():
    clean = (
        "__MOCKYMOCK__ TESTSUITE: X\n"
        "__MOCKYMOCK__ CASE 001 START: only case\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
    )
    assert parse_stdout(clean).all_passed is True


def test_format_console_lists_each_case_and_reasons():
    suite = parse_stdout(SAMPLE_STDOUT)
    output = format_console(suite)
    assert "[PASS]" in output
    assert "[FAIL]" in output
    assert "VERIFY DISCRATE WAS CALLED ONCE" in output


def test_format_junit_xml_is_well_formed_and_has_failures():
    suite = parse_stdout(SAMPLE_STDOUT)
    xml_text = format_junit_xml(suite)
    assert '<testsuite name="ORDRPROC discount calculation"' in xml_text
    assert xml_text.count("<testcase") == 2
    assert xml_text.count("<failure") == 2
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock.report'`

- [ ] **Step 3: Write `mockymock/report/__init__.py`** (empty file)

- [ ] **Step 4: Write `mockymock/report/results.py`**

```python
"""Parses __MOCKYMOCK__-prefixed stdout lines into structured results."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_TESTSUITE_RE = re.compile(r"^__MOCKYMOCK__ TESTSUITE: (?P<name>.+)$")
_CASE_START_RE = re.compile(r"^__MOCKYMOCK__ CASE (?P<id>\S+) START: (?P<name>.+)$")
_CASE_FAIL_RE = re.compile(r"^__MOCKYMOCK__ CASE (?P<id>\S+) FAIL: (?P<reason>.+)$")
_CASE_END_RE = re.compile(r"^__MOCKYMOCK__ CASE (?P<id>\S+) END$")
_SUMMARY_RE = re.compile(
    r"^__MOCKYMOCK__ SUMMARY: RUN=(?P<run>\d+) FAILURES=(?P<failures>\d+)$"
)


@dataclass
class TestResult:
    case_id: str
    case_name: str
    failure_reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failure_reasons


@dataclass
class TestSuiteResult:
    suite_name: str
    results: list[TestResult] = field(default_factory=list)
    tests_run: int = 0
    failures: int = 0

    @property
    def all_passed(self) -> bool:
        return self.failures == 0 and self.tests_run > 0


def parse_stdout(stdout: str) -> TestSuiteResult:
    """Parse a compiled test binary's captured stdout into a TestSuiteResult."""
    suite = TestSuiteResult(suite_name="")
    by_id: dict[str, TestResult] = {}

    for line in stdout.splitlines():
        if (m := _TESTSUITE_RE.match(line)) is not None:
            suite.suite_name = m.group("name")
        elif (m := _CASE_START_RE.match(line)) is not None:
            result = TestResult(case_id=m.group("id"), case_name=m.group("name"))
            by_id[result.case_id] = result
            suite.results.append(result)
        elif (m := _CASE_FAIL_RE.match(line)) is not None:
            target = by_id.get(m.group("id"))
            if target is not None:
                target.failure_reasons.append(m.group("reason"))
        elif (m := _SUMMARY_RE.match(line)) is not None:
            suite.tests_run = int(m.group("run"))
            suite.failures = int(m.group("failures"))
        # _CASE_END_RE intentionally not handled: END only matters for the
        # COBOL-side bracketing, not for parsing — failures are matched to
        # cases purely by id, so an END marker carries no information here.

    return suite
```

- [ ] **Step 5: Write `mockymock/report/formatters.py`**

```python
"""Console and JUnit XML formatters for TestSuiteResult."""

from __future__ import annotations

from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring

from mockymock.report.results import TestSuiteResult


def format_console(suite: TestSuiteResult) -> str:
    lines = [f"TESTSUITE: {suite.suite_name}"]
    for result in suite.results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(f"  [{status}] {result.case_name}")
        for reason in result.failure_reasons:
            lines.append(f"         {reason}")
    lines.append(f"{suite.tests_run} run, {suite.failures} failed")
    return "\n".join(lines)


def format_junit_xml(suite: TestSuiteResult) -> str:
    testsuite_el = Element(
        "testsuite",
        name=suite.suite_name,
        tests=str(suite.tests_run),
        failures=str(suite.failures),
    )
    for result in suite.results:
        testcase_el = SubElement(testsuite_el, "testcase", name=result.case_name)
        for reason in result.failure_reasons:
            failure_el = SubElement(testcase_el, "failure", message=reason)
            failure_el.text = reason
    rough = tostring(testsuite_el, encoding="unicode")
    return minidom.parseString(rough).toprettyxml(indent="  ")
```

- [ ] **Step 6: Run it to verify it passes**

Run: `python -m pytest tests/unit/test_report.py -v`
Expected: PASS (8 passed).

- [ ] **Step 7: Commit**

```bash
git add mockymock/report/ tests/unit/test_report.py
git commit -m "feat: parse __MOCKYMOCK__ stdout output into structured results"
```

---

## Task 5: Mock Surface Analyzer

**Files:**
- Create: `mockymock/analysis/__init__.py`
- Create: `mockymock/analysis/mock_surface.py`
- Test: `tests/unit/test_mock_surface.py`

**Interfaces:**
- Consumes: `cobolparser.parse_cobol`, `cobolparser.analysis.DynamicCallAnalyzer`, `cobolparser.HostVariableResolver`, `cobolparser.IMSSegmentAnalyzer`, `cobolparser.IOLogger` (all verified against source in Task-0 research, see `interface-contract.md`).
- Produces: `CallKind` enum (`STATIC`, `DYNAMIC`); `CallSite(program_name: str | None, kind: CallKind, paragraph_name: str, line: int)`; `MockSurface(call_sites: list[CallSite], file_io_paragraphs: set[str], exec_paragraphs: set[str])` with `.static_call_sites()` / `.dynamic_call_sites()`; `analyze(program: CobolProgram) -> MockSurface`. Tasks 6 (refusal gate) and 13 (`.cut` scaffolding generator) consume this.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mock_surface.py
from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import CallKind, analyze

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDER-FILE ASSIGN TO "ORDERS"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ORDER-FILE.
       01  ORDER-RECORD       PIC X(11).

       WORKING-STORAGE SECTION.
       01  WS-PGM-NAME        PIC X(8) VALUE "DISCRATE".
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       PROCESS-ORDER.
           CALL "DISCRATE" USING WS-AMOUNT WS-RATE.

       DYNAMIC-DISPATCH.
           CALL WS-PGM-NAME USING WS-AMOUNT.

       READ-AN-ORDER.
           READ ORDER-FILE
               AT END DISPLAY "EOF"
           END-READ.
"""


def _ast():
    result = parse_cobol(SOURCE, filename="sample.cbl")
    assert result.success, result.errors
    return result.ast


def test_classifies_static_call_site():
    surface = analyze(_ast())
    static = surface.static_call_sites()
    assert len(static) == 1
    assert static[0].program_name == "DISCRATE"
    assert static[0].paragraph_name == "PROCESS-ORDER"
    assert static[0].kind is CallKind.STATIC


def test_classifies_dynamic_call_site():
    surface = analyze(_ast())
    dynamic = surface.dynamic_call_sites()
    assert len(dynamic) == 1
    assert dynamic[0].paragraph_name == "DYNAMIC-DISPATCH"
    assert dynamic[0].kind is CallKind.DYNAMIC


def test_detects_file_io_paragraph():
    surface = analyze(_ast())
    assert "READ-AN-ORDER" in surface.file_io_paragraphs


def test_paragraph_without_file_io_is_not_flagged():
    surface = analyze(_ast())
    assert "PROCESS-ORDER" not in surface.file_io_paragraphs
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_mock_surface.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock.analysis'`

- [ ] **Step 3: Write `mockymock/analysis/__init__.py`** (empty file)

- [ ] **Step 4: Write `mockymock/analysis/mock_surface.py`**

```python
"""Composes cobolparser analyzers into a single mock-surface report.

v1 only mocks STATIC CALL sites. Dynamic CALL sites, file I/O, and EXEC
SQL/CICS/DLI are *detected* here (for the refusal gate in Task 6) but not
mockable — that's the modularity seam for later categories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from cobolparser.models.program import CobolDivision, CobolParagraph
from cobolparser.models.statements.call import CallStatement
from cobolparser.models.statements.io import (
    IOCloseStatement,
    IODeleteStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOWriteStatement,
)


class CallKind(Enum):
    STATIC = "static"
    DYNAMIC = "dynamic"


@dataclass
class CallSite:
    program_name: str | None  # literal name if STATIC, None if DYNAMIC
    kind: CallKind
    paragraph_name: str
    line: int


@dataclass
class MockSurface:
    call_sites: list[CallSite] = field(default_factory=list)
    file_io_paragraphs: set[str] = field(default_factory=set)
    exec_paragraphs: set[str] = field(default_factory=set)

    def static_call_sites(self) -> list[CallSite]:
        return [c for c in self.call_sites if c.kind is CallKind.STATIC]

    def dynamic_call_sites(self) -> list[CallSite]:
        return [c for c in self.call_sites if c.kind is CallKind.DYNAMIC]


_FILE_IO_TYPES = (
    IOOpenStatement,
    IOCloseStatement,
    IOReadStatement,
    IOWriteStatement,
    IORewriteStatement,
    IODeleteStatement,
)


def analyze(program) -> MockSurface:
    """Walk PROCEDURE DIVISION and classify every CALL/file-IO statement."""
    surface = MockSurface()
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return surface

    for paragraph in _all_paragraphs(procedure):
        for statement in paragraph.statements:
            if isinstance(statement, CallStatement):
                kind = CallKind.DYNAMIC if statement.is_dynamic else CallKind.STATIC
                surface.call_sites.append(
                    CallSite(
                        program_name=None if statement.is_dynamic else statement.called_program,
                        kind=kind,
                        paragraph_name=paragraph.paragraph_name,
                        line=statement.location.line,
                    )
                )
            elif isinstance(statement, _FILE_IO_TYPES):
                surface.file_io_paragraphs.add(paragraph.paragraph_name)
            elif statement.node_type in ("EXEC_SQL", "EXEC_CICS", "EXEC_DLI"):
                surface.exec_paragraphs.add(paragraph.paragraph_name)

    return surface


def _all_paragraphs(procedure_division: CobolDivision) -> list[CobolParagraph]:
    """Mirrors CoverageAnalyzer._analyze_paragraphs's traversal pattern."""
    paragraphs = list(procedure_division.paragraphs)
    for section in procedure_division._sections.values():
        paragraphs.extend(section.paragraphs)
    return paragraphs
```

- [ ] **Step 5: Run it to verify it passes**

Run: `python -m pytest tests/unit/test_mock_surface.py -v`
Expected: PASS (4 passed). If `IOReadStatement` (or any of the `_FILE_IO_TYPES`/`node_type` EXEC strings) doesn't import or match, this is the moment to open `cobolparser/models/statements/io.py` and `cobolparser/parsers/statements/ibm_exec_statements.py` directly and correct the class/string names against what's actually there — don't guess a fix, read the source, exactly the way the SourceLocation question was resolved while writing this plan.

- [ ] **Step 6: Commit**

```bash
git add mockymock/analysis/ tests/unit/test_mock_surface.py
git commit -m "feat: mock surface analyzer classifies static/dynamic CALL and detects file/EXEC"
```

- [ ] **Step 7: Recursive descent into nested statement bodies (amendment — required, not optional)**

Task 5 as originally drafted only walked `paragraph.statements` — the flat, top-level list. That misses every `CALL`/file-I/O/EXEC statement nested inside an `IF`, `EVALUATE`, an inline `PERFORM ... END-PERFORM`, or an IO statement's `AT END`/`INVALID KEY`/`AT END-OF-PAGE` clause body. Since Task 6 (refusal gate) exists specifically to catch dangerous statements before they reach an unmocked compile/run, a detection gap here directly weakens that safety guarantee — a `CALL` hidden inside an `IF` would silently pass refusal instead of blocking it. This step closes that gap by making `analyze()` recurse.

Verified nested-statement attribute names, read directly from `cobolparser` source (do not re-guess these):
- `IfStatement.then_statements: list[CobolStatement]`, `.else_statements: list[CobolStatement]` (`cobolparser/models/statements/control.py:197-198`)
- `EvaluateStatement.when_clauses: list[WhenClause]`, `.default_when: WhenClause | None`; each `WhenClause.statements: list[CobolStatement]` (`cobolparser/models/statements/control.py:100-101`, `:26`)
- `PerformStatement.inline_statements: list[CobolStatement]` — populated for inline `PERFORM ... END-PERFORM`, distinct from `.target_paragraph` used for `PERFORM paragraph-name` (`cobolparser/models/statements/control.py:240`)
- IO statements' clause bodies: `at_end_clause`, `not_at_end_clause`, `invalid_key_clause`, `not_invalid_key_clause`, `at_eop_clause` — all `list[CobolStatement] | None` (`cobolparser/models/statements/io.py:85-88,190-192`)
- `CallStatement.on_exception`, `.not_on_exception`, `.on_overflow` — all `list[CobolStatement] | None` (`cobolparser/models/statements/call.py:34-36`)

Add to `mockymock/analysis/mock_surface.py`:

```python
from cobolparser.models.statements.control import EvaluateStatement

_NESTED_STATEMENT_ATTRS = (
    "then_statements",
    "else_statements",
    "inline_statements",
    "at_end_clause",
    "not_at_end_clause",
    "invalid_key_clause",
    "not_invalid_key_clause",
    "at_eop_clause",
    "on_exception",
    "not_on_exception",
    "on_overflow",
)


def _nested_statement_lists(statement) -> list[list]:
    lists = [
        value
        for attr in _NESTED_STATEMENT_ATTRS
        if (value := getattr(statement, attr, None))
    ]
    if isinstance(statement, EvaluateStatement):
        for when in statement.when_clauses:
            if when.statements:
                lists.append(when.statements)
        if statement.default_when is not None and statement.default_when.statements:
            lists.append(statement.default_when.statements)
    return lists
```

Replace the flat `for statement in paragraph.statements:` loop in `analyze()` with a recursive walk that classifies each statement (same `if isinstance(statement, CallStatement): ... elif isinstance(statement, _FILE_IO_TYPES): ... elif isinstance(statement, (ExecSQLStatement, ExecCicsStatement, ExecImsStatement)): ...` body as before) and then recurses into every list returned by `_nested_statement_lists(statement)`, still attributing findings to the same enclosing `paragraph.paragraph_name` (nesting depth doesn't change which paragraph a refusal-gate check cares about).

- [ ] **Step 8: Add nested-statement tests**

Add to `tests/unit/test_mock_surface.py`: a paragraph with `CALL "NESTED-DISCRATE"` inside an `IF` (asserting it's classified as a static call site with the correct paragraph name), a paragraph with a `READ` whose `AT END` clause contains a `CALL`, and a paragraph with an inline `PERFORM ... END-PERFORM` containing `EXEC SQL`. Each should be detected exactly as if it were top-level.

- [ ] **Step 9: Run the full suite and re-commit**

Run: `python -m pytest tests/ -v`
Expected: all tests pass (new nested-statement tests included), no regressions in the four originally-passing tests.

```bash
git add mockymock/analysis/mock_surface.py tests/unit/test_mock_surface.py
git commit -m "fix: recurse into nested statement bodies in mock surface analysis"
```

---

## Task 6: Refusal Gate

**Files:**
- Create: `mockymock/analysis/refusal.py`
- Test: `tests/unit/test_refusal.py`

**Interfaces:**
- Consumes: `mockymock.analysis.mock_surface.{analyze, MockSurface}` (Task 5); `cobolparser.parse_cobol`; `cobolparser.models.statements.control.PerformStatement.target_paragraph`.
- Produces: `RefusalReason` dataclass (`code: str`, `message: str`); `check_whole_program(parse_result) -> list[RefusalReason]`; `check_test_case(surface: MockSurface, program, perform_target: str, mocked_call_names: set[str]) -> list[RefusalReason]`. Task 12 (driver generation) and Task 14 (CLI `run`) call these before splicing.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_refusal.py
from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import check_test_case, check_whole_program

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PGM-NAME        PIC X(8) VALUE "DISCRATE".
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       SAFE-PARAGRAPH.
           CALL "DISCRATE" USING WS-AMOUNT WS-RATE.

       DYNAMIC-PARAGRAPH.
           CALL WS-PGM-NAME USING WS-AMOUNT.

       WRAPPER-PARAGRAPH.
           PERFORM DYNAMIC-PARAGRAPH.
"""


def _result():
    result = parse_cobol(SOURCE, filename="sample.cbl")
    assert result.success, result.errors
    return result


def test_whole_program_check_passes_for_clean_parse():
    assert check_whole_program(_result()) == []


def test_whole_program_check_flags_parse_errors():
    bad = parse_cobol("NOT EVEN VALID COBOL { } [ ]", filename="bad.cbl")
    reasons = check_whole_program(bad)
    assert any(r.code == "PARSE_ERROR" for r in reasons)


def test_per_case_check_allows_static_call_only_paragraph():
    result = _result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "SAFE-PARAGRAPH", mocked_call_names={"DISCRATE"}
    )
    assert reasons == []


def test_per_case_check_refuses_unreachable_dynamic_call_target():
    result = _result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "DYNAMIC-PARAGRAPH", mocked_call_names=set()
    )
    assert any(r.code == "DYNAMIC_CALL" for r in reasons)


def test_per_case_check_follows_perform_to_find_dynamic_call():
    result = _result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "WRAPPER-PARAGRAPH", mocked_call_names=set()
    )
    assert any(r.code == "DYNAMIC_CALL" for r in reasons)


def test_per_case_check_refuses_unmatched_mock_call():
    result = _result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface,
        result.ast,
        "SAFE-PARAGRAPH",
        mocked_call_names={"SOME-OTHER-PROGRAM"},
    )
    assert any(r.code == "UNMATCHED_MOCK" for r in reasons)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_refusal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock.analysis.refusal'`

- [ ] **Step 3: Write `mockymock/analysis/refusal.py`**

```python
"""Refusal gate: whole-program (parse errors) and per-TESTCASE
(dynamic CALL / file I/O / EXEC reachable from PERFORM target, or an
unmatched MOCK CALL directive) checks.

Reachability is computed with a self-contained BFS over PerformStatement
targets within the same program -- not cobolparser's ProgramFlowAnalyzer --
because that keeps this module's correctness checkable against the same
small set of verified attributes (CobolParagraph.statements,
PerformStatement.target_paragraph) the rest of mockymock already depends
on, rather than additionally depending on ProgramFlowAnalyzer's full edge
taxonomy. A CALL is a leaf: it is never traversed into, since the called
program's source isn't part of this compilation unit.
"""

from __future__ import annotations

from dataclasses import dataclass

from cobolparser.models.statements.control import PerformStatement

from mockymock.analysis.mock_surface import MockSurface, _all_paragraphs


@dataclass
class RefusalReason:
    code: str
    message: str


def check_whole_program(parse_result) -> list[RefusalReason]:
    if parse_result.success:
        return []
    return [
        RefusalReason(
            code="PARSE_ERROR",
            message=f"cobolparser reported {len(parse_result.errors)} parse error(s)",
        )
    ]


def check_test_case(
    surface: MockSurface,
    program,
    perform_target: str,
    mocked_call_names: set[str],
) -> list[RefusalReason]:
    reasons: list[RefusalReason] = []
    reachable = _reachable_paragraphs(program, perform_target)

    if perform_target not in reachable:
        reasons.append(
            RefusalReason(
                code="UNKNOWN_PARAGRAPH",
                message=f"PERFORM target '{perform_target}' not found in PROCEDURE DIVISION",
            )
        )
        return reasons

    reachable_call_names: set[str] = set()
    for site in surface.call_sites:
        if site.paragraph_name not in reachable:
            continue
        if site.kind.value == "dynamic":
            reasons.append(
                RefusalReason(
                    code="DYNAMIC_CALL",
                    message=(
                        f"paragraph '{site.paragraph_name}' (line {site.line}) "
                        f"contains a dynamic CALL, not supported in v1"
                    ),
                )
            )
        else:
            reachable_call_names.add(site.program_name)

    if reachable & surface.file_io_paragraphs:
        hit = sorted(reachable & surface.file_io_paragraphs)[0]
        reasons.append(
            RefusalReason(
                code="UNMOCKED_FILE_IO",
                message=f"paragraph '{hit}' performs file I/O, not mocked in v1",
            )
        )

    if reachable & surface.exec_paragraphs:
        hit = sorted(reachable & surface.exec_paragraphs)[0]
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_EXEC",
                message=f"paragraph '{hit}' contains EXEC SQL/CICS/DLI, not supported in v1",
            )
        )

    for name in mocked_call_names - reachable_call_names:
        reasons.append(
            RefusalReason(
                code="UNMATCHED_MOCK",
                message=(
                    f"MOCK CALL \"{name}\" does not match any static CALL "
                    f"site reachable from '{perform_target}'"
                ),
            )
        )

    return reasons


def _reachable_paragraphs(program, start: str) -> set[str]:
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set()
    by_name = {p.paragraph_name: p for p in _all_paragraphs(procedure)}
    if start not in by_name:
        return set()

    seen: set[str] = set()
    stack = [start]
    while stack:
        name = stack.pop()
        if name in seen or name not in by_name:
            continue
        seen.add(name)
        for statement in by_name[name].statements:
            if isinstance(statement, PerformStatement) and statement.target_paragraph:
                stack.append(statement.target_paragraph)
    return seen
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/unit/test_refusal.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add mockymock/analysis/refusal.py tests/unit/test_refusal.py
git commit -m "feat: per-testcase and whole-program refusal gate"
```

- [ ] **Step 6: Fix reachability BFS to recurse into nested statement bodies (amendment — required, not optional)**

Code review proved this Critical, with a repro: `_reachable_paragraphs` only reads `by_name[name].statements` — a paragraph's top-level statement list — so a `PERFORM` nested inside `IF`/`EVALUATE`/an inline `PERFORM`/an IO-clause body is invisible to the BFS. A program where `WRAPPER-PARAGRAPH` contains `IF WS-FLAG = "Y" PERFORM DYNAMIC-PARAGRAPH END-IF`, and `DYNAMIC-PARAGRAPH` contains a dynamic `CALL`, makes `check_test_case(surface, ast, "WRAPPER-PARAGRAPH", set())` return `[]` — no refusal — even though the dynamic CALL is genuinely reachable. This is the exact class of bug this module exists to prevent, and it's the same root cause as Task 5's original gap (only Step 6/7 there fixed `mock_surface.py`'s own statement classification; `refusal.py`'s separate reachability BFS was never updated to match). Apply the same principle here: don't only look at top-level statements.

Reuse `mock_surface.py`'s existing nested-statement machinery rather than reimplementing it — `_all_paragraphs` is already imported cross-module from there; follow that same precedent for `_nested_statement_lists`:

```python
from mockymock.analysis.mock_surface import _all_paragraphs, _nested_statement_lists
```

Change `_reachable_paragraphs`'s inner loop from a flat `for statement in by_name[name].statements:` to one that also walks nested bodies — for example, replace the loop body with a small recursive helper:

```python
def _find_performs(statements: list) -> list[PerformStatement]:
    found = []
    for statement in statements:
        if isinstance(statement, PerformStatement):
            found.append(statement)
        for nested in _nested_statement_lists(statement):
            found.extend(_find_performs(nested))
    return found
```

and call `_find_performs(by_name[name].statements)` instead of iterating `by_name[name].statements` directly when looking for `PerformStatement`s to push onto the BFS stack.

**Second, related gap in the same finding: `PerformStatement.thru_paragraph` (PERFORM ... THRU) is never followed at all.** Correctly expanding a THRU range requires knowing paragraph source order, which `_all_paragraphs`'s current concatenation (`list(procedure_division.paragraphs)` then each section's paragraphs) does not reliably preserve when top-level paragraphs and sectioned paragraphs are interleaved in the source. Rather than risk an incorrect partial expansion, apply the same fail-closed philosophy used everywhere else in this module: if a reachable paragraph contains a `PerformStatement` with `thru_paragraph` set at all, that itself is a new refusal reason.

Add to `RefusalReason` usage in `check_test_case`:

```python
        if isinstance(statement, PerformStatement) and statement.thru_paragraph:
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_PERFORM_THRU",
                    message=(
                        f"paragraph '{paragraph_name}' uses PERFORM ... THRU, "
                        f"not supported in v1 (range expansion needs source-order "
                        f"guarantees not yet verified)"
                    ),
                )
            )
```

(exact wiring point — inside the same loop that walks `_find_performs(...)` results, since that's where every reachable-paragraph's `PerformStatement`s are already being visited).

- [ ] **Step 7: Add regression tests**

Add to `tests/unit/test_refusal.py`:
- A test mirroring the report's own repro: `WRAPPER-PARAGRAPH` containing `IF WS-FLAG = "Y" PERFORM DYNAMIC-PARAGRAPH END-IF`, `DYNAMIC-PARAGRAPH` containing a dynamic CALL. Assert `DYNAMIC_CALL` IS now detected from `WRAPPER-PARAGRAPH`.
- A test for `PERFORM X THRU Y`: assert `UNSUPPORTED_PERFORM_THRU` is returned when a reachable paragraph performs a THRU range.

- [ ] **Step 8: Run the full suite and re-commit**

Run: `python -m pytest tests/ -v`
Expected: all tests pass (new tests included), no regressions in the original 9 `test_refusal.py` tests.

```bash
git add mockymock/analysis/refusal.py tests/unit/test_refusal.py
git commit -m "fix: recurse into nested statement bodies and refuse PERFORM THRU in reachability BFS"
```

---

## Task 7: `.cut` DSL Model and Parser

**Files:**
- Create: `mockymock/dsl/__init__.py`
- Create: `mockymock/dsl/model.py`
- Create: `mockymock/dsl/parser.py`
- Test: `tests/unit/test_dsl_parser.py`

**Interfaces:**
- Consumes: nothing from prior tasks (pure text parsing).
- Produces: `MockCallDirective(program_name: str, body_lines: list[str])`; `ExpectDirective(data_name: str, expected_value: str)`; `VerifyDirective(program_name: str, expectation: str)`; `MockTestCase(name: str, mocks: list[MockCallDirective], setup_moves: list[tuple[str, str]], perform_target: str, expectations: list[ExpectDirective], verifications: list[VerifyDirective])`; `MockTestSuite(name: str, test_cases: list[MockTestCase])`; `parse_cut(text: str) -> MockTestSuite`; `CutParseError`. Tasks 11-14 (splicer + CLI) consume the parsed model.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_dsl_parser.py
import pytest

from mockymock.dsl.parser import CutParseError, parse_cut

ORDRPROC_CUT = """\
TESTSUITE "ORDRPROC discount calculation"

TESTCASE "10% discount reduces net amount correctly"
    MOCK CALL "DISCRATE"
        MOVE 0.10 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 100.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 90.00
    VERIFY "DISCRATE" WAS CALLED ONCE

TESTCASE "Zero discount leaves amount unchanged"
    MOCK CALL "DISCRATE"
        MOVE 0.00 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 50.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 50.00
"""


def test_parses_suite_name():
    suite = parse_cut(ORDRPROC_CUT)
    assert suite.name == "ORDRPROC discount calculation"


def test_parses_two_test_cases():
    suite = parse_cut(ORDRPROC_CUT)
    assert len(suite.test_cases) == 2
    assert suite.test_cases[0].name == "10% discount reduces net amount correctly"
    assert suite.test_cases[1].name == "Zero discount leaves amount unchanged"


def test_parses_mock_call_body():
    suite = parse_cut(ORDRPROC_CUT)
    case_one = suite.test_cases[0]
    assert len(case_one.mocks) == 1
    assert case_one.mocks[0].program_name == "DISCRATE"
    assert case_one.mocks[0].body_lines == ["MOVE 0.10 TO WS-DISCOUNT-PCT"]


def test_parses_setup_moves_and_perform_target():
    suite = parse_cut(ORDRPROC_CUT)
    case_one = suite.test_cases[0]
    assert case_one.setup_moves == [("100.00", "ORD-AMOUNT")]
    assert case_one.perform_target == "PROCESS-ORDER"


def test_parses_expect_and_verify():
    suite = parse_cut(ORDRPROC_CUT)
    case_one = suite.test_cases[0]
    assert case_one.expectations == [
        ("WS-NET-AMOUNT", "90.00")
    ] or case_one.expectations[0].data_name == "WS-NET-AMOUNT"
    assert case_one.verifications[0].program_name == "DISCRATE"
    assert case_one.verifications[0].expectation == "ONCE"


def test_second_case_has_no_verify():
    suite = parse_cut(ORDRPROC_CUT)
    assert suite.test_cases[1].verifications == []


def test_testcase_before_testsuite_raises():
    with pytest.raises(CutParseError):
        parse_cut('TESTCASE "orphan"\nPERFORM X\n')


def test_unrecognized_line_raises():
    with pytest.raises(CutParseError):
        parse_cut('TESTSUITE "X"\n\nTESTCASE "Y"\nNOT-A-REAL-DIRECTIVE\n')
```

Note: the `test_parses_expect_and_verify` assertion intentionally tolerates either a plain tuple or an `ExpectDirective` dataclass instance via `or` — pin it down to the dataclass form once `model.py` exists, by simplifying that assertion to `case_one.expectations[0].data_name == "WS-NET-AMOUNT"` and `case_one.expectations[0].expected_value == "90.00"` in Step 4 below.

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_dsl_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock.dsl'`

- [ ] **Step 3: Write `mockymock/dsl/model.py`**

```python
"""Model classes for the .cut DSL (v1: TESTSUITE/TESTCASE/MOCK CALL/
MOVE/PERFORM/EXPECT/VERIFY)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MockCallDirective:
    program_name: str
    body_lines: list[str] = field(default_factory=list)


@dataclass
class ExpectDirective:
    data_name: str
    expected_value: str


@dataclass
class VerifyDirective:
    program_name: str
    expectation: str  # "ONCE", "AT LEAST ONCE", "NEVER", or "<n> TIMES"


@dataclass
class MockTestCase:
    name: str
    mocks: list[MockCallDirective] = field(default_factory=list)
    setup_moves: list[tuple[str, str]] = field(default_factory=list)  # (value, target)
    perform_target: str = ""
    expectations: list[ExpectDirective] = field(default_factory=list)
    verifications: list[VerifyDirective] = field(default_factory=list)


@dataclass
class MockTestSuite:
    name: str
    test_cases: list[MockTestCase] = field(default_factory=list)
```

- [ ] **Step 4: Fix the tolerant assertion in the test**

Edit `tests/unit/test_dsl_parser.py`, replace `test_parses_expect_and_verify` with:

```python
def test_parses_expect_and_verify():
    suite = parse_cut(ORDRPROC_CUT)
    case_one = suite.test_cases[0]
    assert case_one.expectations[0].data_name == "WS-NET-AMOUNT"
    assert case_one.expectations[0].expected_value == "90.00"
    assert case_one.verifications[0].program_name == "DISCRATE"
    assert case_one.verifications[0].expectation == "ONCE"
```

- [ ] **Step 5: Write `mockymock/dsl/parser.py`**

```python
"""Parses .cut files into MockTestSuite objects."""

from __future__ import annotations

import re

from mockymock.dsl.model import (
    ExpectDirective,
    MockCallDirective,
    MockTestCase,
    MockTestSuite,
    VerifyDirective,
)

_TESTSUITE_RE = re.compile(r'^TESTSUITE\s+"(?P<name>[^"]*)"$')
_TESTCASE_RE = re.compile(r'^TESTCASE\s+"(?P<name>[^"]*)"$')
_MOCK_CALL_RE = re.compile(r'^MOCK\s+CALL\s+"(?P<name>[^"]*)"$')
_END_MOCK_RE = re.compile(r"^END-MOCK$")
_MOVE_RE = re.compile(r"^MOVE\s+(?P<value>.+?)\s+TO\s+(?P<target>\S+)$")
_PERFORM_RE = re.compile(r"^PERFORM\s+(?P<target>\S+)$")
_EXPECT_RE = re.compile(r"^EXPECT\s+(?P<name>\S+)\s+TO\s+BE\s+(?P<value>.+)$")
_VERIFY_RE = re.compile(
    r'^VERIFY\s+"(?P<name>[^"]*)"\s+WAS\s+CALLED\s+(?P<expectation>.+)$'
)


class CutParseError(ValueError):
    """Raised when a .cut file doesn't match the v1 grammar."""


def parse_cut(text: str) -> MockTestSuite:
    suite: MockTestSuite | None = None
    case: MockTestCase | None = None
    in_mock: MockCallDirective | None = None

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        if in_mock is not None:
            if _END_MOCK_RE.match(line):
                in_mock = None
            else:
                in_mock.body_lines.append(line)
            continue

        if (m := _TESTSUITE_RE.match(line)) is not None:
            suite = MockTestSuite(name=m.group("name"))
        elif (m := _TESTCASE_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: TESTCASE before TESTSUITE")
            case = MockTestCase(name=m.group("name"))
            suite.test_cases.append(case)
        elif (m := _MOCK_CALL_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: MOCK CALL outside TESTCASE")
            in_mock = MockCallDirective(program_name=m.group("name"))
            case.mocks.append(in_mock)
        elif (m := _MOVE_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: MOVE outside TESTCASE")
            case.setup_moves.append((m.group("value"), m.group("target")))
        elif (m := _PERFORM_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: PERFORM outside TESTCASE")
            case.perform_target = m.group("target")
        elif (m := _EXPECT_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: EXPECT outside TESTCASE")
            case.expectations.append(
                ExpectDirective(data_name=m.group("name"), expected_value=m.group("value"))
            )
        elif (m := _VERIFY_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: VERIFY outside TESTCASE")
            case.verifications.append(
                VerifyDirective(
                    program_name=m.group("name"), expectation=m.group("expectation")
                )
            )
        else:
            raise CutParseError(f"line {line_no}: unrecognized statement: {line!r}")

    if suite is None:
        raise CutParseError("no TESTSUITE found")
    return suite
```

- [ ] **Step 6: Run it to verify it passes**

Run: `python -m pytest tests/unit/test_dsl_parser.py -v`
Expected: PASS (8 passed).

- [ ] **Step 7: Commit**

```bash
git add mockymock/dsl/ tests/unit/test_dsl_parser.py
git commit -m "feat: .cut DSL model and parser"
```

---

## Task 8: Statement Span Detection

**Files:**
- Create: `mockymock/splicer/__init__.py`
- Create: `mockymock/splicer/source_map.py`
- Test: `tests/unit/test_source_map.py`

**Interfaces:**
- Consumes: `cobolparser.preprocess.normalize_fixed_format`; `cobolparser.parse_cobol`; `CobolParagraph.statements`, `.location.line` (verified).
- Produces: `statement_span(statement, boundaries: list[int], last_line: int) -> tuple[int, int]`; `collect_boundaries(program) -> list[int]`. Task 9 (stub writer) consumes this.

cobolparser's `SourceLocation` gives a statement's **start** line only — there's no end position. Multi-line statements (e.g. a `CALL` with `USING` parameters wrapped across lines) need their true extent inferred. The approach: a statement's span ends one line before whatever comes next (the next statement in the same paragraph, or the next paragraph's header if it's the last statement) — computed from a flat, sorted list of every paragraph-header and statement-start line in the program, treating paragraph boundaries as just another marker in that same list. This needs no COBOL terminator-period parsing and is exact as long as paragraph/statement start lines are exact, which they are (verified).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_source_map.py
from cobolparser import parse_cobol
from cobolparser.models.statements.call import CallStatement

from mockymock.splicer.source_map import collect_boundaries, statement_span

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       FIRST-PARAGRAPH.
           CALL "DISCRATE"
               USING WS-AMOUNT
                     WS-RATE.

       SECOND-PARAGRAPH.
           DISPLAY "DONE".
"""


def _ast_and_lines():
    result = parse_cobol(SOURCE, filename="sample.cbl")
    assert result.success, result.errors
    return result.ast, SOURCE.splitlines()


def _find_call_statement(ast):
    procedure = ast.get_division("PROCEDURE")
    for paragraph in procedure.paragraphs:
        for statement in paragraph.statements:
            if isinstance(statement, CallStatement):
                return statement
    raise AssertionError("no CALL statement found")


def test_multiline_call_span_covers_all_three_lines():
    ast, lines = _ast_and_lines()
    call_stmt = _find_call_statement(ast)
    boundaries = collect_boundaries(ast)

    start, end = statement_span(call_stmt, boundaries, last_line=len(lines))

    assert start == call_stmt.location.line
    assert end == start + 2
    assert "CALL" in lines[start - 1]
    assert "WS-RATE" in lines[end - 1]


def test_span_ends_before_next_paragraph_header():
    ast, lines = _ast_and_lines()
    call_stmt = _find_call_statement(ast)
    boundaries = collect_boundaries(ast)

    _, end = statement_span(call_stmt, boundaries, last_line=len(lines))

    second_paragraph_line = next(
        i + 1 for i, line in enumerate(lines) if "SECOND-PARAGRAPH" in line
    )
    assert end < second_paragraph_line
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_source_map.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock.splicer'`

- [ ] **Step 3: Write `mockymock/splicer/__init__.py`** (empty file)

- [ ] **Step 4: Write `mockymock/splicer/source_map.py`**

```python
"""Statement span detection on cobolparser's normalized free-form text.

cobolparser's SourceLocation gives only a statement's start line. A
statement's span end is derived as "one line before whatever comes next":
the next statement in the same paragraph, or the next paragraph's header
if this is the last statement in its paragraph, or end-of-file if it's the
very last paragraph's last statement.
"""

from __future__ import annotations

from cobolparser.models.program import CobolDivision, CobolParagraph


def collect_boundaries(program) -> list[int]:
    """Every paragraph-header and statement-start line, sorted ascending."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return []
    lines: set[int] = set()
    for paragraph in _all_paragraphs(procedure):
        lines.add(paragraph.location.line)
        for statement in paragraph.statements:
            lines.add(statement.location.line)
    return sorted(lines)


def statement_span(statement, boundaries: list[int], last_line: int) -> tuple[int, int]:
    """Return (start_line, end_line), both 1-indexed and inclusive."""
    start = statement.location.line
    later = [b for b in boundaries if b > start]
    end = (later[0] - 1) if later else last_line
    return start, end


def _all_paragraphs(procedure_division: CobolDivision) -> list[CobolParagraph]:
    paragraphs = list(procedure_division.paragraphs)
    for section in procedure_division._sections.values():
        paragraphs.extend(section.paragraphs)
    return paragraphs
```

- [ ] **Step 5: Run it to verify it passes**

Run: `python -m pytest tests/unit/test_source_map.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add mockymock/splicer/__init__.py mockymock/splicer/source_map.py tests/unit/test_source_map.py
git commit -m "feat: statement span detection via sorted boundary markers"
```

---

## Task 9: Stub Writer

**Files:**
- Create: `mockymock/splicer/stub_writer.py`
- Test: `tests/unit/test_stub_writer.py`

**Interfaces:**
- Consumes: nothing executable (pure text manipulation); designed to receive `(start_line, end_line)` from Task 8.
- Produces: `comment_and_replace(lines: list[str], start_line: int, end_line: int, replacement: list[str]) -> list[str]`. Task 11 (injector) is the consumer.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_stub_writer.py
from mockymock.splicer.stub_writer import comment_and_replace

SOURCE_LINES = [
    "       FIRST-PARAGRAPH.",
    '           CALL "DISCRATE"',
    "               USING WS-AMOUNT",
    "                     WS-RATE.",
    "",
    "       SECOND-PARAGRAPH.",
    '           DISPLAY "DONE".',
]


def test_comments_out_the_full_span():
    result = comment_and_replace(SOURCE_LINES, start_line=2, end_line=4, replacement=[])
    assert result[1].lstrip().startswith("*>")
    assert result[2].lstrip().startswith("*>")
    assert result[3].lstrip().startswith("*>")
    assert "CALL" in result[1]
    assert "WS-RATE" in result[3]


def test_does_not_touch_lines_outside_the_span():
    result = comment_and_replace(SOURCE_LINES, start_line=2, end_line=4, replacement=[])
    assert result[0] == SOURCE_LINES[0]
    assert result[5] == SOURCE_LINES[5]
    assert result[6] == SOURCE_LINES[6]


def test_blank_lines_in_span_are_left_blank():
    result = comment_and_replace(SOURCE_LINES, start_line=2, end_line=5, replacement=[])
    assert result[4] == ""


def test_replacement_lines_inserted_immediately_after_span():
    result = comment_and_replace(
        SOURCE_LINES,
        start_line=2,
        end_line=4,
        replacement=["           ADD 1 TO UT-DISCRATE-TALLY"],
    )
    assert result[4] == "           ADD 1 TO UT-DISCRATE-TALLY"
    assert result[5] == ""
    assert result[6] == "       SECOND-PARAGRAPH."


def test_does_not_mutate_input_list():
    original = list(SOURCE_LINES)
    comment_and_replace(SOURCE_LINES, start_line=2, end_line=4, replacement=[])
    assert SOURCE_LINES == original
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_stub_writer.py -v`
Expected: FAIL — `ImportError: cannot import name 'comment_and_replace'`

- [ ] **Step 3: Write `mockymock/splicer/stub_writer.py`**

```python
"""Comments out a statement's source span and splices replacement lines in."""

from __future__ import annotations


def comment_and_replace(
    lines: list[str], start_line: int, end_line: int, replacement: list[str]
) -> list[str]:
    """Return a NEW list: lines [start_line, end_line] (1-indexed, inclusive)
    commented out in place, with `replacement` inserted immediately after
    the (now-commented) span.
    """
    result = list(lines)
    for line_no in range(start_line, end_line + 1):
        idx = line_no - 1
        if 0 <= idx < len(result) and result[idx].strip():
            result[idx] = "      *> " + result[idx]
    insert_at = end_line  # 0-indexed position right after the span
    return result[:insert_at] + replacement + result[insert_at:]
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/unit/test_stub_writer.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/stub_writer.py tests/unit/test_stub_writer.py
git commit -m "feat: comment-and-replace statement span surgery"
```

---

## Task 10: Working-Storage Reset Generation

**Files:**
- Create: `mockymock/splicer/reset.py`
- Test: `tests/unit/test_reset.py`

**Interfaces:**
- Consumes: `cobolparser.parse_cobol`; `CobolProgram.get_division("DATA")`; `CobolDataItem.name`, `.level`, `.picture_clause`, `.value_clause` (verified); `PictureClause.pattern` (verified).
- Produces: `reset_move_lines(program) -> list[str]`, one `MOVE <value> TO <name>` COBOL line per top-level WORKING-STORAGE item. Task 12 (driver) wraps this into the `UT-RESET-WORKING-STORAGE` paragraph.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_reset.py
from cobolparser import parse_cobol

from mockymock.splicer.reset import reset_move_lines

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DISCOUNT-PCT    PIC 9V99.
       01  WS-NET-AMOUNT      PIC 9(5)V99.
       01  WS-EOF-FLAG        PIC X VALUE "N".
       01  WS-ORDER-STATUS    PIC XX.

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _ast():
    result = parse_cobol(SOURCE, filename="sample.cbl")
    assert result.success, result.errors
    return result.ast


def test_item_with_value_clause_resets_to_that_value():
    lines = reset_move_lines(_ast())
    assert 'MOVE "N" TO WS-EOF-FLAG' in lines


def test_numeric_item_without_value_clause_resets_to_zero():
    lines = reset_move_lines(_ast())
    assert "MOVE 0 TO WS-DISCOUNT-PCT" in lines
    assert "MOVE 0 TO WS-NET-AMOUNT" in lines


def test_alphanumeric_item_without_value_clause_resets_to_spaces():
    lines = reset_move_lines(_ast())
    assert "MOVE SPACES TO WS-ORDER-STATUS" in lines


def test_one_line_per_top_level_item():
    lines = reset_move_lines(_ast())
    assert len(lines) == 4
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_reset.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock.splicer.reset'`. If `test_item_with_value_clause_resets_to_that_value` fails after Step 4 because `value_clause` turns out to store `N` without quotes (rather than `"N"` with them), that's the moment to adjust `_default_value_literal` below to match — this test exists specifically to surface that.

- [ ] **Step 3: Write `mockymock/splicer/reset.py`**

```python
"""Generates MOVE statements that reset WORKING-STORAGE between test cases.

Necessary because mockymock compiles one binary per TESTSUITE (see Global
Constraints): without an explicit reset, case N's leftover state leaks
into case N+1. Resets to the item's declared VALUE clause if present,
otherwise to COBOL's conventional type default (ZERO for numeric, SPACES
for alphanumeric) -- a deliberate divergence from "truly undefined" COBOL
memory, in exchange for deterministic, order-independent tests.
"""

from __future__ import annotations

import re

_REPEAT_GROUP_RE = re.compile(r"\(\d+\)")


def reset_move_lines(program) -> list[str]:
    """One `MOVE <value> TO <name>` line per top-level WORKING-STORAGE item."""
    working_storage = program.get_division("DATA")
    if working_storage is None:
        return []

    section = _find_working_storage_section(working_storage)
    if section is None:
        return []

    lines: list[str] = []
    for item in _top_level_items(section):
        value = _default_value_literal(item)
        lines.append(f"MOVE {value} TO {item.name}")
    return lines


def _find_working_storage_section(data_division):
    for section in getattr(data_division, "sections", data_division.children):
        name = getattr(section, "_own_section_name", None) or getattr(
            section, "section_name", None
        )
        if name and "WORKING-STORAGE" in name.upper():
            return section
    return None


def _top_level_items(section):
    return [item for item in section.children if getattr(item, "level", None) == 1]


def _is_numeric(item) -> bool:
    if item.picture_clause is None:
        return False
    stripped = _REPEAT_GROUP_RE.sub("", item.picture_clause.pattern)
    return any(c in stripped for c in ("9", "V", "P"))


def _default_value_literal(item) -> str:
    if item.value_clause:
        return item.value_clause
    return "0" if _is_numeric(item) else "SPACES"
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/unit/test_reset.py -v`
Expected: PASS (4 passed). `_find_working_storage_section` and `_top_level_items` make assumptions about how `CobolDivision`/section children expose WORKING-STORAGE — if either helper doesn't find the section on the first run, add a quick `print([type(c).__name__ for c in working_storage.children])` in a throwaway script against the test's `SOURCE` to see the actual tree shape, then fix the helper to match. Don't guess twice; look once.

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/reset.py tests/unit/test_reset.py
git commit -m "feat: working-storage reset generation for test-case isolation"
```

---

## Task 11: Mock Injector

**Files:**
- Create: `mockymock/splicer/injector.py`
- Test: `tests/unit/test_injector.py`

**Interfaces:**
- Consumes: `mockymock.dsl.model.{MockTestSuite, MockCallDirective}` (Task 7); `mockymock.analysis.mock_surface.{MockSurface, CallSite}` (Task 5).
- Produces: `tally_field_name(call_name: str) -> str`; `build_call_dispatch(call_name: str, suite: MockTestSuite) -> list[str]` — the tally-increment + `EVALUATE UT-CURRENT-CASE` block for one CALL splice site, merging every test case in the suite that mocks that call name. Task 12 (driver) and Task 13 (CLI wiring) call this once per distinct mocked call name and feed the result to `stub_writer.comment_and_replace`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_injector.py
from mockymock.dsl.model import MockCallDirective, MockTestCase, MockTestSuite
from mockymock.splicer.injector import build_call_dispatch, tally_field_name


def _suite() -> MockTestSuite:
    case_one = MockTestCase(name="10% discount")
    case_one.mocks.append(
        MockCallDirective(
            program_name="DISCRATE", body_lines=["MOVE 0.10 TO WS-DISCOUNT-PCT"]
        )
    )

    case_two = MockTestCase(name="Zero discount")
    case_two.mocks.append(
        MockCallDirective(
            program_name="DISCRATE", body_lines=["MOVE 0.00 TO WS-DISCOUNT-PCT"]
        )
    )

    return MockTestSuite(name="ORDRPROC", test_cases=[case_one, case_two])


def test_tally_field_name_is_call_name_uppercased():
    assert tally_field_name("DISCRATE") == "UT-DISCRATE-TALLY"


def test_tally_field_name_sanitizes_non_cobol_name_chars():
    assert tally_field_name("sub.pgm 01") == "UT-SUB-PGM-01-TALLY"


def test_dispatch_increments_tally():
    lines = build_call_dispatch("DISCRATE", _suite())
    assert "ADD 1 TO UT-DISCRATE-TALLY" in lines


def test_dispatch_has_one_when_branch_per_test_case():
    lines = build_call_dispatch("DISCRATE", _suite())
    joined = "\n".join(lines)
    assert 'WHEN "001"' in joined
    assert 'WHEN "002"' in joined
    assert "MOVE 0.10 TO WS-DISCOUNT-PCT" in joined
    assert "MOVE 0.00 TO WS-DISCOUNT-PCT" in joined


def test_dispatch_has_when_other_error_fallback():
    lines = build_call_dispatch("DISCRATE", _suite())
    joined = "\n".join(lines)
    assert "WHEN OTHER" in joined
    assert "DISCRATE called" in joined


def test_dispatch_excludes_test_cases_that_dont_mock_this_call():
    case_unrelated = MockTestCase(name="Doesn't mock DISCRATE")
    suite = MockTestSuite(name="X", test_cases=[case_unrelated])
    lines = build_call_dispatch("DISCRATE", suite)
    joined = "\n".join(lines)
    assert 'WHEN "001"' not in joined
    assert "WHEN OTHER" in joined
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_injector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock.splicer.injector'`

- [ ] **Step 3: Write `mockymock/splicer/injector.py`**

```python
"""Merges every test case's MOCK CALL body for one call name into a single
EVALUATE UT-CURRENT-CASE dispatch block -- necessary because all TESTCASEs
in a suite share one compiled binary and therefore one physical copy of
each CALL statement (see Global Constraints: one binary per TESTSUITE).
"""

from __future__ import annotations

import re

from mockymock.dsl.model import MockTestSuite

_NON_COBOL_NAME_CHAR_RE = re.compile(r"[^A-Z0-9-]")


def tally_field_name(call_name: str) -> str:
    sanitized = _NON_COBOL_NAME_CHAR_RE.sub("-", call_name.upper())
    return f"UT-{sanitized}-TALLY"


def build_call_dispatch(call_name: str, suite: MockTestSuite) -> list[str]:
    """Tally increment + EVALUATE block for the CALL "call_name" splice site."""
    tally = tally_field_name(call_name)
    lines = [f"           ADD 1 TO {tally}", "           EVALUATE UT-CURRENT-CASE"]

    for index, case in enumerate(suite.test_cases, start=1):
        case_id = f"{index:03d}"
        for mock in case.mocks:
            if mock.program_name != call_name:
                continue
            lines.append(f'               WHEN "{case_id}"')
            lines.extend(f"                   {body}" for body in mock.body_lines)

    lines.append("               WHEN OTHER")
    lines.append(
        f'                   DISPLAY "__MOCKYMOCK__ ERROR: {call_name} called "'
    )
    lines.append('                       "from unmocked test case " UT-CURRENT-CASE')
    lines.append("           END-EVALUATE")
    return lines
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/unit/test_injector.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/injector.py tests/unit/test_injector.py
git commit -m "feat: merge per-testcase MOCK CALL bodies into EVALUATE dispatch"
```

---

## Task 12: Driver Generation

**Files:**
- Create: `mockymock/splicer/driver.py`
- Test: `tests/unit/test_driver.py`

**Interfaces:**
- Consumes: `mockymock.dsl.model.MockTestSuite` (Task 7); `mockymock.splicer.reset.reset_move_lines` (Task 10); `mockymock.splicer.injector.tally_field_name` (Task 11).
- Produces: `DriverArtifact(working_storage_lines: list[str], procedure_lines: list[str])`; `build_driver(suite: MockTestSuite, reset_lines: list[str], mocked_call_names: list[str]) -> DriverArtifact`. Task 14 (CLI `run`) assembles the final instrumented source from this plus Task 11's per-call dispatch blocks.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_driver.py
from mockymock.dsl.model import (
    ExpectDirective,
    MockCallDirective,
    MockTestCase,
    MockTestSuite,
    VerifyDirective,
)
from mockymock.splicer.driver import build_driver


def _suite() -> MockTestSuite:
    case_one = MockTestCase(
        name="10% discount reduces net amount correctly",
        mocks=[
            MockCallDirective(
                program_name="DISCRATE", body_lines=["MOVE 0.10 TO WS-DISCOUNT-PCT"]
            )
        ],
        setup_moves=[("100.00", "ORD-AMOUNT")],
        perform_target="PROCESS-ORDER",
        expectations=[ExpectDirective("WS-NET-AMOUNT", "90.00")],
        verifications=[VerifyDirective("DISCRATE", "ONCE")],
    )
    return MockTestSuite(name="ORDRPROC discount calculation", test_cases=[case_one])


def test_working_storage_declares_bookkeeping_fields():
    artifact = build_driver(_suite(), reset_lines=[], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.working_storage_lines)
    assert "UT-CURRENT-CASE" in joined
    assert "UT-DISCRATE-TALLY" in joined
    assert "UT-FAIL-COUNT" in joined


def test_testsuite_paragraph_performs_each_case_and_stops():
    artifact = build_driver(_suite(), reset_lines=[], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.procedure_lines)
    assert "UT-TESTSUITE-" in joined
    assert "PERFORM UT-TESTCASE-001" in joined
    assert "STOP RUN" in joined
    assert "__MOCKYMOCK__ TESTSUITE: ORDRPROC discount calculation" in joined


def test_testcase_resets_and_sets_current_case():
    artifact = build_driver(_suite(), reset_lines=["MOVE 0 TO X"], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.procedure_lines)
    assert "PERFORM UT-RESET-WORKING-STORAGE" in joined
    assert 'MOVE "001" TO UT-CURRENT-CASE' in joined
    assert "MOVE 0 TO UT-DISCRATE-TALLY" in joined


def test_testcase_emits_setup_moves_and_perform():
    artifact = build_driver(_suite(), reset_lines=[], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.procedure_lines)
    assert "MOVE 100.00 TO ORD-AMOUNT" in joined
    assert "PERFORM PROCESS-ORDER" in joined


def test_testcase_emits_expect_check():
    artifact = build_driver(_suite(), reset_lines=[], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.procedure_lines)
    assert "IF WS-NET-AMOUNT NOT = 90.00" in joined
    assert "__MOCKYMOCK__ CASE 001 FAIL:" in joined
    assert "ADD 1 TO UT-FAIL-COUNT" in joined


def test_testcase_emits_verify_check():
    artifact = build_driver(_suite(), reset_lines=[], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.procedure_lines)
    assert "IF UT-DISCRATE-TALLY NOT = 1" in joined


def test_testcase_brackets_with_start_and_end_markers():
    artifact = build_driver(_suite(), reset_lines=[], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.procedure_lines)
    assert (
        "__MOCKYMOCK__ CASE 001 START: 10% discount reduces net amount correctly"
        in joined
    )
    assert "__MOCKYMOCK__ CASE 001 END" in joined


def test_summary_line_uses_total_case_count():
    artifact = build_driver(_suite(), reset_lines=[], mocked_call_names=["DISCRATE"])
    joined = "\n".join(artifact.procedure_lines)
    assert 'DISPLAY "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES="' in joined or (
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=" in joined
    )


def test_reset_working_storage_paragraph_included_when_lines_given():
    artifact = build_driver(
        _suite(), reset_lines=["MOVE 0 TO ORD-AMOUNT"], mocked_call_names=["DISCRATE"]
    )
    joined = "\n".join(artifact.procedure_lines)
    assert "UT-RESET-WORKING-STORAGE." in joined
    assert "MOVE 0 TO ORD-AMOUNT" in joined
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_driver.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock.splicer.driver'`

- [ ] **Step 3: Write `mockymock/splicer/driver.py`**

```python
"""Generates the UT-TESTSUITE-*/UT-TESTCASE-*/UT-RESET-WORKING-STORAGE
driver paragraphs, plus the WORKING-STORAGE bookkeeping fields they need.

These become the new PROCEDURE DIVISION entry point: prepended before the
program's own paragraphs, so the original first paragraph never runs
automatically (PROCEDURE DIVISION execution starts at the first paragraph
after the header, and the driver paragraphs come first).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mockymock.dsl.model import MockTestCase, MockTestSuite
from mockymock.splicer.injector import tally_field_name

_SUITE_PARAGRAPH_NAME_RE = re.compile(r"[^A-Z0-9-]")


@dataclass
class DriverArtifact:
    working_storage_lines: list[str]
    procedure_lines: list[str]


def build_driver(
    suite: MockTestSuite, reset_lines: list[str], mocked_call_names: list[str]
) -> DriverArtifact:
    suite_paragraph = "UT-TESTSUITE-" + _SUITE_PARAGRAPH_NAME_RE.sub(
        "-", suite.name.upper()
    )

    working_storage = ["01  UT-CURRENT-CASE        PIC X(3).", "01  UT-FAIL-COUNT          PIC 9(4) VALUE 0."]
    for call_name in mocked_call_names:
        working_storage.append(f"01  {tally_field_name(call_name)}      PIC 9(4) VALUE 0.")

    procedure: list[str] = []
    procedure.append(f"       {suite_paragraph}.")
    procedure.append(f'           DISPLAY "__MOCKYMOCK__ TESTSUITE: {suite.name}"')
    for index in range(1, len(suite.test_cases) + 1):
        procedure.append(f"           PERFORM UT-TESTCASE-{index:03d}")
    procedure.append(
        f'           DISPLAY "__MOCKYMOCK__ SUMMARY: RUN={len(suite.test_cases)} '
        f'FAILURES=" UT-FAIL-COUNT'
    )
    procedure.append("           STOP RUN.")
    procedure.append("")

    if reset_lines:
        procedure.append("       UT-RESET-WORKING-STORAGE.")
        for line in reset_lines[:-1]:
            procedure.append(f"           {line}")
        procedure.append(f"           {reset_lines[-1]}.")
        procedure.append("")

    for index, case in enumerate(suite.test_cases, start=1):
        procedure.extend(_build_testcase_paragraph(index, case, mocked_call_names, bool(reset_lines)))
        procedure.append("")

    return DriverArtifact(working_storage_lines=working_storage, procedure_lines=procedure)


def _build_testcase_paragraph(
    index: int, case: MockTestCase, mocked_call_names: list[str], has_reset: bool
) -> list[str]:
    case_id = f"{index:03d}"
    lines = [f"       UT-TESTCASE-{case_id}."]

    if has_reset:
        lines.append("           PERFORM UT-RESET-WORKING-STORAGE")
    lines.append(f'           MOVE "{case_id}" TO UT-CURRENT-CASE')
    for call_name in {m.program_name for m in case.mocks}:
        lines.append(f"           MOVE 0 TO {tally_field_name(call_name)}")
    lines.append(f'           DISPLAY "__MOCKYMOCK__ CASE {case_id} START: {case.name}"')

    for value, target in case.setup_moves:
        lines.append(f"           MOVE {value} TO {target}")

    lines.append("")
    lines.append(f"           PERFORM {case.perform_target}")
    lines.append("")

    for expectation in case.expectations:
        lines.append(f"           IF {expectation.data_name} NOT = {expectation.expected_value}")
        lines.append(
            f'               DISPLAY "__MOCKYMOCK__ CASE {case_id} FAIL: expected '
            f'{expectation.data_name} = {expectation.expected_value}"'
        )
        lines.append("               ADD 1 TO UT-FAIL-COUNT")
        lines.append("           END-IF")

    for verification in case.verifications:
        tally = tally_field_name(verification.program_name)
        condition = _verify_condition(verification.expectation, tally)
        lines.append(f"           IF {condition}")
        lines.append(
            f'               DISPLAY "__MOCKYMOCK__ CASE {case_id} FAIL: VERIFY '
            f'{verification.program_name} WAS CALLED {verification.expectation}"'
        )
        lines.append("               ADD 1 TO UT-FAIL-COUNT")
        lines.append("           END-IF")

    lines.append(f'           DISPLAY "__MOCKYMOCK__ CASE {case_id} END".')
    return lines


def _verify_condition(expectation: str, tally_field: str) -> str:
    expectation = expectation.strip().upper()
    if expectation == "ONCE":
        return f"{tally_field} NOT = 1"
    if expectation == "NEVER":
        return f"{tally_field} NOT = 0"
    if expectation == "AT LEAST ONCE":
        return f"{tally_field} < 1"
    m = re.match(r"^(\d+)\s+TIMES$", expectation)
    if m:
        return f"{tally_field} NOT = {m.group(1)}"
    raise ValueError(f"unrecognized VERIFY expectation: {expectation!r}")
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/unit/test_driver.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/driver.py tests/unit/test_driver.py
git commit -m "feat: generate TESTSUITE/TESTCASE driver paragraphs"
```

---

## Task 13: `.cut` Scaffolding Generator

**Files:**
- Create: `mockymock/dsl/generator.py`
- Test: `tests/unit/test_dsl_generator.py`

**Interfaces:**
- Consumes: `mockymock.analysis.mock_surface.MockSurface` (Task 5).
- Produces: `scaffold_cut(suite_name: str, surface: MockSurface) -> str` — one `TESTCASE` per static call site, with a `MOCK CALL` stub the user fills in. Task 14 (CLI `generate` command) calls this.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_dsl_generator.py
from mockymock.analysis.mock_surface import CallKind, CallSite, MockSurface
from mockymock.dsl.generator import scaffold_cut
from mockymock.dsl.parser import parse_cut


def _surface() -> MockSurface:
    return MockSurface(
        call_sites=[
            CallSite(
                program_name="DISCRATE",
                kind=CallKind.STATIC,
                paragraph_name="PROCESS-ORDER",
                line=42,
            )
        ]
    )


def test_scaffold_contains_one_testcase_per_static_call_site():
    text = scaffold_cut("ORDRPROC", _surface())
    assert text.count("TESTCASE") == 1
    assert 'MOCK CALL "DISCRATE"' in text
    assert "PERFORM PROCESS-ORDER" in text


def test_scaffold_is_valid_cut_syntax():
    text = scaffold_cut("ORDRPROC", _surface())
    suite = parse_cut(text)
    assert suite.name == "ORDRPROC"
    assert len(suite.test_cases) == 1
    assert suite.test_cases[0].mocks[0].program_name == "DISCRATE"


def test_scaffold_with_no_call_sites_has_no_testcases():
    text = scaffold_cut("EMPTY", MockSurface())
    suite = parse_cut(text)
    assert suite.test_cases == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_dsl_generator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock.dsl.generator'`

- [ ] **Step 3: Write `mockymock/dsl/generator.py`**

```python
"""Auto-scaffolds a starter .cut file from a MockSurface."""

from __future__ import annotations

from mockymock.analysis.mock_surface import MockSurface


def scaffold_cut(suite_name: str, surface: MockSurface) -> str:
    lines = [f'TESTSUITE "{suite_name}"', ""]
    for site in surface.static_call_sites():
        lines.append(f'TESTCASE "Calls {site.program_name} from {site.paragraph_name}"')
        lines.append(f'    MOCK CALL "{site.program_name}"')
        lines.append("        * TODO: set return values via MOVE here")
        lines.append("    END-MOCK")
        lines.append("    * TODO: add MOVE setup statements here")
        lines.append(f"    PERFORM {site.paragraph_name}")
        lines.append("    * TODO: add EXPECT/VERIFY assertions here")
        lines.append("")
    return "\n".join(lines)
```

Note: `parse_cut` (Task 7) treats any unrecognized line as a hard error, so the `* TODO` placeholder lines above would fail to round-trip through `parse_cut` — that's caught by `test_scaffold_is_valid_cut_syntax`. Fix by using a recognized-but-inert form: COBOL-style full-line comments aren't part of the v1 `.cut` grammar at all yet, so represent TODOs as part of the already-recognized directives instead — replace the placeholder lines so the generated file is immediately syntactically valid:

```python
def scaffold_cut(suite_name: str, surface: MockSurface) -> str:
    lines = [f'TESTSUITE "{suite_name}"', ""]
    for site in surface.static_call_sites():
        lines.append(f'TESTCASE "Calls {site.program_name} from {site.paragraph_name}"')
        lines.append(f'    MOCK CALL "{site.program_name}"')
        lines.append("        MOVE 0 TO RETURN-CODE")
        lines.append("    END-MOCK")
        lines.append(f"    PERFORM {site.paragraph_name}")
        lines.append("")
    return "\n".join(lines)
```

(`MOVE 0 TO RETURN-CODE` is an obviously-fake placeholder body the user is expected to replace with a real mocked return value relevant to `site.program_name`'s actual `USING` parameters — it exists so the scaffold is valid, compilable `.cut` syntax out of the box, not a usable test by itself.)

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/unit/test_dsl_generator.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add mockymock/dsl/generator.py tests/unit/test_dsl_generator.py
git commit -m "feat: auto-scaffold starter .cut files from the mock surface"
```

---

## Task 14: CLI Wiring (`generate` and `run`)

**Files:**
- Modify: `mockymock/cli/main.py`
- Test: `tests/integration/test_cli.py`

**Interfaces:**
- Consumes: every module from Tasks 2–13.
- Produces: `mockymock generate <program.cbl> [-o output.cut]`; `mockymock run <program.cbl> --cut <program.cut> [--junit-xml PATH]`, exit code 0 on all-pass, 1 on any failure or refusal.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_cli.py
import shutil
from pathlib import Path

import pytest

from mockymock.cli.main import main

requires_gnucobol = pytest.mark.skipif(
    shutil.which("cobc") is None, reason="GnuCOBOL (cobc) not installed"
)

ORDRPROC_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDRPROC.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  ORD-AMOUNT          PIC 9(5)V99.
       01  WS-DISCOUNT-PCT     PIC 9V99.
       01  WS-NET-AMOUNT       PIC 9(5)V99.

       PROCEDURE DIVISION.
       PROCESS-ORDER.
           CALL "DISCRATE" USING ORD-AMOUNT WS-DISCOUNT-PCT
           COMPUTE WS-NET-AMOUNT =
               ORD-AMOUNT - (ORD-AMOUNT * WS-DISCOUNT-PCT).
"""

ORDRPROC_CUT = """\
TESTSUITE "ORDRPROC discount calculation"

TESTCASE "10% discount reduces net amount correctly"
    MOCK CALL "DISCRATE"
        MOVE 0.10 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 100.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 90.00
    VERIFY "DISCRATE" WAS CALLED ONCE

TESTCASE "Zero discount leaves amount unchanged"
    MOCK CALL "DISCRATE"
        MOVE 0.00 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 50.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 50.00
"""


def test_generate_writes_a_parseable_cut_file(tmp_path: Path):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(ORDRPROC_CBL)
    output = tmp_path / "ORDRPROC.cut"

    exit_code = main(["generate", str(program), "-o", str(output)])

    assert exit_code == 0
    assert output.exists()
    assert 'MOCK CALL "DISCRATE"' in output.read_text()


@requires_gnucobol
def test_run_passes_when_both_cases_are_correct(tmp_path: Path):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(ORDRPROC_CBL)
    cut_file = tmp_path / "ORDRPROC.cut"
    cut_file.write_text(ORDRPROC_CUT)

    exit_code = main(["run", str(program), "--cut", str(cut_file)])

    assert exit_code == 0


@requires_gnucobol
def test_run_fails_when_expectation_is_wrong(tmp_path: Path):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(ORDRPROC_CBL)
    cut_file = tmp_path / "ORDRPROC.cut"
    cut_file.write_text(ORDRPROC_CUT.replace("TO BE 90.00", "TO BE 99.99"))

    exit_code = main(["run", str(program), "--cut", str(cut_file)])

    assert exit_code == 1


def test_run_refuses_program_with_parse_errors(tmp_path: Path, capsys):
    program = tmp_path / "BAD.cbl"
    program.write_text("NOT EVEN VALID COBOL { } [ ]")
    cut_file = tmp_path / "BAD.cut"
    cut_file.write_text('TESTSUITE "X"\n\nTESTCASE "Y"\nPERFORM Z\n')

    exit_code = main(["run", str(program), "--cut", str(cut_file)])

    assert exit_code == 1
    assert "PARSE_ERROR" in capsys.readouterr().out
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/integration/test_cli.py -v`
Expected: FAIL — `argparse` error, `generate`/`run` subcommands don't exist yet.

- [ ] **Step 3: Add `generate` and `run` to `mockymock/cli/main.py`**

```python
"""mockymock CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _cmd_setup(args: argparse.Namespace) -> int:
    from mockymock.runtime.gnucobol_bootstrap import (
        GnuCobolNotFoundError,
        bootstrap,
    )

    try:
        info = bootstrap()
    except GnuCobolNotFoundError as exc:
        print(f"mockymock setup: {exc}")
        return 1
    print(f"mockymock setup: found cobc at {info.path} ({info.version})")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    from cobolparser import parse_cobol

    from mockymock.analysis.mock_surface import analyze
    from mockymock.dsl.generator import scaffold_cut

    source_path = Path(args.program)
    result = parse_cobol(source_path.read_text(), filename=source_path.name)
    if not result.success:
        print(f"mockymock generate: {len(result.errors)} parse error(s):")
        for error in result.errors:
            print(f"  {error}")
        return 1

    surface = analyze(result.ast)
    cut_text = scaffold_cut(result.ast.program_name, surface)

    output_path = Path(args.output) if args.output else source_path.with_suffix(".cut")
    output_path.write_text(cut_text)
    print(f"mockymock generate: wrote {len(surface.static_call_sites())} test case(s) -> {output_path}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from cobolparser import parse_cobol
    from cobolparser.preprocess import normalize_fixed_format

    from mockymock.analysis.mock_surface import analyze
    from mockymock.analysis.refusal import check_test_case, check_whole_program
    from mockymock.dsl.parser import parse_cut
    from mockymock.report.formatters import format_console, format_junit_xml
    from mockymock.report.results import parse_stdout
    from mockymock.runtime.compiler import compile_source
    from mockymock.runtime.executor import run_binary
    from mockymock.runtime.sandbox import sandbox_dir
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.injector import build_call_dispatch
    from mockymock.splicer.reset import reset_move_lines
    from mockymock.splicer.source_map import collect_boundaries, statement_span
    from mockymock.splicer.stub_writer import comment_and_replace

    source_path = Path(args.program)
    raw_source = source_path.read_text()
    result = parse_cobol(raw_source, filename=source_path.name)

    for reason in check_whole_program(result):
        print(f"mockymock run: refused ({reason.code}): {reason.message}")
    if not result.success:
        return 1

    suite = parse_cut(Path(args.cut).read_text())
    surface = analyze(result.ast)

    refused = False
    for case in suite.test_cases:
        mocked_names = {m.program_name for m in case.mocks}
        for reason in check_test_case(surface, result.ast, case.perform_target, mocked_names):
            print(f"mockymock run: refused ({reason.code}): {reason.message}")
            refused = True
    if refused:
        return 1

    normalized = normalize_fixed_format(raw_source.splitlines())
    lines = normalized.splitlines()
    boundaries = collect_boundaries(result.ast)

    mocked_call_names = sorted({m.program_name for case in suite.test_cases for m in case.mocks})
    for call_name in mocked_call_names:
        for site in surface.static_call_sites():
            if site.program_name != call_name:
                continue
            for paragraph in _paragraphs_by_name(result.ast):
                if paragraph.paragraph_name != site.paragraph_name:
                    continue
                for statement in paragraph.statements:
                    if getattr(statement, "called_program", None) == call_name and not statement.is_dynamic:
                        start, end = statement_span(statement, boundaries, last_line=len(lines))
                        replacement = build_call_dispatch(call_name, suite)
                        lines = comment_and_replace(lines, start, end, replacement)

    reset_lines = reset_move_lines(result.ast)
    artifact = build_driver(suite, reset_lines, mocked_call_names)

    instrumented = _insert_driver(lines, artifact)

    with sandbox_dir() as tmp:
        instrumented_path = tmp / source_path.with_suffix(".cbl").name
        instrumented_path.write_text("\n".join(instrumented) + "\n")

        compiled = compile_source(instrumented_path)
        if not compiled.success:
            print("mockymock run: compile failed:")
            print(compiled.stderr)
            return 1

        executed = run_binary(compiled.binary_path)

    suite_result = parse_stdout(executed.stdout)
    print(format_console(suite_result))

    if args.junit_xml:
        Path(args.junit_xml).write_text(format_junit_xml(suite_result))

    return 0 if suite_result.all_passed else 1


def _paragraphs_by_name(program):
    from mockymock.analysis.mock_surface import _all_paragraphs

    procedure = program.get_division("PROCEDURE")
    return _all_paragraphs(procedure) if procedure else []


def _insert_driver(lines: list[str], artifact) -> list[str]:
    """Insert WORKING-STORAGE additions after that section's header, and
    procedure_lines right after the PROCEDURE DIVISION header."""
    result: list[str] = []
    inserted_ws = False
    inserted_proc = False
    for line in lines:
        result.append(line)
        upper = line.strip().upper()
        if not inserted_ws and upper.startswith("WORKING-STORAGE SECTION"):
            result.extend(f"       {ws_line}" for ws_line in artifact.working_storage_lines)
            inserted_ws = True
        if not inserted_proc and upper.startswith("PROCEDURE DIVISION"):
            result.append("")
            result.extend(artifact.procedure_lines)
            inserted_proc = True
    return result


def build_parser() -> argparse.ArgumentParser:
    from mockymock import __version__

    parser = argparse.ArgumentParser(prog="mockymock")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")

    setup_parser = subparsers.add_parser("setup", help="Detect or install GnuCOBOL (cobc)")
    setup_parser.set_defaults(func=_cmd_setup)

    generate_parser = subparsers.add_parser(
        "generate", help="Scaffold a starter .cut file from a COBOL program"
    )
    generate_parser.add_argument("program")
    generate_parser.add_argument("-o", "--output")
    generate_parser.set_defaults(func=_cmd_generate)

    run_parser = subparsers.add_parser(
        "run", help="Splice, compile, run, and assert a COBOL program against a .cut file"
    )
    run_parser.add_argument("program")
    run_parser.add_argument("--cut", required=True)
    run_parser.add_argument("--junit-xml")
    run_parser.set_defaults(func=_cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/integration/test_cli.py -v`
Expected: PASS (4 passed). This is the first test exercising the full splice→compile→run loop through generated (not hand-written) COBOL — if `compiled.success` is `False`, print `compiled.stderr` (the test already does, via the assertion message) and read the actual instrumented source mockymock wrote to the sandbox dir before it was cleaned up; temporarily comment out the `with sandbox_dir()` cleanup or copy `instrumented_path` somewhere durable to inspect it if a compile error isn't self-explanatory.

- [ ] **Step 5: Commit**

```bash
git add mockymock/cli/main.py tests/integration/test_cli.py
git commit -m "feat: wire generate and run subcommands end to end"
```

- [ ] **Step 6 (superseded — see below): the originally-planned "make `_splice_call_sites` recurse" fix turned out to be unsafe, not just incomplete**

A fix attempt for this step discovered that recursing the splicer into nested statement bodies is NOT a safe fix, unlike the analogous fixes in Task 5 and Task 6. Splicing requires knowing a statement's *end* line (via `source_map.py`'s boundary-list approach, Task 8), and `cobolparser`'s AST carries **no location data at all** for block terminators (`END-IF`, `END-EVALUATE`, etc.). Concretely: splicing a `CALL` that's the last statement inside an `IF` body would comment out the following `END-IF` along with it, leaving the `IF` unterminated — the mock dispatch block would fall inside the `IF`'s conditional body, silently changing control flow in a way neither compilation nor `VERIFY` reliably catches. This is worse than the original gap (an unmocked real CALL), so the fix attempt correctly stopped rather than ship it.

**Corrected design (human decision, matches the existing PERFORM...THRU precedent from Task 6): refuse a `MOCK CALL` that targets a nested call site, rather than attempt to splice it.** `_splice_call_sites` in `mockymock/cli/main.py` needs NO changes at all — its original flat, top-level-only scan (from Task 14's initial implementation) is correct as long as refusal.py guarantees only top-level call sites ever reach it. The fix moves entirely into `mock_surface.py` (tag each `CallSite` with whether it's nested) and `refusal.py` (refuse a `MOCK CALL` whose only matching site(s) are nested).

**`mockymock/analysis/mock_surface.py` changes:**

Add a `nested: bool = False` field to `CallSite`:

```python
@dataclass
class CallSite:
    program_name: str | None  # literal name if STATIC, None if DYNAMIC
    kind: CallKind
    paragraph_name: str
    line: int
    nested: bool = False
```

Thread a `nested` parameter through `_classify_statement` and `_walk_statements` (top-level calls default to `False`; every recursive call passes `nested=True`):

```python
def _classify_statement(
    statement, paragraph_name: str, surface: MockSurface, nested: bool
) -> None:
    """Classify a single statement (top-level or nested) into `surface`."""
    if isinstance(statement, CallStatement):
        kind = CallKind.DYNAMIC if statement.is_dynamic else CallKind.STATIC
        surface.call_sites.append(
            CallSite(
                program_name=None if statement.is_dynamic else statement.called_program,
                kind=kind,
                paragraph_name=paragraph_name,
                line=statement.location.line,
                nested=nested,
            )
        )
    elif isinstance(statement, _FILE_IO_TYPES):
        surface.file_io_paragraphs.add(paragraph_name)
    elif isinstance(statement, _EXEC_TYPES):
        surface.exec_paragraphs.add(paragraph_name)


def _walk_statements(
    statements, paragraph_name: str, surface: MockSurface, nested: bool = False
) -> None:
    """Classify `statements` and recurse into every nested statement body."""
    for statement in statements:
        _classify_statement(statement, paragraph_name, surface, nested)
        for nested_list in _nested_statement_lists(statement):
            _walk_statements(nested_list, paragraph_name, surface, nested=True)
```

`analyze()`'s existing call site (`_walk_statements(paragraph.statements, paragraph.paragraph_name, surface)`) needs no change — `nested` defaults to `False` there, correctly marking top-level statements.

**`mockymock/analysis/refusal.py` changes:**

In `check_test_case`, track which mocked call names have at least one *nested* reachable occurrence, alongside the existing `reachable_call_names` tracking:

```python
    reachable_call_names: set[str] = set()
    nested_call_names: set[str] = set()
    for site in surface.call_sites:
        if site.paragraph_name not in reachable:
            continue
        if site.kind.value == "dynamic":
            reasons.append(
                RefusalReason(
                    code="DYNAMIC_CALL",
                    message=(
                        f"paragraph '{site.paragraph_name}' (line {site.line}) "
                        f"contains a dynamic CALL, not supported in v1"
                    ),
                )
            )
        else:
            reachable_call_names.add(site.program_name)
            if site.nested:
                nested_call_names.add(site.program_name)
```

Add a new refusal check (placement doesn't matter relative to the other checks — e.g., right after the `UNSUPPORTED_EXEC` check, before `UNMATCHED_MOCK`):

```python
    for name in sorted(mocked_call_names & nested_call_names):
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_NESTED_CALL_TARGET",
                message=(
                    f'MOCK CALL "{name}" matches a CALL statement nested inside '
                    f"a conditional/loop body (IF/EVALUATE/inline PERFORM), which "
                    f"cannot be safely spliced in v1 (cobolparser has no location "
                    f"data for block terminators like END-IF, so the splicer "
                    f"cannot determine where the nested statement's replacement "
                    f"span should end)"
                ),
            )
        )
```

If a call name has BOTH a top-level occurrence and a nested occurrence (both reachable), it still gets refused — the splicer would attempt to splice every matching site for that name, including the unsafe nested one, so partial safety isn't good enough here.

Update the module docstring to mention this new refusal category, matching the existing style for `UNSUPPORTED_PERFORM_THRU`.

- [ ] **Step 7: Add regression tests**

Add to `tests/unit/test_mock_surface.py`: a test parsing real COBOL with a `CALL` nested inside an `IF`, asserting the resulting `CallSite.nested is True`; and a test confirming a top-level `CallSite.nested is False` (covering the existing tests still pass unmodified — `nested` defaulting to `False` shouldn't change any prior assertion).

Add to `tests/unit/test_refusal.py`: a test mirroring the `_reachable_paragraphs`/`NESTED_IF_SOURCE`-style fixtures already in this file — a paragraph with `CALL "DISCRATE"` nested inside `IF WS-FLAG = "Y" ... END-IF`, `mocked_call_names={"DISCRATE"}`. Assert `UNSUPPORTED_NESTED_CALL_TARGET` is in the returned reasons. Also add a test confirming a top-level (non-nested) `MOCK CALL` for the same call name does NOT trigger this refusal (regression guard against over-refusing).

- [ ] **Step 8: Run the full suite and re-commit**

Run: `python -m pytest tests/ -v`
Expected: all tests pass (new tests included), no regressions in `test_mock_surface.py`'s or `test_refusal.py`'s existing tests. `_splice_call_sites` in `main.py` is unchanged by this fix — confirm `tests/integration/test_cli.py`'s existing line-shift/double-splicing regression tests still pass exactly as before.

```bash
git add mockymock/analysis/mock_surface.py mockymock/analysis/refusal.py tests/unit/test_mock_surface.py tests/unit/test_refusal.py
git commit -m "fix: refuse MOCK CALL targeting a nested (unsplicable) call site"
```

---

## Task 15: ORDRPROC Worked Example

**Files:**
- Create: `examples/ordrproc/ORDRPROC.cbl`
- Create: `examples/ordrproc/ORDRPROC.cut`
- Create: `examples/ordrproc/README.md`
- Test: `tests/integration/test_ordrproc_example.py`

**Interfaces:**
- Consumes: `mockymock.cli.main.main` (Task 14).
- Produces: a committed, runnable example a new contributor can point at; the capstone integration test for the whole pipeline.

- [ ] **Step 1: Write the example files**

`examples/ordrproc/ORDRPROC.cbl` (same program used throughout this plan's tests, written once as the canonical example):

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDRPROC.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  ORD-AMOUNT          PIC 9(5)V99.
       01  WS-DISCOUNT-PCT     PIC 9V99.
       01  WS-NET-AMOUNT       PIC 9(5)V99.

       PROCEDURE DIVISION.
       PROCESS-ORDER.
           CALL "DISCRATE" USING ORD-AMOUNT WS-DISCOUNT-PCT
           COMPUTE WS-NET-AMOUNT =
               ORD-AMOUNT - (ORD-AMOUNT * WS-DISCOUNT-PCT).
```

`examples/ordrproc/ORDRPROC.cut`:

```cobol
TESTSUITE "ORDRPROC discount calculation"

TESTCASE "10% discount reduces net amount correctly"
    MOCK CALL "DISCRATE"
        MOVE 0.10 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 100.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 90.00
    VERIFY "DISCRATE" WAS CALLED ONCE

TESTCASE "Zero discount leaves amount unchanged"
    MOCK CALL "DISCRATE"
        MOVE 0.00 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 50.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 50.00
```

`examples/ordrproc/README.md`:

```markdown
# ORDRPROC example

A minimal program that calls an external `DISCRATE` subprogram to get a
discount rate, then computes a net amount. Demonstrates v1's only
mockable category: static CALL.

```bash
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut
```

Try changing `EXPECT WS-NET-AMOUNT TO BE 90.00` to a wrong value and
re-running to see a FAIL case, or `mockymock generate ORDRPROC.cbl` to see
what auto-scaffolding produces for this program from scratch.
```

- [ ] **Step 2: Write the failing test**

```python
# tests/integration/test_ordrproc_example.py
import shutil
from pathlib import Path

import pytest

from mockymock.cli.main import main

requires_gnucobol = pytest.mark.skipif(
    shutil.which("cobc") is None, reason="GnuCOBOL (cobc) not installed"
)

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "ordrproc"


@requires_gnucobol
def test_committed_ordrproc_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "ORDRPROC.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "ORDRPROC.cut"),
        ]
    )
    assert exit_code == 0
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python -m pytest tests/integration/test_ordrproc_example.py -v`
Expected: FAIL — `FileNotFoundError`, example files don't exist yet (or it's skipped if `cobc` is unavailable — run `mockymock setup` first).

- [ ] **Step 4: Confirm the example files from Step 1 are saved, then run it**

Run: `python -m pytest tests/integration/test_ordrproc_example.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the full test suite to confirm nothing regressed**

Run: `python -m pytest tests/ -v`
Expected: all unit tests pass; integration tests pass if `cobc` is on PATH, otherwise skip with a clear reason — no unexpected failures or errors.

- [ ] **Step 6: Commit**

```bash
git add examples/ tests/integration/test_ordrproc_example.py
git commit -m "feat: ORDRPROC worked example and end-to-end capstone test"
```

---

## Task 16: Copybook Expansion Wiring

The spec (§2 "In scope") lists copybook expansion as MVP scope, but Tasks 1-15 never wire it into the CLI — `_cmd_generate`/`_cmd_run` call `parse_cobol` directly. This task closes that gap.

One non-obvious API fact, verified against `cobolparser/preprocess/copybook_expander.py:704-757`: `parse_cobol_with_expansion()` internally calls `expand_copybooks()` then `parse_cobol()`, but its return value is only the `ParseResult` — it does **not** expose `expansion.expanded_source`. Since the splicer (Task 14's `_cmd_run`) needs the actual expanded text to feed into `normalize_fixed_format()` (not just the parsed AST), this task calls `expand_copybooks()` directly and threads `expansion.expanded_source` through both parsing and normalization itself, rather than using the convenience wrapper.

**Files:**
- Modify: `mockymock/cli/main.py` (`_cmd_generate`, `_cmd_run`, `build_parser`)
- Create: `tests/integration/fixtures/copybook_example/MAINPGM.cbl`
- Create: `tests/integration/fixtures/copybook_example/MAINPGM.cut`
- Create: `tests/integration/fixtures/copybook_example/copybooks/ORDREC.CPY`
- Test: `tests/integration/test_copybook_expansion.py`

**Interfaces:**
- Consumes: `cobolparser.preprocess.expand_copybooks(source_code: str, copybook_paths: list[str]) -> CopybookExpansion` (`.expanded_source: str`, verified).
- Produces: `--copybook-path` (repeatable) on both `mockymock generate` and `mockymock run`.

- [ ] **Step 1: Write the copybook fixture**

`tests/integration/fixtures/copybook_example/copybooks/ORDREC.CPY`:

```cobol
       01  ORD-AMOUNT          PIC 9(5)V99.
       01  WS-DISCOUNT-PCT     PIC 9V99.
       01  WS-NET-AMOUNT       PIC 9(5)V99.
```

`tests/integration/fixtures/copybook_example/MAINPGM.cbl`:

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINPGM.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY ORDREC.

       PROCEDURE DIVISION.
       PROCESS-ORDER.
           CALL "DISCRATE" USING ORD-AMOUNT WS-DISCOUNT-PCT
           COMPUTE WS-NET-AMOUNT =
               ORD-AMOUNT - (ORD-AMOUNT * WS-DISCOUNT-PCT).
```

`tests/integration/fixtures/copybook_example/MAINPGM.cut`:

```cobol
TESTSUITE "MAINPGM discount calculation (via copybook)"

TESTCASE "10% discount reduces net amount correctly"
    MOCK CALL "DISCRATE"
        MOVE 0.10 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 100.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 90.00
```

- [ ] **Step 2: Write the failing test**

```python
# tests/integration/test_copybook_expansion.py
import shutil
from pathlib import Path

import pytest

from mockymock.cli.main import main

requires_gnucobol = pytest.mark.skipif(
    shutil.which("cobc") is None, reason="GnuCOBOL (cobc) not installed"
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "copybook_example"


@requires_gnucobol
def test_run_expands_copybook_and_passes():
    exit_code = main(
        [
            "run",
            str(FIXTURE_DIR / "MAINPGM.cbl"),
            "--cut",
            str(FIXTURE_DIR / "MAINPGM.cut"),
            "--copybook-path",
            str(FIXTURE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 0


def test_generate_expands_copybook_and_finds_call_site(tmp_path: Path):
    output = tmp_path / "MAINPGM.cut"
    exit_code = main(
        [
            "generate",
            str(FIXTURE_DIR / "MAINPGM.cbl"),
            "-o",
            str(output),
            "--copybook-path",
            str(FIXTURE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 0
    assert 'MOCK CALL "DISCRATE"' in output.read_text()


def test_run_without_copybook_path_refuses_with_parse_error(capsys):
    exit_code = main(
        [
            "run",
            str(FIXTURE_DIR / "MAINPGM.cbl"),
            "--cut",
            str(FIXTURE_DIR / "MAINPGM.cut"),
        ]
    )
    assert exit_code == 1
    assert "PARSE_ERROR" in capsys.readouterr().out
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python -m pytest tests/integration/test_copybook_expansion.py -v`
Expected: FAIL — `unrecognized arguments: --copybook-path` (the flag doesn't exist yet).

- [ ] **Step 4: Add `--copybook-path` and copybook expansion to `mockymock/cli/main.py`**

Read the current file first — `_cmd_generate`/`_cmd_run` were extended across Task 14's own fix cycles, so match against what's actually there rather than an earlier snapshot.

In `_cmd_generate`, wherever `raw_source`/`source_path.read_text()` currently feeds into `parse_cobol`, insert copybook expansion first:

```python
    from cobolparser.preprocess import expand_copybooks

    source_path = Path(args.program)
    raw_source = source_path.read_text()
    if args.copybook_path:
        expansion = expand_copybooks(raw_source, copybook_paths=args.copybook_path)
        raw_source = expansion.expanded_source
    result = parse_cobol(raw_source, filename=source_path.name)
```

In `_cmd_run`, the same pattern — expand `raw_source` in place BEFORE it's parsed and BEFORE it's later passed to `normalize_fixed_format(raw_source.splitlines())`:

```python
    from cobolparser.preprocess import expand_copybooks

    source_path = Path(args.program)
    raw_source = source_path.read_text()
    if args.copybook_path:
        expansion = expand_copybooks(raw_source, copybook_paths=args.copybook_path)
        raw_source = expansion.expanded_source
    result = parse_cobol(raw_source, filename=source_path.name)
```

(`_cmd_run`'s later `normalize_fixed_format(raw_source.splitlines())` call is unchanged — it already operates on whatever `raw_source` holds at that point, so threading the expanded text through the same variable is sufficient; no other line in `_cmd_run` needs to change, including the splice/driver-insertion logic added across Task 14's fix cycles.)

In `build_parser`, add to both subparsers:

```python
    generate_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
```

```python
    run_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
```

- [ ] **Step 5: Run it to verify it passes**

Run: `python -m pytest tests/integration/test_copybook_expansion.py -v`
Expected: PASS (3 passed; 1 of them gated on `cobc` availability — expect a SKIP there if `cobc` is still unavailable on this machine, same tracked situation since Task 3, not a failure).

- [ ] **Step 6: Run the full suite and re-commit**

Run: `python -m pytest tests/ -v`
Expected: all unit tests pass; integration tests pass if `cobc` is on PATH, otherwise skip; no regressions.

```bash
git add mockymock/cli/main.py tests/integration/fixtures/copybook_example/ tests/integration/test_copybook_expansion.py
git commit -m "feat: wire copybook expansion into generate and run"
```

---

## Self-Review

**Spec coverage** (against `docs/2026-06-30-mockymock-mvp-design.md`):
- §2 In-scope items: static CALL mocking only (Tasks 5, 11, 14), one binary per TESTSUITE (Task 12), working-storage reset (Task 10), copybook expansion (Task 16), auto-scaffolding (Task 13), GnuCOBOL self-bootstrap (Task 2), standalone CLI (Task 14). Covered.
- §5.3/5.4/5.5 (dispatch, reset, static/dynamic): Tasks 11, 10, 6/5 respectively. Covered.
- §6 DSL grammar: Task 7. Covered.
- §9 Copybook handling: Task 16. Covered.
- §10 Refusal conditions: Task 6, wired into `_cmd_run` in Task 14 (later extended with `UNSUPPORTED_NESTED_CALL_TARGET`, discovered during Task 14's own review cycle — see that task's history). Covered.
- §11 Output capture: the `__MOCKYMOCK__` prefix convention, Task 4/12. Covered (wire format made precise, see Global Constraints note).
- §12 Fidelity framing: not code — a documentation commitment already satisfied by the spec itself; no task needed.
- §13 Testing strategy: every task follows unit-without-cobc / integration-with-cobc split as designed.

**Placeholder scan:** no "TBD"/"implement later" left in any step. The one explicit "fix this generated code" moment (Task 13, scaffold output failing its own round-trip test) is resolved inline with working code, not deferred.

**Type consistency:** `MockSurface`/`CallSite`/`CallKind` (Task 5) match their usage in Task 6 (`refusal.py`), Task 13 (`generator.py`), and Task 14 (`_cmd_generate`/`_cmd_run`). `MockTestSuite`/`MockTestCase`/`MockCallDirective`/`ExpectDirective`/`VerifyDirective` (Task 7) match their usage in Tasks 11, 12, 14. `DriverArtifact.working_storage_lines`/`.procedure_lines` (Task 12) match how Task 14's `_insert_driver` consumes them. `tally_field_name` (Task 11) is reused identically in Task 12 rather than reimplemented.

---

Plan complete and saved to `docs/2026-06-30-mockymock-mvp-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
