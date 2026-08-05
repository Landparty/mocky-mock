"""Pin the exact FixtureBundle surface mockymock consumes (Phase 8)."""

import json

from cobolparser.generators import DataGeneratorOptions, ProgramFixtureGenerator

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BSMOKE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-QTY PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-QTY
           DISPLAY WS-QTY
           GOBACK.
"""


def test_bundle_shape_is_what_with_data_consumes(tmp_path):
    cbl = tmp_path / "BSMOKE.cbl"
    cbl.write_text(SOURCE, encoding="utf-8")
    bundle = ProgramFixtureGenerator(
        DataGeneratorOptions(rows=3)
    ).generate_with_scenarios_from_file(str(cbl), mode="happy", seed=7)
    d = bundle.to_dict()
    assert json.loads(bundle.to_json()) == d
    assert d["bundle_version"] == 1
    assert d["program_name"] == "BSMOKE"
    assert d["seed"] == 7
    scenario = d["scenarios"][0]
    fixture = next(f for f in scenario["fixtures"] if f["category"] == "ACCEPT")
    assert fixture["key"] == "WS-QTY"
    assert fixture["direction"] == "IN"
    assert len(fixture["sequence"]) == 1
    assert set(fixture["sequence"][0]) == {"WS-QTY"}
    kinds = {e["kind"] for e in scenario["expectations"]}
    assert "call_count" in kinds
