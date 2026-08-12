"""Lightweight loader for cobolparser's FixtureBundle JSON -- the
`gen-fixtures` program-scoped test-data initiative's Phase 3/5/6/7
deliverable. Backs `mockymock generate --with-data`.

mockymock never imports cobolparser's bundle *classes* -- only the JSON
shape, parsed here into its own plain dataclasses. That keeps the
independently-checkable-attributes principle from `.okf/analysis.md`
intact: the contract between the two repos is the serialized form, not a
shared Python type either side could drift out of sync with silently. See
cobol-parser's `docs/fixture-bundle-schema.md` for the authoritative shape
this module mirrors, and
docs/plans/2026-08-02-program-data-generation-implementation.md's Phase 8.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Bumped only on a breaking change to the bundle shape (a key removed, a
#: key's type/meaning changed under an unchanged name) -- see the schema
#: doc's "Versioning and compatibility policy". This loader fails closed
#: on anything else rather than guess at a schema that changed underneath
#: it.
SUPPORTED_BUNDLE_VERSION = 1


class UnsupportedBundleVersionError(Exception):
    """Raised when a bundle's `bundle_version` isn't one this loader knows
    how to read."""


class MalformedBundleError(Exception):
    """Raised when bundle text/data is structurally broken -- not JSON, not
    an object, or missing a required key -- as a typed error instead of the
    raw KeyError/JSONDecodeError tracebacks these cases used to escape as
    (2026-08-12 audit Finding 15)."""


@dataclass
class FieldSpec:
    name: str
    column: str
    qualified_name: str
    level: int
    picture: str | None
    usage: str | None
    category: str
    size: int
    integer_digits: int
    decimal_digits: int
    is_signed: bool
    value_clause: str | None = None
    condition_values: list[str] = field(default_factory=list)
    subscripts: list[int] = field(default_factory=list)
    redefines: str | None = None


@dataclass
class BoundaryFixture:
    category: str
    key: str
    paragraph: str | None
    line: int | None
    direction: str  # IN | OUT | BIDIRECTIONAL | STATUS_ONLY
    layout: list[FieldSpec] = field(default_factory=list)
    sequence: list[dict[str, str]] = field(default_factory=list)
    terminal: dict[str, str] | None = None
    status: dict[str, str] = field(default_factory=dict)
    provenance: str = "picture-random"
    unresolved: list[str] = field(default_factory=list)


@dataclass
class Expectation:
    kind: str  # call_count | field_equals | stub
    ref: str
    value: Any = None
    note: str | None = None


@dataclass
class Scenario:
    name: str
    intent: str = ""
    entry: str | None = None
    fixtures: list[BoundaryFixture] = field(default_factory=list)
    expectations: list[Expectation] = field(default_factory=list)
    unconstrained: list[str] = field(default_factory=list)


@dataclass
class FixtureBundle:
    bundle_version: int
    program_name: str | None
    seed: int
    scenarios: list[Scenario] = field(default_factory=list)
    layouts: dict[str, list[FieldSpec]] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    scenario_coverage: dict[str, Any] | None = None


def _load_field_spec(data: dict[str, Any]) -> FieldSpec:
    return FieldSpec(
        name=data["name"],
        column=data["column"],
        qualified_name=data["qualified_name"],
        level=data["level"],
        picture=data.get("picture"),
        usage=data.get("usage"),
        category=data["category"],
        size=data["size"],
        integer_digits=data["integer_digits"],
        decimal_digits=data["decimal_digits"],
        is_signed=data["is_signed"],
        value_clause=data.get("value_clause"),
        condition_values=list(data.get("condition_values") or []),
        subscripts=list(data.get("subscripts") or []),
        redefines=data.get("redefines"),
    )


def _load_fixture(data: dict[str, Any]) -> BoundaryFixture:
    return BoundaryFixture(
        category=data["category"],
        key=data["key"],
        paragraph=data.get("paragraph"),
        line=data.get("line"),
        direction=data["direction"],
        layout=[_load_field_spec(f) for f in data.get("layout") or []],
        sequence=[dict(row) for row in data.get("sequence") or []],
        terminal=data.get("terminal"),
        status=dict(data.get("status") or {}),
        provenance=data.get("provenance", "picture-random"),
        unresolved=list(data.get("unresolved") or []),
    )


def _load_expectation(data: dict[str, Any]) -> Expectation:
    return Expectation(
        kind=data["kind"],
        ref=data["ref"],
        value=data.get("value"),
        note=data.get("note"),
    )


def _load_scenario(data: dict[str, Any]) -> Scenario:
    return Scenario(
        name=data["name"],
        intent=data.get("intent", ""),
        entry=data.get("entry"),
        fixtures=[_load_fixture(f) for f in data.get("fixtures") or []],
        expectations=[_load_expectation(e) for e in data.get("expectations") or []],
        unconstrained=list(data.get("unconstrained") or []),
    )


def load_fixture_bundle(data: dict[str, Any]) -> FixtureBundle:
    """Parse an already-decoded bundle dict (e.g. `json.loads(text)`) into
    a `FixtureBundle` of mockymock-local dataclasses.

    Raises `UnsupportedBundleVersionError` on an unrecognized
    `bundle_version` -- fails closed rather than guessing at a schema that
    changed underneath it (see cobol-parser's fixture-bundle-schema.md
    "Versioning and compatibility policy": a breaking change always bumps
    this field).
    """
    version = data.get("bundle_version")
    if version != SUPPORTED_BUNDLE_VERSION:
        raise UnsupportedBundleVersionError(
            f"unsupported fixture bundle_version {version!r} -- this "
            f"mockymock only understands {SUPPORTED_BUNDLE_VERSION!r}. "
            f"Regenerate the bundle with a compatible cobol-parser, or "
            f"upgrade mockymock."
        )
    try:
        return FixtureBundle(
            bundle_version=version,
            program_name=data.get("program_name"),
            seed=data["seed"],
            scenarios=[_load_scenario(s) for s in data.get("scenarios") or []],
            layouts={
                name: [_load_field_spec(f) for f in fields]
                for name, fields in (data.get("layouts") or {}).items()
            },
            coverage=dict(data.get("coverage") or {}),
            unresolved=list(data.get("unresolved") or []),
            scenario_coverage=data.get("scenario_coverage"),
        )
    except KeyError as exc:
        raise MalformedBundleError(
            f"fixture bundle is missing required key {exc.args[0]!r}"
        ) from exc
    except (TypeError, AttributeError) as exc:
        raise MalformedBundleError(f"malformed fixture bundle: {exc}") from exc


def parse_fixture_bundle(text: str) -> FixtureBundle:
    """Parse raw bundle JSON text (e.g. cobolparser's
    `FixtureBundle.to_json()` output, or a `gen-fixtures --format json`
    file) into a `FixtureBundle`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedBundleError(f"fixture bundle is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MalformedBundleError(
            f"fixture bundle must be a JSON object, got {type(data).__name__}"
        )
    return load_fixture_bundle(data)


def load_fixture_bundle_file(path: Path) -> FixtureBundle:
    """Read and parse a bundle JSON file (`--fixtures bundle.json`)."""
    return parse_fixture_bundle(path.read_text(encoding="utf-8"))
