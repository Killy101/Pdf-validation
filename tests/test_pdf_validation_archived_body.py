"""Archived publisher controls stay outside document collection and comparison."""
from test_pdf_validation import pdf
from app.services import pdf_validation as service
from app.services.pdf_validation_collection import collect_document
from app.services.pdf_validation_navigation import navigation
from app.services.pdf_validation_source import SourceSnapshot, extract_html


URL = "https://laws.justice.gc.ca/eng/regulations/SOR-2021-241/20211213/P1TT3xt3.html"
TITLE = "Synthetic Archived Regulations"
TEXT = "The operator must retain the complete records for each application and submit the annual report within 30 days to the authority under these regulations."


def snapshot(body):
    return SourceSnapshot(f'<html lang="en"><body><main><div class="archive-banner">This Web page has been archived.</div><div class="tocBar"><details><summary>Table of Contents</summary><nav>Unrelated contents controls</nav></details></div><div id="wb-cont" class="docContents">{body}</div></main></body></html>'.encode(), URL, "html", "text/html")


def test_closed_archive_navigation_does_not_render_or_enter_a_complete_document():
    page = snapshot(f'<h1>{TITLE}</h1><h2 id="part-1"><span class="HLabel1">PART 1</span><span>Requirements</span></h2><p>{TEXT}</p>')
    nav = navigation(page)
    assert not nav["interactive"] and nav["content_selector"] == 'div[id="wb-cont"]'
    def unexpected(*args):
        raise AssertionError("Static archived document must not open a browser or fetch another page")
    document = collect_document(page, ("laws.justice.gc.ca",), unexpected, render=unexpected)
    assert document["complete"] and document["source_coverage"]["method"] == "submitted_page"
    text = " ".join(unit["text"] for unit in document["units"])
    assert "This Web page has been archived." not in text and "Table of Contents" not in text
    assert any(unit.get("section_id") == "part:1" for unit in document["units"])


def test_real_document_controls_still_trigger_browser_collection():
    page = snapshot(f'<h1>{TITLE}</h1><details><summary>Section 1</summary><p>{TEXT}</p></details>')
    assert navigation(page)["interactive"]


def test_accessibility_labels_and_duplicate_definition_labels_are_excluded():
    page = snapshot(f'<h1>{TITLE}</h1><p><span class="wb-invisible">Marginal note:</span>Definitions</p><dl class="Definition"><dt><dfn>operator</dfn></dt><dd><p class="Definition"><span class="DefinedTerm"><dfn>operator</dfn></span> means a regulated entity.</p></dd><dt><dfn>permit</dfn></dt><dd><p>A document issued by the authority.</p></dd></dl><p>{TEXT}</p>')
    body, _ = extract_html(page, collection=True)
    text = " ".join(unit["text"] for unit in body["units"])
    assert "Marginal note:" not in text and text.count("operator") == 2
    assert "permit" in text and "means a regulated entity" in text


def test_mixed_parts_sections_and_schedules_are_all_compared(source):
    source[0][URL] = snapshot(f'<h1>{TITLE}</h1><h2>PART 1 Requirements</h2><h3>Section 1 Scope</h3><p>{TEXT}</p><h2 id="schedule-1">SCHEDULE 1 Fees</h2><p>The application fee is 30 units.</p>')
    upload = pdf(f'{TITLE}\nPART 1 Requirements\nSection 1 Scope\n{TEXT}\nSCHEDULE 1 Fees\nThe application fee is 30 units.')
    report = service.validate_pdf(upload, "synthetic.pdf", URL)
    assert report.status == "match" and report.coverage_complete and not report.findings
    changed = pdf(f'{TITLE}\nPART 1 Requirements\nSection 1 Scope\n{TEXT}\nSCHEDULE 1 Fees\nThe application fee is 60 units.')
    report = service.validate_pdf(changed, "synthetic.pdf", URL)
    assert report.status == "mismatch" and len(report.findings) == 1
    assert report.findings[0].source_url.endswith("#schedule-1")
