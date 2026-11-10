"""Official downloads and complete rebuilt PDFs using synthetic source documents."""
from hashlib import sha256
from io import BytesIO
import subprocess

import pytest
from pypdf import PdfReader

from test_pdf_validation import pdf, TEXT, URL
from app.auth import get_current_user
from app.services import pdf_validation_downloads as downloads
from app.services.pdf_validation_source import SourceSnapshot
from app.services.pdf_validation_export_worker import render_pdf
from app.services.pdf_validation_worker import compare_documents


def fields(data, url=URL):
    return {"source_url": url, "source_sha256": sha256(data).hexdigest()}


def rebuild(client, reference, upload=None, url=URL):
    return client.post("/api/pdf-validations/updated-pdf", data=fields(reference, url),
        files={"document": ("synthetic-upload.pdf", upload or pdf(TEXT), "application/pdf")})


def test_official_download_uses_the_pdf_selected_from_a_landing_page(client, source):
    landing = "https://publisher.example/publication"
    data = pdf(TEXT)
    source[0][landing] = SourceSnapshot(b'<main><a href="document.pdf">Download PDF</a></main>', landing, "html")
    source[0][URL] = SourceSnapshot(data, URL, "pdf")
    report = client.post("/api/pdf-validations", data={"content_uri": landing},
        files={"document": ("synthetic.pdf", data, "application/pdf")}).json()["data"]
    response = client.get("/api/pdf-validations/source-pdf", params={key: report[key] for key in fields(data)})
    assert response.status_code == 200 and response.content == data
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="document.pdf"'
    assert response.headers["cache-control"] == "no-store"
    assert source[1] == [landing, URL, URL]


def test_source_change_blocks_both_downloads_before_generation(client, source):
    previous, current = pdf(TEXT), pdf(TEXT + "\nAmended provision.")
    source[0][URL] = SourceSnapshot(current, URL, "pdf")
    official = client.get("/api/pdf-validations/source-pdf", params=fields(previous))
    updated = rebuild(client, previous)
    assert official.status_code == updated.status_code == 409
    assert "Validate again" in official.json()["message"]


def test_downloads_require_authentication_and_a_valid_digest(client, source):
    assert client.get("/api/pdf-validations/source-pdf", params={"source_url": URL, "source_sha256": "invalid"}).status_code == 422
    client.app.dependency_overrides.pop(get_current_user)
    assert client.get("/api/pdf-validations/source-pdf", params=fields(b"source")).status_code in {401, 403}
    assert rebuild(client, b"source").status_code in {401, 403}
    assert not source[1]


def test_html_cannot_be_downloaded_as_an_official_pdf(client, source):
    body = b"<main><h1>Synthetic Regulation 2026</h1></main>"
    source[0][URL] = SourceSnapshot(body, URL, "html")
    response = client.get("/api/pdf-validations/source-pdf", params=fields(body))
    assert response.status_code == 400 and "does not provide" in response.json()["message"]


