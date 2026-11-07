# Coverage Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--coverage` flag to `mockymock run` that compiles with GnuCOBOL's native `--coverage`/gcov instrumentation and reports per-line coverage after the run, proven end-to-end on two real-world programs (a new `DEPTIMSM` example and the existing `ACCTPRG` suite, unmodified).

**Architecture:** `runtime/docker_toolchain.py`'s `compile_source` gains a `coverage: bool` flag that adds `--coverage` to the `cobc` invocation; a new `run_gcov` function runs `gcov` inside the same container after execution and reads back the `.gcov` report. A new `mockymock/report/coverage.py` module parses that gcov text into a `CoverageReport` and formats it for the console. `cli/main.py`'s `_cmd_run` wires `--coverage`/`--coverage-out` together, printing/writing the report before the sandbox is cleaned up.

**Tech Stack:** Python 3.11+, GnuCOBOL 3.2 (via the existing `mockymock-cobc` Docker container — gcc/gcov are already present in that image, confirmed during design), pytest.

## Global Constraints

- Spec: `docs/2026-07-17-coverage-reporting-design.md` (read this first — it has the full rationale, including two addenda written after empirical verification).
- v1 reports line numbers against the **instrumented** source (post-splicing), not the original `.cbl` — this is a deliberate, agreed scope boundary, not a bug to fix in this plan.
- Coverage is purely additive: it must never change the existing pass/fail exit code or `--junit-xml` behavior. Every existing test in `tests/unit/test_cli_docker.py` and `tests/integration/` must keep passing unmodified except for the one required signature update named explicitly in Task 4.
- No new Python dependencies and no Dockerfile changes — `gcc`/`gcov` are already installed in the `mockymock-cobc` image (Debian's `gcc` package pulls in `gcov`; confirmed via `docker exec mockymock-cobc gcov --version` during the design spike).
- All new Docker-requiring tests must use the existing `tests.integration._docker.requires_docker` skip guard so the suite stays green on a Docker-less machine.

---

### Task 1: `compile_source` gains a `coverage` flag

**Files:**
- Modify: `mockymock/runtime/docker_toolchain.py:246-296` (the `compile_source` function)
- Test: `tests/unit/test_docker_toolchain.py` (append new tests after the existing `compile_source` tests, i.e. after line 468)

**Interfaces:**
- Consumes: nothing new (uses existing `to_container_path`, `CONTAINER`, `WORK_ROOT`, `CompileResult`).
- Produces: `compile_source(source_path: Path, coverage: bool = False) -> CompileResult` — the `coverage` parameter is new; existing callers that don't pass it keep today's exact behavior (default `False`, identical argv to before). Later tasks (4) call this as `compile_source(instrumented_path, coverage=args.coverage)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_docker_toolchain.py` (append after `test_compile_source_times_out_cleanly_when_docker_exec_hangs`, i.e. after line 468, before the `run_binary` import block):

```python
def test_compile_source_with_coverage_passes_flag_to_cobc(tmp_path):
    work, source = _work(tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        (source.parent / "PROG").write_text("")
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = compile_source(source, coverage=True)

    assert calls == [
        [
            "docker",
            "exec",
            CONTAINER,
            "cobc",
            "-free",
            "--coverage",
            "-x",
            "/work/mockymock-x/PROG.cbl",
            "-o",
            "/work/mockymock-x/PROG",
        ]
    ]
    assert result.success


def test_compile_source_without_coverage_omits_the_flag(tmp_path):
    """Default behavior (coverage=False, or the parameter omitted entirely)
    must produce the exact same argv as before this feature existed --
    this pins that the existing test_compile_source_execs_cobc_with_container_paths
    behavior is unchanged."""
    work, source = _work(tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        (source.parent / "PROG").write_text("")
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = compile_source(source)

    assert "--coverage" not in calls[0]
    assert result.success
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_docker_toolchain.py -k coverage -v`
Expected: FAIL with `TypeError: compile_source() got an unexpected keyword argument 'coverage'`

- [ ] **Step 3: Implement `coverage` in `compile_source`**

Replace `mockymock/runtime/docker_toolchain.py`'s `compile_source` function (currently lines 246-296) with:

```python
def compile_source(source_path: Path, coverage: bool = False) -> CompileResult:
    """Compile a free-form COBOL source file (which must live under
    WORK_ROOT) inside the container. The binary is written next to the
    source with no suffix -- it is a Linux ELF that only ever executes
    inside the container.

    `coverage=True` adds GnuCOBOL's own `--coverage` flag, which builds on
    gcc's gcov machinery (cobc transpiles COBOL to C): the resulting
    binary, once executed, writes a `.gcda` file next to itself that
    `run_gcov` (below) turns into a per-COBOL-line report. See
    docs/2026-07-17-coverage-reporting-design.md."""
    container_source = to_container_path(source_path, WORK_ROOT)
    binary_path = source_path.with_suffix("")
    container_binary = to_container_path(binary_path, WORK_ROOT)
    cmd = ["docker", "exec", CONTAINER, "cobc", "-free"]
    if coverage:
        cmd.append("--coverage")
    cmd += ["-x", container_source, "-o", container_binary]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CompileResult(
            success=False,
            binary_path=None,
            stdout="",
            stderr=(
                f"mockymock: docker exec cobc timed out after 600s "
                f"(the docker daemon may be wedged): {exc}\n"
            ),
        )
    except OSError as exc:
        return CompileResult(
            success=False,
            binary_path=None,
            stdout="",
            stderr=f"mockymock: could not run docker exec: {exc}\n",
        )
    success = result.returncode == 0 and binary_path.exists()
    return CompileResult(
        success=success,
        binary_path=binary_path if success else None,
        stdout=result.stdout,
        stderr=result.stderr,
    )
```

- [ ] **Step 4: Run all docker_toolchain tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_docker_toolchain.py -v`
Expected: PASS, all tests (including the two new ones and every pre-existing one) — 0 failures.

- [ ] **Step 5: Commit**

```bash
git add mockymock/runtime/docker_toolchain.py tests/unit/test_docker_toolchain.py
git commit -m "feat(coverage): compile_source gains a coverage flag"
```

---

### Task 2: `run_gcov` runs gcov inside the container

**Files:**
- Modify: `mockymock/runtime/docker_toolchain.py` (add `GcovResult` dataclass and `run_gcov` function after `run_binary`, i.e. after the current end of file)
- Test: `tests/unit/test_docker_toolchain.py` (append after Task 1's new tests)

**Interfaces:**
- Consumes: `to_container_path`, `CONTAINER`, `WORK_ROOT` (all already in this module).
- Produces: `GcovResult(success: bool, gcov_text: str, stderr: str)` and `run_gcov(source_path: Path) -> GcovResult`. `source_path` is the same instrumented `.cbl` path passed to `compile_source(..., coverage=True)` — `run_gcov` derives the `.gcda` and `.gcov` filenames from it. Task 4 calls this as `docker_toolchain.run_gcov(instrumented_path)` after `run_binary` succeeds.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_docker_toolchain.py` (at the end of the file, after the existing `run_binary` tests):

```python
from mockymock.runtime.docker_toolchain import GcovResult, run_gcov


def _work_with_gcda(tmp_path, write_gcda: bool = True):
    work = tmp_path / "work"
    sandbox = work / "mockymock-x"
    sandbox.mkdir(parents=True)
    source = sandbox / "PROG.cbl"
    source.write_text("dummy\n")
    if write_gcda:
        (sandbox / "PROG.gcda").write_text("")
    return work, source


def test_run_gcov_execs_gcov_with_container_dir_and_gcda_name(tmp_path):
    work, source = _work_with_gcda(tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        (source.parent / "PROG.cbl.gcov").write_text(
            "        -:    0:Source:PROG.cbl\n"
            "       1*:    1:DISPLAY 'X'.\n"
        )
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = run_gcov(source)

    assert calls == [
        [
            "docker",
            "exec",
            "-w",
            "/work/mockymock-x",
            CONTAINER,
            "gcov",
            "PROG.gcda",
        ]
    ]
    assert result.success
    assert "DISPLAY 'X'." in result.gcov_text


def test_run_gcov_reports_missing_coverage_data_cleanly(tmp_path):
    """No .gcda means the binary never exited normally (e.g. a timeout's
    SIGKILL preempted the gcov atexit dump handler) -- this must be a
    clean, explanatory failure, not a gcov error about a missing file, and
    must never call docker exec at all."""
    work, source = _work_with_gcda(tmp_path, write_gcda=False)
    with (
        mock.patch("mockymock.runtime.docker_toolchain.subprocess.run") as run_mock,
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = run_gcov(source)
    run_mock.assert_not_called()
    assert not result.success
    assert "did not exit normally" in result.stderr


def test_run_gcov_surfaces_gcov_command_failure(tmp_path):
    work, source = _work_with_gcda(tmp_path)
    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            return_value=_completed([], returncode=1, stderr="gcov: boom"),
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = run_gcov(source)
    assert not result.success
    assert "gcov: boom" in result.stderr


def test_run_gcov_reports_cleanly_when_gcov_produces_no_output_file(tmp_path):
    work, source = _work_with_gcda(tmp_path)
    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            return_value=_completed([], returncode=0),  # exits 0 but writes nothing
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = run_gcov(source)
    assert not result.success
    assert "PROG.cbl.gcov" in result.stderr


def test_run_gcov_wraps_docker_oserror_cleanly(tmp_path):
    work, source = _work_with_gcda(tmp_path)
    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            side_effect=OSError("docker went away"),
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = run_gcov(source)
    assert not result.success
    assert "docker went away" in result.stderr
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_docker_toolchain.py -k run_gcov -v`
Expected: FAIL with `ImportError: cannot import name 'GcovResult'` (or `'run_gcov'`)

- [ ] **Step 3: Implement `GcovResult` and `run_gcov`**

Append to the end of `mockymock/runtime/docker_toolchain.py`:

```python
@dataclass
class GcovResult:
    success: bool
    gcov_text: str
    stderr: str


def run_gcov(source_path: Path) -> GcovResult:
    """Run gcov against the .gcda file a --coverage-compiled binary
    (compile_source(..., coverage=True)) writes once it has executed,
    returning the resulting <name>.cbl.gcov text -- a per-COBOL-line
    report `report/coverage.py`'s `parse_gcov` can turn into a
    CoverageReport.

    The .gcda file is only written by the C runtime's coverage-dump
    handler on normal process exit; a binary killed by run_binary's
    timeout SIGKILL never reaches it, so that case is detected up front
    and reported as a clean, explanatory failure rather than a confusing
    gcov error about a missing file."""
    gcda_path = source_path.with_suffix(".gcda")
    if not gcda_path.exists():
        return GcovResult(
            success=False,
            gcov_text="",
            stderr=(
                "mockymock: no coverage data produced (the binary did not "
                "exit normally, so its coverage-dump handler never ran)\n"
            ),
        )
    container_source = to_container_path(source_path, WORK_ROOT)
    container_dir = container_source.rsplit("/", 1)[0]
    try:
        result = subprocess.run(
            ["docker", "exec", "-w", container_dir, CONTAINER, "gcov", gcda_path.name],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GcovResult(
            success=False, gcov_text="", stderr=f"mockymock: gcov failed: {exc}\n"
        )
    if result.returncode != 0:
        return GcovResult(success=False, gcov_text="", stderr=result.stderr)
    gcov_path = source_path.parent / (source_path.name + ".gcov")
    if not gcov_path.exists():
        return GcovResult(
            success=False,
            gcov_text="",
            stderr=f"mockymock: gcov did not produce {gcov_path.name}\n",
        )
    return GcovResult(success=True, gcov_text=gcov_path.read_text(), stderr="")
```

`dataclass` is already imported at the top of this file (`from dataclasses import dataclass` — check it's there; if not, add it. As of Task 1 the file does not import `dataclass` yet, since `CompileResult`/`ExecutionResult` live in other modules — add `from dataclasses import dataclass` to `docker_toolchain.py`'s import block at the top of the file if it isn't already present).

- [ ] **Step 4: Run all docker_toolchain tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_docker_toolchain.py -v`
Expected: PASS, all tests, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add mockymock/runtime/docker_toolchain.py tests/unit/test_docker_toolchain.py
git commit -m "feat(coverage): run_gcov executes gcov inside the mockymock-cobc container"
```

---

### Task 3: `report/coverage.py` — parse and format gcov output

**Files:**
- Create: `mockymock/report/coverage.py`
- Test: Create `tests/unit/test_coverage.py`

**Interfaces:**
- Consumes: nothing (pure string parsing, no Docker dependency — mirrors `report/results.py`/`report/formatters.py`'s existing Docker-free design).
- Produces: `UncoveredLine(line_number: int, text: str)`, `CoverageReport(total_executable: int, total_covered: int, uncovered_lines: list[UncoveredLine])` with a `.percentage` property, `parse_gcov(gcov_text: str) -> CoverageReport`, `format_coverage_console(report: CoverageReport, source_name: str) -> str`. Task 4 imports all of these.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_coverage.py`:

```python
"""Tests for parsing and formatting GnuCOBOL/gcov's per-line coverage
output. Pure string parsing -- no Docker dependency, mirrors
report/results.py's existing design."""

import pytest

from mockymock.report.coverage import (
    CoverageReport,
    UncoveredLine,
    format_coverage_console,
    parse_gcov,
)

SAMPLE_GCOV = (
    "        -:    0:Source:PROG.cbl\n"
    "        -:    0:Graph:PROG.gcno\n"
    "        -:    0:Data:PROG.gcda\n"
    "        -:    0:Runs:1\n"
    "        -:    1:IDENTIFICATION DIVISION.\n"
    "        -:    2:PROGRAM-ID. PROG.\n"
    "        -:    3:\n"
    "       1*:    4:       01  WS-FLAG   PIC X VALUE 'N'.\n"
    "        -:    5:PROCEDURE DIVISION.\n"
    "       1*:    6:MAIN-PARA.\n"
    "       7*:    7:    DISPLAY 'HELLO'\n"
    "    #####:    8:    DISPLAY 'NEVER'\n"
    "        -:    9:.\n"
)


def test_parse_gcov_counts_covered_and_uncovered_executable_lines():
    report = parse_gcov(SAMPLE_GCOV)
    assert report.total_executable == 4  # lines 4, 6, 7, 8
    assert report.total_covered == 3  # lines 4, 6, 7
    assert len(report.uncovered_lines) == 1
    assert report.uncovered_lines[0].line_number == 8
    assert "DISPLAY 'NEVER'" in report.uncovered_lines[0].text


def test_parse_gcov_percentage_is_covered_over_executable():
    report = parse_gcov(SAMPLE_GCOV)
    assert report.percentage == pytest.approx(75.0)


def test_parse_gcov_strips_star_suffix_from_multi_block_line_counts():
    """gcov suffixes a line's count with '*' when the line maps to
    multiple basic blocks with differing counts -- not itself a sign the
    line is uncovered. The '*' must not break int parsing."""
    report = parse_gcov("       3*:    1:IF X = 1 THEN Y ELSE Z.\n")
    assert report.total_executable == 1
    assert report.total_covered == 1
    assert report.uncovered_lines == []


def test_parse_gcov_ignores_header_lines_with_line_number_zero():
    report = parse_gcov("        -:    0:Source:PROG.cbl\n")
    assert report.total_executable == 0
    assert report.total_covered == 0


def test_parse_gcov_percentage_is_100_when_no_executable_lines():
    report = parse_gcov("        -:    0:Source:PROG.cbl\n        -:    1:* comment\n")
    assert report.percentage == 100.0


def test_parse_gcov_ignores_malformed_lines_without_crashing():
    report = parse_gcov("not a gcov line at all\n       1*:    1:DISPLAY 'X'.\n")
    assert report.total_executable == 1
    assert report.total_covered == 1


def test_format_coverage_console_reports_percentage_and_counts():
    report = CoverageReport(total_executable=907, total_covered=692, uncovered_lines=[])
    text = format_coverage_console(report, "DEPTIMSM.cbl")
    assert "76.30% lines executed (692/907)" in text
    assert "DEPTIMSM.cbl" in text


def test_format_coverage_console_lists_uncovered_lines():
    report = CoverageReport(
        total_executable=2,
        total_covered=1,
        uncovered_lines=[UncoveredLine(line_number=8, text="    DISPLAY 'NEVER'")],
    )
    text = format_coverage_console(report, "PROG.cbl")
    assert "  8:     DISPLAY 'NEVER'" in text


def test_format_coverage_console_omits_uncovered_section_when_fully_covered():
    report = CoverageReport(total_executable=4, total_covered=4, uncovered_lines=[])
    text = format_coverage_console(report, "PROG.cbl")
    assert "uncovered lines" not in text
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_coverage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mockymock.report.coverage'`

- [ ] **Step 3: Implement `mockymock/report/coverage.py`**

```python
"""Parser and formatter for GnuCOBOL/gcov's per-line COBOL coverage
output.

`cobc --coverage` (see runtime/docker_toolchain.py's `compile_source`)
builds on gcc's own gcov machinery, since GnuCOBOL transpiles COBOL to C.
Running `gcov <program>.gcda` (runtime/docker_toolchain.py's `run_gcov`)
after executing the compiled binary produces a `<program>.cbl.gcov` file
with one line per source line, in the format
`<count-or-dash-or-hashes>:<line-number>:<source text>`:

- `-` means the line is not executable (declarations, comments, blanks).
- `#####` means the line is executable but was never hit.
- a number is the hit count; gcov suffixes it with `*` when the line maps
  to more than one basic block with differing counts (not itself a sign
  the line is uncovered -- only that `gcov -a` would show a per-block
  breakdown).

See docs/2026-07-17-coverage-reporting-design.md for the full design,
including why v1 reports against the instrumented (post-splicing) source
rather than the original .cbl, and why even a suite that exercises every
real branch will not read anywhere near 100% (the splicer's per-boundary-
site mock dispatch has one WHEN branch per test case that shares that
mock key, most of which are structurally unreachable from any single
case's own PERFORM target)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UncoveredLine:
    line_number: int
    text: str


@dataclass
class CoverageReport:
    total_executable: int
    total_covered: int
    uncovered_lines: list[UncoveredLine] = field(default_factory=list)

    @property
    def percentage(self) -> float:
        if self.total_executable == 0:
            return 100.0
        return 100.0 * self.total_covered / self.total_executable


def parse_gcov(gcov_text: str) -> CoverageReport:
    total_executable = 0
    total_covered = 0
    uncovered: list[UncoveredLine] = []
    for raw_line in gcov_text.splitlines():
        parts = raw_line.split(":", 2)
        if len(parts) != 3:
            continue
        count_field, line_field, text = parts
        count_field = count_field.strip()
        line_field = line_field.strip()
        if not line_field.isdigit():
            continue
        line_number = int(line_field)
        if line_number == 0:
            continue  # header lines: Source:/Graph:/Data:/Runs:
        if count_field == "-":
            continue  # not executable
        if count_field == "#####":
            total_executable += 1
            uncovered.append(UncoveredLine(line_number=line_number, text=text))
            continue
        count_field = count_field.rstrip("*")
        try:
            count = int(count_field)
        except ValueError:
            continue
        total_executable += 1
        if count > 0:
            total_covered += 1
        else:
            uncovered.append(UncoveredLine(line_number=line_number, text=text))
    return CoverageReport(
        total_executable=total_executable,
        total_covered=total_covered,
        uncovered_lines=uncovered,
    )


def format_coverage_console(report: CoverageReport, source_name: str) -> str:
    lines = [
        f"mockymock run: coverage: {report.percentage:.2f}% lines executed "
        f"({report.total_covered}/{report.total_executable}) in {source_name}"
    ]
    if report.uncovered_lines:
        lines.append("mockymock run: coverage: uncovered lines:")
        for uncovered in report.uncovered_lines:
            lines.append(f"  {uncovered.line_number}: {uncovered.text}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify all tests pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_coverage.py -v`
Expected: PASS, all 9 tests, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add mockymock/report/coverage.py tests/unit/test_coverage.py
git commit -m "feat(coverage): parse and format gcov's per-line COBOL coverage output"
```

---

### Task 4: Wire `--coverage`/`--coverage-out` into the CLI

**Files:**
- Modify: `mockymock/cli/main.py` (argparse setup and `_cmd_run`)
- Modify: `tests/unit/test_cli_docker.py` (the `_run_cli` helper's `fake_compile` signature, plus new tests)

**Interfaces:**
- Consumes: `docker_toolchain.compile_source(path, coverage=bool)` (Task 1), `docker_toolchain.run_gcov(path) -> GcovResult` (Task 2), `report.coverage.parse_gcov`/`format_coverage_console` (Task 3).
- Produces: `mockymock run --coverage [--coverage-out PATH]` — no new importable interface, this is the top-level CLI behavior other tasks (5, 6) drive via `mockymock.cli.main.main([...])`.

- [ ] **Step 1: Update the existing `_run_cli` test helper first (required before any new CLI test can pass)**

In `tests/unit/test_cli_docker.py`, find the `_run_cli` function (around line 160) and its nested `fake_compile`. Replace:

```python
    def fake_compile(source_path: Path) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")
```

with:

```python
    def fake_compile(source_path: Path, coverage: bool = False) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")
```

This is the only change needed to `_run_cli` itself — `_cmd_run` (Step 3 below) will call `compile_source(instrumented_path, coverage=args.coverage)` unconditionally (even when `args.coverage` is `False`), so every existing test that goes through `_run_cli` needs this fake to accept the keyword argument or it will raise `TypeError: fake_compile() got an unexpected keyword argument 'coverage'`.

The two other `fake_compile` definitions in this file (`test_run_neutralizes_entry_linkage_and_reports_it`'s local one, and none elsewhere) — check with:

```bash
grep -n "def fake_compile" tests/unit/test_cli_docker.py
```

Apply the same one-line signature change (`coverage: bool = False` added) to every `fake_compile` definition this returns.

- [ ] **Step 2: Write the failing tests**

Append to `tests/unit/test_cli_docker.py` (at the end of the file):

```python
# --- --coverage flag (docs/2026-07-17-coverage-reporting-design.md) --------

from mockymock.runtime.docker_toolchain import GcovResult

COVERAGE_GCOV_TEXT = (
    "        -:    0:Source:ORDRPROC.cbl\n"
    "       1*:    1:PROCESS-ORDER.\n"
    "       1*:    2:    CALL \"DISCRATE\" USING WS-AMOUNT.\n"
    "    #####:    3:    DISPLAY 'UNREACHED'.\n"
)


def _run_cli_with_coverage(tmp_path, executed: ExecutionResult, gcov_result: GcovResult):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)

    def fake_compile(source_path: Path, coverage: bool = False) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")

    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=fake_compile,
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_binary", return_value=executed
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_gcov", return_value=gcov_result
        ) as gcov_mock,
    ):
        exit_code = main(
            ["run", str(program), "--cut", str(cut), "--coverage"]
        )
    return exit_code, gcov_mock


def test_run_coverage_prints_summary_and_uncovered_lines(tmp_path, capsys):
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    gcov_result = GcovResult(success=True, gcov_text=COVERAGE_GCOV_TEXT, stderr="")
    exit_code, gcov_mock = _run_cli_with_coverage(tmp_path, executed, gcov_result)
    assert exit_code == 0
    gcov_mock.assert_called_once()
    out = capsys.readouterr().out
    assert "coverage: 66.67% lines executed (2/3)" in out
    assert "3:     DISPLAY 'UNREACHED'." in out


def test_run_coverage_without_flag_never_calls_gcov(tmp_path, capsys):
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)

    def fake_compile(source_path: Path, coverage: bool = False) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")

    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=fake_compile,
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_binary", return_value=executed
        ),
        mock.patch("mockymock.runtime.docker_toolchain.run_gcov") as gcov_mock,
    ):
        exit_code = main(["run", str(program), "--cut", str(cut)])
    assert exit_code == 0
    gcov_mock.assert_not_called()
    assert "coverage:" not in capsys.readouterr().out


