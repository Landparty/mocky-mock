"""Codegen and harness side of `USE REAL FILE` / `EXPECT FILE` / `SAVE FILE`.

Integration tests level 2 (docs/2026-11-06-real-files-and-job-runs-design.md):
a real file's statements run as written (`engine.checks.expand_real_files`
answers each of its sites with a pass-through directive), so the program
really opens, reads and writes it. What this module adds:

* `rewrite_assigns`: each real file's SELECT ... ASSIGN names a file inside
  the run's sandbox (`FILES_DIR/<FILE>`), relative to the binary's working
  directory, which both toolchains set to the sandbox. Nothing outside the
  sandbox is ever opened.
* `insert_case_staging`: each case starts by deleting every real file and
  copying in the ones with a FROM source (`CBL_DELETE_FILE`,
  `CBL_COPY_FILE`, GnuCOBOL's own file routines), and ends by copying each
  checked file to `OUT_DIR/<case>-<n>`, so cases stay independent and
  each case's output survives the next case.
* `check_files`: after the run, every `EXPECT FILE` snapshot is compared
  with its golden file, record by record, and every `SAVE FILE` snapshot is
  written out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from mockymock.dsl.model import FileCheck, MockTestSuite

#: Sandbox folders (relative to the binary's working directory).
FILES_DIR = "ut-files"
FIXTURES_DIR = "ut-fixtures"
OUT_DIR = "ut-out"

#: Organizations a real file may have (GnuCOBOL's indexed and relative
#: files are not VSAM images, so those stay mocked).
REAL_ORGANIZATIONS = frozenset(
    {"SEQUENTIAL", "LINE SEQUENTIAL", "LINE-SEQUENTIAL", "RECORD SEQUENTIAL"}
)

#: Organizations a real file may have only when the program builds it
#: itself: no `FROM` data and no EXPECT / SAVE FILE (GnuCOBOL's indexed and
#: relative files are its own format, not VSAM images, so there is nothing
#: portable to stage or compare), as in `generate`'s round-trip case.
SELF_BUILT_ORGANIZATIONS = frozenset({"INDEXED", "RELATIVE"})

_ASSIGN_RE = re.compile(
    r"""\bASSIGN(\s+TO)?\s+("[^"]*"|'[^']*'|[A-Za-z0-9][A-Za-z0-9-]*)""",
    re.IGNORECASE,
)
_SENTENCE_END_RE = re.compile(r"\.\s*$")
#: `ASSIGN` / `ASSIGN TO` ending a line: the name is on a following one.
_ASSIGN_ALONE_RE = re.compile(r"\bASSIGN(\s+TO)?\s*$", re.IGNORECASE)
#: The first token of a code line: the ASSIGN name continued from above.
_ASSIGN_NAME_RE = re.compile(
    r"""\s*("[^"]*"|'[^']*'|[A-Za-z0-9][A-Za-z0-9-]*)""", re.IGNORECASE
)


def _code_area(text: str) -> str:
    """`text` without a fixed-format line's identification area (columns
    73-80, which the compiler ignores: NIST programs carry `SQ1024.2`
    there). A comment line or a blank one reads as empty."""
    if len(text) > 6 and text[6:7] in ("*", "/"):
        return ""
    return text[:72] if len(text) > 72 else text


@dataclass(frozen=True)
class FileLayout:
    """What the harness needs of one real file to compare it."""

    organization: str
    record_length: int | None


def sandbox_name(file: str) -> str:
    return f"{FILES_DIR}/{file.upper()}"


def snapshot_name(case_id: str, index: int) -> str:
    return f"{OUT_DIR}/{case_id}-{index}"


def rewrite_assigns(
    lines: list[str], select_lines: dict[str, int], files: set[str]
) -> tuple[list[str], list[str]]:
    """(lines with each real file's ASSIGN pointed into the sandbox,
    problems). `select_lines` maps a file name to its SELECT's 1-based line
    in `lines`; the ASSIGN is looked for from there to the end of the
    SELECT sentence."""
    out = list(lines)
    problems: list[str] = []
    for file in sorted(files):
        start = select_lines.get(file)
        if start is None:
            problems.append(f"USE REAL FILE {file}: the program has no SELECT {file}")
            continue
        index = start - 1
        done = False
        pending = False  # ASSIGN [TO] seen, its name is on a later line
        while index < len(out):
            text = out[index]
            code = _code_area(text)
            if pending:
                name = _ASSIGN_NAME_RE.match(code)
                if name is not None:
                    out[index] = (
                        text[: name.start(1)]
                        + f'"{sandbox_name(file)}"'
                        + text[name.end(1) :]
                    )
                    done = True
                    break
            elif _ASSIGN_ALONE_RE.search(code) is not None:
                # `ASSIGN TO` ending the line: `TO` is no file name.
                pending = True
            else:
                match = _ASSIGN_RE.search(code)
                if match is not None:
                    out[index] = (
                        text[: match.start()]
                        + f'ASSIGN TO "{sandbox_name(file)}"'
                        + text[match.end() :]
                    )
                    done = True
                    break
            if _SENTENCE_END_RE.search(code.split("*>", 1)[0]):
                break
            index += 1
        if not done:
            problems.append(
                f"USE REAL FILE {file}: its SELECT has no ASSIGN TO <name> "
                "this run can point at a sandbox file"
            )
    return out, problems


