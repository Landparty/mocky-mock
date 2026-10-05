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


def test_next_steps_lead_with_running_the_suite_when_it_was_not_run(tmp_path):
    page = render_html(_report(tmp_path))
    assert ">What to do next</h2>" in page
    next_box = page.split('id="h-next"', 1)[1].split("</section>", 1)[0]
    assert "Run the tests to prove them" in next_box
    assert "--execute --mutate" in next_box


def test_findings_use_plain_labels_and_say_what_to_do(tmp_path):
    report = _report(tmp_path)
    report["findings"] = [
        {
            "severity": "medium",
            "category": "untested-paragraph",
            "title": "No test reaches X",
            "detail": "",
            "line": 9,
        }
    ]
    page = render_html(report)
    findings = page.split('id="h-findings"', 1)[1].split("</section>", 1)[0]
    assert "Should fix" in findings
    assert "Paragraph no test reaches" in findings
    assert 'title="untested-paragraph"' in findings  # machine name kept
    assert "What to do: Add a TESTCASE that PERFORMs it." in findings


def test_finding_items_render_as_a_list(tmp_path):
    report = _report(tmp_path)
    report["findings"] = [
        {
            "severity": "info",
            "category": "scenario-gap",
            "title": "Branches",
            "detail": "a; b",
            "items": ["A line 3 (ELSE branch): x", "<b>"],
        }
    ]
    page = render_html(report)
    assert "<li>A line 3 (ELSE branch): x</li>" in page
    assert "<li>&lt;b&gt;</li>" in page


def test_page_has_a_section_nav_and_a_glossary(tmp_path):
    page = render_html(_report(tmp_path))
    assert '<nav class="toc"' in page
    assert 'href="#h-findings"' in page
    assert ">Words used in this report</h2>" in page
    assert "<dt>Mutation score</dt>" in page


def test_identical_findings_fold_into_one_card(tmp_path):
    report = _report(tmp_path)
    same = {
        "severity": "high",
        "category": "refused",
        "title": "The suite is refused before it can run",
    }
    report["findings"] = [
        {**same, "detail": "unmocked CALL A"},
        {**same, "detail": "unmocked CALL B"},
        {**same, "detail": "unmocked CALL A"},
    ]
    page = render_html(report)
    findings = page.split('id="h-findings"', 1)[1].split("</section>", 1)[0]
    assert findings.count('<article class="finding') == 1
    assert "(2 reasons)" in findings
    assert "<li>unmocked CALL A</li>" in findings
    assert "<li>unmocked CALL B</li>" in findings
