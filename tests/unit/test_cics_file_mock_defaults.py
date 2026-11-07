"""Unit checks for the CICS / file / MQ / SQL mock defaults fixed in the
2026-11-05 round-2 bug hunt (executed counterpart:
tests/integration/test_cics_file_mock_bugs_20261105.py): the RESP
mirror, MQ reply fields, SQL cursor names and row rewinds on OPEN."""

from types import SimpleNamespace

from mockymock.analysis.mock_surface import BoundarySite
from mockymock.dsl.model import MockCategory, MockDirective, MockTestCase, MockTestSuite
from mockymock.splicer.cics_resp import cics_resp_mirror
from mockymock.splicer.injector import _mq_reply_fields
from mockymock.splicer.naming import TallyRegistry, rewinds_on_open
from mockymock.splicer.orchestrator import _sql_cursor


class _Cics:
    def __init__(self, text: str) -> None:
        self.cics_text = text


def test_resp_mirror_copies_whichever_side_the_body_set():
    lines = cics_resp_mirror(
        _Cics("READ FILE('F') RESP(WS-R) RESP2(WS-R2)"), ("EIBRESP", "EIBRESP2")
    )
    assert lines == [
        "IF WS-R NOT = 0",
        "    MOVE WS-R TO EIBRESP",
        "ELSE",
        "    MOVE EIBRESP TO WS-R",
        "END-IF",
        "IF WS-R2 NOT = 0",
        "    MOVE WS-R2 TO EIBRESP2",
        "ELSE",
        "    MOVE EIBRESP2 TO WS-R2",
        "END-IF",
    ]


def test_resp_mirror_needs_both_a_resp_option_and_the_eib_field():
    assert cics_resp_mirror(_Cics("READ FILE('F') RESP(WS-R)"), ()) == []
    assert cics_resp_mirror(_Cics("READ FILE('F') NOHANDLE"), ("EIBRESP",)) == []
    # Only RESP2's EIB twin exists: only RESP2 is mirrored.
    assert cics_resp_mirror(
        _Cics("READ FILE('F') RESP(WS-R) RESP2(WS-R2)"), ("EIBRESP2",)
    )[0] == ("IF WS-R2 NOT = 0")
    # A subscripted RESP is not a single data name.
    assert cics_resp_mirror(_Cics("READ FILE('F') RESP(T (1))"), ("EIBRESP",)) == []


def _site(names, *, is_mq=False, mq_target=False):
    statement = SimpleNamespace(
        using_parameters=[SimpleNamespace(name=name) for name in names]
    )
    return BoundarySite(
        category=MockCategory.CALL,
        label="CALL",
        keys=("MQOPEN",),
        match_text=None,
        paragraph_name="P",
        line=1,
        nested=False,
        statement=statement,
        is_mq=is_mq,
        mq_target=mq_target,
    )


def test_mq_reply_fields_are_the_last_two_arguments_of_an_mq_call():
    names = ["H", "OD", "OPTS", "HOBJ", "W-CC", "W-RC"]
    assert _mq_reply_fields(_site(names, is_mq=True)) == ["W-CC", "W-RC"]
    assert _mq_reply_fields(_site(names, mq_target=True)) == ["W-CC", "W-RC"]
    assert _mq_reply_fields(_site(names)) == []
    assert _mq_reply_fields(_site(["W-CC"], is_mq=True)) == []
    assert _mq_reply_fields(_site(["H", '"X"', "0"], is_mq=True)) == []


def test_sql_cursor_reads_open_and_fetch_forms():
    assert _sql_cursor("OPEN C1") == "C1"
    assert _sql_cursor("FETCH C1 INTO:WS-NAME") == "C1"
    assert _sql_cursor("FETCH NEXT FROM EMP-CUR INTO:A") == "EMP-CUR"
    assert _sql_cursor("FETCH ABSOLUTE 5 FROM C2 INTO:A") == "C2"
    assert _sql_cursor("FETCH SENSITIVE PRIOR FROM C3 INTO:A") == "C3"
    assert _sql_cursor("CLOSE C1") is None
    assert _sql_cursor("FETCH") is None
    assert _sql_cursor(None) is None


def test_only_read_and_fetch_rows_rewind():
    assert rewinds_on_open(MockCategory.READ, "INFILE")
    assert rewinds_on_open(MockCategory.SQL, "FETCH C1")
    assert not rewinds_on_open(MockCategory.SQL, "SELECT NAME")
    assert not rewinds_on_open(MockCategory.CALL, "MQGET")


def test_row_cursor_subtracts_the_rewind_only_for_rewound_keys():
    rows = [[("A", "1")]]
    case = MockTestCase(
        name="c",
        mocks=[
            MockDirective(category=MockCategory.READ, key="INFILE", rows=rows),
            MockDirective(category=MockCategory.SQL, key="SELECT X", rows=rows),
        ],
    )
    registry = TallyRegistry(MockTestSuite(name="S", test_cases=[case]))
    assert registry.row_cursor(MockCategory.READ, "INFILE") == (
        "UT-READ-INFILE-TALLY - UT-READ-INFILE-REW"
    )
    assert registry.row_cursor(MockCategory.SQL, "SELECT X") == "UT-SQL-SELECT-X-TALLY"
    assert registry.rewound_keys() == [(MockCategory.READ, "INFILE")]