def test_updated_pdf_contains_all_source_pages_and_updated_wording(client, source):
    paragraphs = [f"Provision {index}: Submit the application within 30 days." for index in range(90)]
    reference = pdf(TEXT + "\n" + "\n".join(paragraphs[:45]), "\n".join(paragraphs[45:]) + "\nFinal source provision.")
    upload = pdf(TEXT + "\nSubmit the application within 60 days.")
    source[0][URL] = SourceSnapshot(reference, URL, "pdf")
    response = rebuild(client, reference, upload)
    assert response.status_code == 200, response.text[:200] if response.status_code != 200 else ""
    reader = PdfReader(BytesIO(response.content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert len(reader.pages) >= 3 and response.content != reference
    assert "source text copy" in text and URL in text and sha256(reference).hexdigest() in text
    assert "Provision 0:" in text and "Provision 89:" in text and "Final source provision." in text
    assert "30 days" in text and "60 days" not in text
    assert "Source PDF page 1" in text and "Source PDF page 2" in text
    assert response.headers["content-disposition"] == 'attachment; filename="synthetic-upload-updated.pdf"'


def test_updated_pdf_preserves_accents_and_literal_markup(client, source):
    from reportlab.pdfgen import canvas
    output = BytesIO()
    page = canvas.Canvas(output)
    for index, line in enumerate(TEXT.splitlines() + ['Règlement publié à Montréal.', 'Literal <b>words</b> & symbols.']):
        page.drawString(40, 740 - index * 20, line)
    page.save()
    reference = output.getvalue()
    source[0][URL] = SourceSnapshot(reference, URL, "pdf")
    response = rebuild(client, reference)
    assert response.status_code == 200
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
    assert "Règlement publié à Montréal." in text and "Literal <b>words</b> & symbols." in text


def test_incomplete_reference_cannot_be_presented_as_complete_updated_pdf(client, source):
    reference = pdf(TEXT, "")
    source[0][URL] = SourceSnapshot(reference, URL, "pdf")
    response = rebuild(client, reference)
    assert response.status_code == 400 and "Complete readable text" in response.json()["message"]


def test_unrelated_upload_cannot_generate_an_updated_copy(client, source):
    reference = pdf(TEXT)
    source[0][URL] = SourceSnapshot(reference, URL, "pdf")
    upload = pdf("Wildlife Protection Rules\nRangers monitor forests wetlands grasslands endangered species and protected habitats.", title="Wildlife Protection Rules")
    response = rebuild(client, reference, upload)
    assert response.status_code == 400 and "same document" in response.json()["message"]


def test_complete_static_document_can_be_rebuilt_without_website_navigation(client, source):
    url = "https://publisher.example/full-document"
    body = f"<nav>Website navigation</nav><main><h1>Synthetic Regulation 2026</h1><p>{TEXT}</p><p>Final provision: retain all records.</p></main>".encode()
    source[0][url] = SourceSnapshot(body, url, "html")
    response = rebuild(client, body, url=url)
    assert response.status_code == 200
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
    assert "Final provision: retain all records." in text and "Website navigation" not in text


def test_missing_font_glyphs_are_rejected_instead_of_silently_dropping_characters():
    with pytest.raises(ValueError, match="every source character"):
        render_pdf({"units": [{"text": "Unsupported character \U0001f642", "page": 1}]}, "Synthetic title",
            {"filename": "synthetic.pdf", "source_url": URL})


def test_unicode_hyphens_keep_their_characters_in_the_rebuilt_text():
    text = "A non\u2010government and non\u2011profit organization."
    data = render_pdf({"units": [{"text": text, "page": 1}]}, "Synthetic Regulation",
        {"filename": "synthetic.pdf", "source_url": URL, "source_sha256": "b" * 64, "max_pages": 10, "max_bytes": 1000000})
    extracted = "\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)
    assert text in extracted


def test_identical_text_uses_the_visible_document_title_for_export():
    document = {"units": [{"text": "Current to September 21, 2026\nAccessible Canada Regulations\nSection 1 Scope\nThis regulation applies to all facilities.", "page": 1}],
        "complete": True, "title": "Current to September 21, 2026"}
    result = compare_documents(document, document, URL)
    assert result["document_identity"] == "match"
    assert result["identity_source_title"] == "Accessible Canada Regulations"


def test_generation_timeout_releases_download_capacity(source, monkeypatch):
    data = pdf(TEXT)
    source[0][URL] = SourceSnapshot(data, URL, "pdf")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("synthetic-worker", 1)
    monkeypatch.setattr(downloads.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="time limit"):
        downloads.updated_pdf(data, "synthetic.pdf", URL, sha256(data).hexdigest(), lambda *args: source[0][URL])
    assert downloads.official_pdf(URL, sha256(data).hexdigest(), lambda *args: source[0][URL])[0] == data
