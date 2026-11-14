"""CALL arguments the fixture bundle could not lay out, filled from the
program's own DATA DIVISION.

cobol-parser's `ProgramFixtureGenerator` resolves a CALL's `USING`
arguments through its layout index, which knows elementary fields and
01/77 records only. An argument naming a group below level 01
(`CALL "X" USING WS-PARMS` with `05 WS-PARMS` under `01 WS-AREA`) or one
element of a table (`WS-CODE(WS-I)`) comes back as an `unresolved` note
and no value, so the scaffolded mock left those bytes as whatever the
program had in them. `fill_call_arguments` gives the bundle the fields the
generator would have produced for them:

- a group or unsubscripted item: each elementary field under it, the same
  `flatten_record` walk the generator itself uses for an 01 record;
- a single-subscript table reference: the fields of one occurrence, MOVEd
  through the argument's own subscript (`MOVE ... TO WS-CODE(WS-I)`), which
  inside the mock body is the very element the CALL passes.

An argument that is not a data item at all (a literal, a figurative
constant, `OMITTED`, `LENGTH OF`, `ADDRESS OF`, `FUNCTION ...`) has no
value to generate: its note is dropped, as cobol-parser 3.1 already does.
A reference-modified argument (`WS-KEY(1:4)`), a multi-subscript one, or a
name the walk finds more than once keeps its note -- no value rather than a
guessed one. An argument only the program supplies (direction OUT) gets the
same `stub` expectation the generator writes for a resolved one.

Best effort, like `entry_parameters.add_entry_parameters`: any failure
leaves the bundle unchanged.
"""

from __future__ import annotations

import random
import re
import zlib
from dataclasses import dataclass, field
from typing import Any

#: cobol-parser's per-argument note (3.0 wording, then 3.1's
#: subscripted/reference-modified one).
_ARG_NOTE_RE = re.compile(
    r"^(?P<category>CALL|DYNCALL) (?P<key>.+?): argument (?P<arg>.+?) "
    r"(?:not resolvable in layout index|is subscripted or reference-modified\b.*)$"
)

#: Arguments that name no data item: nothing for a mock to set.
_NON_DATA_PREFIXES = ("OMITTED", "LENGTH OF ", "ADDRESS OF ", "FUNCTION ")
_FIGURATIVES = frozenset(
    {
        "ZERO",
        "ZEROS",
        "ZEROES",
        "SPACE",
        "SPACES",
        "LOW-VALUE",
        "LOW-VALUES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "QUOTE",
        "QUOTES",
        "NULL",
        "NULLS",
    }
)

_SUBSCRIPT_RE = re.compile(r"^(?P<name>[^()]+?)\s*\(\s*(?P<sub>[^()]*?)\s*\)$")
_QUALIFIER_RE = re.compile(r"\s+(?:OF|IN)\s+", re.IGNORECASE)
_WORD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass
class _Argument:
    """One CALL argument as cobol-parser's boundary inventory reports it,
    merged over every site of the same (category, key)."""

    name: str
    directions: set[str] = field(default_factory=set)
    provenance: str = ""


def is_non_data_argument(text: str) -> bool:
    """True for an argument that names no data item."""
    upper = text.strip().upper()
    if not upper:
        return True
    if upper[0] in "'\"" or upper[0].isdigit() or upper[0] in "+-.":
        return True
    if upper in _FIGURATIVES or upper.startswith("ALL "):
        return True
    return upper == "OMITTED" or upper.startswith(_NON_DATA_PREFIXES)


