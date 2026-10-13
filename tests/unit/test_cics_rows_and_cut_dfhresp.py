"""#169: `MOCK CICS "..." ROWS ( ... ) TERMINAL ( ... )` sequences EXEC CICS
answers like CALL/DLI do (a STARTBR/READNEXT browse loop can now end), and
`DFHRESP(<condition>)` in .cut text expands to its EIBRESP number exactly as
it does in program lines."""

import pytest

from mockymock.analysis.mock_surface import BoundarySite
from mockymock.dsl.model import MockCategory
from mockymock.dsl.parser import CutParseError, parse_cut
from mockymock.splicer.cics_resp import expand_dfhresp_text
from mockymock.splicer.injector import build_site_dispatch
from mockymock.splicer.naming import TallyRegistry

CUT_BROWSE = """\
TESTSUITE "browse"

TESTCASE "browse two records then ENDFILE"
    MOCK CICS "READNEXT" ROWS
        ( WS-CUST-ID = "C1", WS-RESP = DFHRESP(NORMAL) )
        ( WS-CUST-ID = "C2", WS-RESP = 0 )
        TERMINAL ( WS-RESP = DFHRESP(ENDFILE) )
    END-MOCK
    PERFORM 3000-BROWSE
    EXPECT WS-COUNT TO BE 2
"""


def _only_mock(text):
    return parse_cut(text).test_cases[0].mocks[0]


def test_cics_rows_parse_with_terminal():
    directive = _only_mock(CUT_BROWSE)
    assert directive.category is MockCategory.CICS
    assert directive.rows == [
        [("WS-CUST-ID", '"C1"'), ("WS-RESP", "0")],
        [("WS-CUST-ID", '"C2"'), ("WS-RESP", "0")],
    ]
    assert directive.terminal_row == [("WS-RESP", "20")]


def test_cics_rows_without_terminal_is_rejected():
    bad = CUT_BROWSE.replace("        TERMINAL ( WS-RESP = DFHRESP(ENDFILE) )\n", "")
    with pytest.raises(CutParseError, match="needs a TERMINAL"):
        parse_cut(bad)


def test_cics_rows_dispatch_sequences_and_uses_terminal_for_exhaustion():
    suite = parse_cut(CUT_BROWSE)
    site = BoundarySite(
        category=MockCategory.CICS,
        label="EXEC CICS",
        keys=(),
        match_text="READNEXT FILE('CUSTFILE') INTO(WS-REC) RIDFLD(WS-KEY)",
        paragraph_name="3000-BROWSE",
        line=20,
        nested=False,
        statement=object(),
    )
    lines = [
        line.strip() for line in build_site_dispatch(site, suite, TallyRegistry(suite))
    ]
    tally = next(line for line in lines if line.startswith("ADD 1 TO "))[9:]
    assert f"WHEN {tally} = 1" in lines
    assert f"WHEN {tally} = 2" in lines
    second = lines.index(f"WHEN {tally} = 2")
    assert lines[second + 1 : second + 3] == [
        'MOVE "C2" TO WS-CUST-ID',
        "MOVE 0 TO WS-RESP",
    ]
    # The first WHEN OTHER is the rows-exhausted branch (TERMINAL); the
    # last is the unmocked-case trap.
    inner = lines.index("WHEN OTHER")
    assert lines[inner + 1] == "MOVE 20 TO WS-RESP"
    assert "SQLCODE" not in "\n".join(lines)


def test_dfhresp_in_mock_body_setup_and_expect_is_expanded():
    suite = parse_cut("""\
TESTSUITE "s"

TESTCASE "c"
    MOVE DFHRESP(NORMAL) TO WS-RESP
    MOCK CICS "READ"
        MOVE DFHRESP(NOTFND) TO WS-RESP
        DISPLAY "DFHRESP(NOTFND) stays in strings" *> DFHRESP(BOGUS) ok
    END-MOCK
    PERFORM 1000-LOOKUP-CUSTOMER
    EXPECT WS-RESP TO BE DFHRESP(NOTFND)
""")
    case = suite.test_cases[0]
    assert case.mocks[0].body_lines[0] == "MOVE 13 TO WS-RESP"
    assert '"DFHRESP(NOTFND) stays in strings"' in case.mocks[0].body_lines[1]
    assert "DFHRESP(BOGUS)" in case.mocks[0].body_lines[1]
    assert case.setup_moves == [("0", "WS-RESP")]
    assert "DFHRESP" not in repr(case.expectations)
    assert "13" in repr(case.expectations)


def test_unknown_dfhresp_condition_is_a_parse_error():
    bad = """\
TESTSUITE "s"

TESTCASE "c"
    MOCK CICS "READ"
        MOVE DFHRESP(NOTAREALONE) TO WS-RESP
    END-MOCK
    PERFORM P
"""
    with pytest.raises(CutParseError, match=r"line 5: DFHRESP\(NOTAREALONE\)"):
        parse_cut(bad)


def test_comment_lines_are_not_expanded_or_checked():
    parse_cut("""\
TESTSUITE "s"
*> DFHRESP(WHATEVER) in a comment is fine

TESTCASE "c"
    PERFORM P
""")


@pytest.mark.parametrize(
    "text, expected, unknown",
    [
        ("MOVE dfhresp( normal ) TO X", "MOVE 0 TO X", []),
        ("MOVE 'DFHRESP(NOTFND)' TO X", "MOVE 'DFHRESP(NOTFND)' TO X", []),
        ("MOVE DFHRESP(NOPE) TO X", "MOVE DFHRESP(NOPE) TO X", ["NOPE"]),
        ("MOVE X-DFHRESP(NORMAL) TO X", "MOVE X-DFHRESP(NORMAL) TO X", []),
    ],
)
def test_expand_dfhresp_text(text, expected, unknown):
    assert expand_dfhresp_text(text) == (expected, unknown)
