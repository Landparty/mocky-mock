"""USE REAL CALL: the static side (parser, real-program gate, suite views)
and the codegen side (real CALL dispatch, shared driver state, generate
--real). The compiled behaviour is in tests/integration/test_real_call.py.
See docs/2026-11-01-real-call-integration-design.md."""

from pathlib import Path

import pytest

from mockymock.analysis.real_programs import (
    RealSpec,
    check_real_program,
    collect_real_specs,
    entry_program_view,
    matched_directive_ids,
    prepare_real_program,
)
from mockymock.dsl.model import MockCategory
from mockymock.dsl.module_suite import RealLink, link_real_programs
from mockymock.dsl.parser import CutParseError, parse_cut
from mockymock.engine.checks import run_static_checks
from mockymock.splicer.driver import DriverArtifact
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.real_programs import (
    cancel_lines,
    insert_working_storage,
    share_driver_state,
)

EXAMPLE = Path(__file__).parent.parent.parent / "examples" / "paymod"


def _suite(body: str):
    return parse_cut('TESTSUITE "s"\n' + body)


class TestParser:
    def test_use_real_call_is_a_real_call_directive(self):
        suite = _suite(
            'TESTCASE "a"\n'
            '    USE REAL CALL "PAYCALC" FROM "sub/PAYCALC.cbl"\n'
            "    PERFORM MAIN-PARA\n"
        )
        (directive,) = suite.test_cases[0].mocks
        assert directive.category is MockCategory.CALL
        assert directive.key == "PAYCALC"
        assert directive.real_source == "sub/PAYCALC.cbl"
        assert directive.real_line == 3
        assert directive.is_real
        assert directive.describe() == 'REAL CALL "PAYCALC"'

    def test_before_each_real_call_is_inherited_and_overridable(self):
        suite = _suite(
            "BEFORE-EACH\n"
            '    USE REAL CALL "PAYCALC" FROM "PAYCALC.cbl"\n'
            "END-BEFORE\n"
            'TESTCASE "real"\n'
            "    PERFORM MAIN-PARA\n"
            'TESTCASE "mocked"\n'
            '    MOCK CALL "PAYCALC"\n'
            "    END-MOCK\n"
            "    PERFORM MAIN-PARA\n"
        )
        real, mocked = suite.test_cases
        assert [d.is_real for d in real.mocks] == [True]
        assert [d.is_real for d in mocked.mocks] == [False]

    def test_mock_and_real_of_one_key_in_one_case_is_a_duplicate(self):
        with pytest.raises(CutParseError, match="duplicate MOCK"):
            _suite(
                'TESTCASE "a"\n'
                '    USE REAL CALL "X" FROM "x.cbl"\n'
                '    MOCK CALL "X"\n'
                "    END-MOCK\n"
                "    PERFORM P\n"
            )

    @pytest.mark.parametrize(
        "line, message",
        [
            ('USE REAL CALL WS-PGM FROM "x.cbl"', "malformed USE REAL"),
            ('USE REAL CALL "X"', "malformed USE REAL"),
            ('USE REAL CALL "" FROM "x.cbl"', "empty USE REAL CALL key"),
            ('USE REAL CALL "X" FROM ""', "empty FROM path"),
        ],
    )
    def test_malformed_lines_are_refused(self, line, message):
        with pytest.raises(CutParseError, match=message):
            _suite(f'TESTCASE "a"\n    {line}\n    PERFORM P\n')

    def test_outside_a_case_or_before_block(self):
        with pytest.raises(CutParseError, match="USE REAL outside"):
            _suite('USE REAL CALL "X" FROM "x.cbl"\n')

    def test_not_in_after_hooks(self):
        with pytest.raises(CutParseError, match="not allowed inside AFTER-EACH"):
            _suite('AFTER-EACH\n    USE REAL CALL "X" FROM "x.cbl"\nEND-AFTER\n')