def test_run_coverage_writes_coverage_out_file(tmp_path, capsys):
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    gcov_result = GcovResult(success=True, gcov_text=COVERAGE_GCOV_TEXT, stderr="")
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(RUN_PROGRAM)
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(RUN_CUT)
    out_path = tmp_path / "coverage.txt"

    def fake_compile(source_path: Path, coverage: bool = False) -> CompileResult:
        binary = source_path.with_suffix("")
        binary.write_text("")
        return CompileResult(success=True, binary_path=binary, stdout="", stderr="")

    with (
        mock.patch("mockymock.runtime.docker_toolchain.ensure_toolchain"),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
        mock.patch(
            "mockymock.runtime.docker_toolchain.compile_source",
            side_effect=fake_compile,
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_binary", return_value=executed
        ),
        mock.patch(
            "mockymock.runtime.docker_toolchain.run_gcov", return_value=gcov_result
        ),
    ):
        exit_code = main(
            [
                "run",
                str(program),
                "--cut",
                str(cut),
                "--coverage",
                "--coverage-out",
                str(out_path),
            ]
        )
    assert exit_code == 0
    assert "66.67% lines executed (2/3)" in out_path.read_text()


def test_run_coverage_reports_missing_data_without_failing_the_run(tmp_path, capsys):
    """gcov failing (e.g. no .gcda because the binary timed out) must not
    change the pass/fail exit code -- coverage is purely additive."""
    executed = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    gcov_result = GcovResult(
        success=False, gcov_text="", stderr="mockymock: no coverage data produced\n"
    )
    exit_code, _ = _run_cli_with_coverage(tmp_path, executed, gcov_result)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "coverage: mockymock: no coverage data produced" in out
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_cli_docker.py -k coverage -v`
Expected: FAIL — `main` raises `AttributeError: 'Namespace' object has no attribute 'coverage'` (the `--coverage` flag doesn't exist in `build_parser` yet).

- [ ] **Step 4: Add the CLI flags and wire them into `_cmd_run`**

In `mockymock/cli/main.py`, `build_parser`'s `run_parser` section (currently lines 456-478), add two new arguments after `--verbose` and before `run_parser.set_defaults(...)`:

```python
    run_parser.add_argument(
        "--coverage",
        action="store_true",
        help=(
            "Compile with GnuCOBOL's --coverage flag and report per-line "
            "coverage after the run (gcov-based; reported against the "
            "instrumented source, not the original .cbl -- see "
            "docs/2026-07-17-coverage-reporting-design.md)"
        ),
    )
    run_parser.add_argument(
        "--coverage-out",
        help="Write the full coverage report (percentage + uncovered lines) to this file",
    )
