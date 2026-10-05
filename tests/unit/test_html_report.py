"""mockymock.report.html_report: the self-contained HTML page."""

import shutil
from pathlib import Path

from mockymock.report.html_report import render_html
from mockymock.report.test_report import ReportOptions, build_report

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _report(tmp_path, cut_text=None):
    shutil.copy(EXAMPLES / "ordrproc" / "ORDRPROC.cbl", tmp_path / "ORDRPROC.cbl")
    cut = (EXAMPLES / "ordrproc" / "ORDRPROC.cut").read_text(encoding="utf-8")
    (tmp_path / "ORDRPROC.cut").write_text(cut_text or cut, encoding="utf-8")
    return build_report(
        ReportOptions(
            program=tmp_path / "ORDRPROC.cbl",
            cut=tmp_path / "ORDRPROC.cut",
            probe_toolchain=False,
            scenarios="none",
        )
    )


def test_standalone_page_is_a_full_document_with_every_section(tmp_path):
    page = render_html(_report(tmp_path))
    assert page.startswith("<!doctype html>")
    assert "<title>ORDRPROC test report</title>" in page
    for heading in (
        "Findings",
        "Test cases",
        "How the verdict was reached",
        "Assistant journal",
        "Paragraphs",
        "Business rules",
        "Program analysis",
        "GnuCOBOL vs IBM COBOL risks",
        "Verification levels",
    ):
        assert f">{heading}</h2>" in page


def test_fragment_has_no_document_wrapper(tmp_path):
    fragment = render_html(_report(tmp_path), standalone=False)
    assert "<!doctype" not in fragment.lower()
    assert "<body" not in fragment
    assert fragment.startswith("<title>")


def test_page_makes_no_network_requests(tmp_path):
    page = render_html(_report(tmp_path))
    assert "http://" not in page
    assert "https://" not in page


def test_values_from_the_cut_file_are_escaped(tmp_path):
    cut = (EXAMPLES / "ordrproc" / "ORDRPROC.cut").read_text(encoding="utf-8")
    cut = cut.replace(
        '"Zero discount leaves amount unchanged"', '"<script>alert(1)</script>"'
    )
    page = render_html(_report(tmp_path, cut))
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_not_run_suite_says_so_in_the_verdict(tmp_path):
    page = render_html(_report(tmp_path))
    assert "has not been run here" in page