def _paymod_suite(tmp_path: Path, cut: str | None = None):
    for name in ("PAYMAIN.cbl", "PAYCALC.cbl"):
        (tmp_path / name).write_text((EXAMPLE / name).read_text())
    cut_path = tmp_path / "PAYMAIN.cut"
    cut_path.write_text(
        cut if cut is not None else (EXAMPLE / "PAYMAIN.cut").read_text()
    )
    return cut_path


class TestSpecs:
    def test_paths_resolve_against_the_cut_folder(self, tmp_path):
        cut_path = _paymod_suite(tmp_path)
        suite = parse_cut(cut_path.read_text())
        specs, reasons = collect_real_specs(suite, cut_path)
        assert reasons == []
        assert [(s.key, s.source) for s in specs] == [
            ("PAYCALC", (tmp_path / "PAYCALC.cbl").resolve())
        ]

    def test_missing_file(self, tmp_path):
        suite = _suite(
            'TESTCASE "a"\n    USE REAL CALL "X" FROM "x.cbl"\n    PERFORM P\n'
        )
        specs, reasons = collect_real_specs(suite, tmp_path / "s.cut")
        assert specs == []
        assert [r.code for r in reasons] == ["REAL_SOURCE_NOT_FOUND"]

    def test_one_program_two_files(self, tmp_path):
        (tmp_path / "a.cbl").write_text("x")
        (tmp_path / "b.cbl").write_text("x")
        suite = _suite(
            'TESTCASE "a"\n    USE REAL CALL "X" FROM "a.cbl"\n    PERFORM P\n'
            'TESTCASE "b"\n    USE REAL CALL "X" FROM "b.cbl"\n    PERFORM P\n'
        )
        _, reasons = collect_real_specs(suite, tmp_path / "s.cut")
        assert [r.code for r in reasons] == ["CONFLICTING_REAL_SOURCE"]


class TestPrepareAndGate:
    def _prepared(self, tmp_path, key="PAYCALC", name="PAYCALC.cbl"):
        _paymod_suite(tmp_path)
        return prepare_real_program(RealSpec(key, tmp_path / name, 1), None)

    def test_prepares_the_subprogram(self, tmp_path):
        prepared, reasons = self._prepared(tmp_path)
        assert reasons == []
        assert prepared is not None
        assert prepared.program_id == "PAYCALC"
        assert [s.label for s in prepared.surface.boundary_sites if s.category] == [
            "SQL"
        ]

    def test_program_id_must_be_the_call_key(self, tmp_path):
        prepared, reasons = self._prepared(tmp_path, name="PAYMAIN.cbl")
        assert prepared is None
        assert [r.code for r in reasons] == ["REAL_PROGRAM_ID_MISMATCH"]

    def test_every_boundary_must_be_mocked_in_every_real_case(self, tmp_path):
        prepared, _ = self._prepared(tmp_path)
        suite = _suite(
            'TESTCASE "with sql"\n'
            '    USE REAL CALL "PAYCALC" FROM "PAYCALC.cbl"\n'
            '    MOCK SQL "SELECT HOURLY_RATE"\n'
            "    END-MOCK\n"
            "    PERFORM 0000-MAIN\n"
            'TESTCASE "without sql"\n'
            '    USE REAL CALL "PAYCALC" FROM "PAYCALC.cbl"\n'
            "    PERFORM 0000-MAIN\n"
            'TESTCASE "not real"\n'
            '    MOCK CALL "PAYCALC"\n'
            "    END-MOCK\n"
            "    PERFORM 0000-MAIN\n"
        )
        reasons = check_real_program(prepared, suite)
        assert [r.code for r in reasons] == ["UNMOCKED_SQL"]
        assert "'without sql'" in reasons[0].message
        assert reasons[0].suggested_fix.startswith('    MOCK SQL "SELECT"')

    def test_goback_runs_as_written(self, tmp_path):
        prepared, _ = self._prepared(tmp_path)
        assert any(s.label == "GOBACK" for s in prepared.surface.boundary_sites)
        suite = _suite(
            'TESTCASE "a"\n'
            '    USE REAL CALL "PAYCALC" FROM "PAYCALC.cbl"\n'
            '    MOCK SQL "SELECT"\n'
            "    END-MOCK\n"
            "    PERFORM P\n"
        )
        assert check_real_program(prepared, suite) == []

    def test_stop_run_is_a_warning(self, tmp_path):
        source = (
            (EXAMPLE / "PAYCALC.cbl")
            .read_text()
            .replace(
                "               GOBACK\n           END-IF",
                "               STOP RUN\n           END-IF",
            )
        )
        path = tmp_path / "PAYCALC.cbl"
        path.write_text(source)
        prepared, _ = prepare_real_program(RealSpec("PAYCALC", path, 1), None)
        assert prepared is not None
        assert len(prepared.warnings) == 1
        assert "REAL_PROGRAM_STOP_RUN" in prepared.warnings[0]


