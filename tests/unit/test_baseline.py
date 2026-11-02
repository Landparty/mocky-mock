"""Behaviour baselines: the splice side (`splicer.behaviour`), the stdout
markers (`report.results`) and the comparison (`report.baseline`).
docs/2026-11-01-baseline-design.md."""

import json

import pytest
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.call import CallStatement

from mockymock.analysis.mock_surface import BoundarySite
from mockymock.dsl.model import MockCategory, MockDirective, MockTestCase, MockTestSuite
from mockymock.report.baseline import (
    BaselineError,
    build_baseline,
    compare,
    format_comparison,
    load_baseline,
    write_baseline,
)
from mockymock.report.results import parse_stdout
from mockymock.splicer.behaviour import (
    HEXDUMP_PROGRAM,
    LENGTH_DECLARATION,
    cics_data_items,
    cursor_host_variables,
    hexdump_program,
    opened_cursor,
    payload_names,
    returned_items,
    site_lines,
    sql_host_variables,
)
from mockymock.splicer.driver import build_driver
from mockymock.splicer.injector import build_site_dispatch
from mockymock.splicer.naming import TallyRegistry


def _call_site(using, key="DISCRATE"):
    statement = CallStatement(SourceLocation(line=10, column=1))
    statement.set_called_program(key)
    for name in using:
        statement.add_using_parameter(name)
    return BoundarySite(
        category=MockCategory.CALL,
        label="CALL",
        keys=(key,),
        match_text=None,
        paragraph_name="P",
        line=10,
        nested=False,
        statement=statement,
    )


def _suite(directive: MockDirective) -> MockTestSuite:
    case = MockTestCase(name="one")
    case.mocks.append(directive)
    return MockTestSuite(name="S", test_cases=[case])


# --- splice -----------------------------------------------------------------


def test_call_payload_names_skip_literals_and_omitted():
    site = _call_site(["WS-A", '"LIT"', "OMITTED", "WS-T(1)", "42"])
    assert payload_names(site.statement, "", "CALL") == [
        "WS-A",
        None,
        None,
        "WS-T(1)",
        None,
    ]


def test_sql_host_variables_leave_out_into_lists():
    text = (
        "EXEC SQL SELECT LIMIT INTO :WS-LIMIT :WS-IND FROM CUST "
        "WHERE ID = :WS-CUST AND REGION = :WS-REC.WS-REGION "
        "AND ID2 = :WS-CUST END-EXEC"
    )
    assert sql_host_variables(text) == ["WS-CUST", "WS-REGION OF WS-REC"]


def test_sql_update_sends_every_host_variable():
    text = "EXEC SQL UPDATE T SET A = :WS-A, B = :WS-B:WS-BI WHERE K = :WS-K END-EXEC"
    assert sql_host_variables(text) == ["WS-A", "WS-B", "WS-BI", "WS-K"]


def test_cics_data_items_are_from_and_commarea():
    text = "EXEC CICS LINK PROGRAM('X') COMMAREA(WS-COMM) LENGTH(100) END-EXEC"
    assert cics_data_items(text) == ["WS-COMM"]
    text = "EXEC CICS SEND MAP('M') FROM(MAPO) ERASE END-EXEC"
    assert cics_data_items(text) == ["MAPO"]
    assert cics_data_items("EXEC CICS WRITEQ TS QUEUE(Q) FROM('LIT') END-EXEC") == []


def test_dispatch_prints_event_and_dumps_each_argument_before_the_body():
    directive = MockDirective(
        MockCategory.CALL, "DISCRATE", body_lines=["MOVE 1 TO WS-B"]
    )
    suite = _suite(directive)
    lines = build_site_dispatch(
        _call_site(["WS-A", '"X"']),
        suite,
        TallyRegistry(suite),
        statement_text='CALL "DISCRATE" USING WS-A "X"',
        behaviour=True,
    )
    text = "\n".join(lines)
    event = text.index('DISPLAY "__MOCKYMOCK__ EVENT: CALL DISCRATE"')
    dump = text.index(f'CALL "{HEXDUMP_PROGRAM}" USING WS-A UT-BT-LEN')
    body = text.index("MOVE 1 TO WS-B")
    assert event < dump < body
    assert "MOVE LENGTH OF WS-A TO UT-BT-LEN" in text
    assert 'DISPLAY "__MOCKYMOCK__ DATA: -"' in text