```

In `_cmd_run`'s import block (currently lines 200-232), add:

```python
    from mockymock.report.coverage import format_coverage_console, parse_gcov
```

Replace the block currently reading (lines 377-382):

```python
        assert compiled.binary_path is not None  # implied by compiled.success
        executed = docker_toolchain.run_binary(compiled.binary_path)

    if args.verbose and not args.keep_sandbox:
        shutil.rmtree(tmp, ignore_errors=True)
```

with:

```python
        assert compiled.binary_path is not None  # implied by compiled.success
        executed = docker_toolchain.run_binary(compiled.binary_path)

        coverage_text = None
        if args.coverage:
            gcov_result = docker_toolchain.run_gcov(instrumented_path)
            if gcov_result.success:
                coverage_text = format_coverage_console(
                    parse_gcov(gcov_result.gcov_text), instrumented_path.name
                )
            else:
                coverage_text = f"mockymock run: coverage: {gcov_result.stderr.rstrip()}"

    if args.verbose and not args.keep_sandbox:
        shutil.rmtree(tmp, ignore_errors=True)
```

And change the earlier `compiled = docker_toolchain.compile_source(instrumented_path)` call (currently line 370) to:

```python
        compiled = docker_toolchain.compile_source(instrumented_path, coverage=args.coverage)
