"""Cross-feature composition: BEFORE-EACH/BEFORE-ALL desugaring combined
with PROVIDER row expansion.

parse_cut applies `_apply_before_blocks` before `_expand_providers` (see
the module docstring in mockymock/dsl/parser.py) so every row case
instantiated from a PROVIDER-bound TESTCASE inherits the fully-resolved
BEFORE-block mocks, including FILE-STATUS, and TESTCASE-level overrides
still win. These tests pin that composition so a future refactor can't
silently flip the order."""

from mockymock.dsl.model import MockCategory
from mockymock.dsl.parser import parse_cut

BEFORE_EACH_PROVIDER_CUT = """\
TESTSUITE "before-each with provider"

BEFORE-EACH
    MOCK OPEN FILE1
        MOVE "shared" TO WS-FIELD
    END-MOCK
END-BEFORE

PROVIDER StateNames
    HEADER Abbreviation, Name
    ROW "AZ", "Arizona"
    ROW "KY", "Kentucky"

TESTCASE "lookup state" USING PROVIDER StateNames
    MOVE {Abbreviation} TO WS-STATE-CODE
    PERFORM LOOKUP-STATE
    EXPECT WS-STATE-NAME TO BE {Name}
    VERIFY OPEN FILE1 WAS PERFORMED ONCE
"""


def test_before_each_mock_appears_in_every_expanded_provider_row():
    suite = parse_cut(BEFORE_EACH_PROVIDER_CUT)
    assert len(suite.test_cases) == 2
    for case in suite.test_cases:
        keys = {(m.category, m.key) for m in case.mocks}
        assert (MockCategory.OPEN, "FILE1") in keys


def test_verify_against_before_each_mock_resolves_in_every_expanded_row():
    suite = parse_cut(BEFORE_EACH_PROVIDER_CUT)
    for case in suite.test_cases:
        verification = case.verifications[0]
        assert verification.category is MockCategory.OPEN
        assert verification.key == "FILE1"


def test_placeholder_substitution_in_rows_leaves_inherited_mock_body_untouched():
    suite = parse_cut(BEFORE_EACH_PROVIDER_CUT)
    first, second = suite.test_cases

    # MOVE/EXPECT values are substituted per row...
    assert first.setup_moves == [('"AZ"', "WS-STATE-CODE")]
    assert second.setup_moves == [('"KY"', "WS-STATE-CODE")]
    assert first.expectations[0].expected_value == '"Arizona"'
    assert second.expectations[0].expected_value == '"Kentucky"'

    # ...while the inherited BEFORE-EACH mock body is untouched and
    # identical across every expanded row.
    for case in suite.test_cases:
        mock = next(m for m in case.mocks if m.key == "FILE1")
        assert mock.body_lines == ['MOVE "shared" TO WS-FIELD']


BEFORE_ALL_PROVIDER_CUT = """\
TESTSUITE "before-all with provider"

BEFORE-ALL
    MOCK OPEN FILE1
        MOVE "from-all" TO WS-FIELD
    END-MOCK
END-BEFORE

PROVIDER Nums
    HEADER N
    ROW 1
    ROW 2

TESTCASE "override wins" USING PROVIDER Nums
    MOCK OPEN FILE1
        MOVE "from-testcase" TO WS-FIELD
    END-MOCK
    MOVE {N} TO WS-N
    PERFORM MAIN-PROCESS
"""


def test_before_all_mock_appears_in_every_expanded_provider_row():
    suite = parse_cut(BEFORE_ALL_PROVIDER_CUT)
    assert len(suite.test_cases) == 2
    for case in suite.test_cases:
        keys = {(m.category, m.key) for m in case.mocks}
        assert (MockCategory.OPEN, "FILE1") in keys


def test_testcase_mock_overrides_before_all_mock_inside_expanded_rows():
    suite = parse_cut(BEFORE_ALL_PROVIDER_CUT)
    assert len(suite.test_cases) == 2
    for case in suite.test_cases:
        opens = [m for m in case.mocks if m.key == "FILE1"]
        # the BEFORE-ALL mock for the same (category, key) is shadowed,
        # not appended alongside the testcase's own override.
        assert len(opens) == 1
        assert opens[0].body_lines == ['MOVE "from-testcase" TO WS-FIELD']


PROVIDER_FILE_STATUS_CUT = """\
TESTSUITE "file status with provider"

BEFORE-EACH
    MOCK READ FILE1
        FILE-STATUS IS FILE-NOT-FOUND
    END-MOCK
END-BEFORE

PROVIDER Nums
    HEADER N
    ROW 1
    ROW 2
    ROW 3

TESTCASE "reads" USING PROVIDER Nums
    MOVE {N} TO WS-N
    PERFORM MAIN-PROCESS
"""


def test_file_status_survives_before_each_and_provider_expansion():
    suite = parse_cut(PROVIDER_FILE_STATUS_CUT)
    assert len(suite.test_cases) == 3
    for case in suite.test_cases:
        mock = next(m for m in case.mocks if m.key == "FILE1")
        assert mock.file_status == "35"
