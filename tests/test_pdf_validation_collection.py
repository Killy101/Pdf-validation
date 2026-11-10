"""Bounded chapter discovery, incomplete coverage, and immutable source downloads."""
from urllib.error import HTTPError

import pytest

from test_pdf_validation import pdf
from app.config import settings
from app.services import pdf_validation as service
from app.services.pdf_validation_collection import collect_document
from app.services.pdf_validation_source import SourceSnapshot


ROOT = "https://publisher.example/rules/index.html"
TITLE = "Synthetic Environmental Regulations"
SCOPE = "These regulations apply to all facilities and require the operator to retain complete records for each application and publish the annual report."
DEADLINE = "The operator must submit the annual report within 30 days and retain a signed copy for inspection by the authority under these regulations."


def page(text, url, language="en", version="2026"):
    return SourceSnapshot(f'<html lang="{language}"><head><meta name="document-id" content="synthetic-rules"><meta name="document-version" content="{version}"></head><body><main>{text}</main></body></html>'.encode(), url, "html", "text/html")


def fixture(source):
    source[0][ROOT] = page(f'<h1>{TITLE}</h1><nav aria-label="Table of contents"><a href="section1.html">Section 1 Scope</a><a href="section2.html">Section 2 Deadline</a></nav>', ROOT)
    for number, (heading, text) in enumerate((("Scope", SCOPE), ("Deadline", DEADLINE)), 1):
        url = ROOT.replace("index.html", f"section{number}.html")
        source[0][url] = page(f'<h1>{TITLE}</h1><h2 id="section-{number}">Section {number} {heading}</h2><p>{text}</p>', url)
    return pdf(f'{TITLE}\nSection 1 Scope\n{SCOPE}', f'Section 2 Deadline\n{DEADLINE}')


def test_chapters_are_collected_and_compared_by_number_even_when_pdf_order_differs(source):
    fixture(source)
    upload = pdf(f'{TITLE}\nSection 2 Deadline\n{DEADLINE}', f'Section 1 Scope\n{SCOPE}')
    result = service.validate_pdf(upload, "synthetic.pdf", ROOT)
    assert result.status == "match" and result.coverage_complete
    assert result.source_coverage.retrieved_sections == result.source_coverage.expected_sections == 2
    assert result.source_coverage.pages_retrieved == 3
    assert "Compared 2 corresponding" in " ".join(result.scope_notes)


def test_real_section_change_has_the_matching_pdf_page_and_source_fragment(source):
    fixture(source)
    result = service.validate_pdf(pdf(f'{TITLE}\nSection 2 Deadline\n{DEADLINE.replace("30 days", "60 days")}', f'Section 1 Scope\n{SCOPE}'), "synthetic.pdf", ROOT)
    assert result.status == "mismatch" and len(result.findings) == 1
    finding = result.findings[0]
    assert finding.pdf_page == 1 and finding.source_url.endswith("section2.html#section-2")
    assert finding.actual[slice(*finding.actual_change)] == "60"
    assert finding.expected[slice(*finding.expected_change)] == "30"


def test_complete_source_reports_a_section_missing_from_the_upload(source):
    fixture(source)
    result = service.validate_pdf(pdf(f'{TITLE}\nSection 1 Scope\n{SCOPE}'), "synthetic.pdf", ROOT)
    assert result.status == "mismatch" and result.coverage_complete
    assert any(item.kind == "missing_content" and "annual report within 30 days" in item.expected
               and item.source_url.endswith("section2.html#section-2") for item in result.findings)


def test_complete_source_reports_an_extra_uploaded_section(source):
    fixture(source)
    upload = pdf(f'{TITLE}\nSection 1 Scope\n{SCOPE}', f'Section 2 Deadline\n{DEADLINE}',
        'Section 3 Unpublished exemption\nAll applications are automatically exempt from these regulations without review.')
    result = service.validate_pdf(upload, "synthetic.pdf", ROOT)
    assert result.status == "mismatch" and result.coverage_complete
    assert any(item.kind == "extra_content" and item.pdf_page == 3 and "automatically exempt" in item.actual for item in result.findings)


def test_unretrieved_chapter_is_not_reported_as_missing_or_extra_pdf_content(source):
    upload = fixture(source)
    missing = ROOT.replace("index.html", "section2.html")
    source[0][missing] = HTTPError(missing, 503, "Unavailable", {}, None)
    result = service.validate_pdf(upload, "synthetic.pdf", ROOT)
    assert result.status == "needs_review" and not result.coverage_complete and not result.findings
    assert result.source_coverage.retrieved_sections == 1
    assert result.checked_pdf_pages == 1
    assert result.source_coverage.sections[-1].status == "unavailable"


@pytest.mark.parametrize("change", ["language", "edition", "host"])
def test_other_languages_editions_and_hosts_cannot_enter_the_document(source, change):
    upload = fixture(source)
    url = ROOT.replace("index.html", "section2.html")
    if change == "host":
        source[0][ROOT].data = source[0][ROOT].data.replace(b'section2.html', b'https://other.example/section2.html')
    else:
        source[0][url] = page(f'<h1>{TITLE}</h1><h2>Section 2 Deadline</h2><p>{DEADLINE}</p>', url,
            language="fr" if change == "language" else "en", version="2025" if change == "edition" else "2026")
    result = service.validate_pdf(upload, "synthetic.pdf", ROOT)
    assert result.status == "needs_review" and not result.source_coverage.complete
    if change == "host":
        assert not any("other.example" in target for target in source[1])


def test_page_limits_and_cycles_are_visible_and_bounded(source, monkeypatch):
    fixture(source)
    monkeypatch.setattr(settings, "PDF_VALIDATION_CRAWL_MAX_PAGES", 2)
    result = collect_document(source[0][ROOT], ("publisher.example",), service.fetch_source)
    assert result["source_coverage"]["pages_retrieved"] == 2
    assert not result["complete"] and result["source_coverage"]["sections"][-1]["status"] == "not_checked"


