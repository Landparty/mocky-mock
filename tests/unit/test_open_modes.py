"""OPEN statements are mocked per mode when one file is opened in several
(2026-11-02 review): `MOCK OPEN <file> EXTEND` fails the OPEN EXTEND that
finds the log missing (35) while the OPEN OUTPUT that then creates it, and
the OPEN INPUT that reads it back, succeed. A multi-file OPEN failing one
of its files sets that file's FILE STATUS, not the first file's."""

from __future__ import annotations

from pathlib import Path

import pytest
from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import matching_directives
from mockymock.cli.main import main
from mockymock.dsl.fixture_bundle import BoundaryFixture
from mockymock.dsl.generator import _merged_status_only_body, split_open_files
from mockymock.dsl.model import MockCategory, MockDirective, split_read_access
from mockymock.dsl.parser import CutParseError, parse_cut

SAMPLES = Path(__file__).resolve().parents[2] / "examples" / "oraclemix" / "src"


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
    def test_mock_and_verify_take_an_open_mode(self):
        suite = parse_cut(
            'TESTSUITE "S"\n'
            'TESTCASE "c"\n'
            "    MOCK OPEN AUD-ESDS EXTEND\n"
            '        FILE-STATUS IS "35"\n'
            "    END-MOCK\n"
            "    MOCK OPEN aud-esds I-O\n"
            "    END-MOCK\n"
            "    PERFORM P\n"
            "    VERIFY OPEN AUD-ESDS EXTEND WAS CALLED ONCE\n"
        )
        case = suite.test_cases[0]
        assert [m.key for m in case.mocks] == ["AUD-ESDS EXTEND", "AUD-ESDS I-O"]
        assert {m.file_key for m in case.mocks} == {"AUD-ESDS"}
        assert case.verifications[0].key == "AUD-ESDS EXTEND"
        assert split_read_access("AUD-ESDS OUTPUT") == ("AUD-ESDS", "OUTPUT")

    def test_only_open_takes_a_mode(self):
        with pytest.raises(CutParseError, match="only MOCK OPEN"):
            parse_cut(
                'TESTSUITE "S"\nTESTCASE "c"\n    MOCK READ IN-FILE INPUT\n'
                "    END-MOCK\n"
            )

    def test_the_mode_mock_answers_its_open_and_the_bare_one_the_rest(self):
        surface = _surface("VSESDS")
        mocks = [
            MockDirective(MockCategory.OPEN, "AUDIT-ESDS"),
            MockDirective(MockCategory.OPEN, "AUDIT-ESDS EXTEND"),
        ]
        answered = {
            site.open_modes["AUDIT-ESDS"]: [
                d.key for d in matching_directives(mocks, site)
            ]
            for site in surface.boundary_sites
            if site.category is MockCategory.OPEN and site.keys == ("AUDIT-ESDS",)
        }
        assert answered == {
            "EXTEND": ["AUDIT-ESDS EXTEND"],
            "OUTPUT": ["AUDIT-ESDS"],
            "INPUT": ["AUDIT-ESDS"],
        }

    def test_each_file_of_a_multi_file_open_keeps_its_own_mock(self):
        surface = _surface("VSKSDSD")
        site = next(
            s
            for s in surface.boundary_sites
            if s.category is MockCategory.OPEN and len(s.keys) == 2
        )
        assert site.open_modes == {"PARM-FILE": "INPUT", "CUST-KSDS": "INPUT"}
        mocks = [
            MockDirective(MockCategory.OPEN, "PARM-FILE"),
            MockDirective(MockCategory.OPEN, "CUST-KSDS INPUT"),
        ]
        assert [d.key for d in matching_directives(mocks, site)] == [
            "PARM-FILE",
            "CUST-KSDS INPUT",
        ]


class TestGenerate:
    def test_a_file_opened_in_several_modes_gets_a_mock_per_mode(self, tmp_path):
        assert split_open_files(_surface("VSESDS")) == {"AUDIT-ESDS"}
        cut = _generate(tmp_path, "VSESDS")
        happy = _case(cut, "happy path")
        for mode in ("EXTEND", "OUTPUT", "INPUT"):
            assert f"MOCK OPEN AUDIT-ESDS {mode}\n" in happy
        assert "MOCK OPEN AUDIT-ESDS\n" not in happy
        missing = _case(cut, "error status: OPEN AUDIT-ESDS not found")
        assert _mock(missing, "    MOCK OPEN AUDIT-ESDS EXTEND") == [
            'FILE-STATUS IS "35"'
        ]
        # The OPEN OUTPUT that creates the log succeeds.
        assert _mock(missing, "    MOCK OPEN AUDIT-ESDS OUTPUT") == []

    def test_open_output_is_never_failed_with_35(self, tmp_path):
        cut = _generate(tmp_path, "VSESDS")
        for header in ("    MOCK OPEN AUDIT-ESDS OUTPUT",):
            start = 0
            while (start := cut.find(header + "\n", start)) != -1:
                assert _mock(cut[start:], header) == []
                start += 1
        # The ESDS WRITE fails as a full sequential file does.
        write = _case(cut, "file status 34: WRITE AUD-REC")
        assert _mock(write, "    MOCK WRITE AUD-REC") == ['FILE-STATUS IS "34"']

    def test_a_failed_second_file_of_one_open_sets_its_own_status(self, tmp_path):
        cut = _generate(tmp_path, "VSKSDSD")
        case = _case(cut, "error status: OPEN CUST-KSDS not found")
        assert _mock(case, "    MOCK OPEN PARM-FILE") == ['MOVE "35" TO WS-CUST-FS']

    def test_merged_body_keeps_the_directive_file_status_sugar(self):
        def fixture(key: str, field: str, code: str) -> BoundaryFixture:
            return BoundaryFixture(
                category="OPEN",
                key=key,
                paragraph="P",
                line=1,
                direction="STATUS_ONLY",
                layout=[],
                sequence=[],
                terminal=None,
                status={field: code},
            )

        assert _merged_status_only_body(
            [fixture("A", "A-FS", "35"), fixture("B", "B-FS", "00")]
        ) == ['FILE-STATUS IS "35"']
        assert _merged_status_only_body(
            [fixture("A", "A-FS", "00"), fixture("B", "B-FS", "35")]
        ) == ['MOVE "35" TO B-FS']
        assert (
            _merged_status_only_body(
                [fixture("A", "A-FS", "00"), fixture("B", "B-FS", "00")]
            )
            == []
        )
