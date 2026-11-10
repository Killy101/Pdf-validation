"""Language-scoped comparison, formatting equivalence, and dated evidence."""
from io import BytesIO

import pytest
from reportlab.pdfgen import canvas

from test_pdf_validation import URL
from app.services import pdf_validation as service
from app.services.pdf_validation_dates import current_to, website_dates
from app.services.pdf_validation_export_worker import generate
from app.services.pdf_validation_layout import comparison_scope
from app.services.pdf_validation_source import SourceSnapshot
from app.services.pdf_validation_text import normalize_wraps, tokens
from app.services.pdf_validation_worker import compare_documents, extract_pdf


ENGLISH = ["Synthetic Regulations", "The employee must submit the report.", "The report is for the public.",
           "The authority must retain the record.", "The student uses vacation periods.", "The application is under these regulations.",
           "The deadline is within 30 days.", "The employee must receive the notice."]
FRENCH = ["Règlement synthétique", "Les employés doivent présenter le rapport.", "Le rapport est pour le public.",
          "Les autorités doivent garder les documents.", "Les périodes de vacances sont prévues.", "La demande est dans le règlement.",
          "Le délai est de trente jours.", "Les employés doivent recevoir les avis."]


def document_pdf(parallel=False, changed=False, wrapped=False, together=False):
    output = BytesIO()
    writer = canvas.Canvas(output, pagesize=(612, 792))
    writer.setTitle("Synthetic Regulations")
    for _page in range(1 if together else 2):
        writer.setFont("Helvetica", 9)
        english = [line.replace("30 days", "60 days") if changed else line for line in ENGLISH]
        if wrapped:
            english[4:5] = ["The student uses va-", "cation periods."]
        if together:
            english *= 2
        for index, line in enumerate(english):
            writer.drawString(48, 700 - index * 20, line)
        if parallel:
            for index, line in enumerate(FRENCH):
                writer.drawString(318, 700 - index * 20, line)
        writer.showPage()
    writer.save()
    return output.getvalue()


def extract(data):
    return extract_pdf(data, 100, 100000)


def test_english_upload_compares_only_the_confirmed_parallel_english_column():
    upload, reference = extract(document_pdf()), extract(document_pdf(parallel=True))
    result = compare_documents(upload, reference, URL)
    assert result["status"] == "match" and not result["findings"]
    assert result["comparison_language"] == "en"
    assert result["pdf_layout"]["columns"] == 1 and result["source_layout"]["columns"] == 2
    assert result["source_layout"]["languages"] == ["en", "fr"]
    assert "French column" in result["scope_notes"][0]


def test_line_wraps_do_not_hide_real_deadline_changes_or_add_french_findings():
    result = compare_documents(extract(document_pdf(changed=True)), extract(document_pdf(parallel=True, wrapped=True)), URL)
    assert result["status"] == "mismatch" and len(result["findings"]) == 2
    for finding in result["findings"]:
        assert "30" in finding["expected"] and "60" in finding["actual"]
        assert "vacation" not in finding["actual"] and "employés" not in finding["expected"]
        assert finding["pdf_page"] == finding["source_page"]


def test_unknown_upload_language_does_not_silently_exclude_a_column():
    upload, reference = extract(document_pdf()), extract(document_pdf(parallel=True))
    upload["layout"]["languages"] = ["unknown"]
    _, selected, evidence = comparison_scope(upload, reference, URL)
    assert evidence["comparison_language"] == "all"
    assert selected is reference


def test_different_pagination_does_not_reject_matching_english_scope(source):
    source[0][URL] = SourceSnapshot(document_pdf(parallel=True), URL, "pdf")
    result = service.validate_pdf(document_pdf(together=True), "synthetic.pdf", URL)
    assert result.status == "match" and result.comparison_language == "en"
    assert len(result.findings) == 1 and result.findings[0].kind == "page_count"
    assert result.findings[0].severity == "info"


def test_unassigned_source_pages_keep_scoped_coverage_incomplete():
    upload, reference = extract(document_pdf()), extract(document_pdf(parallel=True))
    reference["units"].append({"text": "Unassigned source page with further provisions.", "page": 3, "columns": 1})
    result = compare_documents(upload, reference, URL)
    assert result["status"] == "needs_review" and not result["coverage_complete"]
    assert "coverage is incomplete" in " ".join(result["scope_notes"])


@pytest.mark.parametrize("left,right,equal", [
    ("The student's va-\ncation periods. ( employé)", "The student's vacation periods.(employé)", True),
    ("A long-\nterm permit.", "A long-term permit.", True),
    ("Re-sign the form.", "Resign the form.", False),
    ("Submit within 10-\n20 days.", "Submit within 1020 days.", False),
    ("Submit within 30 days.", "Submit within 60 days.", False),
])
def test_formatting_normalization_preserves_meaningful_hyphens_numbers_and_punctuation(left, right, equal):
    document = lambda text: {"units": [{"text": text}], "complete": True}
    first, second = document(left), document(right)
    assert (tokens(normalize_wraps(first, second))[0] == tokens(normalize_wraps(second, first))[0]) is equal


@pytest.mark.parametrize("text,expected", [("Regulations are current to 2026-06-17", "2026-06-17"),
    ("Current to September 21, 2026", "2026-09-21"), ("Current to 2026-99-01", None),
    ("Downloaded on an unknown day", None)])
def test_current_to_dates_do_not_invent_download_or_amendment_dates(text, expected):
    assert current_to(text) == expected


def test_landing_page_modification_date_survives_following_the_official_pdf(client, source):
    landing = "https://publisher.example/regulations"
    html = f'<meta name="dcterms.modified" content="2026-09-28"><main><h1>Synthetic Regulations</h1><a href="{URL}">PDF</a></main>'.encode()
    source[0][landing] = SourceSnapshot(html, landing, "html")
    data = document_pdf(parallel=True)
    source[0][URL] = SourceSnapshot(data, URL, "pdf")
    response = client.post("/api/pdf-validations", data={"content_uri": landing},
        files={"document": ("synthetic.pdf", document_pdf(), "application/pdf")})
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["website_modified_on"] == "2026-09-28" and result["comparison_language"] == "en"
    assert result["pdf_dates"]["creation_date"] and "download_date" not in result["pdf_dates"]


def test_visible_website_modification_date_takes_priority_over_stale_head_metadata():
    body = '<meta name="dcterms.modified" content="2025-12-05"><div id="wb-dtmd">Date modified: <time property="dateModified">\ufeff2026-09-28</time></div>'
    assert website_dates(SourceSnapshot(body.encode(), URL, "html")) == "2026-09-28"


def test_updated_pdf_uses_the_same_english_scope_and_keeps_source_page_numbers():
    import base64
    from pypdf import PdfReader
    payload = {"upload": base64.b64encode(document_pdf()).decode(), "reference": base64.b64encode(document_pdf(parallel=True)).decode(),
        "filename": "synthetic.pdf", "source_url": URL, "source_sha256": "b" * 64,
        "max_pages": 100, "max_characters": 100000, "max_bytes": 1000000}
    data = base64.b64decode(generate(payload)["data"])
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)
    assert "French column is outside this comparison" in " ".join(text.split())
    assert "The employee must submit the report." in text and "Les employés doivent" not in text
    assert "Source PDF page 2" in text
