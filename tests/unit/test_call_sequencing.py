"""Per-invocation sequencing for MOCK CALL / MQ / dynamic CALL / DLI:
`ROWS ( ... ) ( ... ) TERMINAL ( ... )` -- row N answers the key's Nth
call within one test case, TERMINAL every call after the last row."""

import pytest

from mockymock.analysis.mock_surface import BoundarySite
from mockymock.dsl.model import (
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
)
from mockymock.dsl.parser import CutParseError, parse_cut
from mockymock.splicer.injector import build_site_dispatch
from mockymock.splicer.naming import TallyRegistry

CUT_CALL_ROWS = """\
TESTSUITE "purge"

TESTCASE "one purge iteration"
    MOCK CALL "CBLTDLI" ROWS
        ( CUST-STATUS = "  ", CUST-IO-CIF = "C0001", CUST-IO-STATUS = "CL" )
        ( CUST-STATUS = "  " )
        TERMINAL ( CUST-STATUS = "GB" )
    END-MOCK
    PERFORM 0000-MAIN-PROCESS
    VERIFY CALL "CBLTDLI" WAS CALLED 3 TIMES
"""


def _only_mock(text):
    return parse_cut(text).test_cases[0].mocks[0]


# --- parser -----------------------------------------------------------------


def test_static_call_rows_parse_into_rows_and_terminal():
    directive = _only_mock(CUT_CALL_ROWS)
    assert directive.category is MockCategory.CALL
    assert directive.key == "CBLTDLI"
    assert directive.body_lines == []
    assert directive.rows == [
        [
            ("CUST-STATUS", '"  "'),
            ("CUST-IO-CIF", '"C0001"'),
            ("CUST-IO-STATUS", '"CL"'),
        ],
        [("CUST-STATUS", '"  "')],
    ]
    assert directive.terminal_row == [("CUST-STATUS", '"GB"')]


def test_mq_rows_parse_as_call_category():
    directive = _only_mock(
        CUT_CALL_ROWS.replace('MOCK CALL "CBLTDLI" ROWS', 'MOCK MQ "MQGET" ROWS')
    )
    assert directive.category is MockCategory.CALL
    assert directive.key == "MQGET"
    assert directive.rows is not None


def test_dynamic_call_rows_parse_as_dyncall():
    directive = _only_mock(
        CUT_CALL_ROWS.replace('MOCK CALL "CBLTDLI" ROWS', "MOCK CALL WS-PGM ROWS")
    )
    assert directive.category is MockCategory.DYNCALL
    assert directive.key == "WS-PGM"
    assert directive.terminal_row == [("CUST-STATUS", '"GB"')]


def test_dli_rows_parse():
    directive = _only_mock(
        CUT_CALL_ROWS.replace('MOCK CALL "CBLTDLI" ROWS', 'MOCK DLI "GN" ROWS')
    )
    assert directive.category is MockCategory.DLI
    assert len(directive.rows) == 2


def test_call_rows_without_terminal_is_rejected():
    bad = CUT_CALL_ROWS.replace('        TERMINAL ( CUST-STATUS = "GB" )\n', "")
    with pytest.raises(CutParseError, match="needs a TERMINAL"):
        parse_cut(bad)


def test_dli_rows_without_terminal_is_rejected():
    bad = CUT_CALL_ROWS.replace(
        'MOCK CALL "CBLTDLI" ROWS', 'MOCK DLI "GN" ROWS'
    ).replace('        TERMINAL ( CUST-STATUS = "GB" )\n', "")
    with pytest.raises(CutParseError, match="needs a TERMINAL"):
        parse_cut(bad)


def test_call_rows_duplicate_terminal_is_rejected():
    bad = CUT_CALL_ROWS.replace(
        '        TERMINAL ( CUST-STATUS = "GB" )\n',
        '        TERMINAL ( CUST-STATUS = "GB" )\n'
        '        TERMINAL ( CUST-STATUS = "GE" )\n',
    )
    with pytest.raises(CutParseError, match="duplicate TERMINAL"):
        parse_cut(bad)


def test_call_rows_with_no_rows_is_rejected():
    bad = """\
TESTSUITE "s"

TESTCASE "c"
    MOCK CALL "CBLTDLI" ROWS
    END-MOCK
    PERFORM P
"""
    with pytest.raises(CutParseError, match="has no rows"):
        parse_cut(bad)


