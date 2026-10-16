"""Issue #195: `EXEC SQL WHENEVER` is a precompiler declaration, not a
runtime SQL boundary. mockymock emulates it -- the declaration is spliced
to CONTINUE and the `IF SQLCODE ... GO TO` check DB2 generates follows
every later SQL dispatch -- instead of asking for a mock that clobbers
SQLCODE and loses the GO TO."""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.sql_whenever import parse_whenever
from mockymock.cli.main import main
from mockymock.dsl.model import MockCategory, MockDirective, MockTestCase, MockTestSuite
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import (
    annotate_nested_sites,
    collect_boundaries,
    collect_scope_map,
)

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WHENPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-NAME   PIC X(10).
       01  WS-STATUS PIC X(4).
       PROCEDURE DIVISION.
       GET-NAME.
           EXEC SQL WHENEVER SQLERROR GO TO SQL-ERR END-EXEC
           EXEC SQL WHENEVER NOT FOUND GO TO NOT-FOUND END-EXEC
           EXEC SQL SELECT NAME INTO :WS-NAME FROM CUST WHERE ID = 1
           END-EXEC
           EXEC SQL WHENEVER SQLERROR CONTINUE END-EXEC
           EXEC SQL UPDATE CUST SET NAME = 'X' END-EXEC
           MOVE "OK" TO WS-STATUS
           GO TO GET-NAME-EXIT.
       NOT-FOUND.
           MOVE "NF" TO WS-STATUS
           GO TO GET-NAME-EXIT.
       SQL-ERR.
           EXEC SQL ROLLBACK END-EXEC
           MOVE "ERR" TO WS-STATUS.
       GET-NAME-EXIT.
           EXIT.
"""

CUT = """\
TESTSUITE "w"
TESTCASE "select fails -> error handler"
    MOCK SQL "SELECT"
        MOVE -911 TO SQLCODE
    END-MOCK
    MOCK SQL "UPDATE"
        MOVE 0 TO SQLCODE
    END-MOCK
    MOCK SQL "ROLLBACK"
        MOVE 0 TO SQLCODE
    END-MOCK
    PERFORM GET-NAME THRU GET-NAME-EXIT
    EXPECT WS-STATUS TO BE "ERR"
"""


def _surface():
    result = parse_cobol(SOURCE, filename="whenpgm.cbl")
    assert result.success, result.errors
    return result.ast, analyze(result.ast)


def test_parse_whenever_forms():
    assert parse_whenever("WHENEVER SQLERROR GO TO SQL-ERR") == parse_whenever(
        "WHENEVER  SQLERROR  GOTO :sql-err"
    )
    assert parse_whenever("WHENEVER NOT FOUND CONTINUE").condition == "NOT FOUND"
    assert parse_whenever("WHENEVER NOT FOUND CONTINUE").target is None
    assert parse_whenever("WHENEVER SQLWARNING GO TO W").target == "W"
    assert parse_whenever("WHENEVER SQLERROR DO BREAK").problem


def test_whenever_is_no_boundary_and_later_sql_carries_its_checks():
    _, surface = _surface()
    texts = [site.match_text for site in surface.boundary_sites]
    assert not any(text and text.startswith("WHENEVER") for text in texts)
    assert len(surface.whenever_sites) == 3
    by_text = {
        (site.match_text or "").split()[0]: site.whenever_checks
        for site in surface.boundary_sites
    }
    assert by_text["SELECT"] == (("SQLERROR", "SQL-ERR"), ("NOT FOUND", "NOT-FOUND"))
    # WHENEVER SQLERROR CONTINUE switched the SQLERROR check off.
    assert by_text["UPDATE"] == (("NOT FOUND", "NOT-FOUND"),)


def test_splice_replaces_whenever_and_follows_the_dispatch_with_its_go_to():
    ast, surface = _surface()
    case = MockTestCase(
        name="c",
        mocks=[MockDirective(MockCategory.SQL, "SELECT", ["MOVE -911 TO SQLCODE"])],
        perform_target="GET-NAME",
    )
    suite = MockTestSuite(name="S", test_cases=[case])
    lines = normalize_fixed_format(SOURCE.splitlines()).splitlines()
    annotate_nested_sites(surface, collect_scope_map(ast, lines), lines)
    spliced = [
        line.strip()
        for line in splice_program(
            lines, collect_boundaries(ast), surface, suite, TallyRegistry(suite)
        )
    ]
    live = [line for line in spliced if not line.startswith("*")]
    assert not any("WHENEVER" in line for line in live)
    end = live.index("END-EVALUATE")
    assert live[end + 1 : end + 7] == [
        "IF SQLCODE < 0",
        "GO TO SQL-ERR",
        "END-IF",
        "IF SQLCODE = 100",
        "GO TO NOT-FOUND",
        "END-IF",
    ]


def _write(tmp_path, source=SOURCE, cut=CUT):
    cbl = tmp_path / "WHENPGM.cbl"
    cbl.write_text(source)
    cut_path = tmp_path / "WHENPGM.cut"
    cut_path.write_text(cut)
    return cbl, cut_path


def test_lint_needs_no_whenever_mock(tmp_path, capsys):
    cbl, cut = _write(tmp_path)
    assert main(["lint", str(cbl), "--cut", str(cut)]) == 0, capsys.readouterr().out


def test_handler_reached_only_through_whenever_must_be_mocked(tmp_path, capsys):
    """SQL-ERR's ROLLBACK is reachable only through the WHENEVER GO TO:
    the reachability walk follows it like a written GO TO."""
    cbl, cut = _write(
        tmp_path,
        cut=CUT.replace(
            '    MOCK SQL "ROLLBACK"\n        MOVE 0 TO SQLCODE\n    END-MOCK\n', ""
        ),
    )
    assert main(["lint", str(cbl), "--cut", str(cut)]) == 1
    out = capsys.readouterr().out
    assert "UNMOCKED_SQL" in out and "ROLLBACK" in out


def test_a_whenever_mock_is_refused_with_the_reason(tmp_path, capsys):
    cbl, cut = _write(
        tmp_path,
        cut=CUT.replace(
            '    MOCK SQL "SELECT"\n',
            '    MOCK SQL "WHENEVER"\n        MOVE 0 TO SQLCODE\n    END-MOCK\n'
            '    MOCK SQL "SELECT"\n',
        ),
    )
    assert main(["lint", str(cbl), "--cut", str(cut)]) == 1
    out = capsys.readouterr().out
    assert "UNMATCHED_MOCK" in out and "precompiler declaration" in out


def test_an_unreadable_whenever_is_refused(tmp_path, capsys):
    cbl, cut = _write(
        tmp_path,
        source=SOURCE.replace(
            "WHENEVER NOT FOUND GO TO NOT-FOUND", "WHENEVER NOT FOUND DO BREAK"
        ),
    )
    assert main(["lint", str(cbl), "--cut", str(cut)]) == 1
    assert "UNSUPPORTED_SQL_WHENEVER" in capsys.readouterr().out


def test_generate_scaffolds_no_whenever_mock(tmp_path, capsys):
    cbl, _ = _write(tmp_path)
    out_cut = tmp_path / "gen.cut"
    assert main(["generate", str(cbl), "--per-paragraph", "-o", str(out_cut)]) == 0
    assert "WHENEVER" not in out_cut.read_text()
