"""`generate --real-files`: turn a scenario suite into a real-file suite.

Integration tests level 2 (docs/2026-11-06-real-files-and-job-runs-design.md).
`generate` scaffolds one TESTCASE per scenario, each with the READ data the
fixture bundle generated for it as a `MOCK READ` body. This rewrites the
text so every sequential file of the program is real:

* the MOCK blocks of a real file's OPEN / READ / WRITE / REWRITE / CLOSE
  go, with the VERIFY lines counting them and the STUB EXPECT lines naming
  its records: a real file is checked as a whole instead;
* a file the program READs gets a data file holding the very records its
  mock returned, encoded with the FD's record layout (cobol-parser's record
  encoder, FILLER included), and `USE REAL FILE <file> FROM "<data>"`;
* a file the program writes gets `USE REAL FILE <file>` and an
  `EXPECT FILE <file> MATCHES "<golden>"`, recorded by the first
  `run --record-expectations`.

Indexed and relative files stay mocked (they are not VSAM images).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mockymock.dsl.model import FILE_OP_CATEGORIES, MockCategory
from mockymock.splicer.real_files import REAL_ORGANIZATIONS, SELF_BUILT_ORGANIZATIONS

_TESTCASE_RE = re.compile(r'^TESTCASE\s+"(?P<name>[^"]*)"')
_MOCK_RE = re.compile(
    r"^MOCK\s+(?P<cat>OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START|UNLOCK)\s+"
    r"(?P<key>[A-Za-z0-9][A-Za-z0-9-]*)",
    re.IGNORECASE,
)
_END_MOCK_RE = re.compile(r"^END-MOCK\.?$", re.IGNORECASE)
_VERIFY_RE = re.compile(
    r"^(?:\*>\s*)?VERIFY\s+(?:OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START|UNLOCK)\s+"
    r"(?P<key>[A-Za-z0-9][A-Za-z0-9-]*)(?:\s+(?:INPUT|OUTPUT|I-O|EXTEND))?\s+WAS\b",
    re.IGNORECASE,
)
_STUB_RE = re.compile(r"^\*>\s*STUB EXPECT\s+(?P<name>[A-Za-z0-9][A-Za-z0-9-]*)\b")
_PERFORM_RE = re.compile(r"^PERFORM\s+", re.IGNORECASE)
_WHEN_TALLY_RE = re.compile(
    r"^WHEN\s+UT-READ-\S+-TALLY\s*=\s*(?P<n>\d+)$", re.IGNORECASE
)
_WHEN_RE = re.compile(r"^WHEN\b", re.IGNORECASE)
_MOVE_RE = re.compile(
    r"^MOVE\s+(?P<value>.+?)\s+TO\s+(?P<target>[A-Za-z0-9][A-Za-z0-9-]*)\s*$",
    re.IGNORECASE,
)


@dataclass
class RealFilePlan:
    """One sequential file `--real-files` makes real."""

    file: str
    names: set[str]  # the file and its record names (upper case)
    reads: bool
    writes: bool
    specs: list[Any] = field(default_factory=list)  # byte-complete layout
    line_sequential: bool = False
    #: Source lines of the first OPEN OUTPUT/EXTEND and the first OPEN
    #: INPUT/I-O of the file (None: none), for `round_trip_case`.
    first_create: int | None = None
    first_open_read: int | None = None
    #: Other files a statement naming this one names too (OPEN A B): a
    #: statement runs once, so they are real together or not at all.
    partners: set[str] = field(default_factory=set)

    @property
    def round_trip(self) -> bool:
        """The program creates the file before it first opens it to read,
        so a real file with no data of its own gives the reads back what
        the program wrote."""
        return (
            self.reads
            and self.writes
            and self.first_create is not None
            and (
                self.first_open_read is None or self.first_create < self.first_open_read
            )
        )


def plan_real_files(
    ast: Any, surface: Any, self_built: bool = False
) -> tuple[list[RealFilePlan], list[str]]:
    """(the program's files that can be real, notes on the ones that stay
    mocked). With `self_built`, indexed and relative files count too: they
    can be real only with no data staged or compared (the round-trip
    case)."""
    from cobolparser.generators.data.layout import flatten_record
    from cobolparser.generators.data.options import DataGeneratorOptions
    from cobolparser.generators.data.program_layout import ProgramLayoutIndex

    index = ProgramLayoutIndex.build(ast)
    options = DataGeneratorOptions().for_record_image()
    plans: dict[str, RealFilePlan] = {}
    notes: list[str] = []
    together: dict[str, set[str]] = {}
    for site in surface.boundary_sites:
        if site.category not in FILE_OP_CATEGORIES:
            continue
        named = {f for f in (_file_of(index, k.upper()) for k in site.keys) if f}
        for one in named:
            together.setdefault(one, set()).update(named - {one})
        for key in site.keys:
            file = _file_of(index, key.upper())
            if file is None:
                continue
            facts = index.file_facts(file)
            organization = (
                (facts.organization if facts else None) or "SEQUENTIAL"
            ).upper()
            if facts is None or facts.record_type == "SD":
                continue
            if organization not in REAL_ORGANIZATIONS and not (
                self_built and organization in SELF_BUILT_ORGANIZATIONS
            ):
                note = f"{file} stays mocked: {organization} files cannot be real"
                if note not in notes:
                    notes.append(note)
                continue
            plan = plans.get(file)
            if plan is None:
                records = index.records_for_file(file)
                specs: list[Any] = []
                if records:
                    biggest = max(
                        records, key=lambda r: len(flatten_record(r, options))
                    )
                    specs = flatten_record(biggest, options)
                plan = RealFilePlan(
                    file=file,
                    names={file, *(n.upper() for n in facts.record_names)},
                    reads=False,
                    writes=False,
                    specs=specs,
                    line_sequential="LINE" in organization,
                )
                plans[file] = plan
            if site.category is MockCategory.READ:
                plan.reads = True
            if site.category in (MockCategory.WRITE, MockCategory.REWRITE):
                plan.writes = True
            if site.category is MockCategory.OPEN:
                mode = (getattr(site, "open_modes", {}) or {}).get(file, "")
                if mode in ("OUTPUT", "EXTEND", "I-O"):
                    plan.writes = True
                line = getattr(site, "line", None)
                if isinstance(line, int):
                    if mode in ("OUTPUT", "EXTEND"):
                        plan.first_create = min(plan.first_create or line, line)
                    elif mode in ("INPUT", "I-O"):
                        plan.first_open_read = min(plan.first_open_read or line, line)
                if mode in ("INPUT", "I-O", "EXTEND"):
                    plan.reads = plan.reads or mode == "INPUT"
    for file, plan in plans.items():
        plan.partners = together.get(file, set())
    return sorted(plans.values(), key=lambda p: p.file), notes


def _file_of(index: Any, name: str) -> str | None:
    if index.file_facts(name) is not None:
        return name
    for file in index.file_names():
        facts = index.file_facts(file)
        if facts is not None and name in {n.upper() for n in facts.record_names}:
            return file.upper()
    return None


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read_rows(body: list[str]) -> list[dict[str, str]]:
    """The records a generated `MOCK READ` body returns, in order: one
    `{field: value}` per `WHEN UT-READ-<file>-TALLY = n` arm (the
    generator's form), or one for a plain body of MOVEs."""
    rows: dict[int, dict[str, str]] = {}
    current: int | None = None
    plain: dict[str, str] = {}
    saw_tally = False
    for raw in body:
        line = raw.strip()
        if (m := _WHEN_TALLY_RE.match(line)) is not None:
            current = int(m.group("n"))
            saw_tally = True
            rows.setdefault(current, {})
            continue
        if _WHEN_RE.match(line):
            current = None
            continue
        if (m := _MOVE_RE.match(line)) is not None:
            target = m.group("target").upper()
            if target.startswith("UT-"):
                continue
            value = _strip_quotes(m.group("value"))
            if current is not None:
                rows[current][target] = value
            elif not saw_tally:
                plain[target] = value
    if saw_tally:
        return [rows[n] for n in sorted(rows)]
    return [plain] if plain else []


def encode_rows(plan: RealFilePlan, rows: list[dict[str, str]], seed: int) -> bytes:
    """The data file holding `rows`: each record's other fields are filled
    from their PICTUREs (seeded), so the file is the same on every run."""
    import random

    from cobolparser.generators.data.encoding import (
        Charset,
        EncodingOptions,
        encode_record,
    )
    from cobolparser.generators.data.options import DataGeneratorOptions
    from cobolparser.generators.data.values import ValueFactory

    options = EncodingOptions(charset=Charset.ASCII)
    factory = ValueFactory(
        random.Random(seed), DataGeneratorOptions().for_record_image()
    )
    out = bytearray()
    for number, row in enumerate(rows):
        cells = []
        for spec in plan.specs:
            name = str(getattr(spec, "name", "") or "").upper()
            if name in row:
                cells.append(row[name])
            else:
                cells.append(factory.value_for(spec, number))
        record = encode_record(plan.specs, cells, options)
        if plan.line_sequential:
            record = record.rstrip(b" ") + b"\n"
        out += record
    return bytes(out)


def make_real_file_suite(
    cut_text: str,
    plans: list[RealFilePlan],
    program: str,
    cut_path: Path,
    seed: int = 0,
) -> tuple[str, dict[Path, bytes], list[str]]:
    """(rewritten `.cut` text, data files to write, notes)."""
    if not plans:
        return cut_text, {}, ["no sequential file to make real"]
    by_name = {name: plan for plan in plans for name in plan.names}
    lines = cut_text.split("\n")
    out: list[str] = []
    files: dict[Path, bytes] = {}
    notes: list[str] = []
    case_number = 0
    case_rows: dict[str, list[dict[str, str]]] = {}
    pending_case: list[str] | None = None
    skip_mock = False
    mock_body: list[str] | None = None
    mock_file: str | None = None
    prefix = f"{program.upper()}"

    def flush_case() -> None:
        nonlocal pending_case
        if pending_case is None:
            return
        header, *rest = pending_case
        out.append(header)
        indent = "    "
        uses: list[str] = []
        checks: list[str] = []
        for plan in plans:
            if plan.reads:
                rows = case_rows.get(plan.file, [])
                relative = f"data/{prefix}/{case_number}-{plan.file}.dat"
                files[cut_path.parent / relative] = encode_rows(
                    plan, rows, seed + case_number
                )
                uses.append(f'{indent}USE REAL FILE {plan.file} FROM "{relative}"')
            else:
                uses.append(f"{indent}USE REAL FILE {plan.file}")
            if plan.writes:
                golden = f"expected/{prefix}/{case_number}-{plan.file}.dat"
                checks.append(f'{indent}EXPECT FILE {plan.file} MATCHES "{golden}"')
        inserted = False
        for line in rest:
            if not inserted and _PERFORM_RE.match(line.strip()):
                out.extend(uses)
                inserted = True
            out.append(line)
        if not inserted:
            out.extend(uses)
        # The checks go after the last assertion of the case.
        while out and not out[-1].strip():
            out.pop()
        out.extend(checks)
        out.append("")
        pending_case = None

    for line in lines:
        stripped = line.strip()
        if mock_body is not None:
            if _END_MOCK_RE.match(stripped):
                if mock_file is not None and skip_mock:
                    case_rows.setdefault(mock_file, []).extend(read_rows(mock_body))
                mock_body = None
                mock_file = None
                if skip_mock:
                    skip_mock = False
                    continue
            else:
                mock_body.append(line)
                if skip_mock:
                    continue
            target = pending_case if pending_case is not None else out
            target.append(line)
            continue
        if (m := _TESTCASE_RE.match(stripped)) is not None:
            flush_case()
            case_number += 1
            case_rows = {}
            pending_case = [line]
            continue
        if (m := _MOCK_RE.match(stripped)) is not None:
            key = m.group("key").upper()
            plan = by_name.get(key)
            mock_body = []
            if plan is not None:
                skip_mock = True
                mock_file = plan.file if m.group("cat").upper() == "READ" else None
                continue
            mock_file = None
            target = pending_case if pending_case is not None else out
            target.append(line)
            continue
        if (m := _VERIFY_RE.match(stripped)) is not None and m.group(
            "key"
        ).upper() in by_name:
            continue
        if (m := _STUB_RE.match(stripped)) is not None and m.group(
            "name"
        ).upper() in by_name:
            continue
        target = pending_case if pending_case is not None else out
        target.append(line)
    flush_case()
    real = ", ".join(p.file for p in plans)
    notes.append(f"real files: {real} ({len(files)} data file(s) written)")
    text = "\n".join(out).rstrip("\n") + "\n"
    return text, files, notes


def _round_trip_files(plans: list[RealFilePlan]) -> list[RealFilePlan]:
    """The files the round-trip case makes real: the round-trip ones, plus
    any output-only file a statement names with one (it needs no data);
    a round-trip file sharing a statement with a file that cannot be real
    without data (an indexed file, an input) stays mocked."""
    by_file = {plan.file: plan for plan in plans}
    real = {plan.file for plan in plans if plan.round_trip}
    changed = True
    while changed:
        changed = False
        for file in sorted(real):
            for partner in by_file[file].partners:
                if partner in real:
                    continue
                other = by_file.get(partner)
                if other is not None and other.writes and not other.reads:
                    real.add(partner)
                else:
                    real.discard(file)
                changed = True
                break
    return [by_file[file] for file in sorted(real)]


_EXPECT_RE = re.compile(r"^EXPECT\b", re.IGNORECASE)
_CHARACTERIZATION_RE = re.compile(r"^\*>\s*CHARACTERIZATION\b", re.IGNORECASE)


def _copy_first_case(cut_text: str, title: str, uses: list[str], drop: Any) -> str:
    """`cut_text` with a copy of its first TESTCASE appended under `title`,
    `uses` lines first. `drop(category, key)` names the MOCK blocks, VERIFY
    and STUB EXPECT lines to leave out (STUB EXPECT has category None); the
    copy's EXPECT lines go too, for `run --record-expectations` to record
    the copy's own."""
    lines = cut_text.split("\n")
    start = next(
        (i for i, line in enumerate(lines) if _TESTCASE_RE.match(line.strip())),
        None,
    )
    if start is None:
        return cut_text
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if _TESTCASE_RE.match(lines[i].strip())
        ),
        len(lines),
    )
    body: list[str] = []
    skipping = False
    for line in lines[start + 1 : end]:
        stripped = line.strip()
        if skipping:
            skipping = not _END_MOCK_RE.match(stripped)
            continue
        if (m := _ANY_MOCK_RE.match(stripped)) is not None and drop(
            m.group("cat").upper(), _unquote(m.group("key")).upper()
        ):
            skipping = True
            continue
        if (m := _ANY_VERIFY_RE.match(stripped)) is not None and drop(
            m.group("cat").upper(), _unquote(m.group("key")).upper()
        ):
            continue
        if (m := _STUB_RE.match(stripped)) is not None and drop(
            None, m.group("name").upper()
        ):
            continue
        if _EXPECT_RE.match(stripped) or _CHARACTERIZATION_RE.match(stripped):
            continue
        body.append(line)
    while body and not body[-1].strip():
        body.pop()
    case = [f'TESTCASE "{title}"', *uses, *body]
    return cut_text.rstrip("\n") + "\n\n" + "\n".join(case) + "\n"