def test_call_rows_with_free_form_line_is_rejected():
    bad = CUT_CALL_ROWS.replace(
        '        ( CUST-STATUS = "  " )\n', '        MOVE "  " TO CUST-STATUS\n'
    )
    with pytest.raises(CutParseError, match="malformed ROWS row"):
        parse_cut(bad)


def test_capture_inside_call_rows_is_kept():
    text = CUT_CALL_ROWS.replace(
        'MOCK CALL "CBLTDLI" ROWS\n',
        'MOCK CALL "CBLTDLI" ROWS\n        CAPTURE ARG 1 INTO WS-LAST-FUNC\n',
    )
    directive = _only_mock(text)
    assert directive.captures == [(1, "WS-LAST-FUNC")]
    assert len(directive.rows) == 2


def test_call_rows_in_before_each():
    text = """\
TESTSUITE "s"

BEFORE-EACH
    MOCK CALL "CBLTDLI" ROWS
        ( CUST-STATUS = "  " )
        TERMINAL ( CUST-STATUS = "GB" )
    END-MOCK
END-BEFORE

TESTCASE "c"
    PERFORM P
"""
    directive = parse_cut(text).test_cases[0].mocks[0]
    assert directive.rows == [[("CUST-STATUS", '"  "')]]
    assert directive.terminal_row == [("CUST-STATUS", '"GB"')]


def test_call_rows_reject_provider_placeholders_like_any_mock_body():
    """Same rule as READ/SQL ROWS: PROVIDER values substitute into MOVE and
    EXPECT only, never into a mock body."""
    text = """\
TESTSUITE "s"

PROVIDER SEGS
    HEADER Cif
    ROW "C0001"
    ROW "C0002"

TESTCASE "c" USING PROVIDER SEGS
    MOCK CALL "CBLTDLI" ROWS
        ( CUST-STATUS = "  ", CUST-IO-CIF = {Cif} )
        TERMINAL ( CUST-STATUS = "GB" )
    END-MOCK
    PERFORM P
"""
    with pytest.raises(CutParseError, match="is not substituted"):
        parse_cut(text)


def test_terminal_on_sql_rows_is_still_rejected():
    bad = """\
TESTSUITE "s"

TESTCASE "c"
    MOCK SQL "FETCH C1" ROWS
        ( X = 1 )
        TERMINAL ( X = 2 )
    END-MOCK
    PERFORM P
"""
    with pytest.raises(CutParseError, match="TERMINAL is only supported"):
        parse_cut(bad)


@pytest.mark.parametrize("opening", ["MOCK OPEN F ROWS", "MOCK WRITE F ROWS"])
def test_rows_still_rejected_on_other_categories(opening):
    bad = f"""\
TESTSUITE "s"

TESTCASE "c"
    {opening}
        ( X = 1 )
    END-MOCK
    PERFORM P
"""
    with pytest.raises(CutParseError, match="ROWS is only supported"):
        parse_cut(bad)


# --- splice -----------------------------------------------------------------


def _site(category=MockCategory.CALL, keys=("CBLTDLI",), match_text=None):
    return BoundarySite(
        category=category,
        label="CALL" if category is not MockCategory.DLI else "EXEC DLI",
        keys=keys,
        match_text=match_text,
        paragraph_name="P",
        line=10,
        nested=False,
        statement=object(),
    )


def _dispatch(suite, site=None):
    return [
        line.strip()
        for line in build_site_dispatch(site or _site(), suite, TallyRegistry(suite))
    ]


def test_call_rows_dispatch_sequences_on_the_key_tally():
    suite = parse_cut(CUT_CALL_ROWS)
    assert _dispatch(suite) == [
        "EVALUATE UT-CURRENT-CASE",
        'WHEN "001"',
        "ADD 1 TO UT-CBLTDLI-TALLY",
        "EVALUATE TRUE",
        "WHEN UT-CBLTDLI-TALLY = 1",
        'MOVE "  " TO CUST-STATUS',
        'MOVE "C0001" TO CUST-IO-CIF',
        'MOVE "CL" TO CUST-IO-STATUS',
        "WHEN UT-CBLTDLI-TALLY = 2",
        'MOVE "  " TO CUST-STATUS',
        "WHEN OTHER",
        'MOVE "GB" TO CUST-STATUS',
        "END-EVALUATE",
        "WHEN OTHER",
        'DISPLAY "__MOCKYMOCK__ ERROR: CALL boundary (line 10) reached "',
        '"from unmocked test case " UT-CURRENT-CASE',
        "ADD 1 TO UT-FAIL-COUNT",
        "END-EVALUATE",
    ]