def _call(routine: str, *args: str) -> str:
    quoted = " ".join(f'"{arg}"' for arg in args)
    return f'           CALL "{routine}" USING {quoted}'


def insert_case_staging(
    instrumented: list[str],
    suite: MockTestSuite,
    fixtures: dict[tuple[int, str], str],
) -> list[str]:
    """The instrumented source with each case's file staging added.

    `fixtures` maps (1-based case index, file) to the sandbox fixture path
    the case's FROM source was copied to. The setup goes right after the
    driver's `MOVE "<id>" TO UT-CURRENT-CASE` (before it resets
    RETURN-CODE, which the file routines set); the snapshots right before
    the case's END marker."""
    out = list(instrumented)
    for index, case in enumerate(suite.test_cases, start=1):
        if not case.real_files:
            continue
        case_id = f"{index:03d}"
        setup: list[str] = []
        for real in case.real_files:
            setup.append(_call("CBL_DELETE_FILE", sandbox_name(real.file)))
            fixture = fixtures.get((index, real.file))
            if fixture is not None:
                setup.append(_call("CBL_COPY_FILE", fixture, sandbox_name(real.file)))
        teardown = [
            _call("CBL_COPY_FILE", sandbox_name(check.file), snapshot_name(case_id, n))
            for n, check in enumerate(case.file_checks)
        ]
        header = f"       UT-TESTCASE-{case_id}."
        try:
            start = out.index(header)
        except ValueError:
            continue
        move = f'           MOVE "{case_id}" TO UT-CURRENT-CASE'
        position = next((i for i in range(start, len(out)) if out[i] == move), start)
        out[position + 1 : position + 1] = setup
        end_marker = f'           DISPLAY "__MOCKYMOCK__ CASE {case_id} END".'
        end = next((i for i in range(position, len(out)) if out[i] == end_marker), None)
        if end is not None and teardown:
            out[end:end] = teardown
    return out


def _records(data: bytes, layout: FileLayout | None) -> list[bytes]:
    if layout is not None and "LINE" in layout.organization.upper():
        text = data.replace(b"\r\n", b"\n")
        records = text.split(b"\n")
        if records and records[-1] == b"":
            records.pop()
        # GnuCOBOL drops trailing blanks of a LINE SEQUENTIAL record.
        return [record.rstrip(b" ") for record in records]
    if layout is not None and layout.record_length:
        size = layout.record_length
        return [data[i : i + size] for i in range(0, len(data), size)]
    return [data] if data else []


def _show(record: bytes) -> str:
    text = record.decode("latin-1")
    shown = "".join(ch if 32 <= ord(ch) < 127 else "." for ch in text)
    return f'"{shown[:80]}"' + ("..." if len(shown) > 80 else "")


def compare_file(
    actual: bytes, expected: bytes, layout: FileLayout | None
) -> str | None:
    """None when equal, else what differs (first differing record)."""
    got = _records(actual, layout)
    want = _records(expected, layout)
    for number, (a, b) in enumerate(zip(got, want, strict=False), start=1):
        if a != b:
            return f"record {number} differs: expected {_show(b)}, got {_show(a)}"
    if len(got) != len(want):
        return f"expected {len(want)} record(s), got {len(got)}"
    return None


@dataclass
class FileCheckOutcome:
    case_index: int
    check: FileCheck
    failure: str | None = None
    recorded: bool = False


def check_files(
    suite: MockTestSuite,
    snapshots: dict[str, bytes],
    cut_dir: Path,
    layouts: dict[str, FileLayout],
    record: bool,
    ran: set[int],
) -> list[FileCheckOutcome]:
    """Compare every EXPECT FILE of a case that ran (1-based indexes in
    `ran`) with its golden file, and write every SAVE FILE. Under `record`
    (`--record-expectations`) a missing golden file is written from what the
    case produced."""
    outcomes: list[FileCheckOutcome] = []
    for index, case in enumerate(suite.test_cases, start=1):
        if index not in ran:
            continue
        case_id = f"{index:03d}"
        for n, check in enumerate(case.file_checks):
            outcome = FileCheckOutcome(case_index=index, check=check)
            outcomes.append(outcome)
            data = snapshots.get(snapshot_name(case_id, n))
            target = (cut_dir / check.path).resolve()
            if data is None:
                outcome.failure = (
                    f"{check.kind} FILE {check.file}: the case left no file "
                    f"{check.file} (never opened for output, or not closed)"
                )
                continue
            if check.kind == "SAVE":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                continue
            if not target.is_file():
                if record:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    outcome.recorded = True
                else:
                    outcome.failure = (
                        f'EXPECT FILE {check.file} MATCHES "{check.path}": no such '
                        "golden file (run with --record-expectations to record it)"
                    )
                continue
            difference = compare_file(
                data, target.read_bytes(), layouts.get(check.file)
            )
            if difference is not None:
                outcome.failure = (
                    f'EXPECT FILE {check.file} MATCHES "{check.path}": {difference}'
                )
    return outcomes
