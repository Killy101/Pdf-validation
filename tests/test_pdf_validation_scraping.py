"""Scrapling extraction and PDF discovery using synthetic publisher pages."""
import json

import pytest

from test_pdf_validation import pdf, TEXT
from app.config import settings
from app.services import pdf_validation as service
from app.services import pdf_validation_source as retrieval
from app.services.pdf_validation_source import SourceSnapshot, extract_html


URL = "https://publisher.example/document"


def page(markup):
    return SourceSnapshot(markup.encode(), URL, "html", "text/html; charset=utf-8")


def test_omitted_heading_and_paragraph_end_tags_preserve_text_and_source_locations(source):
    title, heading, paragraph = TEXT.splitlines()
    snapshot = page(f'<main><h1>{title}<h2 id="scope">{heading}<p>{paragraph}</main>')
    document, references = extract_html(snapshot)
    assert document["complete"] and not references
    assert [unit["text"] for unit in document["units"]] == [title, heading, paragraph]
    assert document["units"][-1]["heading"] == heading
    assert document["units"][-1]["url"] == URL + "#scope"
    source[0][URL] = snapshot
    match = service.validate_pdf(pdf(TEXT), "synthetic.pdf", URL)
    assert match.status == "match" and match.coverage_complete
    changed = service.validate_pdf(pdf(TEXT.replace("all regulated", "some regulated")), "synthetic.pdf", URL)
    assert changed.status == "mismatch" and changed.findings[0].source_url == URL + "#scope"


@pytest.mark.parametrize("markup,expected", [
    ('<button data-pdf-url="/download?edition=2026">Download</button>', "/download?edition=2026"),
    ('<button data-download-url="/download?id=1" type="application/pdf">Download</button>', "/download?id=1"),
    ('<button data-download-url="/download?id=1" aria-label="Download PDF"></button>', "/download?id=1"),
    ('<a data-href="document.pdf#page=2">Download</a>', "/document.pdf"),
    ('<iframe data-src="/viewer.html?file=%2Fdocument.pdf"></iframe>', "/document.pdf"),
    ('<embed data-src="document.pdf?download=1" type="application/pdf">', "/document.pdf?download=1"),
])
def test_discovery_finds_declared_and_lazy_pdf_downloads(markup, expected):
    _, references = extract_html(page(markup))
    assert [item["url"] for item in references] == ["https://publisher.example" + expected]


@pytest.mark.parametrize("metadata", [
    {"@type": "MediaObject", "encodingFormat": "application/pdf", "contentUrl": "/download?id=1"},
    {"encoding": {"fileFormat": "PDF", "contentUrl": "/download?id=1"}},
    {"@graph": [{"associatedMedia": [{"encodingFormat": "application/pdf; charset=binary", "contentUrl": "/download?id=1"}]}]},
    [{"distribution": {"encodingFormat": "application/pdf", "contentUrl": "/download?id=1", "name": "Official edition"}}],
])
def test_json_ld_pdf_media_are_available_for_discovery_and_validation(source, metadata):
    source[0][URL] = page('<script type="application/ld+json">' + json.dumps(metadata) + '</script>')
    reference = "https://publisher.example/download?id=1"
    source[0][reference] = SourceSnapshot(pdf(TEXT), reference, "pdf")
    discovery = service.discover_pdf_source(URL)
    assert [item.url for item in discovery.references] == [reference]
    result = service.validate_pdf(pdf(TEXT), "synthetic.pdf", URL)
    assert result.status == "match" and result.comparison == "exact_file"
    assert source[1] == [URL, URL, reference]


def test_metadata_references_resolve_base_urls_and_deduplicate():
    markup = ('<head><base href="/editions/"></head><a href="document.pdf">Official PDF</a>'
              '<button data-pdf-url="document.pdf#page=1">PDF</button>'
              '<script type="application/ld+json">{"contentUrl":"document.pdf#page=2"}</script>')
    _, references = extract_html(page(markup))
    assert [item["url"] for item in references] == ["https://publisher.example/editions/document.pdf"]


def test_malformed_or_non_pdf_metadata_does_not_create_references_or_comparison_text():
    metadata = [{"contentUrl": "/preview", "encodingFormat": "image/png"},
                {"contentUrl": "/document", "name": "Regulation"},
                {"contentUrl": {"unexpected": "document.pdf"}, "encodingFormat": "application/pdf"}]
    markup = ('<script type="application/ld+json">{broken</script>'
              '<script type="application/ld+json">' + '[' * 2000 + '0' + ']' * 2000 + '</script>'
              '<script type="application/ld+json">' + json.dumps(metadata) + '</script>'
              '<script type="application/json">{"contentUrl":"unrelated.pdf"}</script>'
              '<button data-download-url="/preview">Preview</button>')
    document, references = extract_html(page(markup))
    assert not references and not document["units"] and not document["complete"]


def test_metadata_respects_source_hosts_and_rejects_unsafe_urls_without_fetching(source):
    markup = ('<button data-pdf-url="https://other.example/reference.pdf">PDF</button>'
              '<button data-pdf-url="javascript:openDocument()">PDF</button>'
              '<iframe data-src="file:///private/document.pdf"></iframe>'
              '<script type="application/ld+json">'
              '{"encodingFormat":"application/pdf","contentUrl":"https://user:secret@publisher.example/secret.pdf"}'
              '</script><script>fetch("https://other.example/reference.pdf")</script>')
    source[0][URL] = page(markup)
    discovery = service.discover_pdf_source(URL)
    assert len(discovery.references) == 1 and not discovery.references[0].available
    result = service.validate_pdf(pdf(TEXT), "synthetic.pdf", URL)
    assert result.status == "needs_review" and result.comparison == "not_checked"
    assert source[1] == [URL, URL]


@pytest.mark.parametrize("encoding,content_type,prefix", [
    ("windows-1252", "text/html; charset=windows-1252", ""),
    ("windows-1252", "text/html", '<meta charset="windows-1252">'),
    ("utf-16", "text/html", ""),
    ("utf-8", "application/xhtml+xml", '<?xml version="1.0" encoding="UTF-8"?>'),
])
def test_declared_encodings_and_xhtml_preserve_text_and_unicode_links(encoding, content_type, prefix):
    markup = prefix + '<html><body><main><h1>R\u00e9gulation</h1><p>Pr\u00e9ambule</p><a href="/\u00e9dition.pdf">PDF</a></main></body></html>'
    document, references = extract_html(SourceSnapshot(markup.encode(encoding), URL, "html", content_type))
    assert document["title"] == "R\u00e9gulation"
    assert document["units"][1]["text"] == "Pr\u00e9ambule"
    assert references[0]["url"] == "https://publisher.example/\u00e9dition.pdf"


def test_html_size_limit_is_checked_before_scrapling(monkeypatch):
    monkeypatch.setattr(settings, "PDF_VALIDATION_MAX_HTML_BYTES", 1024)
    def unexpected(*args):
        pytest.fail("Oversized source HTML must not be parsed.")
    monkeypatch.setattr(retrieval, "scrape_page", unexpected)
    with pytest.raises(ValueError, match="too large"):
        extract_html(page("<main>" + "x" * 1024 + "</main>"))


def test_excessive_dom_depth_cannot_silently_establish_complete_coverage():
    with pytest.raises(ValueError, match="too complex"):
        extract_html(page("<div>" * 260 + "<h1>Title</h1>" + "</div>" * 260))
