"""Parses GnuCOBOL's COB_TRACE_FILE output into an executed-path report.

The trace is emitted with COB_TRACE_FORMAT='%P|%S|%L' (set by
`runtime.docker_toolchain.run_binary`). Fields stay space-padded even with
an explicit format, so every split field is stripped. Two preamble lines
(`Source: '...'` and a bare `Program-Id:`) precede the entries and carry no
delimiters.

Line numbers in the trace are INSTRUMENTED-source lines. They mean nothing
to the user until remapped through
`report.coverage.build_original_line_map`, which drops splicer-inserted
lines -- so the reported path answers "which of MY lines ran", exactly as
the coverage report does.

Mock firing order deliberately does NOT come from here: the mock dispatch
blocks are splicer-inserted, so that same remap drops them. It arrives
instead via `__MOCKYMOCK__ MOCK:` lines on stdout
(`report.results.TestResult.mock_hits`). See
docs/2026-07-21-debug-trace-design.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

TRACE_JSON_VERSION = 1

#: A `PERFORM UNTIL` with many iterations can emit an effectively unbounded
#: trace. Cap the reported path and say so, rather than streaming or
#: sampling.
TRACE_ENTRY_CAP = 50_000

_PARAGRAPH_PREFIX = "Paragraph:"
_ENTRY_PREFIX = "Entry:"


@dataclass
class TraceEntry:
    """One traced statement, at an INSTRUMENTED-source line number."""

    line: int
    statement: str | None
    paragraph: str | None
    #: The PROGRAM-ID the entry ran in (`%P`), upper case; "" when unknown.
    program: str = ""


def parse_trace(trace_text: str) -> list[TraceEntry]:
    """Traced statements in execution order, at instrumented line numbers."""
    entries: list[TraceEntry] = []
    for raw in trace_text.splitlines():
        parts = raw.split("|")
        if len(parts) != 3:
            continue  # preamble lines carry no delimiters
        program_text, what, line_text = (part.strip() for part in parts)
        # `%P` renders as "Program-Id:  NAME", padded.
        program = program_text.split(":", 1)[-1].strip().upper()
        try:
            line = int(line_text)
        except ValueError:
            continue
        if what.startswith(_PARAGRAPH_PREFIX):
            entries.append(
                TraceEntry(
                    line=line,
                    statement=None,
                    paragraph=what[len(_PARAGRAPH_PREFIX) :].strip(),
                    program=program,
                )
            )
        elif what.startswith(_ENTRY_PREFIX):
            continue  # program entry, not one of the user's statements
        else:
            entries.append(
                TraceEntry(line=line, statement=what, paragraph=None, program=program)
            )
    return entries


_CASE_PARAGRAPH_PREFIX = "UT-TESTCASE-"


def case_entries(
    entries: list[TraceEntry], instrumented: list[str], case_id: str | None
) -> list[TraceEntry]:
    """Only the entries the selected case ran (issue #334).

    The trace file covers the whole binary, so BEFORE-ALL steps (run in
    the suite paragraph before the case is PERFORMed) and AFTER-ALL steps
    (after it returns) were reported as the case's path. A case runs from
    the entry into its driver paragraph `UT-TESTCASE-<id>` up to its
    `CASE <id> END` DISPLAY, the paragraph's last statement; BEFORE-EACH
    and AFTER-EACH run between the two and stay in. Without the case id
    (the case never printed START) the first case paragraph is used, and
    without an END line in the source the span runs to the trace's end."""
    paragraph = f"{_CASE_PARAGRAPH_PREFIX}{case_id}" if case_id else None
    end_marker = f'__MOCKYMOCK__ CASE {case_id} END"' if case_id else None
    end_lines = {
        number
        for number, text in enumerate(instrumented, start=1)
        if end_marker is not None and end_marker in text
    }
    start = next(
        (
            index
            for index, entry in enumerate(entries)
            if entry.paragraph is not None
            and (
                entry.paragraph.upper() == paragraph
                if paragraph is not None
                else entry.paragraph.upper().startswith(_CASE_PARAGRAPH_PREFIX)
            )
        ),
        None,
    )
    if start is None:
        return []
    scoped: list[TraceEntry] = []
    for entry in entries[start:]:
        scoped.append(entry)
        if entry.paragraph is None and entry.line in end_lines:
            break
    return scoped


def format_trace_json(
    entries: list[TraceEntry],
    line_map: dict[int, int],
    mock_hits: list[str],
    case_name: str,
    case_line: int | None,
    cut_file: str,
    program_file: str,
    copybook_lines: dict[int, tuple[str, int]] | None = None,
) -> str:
    """The machine-readable contract consumed by the VS Code extension.

    `copybook_lines` (`coverage.build_copybook_line_map`) places a
    statement a COPY brought in: its entry carries the copybook's `file`
    name and its line there (issue #242). Entries without `file` are lines
    of `programFile`."""
    path: list[dict[str, object]] = []
    truncated = False
    for entry in entries:
        original = line_map.get(entry.line)
        where: dict[str, object]
        if original is not None:
            where = {"line": original}
        elif copybook_lines and entry.line in copybook_lines:
            copybook, copybook_line = copybook_lines[entry.line]
            where = {"file": copybook, "line": copybook_line}
        else:
            continue  # splicer-inserted line: not the user's code
        if len(path) >= TRACE_ENTRY_CAP:
            truncated = True
            break
        if entry.paragraph is not None:
            path.append({**where, "paragraph": entry.paragraph})
        else:
            path.append({**where, "statement": entry.statement})

    payload = {
        "version": TRACE_JSON_VERSION,
        "cutFile": cut_file,
        "programFile": program_file,
        "case": {"name": case_name, "line": case_line},
        "path": path,
        "mocks": [
            {"order": index, "label": label}
            for index, label in enumerate(mock_hits, start=1)
        ],
        "truncated": truncated,
    }
    return json.dumps(payload, indent=2) + "\n"


def format_trace_console(payload: dict) -> str:
    """Human-readable rendering of the same contract, for a plain --trace."""
    case = payload["case"]
    lines = [f"Execution trace for case: {case['name']}"]
    if payload["mocks"]:
        lines.append("  mocks fired, in order:")
        lines.extend(
            f"    {entry['order']}. {entry['label']}" for entry in payload["mocks"]
        )
    else:
        lines.append("  mocks fired: none")
    lines.append(f"  statements executed: {len(payload['path'])}")
    if payload["truncated"]:
        lines.append(f"  (path truncated at {TRACE_ENTRY_CAP} entries)")
    for entry in payload["path"]:
        origin = f" ({entry['file']})" if entry.get("file") else ""
        if "paragraph" in entry:
            lines.append(
                f"    line {entry['line']:>6}  paragraph  {entry['paragraph']}{origin}"
            )
        else:
            lines.append(
                f"    line {entry['line']:>6}             {entry['statement']}{origin}"
            )
    return "\n".join(lines)