def test_dispatch_without_behaviour_prints_nothing():
    directive = MockDirective(MockCategory.CALL, "DISCRATE", body_lines=[])
    suite = _suite(directive)
    lines = build_site_dispatch(_call_site(["WS-A"]), suite, TallyRegistry(suite))
    assert not any("EVENT" in line or HEXDUMP_PROGRAM in line for line in lines)


def test_real_call_branch_prints_no_event():
    directive = MockDirective(MockCategory.CALL, "DISCRATE", real_source="DISCRATE.cbl")
    suite = _suite(directive)
    lines = build_site_dispatch(
        _call_site(["WS-A"]),
        suite,
        TallyRegistry(suite),
        behaviour=True,
        real_statement=['CALL "DISCRATE" USING WS-A'],
    )
    assert not any("EVENT" in line for line in lines)


def test_driver_prints_return_code_before_each_case_end():
    suite = MockTestSuite(name="S", test_cases=[MockTestCase(name="one")])
    artifact = build_driver(suite, [], TallyRegistry(suite), behaviour=True)
    procedure = artifact.procedure_lines
    end = next(i for i, line in enumerate(procedure) if "CASE 001 END" in line)
    assert 'DISPLAY "__MOCKYMOCK__ RC 001: " RETURN-CODE' in procedure[end - 1]
    assert LENGTH_DECLARATION in artifact.working_storage_lines


def test_driver_without_behaviour_has_no_rc_line():
    suite = MockTestSuite(name="S", test_cases=[MockTestCase(name="one")])
    artifact = build_driver(suite, [], TallyRegistry(suite))
    assert not any("__MOCKYMOCK__ RC" in line for line in artifact.procedure_lines)


def test_hexdump_program_is_a_complete_program():
    source = "\n".join(hexdump_program())
    assert f"PROGRAM-ID. {HEXDUMP_PROGRAM}." in source
    assert "PROCEDURE DIVISION USING L-DATA L-LEN." in source
    assert source.rstrip().endswith(f"END PROGRAM {HEXDUMP_PROGRAM}.")


# --- stdout markers -----------------------------------------------------------

_STDOUT = "\n".join(
    [
        "__MOCKYMOCK__ TESTSUITE: S",
        "__MOCKYMOCK__ CASE 001 START: first",
        "__MOCKYMOCK__ EVENT: CALL DATEUTL",
        "__MOCKYMOCK__ DATA: 3230323631313031",
        "__MOCKYMOCK__ DATA: -",
        "REPORT LINE 1",
        "__MOCKYMOCK__ EVENT: OPEN F",
        "__MOCKYMOCK__ RC 001: +000000004",
        "__MOCKYMOCK__ CASE 001 END",
        "__MOCKYMOCK__ CASE 002 START: second",
        "__MOCKYMOCK__ EVENT: WRITE R",
        "__MOCKYMOCK__ DATA: 41+",
        "__MOCKYMOCK__ RC 002: +000000000",
        "__MOCKYMOCK__ CASE 002 END",
        "__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=0",
        "",
    ]
)


def test_parse_stdout_reads_events_data_rc_and_output():
    suite = parse_stdout(_STDOUT)
    first, second = suite.results
    assert [(e.label, e.data) for e in first.events] == [
        ("CALL DATEUTL", ["3230323631313031", "-"]),
        ("OPEN F", []),
    ]
    assert first.return_code == "+000000004"
    assert first.output == ["REPORT LINE 1"]
    assert second.events[0].data == ["41+"]
    assert second.output == []
    assert suite.all_passed


# --- compare --------------------------------------------------------------------


