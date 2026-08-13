"""Standing malformed/adversarial-input regression net for the
pure-Python entry points that parse externally-authored or
externally-produced text: a `.cut` file a contributor hand-wrote, and a
compiled test binary's own stdout.

Most individual malformed shapes already have dedicated, well-named tests
elsewhere (test_dsl_parser*.py, test_fixture_bundle.py, test_report.py,
test_skills_cmd.py -- several of them regression tests for specific
findings from the 2026-08-10/2026-08-12 framework audits). This file is
deliberately not another one-shape-per-test file: it exists so the
"garbage input must never surface an untyped exception" CONTRACT itself is
checked in one place, parametrized over a wide, adversarial battery
(binary/control bytes, BOM prefixes, pathological repetition/nesting,
oversized numeric fields, empty input) rather than only the specific
shapes a human thought to name. New adversarial cases belong here; a new
SPECIFIC parse behavior (a new error message, a new refusal code) belongs
in the module's own dedicated test file instead.

Two entry points are covered:

- `dsl.parser.parse_cut` must raise `CutParseError` on anything it can't
  parse -- never a bare exception of some other type, never an unbounded
  hang/recursion.
- `report.results.parse_stdout` must never raise at all: a compiled
  binary's stdout is not something mockymock controls the shape of (a
  crash mid-DISPLAY, binary garbage on a mocked ACCEPT echo, truncated
  output from a killed process), so this parser's whole contract is
  fail-soft -- worst case, an empty/partial TestSuiteResult.

A third entry point, `dsl.fixture_bundle.load_fixture_bundle` called
directly with a non-dict value (bypassing `parse_fixture_bundle`'s own
guard), is covered by its own regression test in test_fixture_bundle.py
(`test_load_fixture_bundle_rejects_non_dict_directly`) rather than
repeated here -- it was a genuine gap this sweep surfaced (the
`data.get("bundle_version")` line ran before the function's try/except,
so was invisible to the 2026-08-12 audit's otherwise-thorough Finding 15
fix), now closed with a type check at the top of the function.
"""

import pytest

from mockymock.dsl.parser import CutParseError, parse_cut
from mockymock.report.results import parse_stdout

# --- parse_cut: always CutParseError, never anything else, never a hang ---

MALFORMED_CUT_INPUTS = [
    pytest.param("", id="empty"),
    pytest.param("   \n\n\t\n", id="whitespace-only"),
    pytest.param("\x00" * 500, id="null-bytes"),
    pytest.param('﻿TESTSUITE "x"\n', id="bom-prefixed"),
    pytest.param('TESTSUITE "x"' * 100, id="one-giant-line-no-newlines"),
    pytest.param(
        'TESTSUITE "x"\n' + ('MOCK CALL "X"\n' * 500),
        id="many-unterminated-mock-opens",
    ),
    pytest.param(
        'TESTSUITE "x"\nTESTCASE "c"\n    EXPECT WS-X(1 TO BE 5\n',
        id="unbalanced-subscript-no-space",
    ),
    pytest.param(
        'TESTSUITE "x"\nTESTCASE "c"\n    MOVE 5 TO WS-TAB(1\n',
        id="unbalanced-subscript-move-target",
    ),
    pytest.param(
        'TESTSUITE "x"\nTESTCASE "c"\n' + ("IF A\n" * 3000),
        id="deeply-repeated-unrecognized-statement",
    ),
    pytest.param("NOT-A-DIRECTIVE AT ALL\n", id="unrecognized-first-line"),
]


@pytest.mark.parametrize("text", MALFORMED_CUT_INPUTS)
def test_parse_cut_never_raises_anything_but_cut_parse_error(text):
    with pytest.raises(CutParseError):
        parse_cut(text)


# --- parse_stdout: never raises at all, on anything ------------------------

ADVERSARIAL_STDOUT_INPUTS = [
    pytest.param("", id="empty"),
    pytest.param("\x00" * 10000, id="null-bytes"),
    pytest.param("__MOCKYMOCK__ " * 5000, id="repeated-bare-prefix"),
    pytest.param(
        "__MOCKYMOCK__ CASE 001 START: a\n" * 3000, id="repeated-duplicate-start"
    ),
    pytest.param("﻿__MOCKYMOCK__ TESTSUITE: x\n", id="bom-prefixed"),
    pytest.param(
        "__MOCKYMOCK__ RECORD 001 " + ("X" * 5000) + ": v\n",
        id="oversized-data-name",
    ),
    pytest.param("ordinary program noise, no markers at all\n" * 200, id="no-markers"),
    pytest.param(
        "__MOCKYMOCK__ SUMMARY: RUN=999999999999999999999 FAILURES=0\n",
        id="oversized-summary-counters",
    ),
    pytest.param(
        "__MOCKYMOCK__ CASE 001 START: \x00\x01 control bytes in a name\n",
        id="control-bytes-in-case-name",
    ),
    pytest.param(
        "__MOCKYMOCK__ CASE  START: missing id\n", id="malformed-case-start-no-id"
    ),
]


@pytest.mark.parametrize("stdout", ADVERSARIAL_STDOUT_INPUTS)
def test_parse_stdout_never_raises(stdout):
    parse_stdout(stdout)  # must not raise; the return value's shape is
    # already covered case-by-case in test_report.py