def fill_call_arguments(
    bundle: dict[str, Any],
    program_path: str,
    copybook_paths: list[str] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Fill the CALL / DYNCALL arguments `bundle` (a `FixtureBundle.to_dict()`)
    could not lay out. Returns the bundle and one line per argument filled,
    for the command to report."""
    notes = _argument_notes(bundle)
    if not notes:
        return bundle, []
    try:
        index, arguments = _call_arguments(program_path, copybook_paths)
    except Exception:  # noqa: BLE001 -- an unreadable program: bundle unchanged
        return bundle, []
    seed = int(bundle.get("seed") or 0)
    dropped: set[str] = set()
    reworded: dict[str, str] = {}
    filled: list[str] = []
    for note, (category, key, arg_text) in notes.items():
        if is_non_data_argument(arg_text):
            dropped.add(note)
            continue
        argument = arguments.get((category, key), {}).get(_normal(arg_text))
        if argument is None:
            continue
        if argument.directions <= {"OUT"}:
            _add_stub(bundle, category, key, argument, outbound=True)
            dropped.add(note)
            continue
        try:
            specs = argument_fields(index, arg_text)
        except Exception:  # noqa: BLE001 -- one odd argument never fails the rest
            specs = None
        if specs == []:
            # Found, but nothing a MOVE can set: say so, not "not
            # resolvable" (a packed or binary all-FILLER group).
            reworded[note] = (
                f"{category} {key}: argument {arg_text} holds only FILLER "
                "fields with no character image (binary or packed), so no "
                "value is generated for it"
            )
            continue
        if not specs:
            continue
        direction = (
            "BIDIRECTIONAL"
            if "BIDIRECTIONAL" in argument.directions or len(argument.directions) > 1
            else next(iter(argument.directions), "BIDIRECTIONAL")
        )
        if _add_fields(bundle, category, key, arg_text, specs, seed, direction):
            if "BIDIRECTIONAL" in argument.directions:
                _add_stub(bundle, category, key, argument, outbound=False)
            dropped.add(note)
            filled.append(
                f"{category} {key}: argument {arg_text} filled from the "
                "program's DATA DIVISION"
            )
    _drop_notes(bundle, dropped)
    _reword_notes(bundle, reworded)
    return bundle, filled


def _argument_notes(bundle: dict[str, Any]) -> dict[str, tuple[str, str, str]]:
    """Every per-argument note in the bundle, bundle-level or per-fixture."""
    found: dict[str, tuple[str, str, str]] = {}
    texts = list(bundle.get("unresolved") or [])
    for scenario in bundle.get("scenarios") or []:
        for fixture in scenario.get("fixtures") or []:
            texts.extend(fixture.get("unresolved") or [])
    for text in texts:
        match = _ARG_NOTE_RE.match(str(text))
        if match:
            found[str(text)] = (
                match.group("category"),
                match.group("key"),
                match.group("arg"),
            )
    return found


def _normal(text: str) -> str:
    return " ".join(text.upper().split())


def _call_arguments(
    program_path: str, copybook_paths: list[str] | None
) -> tuple[Any, dict[tuple[str, str], dict[str, _Argument]]]:
    from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
    from cobolparser.generators.data import ProgramLayoutIndex

    index = ProgramLayoutIndex.from_file(program_path, copybook_paths=copybook_paths)
    if index.ast is None:
        raise ValueError(f"{program_path}: no program to read")
    report = BoundaryInventoryAnalyzer().analyze(index.ast, index)
    arguments: dict[tuple[str, str], dict[str, _Argument]] = {}
    for boundary in report.boundaries:
        category = str(getattr(boundary.ref.category, "value", boundary.ref.category))
        if category not in ("CALL", "DYNCALL"):
            continue
        by_name = arguments.setdefault((category, str(boundary.ref.key)), {})
        for arg in boundary.call_args or []:
            entry = by_name.setdefault(_normal(arg.name), _Argument(arg.name))
            entry.directions.add(str(arg.direction))
            entry.provenance = entry.provenance or str(arg.provenance or "")
    return index, arguments


def argument_fields(index: Any, text: str) -> list[Any] | None:
    """The cobol-parser `FieldSpec`s a mock sets for CALL argument `text`,
    with `column` the reference a MOVE writes and `qualified_name` the
    item's full path; None when the argument cannot be laid out exactly."""
    from cobolparser.generators.data import DataGeneratorOptions, flatten_record

    reference = text.strip()
    subscript: str | None = None
    match = _SUBSCRIPT_RE.match(reference)
    if match:
        subscript = match.group("sub").strip()
        reference = match.group("name").strip()
        if not _WORD_RE.match(subscript):
            # reference modification (`1:4`), several subscripts, or an
            # expression: not one whole element.
            return None
    elif "(" in reference:
        return None
    parts = [part.strip().upper() for part in _QUALIFIER_RE.split(reference)]
    if not all(_WORD_RE.match(part) for part in parts):
        return None
    found = _find_item(index.ast, parts[0], parts[1:])
    if found is None:
        return None
    item, ancestors = found
    if any(_occurs(a) for a in ancestors):
        return None  # needs more subscripts than one
    if (subscript is not None) != _occurs(item):
        return None
    prefix = tuple(str(a.name).upper() for a in ancestors)
    specs = []
    for spec in flatten_record(item, DataGeneratorOptions()):
        if subscript is not None:
            if list(spec.subscripts) != [1]:
                if len(spec.subscripts) != 1:
                    return None  # a table nested inside the element
                continue  # another occurrence: the subscript picks one
            spec.column = f"{spec.name}({subscript})"
        spec.path = (*prefix, *spec.path)
        specs.append(spec)
    if not specs:
        opaque = _opaque_group_spec(item, prefix, subscript)
        if opaque is not None:
            specs.append(opaque)
    return specs


#: The FILLER fields an opaque group spec stands for (`_opaque_group_spec`),
#: kept on the spec so `_add_fields` can build its value field by field.
_OPAQUE_PARTS = "_mockymock_opaque_parts"


def _opaque_group_spec(item: Any, prefix: tuple[str, ...], subscript: str | None):
    """One alphanumeric spec for a group whose every field is FILLER
    (`01 WSSSA-PDS205RU. 05 FILLER PIC X(5). 05 FILLER PIC 9(4).`), which
    `flatten_record` leaves with no field at all. The group is set by its
    own name, as one value the size of the group: no MOVE can name a
    FILLER. None for an elementary item, or a group holding a field that
    is not DISPLAY (a binary or packed FILLER has no character image to
    write)."""
    from dataclasses import replace

    from cobolparser.generators.data import DataGeneratorOptions, flatten_record
    from cobolparser.layout.fields import FieldCategory

    if not list(getattr(item, "children", None) or []):
        return None
    parts = list(flatten_record(item, DataGeneratorOptions(include_filler=True)))
    if not parts or any(
        str(part.usage).upper() != "DISPLAY"
        or part.storage_size != part.size
        or (subscript is not None and len(part.subscripts) > 1)
        for part in parts
    ):
        return None
    if subscript is not None:
        parts = [part for part in parts if list(part.subscripts) in ([], [1])]
    total = sum(part.size for part in parts)
    name = str(item.name).upper()
    spec = replace(
        parts[0],
        name=name,
        path=(*prefix, name),
        column=f"{name}({subscript})" if subscript is not None else name,
        level=int(getattr(item, "level", parts[0].level) or parts[0].level),
        picture=f"X({total})",
        category=FieldCategory.ALPHANUMERIC,
        size=total,
        integer_digits=0,
        decimal_digits=0,
        is_signed=False,
        value_clause=None,
        condition_values=[],
        subscripts=(),
        is_filler=False,
        sign_clause=None,
        blank_when_zero=False,
        justified=False,
    )
    setattr(spec, _OPAQUE_PARTS, parts)
    return spec


def _opaque_value(spec: Any, factory: Any, row_number: int) -> str | None:
    """The value of an opaque group spec: each FILLER's own generated
    characters, numeric ones zero (a valid DISPLAY number of any
    PICTURE), laid end to end. None for any other spec."""
    from dataclasses import replace

    parts = getattr(spec, _OPAQUE_PARTS, None)
    if parts is None:
        return None
    pieces = []
    for part in parts:
        if part.category in ("numeric", "numeric-edited"):
            pieces.append("0" * part.size)
        else:
            # A FILLER generates as blanks: draw it as a named field.
            named = replace(part, is_filler=False, name=spec.name)
            text = str(factory.value_for(named, row_number))
            pieces.append(text[: part.size].ljust(part.size))
    return "".join(pieces)


def _occurs(item: Any) -> bool:
    return getattr(item, "occurs_clause", None) is not None


def _find_item(
    ast: Any, name: str, qualifiers: list[str]
) -> tuple[Any, list[Any]] | None:
    """The one data item named `name` whose ancestors hold every qualifier
    (innermost first, as `A OF B OF C` names them), with its ancestors from
    the 01 down; None when there is none or more than one."""
    from cobolparser.models import CobolDataItem

    division = ast.get_division("DATA") if ast is not None else None
    if division is None:
        return None
    matches: list[tuple[Any, list[Any]]] = []

    def walk(items: list[Any], ancestors: list[Any]) -> None:
        for item in items:
            if not isinstance(item, CobolDataItem):
                continue
            if str(item.name or "").upper() == name and _qualified_by(
                ancestors, qualifiers
            ):
                matches.append((item, list(ancestors)))
            walk(list(item.children or []), [*ancestors, item])

    for section in division._sections.values():
        walk(list(getattr(section, "data_items", None) or []), [])
    return matches[0] if len(matches) == 1 else None


def _qualified_by(ancestors: list[Any], qualifiers: list[str]) -> bool:
    names = [str(a.name or "").upper() for a in reversed(ancestors)]
    position = 0
    for qualifier in qualifiers:
        try:
            position = names.index(qualifier, position) + 1
        except ValueError:
            return False
    return True


def _add_fields(
    bundle: dict[str, Any],
    category: str,
    key: str,
    arg_text: str,
    specs: list[Any],
    seed: int,
    direction: str = "BIDIRECTIONAL",
) -> bool:
    """Add `specs` (and a generated value per scenario) to every scenario's
    fixture for (category, key), creating the fixture where the generator
    made none. False when the fields would collide with ones already laid
    out -- the same item passed twice, or overlapping another argument."""
    from cobolparser.generators.data import DataGeneratorOptions, ValueFactory

    scenarios = bundle.get("scenarios") or []
    for scenario in scenarios:
        fixture = _fixture(scenario, category, key)
        if fixture is None:
            continue
        taken = {spec["column"] for spec in fixture.get("layout") or []}
        names = {spec["qualified_name"] for spec in fixture.get("layout") or []}
        if any(s.column in taken or s.qualified_name in names for s in specs):
            return False
    layout = [spec.to_dict() for spec in specs]
    for scenario in scenarios:
        name = str(scenario.get("name") or "")
        rng = random.Random(
            zlib.crc32(f"{seed}:{name}:{category}:{key}:{arg_text}".encode())
        )
        factory = ValueFactory(rng, DataGeneratorOptions())
        fixture = _fixture(scenario, category, key)
        if fixture is None:
            fixture = {
                "category": category,
                "key": key,
                "paragraph": None,
                "line": None,
                "direction": direction,
                "layout": [],
                "sequence": [{}],
                "terminal": None,
                "status": {},
                "provenance": "picture-random",
                "unresolved": [],
            }
            scenario.setdefault("fixtures", []).append(fixture)
        # A CALL fixture's direction is its arguments' (the schema has no
        # empty value; older cobol-parser left it ""): one more argument
        # going another way makes it BIDIRECTIONAL.
        current = fixture.get("direction") or ""
        if not current:
            fixture["direction"] = direction
        elif current != direction:
            fixture["direction"] = "BIDIRECTIONAL"
        fixture.setdefault("layout", []).extend(layout)
        rows = fixture.setdefault("sequence", [])
        if not rows:
            rows.append({})
        for row_number, row in enumerate(rows):
            for spec in specs:
                opaque = _opaque_value(spec, factory, row_number)
                row[spec.column] = (
                    opaque
                    if opaque is not None
                    else factory.value_for(spec, row_number)
                )
    return True


def _fixture(
    scenario: dict[str, Any], category: str, key: str
) -> dict[str, Any] | None:
    for fixture in scenario.get("fixtures") or []:
        if fixture.get("category") == category and fixture.get("key") == key:
            return fixture
    return None


def _add_stub(
    bundle: dict[str, Any],
    category: str,
    key: str,
    argument: _Argument,
    *,
    outbound: bool,
) -> None:
    """The `stub` expectation cobol-parser writes for a resolved argument."""
    provenance = argument.provenance or "assumed-bidirectional"
    note = (
        "value supplied by the program under test, not mock-generated "
        f"(provenance={provenance})"
        if outbound
        else "bidirectional: the OUT aspect (value the caller supplies) is "
        f"not asserted in v1 (provenance={provenance})"
    )
    for scenario in bundle.get("scenarios") or []:
        expectations = scenario.setdefault("expectations", [])
        if any(
            e.get("kind") == "stub" and e.get("ref") == argument.name
            for e in expectations
        ):
            continue
        expectations.append(
            {"kind": "stub", "ref": argument.name, "value": None, "note": note}
        )


def _reword_notes(bundle: dict[str, Any], reworded: dict[str, str]) -> None:
    if not reworded:
        return
    bundle["unresolved"] = [reworded.get(n, n) for n in bundle.get("unresolved") or []]
    for scenario in bundle.get("scenarios") or []:
        for fixture in scenario.get("fixtures") or []:
            fixture["unresolved"] = [
                reworded.get(n, n) for n in fixture.get("unresolved") or []
            ]


def _drop_notes(bundle: dict[str, Any], dropped: set[str]) -> None:
    if not dropped:
        return
    bundle["unresolved"] = [
        n for n in bundle.get("unresolved") or [] if n not in dropped
    ]
    for scenario in bundle.get("scenarios") or []:
        for fixture in scenario.get("fixtures") or []:
            fixture["unresolved"] = [
                n for n in fixture.get("unresolved") or [] if n not in dropped
            ]
