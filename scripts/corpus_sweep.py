"""Corpus-sweep harness for `mockymock generate`.

Runs `mockymock generate <program.cbl>` over every COBOL program in a corpus
and tallies the outcomes into a Markdown report: which programs generate
cleanly, and which blocker categories (`refused (<CODE>)` codes, parse
errors, missing copybooks, crashes, timeouts) and unmockable-boundary
categories show up. The tallying lives in `mockymock.report.sweep`.

Each run can be saved as a JSON snapshot (`--json`) and compared with an
earlier one (`--baseline`): the report then gains a per-category diff that
names the programs newly blocked or cleared in each category, and
`--fail-on-regression` turns any program newly blocked by a category into
exit status 1.

This is measurement only -- it does not touch engine code and does not run
Docker (`generate` is parse-and-analyze only, no compile/run). It never
writes into the repo's tracked `.cut` files: every `-o` target is a path
inside a throwaway `tempfile.TemporaryDirectory()`.

Default corpus (when no --corpus is given):
  - 17 real-world programs in ../legacy-application/cobol/*.cbl (sibling
    repo), with ../legacy-application/copybook passed as --copybook-path
    when it exists.
  - tests/integration/fixtures/*.cbl and its subdirectories (each
    subdirectory's own copybooks/ dir, if present, is used).
  - examples/**/*.cbl and examples/**/*.CBL (each program directory's own
    copybooks/ or copybook/ dir, if present, is used; the uppercase
    extension covers the NIST CCVS85 examples on case-sensitive
    filesystems).

With --corpus DIR (repeatable), every .cbl/.cob/.CBL/.COB file under DIR is
swept instead, labelled by its path relative to DIR's parent so labels stay
the same from run to run.

Usage:
    python scripts/corpus_sweep.py > docs/corpus-sweep-report.md
    python scripts/corpus_sweep.py --corpus ~/src/cobol \\
        --copybook-path ~/src/copy --timeout 120 --jobs 4 \\
        --json sweeps/today.json --baseline sweeps/last.json -o report.md
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import traceback
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from mockymock.report.sweep import (
    ProgramResult,
    SweepSnapshot,
    classify_output,
    crashed,
    diff_snapshots,
    render_diff,
    render_report,
    timed_out,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_APP_ROOT = REPO_ROOT.parent / "legacy-application"

_PROGRAM_PATTERNS = ("*.cbl", "*.cob", "*.CBL", "*.COB")
# Runs `mockymock generate` in a child process, so a hung program can be
# killed at --timeout. Same entry point as the in-process path.
_CHILD = "import sys; from mockymock.cli.main import main; sys.exit(main(sys.argv[1:]))"


@dataclass
class CorpusEntry:
    path: Path
    label: str
    copybook_dirs: list[Path]


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


def _relative_label(path: Path) -> str:
    for base in (LEGACY_APP_ROOT, REPO_ROOT):
        try:
            return str(path.relative_to(base)).replace("\\", "/")
        except ValueError:
            continue
    return str(path)


def discover_corpus(
    corpus_dirs: Sequence[Path] = (), copybook_paths: Sequence[Path] = ()
) -> list[CorpusEntry]:
    """Every program to sweep, with the copybook dirs to pass for it: the
    ones found next to it, then `copybook_paths`. Without `corpus_dirs`,
    the default corpus (the legacy-application programs, the
    integration-test fixtures and the in-repo examples)."""
    entries: list[CorpusEntry] = []
    seen: set[Path] = set()

    def add(path: Path, label: str) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        local = find_copybook_dir(path)
        dirs = ([local] if local is not None else []) + [
            p for p in copybook_paths if p != local
        ]
        entries.append(CorpusEntry(path, label, dirs))

    if corpus_dirs:
        for root in corpus_dirs:
            if root.is_file():
                add(root, root.name)
                continue
            base = root.resolve().parent
            programs = {p for pattern in _PROGRAM_PATTERNS for p in root.rglob(pattern)}
            for program in sorted(programs):
                label = str(program.resolve().relative_to(base)).replace("\\", "/")
                add(program, label)
        return entries

    legacy_cobol_dir = LEGACY_APP_ROOT / "cobol"
    if legacy_cobol_dir.is_dir():
        for cbl in sorted(legacy_cobol_dir.glob("*.cbl")):
            add(cbl, _relative_label(cbl))

    fixtures_dir = REPO_ROOT / "tests" / "integration" / "fixtures"
    if fixtures_dir.is_dir():
        for cbl in sorted(fixtures_dir.rglob("*.cbl")):
            add(cbl, _relative_label(cbl))

    # NIST CCVS85 examples use the uppercase .CBL extension; rglob is
    # case-sensitive on Linux, so both spellings are swept explicitly.
    examples_dir = REPO_ROOT / "examples"
    if examples_dir.is_dir():
        for pattern in ("*.cbl", "*.CBL"):
            for cbl in sorted(examples_dir.rglob(pattern)):
                add(cbl, _relative_label(cbl))

    return entries


def _generate_argv(entry: CorpusEntry, output_path: Path) -> list[str]:
    argv = ["generate", str(entry.path), "-o", str(output_path), "--force"]
    for copybook_dir in entry.copybook_dirs:
        argv.extend(["--copybook-path", str(copybook_dir)])
    return argv


def run_generate(entry: CorpusEntry, output_path: Path) -> ProgramResult:
    """Invoke `mockymock generate` in-process for one program and tally
    what it printed. An exception raised inside generate is recorded
    rather than allowed to abort the sweep."""
    from mockymock.cli.main import main

    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            exit_code = main(_generate_argv(entry, output_path))
    except Exception:  # noqa: BLE001 - a crashing program IS a finding
        return crashed(entry.label, traceback.format_exc())
    return classify_output(entry.label, exit_code, buffer.getvalue())


def run_generate_subprocess(
    entry: CorpusEntry, output_path: Path, timeout: float | None
) -> ProgramResult:
    """Same as `run_generate`, in a child process that is killed after
    `timeout` seconds."""
    try:
        completed = subprocess.run(
            [sys.executable, "-c", _CHILD, *_generate_argv(entry, output_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        return timed_out(entry.label, timeout or 0)
    if completed.returncode != 0 and "Traceback (most recent call last)" in (
        completed.stderr
    ):
        return crashed(entry.label, completed.stderr)
    return classify_output(entry.label, completed.returncode, completed.stdout)


def sweep(
    entries: Sequence[CorpusEntry], timeout: float | None = None, jobs: int = 1
) -> list[ProgramResult]:
    """Run every entry, in order. With a timeout or more than one job,
    each program runs in its own child process."""
    with tempfile.TemporaryDirectory(prefix="mockymock-corpus-sweep-") as tmp:
        tmp_dir = Path(tmp)
        # One scratch .cut per entry, so parallel runs never share a path.
        outputs = [tmp_dir / f"{i}-{e.path.stem}.cut" for i, e in enumerate(entries)]
        if timeout is None and jobs <= 1:
            return [
                run_generate(e, out) for e, out in zip(entries, outputs, strict=True)
            ]
        with ThreadPoolExecutor(max_workers=max(jobs, 1)) as pool:
            return list(
                pool.map(
                    lambda pair: run_generate_subprocess(pair[0], pair[1], timeout),
                    zip(entries, outputs, strict=True),
                )
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sweep `mockymock generate` over a COBOL corpus and "
        "tally blockers per category."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        action="append",
        default=[],
        help="directory (or single program) to sweep; repeatable. Default: "
        "the legacy-application programs, test fixtures and examples",
    )
    parser.add_argument(
        "--copybook-path",
        type=Path,
        action="append",
        default=[],
        help="copybook directory passed to every program; repeatable",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="seconds before a program counts as TIMEOUT (runs each "
        "program in a child process)",
    )
    parser.add_argument(
        "--jobs", type=int, default=1, help="programs to run at once (default 1)"
    )
    parser.add_argument(
        "--json", type=Path, help="save this run's snapshot as JSON to this path"
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="an earlier --json snapshot to diff this run against",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="exit 1 when a program is blocked by a category it was not "
        "blocked by in --baseline",
    )
    parser.add_argument(
        "-o", "--output", type=Path, help="write the Markdown report here, not stdout"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.fail_on_regression and args.baseline is None:
        print("corpus_sweep: --fail-on-regression needs --baseline", file=sys.stderr)
        return 2
    # Read the baseline before the (long) sweep, so a bad path fails fast.
    baseline = SweepSnapshot.load(args.baseline) if args.baseline else None

    entries = discover_corpus(args.corpus, args.copybook_path)
    results = sweep(entries, timeout=args.timeout, jobs=args.jobs)
    snapshot = SweepSnapshot.from_results(results, corpus=[str(p) for p in args.corpus])
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        snapshot.save(args.json)

    report = render_report(snapshot)
    diff = diff_snapshots(baseline, snapshot) if baseline is not None else None
    if diff is not None:
        report += "\n" + render_diff(diff)
    if args.output is not None:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)
    if args.fail_on_regression and diff is not None and diff.has_regressions:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
