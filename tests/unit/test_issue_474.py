"""Issue #474: an entry-parameter stub for a field under an OCCURS names
its occurrence, and a bare table element is skipped before the driver is
built, so `run --record-expectations` never splices an unsubscripted
DISPLAY."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock.analysis.stub_expectations import (
    scan_stub_expectations,
    skip_unsubscripted_table_stubs,
)
from mockymock.dsl.entry_parameters import (
    _entry_parameter_layout,
    add_entry_parameters,
)
from mockymock.dsl.generator.counts import _expect_name
from mockymock.dsl.parser import parse_cut
from mockymock.report.record_rewrite import table_fields

SUBQ = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBQ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMT            PIC 9(5).
       LINKAGE SECTION.
       01  LK-TAB.
           05  LK-ENT OCCURS 3 TIMES.
               10  LK-AMT    PIC 9(5).
               10  LK-AMT-X  PIC X(2).
       01  LK-TOTAL          PIC 9(7).
       PROCEDURE DIVISION USING LK-TAB LK-TOTAL.
           MOVE 1 TO LK-AMT(2)
           GOBACK.
"""

TABLE = "LK-TAB.LK-ENT.LK-AMT"


def _program(tmp_path):
    path = tmp_path / "SUBQ.cbl"
    path.write_text(SUBQ, encoding="utf-8")
    return str(path)


def test_outputs_name_each_occurrence(tmp_path) -> None:
    layout = _entry_parameter_layout(_program(tmp_path), None)
    assert layout is not None
    assert layout[3] == [f"{TABLE}(1)", f"{TABLE}(2)", f"{TABLE}(3)"]


def test_generated_stub_is_subscripted() -> None:
    assert _expect_name(f"{TABLE}(2)", None) == "LK-AMT(2)"


def test_bare_table_stub_from_cobol_parser_is_replaced(tmp_path) -> None:
    bare = {"kind": "stub", "ref": TABLE, "value": None, "note": "x"}
    other = {"kind": "stub", "ref": "LK-TOTAL", "value": None, "note": "y"}
    bundle = {
        "seed": 1,
        "scenarios": [
            {"name": "s", "entry_parameters": {}, "expectations": [bare, other]}
        ],
    }
    add_entry_parameters(bundle, _program(tmp_path), None)
    refs = [e["ref"] for e in bundle["scenarios"][0]["expectations"]]
    assert TABLE not in refs
    assert "LK-TOTAL" in refs
    assert [r for r in refs if r.startswith(TABLE)] == [
        f"{TABLE}(1)",
        f"{TABLE}(2)",
        f"{TABLE}(3)",
    ]


def test_new_scenario_gets_subscripted_stubs(tmp_path) -> None:
    bundle = {"seed": 1, "scenarios": [{"name": "s", "expectations": []}]}
    add_entry_parameters(bundle, _program(tmp_path), None)
    refs = [e["ref"] for e in bundle["scenarios"][0]["expectations"]]
    assert refs == [f"{TABLE}(1)", f"{TABLE}(2)", f"{TABLE}(3)"]


def test_table_fields() -> None:
    ast = parse_cobol(SUBQ).ast
    assert table_fields(ast) == {"LK-ENT", "LK-AMT", "LK-AMT-X"}


def test_name_also_declared_outside_a_table_is_kept() -> None:
    source = SUBQ.replace("WS-AMT            PIC 9(5)", "LK-AMT-X          PIC X(2)")
    ast = parse_cobol(source).ast
    assert "LK-AMT-X" not in table_fields(ast)


CUT = """\
TESTSUITE "S"

TESTCASE "t"
    PERFORM MAIN-PARA
    *> STUB EXPECT LK-AMT -- returned to the caller of SUBQ
    *> STUB EXPECT LK-AMT(2) -- returned to the caller of SUBQ
    *> STUB EXPECT LK-AMT OF LK-ENT
    *> STUB EXPECT LK-TOTAL
"""


def test_bare_table_stub_is_skipped_before_the_driver() -> None:
    scan = scan_stub_expectations(CUT, parse_cut(CUT))
    result = skip_unsubscripted_table_stubs(scan, {"LK-AMT", "LK-ENT"})
    assert [s.data_name for s in result.stubs] == ["LK-AMT(2)", "LK-TOTAL"]
    assert [s.data_name for s in result.skipped] == ["LK-AMT", "LK-AMT OF LK-ENT"]
    assert "OCCURS" in result.skipped[0].reason