def _baseline(stdout: str = _STDOUT, inputs=None) -> dict:
    return build_baseline(parse_stdout(stdout), inputs or {"cut": "a"}, "0.0")


def test_same_run_compares_same():
    comparison = compare(_baseline(), parse_stdout(_STDOUT), {"cut": "a"})
    assert comparison.matches
    assert comparison.counts() == {"same": 2, "differs": 0, "new": 0, "not-run": 0}
    assert comparison.changed_inputs == []


def test_a_changed_value_is_reported_with_its_text():
    changed = _STDOUT.replace("DATA: 3230323631313031", "DATA: 3230323631313032")
    comparison = compare(_baseline(), parse_stdout(changed), {"cut": "a"})
    assert not comparison.matches
    case = comparison.cases[0]
    assert case.verdict == "differs"
    assert case.differences == [
        "event 1 (CALL DATEUTL): value 1 was 3230323631313031, now "
        '3230323631313032 ("20261101" -> "20261102")'
    ]


def test_missing_event_output_and_rc_are_reported():
    changed = (
        _STDOUT.replace("__MOCKYMOCK__ EVENT: OPEN F\n", "")
        .replace("REPORT LINE 1", "REPORT LINE 2")
        .replace("RC 001: +000000004", "RC 001: +000000000")
    )
    case = compare(_baseline(), parse_stdout(changed), {"cut": "a"}).cases[0]
    assert case.differences == [
        "event 2: was OPEN F, now nothing",
        "2 boundary event(s) recorded, 1 now",
        "output line 1 was 'REPORT LINE 1', now 'REPORT LINE 2'",
        "RETURN-CODE was +000000004, now +000000000",
    ]


def test_new_and_not_run_cases_do_not_fail_and_inputs_are_named():
    only_second = _STDOUT.replace("CASE 001 START: first", "CASE 001 START: renamed")
    comparison = compare(_baseline(), parse_stdout(only_second), {"cut": "b"})
    verdicts = {case.name: case.verdict for case in comparison.cases}
    assert verdicts == {"renamed": "new", "second": "same", "first": "not-run"}
    assert comparison.matches
    assert comparison.changed_inputs == ["cut"]
    assert "the .cut file changed" in format_comparison(comparison)


def test_baseline_round_trips_and_bad_files_are_refused(tmp_path):
    path = tmp_path / "b" / "base.json"
    write_baseline(path, _baseline())
    assert load_baseline(path)["cases"][0]["name"] == "first"
    (tmp_path / "junk.json").write_text("{")
    with pytest.raises(BaselineError):
        load_baseline(tmp_path / "junk.json")
    (tmp_path / "other.json").write_text(json.dumps({"format": "x"}))
    with pytest.raises(BaselineError, match="not a mockymock baseline"):
        load_baseline(tmp_path / "other.json")
    (tmp_path / "v9.json").write_text(
        json.dumps({"format": "mockymock-baseline", "version": 9, "cases": []})
    )
    with pytest.raises(BaselineError, match="version"):
        load_baseline(tmp_path / "v9.json")
    (tmp_path / "v1.json").write_text(
        json.dumps({"format": "mockymock-baseline", "version": 1, "cases": []})
    )
    assert load_baseline(tmp_path / "v1.json")["version"] == 1


# --- version 2: cursor inputs and returned LINKAGE ---------------------------


def test_cursor_host_variables_come_from_each_declare():
    lines = [
        "       WORKING-STORAGE SECTION.",
        "           EXEC SQL DECLARE CUSTCUR CURSOR FOR",
        "               SELECT CUST_ID INTO :NOT-SENT FROM CUSTOMER",
        "                WHERE REGION = :WS-REGION AND TIER > :T.TIER",
        "           END-EXEC.",
        "           EXEC SQL DECLARE C2 SCROLL CURSOR WITH HOLD FOR S1 END-EXEC.",
        "           EXEC SQL DECLARE C3 CURSOR FOR SELECT A FROM B END-EXEC.",
    ]
    assert cursor_host_variables(lines) == {"CUSTCUR": ["WS-REGION", "TIER OF T"]}
    assert opened_cursor("EXEC SQL OPEN CUSTCUR END-EXEC") == "CUSTCUR"
    assert opened_cursor("EXEC SQL FETCH CUSTCUR INTO :A END-EXEC") is None


