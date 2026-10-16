"""Parser and formatter for GnuCOBOL/gcov's per-line COBOL coverage
output.

`cobc --coverage` (see runtime/docker_toolchain.py's `compile_source`)
builds on gcc's own gcov machinery, since GnuCOBOL transpiles COBOL to C.
Running `gcov <program>.gcda` (runtime/docker_toolchain.py's `run_gcov`)
after executing the compiled binary produces a `<program>.cbl.gcov` file
with one line per source line, in the format
`<count-or-dash-or-hashes>:<line-number>:<source text>`:

- `-` means the line is not executable (declarations, comments, blanks).
- `#####` means the line is executable but was never hit; `=====` is the
  same for a line reachable only along an exceptional path.
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

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class UncoveredLine:
    line_number: int
    text: str


@dataclass
class CoverageReport:
    total_executable: int
    total_covered: int
    uncovered_lines: list[UncoveredLine] = field(default_factory=list)
    covered_lines: list[int] = field(default_factory=list)
    """Instrumented-source line numbers with a nonzero hit count, in file
    order -- the complement of `uncovered_lines` within the executable set.
    Needed by the original-source remapping and the JSON formatter; the
    console formatter only ever reports the uncovered side."""

    @property
    def percentage(self) -> float:
        if self.total_executable == 0:
            return 100.0
        return 100.0 * self.total_covered / self.total_executable


def parse_gcov(gcov_text: str) -> CoverageReport:
    total_executable = 0
    total_covered = 0
    uncovered: list[UncoveredLine] = []
    covered: list[int] = []
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
        if count_field in ("#####", "====="):
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
            covered.append(line_number)
        else:
            uncovered.append(UncoveredLine(line_number=line_number, text=text))
    return CoverageReport(
        total_executable=total_executable,
        total_covered=total_covered,
        uncovered_lines=uncovered,
        covered_lines=covered,
    )


@dataclass
class MappedLineCoverage:
    """Coverage for one line of the ORIGINAL .cbl file (1-based)."""

    line: int
    covered: bool


@dataclass
class OriginalCoverage:
    """The original-.cbl view of one run's coverage: the numbers a human
    should actually read.

    `CoverageReport` measures the INSTRUMENTED sandbox copy, which counts
    the splicer's own injected dispatch/driver lines as program lines and
    so reports a number that is inflated (and, worse, moves when the
    harness changes rather than when the program's tested surface does).
    This view drops every line that has no counterpart in the user's own
    file, so `percentage` answers the question people think `--coverage`
    is answering: how much of MY program ran."""

    total_executable: int
    total_covered: int
    uncovered_lines: list[UncoveredLine] = field(default_factory=list)

    @property
    def percentage(self) -> float:
        if self.total_executable == 0:
            return 100.0
        return 100.0 * self.total_covered / self.total_executable


def summarize_original(
    mapped: list[MappedLineCoverage], original_lines: list[str]
) -> OriginalCoverage:
    """Reduce `map_coverage_to_original`'s per-line view to the totals plus
    the uncovered lines, each carrying its own ORIGINAL source text (cut to
    the fixed-format program area, columns 8-72, with trailing blanks
    removed) so the console report can name uncovered lines the way the
    reader's own editor would show them. Leading blanks are deliberately
    KEPT: Area A / Area B indentation is what tells a paragraph header from
    a statement inside it at a glance, and stripping it would flatten every
    uncovered line to the same margin. A `line` past the end of `original_lines` cannot happen
    (every mapped line came from that same list) but renders as empty text
    rather than raising if it ever does."""
    uncovered = [
        UncoveredLine(
            line_number=entry.line,
            text=(
                original_lines[entry.line - 1][7:72].rstrip()
                if 0 < entry.line <= len(original_lines)
                else ""
            ),
        )
        for entry in mapped
        if not entry.covered
    ]
    return OriginalCoverage(
        total_executable=len(mapped),
        total_covered=sum(1 for entry in mapped if entry.covered),
        uncovered_lines=uncovered,
    )


def _matching_index_map(a: list[str], b: list[str]) -> dict[int, int]:
    """0-based index map b -> a over the lines the two sequences share, via
    difflib's matching blocks. Unlike a greedy forward scan, this never lets
    an inserted line (driver code, mock dispatch) that happens to equal a
    LATER source line (an `END-IF`, say) steal the match and orphan
    everything in between -- SequenceMatcher optimizes for the longest
    contiguous runs, and instrumentation insertions sit between long
    verbatim runs of the source they were spliced into."""
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    mapping: dict[int, int] = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            mapping[block.b + offset] = block.a + offset
    return mapping


def _extract_fixed_format(original_lines: list[str]) -> list[tuple[int, str]]:
    """(1-based original line number, columns 8-72 content) for every
    non-comment line, mirroring what `normalize_fixed_format` extracts so
    the two sides align on equal strings. Comment lines (`*`/`/` in column
    7) are dropped exactly as the normalizer drops them; continuation
    merges are NOT replicated -- a merged line simply won't find an equal
    partner and stays unmapped, which fails safe (that line just carries no
    coverage) rather than mismapping."""
    extracted: list[tuple[int, str]] = []
    for line_no, raw in enumerate(original_lines, start=1):
        indicator = raw[6] if len(raw) > 6 else " "
        if indicator in ("*", "/"):
            continue
        extracted.append((line_no, raw[7:72].rstrip()))
    return extracted


def build_original_line_map(
    instrumented_lines: list[str],
    normalized_lines: list[str],
    original_lines: list[str],
) -> dict[int, int]:
    """1-based instrumented line -> 1-based ORIGINAL .cbl line.

    Composes the same two alignments `map_coverage_to_original` uses:
    instrumented -> normalized (the splicer inserts lines but keeps
    untouched source verbatim and in order), then normalized -> original
    (fixed-format extraction drops comments/sequence columns). Instrumented
    lines with no original counterpart -- the splicer's own dispatch and
    driver code -- are simply absent from the result.

    Shared with the execution-trace report, whose trace-file line numbers
    are instrumented lines needing exactly this remap; see
    docs/2026-07-21-debug-trace-design.md.
    """
    normalized_stripped = [line.rstrip() for line in normalized_lines]
    instrumented_stripped = [line.rstrip() for line in instrumented_lines]
    inst_to_norm = _matching_index_map(normalized_stripped, instrumented_stripped)

    # A statement the splicer replaced (a mocked boundary, a neutralized
    # GOBACK / STOP RUN) stays in the instrumented source commented out,
    # `stub_writer.comment_and_replace`'s prefix before its own text, with
    # the replacement right after it. Align those commented copies too, so
    # the statement keeps its place (issue #297: they dropped out of the
    # executable set, and an untaken CALL-only branch read 100%).
    commented: set[int] = set()
    if any(line.startswith(_COMMENTED_PREFIX) for line in instrumented_stripped):
        aligned = list(instrumented_stripped)
        for index, line in enumerate(instrumented_stripped):
            if index not in inst_to_norm and line.startswith(_COMMENTED_PREFIX):
                aligned[index] = line[len(_COMMENTED_PREFIX) :]
                commented.add(index)
        inst_to_norm = _matching_index_map(normalized_stripped, aligned)
        commented &= set(inst_to_norm)

    extracted = _extract_fixed_format(original_lines)
    norm_to_orig = _matching_index_map(
        [content for _, content in extracted], normalized_stripped
    )

    mapping: dict[int, int] = {}
    for inst_index, norm_index in inst_to_norm.items():
        extracted_index = norm_to_orig.get(norm_index)
        if extracted_index is not None:
            mapping[inst_index + 1] = extracted[extracted_index][0]

    # The replacement block after a commented span stands for the span's
    # first line: the statement counts as executed exactly when its
    # replacement ran.
    for index in sorted(commented):
        if index - 1 in commented or index + 1 not in mapping:
            continue  # not the first line of its span, or unmapped
        original = mapping[index + 1]
        follower = index + 1
        while follower in commented:
            follower += 1
        while (
            follower < len(instrumented_stripped)
            and follower not in inst_to_norm
            # A replacement is indented statements; a line starting in
            # column 1 is a paragraph header the splicer added after it.
            and not instrumented_stripped[follower][:1].strip()
        ):
            mapping[follower + 1] = original
            follower += 1
    return mapping


def build_copybook_line_map(
    instrumented_lines: list[str],
    normalized_lines: list[str],
    source_location_map: dict[int, tuple[str, int]] | None,
) -> dict[int, tuple[str, int]]:
    """1-based instrumented line -> (copybook file name, line in it), for
    the lines a COPY brought in. `build_original_line_map` drops them --
    they have no counterpart in the `.cbl` -- so a paragraph living in a
    procedure copybook vanished from `run --trace` (issue #242).
    `source_location_map` is the expansion's own (expanded line, the
    normalized text's numbering -> file, line), `"<main>"` entries being
    the program's lines, which this leaves to `build_original_line_map`."""
    if not source_location_map:
        return {}
    inst_to_norm = _matching_index_map(
        [line.rstrip() for line in normalized_lines],
        [line.rstrip() for line in instrumented_lines],
    )
    mapping: dict[int, tuple[str, int]] = {}
    for inst_index, norm_index in inst_to_norm.items():
        origin = source_location_map.get(norm_index + 1)
        if origin is not None and origin[0] != "<main>":
            mapping[inst_index + 1] = (Path(origin[0]).name, origin[1])
    return mapping


#: The prefix `splicer.stub_writer.comment_and_replace` puts before each
#: line of a statement span it replaces.
_COMMENTED_PREFIX = "      *> "


def map_coverage_to_original(
    report: CoverageReport,
    instrumented_lines: list[str],
    normalized_lines: list[str],
    original_lines: list[str],
) -> list[MappedLineCoverage]:
    """Remap instrumented-source coverage onto original .cbl line numbers.

    Two alignments compose: instrumented -> normalized (the splicer inserts
    dispatch/driver lines but keeps untouched source lines verbatim and in
    order), then normalized -> original (fixed-format extraction drops
    comments/sequence columns but keeps content). Lines with no mapping --
    the splicer's own instrumentation, mock-dispatch replacements of
    original boundary lines, continuation merges -- are excluded, so the
    result covers exactly the user's own executable lines. That exclusion
    is the point: v1 deliberately reported against the instrumented source
    (see module docstring); this view answers "which of MY lines ran"."""
    line_map = build_original_line_map(
        instrumented_lines, normalized_lines, original_lines
    )

    def to_original(instrumented_line: int) -> int | None:
        return line_map.get(instrumented_line)

    mapped: dict[int, bool] = {}
    for line_number in report.covered_lines:
        original = to_original(line_number)
        if original is not None:
            mapped[original] = True
    for uncovered in report.uncovered_lines:
        original = to_original(uncovered.line_number)
        if original is not None:
            # A covered verdict wins if both ever map to one original line
            # (can only happen via a continuation merge that slipped both
            # halves through): claiming "uncovered" for executed code is
            # the misleading direction.
            mapped.setdefault(original, False)
    return [
        MappedLineCoverage(line=line, covered=covered)
        for line, covered in sorted(mapped.items())
    ]


COVERAGE_JSON_VERSION = 1


def format_coverage_json(
    report: CoverageReport,
    mapped: list[MappedLineCoverage],
    program_file: str,
    instrumented_name: str,
) -> str:
    """Machine-readable coverage for editor integrations: the instrumented
    totals plus the per-line original-file view produced by
    `map_coverage_to_original`, each with its own percentage so a consumer
    never has to recompute one (or pick the wrong one -- `original` is the
    meaningful figure, `instrumented` counts mockymock's injected lines).
    `original.percentage` was added alongside the console report leading
    with the same number; it is an additive key, so a v1 consumer that
    ignores it still reads this file correctly."""
    mapped_covered = sum(1 for entry in mapped if entry.covered)
    payload = {
        "version": COVERAGE_JSON_VERSION,
        "programFile": program_file,
        "instrumented": {
            "sourceName": instrumented_name,
            "percentage": round(report.percentage, 2),
            "totalExecutable": report.total_executable,
            "totalCovered": report.total_covered,
        },
        "original": {
            "percentage": round(
                100.0 * mapped_covered / len(mapped) if mapped else 100.0, 2
            ),
            "totalExecutable": len(mapped),
            "totalCovered": mapped_covered,
            "lines": [
                {"line": entry.line, "covered": entry.covered} for entry in mapped
            ],
        },
    }
    return json.dumps(payload, indent=2) + "\n"


def format_coverage_console(
    report: CoverageReport,
    source_name: str,
    original: OriginalCoverage | None = None,
    program_name: str | None = None,
) -> str:
    """The human-readable coverage report.

    When `original` is supplied (which every `mockymock run --coverage`
    invocation does), the ORIGINAL .cbl's own numbers lead and its own
    uncovered lines are what get listed -- that is the number a reader can
    act on. The instrumented sandbox copy's number is still printed, once,
    on a clearly subordinate line labelled with WHY it differs: it counts
    the splicer's injected dispatch/driver lines as program lines (which
    can push it either way -- the label names the actual direction). Leading
    with the instrumented number (v1's behavior, kept as the `original is
    None` fallback for callers that have no remap available) meant the more
    prominent of the two figures was the less meaningful one.

    `program_name` names the original file; it falls back to a generic
    label so this function never has to be called with a path it does not
    have."""
    if original is None:
        lines = [
            f"mockymock run: coverage: {report.percentage:.2f}% lines executed "
            f"({report.total_covered}/{report.total_executable}) in {source_name}"
        ]
        if report.uncovered_lines:
            lines.append("mockymock run: coverage: uncovered lines:")
            for uncovered in report.uncovered_lines:
                lines.append(f"  {uncovered.line_number}: {uncovered.text}")
        return "\n".join(lines)

    shown_program = program_name or "the original program"
    lines = [
        f"mockymock run: coverage: {original.percentage:.2f}% of "
        f"{shown_program}'s own lines executed "
        f"({original.total_covered}/{original.total_executable})"
    ]
    if original.uncovered_lines:
        lines.append(f"mockymock run: coverage: uncovered lines in {shown_program}:")
        for uncovered in original.uncovered_lines:
            lines.append(f"  {uncovered.line_number}: {uncovered.text}")
    # The injected lines can pull the sandbox figure either way: driver
    # lines always run (pushing it up), but every never-taken mock
    # dispatch branch counts as uncovered (pulling it down) -- on the
    # committed ACCTPRG/DEPTIMSM examples it is the LOWER of the two. So
    # the label states the actual direction instead of assuming "higher".
    if report.percentage > original.percentage:
        direction = "higher"
    elif report.percentage < original.percentage:
        direction = "lower"
    else:
        direction = "different in composition"
    lines.append(
        f"mockymock run: coverage: (instrumented sandbox copy {source_name}: "
        f"{report.percentage:.2f}%, {report.total_covered}/"
        f"{report.total_executable} -- {direction} because it also counts "
        f"mockymock's own injected dispatch/driver lines; the figure above "
        f"is the one about your program)"
    )
    return "\n".join(lines)
