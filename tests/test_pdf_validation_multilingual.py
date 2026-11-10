"""Original-language content comparison follows the uploaded PDF's scope."""
from io import BytesIO

import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from test_pdf_validation import URL
from app.services import pdf_validation as service
from app.services.pdf_validation_language import language
from app.services.pdf_validation_layout import document_layout
from app.services.pdf_validation_navigation import navigation, section_key
from app.services.pdf_validation_source import SourceSnapshot, extract_html
from app.services.pdf_validation_worker import compare_documents, extract_pdf


EN = "The operator must submit the report for the application and retain the records under these regulations. The deadline for the report is 30 days and the authority must receive the signed copy."
FR = "Les employés doivent présenter le rapport dans les trente jours. Les autorités doivent garder les documents pour les demandes et les avis dans le règlement. Le rapport est pour le public et les employés."
ES = "Los operadores deberán presentar el informe para las instalaciones. La autoridad deberá conservar los documentos para las solicitudes y los avisos. El plazo para el informe es de 30 días y los documentos se guardan para la revisión."


def document(text, language_code="unknown", title=None):
    return {"title": title or text.splitlines()[0], "complete": True, "units": [{"text": text, "page": 1}],
        "layout": {"columns": 1, "languages": [language_code]}, "pages": 1}


@pytest.mark.parametrize("code,text", [("en", EN), ("fr", FR), ("es", ES),
    ("ja", "事業者は報告書を提出しなければならない。記録を保存することが必要である。申請の期限は三十日である。"),
    ("ko", "사업자는 보고서를 제출하여야 하며 관련 기록을 보관하여야 한다. 신청 기한은 삼십 일이다."),
    ("und-Arab", "يجب على الجهة تقديم التقرير والاحتفاظ بالسجلات وفقاً لأحكام هذه اللائحة وتقديم الطلب خلال ثلاثين يوماً.")])
def test_language_evidence_does_not_default_to_english(code, text):
    assert language(text) == code


def test_french_upload_selects_french_column_and_retains_real_number_changes():
    units = [{"text": f'Synthetic Regulations\n{EN}\nRèglement synthétique\n{FR}', "page": page,
              "columns": 2, "left": "Synthetic Regulations\n" + EN, "right": "Règlement synthétique\n" + FR} for page in (1, 2)]
    source = {"title": "Synthetic Regulations", "units": units, "complete": True, "pages": 2, "layout": document_layout(units)}
    upload = document("Règlement synthétique\n" + FR, "fr")
    upload["units"] *= 2
    result = compare_documents(upload, source, URL)
    assert result["status"] == "match" and result["comparison_language"] == "fr" and result["language_alignment"] == "selected"
    assert result["document_identity"] == "match" and not result["findings"]
    changed = {**upload, "units": [{"text": unit["text"].replace("trente", "soixante"), "page": 1} for unit in upload["units"]]}
    result = compare_documents(changed, source, URL)
    assert result["status"] == "mismatch" and all("The operator" not in item["expected"] for item in result["findings"])


def test_unknown_bilingual_scope_does_not_create_false_content_findings():
    upload = document("Règlement synthétique\n" + FR)
    reference = document("Synthetic Regulations\n" + EN + "\n" + FR)
    reference["layout"] = {"columns": 2, "languages": ["en", "fr"], "parallel_bilingual": True}
    result = compare_documents(upload, reference, URL)
    assert result["status"] == "needs_review" and result["language_alignment"] == "needs_review"
    assert result["checked_pdf_pages"] == 0 and not result["findings"]


def test_unconfirmed_column_language_does_not_turn_another_language_into_missing_text():
    upload = document("मूल नियम\nआवेदन और संबंधित अभिलेख अधिकारी के समक्ष प्रस्तुत किए जाने चाहिए। इन अभिलेखों को सुरक्षित रखा जाना चाहिए।")
    source = document(EN + "\n" + upload["units"][0]["text"])
    source["layout"] = {"columns": 2, "languages": ["unknown"], "column_languages": ["en", "unknown"]}
    result = compare_documents(upload, source, URL)
    assert result["status"] == "needs_review" and not result["findings"] and not result["coverage_complete"]


def test_two_columns_in_the_same_language_are_both_compared():
    upload = document("Synthetic Regulations\n" + EN + "\n" + EN, "en")
    source = {**upload, "layout": {"columns": 2, "languages": ["en"], "column_languages": ["en", "en"]}}
    assert compare_documents(upload, source, URL)["status"] == "match"


def test_single_bilingual_page_can_select_the_corresponding_language():
    unit = {"text": EN + "\n" + FR, "left": EN, "right": FR, "columns": 2, "page": 1}
    layout = document_layout([unit])
    assert layout["parallel_bilingual"] and layout["languages"] == ["en", "fr"]
    source = {"units": [unit], "complete": True, "pages": 1, "layout": layout}
    result = compare_documents(document(FR, "fr"), source, URL)
    assert result["status"] == "match" and result["comparison_language"] == "fr"


def html_source():
    markup = f'<html><body><main><section lang="en"><h1>Synthetic Regulations</h1><p>{EN}</p></section><section lang="es"><h1>Reglamento de instalaciones</h1><p>{ES}</p></section></main></body></html>'
    return extract_html(SourceSnapshot(markup.encode(), URL, "html", "text/html"), collection=True)[0]


