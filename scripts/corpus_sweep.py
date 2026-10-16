"""Corpus-sweep harness for `mockymock generate`.

Runs `mockymock generate <program.cbl>` (in-process, via
`mockymock.cli.main.main`) over every COBOL program in the corpus and tallies
the outcomes into a Markdown report: how many programs parse at all, how many
generate cleanly, which `refused (<CODE>)` codes fire, and which "boundary
point(s) detected that are not mockable" categories show up.

This is measurement only -- it does not touch engine code and does not run
Docker (`generate` is parse-and-analyze only, no compile/run). It never
writes into the repo's tracked `.cut` files: every `-o` target is a path
inside a throwaway `tempfile.TemporaryDirectory()`.

Corpus swept:
  - 17 real-world programs in ../legacy-application/cobol/*.cbl (sibling
    repo), with ../legacy-application/copybook passed as --copybook-path
    when it exists.
  - tests/integration/fixtures/*.cbl and its subdirectories (each
    subdirectory's own copybooks/ dir, if present, is used).
  - examples/**/*.cbl and examples/**/*.CBL (each program directory's own
    copybooks/ or copybook/ dir, if present, is used; the uppercase
    extension covers the NIST CCVS85 examples on case-sensitive
    filesystems).

Usage:
    python scripts/corpus_sweep.py > docs/corpus-sweep-report.md
"""

from __future__ import annotations

import contextlib
import io
import re
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_APP_ROOT = REPO_ROOT.parent / "legacy-application"

_REFUSED_RE = re.compile(r"refused \(([A-Z_]+)\):")
_PARSE_ERROR_HEADER_RE = re.compile(r"(\d+) parse error\(s\)")
_BOUNDARY_HEADER_RE = re.compile(r"(\d+) boundary point\(s\) detected")
# Boundary finding lines look like:
#   "  - CALL in paragraph 'FOO' (line 12)"
#   "  - nested SORT/MERGE in paragraph 'FOO' (line 12) -- reason text"
_BOUNDARY_LINE_RE = re.compile(r"^  - (nested )?(.+?) in paragraph '")


@dataclass
class ProgramResult:
    name: str
    path: Path
    copybook_dir: Path | None
    exit_code: int | None = None  # None if generate raised an exception
    parse_error_count: int = 0
    refusal_codes: list[str] = field(default_factory=list)
    unmockable_categories: dict[str, int] = field(default_factory=dict)
    exception_text: str | None = None
    stdout: str = ""

    @property
    def parsed_ok(self) -> bool:
        """True unless a parse error or an uncaught exception occurred."""
        if self.exception_text is not None:
            return False
        return self.parse_error_count == 0

    @property
    def generate_clean(self) -> bool:
        return self.exit_code == 0


def find_copybook_dir(program_path: Path) -> Path | None:
    """Look for a copybook directory alongside `program_path`, then fall
    back to the shared legacy-application copybook dir. Returns None if
    nothing is found (the program is still run -- it'll likely refuse
    UNRESOLVED_COPYBOOK, which is itself a valid data point)."""
    local_dir = program_path.parent
    for name in ("copybooks", "copybook"):
        candidate = local_dir / name
        if candidate.is_dir():
            return candidate

    try:
        program_path.relative_to(LEGACY_APP_ROOT)
    except ValueError:
        pass
    else:
        shared = LEGACY_APP_ROOT / "copybook"
        if shared.is_dir():
            return shared

    return None


def discover_corpus() -> list[tuple[Path, Path | None]]:
    """Return [(program_path, copybook_dir_or_None), ...] for the whole
    sweep: the 17 legacy-application programs, the integration-test
    fixtures, and the in-repo examples."""
    entries: list[tuple[Path, Path | None]] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        entries.append((path, find_copybook_dir(path)))

    legacy_cobol_dir = LEGACY_APP_ROOT / "cobol"
    if legacy_cobol_dir.is_dir():
        for cbl in sorted(legacy_cobol_dir.glob("*.cbl")):
            add(cbl)

    fixtures_dir = REPO_ROOT / "tests" / "integration" / "fixtures"
    if fixtures_dir.is_dir():
        for cbl in sorted(fixtures_dir.rglob("*.cbl")):
            add(cbl)

    # NIST CCVS85 examples use the uppercase .CBL extension; rglob is
    # case-sensitive on Linux, so both spellings are swept explicitly.
    examples_dir = REPO_ROOT / "examples"
    if examples_dir.is_dir():
        for pattern in ("*.cbl", "*.CBL"):
            for cbl in sorted(examples_dir.rglob(pattern)):
                add(cbl)

    return entries


def run_generate(
    program_path: Path, copybook_dir: Path | None, tmp_dir: Path
) -> ProgramResult:
    """Invoke `mockymock generate` in-process for one program, capturing
    stdout, and tally the signals it printed. Any exception raised inside
    generate is caught and recorded rather than allowed to abort the sweep."""
    from mockymock.cli.main import main

    result = ProgramResult(
        name=program_path.stem, path=program_path, copybook_dir=copybook_dir
    )

    output_path = tmp_dir / f"{program_path.stem}.cut"
    # Scratch output: two programs sharing a stem reuse one path.
    argv = ["generate", str(program_path), "-o", str(output_path), "--force"]
    if copybook_dir is not None:
        argv.extend(["--copybook-path", str(copybook_dir)])

    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            exit_code = main(argv)
    except Exception:  # noqa: BLE001 - a crashing program IS a finding
        result.exception_text = traceback.format_exc()
        result.stdout = buffer.getvalue()
        return result

    result.exit_code = exit_code
    stdout = buffer.getvalue()
    result.stdout = stdout
    _parse_output(result, stdout)
    return result