class TestViews:
    def test_entry_program_view_drops_directives_of_real_programs_only(self, tmp_path):
        cut_path = _paymod_suite(tmp_path)
        suite = parse_cut(cut_path.read_text())
        prepared, _ = prepare_real_program(
            RealSpec("PAYCALC", tmp_path / "PAYCALC.cbl", 1), None
        )
        sub = matched_directive_ids(prepared.surface, suite)
        view = entry_program_view(suite, sub)
        first = view.test_cases[0]
        assert MockCategory.SQL not in {d.category for d in first.mocks}
        assert all(v.category is not MockCategory.SQL for v in first.verifications)
        # The full suite keeps everything: the driver and splicer use it.
        assert MockCategory.SQL in {d.category for d in suite.test_cases[0].mocks}

    def test_static_checks_pass_the_example(self, tmp_path):
        cut_path = _paymod_suite(tmp_path)
        checked = run_static_checks(tmp_path / "PAYMAIN.cbl", cut_path, None)
        assert checked.problems == []
        assert [p.program_id for p in checked.real_programs] == ["PAYCALC"]

    def test_static_checks_name_data_of_the_real_program(self, tmp_path):
        cut = (
            (EXAMPLE / "PAYMAIN.cut")
            .read_text()
            .replace("MOVE 20.00 TO WS-RATE", "MOVE 20.00 TO WS-NO-SUCH-RATE")
        )
        cut_path = _paymod_suite(tmp_path, cut)
        checked = run_static_checks(tmp_path / "PAYMAIN.cbl", cut_path, None)
        assert any(
            "UNKNOWN_DATA_NAME" in p and "WS-NO-SUCH-RATE" in p and "PAYCALC" in p
            for p in checked.problems
        )