def test_a_complete_view_is_used_without_comparing_the_index_links(source):
    upload = fixture(source)
    source[0][ROOT] = page(f'<h1>{TITLE}</h1><a href="full.html">Full document</a><nav aria-label="Table of contents"><a href="section1.html">Section 1 Scope</a></nav>', ROOT)
    url = ROOT.replace("index.html", "full.html")
    source[0][url] = page(f'<h1>{TITLE}</h1><h2 id="section-1">Section 1 Scope</h2><p>{SCOPE}</p><h2 id="section-2">Section 2 Deadline</h2><p>{DEADLINE}</p>', url)
    result = service.validate_pdf(upload, "synthetic.pdf", ROOT)
    assert result.status == "match"
    assert source[1] == [ROOT, url]


def test_changed_chapter_blocks_rebuilt_download_even_when_landing_page_is_unchanged(client, source):
    upload = fixture(source)
    result = service.validate_pdf(upload, "synthetic.pdf", ROOT)
    child = ROOT.replace("index.html", "section2.html")
    source[0][child].data = source[0][child].data.replace(b"30 days", b"45 days")
    response = client.post("/api/pdf-validations/updated-pdf", data={"source_url": ROOT, "source_sha256": result.source_sha256},
        files={"document": ("synthetic.pdf", upload, "application/pdf")})
    assert response.status_code == 409


def test_rebuilt_download_includes_the_entire_collected_document(client, source):
    from io import BytesIO
    from pypdf import PdfReader
    upload = fixture(source)
    result = service.validate_pdf(upload, "synthetic.pdf", ROOT)
    response = client.post("/api/pdf-validations/updated-pdf", data={"source_url": ROOT, "source_sha256": result.source_sha256},
        files={"document": ("synthetic.pdf", upload, "application/pdf")})
    assert response.status_code == 200
    text = " ".join(" ".join(page.extract_text().split()) for page in PdfReader(BytesIO(response.content)).pages)
    assert SCOPE in text and DEADLINE in text


def test_toc_fragments_are_checked_without_refetching_the_same_page(source):
    url = ROOT
    snapshot = page(f'<h1>{TITLE}</h1><nav aria-label="Table of contents"><a href="#section-1">Section 1</a><a href="#missing">Section 2</a></nav><h2 id="section-1">Section 1 Scope</h2><p>{SCOPE}</p>', url)
    result = collect_document(snapshot, ("publisher.example",), lambda *args: pytest.fail("Page was fetched twice"))
    assert result["source_coverage"]["retrieved_sections"] == 1 and not result["complete"]


def test_section_manifest_limit_does_not_claim_complete_collection(source, monkeypatch):
    fixture(source)
    monkeypatch.setattr(settings, "PDF_VALIDATION_CRAWL_MAX_SECTIONS", 1)
    result = collect_document(source[0][ROOT], ("publisher.example",), service.fetch_source)
    assert not result["complete"] and "section limit" in " ".join(result["source_coverage"]["notes"])


def test_next_page_cycles_are_fetched_once_and_language_query_is_excluded(source):
    fixture(source)
    second = ROOT.replace("index.html", "section2.html")
    source[0][second].data = source[0][second].data.replace(b'</main>', b'<a rel="next" href="index.html">Next page</a></main>')
    result = collect_document(source[0][ROOT], ("publisher.example",), service.fetch_source)
    assert result["complete"] and len(source[1]) == len(set(source[1])) == 2
    from app.services.pdf_validation_navigation import eligible_link
    assert not eligible_link({"url": second + "?lang=fr"}, ROOT, {"language": "en"}, ("publisher.example",))


def test_dynamic_landing_page_pdf_is_discovered_before_text_comparison(source, monkeypatch):
    from app.services import pdf_validation_browser
    data = pdf(f'{TITLE}\nSection 1 Scope\n{SCOPE}')
    source[0][ROOT] = page('<div id="app"></div>', ROOT)
    reference = ROOT.replace("index.html", "official.pdf")
    source[0][reference] = SourceSnapshot(data, reference, "pdf", "application/pdf")
    monkeypatch.setattr(pdf_validation_browser, "render_document", lambda *args:
        (page(f'<h1>{TITLE}</h1><a href="official.pdf">Official PDF</a>', ROOT), True, []))
    result = service.validate_pdf(data, "synthetic.pdf", ROOT)
    assert result.status == "match" and result.comparison == "exact_file" and result.source_url == reference
    assert result.source_coverage is None


def test_pagination_does_not_consume_chapter_depth(source, monkeypatch):
    monkeypatch.setattr(settings, "PDF_VALIDATION_CRAWL_MAX_DEPTH", 0)
    for number in range(5):
        url = ROOT if number == 0 else ROOT.replace("index.html", f"page{number}.html")
        next_url = f"page{number + 1}.html" if number < 4 else "index.html"
        source[0][url] = page(f'<h1>{TITLE}</h1><h2>Section {number + 1}</h2><p>{SCOPE}</p><a rel="next" href="{next_url}">Next page</a>', url)
    result = collect_document(source[0][ROOT], ("publisher.example",), service.fetch_source)
    assert result["complete"] and result["source_coverage"]["pages_retrieved"] == 5
    assert len(source[1]) == 4
    assert "Next page" not in " ".join(unit["text"] for unit in result["units"])
    upload = pdf(*(f'{TITLE if number == 0 else ""}\nSection {number + 1}\n{SCOPE}' for number in range(5)))
    assert service.validate_pdf(upload, "synthetic.pdf", ROOT).status == "match"