def _parse_output(result: ProgramResult, stdout: str) -> None:
    lines = stdout.splitlines()

    header_match = _PARSE_ERROR_HEADER_RE.search(stdout)
    if header_match:
        result.parse_error_count = int(header_match.group(1))

    for line in lines:
        refused_match = _REFUSED_RE.search(line)
        if refused_match:
            result.refusal_codes.append(refused_match.group(1))

    in_boundary_block = False
    for line in lines:
        if _BOUNDARY_HEADER_RE.search(line):
            in_boundary_block = True
            continue
        if in_boundary_block:
            if not line.startswith("  - "):
                in_boundary_block = False
                continue
            boundary_match = _BOUNDARY_LINE_RE.match(line)
            if boundary_match:
                nested_prefix, label = boundary_match.groups()
                category = f"nested {label}" if nested_prefix else label
                result.unmockable_categories[category] = (
                    result.unmockable_categories.get(category, 0) + 1
                )


def sweep() -> list[ProgramResult]:
    entries = discover_corpus()
    results: list[ProgramResult] = []
    with tempfile.TemporaryDirectory(prefix="mockymock-corpus-sweep-") as tmp:
        tmp_dir = Path(tmp)
        for program_path, copybook_dir in entries:
            results.append(run_generate(program_path, copybook_dir, tmp_dir))
    return results


def _relative_label(path: Path) -> str:
    for base in (LEGACY_APP_ROOT, REPO_ROOT):
        try:
            return str(path.relative_to(base)).replace("\\", "/")
        except ValueError:
            continue
    return str(path)


def render_report(results: list[ProgramResult]) -> str:
    lines: list[str] = []
    lines.append("# Corpus Sweep Report")
    lines.append("")
    lines.append(
        f"Swept {len(results)} COBOL program(s) with `mockymock generate` "
        "(parse-and-analyze only, no Docker/compile)."
    )
    lines.append("")
    lines.append(
        "| Program | Parsed OK? | Generate Exit | Refusal Codes | "
        "Unmockable Boundaries (by category) |"
    )
    lines.append("|---|---|---|---|---|")

    code_totals: dict[str, int] = {}
    category_totals: dict[str, int] = {}
    parsed_ok_count = 0
    clean_generate_count = 0
    exception_count = 0

    for result in results:
        program_label = _relative_label(result.path)

        if result.exception_text is not None:
            exception_count += 1
            exit_display = "**EXCEPTION**"
            parsed_display = "ERROR"
        else:
            if result.parsed_ok:
                parsed_ok_count += 1
            parsed_display = "yes" if result.parsed_ok else "no"
            exit_display = str(result.exit_code)
            if result.generate_clean:
                clean_generate_count += 1

        if result.parse_error_count:
            code_totals["PARSE_ERROR"] = code_totals.get("PARSE_ERROR", 0) + 1
        for code in result.refusal_codes:
            code_totals[code] = code_totals.get(code, 0) + 1
        for category, count in result.unmockable_categories.items():
            category_totals[category] = category_totals.get(category, 0) + count

        if result.parse_error_count:
            refusal_display_parts = [f"PARSE_ERROR x{result.parse_error_count}"]
        else:
            refusal_display_parts = []
        if result.refusal_codes:
            code_counts: dict[str, int] = {}
            for code in result.refusal_codes:
                code_counts[code] = code_counts.get(code, 0) + 1
            refusal_display_parts.extend(
                f"{code} x{n}" if n > 1 else code for code, n in code_counts.items()
            )
        refusal_display = ", ".join(refusal_display_parts) or "-"

        if result.unmockable_categories:
            boundary_display = ", ".join(
                f"{cat} x{n}" for cat, n in sorted(result.unmockable_categories.items())
            )
        else:
            boundary_display = "-"

        if result.exception_text is not None:
            first_line = result.exception_text.strip().splitlines()[-1]
            refusal_display = f"exception: {first_line}"

        lines.append(
            f"| {program_label} | {parsed_display} | {exit_display} | "
            f"{refusal_display} | {boundary_display} |"
        )

    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append(f"- Programs swept: {len(results)}")
    lines.append(f"- Parsed OK (no parse error, no exception): {parsed_ok_count}")
    lines.append(f"- Generate exited 0 (clean): {clean_generate_count}")
    lines.append(f"- Raised an uncaught exception: {exception_count}")
    lines.append("")
    lines.append("### Refusal codes across corpus")
    lines.append("")
    if code_totals:
        lines.append("| Code | Count |")
        lines.append("|---|---|")
        for code, count in sorted(code_totals.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {code} | {count} |")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("### Unmockable-boundary categories across corpus")
    lines.append("")
    if category_totals:
        lines.append("| Category | Count |")
        lines.append("|---|---|")
        for category, count in sorted(category_totals.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {category} | {count} |")
    else:
        lines.append("(none)")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    results = sweep()
    print(render_report(results))


if __name__ == "__main__":
    main()
