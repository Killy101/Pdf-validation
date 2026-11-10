"""ZIP discovery, isolated comparison, provenance, and archive trust boundaries."""
from hashlib import sha256
from io import BytesIO
import socket
import struct
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from pypdf import PdfReader

from test_pdf_validation import pdf, TEXT
from test_pdf_validation_identity_and_batches import EMPLOYMENT, WILDLIFE
from app.config import settings
from app.pdf_validation_models import PdfValidationOptions
from app.services import pdf_validation as service
from app.services.pdf_validation_archive import resolve_archive
from app.services.pdf_validation_archive_worker import inspect_archive
from app.services.pdf_validation_source import SourceSnapshot, extract_html


URL = "https://publisher.example/book.zip"
LANDING = "https://publisher.example/book"


def zipped(entries):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return output.getvalue()


def snapshot(entries):
    return SourceSnapshot(zipped(entries), URL, "zip", "application/zip")


def payload(data, **changes):
    import base64
    return {"data": base64.b64encode(data).decode(), "url": URL, "member": None, "discover": False,
        "max_files": 100, "max_expanded_bytes": 1000000, "max_bytes": 1000000,
        "max_html_bytes": 100000, "timeout": 10, **changes}


@pytest.mark.parametrize("markup", [
    '<a href="book.zip">Download</a>',
    '<a href="download" download="book.zip">Download</a>',
    '<a href="download" type="application/zip">Download</a>',
    '<button data-zip-url="download">Download</button>',
    '<button data-download-url="download" type="application/zip">Download</button>',
    '<script type="application/ld+json">{"contentUrl":"download","encodingFormat":"application/zip"}</script>',
])
def test_discovers_declared_and_extensionless_zip_links(markup):
    _, references = extract_html(SourceSnapshot(markup.encode(), LANDING, "html"))
    assert len(references) == 1 and references[0]["kind"] == "zip"


@pytest.mark.parametrize("link", ['<a href="book.pdf">ZIP Code Regulation</a>', '<a href="download" type="application/pdf">ZIP Code Regulation</a>'])
def test_zip_word_in_a_pdf_title_does_not_change_its_download_type(link):
    _, references = extract_html(SourceSnapshot(link.encode(), LANDING, "html"))
    assert len(references) == 1 and references[0].get("kind", "pdf") == "pdf"


def test_landing_discovery_lists_members_and_validation_uses_the_same_selection(source):
    source[0][LANDING] = SourceSnapshot(b'<main><a href="book.zip">ZIP</a></main>', LANDING, "html")
    data = pdf(TEXT)
    source[0][URL] = snapshot([("editions/current.pdf", data), ("editions/previous.pdf", pdf(TEXT + " Old wording."))])
    discovery = service.discover_pdf_source(LANDING)
    assert [item.archive_member for item in discovery.references] == ["editions/current.pdf", "editions/previous.pdf"]
    ambiguous = service.validate_pdf(data, "upload.pdf", LANDING)
    assert ambiguous.status == "needs_review" and ambiguous.comparison == "not_checked"
    result = service.validate_pdf(data, "upload.pdf", LANDING, URL, PdfValidationOptions(archive_member="editions/current.pdf"))
    assert result.status == "match" and result.comparison == "exact_file"
    assert result.source_type == "pdf" and result.source_url == URL
    assert result.archive_source.member == "editions/current.pdf"
    assert result.archive_source.sha256 == sha256(source[0][URL].data).hexdigest()
    assert result.source_sha256 == result.archive_source.member_sha256 == sha256(data).hexdigest()


