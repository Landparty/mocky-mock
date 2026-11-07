"""A mocked statement starts from the outcome the real one reports on
success (2026-11-05 resource-mock bug hunt): RETURN-CODE 0 for a CALL,
SQLCODE 0 for EXEC SQL, a blank DIBSTAT for EXEC DLI. A keyed READ whose
ROWS run out reports 23 (INVALID KEY), not 10. A dynamic CALL's real-call
route tests the identifier as the CALL writes it (subscript, qualifier).
Executed counterparts: tests/integration/test_resource_mock_defaults_20261105.py."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import BoundarySite
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.injector import build_site_dispatch
from mockymock.splicer.naming import TallyRegistry


def _site(category_cut_key, label, keys=(), match_text=None, **extra):
    from mockymock.dsl.model import MockCategory

    return BoundarySite(
        category=MockCategory[category_cut_key],
        label=label,
        keys=keys,
        match_text=match_text,
        paragraph_name="P",
        line=10,
        nested=False,
        statement=extra.pop("statement", object()),
        **extra,
    )


def _suite(mock: str):
    return parse_cut(f'TESTSUITE "s"\nTESTCASE "c"\n{mock}\n    PERFORM P\n')


def _dispatch(suite, site, **kwargs):
    return [
        line.strip()
        for line in build_site_dispatch(site, suite, TallyRegistry(suite), **kwargs)
    ]


def test_empty_sql_mock_reports_sqlcode_zero():
    suite = _suite('    MOCK SQL "CLOSE C1"\n    END-MOCK')
    site = _site("SQL", "SQL", match_text="CLOSE C1")
    lines = _dispatch(suite, site, sqlcode=True, sqlstate=True)
    assert lines[3:5] == ["MOVE 0 TO SQLCODE", 'MOVE "00000" TO SQLSTATE']


def test_sql_default_comes_before_the_body():
    suite = _suite(
        '    MOCK SQL "CLOSE C1"\n        MOVE -501 TO SQLCODE\n    END-MOCK'
    )
    site = _site("SQL", "SQL", match_text="CLOSE C1")
    lines = _dispatch(suite, site, sqlcode=True)
    assert lines.index("MOVE 0 TO SQLCODE") < lines.index("MOVE -501 TO SQLCODE")
    assert "SQLSTATE" not in "\n".join(lines)


def test_no_sqlcode_default_without_an_sqlca():
    suite = _suite('    MOCK SQL "CLOSE C1"\n    END-MOCK')
    site = _site("SQL", "SQL", match_text="CLOSE C1")
    assert "SQLCODE" not in "\n".join(_dispatch(suite, site))


def test_empty_dli_mock_blanks_dibstat_only_with_a_dib():
    suite = _suite('    MOCK DLI "TERM"\n    END-MOCK')
    site = _site("DLI", "EXEC DLI", match_text="TERM")
    assert "MOVE SPACES TO DIBSTAT" in _dispatch(suite, site, dibstat=True)
    assert "DIBSTAT" not in "\n".join(_dispatch(suite, site))


def test_call_mocks_reset_return_code():
    suite = _suite('    MOCK CALL "LOGIT"\n    END-MOCK')
    assert "MOVE 0 TO RETURN-CODE" in _dispatch(
        suite, _site("CALL", "CALL", keys=("LOGIT",))
    )
    dynamic = _suite("    MOCK CALL WS-PGM\n    END-MOCK")
    assert "MOVE 0 TO RETURN-CODE" in _dispatch(
        dynamic, _site("DYNCALL", "dynamic CALL", keys=("WS-PGM",))
    )


def test_file_mocks_do_not_touch_return_code():
    suite = _suite("    MOCK CLOSE F\n    END-MOCK")
    lines = _dispatch(suite, _site("CLOSE", "CLOSE", keys=("F",)))
    assert "RETURN-CODE" not in "\n".join(lines)


def _rows_end(read_form):
    suite = _suite('    MOCK READ F ROWS\n        ( F-NAME = "A" )\n    END-MOCK')
    site = _site("READ", "READ", keys=("F",), read_form=read_form)
    lines = _dispatch(suite, site, file_status_fields={"F": "WS-FS"})
    return lines[lines.index("WHEN OTHER") + 1]


def test_keyed_read_rows_end_with_not_found():
    assert _rows_end("KEY") == 'MOVE "23" TO WS-FS'
    assert _rows_end("KEY F-ALT") == 'MOVE "23" TO WS-FS'


def test_sequential_read_rows_end_with_end_of_file():
    assert _rows_end("NEXT") == 'MOVE "10" TO WS-FS'
    assert _rows_end(None) == 'MOVE "10" TO WS-FS'


_TABLE_CALL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TAB.
           05 WS-ENT    PIC X(8) OCCURS 2 TIMES.
       01  WS-I         PIC 9 VALUE 2.
       PROCEDURE DIVISION.
       P.
           CALL WS-ENT(WS-I).
"""


def test_real_dynamic_route_tests_the_subscripted_entry():
    call = parse_cobol(_TABLE_CALL).ast.find_all_by_type("CallStatement")[0]
    if not call.get_metadata("called_program_reference"):
        return  # an older cobol-parser keeps no reference: bare-name route
    suite = _suite(
        '    USE REAL CALL "SUB" FROM "SUB.cbl"\n    MOCK CALL WS-ENT\n    END-MOCK'
    )
    site = _site("DYNCALL", "dynamic CALL", keys=("WS-ENT",), statement=call)
    lines = _dispatch(suite, site, real_statement=["CALL WS-ENT(WS-I)"])
    route = next(line for line in lines if "UPPER-CASE" in line)
    assert route.endswith("FUNCTION UPPER-CASE(WS-ENT ( WS-I ))")


def test_cics_condition_sets_eibresp_when_the_program_has_one():
    suite = _suite('    MOCK CICS "READ"\n        CONDITION IS NOTFND\n    END-MOCK')
    site = _site("CICS", "EXEC CICS", match_text="READ FILE('CUST')")
    lines = _dispatch(suite, site, eib_resp_names=("EIBRESP",))
    assert lines.index("MOVE 0 TO EIBRESP") < lines.index("MOVE 13 TO EIBRESP")
    assert "MOVE 13 TO EIBRESP" not in _dispatch(suite, site)
