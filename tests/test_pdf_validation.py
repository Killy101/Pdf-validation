"""PDF source validation using synthetic documents and isolated HTTP responses."""
from io import BytesIO
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import settings
from app.routers.pdf_validation import router
from app.services import pdf_validation as service
from app.services.pdf_validation_source import SourceSnapshot, extract_html, fetch_source
from app.services.pdf_validation_access import access_issue, SourceAccessError
from app.services.pdf_validation_worker import compare_documents, extract_pdf, ExtractionIncomplete
from reflink.url.evidence import _ValidatingRedirectHandler


URL = "https://publisher.example/document.pdf"
TEXT = "Synthetic Regulation 2026\nSection 1 Scope\nThis regulation applies to the operation of all regulated facilities."


def pdf(*pages, title="Synthetic Regulation 2026", encrypted=False, image=False):
    writer = PdfWriter()
    writer.add_metadata({"/Title": title})
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_ref = writer._add_object(font)
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})})
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = DecodedStreamObject()
        lines = escaped.splitlines()
        operators = "BT /F1 12 Tf 40 740 Td " + " 0 -16 Td ".join(f"({line}) Tj" for line in lines) + " ET"
        if image:
            graphic = DecodedStreamObject()
            graphic.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                            NameObject("/BBox"): page["/MediaBox"]})
            graphic.set_data(b"0 0 10 10 re f")
            page["/Resources"][NameObject("/XObject")] = DictionaryObject({NameObject("/Graphic"): writer._add_object(graphic)})
            operators += " q /Graphic Do Q"
        stream.set_data(operators.encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("synthetic-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_exact_file_match_includes_scanned_or_blank_pages(source):
    data = pdf(TEXT, "")
    source[0][URL] = SourceSnapshot(data, URL, "pdf")
    result = service.validate_pdf(data, "download.pdf", URL)
    assert result.status == "match" and result.comparison == "exact_file"
    assert result.coverage_complete and result.pdf_pages == result.checked_pdf_pages == 2
    assert result.upload_sha256 == result.source_sha256 and not result.findings


def test_different_pdf_metadata_does_not_fail_matching_text(source):
    data = pdf(TEXT)
    reference = pdf(TEXT, title="Different packaging title")
    source[0][URL] = SourceSnapshot(reference, URL, "pdf")
    result = service.validate_pdf(data, "download.pdf", URL)
    assert result.status == "match" and result.comparison == "content"
    assert result.upload_sha256 != result.source_sha256
    assert any("images" in limitation for limitation in result.limitations)


@pytest.mark.parametrize("page_count,changed_page", [(1000, None), (2000, None), (2000, 1999)])
def test_large_pdf_content_validation_checks_all_pages(source, page_count, changed_page):
    pages = [f"Section {index + 1} Requirements\n" +
             "Regulated facilities must submit their application within 30 days of approval.\n" * 24
             for index in range(page_count)]
    source[0][URL] = SourceSnapshot(pdf(*pages, title="Website edition"), URL, "pdf")
    if changed_page is not None:
        pages[changed_page] = pages[changed_page].replace("30 days", "60 days", 1)
    result = service.validate_pdf(pdf(*pages), "large.pdf", URL)
    assert result.comparison == "content" and result.coverage_complete
    assert result.pdf_pages == result.source_pages == result.checked_pdf_pages == page_count
    assert result.status == ("mismatch" if changed_page is not None else "match")
    if changed_page is None:
        assert not result.findings
    else:
        assert result.findings[0].pdf_page == result.findings[0].source_page == page_count
        assert "30" in result.findings[0].expected and "60" in result.findings[0].actual


def test_large_comparison_preserves_distant_missing_and_extra_pages():
    units = [{"text": f"Section {index} " + TEXT * 12, "page": index} for index in range(1, 2001)]
    uploaded = [{**unit} for unit in units]
    uploaded.pop(20)
    uploaded.insert(1800, {"text": "Additional unexpected regulation text.", "page": 1801})
    result = compare_documents({"units": uploaded, "complete": True}, {"units": units, "complete": True}, URL)
    assert result["status"] == "mismatch" and result["coverage_complete"]
    missing = next(item for item in result["findings"] if item["kind"] == "missing_content")
    extra = next(item for item in result["findings"] if item["kind"] == "extra_content")
    assert missing["source_page"] == 21 and missing["approximate_location"]
    assert extra["pdf_page"] == 1801 and "unexpected" in extra["actual"]


def test_large_comparison_accepts_equivalent_text_with_different_pagination():
    text = (TEXT + "\n") * 2000
    upload = {"units": [{"text": text, "page": 1}], "complete": True}
    reference = {"units": [{"text": TEXT, "page": index} for index in range(1, 2001)], "complete": True}
    assert compare_documents(upload, reference, URL)["status"] == "match"


def test_long_changed_ranges_and_report_truncation_remain_bounded():
    reference = {"units": [{"text": (f"source {index} " * 2500), "page": index} for index in range(1, 151)], "complete": True}
    upload = {"units": [{"text": (f"uploaded {index} " * 2500), "page": index} for index in range(1, 151)], "complete": True}
    result = compare_documents(upload, reference, URL)
    assert result["status"] == "mismatch" and result["coverage_complete"]
    assert len(result["findings"]) <= 100
    assert all(len(item["actual"]) <= 900 and len(item["expected"]) <= 900 for item in result["findings"])
    reference["units"] = [{"text": f"Section {index} source text.", "page": index} for index in range(1, 151)]
    upload["units"] = [{"text": f"Section {index} uploaded text.", "page": index} for index in range(1, 151)]
    result = compare_documents(upload, reference, URL)
    assert len(result["findings"]) == 100 and result["findings_truncated"]


def test_matching_text_with_unchecked_graphics_requires_review(source):
    source[0][URL] = SourceSnapshot(pdf(TEXT, image=True), URL, "pdf")
    result = service.validate_pdf(pdf(TEXT), "download.pdf", URL)
    assert result.status == "needs_review" and "visual" in result.summary
    url = "https://publisher.example/document"
    source[0][url] = SourceSnapshot('<main><h1>Synthetic Regulation 2026</h1><h2>Section 1 Scope</h2><p>This regulation applies to the operation of all regulated facilities.</p><img src="figure.png" alt="Required diagram"></main>'.encode(), url, "html")
    result = service.validate_pdf(pdf(TEXT), "download.pdf", url)
    assert result.status == "needs_review" and "visual" in result.summary


def test_changed_number_reports_pdf_and_reference_pages(source):
    data = pdf(TEXT, "Section 2 Deadline\nThe application must be submitted within 60 days of approval.")
    reference = pdf(TEXT, "Section 2 Deadline\nThe application must be submitted within 30 days of approval.")
    source[0][URL] = SourceSnapshot(reference, URL, "pdf")
    result = service.validate_pdf(data, "download.pdf", URL)
    assert result.status == "mismatch"
    finding = result.findings[0]
    assert finding.pdf_page == finding.source_page == 2
    assert "30" in finding.expected and "60" in finding.actual
    assert finding.source_url.endswith("#page=2")


def test_missing_and_extra_content_are_checked_in_both_directions():
    document = lambda text: {"units": [{"text": text, "page": 1}], "complete": True}
    result = compare_documents(document("Scope applies. Unexpected extra material."), document("Scope applies. Section 12 Missing requirement."), URL)
    assert result["status"] == "mismatch" and result["findings"]
    assert any("Missing requirement." in finding["expected"] for finding in result["findings"])
    extra = compare_documents(document("Scope applies. Unexpected extra material."), document("Scope applies."), URL)
    assert extra["findings"][0]["kind"] == "extra_content"
    missing = compare_documents(document("Scope applies."), document("Scope applies. Section 12 Missing requirement."), URL)
    assert missing["findings"][0]["kind"] == "missing_content"
    assert missing["findings"][0]["approximate_location"] is True


def test_html_excludes_site_furniture_and_retains_source_section(source):
    url = "https://publisher.example/document"
    body = b'<html><head><title>Site title</title></head><body><nav>Account navigation</nav><main><h1>Synthetic Regulation 2026</h1><h2 id="scope">Section 1 Scope</h2><p>This regulation applies to the operation of all regulated facilities.</p><p hidden>Hidden obsolete text.</p></main><footer>Copyright</footer></body></html>'
    snapshot = SourceSnapshot(body, url, "html", "text/html")
    html, references = extract_html(snapshot)
    assert not references and html["complete"]
    assert "Account" not in str(html) and "Hidden" not in str(html) and "Copyright" not in str(html)
    source[0][url] = snapshot
    match = service.validate_pdf(pdf(TEXT), "download.pdf", url)
    assert match.status == "match" and match.source_type == "html"
    mismatch = service.validate_pdf(pdf(TEXT.replace("all regulated", "some regulated")), "download.pdf", url)
    finding = mismatch.findings[0]
    assert mismatch.status == "mismatch" and finding.pdf_page == 1
    assert finding.source_heading == "Section 1 Scope" and finding.source_url.endswith("#scope")


@pytest.mark.parametrize("attributes", [
    'role="navigation"', 'role="toolbar"', 'role="tablist"', 'role="search"',
    'class="breadcrumb"', 'class="pagination"', 'class="toc-body"',
    'class="toolbar-btns-container d-print-none"', 'id="versionPanel"', 'id="pageHeader"',
])
def test_document_body_excludes_website_controls_and_keeps_real_text(source, attributes):
    url = "https://publisher.example/document"
    title, heading, paragraph = TEXT.splitlines()
    body = f'<main><h1>Publisher website</h1><div {attributes}>Text Details Downloads All versions Page 1 of 200</div><div id="document-content"><h1>{title}</h1><h2 id="scope">{heading}</h2><p>{paragraph}</p></div></main>'
    html, references = extract_html(SourceSnapshot(body.encode(), url, "html"))
    assert html["complete"] and not references
    assert [unit["text"] for unit in html["units"]] == [title, heading, paragraph]
    source[0][url] = SourceSnapshot(body.encode(), url, "html")
    result = service.validate_pdf(pdf(TEXT), "download.pdf", url)
    assert result.status == "match" and result.coverage_complete and not result.findings


def test_article_body_has_priority_over_surrounding_main_metadata_and_buttons(source):
    url = "https://publisher.example/document"
    title, heading, paragraph = TEXT.splitlines()
    body = f'<main><h1>Publisher record</h1><p>Administered by Publisher. Latest version.</p><button>Print page</button><article><h1>{title}</h1><h2>{heading}</h2><p>{paragraph}</p></article></main>'
    source[0][url] = SourceSnapshot(body.encode(), url, "html")
    result = service.validate_pdf(pdf(TEXT), "download.pdf", url)
    assert result.status == "match" and result.coverage_complete and not result.findings


def test_real_numeric_content_changes_survive_document_body_filtering(source):
    url = "https://publisher.example/document"
    body = f'<main><div class="version-panel">Page 1 of 200 Download latest version</div><div id="legislation-text"><h1>Synthetic Regulation</h1><h2 id="deadline">Deadline</h2><p>{TEXT}</p><p>Submit within 30 days.</p></div></main>'
    source[0][url] = SourceSnapshot(body.encode(), url, "html")
    result = service.validate_pdf(pdf("Synthetic Regulation\nDeadline\n" + TEXT + "\nSubmit within 60 days."), "download.pdf", url)
    assert result.status == "mismatch" and result.coverage_complete
    finding = next(item for item in result.findings if "30" in item.expected and "60" in item.actual)
    assert finding.source_url.endswith("#deadline") and finding.pdf_page == 1
    assert all("download latest version" not in item.expected for item in result.findings)


def test_document_headers_contents_tables_and_legitimate_page_words_are_preserved():
    body = '<main><div class="documentBody"><header class="page-header"><h1>Synthetic Regulation</h1></header><div class="table-of-contents">Contents Section 1 Scope</div><h2>Downloads and page headers</h2><p>The page count must be 12. Header information is required.</p><table><tr><th>Amount</th><td>50</td></tr></table><footer class="page-footer">Authorised document version 4</footer></div></main>'
    html, _ = extract_html(SourceSnapshot(body.encode(), URL, "html"))
    text = " ".join(unit["text"] for unit in html["units"])
    assert "Synthetic Regulation" in text and "Contents Section 1 Scope" in text
    assert "Downloads and page headers" in text and "page count must be 12" in text
    assert "Amount" in text and "50" in text and "Authorised document version 4" in text
    assert html["requires_visual_review"]


def test_viewer_navigation_inside_the_document_container_does_not_make_coverage_incomplete():
    body = f'<div id="document-content"><h1>Synthetic Regulation</h1><div role="toolbar"><a href="#" aria-expanded="false">Next page</a><button>Show more controls</button></div><p>{TEXT}</p></div>'
    html, _ = extract_html(SourceSnapshot(body.encode(), URL, "html"))
    assert html["complete"] and "Next page" not in str(html) and "Show more controls" not in str(html)


def test_pdf_download_links_without_extensions_or_visible_labels_are_found(source):
    url = "https://publisher.example/document"
    reference = "https://publisher.example/edition/text/original/pdf"
    body = '<main><h1>Publisher record</h1><div role="toolbar"><a href="/edition/text/original/pdf" aria-label="Open PDF"><svg></svg></a></div></main>'
    source[0][url] = SourceSnapshot(body.encode(), url, "html")
    source[0][reference] = SourceSnapshot(pdf(TEXT), reference, "pdf")
    result = service.validate_pdf(pdf(TEXT), "download.pdf", url)
    assert result.status == "match" and result.comparison == "exact_file"
    assert result.source_url == reference and source[1] == [url, reference]


@pytest.mark.parametrize("edition", ["2023-07-01", "2025-11-01"])
def test_legislation_viewer_uses_the_pdf_of_the_displayed_edition(source, edition):
    url = "https://www.legislation.gov.au/F2019L00417"
    prefix = f"https://www.legislation.gov.au/F2019L00417/{edition}/{edition}/text/original"
    body = f'<main id="maincontent"><div role="tablist"><a role="tab">Text</a><a role="tab">Downloads</a></div><h1>Publisher record</h1><div class="version-panel">Latest version C05 2025</div><div class="epub-viewer-container"><div class="toc-header">Table of contents</div><div class="toc-body">Page 1 of 85 Chapter 1</div><iframe id="epubFrame" title="Document: Synthetic Regulation" src="{prefix}/epub/OEBPS/document_1/document_1.html"></iframe></div></main>'
    snapshot = SourceSnapshot(body.encode(), url, "html")
    html, references = extract_html(snapshot)
    assert not html["units"] and not html["complete"]
    assert [item["url"] for item in references] == [prefix + "/pdf"]
    source[0][url] = snapshot
    source[0][prefix + "/pdf"] = SourceSnapshot(pdf(TEXT), prefix + "/pdf", "pdf")
    result = service.validate_pdf(pdf(TEXT), "download.pdf", url)
    assert result.status == "match" and result.comparison == "exact_file"
    assert result.source_url == prefix + "/pdf" and not result.findings
    assert source[1] == [url, prefix + "/pdf"]


def test_real_document_and_edition_changes_remain_findings_after_viewer_cleanup(source):
    url = "https://www.legislation.gov.au/F2019L00417"
    prefix = "https://www.legislation.gov.au/F2019L00417/2025-11-01/2025-11-01/text/original"
    body = f'<main><h1>Publisher record</h1><div class="toc-body">Table of contents Page 1</div><iframe id="epubFrame" src="{prefix}/epub/OEBPS/document_1/document_1.html"></iframe></main>'
    source[0][url] = SourceSnapshot(body.encode(), url, "html")
    current = TEXT + "\nCompilation 5 2025\nSubmit within 30 days."
    uploaded = TEXT + "\nCompilation 4 2023\nSubmit within 60 days."
    source[0][prefix + "/pdf"] = SourceSnapshot(pdf(current), prefix + "/pdf", "pdf")
    result = service.validate_pdf(pdf(uploaded), "download.pdf", url)
    assert result.status == "mismatch" and result.coverage_complete
    assert any("30" in item.expected and "60" in item.actual for item in result.findings)
    assert any("2025" in item.expected and "2023" in item.actual for item in result.findings)
    assert all("publisher record" not in item.expected and "table of contents" not in item.expected for item in result.findings)


def test_unavailable_embedded_document_never_compares_website_controls(source, monkeypatch):
    url = "https://publisher.example/document"
    body = b'<main><h1>Publisher record</h1><p>Administered by Publisher. Latest version C05.</p><iframe id="documentFrame" class="border" title="Document: Synthetic Regulation" src="viewer/body.html"></iframe></main>'
    source[0][url] = SourceSnapshot(body, url, "html")
    def unexpected(*args, **kwargs):
        pytest.fail("Viewer controls must never be compared as document text.")
    monkeypatch.setattr(service, "run_analysis", unexpected)
    result = service.validate_pdf(pdf(TEXT), "download.pdf", url)
    assert result.status == "needs_review" and result.comparison == "not_checked" and not result.findings
    assert "document text could not be retrieved" in result.summary


def test_foreign_viewers_do_not_invent_legislation_pdf_endpoints():
    body = b'<iframe id="epubFrame" src="https://other.example/record/text/original/epub/document.html"></iframe>'
    html, references = extract_html(SourceSnapshot(body, URL, "html"))
    assert not references and not html["units"]


def test_ambiguous_landing_page_requires_selection_and_rejects_unlisted_url(source):
    url = "https://publisher.example/editions"
    other = "https://publisher.example/previous.pdf"
    source[0][url] = SourceSnapshot(f'<main><h1>Editions</h1><a href="{URL}">Current PDF</a><a href="{other}">Previous PDF</a></main>'.encode(), url, "html")
    source[0][URL] = SourceSnapshot(pdf(TEXT), URL, "pdf")
    result = service.validate_pdf(pdf(TEXT), "download.pdf", url)
    assert result.status == "needs_review" and result.comparison == "not_checked"
    assert len(result.references) == 2 and source[1] == [url]
    selected = service.validate_pdf(pdf(TEXT), "download.pdf", url, URL)
    assert selected.status == "match" and selected.source_url == URL
    denied = service.validate_pdf(pdf(TEXT), "download.pdf", url, "https://unlisted.example/secret.pdf")
    assert denied.status == "unable" and "Select an available" in denied.summary
    assert "https://unlisted.example/secret.pdf" not in source[1]


def test_one_pdf_link_is_followed_and_external_host_is_not(source):
    url = "https://publisher.example/document"
    source[0][url] = SourceSnapshot(b'<main><h1>Document</h1><a href="document.pdf">Download PDF</a></main>', url, "html")
    source[0][URL] = SourceSnapshot(pdf(TEXT), URL, "pdf")
    assert service.validate_pdf(pdf(TEXT), "download.pdf", url).status == "match"
    source[0][url] = SourceSnapshot(b'<main><h1>Document</h1><a href="https://other.example/document.pdf">Download PDF</a></main>', url, "html")
    result = service.validate_pdf(pdf(TEXT), "download.pdf", url)
    assert result.status == "needs_review" and result.references[0].available is False
    assert "https://other.example/document.pdf" not in source[1]


@pytest.mark.parametrize("markup", [
    '<iframe src="document.pdf#page=2" title="Official PDF"></iframe>',
    '<embed src="document.pdf?download=1" type="application/pdf">',
    '<object data="document.pdf" type="application/pdf"></object>',
    '<iframe src="viewer.html?file=%2Fdocument.pdf"></iframe>',
    '<a href="document.pdf?download=1">Download</a>',
    '<a href="download?file=document.pdf&amp;version=1">Download</a>',
    '<a href="download?id=1" download="document.pdf">Download</a>',
    '<head><meta name="citation_pdf_url" content="document.pdf"></head>',
    '<head><link type="application/pdf" href="document.pdf" title="Publication"></head>',
    '<nav><a href="document.pdf">Download PDF</a></nav>',
])
def test_discovery_finds_linked_embedded_and_declared_pdfs(markup):
    html, references = extract_html(SourceSnapshot(markup.encode(), "https://publisher.example/document", "html"))
    assert len(references) == 1
    assert references[0]["url"] in {URL, URL + "?download=1", "https://publisher.example/download?id=1",
                                    "https://publisher.example/download?file=document.pdf&version=1"}


def test_discovery_resolves_base_urls_and_deduplicates_references():
    markup = '<head><base href="/publications/"></head><a href="document.pdf#page=1">PDF</a><iframe src="document.pdf"></iframe>'
    _, references = extract_html(SourceSnapshot(markup.encode(), "https://publisher.example/document", "html"))
    assert [item["url"] for item in references] == ["https://publisher.example/publications/document.pdf"]
    markup = '<iframe src="/publications/viewer.html?file=document.pdf"></iframe>'
    _, references = extract_html(SourceSnapshot(markup.encode(), "https://publisher.example/document", "html"))
    assert references[0]["url"] == "https://publisher.example/publications/document.pdf"


def test_large_html_is_rejected_before_discovery_or_comparison(client, source, monkeypatch):
    url = "https://publisher.example/document"
    source[0][url] = SourceSnapshot(b"<main>" + b"x" * 1024 + b"</main>", url, "html")
    monkeypatch.setattr(settings, "PDF_VALIDATION_MAX_HTML_BYTES", 1024)
    response = client.post("/api/pdf-validations/sources", json={"content_uri": url})
    assert response.status_code == 400 and "too large" in response.json()["message"]
    result = service.validate_pdf(pdf(TEXT), "download.pdf", url)
    assert result.status == "needs_review" and result.comparison == "not_checked"


def test_single_embedded_pdf_is_followed_even_on_a_long_landing_page(source):
    url = "https://publisher.example/document"
    source[0][url] = SourceSnapshot(("<main><h1>Publication</h1><p>" + TEXT * 20 +
                                    '</p><iframe src="document.pdf"></iframe></main>').encode(), url, "html")
    source[0][URL] = SourceSnapshot(pdf(TEXT), URL, "pdf")
    result = service.validate_pdf(pdf(TEXT), "download.pdf", url)
    assert result.status == "match" and result.comparison == "exact_file"
    assert result.source_url == URL and source[1] == [url, URL]


def test_authenticated_discovery_does_not_require_an_uploaded_file(client, source):
    url = "https://publisher.example/document"
    other = "https://other.example/previous.pdf"
    source[0][url] = SourceSnapshot(f'<main><h1>Publication</h1><a href="{URL}">Current PDF</a><embed src="{other}"></main>'.encode(), url, "html")
    response = client.post("/api/pdf-validations/sources", json={"content_uri": url})
    assert response.status_code == 200 and response.json()["success"]
    result = response.json()["data"]
    assert result["source_type"] == "html" and result["source_title"] == "Publication"
    assert result["references"] == [{"url": URL, "label": "Current PDF", "available": True, "kind": "pdf", "archive_member": None},
                                    {"url": other, "label": "Embedded document", "available": False, "kind": "pdf", "archive_member": None}]
    assert source[1] == [url]
    assert client.post("/api/pdf-validations/sources", json={"content_uri": "file:///private"}).status_code == 400
    source[0][URL] = SourceSnapshot(pdf(TEXT), URL, "pdf")
    direct = client.post("/api/pdf-validations/sources", json={"content_uri": URL}).json()["data"]
    assert direct["source_type"] == "pdf" and not direct["references"]
    source[0][url] = HTTPError(url, 403, "Forbidden", {}, None)
    assert client.post("/api/pdf-validations/sources", json={"content_uri": url}).status_code == 400


def test_blank_pdf_or_dynamic_source_cannot_pass_content_comparison(source):
    source[0][URL] = SourceSnapshot(pdf(TEXT), URL, "pdf")
    result = service.validate_pdf(pdf(""), "scan.pdf", URL)
    assert result.status == "needs_review" and not result.coverage_complete
    url = "https://publisher.example/viewer"
    source[0][url] = SourceSnapshot(b'<main><h1>Viewer</h1><iframe src="chapter"></iframe><p>Loading...</p></main>', url, "html")
    result = service.validate_pdf(pdf(TEXT), "download.pdf", url)
    assert result.status == "needs_review" and not result.coverage_complete


def test_corrupt_pdf_and_unavailable_source_do_not_become_mismatches(source):
    source[0][URL] = SourceSnapshot(pdf(TEXT), URL, "pdf")
    result = service.validate_pdf(b"%PDF-1.7 broken", "broken.pdf", URL)
    assert result.status == "unable" and not result.coverage_complete
    source[0][URL] = HTTPError(URL, 403, "Forbidden", {}, None)
    result = service.validate_pdf(pdf(TEXT), "download.pdf", URL)
    assert result.status == "unable" and "403" in result.summary and result.comparison == "not_checked"


@pytest.mark.parametrize("body,issue", [
    (b'<html><title>Just a moment...</title><body>Enable JavaScript and cookies to continue.</body></html>', "captcha"),
    (b'<main><h1>Verify you are human</h1><div class="cf-turnstile"></div></main>', "captcha"),
    (b'<html><title>Verification</title><body>Complete the CAPTCHA.<div class="g-recaptcha"></div></body></html>', "captcha"),
    (b'<html><title>Verification</title><body>Solve this CAPTCHA.<div class="h-captcha"></div></body></html>', "captcha"),
    (b'<html><title>Human verification</title><body>Check the verification box to proceed.</body></html>', "captcha"),
    (b'<html><title>Access denied</title><body>Permission required.</body></html>', "access_denied"),
    (b'<html><title>Sign in</title><form><input type="password"></form></html>', "access_denied"),
    (b'<html><title>Too many requests</title></html>', "rate_limited"),
])
def test_access_barrier_pages_warn_without_comparing_or_scraping(client, source, monkeypatch, body, issue):
    def unexpected(*args, **kwargs):
        pytest.fail("An access barrier must never be compared as a source document.")
    monkeypatch.setattr(service, "run_analysis", unexpected)
    source[0][URL] = SourceSnapshot(body, URL, "html")
    result = service.validate_pdf(pdf(TEXT), "download.pdf", URL)
    assert result.status == "unable" and result.source_access_issue == issue
    assert result.comparison == "not_checked" and not result.coverage_complete and not result.findings
    assert "website" in result.summary.lower()
    response = client.post("/api/pdf-validations/sources", json={"content_uri": URL})
    assert response.status_code == 400 and response.json()["success"] is False
    assert "website" in response.json()["message"].lower()


@pytest.mark.parametrize("code,issue", [(401, "access_denied"), (403, "access_denied"), (429, "rate_limited"), (503, "unavailable")])
def test_http_access_failures_are_reported_with_actionable_messages(source, code, issue):
    source[0][URL] = HTTPError(URL, code, "Synthetic source error", {}, None)
    result = service.validate_pdf(pdf(TEXT), "download.pdf", URL)
    assert result.status == "unable" and result.source_access_issue == issue
    assert str(code) in result.summary and result.comparison == "not_checked"


def test_http_captcha_body_and_unreachable_source_are_identified(source):
    source[0][URL] = HTTPError(URL, 403, "Forbidden", {}, BytesIO(b'<html><title>Verify you are human</title></html>'))
    result = service.validate_pdf(pdf(TEXT), "download.pdf", URL)
    assert result.source_access_issue == "captcha" and "CAPTCHA" in result.summary
    source[0][URL] = URLError("Synthetic unreachable host")
    result = service.validate_pdf(pdf(TEXT), "download.pdf", URL)
    assert result.source_access_issue == "unavailable" and "could not be reached" in result.summary


def test_selected_reference_pdf_with_a_captcha_does_not_become_a_content_mismatch(source):
    url = "https://publisher.example/document"
    source[0][url] = SourceSnapshot(b'<main><h1>Publication</h1><a href="document.pdf">PDF</a></main>', url, "html")
    source[0][URL] = SourceSnapshot(b'<html><title>Verify you are human</title></html>', URL, "html")
    result = service.validate_pdf(pdf(TEXT), "download.pdf", url)
    assert result.source_access_issue == "captcha" and result.status == "unable" and not result.findings


def test_ordinary_document_captcha_mentions_and_footer_widgets_do_not_block_validation():
    body = f'<main><h1>Synthetic CAPTCHA Regulation</h1><h2>CAPTCHA</h2><p>{TEXT}</p><p>The document describes human verification and CAPTCHA systems.</p></main><footer><div class="g-recaptcha"></div></footer>'
    assert access_issue(body.encode()) is None
    assert access_issue(pdf(TEXT + " CAPTCHA security verification")) is None


def test_extraction_limits_and_encryption_require_review():
    with pytest.raises(ExtractionIncomplete, match="page limit"):
        extract_pdf(pdf(TEXT, TEXT), 1, 10000)
    with pytest.raises(ExtractionIncomplete, match="text limit"):
        extract_pdf(pdf(TEXT), 10, 10)
    with pytest.raises(ExtractionIncomplete, match="password"):
        extract_pdf(pdf(TEXT, encrypted=True), 10, 10000)
    with pytest.raises(ExtractionIncomplete, match="page limit"):
        extract_pdf(pdf(*([TEXT] * 2001)), 2000, settings.PDF_VALIDATION_MAX_CHARACTERS)


def test_analysis_timeout_is_a_review_result(source, monkeypatch):
    source[0][URL] = SourceSnapshot(pdf(TEXT), URL, "pdf")
    def expired(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(service.subprocess, "run", expired)
    result = service.validate_pdf(pdf(TEXT), "download.pdf", URL)
    assert result.status == "needs_review" and "time limit" in result.summary


def test_parser_memory_exhaustion_requires_review(monkeypatch, capsys):
    import base64
    import json
    from io import StringIO
    from app.services import pdf_validation_limits, pdf_validation_worker
    def exhausted(*args, **kwargs):
        raise MemoryError()
    monkeypatch.setattr(pdf_validation_worker, "PdfReader", exhausted)
    monkeypatch.setattr(pdf_validation_limits, "limit_memory", lambda *args: None)
    payload = {"upload": base64.b64encode(pdf(TEXT)).decode(), "exact": True, "max_pages": 10,
               "max_characters": 10000, "memory_mb": 512}
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))
    pdf_validation_worker.main()
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "needs_review" and result["coverage_complete"] is False


def test_public_address_checks_cover_initial_and_redirect_hosts(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="non-public"):
        fetch_source(URL, ("publisher.example",), 1024, 1)
    handler = _ValidatingRedirectHandler(("publisher.example",))
    with pytest.raises(ValueError, match="not approved"):
        handler.redirect_request(None, None, 302, "Redirect", {}, "https://other.example/redirect.pdf")


@pytest.mark.parametrize("url,expected", [
    ("https://publisher.example/행정규칙/규정.pdf#페이지=2",
     "https://publisher.example/%ED%96%89%EC%A0%95%EA%B7%9C%EC%B9%99/%EA%B7%9C%EC%A0%95.pdf"),
    ("https://publisher.example/document.pdf?title=금융&edition=2026%2F09&x=1+2&target=%2Ftext%3Fa%3Db%26c%3Dd",
     "https://publisher.example/document.pdf?title=%EA%B8%88%EC%9C%B5&edition=2026%2F09&x=1+2&target=%2Ftext%3Fa%3Db%26c%3Dd"),
    ("https://publisher.example/%EA%B7%9C%EC%A0%95.pdf?title=%EA%B8%88%EC%9C%B5",
     "https://publisher.example/%EA%B7%9C%EC%A0%95.pdf?title=%EA%B8%88%EC%9C%B5"),
])
def test_source_request_encodes_unicode_without_changing_url_meaning(monkeypatch, url, expected):
    from app.services import pdf_validation_source as retrieval
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    class Response(BytesIO):
        headers = {"Content-Type": "application/pdf"}
        def geturl(self):
            return expected
    def open_source(request, **kwargs):
        f"GET {request.selector} HTTP/1.1".encode("ascii")
        assert request.full_url == expected
        return Response(b"%PDF-synthetic")
    monkeypatch.setattr(retrieval, "build_opener", lambda *args: SimpleNamespace(open=open_source))
    snapshot = fetch_source(url, ("publisher.example",), 1024, 1)
    assert snapshot.kind == "pdf" and snapshot.url == expected


def test_unicode_source_discovery_and_linked_pdf_validation(monkeypatch):
    from app.services import pdf_validation_source as retrieval
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(settings, "PDF_VALIDATION_ALLOWED_HOSTS", [])
    url = "https://publisher.example/행정규칙"
    page_url = "https://publisher.example/%ED%96%89%EC%A0%95%EA%B7%9C%EC%B9%99"
    pdf_url = "https://publisher.example/%EA%B7%9C%EC%A0%95.pdf"
    data = pdf(TEXT)
    documents = {page_url: '<main><h1>Document</h1><a href="/규정.pdf">Reference PDF</a></main>'.encode(),
                 pdf_url: data}
    calls = []
    class Response(BytesIO):
        def __init__(self, request_url):
            super().__init__(documents[request_url])
            self.url = request_url
            self.headers = {"Content-Type": "application/pdf" if request_url == pdf_url else "text/html; charset=utf-8"}
        def geturl(self):
            return self.url
    def open_source(request, **kwargs):
        f"GET {request.selector} HTTP/1.1".encode("ascii")
        calls.append(request.full_url)
        return Response(request.full_url)
    monkeypatch.setattr(retrieval, "build_opener", lambda *args: SimpleNamespace(open=open_source))
    discovery = service.discover_pdf_source(url)
    assert discovery.references[0].url == "https://publisher.example/규정.pdf"
    result = service.validate_pdf(data, "규정.pdf", url, discovery.references[0].url)
    assert result.status == "match" and result.comparison == "exact_file"
    assert result.checked_pdf_pages == 1 and result.coverage_complete
    assert result.submitted_url == url and result.source_url == pdf_url
    assert calls == [page_url, page_url, pdf_url]


def test_response_size_limits_and_pdf_signature_detection(monkeypatch):
    from app.services import pdf_validation_source as retrieval
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    class Response(BytesIO):
        headers = {"Content-Type": "text/html"}
        def geturl(self):
            return URL
    monkeypatch.setattr(retrieval, "build_opener", lambda *args: SimpleNamespace(open=lambda *args, **kwargs: Response(b"%PDF-" + b"x" * 30)))
    with pytest.raises(ValueError, match="size limit"):
        fetch_source(URL, ("publisher.example",), 20, 1)
    snapshot = fetch_source(URL + "#page=2", ("publisher.example",), 100, 1)
    assert snapshot.kind == "pdf" and snapshot.url == URL
    Response.headers = {"Content-Length": "5000"}
    with pytest.raises(ValueError, match="size limit"):
        fetch_source(URL, ("publisher.example",), 100, 1)
    Response.headers = {"Content-Type": "text/html", "cf-mitigated": "challenge"}
    with pytest.raises(SourceAccessError, match="CAPTCHA"):
        fetch_source(URL, ("publisher.example",), 100, 1)


def test_load_more_and_multiple_documents_cannot_establish_complete_coverage():
    body = f'<main><h1>Document</h1><p>{TEXT}</p><button>Show more</button></main>'
    html, _ = extract_html(SourceSnapshot(body.encode(), URL, "html"))
    assert not html["complete"]
    body = f'<article><h1>First document</h1><p>{TEXT}</p></article><article><h1>Second document</h1><p>{TEXT}</p></article>'
    html, _ = extract_html(SourceSnapshot(body.encode(), URL, "html"))
    assert not html["complete"]


def test_pagination_difference_and_worker_failure_require_review(source, monkeypatch):
    source[0][URL] = SourceSnapshot(pdf(TEXT), URL, "pdf")
    lines = TEXT.splitlines()
    result = service.validate_pdf(pdf("\n".join(lines[:2]), lines[2]), "download.pdf", URL)
    assert result.status == "needs_review" and any(finding.kind == "page_count" for finding in result.findings)
    monkeypatch.setattr(service.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    result = service.validate_pdf(pdf(TEXT), "download.pdf", URL)
    assert result.status == "needs_review" and "resource limits" in result.summary


def test_authenticated_api_returns_envelope_and_rejects_invalid_uploads(client, source, monkeypatch):
    source[0][URL] = SourceSnapshot(pdf(TEXT), URL, "pdf")
    limits = client.get("/api/pdf-validations/configuration")
    assert limits.status_code == 200 and limits.json()["data"]["max_pages"] == settings.PDF_VALIDATION_MAX_PAGES
    assert limits.json()["data"]["max_files"] == settings.PDF_VALIDATION_MAX_FILES
    monkeypatch.setattr(settings, "PDF_VALIDATION_MAX_FILES", 3)
    assert client.get("/api/pdf-validations/configuration").json()["data"]["max_files"] == 3
    response = client.post("/api/pdf-validations", data={"content_uri": URL}, files={"document": ("download.pdf", pdf(TEXT), "application/pdf")})
    assert response.status_code == 200 and response.json()["success"] is True
    assert response.json()["data"]["status"] == "match"
    invalid = client.post("/api/pdf-validations", data={"content_uri": URL}, files={"document": ("bad.pdf", b"HTML error", "application/pdf")})
    assert invalid.status_code == 400 and invalid.json()["success"] is False
    assert client.post("/api/pdf-validations", data={"content_uri": "file:///private"}, files={"document": ("download.pdf", pdf(TEXT))}).status_code == 400
    monkeypatch.setattr(settings, "PDF_VALIDATION_MAX_BYTES", 10)
    oversized = client.post("/api/pdf-validations", data={"content_uri": URL}, files={"document": ("large.pdf", b"%PDF-" + b"x" * 20)})
    assert oversized.status_code == 413
    assert client.post("/api/pdf-validations", data={"content_uri": URL}).status_code == 422


def test_api_requires_authentication():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        assert client.get("/api/pdf-validations/configuration").status_code == 401
        response = client.post("/api/pdf-validations", data={"content_uri": URL}, files={"document": ("download.pdf", pdf(TEXT))})
        assert client.post("/api/pdf-validations/sources", json={"content_uri": URL}).status_code == 401
    assert response.status_code == 401