def test_spanish_html_selection_excludes_english_and_finds_changed_number():
    source = html_source()
    source["complete"] = True
    upload = document("Reglamento de instalaciones\n" + ES.replace("30 días", "60 días"), "es")
    result = compare_documents(upload, source, URL)
    assert result["status"] == "mismatch" and result["comparison_language"] == "es" and result["document_identity"] == "match"
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["expected"][slice(*finding["expected_change"])] == "30"
    assert finding["actual"][slice(*finding["actual_change"])] == "60"


def test_unknown_pdf_language_can_use_strong_original_text_evidence_for_tagged_html():
    result = compare_documents(document("Reglamento de instalaciones\n" + ES), html_source(), URL)
    assert result["status"] == "match" and result["comparison_language"] == "es"
    result = compare_documents(document("Unclear title\nVery short ambiguous text."), html_source(), URL)
    assert result["status"] == "needs_review" and not result["findings"]


def test_complete_multilingual_text_can_match_without_excluding_any_language():
    source = html_source()
    result = compare_documents(document("\n".join(unit["text"] for unit in source["units"])), source, URL)
    assert result["status"] == "match" and result["comparison_language"] == "all"
    assert result["language_alignment"] == "all_text" and not result["findings"]


def test_uploaded_spanish_pdf_is_validated_and_exported_against_its_original_html_language(client, source):
    import textwrap
    from pypdf import PdfReader
    root = "https://publisher.example/reglamento"
    html = f'<html><body><main><section lang="en"><h1>Synthetic Regulations</h1><p>{EN}</p></section><section lang="es"><h1>Reglamento de instalaciones</h1><p>{ES}</p></section></main></body></html>'
    source[0][root] = SourceSnapshot(html.encode(), root, "html", "text/html")
    output = BytesIO()
    writer = canvas.Canvas(output)
    writer.setTitle("Reglamento de instalaciones")
    for index, line in enumerate(["Reglamento de instalaciones", *textwrap.wrap(ES.replace("30 días", "60 días"), width=80)]):
        writer.drawString(40, 740 - index * 18, line)
    writer.save()
    data = output.getvalue()
    report = service.validate_pdf(data, "synthetic.pdf", root)
    assert report.status == "mismatch" and report.comparison_language == "es" and report.language_alignment == "selected"
    assert report.document_identity == "match" and len(report.findings) == 1
    response = client.post("/api/pdf-validations/updated-pdf", data={"source_url": root, "source_sha256": report.source_sha256},
        files={"document": ("synthetic.pdf", data, "application/pdf")})
    assert response.status_code == 200
    text = " ".join(" ".join(page.extract_text().split()) for page in PdfReader(BytesIO(response.content)).pages)
    assert "30 días" in text and "60 días" not in text and "The operator must" not in text


@pytest.mark.parametrize("expected,actual", [
    ("事業者は申請書を提出しなければならない。期限は30日である。", "事業者は申請書を提出しなければならない。\n期限は60日である。"),
    ("经营者必须提交申请并保存有关记录。期限为30日。", "经营者必须提交申请并保存有关记录。\n期限为60日。"),
    ("يجب تقديم الطلب خلال 30 يوماً والاحتفاظ بالسجلات للمراجعة.", "يجب تقديم الطلب خلال 60 يوماً والاحتفاظ بالسجلات للمراجعة.")])
def test_non_latin_number_changes_keep_precise_page_and_character_evidence(expected, actual):
    finding = compare_documents(document(actual, title="Original document"), document(expected, title="Original document"), URL)["findings"][0]
    assert finding["pdf_page"] == 1
    assert finding["expected"][slice(*finding["expected_change"])] == "30"
    assert finding["actual"][slice(*finding["actual_change"])] == "60"
    assert compare_documents(document(expected), document(expected.replace("。", "。\n")), URL)["status"] == "match"


def test_unspaced_cjk_pdf_page_is_readable():
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    output = BytesIO()
    writer = canvas.Canvas(output)
    writer.setFont("STSong-Light", 10)
    writer.drawString(40, 740, "经营者必须提交申请并保存有关记录以供监管机关进行检查")
    writer.save()
    result = extract_pdf(output.getvalue(), 10, 10000)
    assert result["complete"] and not result["blank_pages"]


@pytest.mark.parametrize("heading,key", [("Article 1 Objet", "section:1"), ("Artículo 2 Ámbito", "section:2"),
    ("Kapitel 3", "chapter:3"), ("第4条 適用", "section:4"), ("제5조 적용", "section:5"), ("المادة ٦", "section:6")])
def test_localized_numbered_headings_have_stable_section_keys(heading, key):
    assert section_key(heading) == key


def test_localized_toc_full_text_and_pagination_links_are_discovered():
    root = "https://publisher.example/reglement/index.html"
    index = '<html lang="fr"><body><main><h1>Règlement synthétique</h1><nav aria-label="Sommaire"><a href="chapitre1.html">Chapitre 1</a></nav><a href="complet.html">Texte intégral</a></main></body></html>'
    nav = navigation(SourceSnapshot(index.encode(), root, "html"))
    assert nav["links"][0]["url"].endswith("chapitre1.html") and nav["complete"][0]["url"].endswith("complet.html")
    page = SourceSnapshot(f'<html lang="fr"><body><main><h1>Règlement synthétique</h1><p>{FR}</p><a href="suivant.html">Page suivante</a></main></body></html>'.encode(), root, "html")
    assert navigation(page)["links"][0]["kind"] == "continuation"
    body, _ = extract_html(page, collection=True)
    assert "Page suivante" not in " ".join(unit["text"] for unit in body["units"])
