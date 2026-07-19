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
entry point, exercised): still 75.90% (693/913), the rest being this
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