```

Finally, add the printing/file-writing after the existing `--junit-xml` block (currently lines 402-405):

```python
    if args.junit_xml:
        Path(args.junit_xml).write_text(
            format_junit_xml(suite_result, crash_detail=crash_detail)
        )

    if coverage_text is not None:
        print(coverage_text)
        if args.coverage_out:
            Path(args.coverage_out).write_text(coverage_text + "\n")
```

- [ ] **Step 5: Run the new CLI tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_cli_docker.py -v`
Expected: PASS, every test in the file (new and pre-existing), 0 failures.

- [ ] **Step 6: Run the entire unit suite to check nothing else broke**

Run: `.venv/Scripts/python.exe -m pytest tests/unit -v`
Expected: PASS, 0 failures (the project's own README documents ~461+ passing at the time of writing this plan; an exact count isn't pinned here since it grows with each task in this same plan — just confirm 0 failures/0 errors).

- [ ] **Step 7: Commit**

```bash
git add mockymock/cli/main.py tests/unit/test_cli_docker.py
git commit -m "feat(coverage): wire --coverage/--coverage-out into mockymock run"
```

---

### Task 5: New `DEPTIMSM` example, proven end-to-end with `--coverage`

**Files:**
- Create: `examples/real-world/DEPTIMSM/DEPTIMSM.cbl` (copy of `../legacy-application/cobol/DEPTIMSM.cbl`, unmodified)
- Create: `examples/real-world/DEPTIMSM/copybooks/WSCOMMON.cpy`, `ERRORCD.cpy`, `IMSPCB.cpy`, `TRNSEG.cpy` (copies of the corresponding files in `../legacy-application/copybook/`, unmodified)
- Create: `examples/real-world/DEPTIMSM/DEPTIMSM.cut` (new, full content given below — already hand-verified against real GnuCOBOL in Docker while writing this plan: 20/20 cases pass, and `--coverage` reports exactly 692/907 lines = 76.30%)
- Test: Create `tests/integration/test_realworld_deptimsm_example.py`

