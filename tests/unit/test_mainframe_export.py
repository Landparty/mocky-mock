"""Unit tests for mockymock.cli.mainframe_export -- the export-only text
transforms that make the instrumented source z/OS-compilable. See
docs/2026-08-03-mainframe-export-command-design.md for the empirical basis
(spiked against a real cobolparser install and a real GnuCOBOL container
before this code was written)."""
from mockymock.cli.mainframe_export import (
    build_provenance_header,
    insert_provenance_header,
    restore_fixed_format_columns,
)


def test_restore_fixed_format_columns_prepends_seven_spaces():
    lines = ["IDENTIFICATION DIVISION.", "", "PROGRAM-ID. X."]
    result = restore_fixed_format_columns(lines)
    assert result == [
        "       IDENTIFICATION DIVISION.",
        "       ",
        "       PROGRAM-ID. X.",
    ]


def test_restore_fixed_format_columns_preserves_line_count():
    lines = ["A"] * 50
    assert len(restore_fixed_format_columns(lines)) == 50


def test_provenance_header_lines_all_fit_within_72_columns():
    header = build_provenance_header("PROG.cbl", "PROG.cut")
    assert all(len(line) <= 72 for line in header)


def test_provenance_header_names_source_files_by_basename_only():
    header = build_provenance_header(
        "C:/very/deeply/nested/workspace/path/PROG.cbl",
        "C:/very/deeply/nested/workspace/path/PROG.cut",
    )
    joined = "\n".join(header)
    assert "PROG.cbl" in joined
    assert "PROG.cut" in joined
    assert "very/deeply/nested" not in joined


def test_provenance_header_mentions_mock_only_and_finding_1():
    header = "\n".join(build_provenance_header("P.cbl", "P.cut"))
    assert "MOCK-ONLY" in header
    assert "real-world-readiness-audit" in header


def test_insert_provenance_header_lands_before_identification_division():
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. X.",
    ]
    header = ["      *> header line 1", "      *> header line 2", ""]
    result = insert_provenance_header(lines, header)
    assert result == [
        "      *> header line 1",
        "      *> header line 2",
        "",
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. X.",
    ]


def test_insert_provenance_header_lands_after_a_preserved_directive():
    """PROCESS/CBL directives must precede IDENTIFICATION DIVISION -- the
    header must not be inserted between a preserved directive and it."""
    lines = [
        "       CBL APOST",
        "       IDENTIFICATION DIVISION.",
    ]
    header = ["      *> header", ""]
    result = insert_provenance_header(lines, header)
    assert result == [
        "       CBL APOST",
        "      *> header",
        "",
        "       IDENTIFICATION DIVISION.",
    ]
