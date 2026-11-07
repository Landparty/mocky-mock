"""Unit tests for `dsl.fixture_bundle`: parsing cobol-parser's FixtureBundle
JSON into mockymock-local dataclasses. See
docs/plans/2026-08-02-program-data-generation-implementation.md's Phase 8
and cobol-parser's docs/fixture-bundle-schema.md."""

import json

import pytest

from mockymock.dsl.fixture_bundle import (
    SUPPORTED_BUNDLE_VERSION,
    MalformedBundleError,
    UnsupportedBundleVersionError,
    load_fixture_bundle,
    load_fixture_bundle_file,
    parse_fixture_bundle,
)

MINIMAL_BUNDLE = {
    "bundle_version": 1,
    "program_name": "DOCEX",
    "seed": 7,
    "scenarios": [
        {
            "name": "happy path",
            "intent": "layout-valid values for every boundary",
            "entry": "MAIN-PARA",
            "fixtures": [
                {
                    "category": "READ",
                    "key": "ORDER-FILE",
                    "paragraph": "MAIN-PARA",
                    "line": 22,
                    "direction": "IN",
                    "layout": [
                        {
                            "name": "ORDER-QTY",
                            "column": "ORDER-QTY",
                            "qualified_name": "ORDER-RECORD.ORDER-QTY",
                            "level": 5,
                            "picture": "9(3)",
                            "usage": "DISPLAY",
                            "category": "numeric",
                            "size": 3,
                            "integer_digits": 3,
                            "decimal_digits": 0,
                            "is_signed": False,
                            "value_clause": None,
                            "condition_values": [],
                            "subscripts": [],
                            "redefines": None,
                        }
                    ],
                    "sequence": [{"ORDER-QTY": "50"}],
                    "terminal": {"WS-ORDER-STATUS": "10"},
                    "status": {"WS-ORDER-STATUS": "00"},
                    "provenance": "picture-random",
                    "unresolved": [],
                }
            ],
            "expectations": [
                {
                    "kind": "call_count",
                    "ref": "READ:ORDER-FILE",
                    "value": 2,
                    "note": "derived from this scenario's own generated sequence length",
                }
            ],
            "unconstrained": [],
        }
    ],
    "layouts": {
        "ORDER-RECORD": [
            {
                "name": "ORDER-QTY",
                "column": "ORDER-QTY",
                "qualified_name": "ORDER-RECORD.ORDER-QTY",
                "level": 5,
                "picture": "9(3)",
                "usage": "DISPLAY",
                "category": "numeric",
                "size": 3,
                "integer_digits": 3,
                "decimal_digits": 0,
                "is_signed": False,
                "value_clause": None,
                "condition_values": [],
                "subscripts": [],
                "redefines": None,
            }
        ]
    },
    "coverage": {
        "total_boundaries": 1,
        "resolved_boundaries": 1,
        "unresolved_boundaries": 0,
    },
    "unresolved": [],
    "scenario_coverage": None,
}


def test_loads_top_level_fields():
    bundle = load_fixture_bundle(MINIMAL_BUNDLE)
    assert bundle.bundle_version == 1
    assert bundle.program_name == "DOCEX"
    assert bundle.seed == 7
    assert len(bundle.scenarios) == 1
    assert bundle.coverage == {
        "total_boundaries": 1,
        "resolved_boundaries": 1,
        "unresolved_boundaries": 0,
    }
    assert bundle.scenario_coverage is None


def test_loads_scenario_fields():
    scenario = load_fixture_bundle(MINIMAL_BUNDLE).scenarios[0]
    assert scenario.name == "happy path"
    assert scenario.entry == "MAIN-PARA"
    assert len(scenario.fixtures) == 1
    assert len(scenario.expectations) == 1
    assert scenario.unconstrained == []


def test_loads_fixture_fields():
    fixture = load_fixture_bundle(MINIMAL_BUNDLE).scenarios[0].fixtures[0]
    assert fixture.category == "READ"
    assert fixture.key == "ORDER-FILE"
    assert fixture.direction == "IN"
    assert fixture.sequence == [{"ORDER-QTY": "50"}]
    assert fixture.terminal == {"WS-ORDER-STATUS": "10"}
    assert fixture.status == {"WS-ORDER-STATUS": "00"}
    assert len(fixture.layout) == 1
    assert fixture.layout[0].name == "ORDER-QTY"
    assert fixture.layout[0].category == "numeric"


def test_loads_expectation_fields():
    expectation = load_fixture_bundle(MINIMAL_BUNDLE).scenarios[0].expectations[0]
    assert expectation.kind == "call_count"
    assert expectation.ref == "READ:ORDER-FILE"
    assert expectation.value == 2
    assert "sequence length" in expectation.note


def test_loads_layouts_map():
    bundle = load_fixture_bundle(MINIMAL_BUNDLE)
    assert "ORDER-RECORD" in bundle.layouts
    assert bundle.layouts["ORDER-RECORD"][0].name == "ORDER-QTY"


