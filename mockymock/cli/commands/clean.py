"""`mockymock clean`: remove the reports and saved results mockymock wrote."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

#: Dependency/build folders `clean` never walks into, as the dashboard.
_CLEAN_SKIPPED_DIRS = frozenset(
    {"node_modules", "__pycache__", "venv", ".venv", ".git", "build", "dist"}
)


def _clean_candidates(target: Path, include_journal: bool) -> list[Path]:
    """Every artifact `clean` would remove under `target` (a `.cut`, a
    program, or a directory): `.mockymock/` contents, plus files the
    pre-#353 layout left next to a program or suite."""
    from mockymock.project.discovery import COBOL_SOURCE_EXTENSIONS
    from mockymock.report.artifacts import (
        ARTIFACT_DIR,
        KINDS,
        legacy_paths,
        suite_artifacts,
    )

    if target.is_file():
        if target.suffix == ".cut":
            return suite_artifacts(target, None, include_journal=include_journal)
        # A program: every suite named after it, plus its old report files.
        found: list[Path] = []
        for cut in sorted(target.parent.glob(f"{target.stem}*.cut")):
            if cut.stem == target.stem or cut.stem.startswith(f"{target.stem}."):
                found += suite_artifacts(cut, None, include_journal=include_journal)
        found += [
            p
            for p in legacy_paths(target, target.with_suffix(".cut"))[1:]
            if p.is_file()
        ]
        return sorted(set(found))
    found = []
    journal_suffix = "." + KINDS["journal"]
    for dirpath, dirnames, filenames in os.walk(target):
        current = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in _CLEAN_SKIPPED_DIRS
            and (not d.startswith(".") or d == ARTIFACT_DIR)
        )
        if current.name == ARTIFACT_DIR:
            found += [
                current / name
                for name in filenames
                if include_journal or not name.endswith(journal_suffix)
            ]
            continue
        stems = {
            Path(name).stem
            for name in filenames
            if name.endswith(".cut") or name.endswith(COBOL_SOURCE_EXTENSIONS)
        }
        for name in filenames:
            for suffix in (".report.html", ".report.json", ".mutation.json") + (
                (".journal.jsonl",) if include_journal else ()
            ):
                if name.endswith(suffix) and name[: -len(suffix)] in stems:
                    found.append(current / name)
    return sorted(found)


def _cmd_clean(args: argparse.Namespace) -> int:
    """Remove the reports and saved results mockymock wrote (issue #353).
    Journals are the assistant's own record, not something a command can
    recompute, so they stay unless --all."""
    target = Path(args.target) if args.target else Path.cwd()
    if not target.exists():
        print(f"mockymock clean: {target} does not exist")
        return 1
    candidates = _clean_candidates(target, include_journal=args.all)
    staged = _clean_staged_aliases(target, getattr(args, "_config", None))
    if not candidates and not staged:
        print("mockymock clean: nothing to remove")
        return 0
    failed = _remove_staged_aliases(staged, args.dry_run)
    for path in candidates:
        if args.dry_run:
            print(f"would remove {path}")
            continue
        try:
            path.unlink()
        except OSError as exc:
            print(f"mockymock clean: could not remove {path}: {exc}")
            failed += 1
            continue
        print(f"removed {path}")
        parent = path.parent
        if parent.name == ".mockymock":
            try:
                parent.rmdir()  # only succeeds once it is empty
            except OSError:
                pass
    verb = "would remove" if args.dry_run else "removed"
    summary = f"{len(candidates) + len(staged) - failed} file(s)"
    if staged:
        summary += f", {len(staged)} of them folder(s) of staged copybook copies"
    print(f"mockymock clean: {verb} {summary}")
    return 1 if failed else 0


def _clean_staged_aliases(target: Path, config) -> list[Path]:
    """The copybook-alias staging directories (project/copybook_aliases.py)
    built from files under `target` (a program or `.cut`: its folder), or
    under the config's copybook_path and copybook_aliases: copies of
    renamed copybooks in the system temp folder that outlive every run."""
    from mockymock.project.copybook_aliases import staged_directories_for

    roots = [target if target.is_dir() else target.parent]
    if config is not None:
        roots += [Path(entry) for entry in config.copybook_path]
        roots += [Path(entry) for entry in config.copybook_aliases.values()]
    return staged_directories_for(roots)


def _remove_staged_aliases(staged: list[Path], dry_run: bool) -> int:
    """Remove each staging directory and its manifest; the failure count."""
    from mockymock.project.copybook_aliases import manifest_path

    failed = 0
    for directory in staged:
        if dry_run:
            print(f"would remove {directory}")
            continue
        try:
            shutil.rmtree(directory)
            manifest_path(directory).unlink(missing_ok=True)
        except OSError as exc:
            print(f"mockymock clean: could not remove {directory}: {exc}")
            failed += 1
            continue
        print(f"removed {directory}")
    return failed


def register_clean(subparsers: argparse._SubParsersAction) -> None:
    """Add `mockymock clean` to the top-level parser."""
    clean_parser = subparsers.add_parser(
        "clean",
        help=(
            "Remove the reports and saved run/mutation results mockymock "
            "wrote (the .mockymock/ folders); journals are kept unless --all"
        ),
    )
    clean_parser.add_argument(
        "target",
        nargs="?",
        help=(
            "A .cut (that suite), a program (all its suites) or a directory "
            "(everything under it); default: the current directory"
        ),
    )
    clean_parser.add_argument(
        "--all",
        action="store_true",
        help="Also remove the assistant journals",
    )
    clean_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be removed without removing it",
    )
    clean_parser.set_defaults(func=_cmd_clean)
