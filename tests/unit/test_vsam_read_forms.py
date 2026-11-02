"""VSAM files are mocked per READ form (2026-11-02): a browse (READ NEXT /
PREVIOUS) and a keyed lookup of one KSDS each get their own MOCK, rows and
tally; a keyed READ keeps the key the program asked for; a failed READ
returns its status and no record; a loop-end count is not asserted for a
browse the case may never reach."""

from __future__ import annotations

from pathlib import Path

import pytest
from cobolparser import parse_cobol
from cobolparser.analysis.constraints import ConstraintReport

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import matching_directives
from mockymock.cli.main import main
from mockymock.dsl.model import (
    MockCategory,
    MockDirective,
    read_access_matches,
    split_read_access,
)
from mockymock.dsl.parser import CutParseError, parse_cut

SAMPLES = Path(__file__).resolve().parents[2] / "examples" / "oraclemix" / "src"

#: cobol-parser's file-status scenario family (one case per FILE STATUS code
#: a statement is tested for) came with `ConstraintReport.statement_sites`;
#: the published release the compat job installs may predate it.
needs_file_status_scenarios = pytest.mark.skipif(
    not hasattr(ConstraintReport(), "statement_sites"),
    reason="installed cobolparser has no file-status scenario family",
)


def _surface(name: str):
    result = parse_cobol((SAMPLES / f"{name}.cbl").read_text())
    assert result.ast is not None
    return analyze(result.ast)


def _generate(tmp_path: Path, name: str) -> str:
    source = tmp_path / f"{name}.cbl"
    source.write_text((SAMPLES / f"{name}.cbl").read_text())
    out = tmp_path / f"{name}.cut"
    assert main(["generate", str(source), "-o", str(out), "--scenarios", "all"]) == 0
    return out.read_text()


def _case(cut: str, name: str) -> str:
    start = cut.index(f'TESTCASE "{name}"')
    end = cut.find("\nTESTCASE ", start + 1)
    return cut[start : end if end != -1 else len(cut)]


def _mock(text: str, header: str) -> list[str]:
    start = text.index(header + "\n")
    return [
        line.strip()
        for line in text[start : text.index("END-MOCK", start)].splitlines()[1:]
        if line.strip()
    ]


class TestDsl:
    def test_mock_and_verify_take_a_read_form(self):
        suite = parse_cut(
            'TESTSUITE "S"\n'
            'TESTCASE "c"\n'
            "    MOCK READ CUST-KSDS NEXT ROWS\n"
            "        ( CK-ID = 1 )\n"
            "    END-MOCK\n"
            "    MOCK READ cust-ksds KEY CK-BRANCH\n"
            "    END-MOCK\n"
            "    MOCK READ CUST-KSDS\n"
            "    END-MOCK\n"
            "    PERFORM P\n"
            "    VERIFY READ CUST-KSDS PREVIOUS WAS CALLED ONCE\n"
        )
        case = suite.test_cases[0]
        assert [m.key for m in case.mocks] == [
            "CUST-KSDS NEXT",
            "CUST-KSDS KEY CK-BRANCH",
            "CUST-KSDS",
        ]
        assert {m.file_key for m in case.mocks} == {"CUST-KSDS"}
        assert case.mocks[0].rows == [[("CK-ID", "1")]]
        assert case.verifications[0].key == "CUST-KSDS PREVIOUS"

    def test_only_read_takes_a_form(self):
        with pytest.raises(CutParseError, match="only MOCK READ"):
            parse_cut(
                'TESTSUITE "S"\nTESTCASE "c"\n    MOCK WRITE OUT-REC NEXT\n'
                "    END-MOCK\n"
            )

    def test_split_and_match(self):
        assert split_read_access("F KEY X") == ("F", "KEY X")
        assert split_read_access("F") == ("F", None)
        assert read_access_matches("KEY", "KEY X")
        assert read_access_matches("KEY", "KEY")
        assert not read_access_matches("KEY X", "KEY")
        assert not read_access_matches("NEXT", "PREVIOUS")