def test_sole_pdf_auto_selection_preserves_changes_identity_and_unsupported_inventory(source):
    text = TEXT + "\nSubmit within 30 days."
    source[0][URL] = snapshot([("book.pdf", pdf(text)), ("metadata.xml", b"<metadata/>"), ("nested.zip", b"unsupported")])
    result = service.validate_pdf(pdf(text.replace("30 days", "60 days")), "upload.pdf", URL)
    assert result.status == "mismatch" and result.document_identity == "match"
    assert result.coverage_complete and result.findings[0].source_archive_member == "book.pdf"
    assert "30" in result.findings[0].expected and "60" in result.findings[0].actual
    assert result.archive_source.unsupported_members == ["metadata.xml", "nested.zip"]
    assert any("unsupported" in item for item in result.limitations)
    source[0][URL] = snapshot([("book.pdf", pdf(EMPLOYMENT, title="Employment Rights Act"))])
    unrelated = service.validate_pdf(pdf(WILDLIFE, title="Employment Rights Act"), "upload.pdf", URL)
    assert unrelated.document_identity == "mismatch"


def test_direct_zip_discovery_and_invalid_member_selection(source):
    source[0][URL] = snapshot([("english.pdf", pdf(TEXT)), ("french.pdf", pdf(TEXT))])
    discovery = service.discover_pdf_source(URL)
    assert discovery.source_type == "zip" and len(discovery.references) == 2
    result = service.validate_pdf(pdf(TEXT), "upload.pdf", URL, options=PdfValidationOptions(archive_member="../private.pdf"))
    assert result.comparison == "not_checked" and "listed in this ZIP" in result.summary


def chapter_archive(missing=False):
    index = b'<main><h1>Synthetic Regulation 2026</h1><nav id="toc"><a href="one.html">Section 1 Scope</a><a href="two.html">Section 2 Records</a></nav></main>'
    entries = [("book/index.html", index), ("book/one.html", f'<main><h1>Section 1 Scope</h1><p>{TEXT.splitlines()[-1]} Additional scope requirements apply to each regulated facility.</p></main>'.encode())]
    if not missing:
        entries.append(("book/two.html", b'<main><h1>Section 2 Records</h1><p>Operators must retain all records for 30 days. These requirements apply to all regulated facilities throughout the period.</p></main>'))
    return snapshot(entries)


@pytest.mark.parametrize("missing", [False, True])
def test_archived_html_collects_declared_chapters_without_external_network(source, missing):
    source[0][URL] = chapter_archive(missing)
    result = service.validate_pdf(pdf(TEXT + "\nSection 2 Records\nOperators must retain all records for 60 days."), "upload.pdf", URL,
        options=PdfValidationOptions(archive_member="book/index.html"))
    assert result.source_type == "html" and result.source_coverage.method == "zip_html"
    assert result.source_coverage.complete is not missing
    assert result.coverage_complete is not missing
    assert source[1] == [URL]
    assert all("archive.invalid" not in item.url for item in result.source_coverage.sections)
    if missing:
        assert result.status == "needs_review"
        assert any(item.status == "unavailable" for item in result.source_coverage.sections)
    else:
        assert result.status == "mismatch"
        assert any(item.source_archive_member == "book/two.html" for item in result.findings)


@pytest.mark.parametrize("markup", [
    '<main><h1>Synthetic Regulation 2026</h1><nav id="toc"><a href="https://other.example/required.html">Section 1</a></nav></main>',
    '<main><h1>Synthetic Regulation 2026</h1><details><summary>Scope</summary><p>Hidden interactive content.</p></details></main>',
    '<main><h1>Synthetic Regulation 2026</h1><nav id="toc"><a href="required.xml">Section 1</a></nav></main>',
])
def test_external_interactive_and_unsupported_required_chapters_prevent_a_match(source, markup):
    source[0][URL] = snapshot([("index.html", markup), ("required.xml", b"<document/>")])
    result = service.validate_pdf(pdf(TEXT), "upload.pdf", URL)
    assert result.status == "needs_review" and not result.coverage_complete
    assert source[1] == [URL]


@pytest.mark.parametrize("name", ["../book.pdf", "/book.pdf", "C:/book.pdf", "dir\\book.pdf", "dir/../book.pdf"])
def test_rejects_unsafe_archive_paths(name):
    data = zipped([(name.replace("\\", "/"), b"%PDF-test")])
    if "\\" in name:
        data = data.replace(name.replace("\\", "/").encode(), name.encode())
    with pytest.raises(ValueError, match="unsafe"):
        inspect_archive(payload(data, discover=True))