class TestCodegen:
    def test_share_driver_state_makes_bookkeeping_external(self):
        suite = _suite('TESTCASE "a"\n    MOCK CALL "X"\n    END-MOCK\n    PERFORM P\n')
        registry = TallyRegistry(suite)
        artifact = DriverArtifact(
            working_storage_lines=[
                "01  UT-CURRENT-CASE        PIC X(9).",
                "01  UT-FAIL-COUNT          PIC 9(9) VALUE 0.",
                '01  UT-EARLY-EXIT          PIC X VALUE "N".',
                '01  UT-MOCK-STATUS         PIC XX VALUE "00".',
                "01  UT-X-TALLY      PIC 9(9) VALUE 0.",
                "01  UT-X-BASE      PIC 9(9) VALUE 0.",
            ],
            procedure_lines=["       UT-TESTSUITE-S.", '           DISPLAY "x"'],
        )
        shared, sub_ws = share_driver_state(artifact, registry)
        assert "01  UT-X-TALLY  PIC 9(9) EXTERNAL." in shared.working_storage_lines
        assert "01  UT-X-BASE      PIC 9(9) VALUE 0." in shared.working_storage_lines
        assert '01  UT-MOCK-STATUS         PIC XX VALUE "00".' in (
            shared.working_storage_lines
        )
        assert shared.procedure_lines[:4] == [
            "       UT-TESTSUITE-S.",
            "           MOVE 0 TO UT-FAIL-COUNT",
            '           MOVE "N" TO UT-EARLY-EXIT',
            "           MOVE 0 TO UT-X-TALLY",
        ]
        assert "01  UT-CURRENT-CASE  PIC X(9) EXTERNAL." in sub_ws
        assert sub_ws[-1].startswith("01  UT-MOCK-STATUS")

    def test_cancel_lines(self, tmp_path):
        assert cancel_lines([RealSpec("A", tmp_path, 1)]) == ['CANCEL "A"']

    def test_insert_working_storage_synthesizes_a_section(self):
        lines = [
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. S.",
            "DATA DIVISION.",
            "LINKAGE SECTION.",
            "01  LK PIC X.",
            "PROCEDURE DIVISION USING LK.",
        ]
        out = insert_working_storage(lines, ["01  UT-A PIC X EXTERNAL."])
        assert out[3:5] == [
            "       WORKING-STORAGE SECTION.",
            "       01  UT-A PIC X EXTERNAL.",
        ]

    def test_real_dispatch_runs_the_statement_and_counts_it(self, tmp_path):
        from mockymock.analysis.mock_surface import analyze
        from mockymock.splicer.injector import build_site_dispatch

        prepared, _ = prepare_real_program(
            RealSpec("PAYMAIN", EXAMPLE / "PAYMAIN.cbl", 1), None
        )
        suite = parse_cut((EXAMPLE / "PAYMAIN.cut").read_text())
        registry = TallyRegistry(suite)
        surface = analyze(prepared.ast)
        site = next(s for s in surface.boundary_sites if s.keys == ("PAYCALC",))
        block = build_site_dispatch(
            site,
            suite,
            registry,
            real_statement=['CALL "PAYCALC" USING PAY-AREA'],
        )
        text = "\n".join(block)
        assert 'WHEN "001"' in text and 'WHEN "002"' in text
        # Both cases run the same branch, emitted once (stress test
        # 2026-11-02: one copy per case made HUGE01 uncompilable).
        assert text.count('CALL "PAYCALC" USING PAY-AREA') == 1
        assert text.count("ADD 1 TO UT-PAYCALC-TALLY") == 1


class TestGenerateReal:
    def test_links_the_subprogram(self, tmp_path):
        _paymod_suite(tmp_path)
        prepared, _ = prepare_real_program(
            RealSpec("PAYCALC", tmp_path / "PAYCALC.cbl", 0), None
        )
        cut = (
            'TESTSUITE "PAYMAIN"\n\n'
            'TESTCASE "happy path"\n'
            '    MOCK CALL "PAYCALC"\n'
            "        CAPTURE ARG 1 INTO UT-CAP-PAYCALC-1\n"
            "        MOVE 1 TO PA-RC\n"
            "    END-MOCK\n"
            "    PERFORM 0000-MAIN\n"
            "    *> STUB EXPECT UT-CAP-PAYCALC-1 -- the value passed\n"
            '    VERIFY CALL "PAYCALC" WAS CALLED 1 TIMES\n'
        )
        text, notes = link_real_programs(
            cut, [RealLink(prepared)], tmp_path / "tests" / "PAYMAIN.cut"
        )
        assert 'USE REAL CALL "PAYCALC" FROM "../PAYCALC.cbl"' in text
        assert 'MOCK CALL "PAYCALC"' not in text
        assert "UT-CAP-PAYCALC-1" not in text
        assert 'VERIFY CALL "PAYCALC" WAS CALLED 1 TIMES' in text
        assert '    MOCK SQL "SELECT"' in text
        assert text.index("BEFORE-EACH") < text.index("TESTCASE")
        assert "1 MOCK CALL block(s) replaced" in notes[0]
        parse_cut(text)  # still a valid suite


ORACLEMIX = Path(__file__).parent.parent.parent / "examples" / "oraclemix" / "src"

