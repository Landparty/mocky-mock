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

import copy
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

#: Every version this loader reads. Version 2 (cobol-parser main) moves each
#: scenario's fixtures into a top-level ``fixtures`` table that scenarios
#: point into by id; it is expanded back into the version 1 shape on load
#: (#461), so everything past the loader sees version 1.
READABLE_BUNDLE_VERSIONS = (1, 2)


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
    #: cobol-parser's own self-verification verdict for this scenario: did
    #: the data it generated actually satisfy the branch the scenario is
    #: named for? `{"status": "verified"|"unverified", "fields": [...],
    #: "gaps": [...]}`, or `None` for a bundle produced before that check
    #: existed (or a happy-path scenario, which targets no branch). Read
    #: defensively -- an older bundle is still a valid v1 bundle.
    verification: dict[str, Any] | None = None
    #: The values a caller passes through the program's own PROCEDURE
    #: DIVISION USING items (category "ENTRY", key = PROGRAM-ID), one row
    #: over their elementary fields; None when the program takes none or
    #: the bundle predates them (issue #275). The scaffold MOVEs the row
    #: into the parameters before its PERFORM.
    entry_parameters: BoundaryFixture | None = None


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


def _object(value: Any, what: str) -> dict[str, Any]:
    """`dict(value)` for a JSON object only. `dict()` of anything else
    either raised a raw ValueError (`"abc"`) that escaped the typed
    MalformedBundleError, or silently built a garbage mapping from a list
    of two-character strings (`["AB"]` -> `{"A": "B"}`)."""
    if not isinstance(value, dict):
        raise MalformedBundleError(
            f"fixture bundle {what} must be a JSON object, got {type(value).__name__}"
        )
    return dict(value)


def _load_fixture(data: dict[str, Any]) -> BoundaryFixture:
    return BoundaryFixture(
        category=data["category"],
        key=data["key"],
        paragraph=data.get("paragraph"),
        line=data.get("line"),
        direction=data["direction"],
        layout=[_load_field_spec(f) for f in data.get("layout") or []],
        sequence=[_object(row, "sequence row") for row in data.get("sequence") or []],
        terminal=data.get("terminal"),
        status=_object(data.get("status") or {}, "fixture status"),
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
        verification=data.get("verification"),
        entry_parameters=(
            _load_fixture(_object(data["entry_parameters"], "entry_parameters"))
            if data.get("entry_parameters") is not None
            else None
        ),
    )


def _check_version(data: Any) -> int:
    """The bundle's `bundle_version`, or a typed error for one this loader
    cannot read."""
    if not isinstance(data, dict):
        raise MalformedBundleError(
            f"fixture bundle must be a JSON object, got {type(data).__name__}"
        )
    version = data.get("bundle_version")
    # `type(...) is int`, not `==` alone: JSON `true` and `1.0` both
    # compare equal to 1 in Python, so a bundle declaring either used to
    # be accepted as version 1 -- and then carried `True`/`1.0` into
    # `FixtureBundle.bundle_version`.
    if type(version) is not int or version not in READABLE_BUNDLE_VERSIONS:
        readable = " or ".join(str(v) for v in READABLE_BUNDLE_VERSIONS)
        raise UnsupportedBundleVersionError(
            f"unsupported fixture bundle_version {version!r} -- this "
            f"mockymock only understands {readable}. "
            f"Regenerate the bundle with a compatible cobol-parser, or "
            f"upgrade mockymock."
        )
    return version


def expand_shared_fixtures(data: dict[str, Any]) -> dict[str, Any]:
    """A copy of bundle dict *data* in the version 1 shape (#461).

    Version 2 lists each scenario's fixtures as ids into a top-level
    ``fixtures`` table; this puts the fixtures back inline. A version 1 dict
    comes back as an equal copy. Raises `UnsupportedBundleVersionError` /
    `MalformedBundleError` like `load_fixture_bundle`, so a caller that walks
    the scenarios before loading (`generate --with-data`) gets the same clear
    refusal instead of an AttributeError.
    """
    version = _check_version(data)
    result = copy.deepcopy(data)
    table = result.pop("fixtures", None)
    if version == 1:
        return result
    if not isinstance(table, dict):
        raise MalformedBundleError(
            "fixture bundle_version 2 needs a top-level 'fixtures' table"
        )
    for scenario in result.get("scenarios") or []:
        ids = scenario.get("fixtures") or [] if isinstance(scenario, dict) else []
        try:
            scenario["fixtures"] = [copy.deepcopy(table[i]) for i in ids]
        except (KeyError, TypeError) as exc:
            raise MalformedBundleError(
                f"fixture bundle names an unknown shared fixture {exc.args[0]!r}"
            ) from exc
    result["bundle_version"] = SUPPORTED_BUNDLE_VERSION
    return result


def bundle_dict(bundle: Any) -> dict[str, Any]:
    """A cobol-parser `FixtureBundle` as a version 1 dict, whatever version
    the installed cobol-parser writes by default (#461)."""
    return expand_shared_fixtures(bundle.to_dict())


def load_fixture_bundle(data: dict[str, Any]) -> FixtureBundle:
    """Parse an already-decoded bundle dict (e.g. `json.loads(text)`) into
    a `FixtureBundle` of mockymock-local dataclasses.

    Raises `UnsupportedBundleVersionError` on an unrecognized
    `bundle_version` -- fails closed rather than guessing at a schema that
    changed underneath it (see cobol-parser's fixture-bundle-schema.md
    "Versioning and compatibility policy": a breaking change always bumps
    this field).

    Raises `MalformedBundleError` for a non-dict `data` too: `data.get(...)`
    below would otherwise raise a raw, untyped AttributeError for a caller
    that skips `parse_fixture_bundle`'s own JSON-object check and hands a
    list/str/None/etc. straight to this function -- exactly the "typed
    error, not a bare traceback" contract this loader promises everywhere
    else (2026-08-12 audit Finding 15 covered every key access already
    inside the try/except below; this one line ran before it, so was
    invisible to that fix).
    """
    if _check_version(data) != SUPPORTED_BUNDLE_VERSION:
        data = expand_shared_fixtures(data)
    version = SUPPORTED_BUNDLE_VERSION
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