def test_rejects_duplicate_paths_symlinks_and_declared_expansion_limits():
    with pytest.raises(ValueError, match="duplicate"):
        inspect_archive(payload(zipped([("Book.pdf", b"one"), ("book.pdf", b"two")]), discover=True))
    link = ZipInfo("link.pdf")
    link.create_system = 3
    link.external_attr = 0o120777 << 16
    with pytest.raises(ValueError, match="symbolic link"):
        inspect_archive(payload(zipped([(link, "target.pdf")]), discover=True))
    data = zipped([("large.pdf", b"x" * 5000)])
    with pytest.raises(ValueError, match="expands"):
        inspect_archive(payload(data, max_expanded_bytes=4999))
    with pytest.raises(ValueError, match="document size"):
        inspect_archive(payload(data, max_bytes=200))
    with pytest.raises(ValueError, match="too many"):
        inspect_archive(payload(zipped([("one.txt", "1"), ("two.txt", "2")]), max_files=1))


def test_corruption_encryption_and_bad_member_types_fail_without_comparison(source):
    valid = zipped([("book.pdf", pdf(TEXT))])
    encrypted = bytearray(valid)
    central = encrypted.index(b"PK\x01\x02")
    struct.pack_into("<H", encrypted, central + 8, 1)
    for data in [b"PK\x03\x04broken", bytes(encrypted), zipped([("book.pdf", b"not a PDF")])]:
        source[0][URL] = SourceSnapshot(data, URL, "zip")
        result = service.validate_pdf(pdf(TEXT), "upload.pdf", URL)
        assert result.status == "unable" and result.comparison == "not_checked" and not result.coverage_complete


def test_downloads_verify_both_archive_and_selected_document(client, source):
    data = pdf(TEXT)
    source[0][URL] = snapshot([("editions/book.pdf", data)])
    report = service.validate_pdf(data, "upload.pdf", URL)
    fields = {"source_url": URL, "source_sha256": report.source_sha256,
        "archive_member": report.archive_source.member, "archive_sha256": report.archive_source.sha256}
    official = client.get("/api/pdf-validations/source-pdf", params=fields)
    assert official.status_code == 200 and official.content == data
    assert 'filename="book.pdf"' in official.headers["content-disposition"]
    generated = client.post("/api/pdf-validations/updated-pdf", data=fields,
        files={"document": ("upload.pdf", data, "application/pdf")})
    assert generated.status_code == 200
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(generated.content)).pages)
    assert "Archive member: editions/book.pdf" in text and fields["archive_sha256"] in text
    invalid = client.get("/api/pdf-validations/source-pdf", params={**fields, "source_sha256": "a" * 64})
    assert invalid.status_code == 409
    source[0][URL] = snapshot([("editions/book.pdf", data), ("new.txt", b"changed packaging")])
    assert client.get("/api/pdf-validations/source-pdf", params=fields).status_code == 409
    assert client.post("/api/pdf-validations/updated-pdf", data=fields,
        files={"document": ("upload.pdf", data, "application/pdf")}).status_code == 409


def test_archive_batches_cache_downloads_and_bind_member_selection(client, source, batch_store):
    data = pdf(TEXT)
    source[0][URL] = snapshot([("one.pdf", data), ("two.pdf", data)])
    fields = {"content_uri": URL, "reference_url": URL, "archive_member": "one.pdf"}
    response = client.post("/api/pdf-validations/batches", json=fields)
    batch = response.json()["data"]["batch_id"]
    for _ in range(2):
        result = client.post("/api/pdf-validations", data={**fields, "batch_id": batch},
            files={"document": ("upload.pdf", data, "application/pdf")})
        assert result.status_code == 200 and result.json()["data"]["status"] == "match"
    assert source[1] == [URL]
    changed = client.post("/api/pdf-validations", data={**fields, "archive_member": "two.pdf", "batch_id": batch},
        files={"document": ("upload.pdf", data, "application/pdf")})
    assert changed.status_code == 409 and source[1] == [URL]
    assert client.delete(f"/api/pdf-validations/batches/{batch}").status_code == 204
    assert not (batch_store / ("batch-" + batch)).exists()