_DYNDRV_CUT = """TESTSUITE "DYNDRV"

BEFORE-EACH
    USE REAL CALL "RATECALC" FROM "RATECALC.cbl"
END-BEFORE

TESTCASE "rated"
    MOCK OPEN INV-IN
    END-MOCK
    MOCK OPEN INV-OUT
    END-MOCK
    MOCK READ INV-IN
        MOVE "10" TO UT-MOCK-STATUS
    END-MOCK
    MOCK CLOSE INV-IN
    END-MOCK
    MOCK CLOSE INV-OUT
    END-MOCK
    MOCK CALL WS-RATE-PGM
    END-MOCK
    MOCK WRITE INV-OUT-REC
    END-MOCK
    PERFORM 0000-MAIN
"""


class TestRealDynamicCall:
    """A USE REAL CALL program reached only through a dynamic CALL
    (docs/2026-11-02-real-dynamic-call-design.md)."""

    def _cut(self, tmp_path, cut=_DYNDRV_CUT):
        for name in ("DYNDRV.cbl", "RATECALC.cbl"):
            (tmp_path / name).write_text((ORACLEMIX / name).read_text())
        cut_path = tmp_path / "DYNDRV.cut"
        cut_path.write_text(cut)
        return cut_path

    def test_the_real_directive_is_used_by_the_dynamic_call(self, tmp_path):
        cut_path = self._cut(tmp_path)
        checked = run_static_checks(tmp_path / "DYNDRV.cbl", cut_path, None)
        assert checked.problems == []
        assert [p.program_id for p in checked.real_programs] == ["RATECALC"]

    def test_the_dispatch_runs_the_statement_when_the_name_matches(self):
        from cobolparser import parse_cobol

        from mockymock.analysis.mock_surface import analyze
        from mockymock.splicer.injector import build_site_dispatch

        ast = parse_cobol((ORACLEMIX / "DYNDRV.cbl").read_text()).ast
        (site,) = [
            s for s in analyze(ast).boundary_sites if s.category is MockCategory.DYNCALL
        ]
        suite = parse_cut(_DYNDRV_CUT)
        registry = TallyRegistry(suite)
        lines = build_site_dispatch(
            site,
            suite,
            registry,
            real_statement=["CALL WS-RATE-PGM USING WS-RATE-AREA"],
        )
        text = "\n".join(line.strip() for line in lines)
        assert text.startswith('EVALUATE TRUE\nWHEN (UT-CURRENT-CASE = "001"')
        assert 'FUNCTION UPPER-CASE(WS-RATE-PGM)\n= "RATECALC"' in text
        real, mocked = text.split("WHEN OTHER", 1)
        assert "CALL WS-RATE-PGM USING WS-RATE-AREA" in real
        assert "EVALUATE UT-CURRENT-CASE" in mocked
        assert text.endswith("END-EVALUATE\nEND-EVALUATE")


class TestFoundRecordCases:
    """`generate --real` adds a case where a real lookup finds its record."""

    def test_the_lookup_comparison_is_found(self, tmp_path):
        from mockymock.analysis.real_programs import RealSpec, prepare_real_program
        from mockymock.dsl.real_branches import key_matches

        source = tmp_path / "PRTRATE.cbl"
        source.write_text((ORACLEMIX / "PRTRATE.cbl").read_text())
        prepared, reasons = prepare_real_program(RealSpec("PRTRATE", source, 0), None)
        assert reasons == [] and prepared is not None
        (match,) = key_matches(prepared)
        assert (match.file, match.record_field, match.linkage_item) == (
            "RATE-FILE",
            "RATE-PART",
            "LK-PART",
        )

    def test_hex_literal_for_a_byte_no_character_spells(self):
        from mockymock.dsl.generator import _bundle_rendered_value

        assert _bundle_rendered_value("\xf3", "alphanumeric") == "X'F3'"
        assert _bundle_rendered_value("AB", "alphanumeric") == '"AB"'