_ANY_MOCK_RE = re.compile(
    r"""^MOCK\s+(?P<cat>[A-Z-]+)\s+(?P<key>"[^"]*"|'[^']*'|[A-Za-z0-9][A-Za-z0-9-]*)""",
    re.IGNORECASE,
)
_ANY_VERIFY_RE = re.compile(
    r"""^(?:\*>\s*)?VERIFY\s+(?P<cat>[A-Z-]+)\s+"""
    r"""(?P<key>"[^"]*"|'[^']*'|[A-Za-z0-9][A-Za-z0-9-]*)""",
    re.IGNORECASE,
)


def _unquote(key: str) -> str:
    return key[1:-1] if len(key) >= 2 and key[0] in "\"'" else key


_FILE_CATEGORIES = {
    "OPEN",
    "CLOSE",
    "READ",
    "WRITE",
    "REWRITE",
    "DELETE",
    "START",
    "UNLOCK",
}


def round_trip_case(cut_text: str, plans: list[RealFilePlan]) -> str:
    """`cut_text` with one more TESTCASE: a copy of its first case where
    every file the program writes and then reads back (sequential, or
    indexed / relative since the program builds them) is real with no data
    of its own, so the program reads what it wrote instead of what a mock
    returns. The scenario cases mock each READ, so the checks a program
    makes on its own records (NIST's SQ / IX / RL programs) only run their
    passing side here. `cut_text` comes back unchanged when no file
    qualifies."""
    files = _round_trip_files(plans)
    if not files:
        return cut_text
    names = {name for plan in files for name in plan.names}
    label = ", ".join(plan.file for plan in files)
    return _copy_first_case(
        cut_text,
        f"round trip: {label} real",
        [f"    USE REAL FILE {plan.file}" for plan in files],
        lambda cat, key: (cat is None or cat in _FILE_CATEGORIES) and key in names,
    )


def real_calls_case(cut_text: str, calls: dict[str, str]) -> str:
    """`cut_text` with one more TESTCASE: a copy of its first case where
    each statically CALLed program in `calls` (name -> source path relative
    to the `.cut`) runs for real (`USE REAL CALL`) instead of its mock, so
    the checks a program makes on what its subprograms return (NIST's IC
    programs) run their passing side. `cut_text` comes back unchanged when
    `calls` is empty."""
    if not calls:
        return cut_text
    keys = {key.upper() for key in calls}
    return _copy_first_case(
        cut_text,
        f"real calls: {', '.join(sorted(calls))}",
        [
            f'    USE REAL CALL "{key}" FROM "{path}"'
            for key, path in sorted(calls.items())
        ],
        lambda cat, key: cat == "CALL" and key in keys,
    )