def test_unsupported_only_and_empty_archives_require_review(source):
    for entries in [[], [("document.xml", b"<document/>")]]:
        source[0][URL] = snapshot(entries)
        result = service.validate_pdf(pdf(TEXT), "upload.pdf", URL)
        assert result.status == "needs_review" and result.comparison == "not_checked"
        assert "no supported" in result.summary


def test_archive_limits_are_passed_to_the_isolated_worker(monkeypatch):
    monkeypatch.setattr(settings, "PDF_VALIDATION_ZIP_MAX_FILES", 1)
    with pytest.raises(ValueError, match="too many"):
        resolve_archive(snapshot([("one.pdf", pdf(TEXT)), ("two.pdf", pdf(TEXT))]), discover=True)


def test_archived_html_order_comes_from_the_index_instead_of_zip_entry_order():
    original = chapter_archive()
    with ZipFile(BytesIO(original.data)) as archive:
        reversed_entries = [(name, archive.read(name)) for name in reversed(archive.namelist())]
    result = inspect_archive(payload(zipped(reversed_entries), member="book/index.html"))
    text = "\n".join(item["text"] for item in result["html"]["units"])
    assert text.index("Section 1 Scope") < text.index("Section 2 Records")
    assert result["html"]["complete"]


def test_archive_timeout_unsupported_compression_and_truncated_member_are_rejected():
    data = zipped([("book.pdf", pdf(TEXT))])
    with pytest.raises(ValueError, match="time limit"):
        inspect_archive(payload(data, timeout=-1))
    central = data.index(b"PK\x01\x02")
    unsupported = bytearray(data)
    struct.pack_into("<H", unsupported, central + 10, 99)
    with pytest.raises(ValueError, match="compression"):
        inspect_archive(payload(bytes(unsupported), discover=True))
    truncated = bytearray(data)
    struct.pack_into("<I", truncated, central + 24, 1)
    from zipfile import BadZipFile
    with pytest.raises(BadZipFile):
        inspect_archive(payload(bytes(truncated)))


@pytest.mark.parametrize("content_type,data,expected", [
    ("application/octet-stream", zipped([("book.pdf", b"%PDF-test")]), "zip"),
    ("application/zip", b"<html><h1>Sign in</h1></html>", "html"),
    ("application/zip", b"not an archive", "unknown"),
])
def test_extensionless_downloads_use_response_bytes_and_preserve_access_barriers(monkeypatch, content_type, data, expected):
    from app.services import pdf_validation_source as retrieval
    from app.services.pdf_validation_access import ensure_source_access, SourceAccessError
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    url = "https://publisher.example/download?id=1"
    class Response(BytesIO):
        headers = {"Content-Type": content_type}
        def geturl(self):
            return url
    monkeypatch.setattr(retrieval, "build_opener", lambda *args: SimpleNamespace(open=lambda *args, **kwargs: Response(data)))
    result = retrieval.fetch_source(url, ("publisher.example",), 100000, 2)
    assert result.kind == expected
    if expected == "html":
        with pytest.raises(SourceAccessError, match="access restriction"):
            ensure_source_access(result)


def test_zip_links_on_collected_chapters_and_rendered_pages_are_discovered(source):
    from app.services.pdf_validation_collection import collect_document
    root = b'<main><h1>Synthetic Regulation 2026</h1><nav id="toc"><a href="chapter">Section 1 Scope</a></nav></main>'
    source[0][LANDING] = SourceSnapshot(root, LANDING, "html")
    chapter = "https://publisher.example/chapter"
    source[0][chapter] = SourceSnapshot(f'<main><h1>Section 1 Scope</h1><p>{TEXT}</p><a href="book.zip">ZIP</a></main>'.encode(), chapter, "html")
    source[0][URL] = snapshot([("book.pdf", pdf(TEXT))])
    discovery = service.discover_pdf_source(LANDING)
    assert discovery.references[0].archive_member == "book.pdf"
    interactive = SourceSnapshot(b'<main><h1>Synthetic Regulation 2026</h1><details><summary>Content</summary></details></main>', LANDING, "html")
    rendered = SourceSnapshot(f'<main><h1>Synthetic Regulation 2026</h1><p>{TEXT}</p><a href="book.zip">ZIP</a></main>'.encode(), LANDING, "html")
    collection = collect_document(interactive, ("publisher.example",), service.fetch_source,
        render=lambda *args: (rendered, True, []))
    assert collection["references"][0]["url"] == URL


