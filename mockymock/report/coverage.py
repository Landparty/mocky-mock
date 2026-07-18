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