**Interfaces:**
- Consumes: the finished `--coverage` flag from Task 4.
- Produces: nothing consumed by later tasks — this is a leaf, Docker-gated proof.

- [ ] **Step 1: Create the example directory and copy the program + copybooks**

```bash
mkdir -p examples/real-world/DEPTIMSM/copybooks
cp ../legacy-application/cobol/DEPTIMSM.cbl examples/real-world/DEPTIMSM/DEPTIMSM.cbl
cp ../legacy-application/copybook/WSCOMMON.cpy examples/real-world/DEPTIMSM/copybooks/
cp ../legacy-application/copybook/ERRORCD.cpy examples/real-world/DEPTIMSM/copybooks/
cp ../legacy-application/copybook/IMSPCB.cpy examples/real-world/DEPTIMSM/copybooks/
cp ../legacy-application/copybook/TRNSEG.cpy examples/real-world/DEPTIMSM/copybooks/
```

(This mirrors the existing `examples/real-world/ACCTPRG/` layout exactly: the program plus only the copybooks it actually `COPY`s, no README — the `real-world/` subdirectory convention doesn't include one, unlike the simpler top-level examples such as `examples/invupdt/`.)

- [ ] **Step 2: Write `examples/real-world/DEPTIMSM/DEPTIMSM.cut`**

```
TESTSUITE "DEPTIMSM deposit MPP (IMS DL/I message processing)"

TESTCASE "1000-INITIALIZE enables the message loop"
    PERFORM 1000-INITIALIZE
    EXPECT WS-NO-MORE-MSGS TO BE "N"

TESTCASE "2100-GET-MSG accepts a message when IOPCB reports success"
    MOCK CALL "CBLTDLI"
        MOVE SPACES TO IOPCB-STATUS
    END-MOCK
    PERFORM 2100-GET-MSG
    EXPECT WS-NO-MORE-MSGS TO BE "N"

TESTCASE "2100-GET-MSG signals end-of-queue on IOPCB QC status"
    MOCK CALL "CBLTDLI"
        MOVE "QC" TO IOPCB-STATUS
    END-MOCK
    PERFORM 2100-GET-MSG
    EXPECT WS-NO-MORE-MSGS TO BE "Y"

TESTCASE "2100-GET-MSG treats an unexpected IOPCB status as end-of-queue"
    MOCK CALL "CBLTDLI"
        MOVE "AB" TO IOPCB-STATUS
    END-MOCK
    PERFORM 2100-GET-MSG
    EXPECT WS-NO-MORE-MSGS TO BE "Y"

TESTCASE "2200-VALIDATE-INPUT rejects a blank CIF number"
    MOVE SPACES TO MSG-CIF-NUMBER
    PERFORM 2200-VALIDATE-INPUT
    EXPECT REPLY-RC TO BE "08"
    EXPECT REPLY-TEXT TO BE "CIF NUMBER REQUIRED"
    EXPECT WS-TRAN-ERROR TO BE "Y"
    EXPECT WS-INVALID-INPUT TO BE 1

TESTCASE "2200-VALIDATE-INPUT rejects an invalid transaction type"
    MOVE "1234567890" TO MSG-CIF-NUMBER
    MOVE "XX" TO MSG-TRAN-TYPE
    PERFORM 2200-VALIDATE-INPUT
    EXPECT REPLY-RC TO BE "08"
    EXPECT REPLY-TEXT TO BE "TRAN TYPE MUST BE DP OR WD"

TESTCASE "2200-VALIDATE-INPUT rejects a non-numeric amount"
    MOVE "1234567890" TO MSG-CIF-NUMBER
    MOVE "DP" TO MSG-TRAN-TYPE
    MOVE "NOTANUMBER" TO MSG-AMOUNT-CHAR
    PERFORM 2200-VALIDATE-INPUT
    EXPECT REPLY-RC TO BE "08"
    EXPECT REPLY-TEXT TO BE "AMOUNT IS NOT NUMERIC"

TESTCASE "2200-VALIDATE-INPUT rejects a non-positive amount"
    MOVE "1234567890" TO MSG-CIF-NUMBER
    MOVE "DP" TO MSG-TRAN-TYPE
    MOVE "0" TO MSG-AMOUNT-CHAR
    PERFORM 2200-VALIDATE-INPUT
    EXPECT REPLY-RC TO BE "08"
    EXPECT REPLY-TEXT TO BE "AMOUNT MUST BE GREATER THAN ZERO"

TESTCASE "2200-VALIDATE-INPUT accepts a valid deposit"
    MOVE "1234567890" TO MSG-CIF-NUMBER
    MOVE "DP" TO MSG-TRAN-TYPE
    MOVE "150.00" TO MSG-AMOUNT-CHAR
    PERFORM 2200-VALIDATE-INPUT
    EXPECT WS-TRAN-ERROR TO BE "N"

TESTCASE "2300-GET-CUSTOMER succeeds when CUSTDB reports success"
    MOVE "1234567890" TO MSG-CIF-NUMBER
    MOCK CALL "CBLTDLI"
        MOVE SPACES TO CUST-STATUS
    END-MOCK
    PERFORM 2300-GET-CUSTOMER
    EXPECT WS-TRAN-ERROR TO BE "N"

TESTCASE "2300-GET-CUSTOMER flags an error when customer is not found"
    MOVE "1234567890" TO MSG-CIF-NUMBER
    MOCK CALL "CBLTDLI"
        MOVE "GE" TO CUST-STATUS
    END-MOCK
    PERFORM 2300-GET-CUSTOMER
    EXPECT REPLY-RC TO BE "04"
    EXPECT WS-TRAN-ERROR TO BE "Y"
    EXPECT WS-CUST-NOT-FOUND TO BE 1

TESTCASE "2300-GET-CUSTOMER flags a database error on an unexpected CUSTDB status"
    MOVE "1234567890" TO MSG-CIF-NUMBER
    MOCK CALL "CBLTDLI"
        MOVE "AB" TO CUST-STATUS
    END-MOCK
    PERFORM 2300-GET-CUSTOMER
    EXPECT REPLY-RC TO BE "12"
    EXPECT WS-DB-ERRORS TO BE 1

TESTCASE "2400-INSERT-TRNSEG posts a deposit when CUSTDB accepts the insert"
    MOVE "1234567890" TO MSG-CIF-NUMBER
    MOVE "123456789012" TO MSG-ACCT-NUMBER
    MOVE "DP" TO MSG-TRAN-TYPE
    MOCK CALL "CBLTDLI"
        MOVE SPACES TO CUST-STATUS
    END-MOCK
    PERFORM 2400-INSERT-TRNSEG
    EXPECT REPLY-RC TO BE "00"
    EXPECT WS-TRNS-INSERTED TO BE 1

TESTCASE "2400-INSERT-TRNSEG flags a database error when CUSTDB rejects the insert"
    MOVE "1234567890" TO MSG-CIF-NUMBER
    MOCK CALL "CBLTDLI"
        MOVE "AB" TO CUST-STATUS
    END-MOCK
    PERFORM 2400-INSERT-TRNSEG
    EXPECT REPLY-RC TO BE "12"
    EXPECT WS-DB-ERRORS TO BE 1

TESTCASE "2500-SEND-REPLY completes when IOPCB accepts the reply"
    MOCK CALL "CBLTDLI"
        MOVE SPACES TO IOPCB-STATUS
    END-MOCK
    PERFORM 2500-SEND-REPLY
    VERIFY CALL "CBLTDLI" WAS CALLED ONCE

TESTCASE "2500-SEND-REPLY reports an error when IOPCB rejects the reply"
    MOCK CALL "CBLTDLI"
        MOVE "AB" TO IOPCB-STATUS
    END-MOCK
    PERFORM 2500-SEND-REPLY
    VERIFY CALL "CBLTDLI" WAS CALLED ONCE

TESTCASE "3000-FINALIZE reports final counters"
    MOVE 5 TO WS-RECS-READ
    MOVE 3 TO WS-TRNS-INSERTED
    PERFORM 3000-FINALIZE
    EXPECT WS-RECS-READ TO BE 5

TESTCASE "2000-PROCESS-MESSAGES does nothing further once the queue is empty"
    MOCK CALL "CBLTDLI"
        MOVE "QC" TO IOPCB-STATUS
    END-MOCK
    PERFORM 2000-PROCESS-MESSAGES
    EXPECT WS-RECS-READ TO BE 0
    VERIFY CALL "CBLTDLI" WAS CALLED ONCE

TESTCASE "2000-PROCESS-MESSAGES processes one full deposit end-to-end"
    MOCK CALL "CBLTDLI"
        EVALUATE UT-CBLTDLI-TALLY
            WHEN 1
                MOVE SPACES TO IOPCB-STATUS
                MOVE "1234567890" TO MSG-CIF-NUMBER
                MOVE "123456789012" TO MSG-ACCT-NUMBER
                MOVE "150.00" TO MSG-AMOUNT-CHAR
                MOVE "DP" TO MSG-TRAN-TYPE
            WHEN 2
                MOVE SPACES TO CUST-STATUS
            WHEN 3
                MOVE SPACES TO CUST-STATUS
            WHEN 4
                MOVE SPACES TO IOPCB-STATUS
        END-EVALUATE
    END-MOCK
    PERFORM 2000-PROCESS-MESSAGES
    EXPECT REPLY-RC TO BE "00"
    EXPECT WS-RECS-READ TO BE 1
    EXPECT WS-TRNS-INSERTED TO BE 1
    VERIFY CALL "CBLTDLI" WAS CALLED 4 TIMES

TESTCASE "0000-MAIN-PROCESS runs one deposit end-to-end via its real entry point"
    MOCK CALL "CBLTDLI"
        EVALUATE UT-CBLTDLI-TALLY
            WHEN 1
                MOVE SPACES TO IOPCB-STATUS
                MOVE "1234567890" TO MSG-CIF-NUMBER
                MOVE "123456789012" TO MSG-ACCT-NUMBER
                MOVE "150.00" TO MSG-AMOUNT-CHAR
                MOVE "DP" TO MSG-TRAN-TYPE
            WHEN 2
                MOVE SPACES TO CUST-STATUS
            WHEN 3
                MOVE SPACES TO CUST-STATUS
            WHEN 4
                MOVE SPACES TO IOPCB-STATUS
            WHEN 5
                MOVE "QC" TO IOPCB-STATUS
        END-EVALUATE
    END-MOCK
    PERFORM 0000-MAIN-PROCESS
    EXPECT WS-RECS-READ TO BE 1
    EXPECT WS-TRNS-INSERTED TO BE 1
    EXPECT WS-NO-MORE-MSGS TO BE "Y"
    VERIFY CALL "CBLTDLI" WAS CALLED 5 TIMES
```

- [ ] **Step 3: Write the integration test**

Create `tests/integration/test_realworld_deptimsm_example.py`:

```python
"""End-to-end proof for the new DEPTIMSM (IMS MPP deposit transaction)
example, and the first real-world proof of the --coverage feature
(docs/2026-07-17-coverage-reporting-design.md). Like ACCTPRG, this
program uses a named ENTRY 'DLITCBL' bound to a LINKAGE SECTION mockymock's
PERFORM-only driver neutralizes into WORKING-STORAGE.

The coverage percentage/line counts below were verified empirically
against real GnuCOBOL in Docker while writing this test's own suite (not
guessed): 20/20 cases pass, and gcov reports exactly 692/907 executable
lines covered (76.30%). See the design doc's addendum for why this
number is expected to be well below 100% even though every real branch in
the program is exercised (driver harness dead-fail branches, and the
splicer's per-boundary-site mock dispatch emitting one WHEN clause per
test case that shares a mock key, most of which are structurally
unreachable from any single case's own PERFORM target)."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = (
    Path(__file__).parent.parent.parent / "examples" / "real-world" / "DEPTIMSM"
)


@requires_docker
def test_committed_deptimsm_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "DEPTIMSM.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "DEPTIMSM.cut"),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_committed_deptimsm_example_reports_coverage(capsys):
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "DEPTIMSM.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "DEPTIMSM.cut"),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
            "--coverage",
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "coverage: 76.30% lines executed (692/907)" in out
```

- [ ] **Step 4: Run the new integration tests**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_realworld_deptimsm_example.py -v`
Expected: PASS, both tests (requires the Docker daemon reachable and `mockymock setup` already run once, same as every other `tests/integration/` test — if Docker isn't reachable in the current environment both tests SKIP rather than fail).

- [ ] **Step 5: Run the full test suite (unit + integration) once more**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: PASS, 0 failures (Docker-gated tests either pass or skip depending on daemon availability, never fail).

- [ ] **Step 6: Commit**

```bash
git add examples/real-world/DEPTIMSM tests/integration/test_realworld_deptimsm_example.py
git commit -m "feat(coverage): add DEPTIMSM example, proven end-to-end with --coverage"
```

---

### Task 6: Prove `--coverage` composes with the existing, unmodified `ACCTPRG` suite

**Files:**
- Modify: `tests/integration/test_realworld_acctprg_example.py` (add one new test; no changes to `ACCTPRG.cbl`/`ACCTPRG.cut` themselves)

**Interfaces:**
- Consumes: the finished `--coverage` flag from Task 4.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the test**

Append to `tests/integration/test_realworld_acctprg_example.py` (after the existing two tests, before/after doesn't matter since they're independent):

```python
@requires_docker
def test_committed_acctprg_example_reports_coverage(capsys):
    """--coverage composing with a suite nobody wrote with coverage in
    mind (ACCTPRG's suite predates this feature entirely) -- not a suite
    change, a sanity check that the tool works against pre-existing
    suites, not only purpose-built ones. Verified empirically while
    writing this test: gcov reports exactly 459/561 executable lines
    covered (81.82%), unchanged by anything in this task."""
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "ACCTPRG.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "ACCTPRG.cut"),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
            "--coverage",
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "coverage: 81.82% lines executed (459/561)" in out
```

- [ ] **Step 2: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_realworld_acctprg_example.py -v`
Expected: PASS, all three tests in the file (the two pre-existing ones plus this new one).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_realworld_acctprg_example.py
git commit -m "test(coverage): prove --coverage composes with the existing ACCTPRG suite"
```

---

### Task 7: Documentation — README, OKF bundle, corpus-sweep report cross-link

**Files:**
- Modify: `README.md` (repo root)
- Create: `.okf/coverage.md` (new OKF concept)
- Modify: `.okf/index.md`, `.okf/cli.md`, `.okf/runtime.md`, `.okf/report.md` (one-line "See Also" additions each)
- Modify: `.okf/log.md` (new dated entry at the top)

**Interfaces:** None — documentation only, no code.

- [ ] **Step 1: Add a "Coverage reporting" section to `README.md`**

Insert into `README.md`, after the existing "### `STOP RUN` / `GOBACK` inside a test case's PERFORM target" section (currently ends at line 146) and before "## Install" (currently line 148):

```markdown
## Coverage reporting

`mockymock run --coverage` compiles with GnuCOBOL's own `--coverage`
flag (GnuCOBOL transpiles COBOL to C, so this builds on gcc's gcov) and,
after the run, reports the percentage of lines executed plus the exact
uncovered lines:

```
mockymock run: coverage: 76.30% lines executed (692/907) in DEPTIMSM.cbl
mockymock run: coverage: uncovered lines:
  751:               EXIT PARAGRAPH
  ...
```

`--coverage-out PATH` additionally writes the full report to a file.
Coverage is purely additive: it never changes the pass/fail exit code.

Two things to know before reading a number:

- **Line numbers are against the *instrumented* source** (after mock-body
  splicing and the generated test-driver code), not the original `.cbl` —
  the same file `--verbose`/`--keep-sandbox` already expose. Remapping to
  original line numbers is a known, not-yet-built follow-up.
- **A suite that exercises every real branch still won't read near
  100%.** Two structural sources of "uncovered" lines are expected, not a
  sign of a weak suite: the driver's own `FAIL`/tally-increment lines
  (dead whenever every check passes), and — the larger one — the splicer
  emitting one shared dispatch per boundary site with a `WHEN` branch for
  *every* test case that mocks that key, not only cases whose `PERFORM`
  target reaches that exact site. See
  `docs/2026-07-17-coverage-reporting-design.md` for the full writeup and
  a worked example.
```

- [ ] **Step 2: Create `.okf/coverage.md`**

```markdown
---
type: Module
title: Coverage Reporting
description: GnuCOBOL --coverage/gcov instrumentation wired into `mockymock run`, reporting per-line coverage of the instrumented source.
tags: [coverage, gcov, cli, runtime]
timestamp: 2026-07-17T00:00:00Z
---
# Overview

`mockymock run --coverage` proves which lines of the *instrumented*
COBOL source actually ran during a suite. It adds no new instrumentation
engine — GnuCOBOL's own `cobc --coverage` flag builds on gcc's gcov
machinery (`cobc` transpiles COBOL to C), and `-fgen-c-line-directives`
(auto-enabled by `--coverage`) keeps gcov's line attribution pointed at
the real COBOL source lines rather than the generated C.

```
runtime/docker_toolchain.py
  compile_source(path, coverage=True)  -- adds --coverage to the cobc invocation
  run_binary(binary)                    -- unchanged; writes <name>.gcda on normal exit
  run_gcov(path)                        -- docker exec ... gcov <name>.gcda, reads back <name>.cbl.gcov

report/coverage.py
  parse_gcov(gcov_text) -> CoverageReport   -- per-line hit counts -> totals + uncovered lines
  format_coverage_console(report, name)     -- console rendering, same style as report/formatters.py

cli/main.py: _cmd_run
  --coverage / --coverage-out wiring; printed/written after run_binary succeeds,
  before the sandbox is cleaned up (the .gcda/.gcov files live in the same tmp dir)
```

# Data Model

```python
@dataclass
class UncoveredLine:
    line_number: int
    text: str

@dataclass
class CoverageReport:
    total_executable: int
    total_covered: int
    uncovered_lines: list[UncoveredLine]

    @property
    def percentage(self) -> float: ...  # 100.0 when total_executable == 0
```

# Gotchas

**Coverage is against the instrumented source, not the original `.cbl`
(v1, deliberate scope boundary).** Mock-body splicing and the generated
test-driver code shift every line number after the `WORKING-STORAGE
SECTION`/`PROCEDURE DIVISION` insertion points, and boundary splicing can
replace one line with a multi-line mock body anywhere in the file.
Remapping back to original line numbers needs a line-provenance map
threaded through the whole splicer (`orchestrator.py`, `driver.py`,
`linkage.py`, `sqlca.py`) — named as a v2 follow-up in
`docs/2026-07-17-coverage-reporting-design.md`, not built.

**A fully-branch-covering suite still won't read near 100% (structural,
not a suite-authoring gap).** The splicer emits one shared `EVALUATE
UT-CURRENT-CASE` dispatch per boundary site with a `WHEN "<case-id>"`
branch for *every* test case in the suite that mocks the same key — not
only cases whose `PERFORM` target reaches that exact site. Those other
cases' branches are structurally dead there. Confirmed on `DEPTIMSM`'s
20-case suite (every real branch, including the full `0000-MAIN-PROCESS`
entry point, exercised): still 76.30% (692/907), the rest being this
cross product, the driver's own dead `FAIL` branches, and the terminator-
neutralization transform's defensive `IF UT-EARLY-EXIT = "Y" EXIT
PARAGRAPH END-IF` guards (dead whenever the guarded paragraph has no
nested terminator of its own). Don't read a number well under 100% as a
weak suite without checking which of these it is.

**`.gcda` is only written on normal process exit.** A binary killed by
`run_binary`'s timeout `SIGKILL` never reaches the C runtime's coverage-
dump `atexit` handler, so `run_gcov` checks for the file up front and
returns a clean "no coverage data produced" result instead of a confusing
gcov error about a missing file.

**`docker exec -w <path>` needs a real absolute *container* path, and
works fine via `subprocess.run` (see `runtime.md`'s existing note on
`run_binary`'s use of the same flag) — an ad hoc `docker exec -w
/work/...` typed directly at a Git Bash prompt fails with "Cwd must be an
absolute path" due to Git Bash's own MSYS argument path-mangling, not a
real Docker limitation. Don't mistake that shell artifact for a reason to
avoid `-w` in the actual Python implementation.

# See Also

- [runtime](runtime.md) — the Docker toolchain `compile_source`/`run_gcov` extend
- [report](report.md) — `report/coverage.py` follows the same Docker-free
  parsing/formatting split as `report/results.py`/`report/formatters.py`
- [cli](cli.md) — `run`'s `--coverage`/`--coverage-out` flags
```

- [ ] **Step 3: Add "See Also" links from the three related concepts**

In `.okf/cli.md`'s "See Also" section (currently at the very end of the file), add a line so it reads:

```markdown
# See Also

- [runtime](runtime.md)
- [report](report.md)
- [dsl](dsl.md)
- [coverage](coverage.md)
```

In `.okf/runtime.md`'s "See Also" section (currently at the very end), add a line so it reads:

```markdown
# See Also

- [splicer](splicer.md) — produces the instrumented `.cbl` source that gets
  written into the Docker sandbox and compiled.
- [cli](cli.md) — `setup`/`run` command wiring that drives `ensure_toolchain`,
  `compile_source`, and `run_binary`.
- [coverage](coverage.md) — `compile_source(..., coverage=True)` and `run_gcov`
  build on this module's existing Docker toolchain.
```

In `.okf/report.md`'s "See Also" section (currently at the very end), add a line so it reads:

```markdown
# See Also

- [cli](cli.md)
- [dsl](dsl.md)
- [coverage](coverage.md) — a separate, Docker-free parsing/formatting module
  following this one's design (gcov text in, a report model, a console formatter).
```

- [ ] **Step 4: Add `coverage.md` to `.okf/index.md`**

In `.okf/index.md`'s "## Integration & Testing" section (currently lines 24-27), add a line so it reads:

```markdown
## Integration & Testing

* [Integration Contract](integration.md) — the cobolparser AST surface mockymock depends on (distills the repo-root [interface-contract.md](../interface-contract.md))
* [Testing](testing.md) — unit/integration split, Docker-availability skip gate, `tests/integration/fixtures/` corpus, and the two worked examples (INVUPDT, ORDRPROC)
* [Coverage](coverage.md) — `mockymock run --coverage`: GnuCOBOL/gcov-based per-line coverage reporting
```

- [ ] **Step 5: Append a dated entry to `.okf/log.md`**

Insert at the very top of `.okf/log.md`, immediately after its `# mocky-mock OKF Bundle — Update Log` header and before the existing `## 2026-07-17 (corpus re-sweep ...)` entry:

```markdown
## 2026-07-17 (coverage reporting: --coverage/--coverage-out, DEPTIMSM example)

* **New feature**: `mockymock run --coverage` compiles with GnuCOBOL's
  native `--coverage` flag (builds on gcc's gcov, since `cobc` transpiles
  COBOL to C) and reports per-line coverage of the instrumented source
  after the run; `--coverage-out PATH` writes the full report to a file.
  New `runtime/docker_toolchain.py` `run_gcov` + `GcovResult`; new
  `report/coverage.py` (`parse_gcov`/`format_coverage_console`); no new
  Dockerfile/dependency changes (`gcc`/`gcov` already present in the
  `mockymock-cobc` image). See `docs/2026-07-17-coverage-reporting-design.md`
  and the new [coverage](coverage.md) OKF concept.
* **New example**: `examples/real-world/DEPTIMSM/` (IMS MPP deposit
  transaction, IMS DL/I via `CALL 'CBLTDLI'`) — 20 test cases including
  one driving the real `0000-MAIN-PROCESS` entry point to `GOBACK`
  end-to-end, proven against real GnuCOBOL in Docker. First real-world
  proof this repo's 17-program `legacy-application/cobol/` corpus can go
  beyond `mockymock generate`'s parse-only sweep to an actual
  compile-and-run — 3 of 17 corpus programs (`ACCTPRG`, `DEPTMQP`,
  `DEPTMQC`, now `DEPTIMSM`) are proven end-to-end; the remaining 13 are
  explicit, named follow-up work, not attempted here.
* **Coverage numbers are lower than "every branch exercised" would
  suggest, and that's expected**: `DEPTIMSM`'s 20-case suite hits every
  real branch (verified by hand while writing it) yet reports 76.30%
  (692/907) — see the design doc's addendum and the new `coverage.md`
  concept for why (driver dead-fail branches, terminator-neutralization
  guard branches, and — the largest source — the splicer's per-boundary-
  site mock dispatch emitting one `WHEN` branch per test case sharing a
  mock key, most structurally unreachable from any single case's own
  `PERFORM` target). `ACCTPRG`'s existing, unmodified suite reports
  81.82% (459/561) under the same feature, proving it composes with a
  suite written years before coverage reporting existed.

```

- [ ] **Step 6: Validate the OKF bundle**

Run: `/okf:validate .okf --strict`
Expected: no new errors (only whatever pre-existing warning classes already applied before this task, per the project's established convention — check the tool's output against a baseline run on `main` if any warnings appear, to confirm they aren't new).

- [ ] **Step 7: Commit**

```bash
git add README.md .okf/coverage.md .okf/index.md .okf/cli.md .okf/runtime.md .okf/report.md .okf/log.md
git commit -m "docs(coverage): README + OKF concept for coverage reporting"
```

---

## Plan Self-Review Notes (for the implementer's awareness, not a task)

- **Spec coverage**: every decision in `docs/2026-07-17-coverage-reporting-design.md` (mechanism, v1 instrumented-line scope, output format, error handling, the two DEPTIMSM/ACCTPRG proofs) maps to a task above. The design doc's two addenda (the `-w` MSYS false alarm, and the per-site mock-dispatch structural finding) are folded into Task 2's implementation and Task 7's documentation respectively.
- **Explicitly out of scope, do not attempt as part of this plan** (already named in the design doc): remapping to original `.cbl` line numbers; raising coverage across the other 13 not-yet-proven corpus programs; a coverage threshold/gate; lcov/gcovr/HTML report generation.
- **Pinned numbers are real, not estimates**: 692/907 (76.30%) for `DEPTIMSM` and 459/561 (81.82%) for `ACCTPRG` were both measured by actually compiling the real instrumented source with `cobc --coverage` and running `gcov` in the real `mockymock-cobc` container while this plan was being written — if Task 4's implementation produces a different number for either, that's a signal something in Task 1/2/4's implementation doesn't match what was verified, not a reason to just update the pinned value without understanding why first.