def test_call_rows_never_touch_sqlcode():
    joined = "\n".join(_dispatch(parse_cut(CUT_CALL_ROWS)))
    assert "SQLCODE" not in joined


def test_dli_rows_dispatch_uses_terminal_for_exhaustion():
    suite = parse_cut(
        CUT_CALL_ROWS.replace('MOCK CALL "CBLTDLI" ROWS', 'MOCK DLI "GN" ROWS')
    )
    lines = _dispatch(
        suite, _site(MockCategory.DLI, keys=(), match_text="GN USING PCB(1)")
    )
    other = lines.index("WHEN OTHER")
    assert lines[other + 1] == 'MOVE "GB" TO CUST-STATUS'
    assert "SQLCODE" not in "\n".join(lines)


def test_two_cases_each_get_their_own_rows_on_the_shared_tally():
    """Both cases switch on the same per-key tally, which the driver zeroes
    at the start of every case -- so case 2 starts back at its own row 1."""
    text = CUT_CALL_ROWS + (
        '\nTESTCASE "empty database"\n'
        '    MOCK CALL "CBLTDLI" ROWS\n'
        '        ( CUST-STATUS = "GB" )\n'
        '        TERMINAL ( CUST-STATUS = "GB" )\n'
        "    END-MOCK\n"
        "    PERFORM 0000-MAIN-PROCESS\n"
    )
    lines = _dispatch(parse_cut(text))
    case_two = lines.index('WHEN "002"')
    assert lines[case_two + 1 : case_two + 5] == [
        "ADD 1 TO UT-CBLTDLI-TALLY",
        "EVALUATE TRUE",
        "WHEN UT-CBLTDLI-TALLY = 1",
        'MOVE "GB" TO CUST-STATUS',
    ]


def test_capture_precedes_the_rows_block():
    from cobolparser.models.ast_base import SourceLocation
    from cobolparser.models.statements.call import CallStatement

    statement = CallStatement(SourceLocation(line=10, column=1))
    statement.set_called_program("CBLTDLI")
    statement.add_using_parameter("DLI-GHN")
    site = BoundarySite(
        category=MockCategory.CALL,
        label="CALL",
        keys=("CBLTDLI",),
        match_text=None,
        paragraph_name="P",
        line=10,
        nested=False,
        statement=statement,
    )
    suite = parse_cut(
        CUT_CALL_ROWS.replace(
            'MOCK CALL "CBLTDLI" ROWS\n',
            'MOCK CALL "CBLTDLI" ROWS\n        CAPTURE ARG 1 INTO WS-LAST-FUNC\n',
        )
    )
    lines = _dispatch(suite, site)
    assert lines.index("MOVE DLI-GHN TO WS-LAST-FUNC") < lines.index("EVALUATE TRUE")


def test_call_rows_without_terminal_raises_at_splice_time():
    """The parser rejects this; a hand-built directive must not silently
    splice a sequence that never ends."""
    case = MockTestCase(
        name="c",
        mocks=[
            MockDirective(
                MockCategory.CALL, "CBLTDLI", rows=[[("CUST-STATUS", '"  "')]]
            )
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    with pytest.raises(ValueError, match="no TERMINAL"):
        build_site_dispatch(_site(), suite, TallyRegistry(suite))


def test_plain_call_mock_dispatch_is_unchanged():
    case = MockTestCase(
        name="c",
        mocks=[
            MockDirective(
                MockCategory.CALL, "CBLTDLI", body_lines=['MOVE "GB" TO CUST-STATUS']
            )
        ],
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    assert _dispatch(suite)[:4] == [
        "EVALUATE UT-CURRENT-CASE",
        'WHEN "001"',
        "ADD 1 TO UT-CBLTDLI-TALLY",
        'MOVE "GB" TO CUST-STATUS',
    ]