def test_unsupported_bundle_version_raises():
    bad = dict(MINIMAL_BUNDLE, bundle_version=2)
    with pytest.raises(UnsupportedBundleVersionError, match="2"):
        load_fixture_bundle(bad)


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_bundle_version_equal_to_one_but_not_the_integer_1_raises(version):
    """JSON `true` and `1.0` compare equal to 1 in Python; the loader used
    to accept both (and carry `True`/`1.0` into `bundle_version`)."""
    bad = dict(MINIMAL_BUNDLE, bundle_version=version)
    with pytest.raises(UnsupportedBundleVersionError):
        load_fixture_bundle(bad)
    with pytest.raises(UnsupportedBundleVersionError):
        parse_fixture_bundle(json.dumps(bad))


def test_missing_bundle_version_raises():
    bad = dict(MINIMAL_BUNDLE)
    del bad["bundle_version"]
    with pytest.raises(UnsupportedBundleVersionError):
        load_fixture_bundle(bad)


def test_supported_bundle_version_constant_matches_current_schema():
    assert SUPPORTED_BUNDLE_VERSION == 1


# 2026-08-12 audit Finding 15: every required-field access was a bare
# data["key"], so a right-versioned but otherwise malformed bundle raised a
# raw KeyError (and non-JSON text a raw JSONDecodeError) with no typed-error
# contract at all -- masked only by the one CLI call site's blanket
# `except Exception`. Any other caller got the traceback.


def test_missing_required_top_level_key_raises_malformed():
    bad = dict(MINIMAL_BUNDLE)
    del bad["seed"]
    with pytest.raises(MalformedBundleError, match="seed"):
        load_fixture_bundle(bad)


def test_scenario_missing_required_key_raises_malformed():
    bad = dict(MINIMAL_BUNDLE, scenarios=[{"entry": "MAIN-PARA"}])
    with pytest.raises(MalformedBundleError, match="name"):
        load_fixture_bundle(bad)


def test_fixture_missing_required_key_raises_malformed():
    bad = dict(
        MINIMAL_BUNDLE,
        scenarios=[{"name": "s", "fixtures": [{"category": "CALL", "key": "X"}]}],
    )
    with pytest.raises(MalformedBundleError, match="direction"):
        load_fixture_bundle(bad)


def test_invalid_json_text_raises_malformed():
    with pytest.raises(MalformedBundleError, match="not valid JSON"):
        parse_fixture_bundle("{not json")


def test_non_object_json_raises_malformed():
    with pytest.raises(MalformedBundleError):
        parse_fixture_bundle('["a", "list"]')


@pytest.mark.parametrize("bad", [["a", "list"], "a string", None, 42])
def test_load_fixture_bundle_rejects_non_dict_directly(bad):
    """`parse_fixture_bundle` guards non-dict JSON before ever calling
    `load_fixture_bundle`, but `load_fixture_bundle` is itself a public
    function (cli/main.py's --with-data path calls it directly with a
    cobolparser-produced dict) -- a caller that skips that guard and hands
    it a list/str/None/int must still get MalformedBundleError, not the
    raw AttributeError `data.get(...)` would otherwise raise before the
    function's own try/except even starts."""
    with pytest.raises(MalformedBundleError, match="JSON object"):
        load_fixture_bundle(bad)


def test_parse_fixture_bundle_from_json_text():
    bundle = parse_fixture_bundle(json.dumps(MINIMAL_BUNDLE))
    assert bundle.program_name == "DOCEX"


def test_load_fixture_bundle_file(tmp_path):
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
    bundle = load_fixture_bundle_file(path)
    assert bundle.program_name == "DOCEX"


def test_null_program_name_is_preserved():
    bundle = load_fixture_bundle(dict(MINIMAL_BUNDLE, program_name=None))
    assert bundle.program_name is None


def test_missing_optional_fields_default_sensibly():
    """A future additive key mockymock doesn't know about yet must not
    break parsing (see the schema doc's "consumer only reads keys it
    knows about" compatibility policy) -- and conversely, an OLDER/minimal
    bundle missing an optional key (e.g. no `unresolved` list at the
    fixture level) must not crash either."""
    minimal_fixture = {
        "category": "OPEN",
        "key": "INV-FILE",
        "paragraph": "MAIN-PARA",
        "line": 10,
        "direction": "STATUS_ONLY",
    }
    bundle_data = dict(MINIMAL_BUNDLE)
    bundle_data["scenarios"] = [
        {
            "name": "happy path",
            "entry": "MAIN-PARA",
            "fixtures": [minimal_fixture],
            "expectations": [],
        }
    ]
    bundle = load_fixture_bundle(bundle_data)
    fixture = bundle.scenarios[0].fixtures[0]
    assert fixture.layout == []
    assert fixture.sequence == []
    assert fixture.terminal is None
    assert fixture.status == {}
    assert fixture.unresolved == []


# Regression: bug hunt round 11.


# --- fixture bundle: non-object rows -----------------------------------------


@pytest.mark.parametrize("row", ["abc", "AB", ["A", "1"]])
def test_fixture_bundle_non_object_sequence_row_is_a_typed_error(row):
    data = {
        "bundle_version": 1,
        "seed": 1,
        "scenarios": [
            {
                "name": "s",
                "fixtures": [
                    {
                        "category": "READ",
                        "key": "F",
                        "direction": "IN",
                        "sequence": [row],
                    }
                ],
            }
        ],
    }
    with pytest.raises(MalformedBundleError):
        load_fixture_bundle(data)
