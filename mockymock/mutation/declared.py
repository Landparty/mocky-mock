"""Mutants a person has reviewed and declared equivalent.

`equivalence.py` proves only the shapes it can see from two adjacent
statements. Everything else a test can never kill -- `ADD 1 TO C` swapped
to `SUBTRACT 1 FROM C` on an unsigned COMP-3 that is always zero there,
for instance -- still counts as a survivor and caps the score below 100%.
This file is the reviewed escape hatch: it sits next to the `.cut`, named
`<cut stem>.equivalent.json`, so it is committed and reviewed with the
suite:

    {"equivalent": [
      {"operator": "arith-verb-swap",
       "original": "ADD 1 TO WS-RETRY-COUNT",
       "line": 212,
       "reason": "WS-RETRY-COUNT is unsigned and always 0 on this path"}
    ]}

An entry names its mutant by `operator` plus the source statement it
mutates (`original`, compared with whitespace collapsed, so a line that
moves keeps its declaration) and/or `line` (which picks one when the same
statement appears more than once). `mutated` narrows it to one mutation
when an operator makes several on a line. `reason` is required: a
declaration with none is ignored, and said so.

A declared mutant is never built, is reported as `equivalent` with
"declared equivalent: <reason>" as its detail, and is left out of the
score. An entry that matches no generated mutant -- the statement was
edited or deleted -- is reported, so the list cannot go stale silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from mockymock.mutation.operators import TEXT_START_COL, Mutant

DECLARED_PREFIX = "declared equivalent: "


def declared_equivalents_path(cut_path: Path) -> Path:
    return cut_path.with_name(f"{cut_path.stem}.equivalent.json")


@dataclass(frozen=True)
class Declaration:
    operator: str
    reason: str
    original: str | None = None
    line: int | None = None
    mutated: str | None = None

    def describe(self) -> str:
        where = f"line {self.line} " if self.line is not None else ""
        what = f"{self.original!r} " if self.original else ""
        return f"{where}[{self.operator}] {what}".rstrip()


def _squash(text: str) -> str:
    return " ".join(text.split()).rstrip(".").rstrip().upper()


def _code(line: str) -> str:
    """A source line's statement text: columns 8-72, no `*>` comment."""
    return _squash(line[TEXT_START_COL - 1 : 72].partition("*>")[0])


def load_declarations(path: Path) -> tuple[list[Declaration], list[str]]:
    """The file's declarations, and a note per entry that was ignored (or
    for the whole file when it does not parse). No file, no declarations."""
    if not path.is_file():
        return [], []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return [], [f"{path.name}: not read ({exc}); no mutant declared equivalent"]
    entries = data.get("equivalent") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return [], [f'{path.name}: expected a list under "equivalent"; ignored']
    declarations: list[Declaration] = []
    notes: list[str] = []
    for number, entry in enumerate(entries, start=1):
        where = f"{path.name} entry {number}"
        if not isinstance(entry, dict):
            notes.append(f"{where}: not an object; ignored")
            continue
        operator = entry.get("operator")
        reason = entry.get("reason")
        original = entry.get("original")
        line = entry.get("line")
        mutated = entry.get("mutated")
        if not isinstance(operator, str) or not operator.strip():
            notes.append(f'{where}: no "operator"; ignored')
            continue
        if not isinstance(reason, str) or not reason.strip():
            notes.append(
                f'{where}: no "reason" -- say why no test can kill it; ignored'
            )
            continue
        if not isinstance(line, int) or isinstance(line, bool):
            line = None
        if not isinstance(original, str) or not original.strip():
            original = None
        if line is None and original is None:
            notes.append(f'{where}: needs "original", "line" or both; ignored')
            continue
        declarations.append(
            Declaration(
                operator=operator.strip(),
                reason=reason.strip(),
                original=original,
                line=line,
                mutated=mutated if isinstance(mutated, str) else None,
            )
        )
    return declarations, notes


def match_declarations(
    mutants: list[Mutant], declarations: list[Declaration]
) -> tuple[dict[int, str], list[str]]:
    """Mutant index -> reason for every mutant a declaration names, and a
    note per declaration that names none."""
    matched: dict[int, str] = {}
    notes: list[str] = []
    for declaration in declarations:
        candidates = [
            index
            for index, mutant in enumerate(mutants)
            if mutant.operator == declaration.operator
            and (
                declaration.original is None
                or _code(mutant.original) == _squash(declaration.original)
            )
            and (
                declaration.mutated is None
                or _code(mutant.mutated) == _squash(declaration.mutated)
            )
        ]
        if declaration.line is not None:
            on_line = [i for i in candidates if mutants[i].line == declaration.line]
            # The statement moved: `original` still names it, so follow it
            # rather than lose the declaration -- but only when that is
            # unambiguous.
            if on_line or declaration.original is None or len(candidates) != 1:
                candidates = on_line
        if not candidates:
            notes.append(
                f"declared equivalent {declaration.describe()} matches no "
                "generated mutant (was the statement edited or removed?) -- "
                "update or drop that entry"
            )
            continue
        for index in candidates:
            matched.setdefault(index, declaration.reason)
    return matched, notes