class TestReadForms:
    def test_each_read_of_a_dynamic_ksds_has_its_form(self):
        forms = {
            site.line: site.read_form
            for site in _surface("VSKSDSD").boundary_sites
            if site.category is MockCategory.READ and site.keys == ("CUST-KSDS",)
        }
        assert sorted(forms.values()) == ["KEY CK-BRANCH", "NEXT", "PREVIOUS"]

    def test_a_random_ksds_read_is_keyed_and_a_sequential_file_next(self):
        forms = {
            site.keys[0]: site.read_form
            for site in _surface("VSKSDSR").boundary_sites
            if site.category is MockCategory.READ
        }
        assert forms == {"TRAN-FILE": "NEXT", "ACCT-KSDS": "KEY"}

    def test_the_most_specific_mock_answers(self):
        surface = _surface("VSKSDSD")
        mocks = [
            MockDirective(MockCategory.READ, "CUST-KSDS"),
            MockDirective(MockCategory.READ, "CUST-KSDS NEXT"),
            MockDirective(MockCategory.READ, "CUST-KSDS KEY"),
            MockDirective(MockCategory.READ, "CUST-KSDS KEY CK-BRANCH"),
        ]
        answered = {
            site.read_form: [d.key for d in matching_directives(mocks, site)]
            for site in surface.boundary_sites
            if site.category is MockCategory.READ and site.keys == ("CUST-KSDS",)
        }
        assert answered == {
            "NEXT": ["CUST-KSDS NEXT"],
            "PREVIOUS": ["CUST-KSDS"],
            "KEY CK-BRANCH": ["CUST-KSDS KEY CK-BRANCH"],
        }


class TestGenerate:
    def test_browse_and_lookup_get_their_own_mock(self, tmp_path):
        cut = _generate(tmp_path, "VSKSDSD")
        happy = _case(cut, "happy path")
        for form in ("NEXT", "PREVIOUS", "KEY CK-BRANCH"):
            assert f"MOCK READ CUST-KSDS {form}\n" in happy
        assert "MOCK READ CUST-KSDS\n" not in happy
        # The lookup keeps the alternate key the program asked for.
        lookup = _mock(happy, "    MOCK READ CUST-KSDS KEY CK-BRANCH")
        assert not any("TO CK-BRANCH" in line for line in lookup)
        assert any("TO CK-ID" in line for line in lookup)

    def test_a_failed_keyed_read_returns_its_status_only(self, tmp_path):
        cut = _generate(tmp_path, "VSKSDSD")
        case = _case(cut, "error status: READ CUST-KSDS INVALID KEY")
        assert _mock(case, "    MOCK READ CUST-KSDS KEY CK-BRANCH") == [
            'MOVE "23" TO WS-CUST-FS'
        ]
        # A browse cannot return INVALID KEY: it still reads to end of file.
        browse = _mock(case, "    MOCK READ CUST-KSDS NEXT")
        assert '"23"' not in " ".join(browse)
        assert any('MOVE "10" TO WS-CUST-FS' in line for line in browse)

    @needs_file_status_scenarios
    def test_a_duplicate_alternate_key_comes_with_its_record(self, tmp_path):
        cut = _generate(tmp_path, "VSKSDSD")
        case = _case(cut, "file status 02: READ CUST-KSDS")
        lookup = _mock(case, "    MOCK READ CUST-KSDS KEY CK-BRANCH")
        assert 'MOVE "02" TO WS-CUST-FS' in lookup
        assert any("TO CK-NAME" in line for line in lookup)

    @needs_file_status_scenarios
    def test_tested_statuses_get_a_case_at_their_statement(self, tmp_path):
        cut = _generate(tmp_path, "VSKSDSR")
        read = _case(cut, "file status 23: READ ACCT-KSDS")
        assert _mock(read, "    MOCK READ ACCT-KSDS") == ['MOVE "23" TO WS-ACCT-FS']
        rewrite = _case(cut, "file status 23: REWRITE ACCT-REC")
        assert _mock(rewrite, "    MOCK REWRITE ACCT-REC") == ['FILE-STATUS IS "23"']
        write = _case(cut, "error status: WRITE ACCT-REC INVALID KEY")
        assert _mock(write, "    MOCK WRITE ACCT-REC") == ['FILE-STATUS IS "22"']

    def test_a_browse_loop_count_is_not_asserted_where_it_may_not_run(self, tmp_path):
        cut = _generate(tmp_path, "VSCICS")
        assert 'VERIFY CICS "READNEXT" WAS CALLED 2 TIMES' not in cut
