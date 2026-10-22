"""Where mockymock keeps the files it writes for one suite.

Every artifact a command writes for a `.cut` suite goes into one folder,
`.mockymock/`, next to the `.cut`, named `<cut stem>.<kind>` (issue #353):

    tests/.mockymock/ORDRPROC.report.html     mockymock report
    tests/.mockymock/ORDRPROC.report.json     mockymock report --json
    tests/.mockymock/ORDRPROC.run.json        mockymock run (whole suite)
    tests/.mockymock/ORDRPROC.coverage.json   mockymock run --coverage
    tests/.mockymock/ORDRPROC.mutation.json   mockymock mutate
    tests/.mockymock/ORDRPROC.journal.jsonl   mockymock journal
    tests/.mockymock/ORDRPROC.inputs.json     what each result was computed from

Keyed by the `.cut`'s stem rather than the program's, because a program
can have several suites (`PROG.cut`, `PROG.batch.cut`), and every one of
these files describes one suite. `mockymock clean` removes them.

`run`, `coverage` and `mutation` results are saved automatically so that
`report --execute --mutate` can reuse them instead of compiling and running
everything a second time (issue #352). `inputs.json` records a fingerprint
of what each one was computed from -- the program, the suite, the
copybook directories and the mockymock version -- and a saved result is
reused only while that fingerprint still matches.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ARTIFACT_DIR = ".mockymock"

#: kind -> file suffix after `<cut stem>.`
KINDS: dict[str, str] = {
    "report": "report.html",
    "report-json": "report.json",
    "run": "run.json",
    "coverage": "coverage.json",
    "mutation": "mutation.json",
    "journal": "journal.jsonl",
    "inputs": "inputs.json",
}

#: Results `save_result` fingerprints and `fresh_result` may hand back.
REUSABLE = ("run", "coverage", "mutation")


def artifact_dir(cut_path: Path) -> Path:
    return cut_path.parent / ARTIFACT_DIR


def artifact_path(cut_path: Path, kind: str) -> Path:
    return artifact_dir(cut_path) / f"{cut_path.stem}.{KINDS[kind]}"


def legacy_paths(program_path: Path | None, cut_path: Path) -> list[Path]:
    """Where these files went before issue #353, for `clean` to sweep up
    and for the journal to keep being found: next to the program (report,
    mutation) or next to the `.cut` (journal)."""
    paths = [cut_path.with_name(f"{cut_path.stem}.journal.jsonl")]
    if program_path is not None:
        stem = program_path.stem
        paths += [
            program_path.with_name(f"{stem}.report.html"),
            program_path.with_name(f"{stem}.report.json"),
            program_path.with_name(f"{stem}.mutation.json"),
        ]
    return paths


def journal_path(cut_path: Path) -> Path:
    """The suite's journal: in `.mockymock/`, unless a journal from before
    that folder existed is still next to the `.cut` and none has been
    started in the folder -- an existing journal keeps being appended to
    and read rather than silently forked in two."""
    new = artifact_path(cut_path, "journal")
    legacy = cut_path.with_name(f"{cut_path.stem}.journal.jsonl")
    if legacy.is_file() and not new.exists():
        return legacy
    return new


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def fingerprint(
    program_path: Path, cut_path: Path, copybook_paths: list[str] | None
) -> dict[str, Any]:
    """What a run/mutate result depends on. Copybook directories are
    fingerprinted by each file's name, size and modification time rather
    than read in full: a copybook directory can hold thousands of members,
    and any edit to one changes its mtime."""
    from mockymock import __version__

    copybooks: list[list[Any]] = []
    for directory in copybook_paths or []:
        root = Path(directory)
        try:
            entries = sorted(root.iterdir())
        except OSError:
            copybooks.append([str(root), None])
            continue
        for entry in entries:
            try:
                stat = entry.stat()
            except OSError:
                continue
            if entry.is_file():
                copybooks.append([str(entry), stat.st_size, stat.st_mtime_ns])
    return {
        "program": _sha256(program_path),
        "cut": _sha256(cut_path),
        "copybooks": hashlib.sha256(json.dumps(copybooks).encode("utf-8")).hexdigest(),
        "mockymock": __version__,
    }


def _read_inputs(cut_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(artifact_path(cut_path, "inputs").read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_result(
    cut_path: Path,
    program_path: Path,
    kind: str,
    content: str,
    copybook_paths: list[str] | None,
    inputs: dict[str, Any] | None = None,
) -> Path:
    """Write one reusable result and record what it was computed from.
    `inputs` is the fingerprint taken BEFORE the command ran (a `run
    --record-expectations` rewrites the `.cut` it ran, and the result
    belongs to the suite as it was). Raises OSError on a failed write."""
    if kind not in REUSABLE:
        raise ValueError(f"not a reusable result kind: {kind}")
    path = artifact_path(cut_path, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    stamps = _read_inputs(cut_path)
    stamps[kind] = {
        **(inputs or fingerprint(program_path, cut_path, copybook_paths)),
        "written": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    artifact_path(cut_path, "inputs").write_text(
        json.dumps(stamps, indent=2) + "\n", encoding="utf-8"
    )
    return path


def fresh_result(
    cut_path: Path,
    program_path: Path,
    kind: str,
    copybook_paths: list[str] | None,
) -> tuple[Path, str] | None:
    """(path, when it was written) for a saved result still computed from
    exactly the current program, suite, copybooks and mockymock version,
    or None."""
    path = artifact_path(cut_path, kind)
    stamp = _read_inputs(cut_path).get(kind)
    if not path.is_file() or not isinstance(stamp, dict):
        return None
    current = fingerprint(program_path, cut_path, copybook_paths)
    if any(stamp.get(key) != value for key, value in current.items()):
        return None
    return path, str(stamp.get("written", ""))


def suite_artifacts(
    cut_path: Path, program_path: Path | None, *, include_journal: bool
) -> list[Path]:
    """Every file `clean` would remove for one suite, existing ones only."""
    kinds = [k for k in KINDS if include_journal or k != "journal"]
    paths = [artifact_path(cut_path, kind) for kind in kinds]
    for legacy in legacy_paths(program_path, cut_path):
        if include_journal or not legacy.name.endswith(".journal.jsonl"):
            paths.append(legacy)
    return [p for p in paths if p.is_file()]