def test_cursor_open_is_followed_by_the_cursor_inputs_event():
    lines = site_lines(
        "SQL",
        "OPEN",
        None,
        "EXEC SQL OPEN CUSTCUR END-EXEC",
        "SQL",
        "    ",
        cursor_hosts={"CUSTCUR": ["WS-REGION"]},
    )
    assert lines[0] == '    DISPLAY "__MOCKYMOCK__ EVENT: SQL OPEN"'
    assert lines[1] == '    DISPLAY "__MOCKYMOCK__ EVENT: SQL CURSOR CUSTCUR"'
    assert lines[2:] == [
        "    MOVE LENGTH OF WS-REGION TO UT-BT-LEN",
        f'    CALL "{HEXDUMP_PROGRAM}" USING WS-REGION UT-BT-LEN',
    ]
    # Without a DECLARE that names host variables, nothing is added.
    assert site_lines("SQL", "OPEN", None, "EXEC SQL OPEN C9 END-EXEC", "SQL", "") == [
        'DISPLAY "__MOCKYMOCK__ EVENT: SQL OPEN"'
    ]


def _parse(source: str):
    from cobolparser import parse_cobol

    return parse_cobol(source, filename="p.cbl").ast


def test_returned_items_are_the_using_items_or_the_commarea():
    called = _parse(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       DATA DIVISION.\n"
        "       LINKAGE SECTION.\n"
        "       01  LK-A PIC X.\n"
        "       01  LK-B PIC X.\n"
        "       PROCEDURE DIVISION USING LK-A LK-B.\n"
        "           GOBACK.\n"
    )
    assert returned_items(called) == ["LK-A", "LK-B"]
    cics = _parse(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       DATA DIVISION.\n"
        "       LINKAGE SECTION.\n"
        "       01  DFHCOMMAREA PIC X(8).\n"
        "       PROCEDURE DIVISION.\n"
        "           GOBACK.\n"
    )
    assert returned_items(cics) == ["DFHCOMMAREA"]
    batch = _parse(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       PROCEDURE DIVISION.\n"
        "           GOBACK.\n"
    )
    assert returned_items(batch) == []


def test_driver_dumps_returned_items_before_the_rc_line():
    suite = MockTestSuite(name="S", test_cases=[MockTestCase(name="one")])
    artifact = build_driver(
        suite, [], TallyRegistry(suite), behaviour=True, returned=["DFHCOMMAREA"]
    )
    procedure = artifact.procedure_lines
    rc = next(i for i, line in enumerate(procedure) if "__MOCKYMOCK__ RC 001" in line)
    assert procedure[rc - 3 : rc] == [
        '           DISPLAY "__MOCKYMOCK__ EVENT: RETURNED LINKAGE"',
        "           MOVE LENGTH OF DFHCOMMAREA TO UT-BT-LEN",
        f'           CALL "{HEXDUMP_PROGRAM}" USING DFHCOMMAREA UT-BT-LEN',
    ]


def test_a_version_1_baseline_ignores_the_version_2_events():
    old = _baseline()
    old["version"] = 1
    newer = _STDOUT.replace(
        "__MOCKYMOCK__ RC 001",
        "__MOCKYMOCK__ EVENT: RETURNED LINKAGE\n__MOCKYMOCK__ DATA: 41\n"
        "__MOCKYMOCK__ RC 001",
    )
    comparison = compare(old, parse_stdout(newer), {"cut": "a"})
    assert comparison.matches
    assert comparison.notes and "version 1" in comparison.notes[0]
    assert "note: baseline version 1" in format_comparison(comparison)
    # A version-2 baseline compares them.
    comparison = compare(_baseline(), parse_stdout(newer), {"cut": "a"})
    assert not comparison.matches
    assert comparison.notes == []