def test_unapproved_zip_hosts_are_not_fetched(source):
    source[0][LANDING] = SourceSnapshot(b'<main><a href="https://other.example/book.zip">ZIP</a></main>', LANDING, "html")
    discovery = service.discover_pdf_source(LANDING)
    assert not discovery.references[0].available
    result = service.validate_pdf(pdf(TEXT), "upload.pdf", LANDING)
    assert result.status == "needs_review" and result.comparison == "not_checked"
    assert source[1] == [LANDING, LANDING]


def test_archive_download_redirect_preserves_the_linked_selection_url(source):
    source[0][LANDING] = SourceSnapshot(b'<main><a href="book.zip">ZIP</a></main>', LANDING, "html")
    resolved_url = "https://publisher.example/download/edition.zip"
    archive = snapshot([("one.pdf", pdf(TEXT)), ("two.pdf", pdf(TEXT))])
    archive.url = resolved_url
    source[0][URL] = archive
    result = service.validate_pdf(pdf(TEXT), "upload.pdf", LANDING)
    assert result.references[0].url == URL
    chosen = service.validate_pdf(pdf(TEXT), "upload.pdf", LANDING, result.references[0].url,
        PdfValidationOptions(archive_member=result.references[0].archive_member))
    assert chosen.status == "match" and chosen.archive_source.url == resolved_url


def test_html_archive_export_uses_the_same_chapter_manifest(client, source):
    source[0][URL] = chapter_archive()
    upload = pdf(TEXT + "\nAdditional scope requirements apply to each regulated facility.\nSection 2 Records\nOperators must retain all records for 30 days. These requirements apply to all regulated facilities throughout the period.")
    report = service.validate_pdf(upload, "upload.pdf", URL, options=PdfValidationOptions(archive_member="book/index.html"))
    fields = {"source_url": URL, "source_sha256": report.source_sha256, "archive_sha256": report.archive_source.sha256,
        "archive_member": report.archive_source.member}
    generated = client.post("/api/pdf-validations/updated-pdf", data=fields,
        files={"document": ("upload.pdf", upload, "application/pdf")})
    assert generated.status_code == 200
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(generated.content)).pages)
    assert "Archive member: book/index.html" in text and "throughout the period" in text
    assert "archive.invalid" not in text
    assert client.get("/api/pdf-validations/source-pdf", params=fields).status_code == 400


def test_explicitly_dated_archives_keep_historical_versions_separate(source):
    from test_pdf_validation_history import range_options
    first, second = "https://publisher.example/first.zip", "https://publisher.example/second.zip"
    source[0][LANDING] = SourceSnapshot(f'<a href="{first}" data-valid-from="2025-08-01" data-valid-to="2025-09-14">First</a><a href="{second}" data-valid-from="2025-09-15">Second</a>'.encode(), LANDING, "html")
    source[0][first] = SourceSnapshot(zipped([("edition.pdf", pdf(TEXT))]), first, "zip")
    source[0][second] = SourceSnapshot(zipped([("edition.pdf", pdf(TEXT.replace("all regulated", "some regulated")))]), second, "zip")
    result = service.validate_pdf(pdf(TEXT), "upload.pdf", LANDING, options=range_options())
    assert [item.result.status for item in result.versions] == ["match", "mismatch"]
    assert [item.result.archive_source.url for item in result.versions] == [first, second]
    assert not result.history_complete
