"""Readable excerpts, cover titles, and physical PDF page ranges."""
from test_pdf_validation import URL
from app.services.pdf_validation_worker import compare_documents


def document(pages, title="Synthetic Regulations"):
    return {"units": [{"text": text, "page": index} for index, text in enumerate(pages, 1)],
            "title": title, "complete": True}


def test_excerpts_preserve_original_case_punctuation_and_line_breaks():
    expected = "The application must be filed within 30 days.\nKeep a signed copy at https://publisher.example/forms."
    actual = expected.replace("30 days", "60 days")
    result = compare_documents(document([actual]), document([expected]), URL)
    finding = result["findings"][0]
    assert "The application" in finding["actual"] and "60 days." in finding["actual"]
    assert "\nKeep" in finding["actual"] and "30 days." in finding["expected"]
    assert " ." not in finding["actual"]
    assert "60 days" in finding["pdf_search_text"] and finding["pdf_search_text"] != "60"
    assert finding["pdf_page"] == finding["pdf_page_end"] == 1
    assert finding["expected"][slice(*finding["expected_change"])] == "30"
    assert finding["actual"][slice(*finding["actual_change"])] == "60"


def test_long_findings_report_all_affected_pages_and_excerpt_limits():
    reference = document([("source " + str(index) + " ") * 1800 for index in range(3)])
    upload = document([("uploaded " + str(index) + " ") * 1800 for index in range(3)])
    result = compare_documents(upload, reference, URL)
    finding = result["findings"][0]
    assert finding["pdf_page"] == 1 and finding["pdf_page_end"] == 3
    assert finding["source_page"] == 1 and finding["source_page_end"] == 3
    assert finding["excerpt_truncated"] and len(finding["actual"]) <= 900
    assert finding["actual"].endswith("...")
    assert 0 <= finding["actual_change"][0] <= finding["actual_change"][1] <= len(finding["actual"])


def test_sentence_anchors_locate_distant_changes_after_repagination():
    clauses = [f"Clause {index}: The permit for zone {index} requires submission within 30 days and records details of protected facilities under this regulation."
               for index in range(210)]
    expected = ["\n".join(clauses[index:index + 4]) for index in range(0, len(clauses), 4)]
    uploaded = clauses.copy()
    for index in (12, 180):
        uploaded[index] = uploaded[index].replace("30 days", "60 days")
    actual = ["\n".join(uploaded[index:index + 3]) for index in range(0, len(uploaded), 3)]
    result = compare_documents(document(actual), document(expected), URL)
    changed = [finding for finding in result["findings"] if "60 days" in finding["actual"]]
    assert result["status"] == "mismatch" and len(result["findings"]) == len(changed) == 2
    assert [finding["pdf_page"] for finding in changed] == [5, 61]
    assert [finding["source_page"] for finding in changed] == [4, 46]
    assert all(finding["pdf_page"] == finding["pdf_page_end"] for finding in changed)


def test_missing_source_text_uses_a_nearby_page_and_searchable_anchor():
    reference = document(["Missing preliminary provision.\nThe application requires a signed statement before the permit can be issued."])
    upload = document(["The application requires a signed statement before the permit can be issued."])
    finding = compare_documents(upload, reference, URL)["findings"][0]
    assert finding["kind"] == "missing_content" and finding["approximate_location"]
    assert finding["actual"] == "" and finding["pdf_page"] == finding["pdf_page_end"] == 1
    assert finding["actual_change"] == [0, 0]
    assert "application requires" in finding["pdf_search_text"]


def test_search_phrase_stays_on_the_page_containing_the_change():
    reference = document(["Previous-page-only-marker.", "Expired permits require a signed application."])
    upload = document(["Previous-page-only-marker.", "Renewed permits require a signed application."])
    finding = compare_documents(upload, reference, URL)["findings"][0]
    assert finding["pdf_page"] == 2
    assert finding["pdf_search_text"].startswith("Renewed permits")
    assert "marker" not in finding["pdf_search_text"]


def test_cover_dates_and_enabling_act_do_not_hide_a_shared_visible_title():
    body = "Regulated employers must publish accessible plans and retain progress reports. The commissioner reviews applications and public feedback under these regulations."
    reference = document(["Current to September 21, 2026\nPublished by the Minister of Justice\nhttp://laws.justice.gc.ca\nCANADA\nCONSOLIDATION\nAccessible Canada Regulations\n" + body],
                         title="Current to September 21, 2026")
    upload = document(["ACCESSIBLE CANADA ACT\nRegistration 2021-12-13\nAccessible Canada Regulations\n" + body.replace("public feedback", "written feedback")],
                      title="ACCESSIBLE CANADA ACT")
    result = compare_documents(upload, reference, URL)
    assert result["document_identity"] == "match" and result["status"] == "mismatch"
    assert result["identity_pdf_title"] == result["identity_source_title"] == "Accessible Canada Regulations"
    assert result["findings"] and all(finding["kind"] != "document_mismatch" for finding in result["findings"])


def test_shared_parent_act_does_not_confirm_unrelated_regulations():
    upload = document(["Wildlife Regulations\nCommon Enabling Act\nRangers protect endangered species habitats forests wetlands migration breeding ecology conservation hunting populations."], title="Wildlife Regulations")
    reference = document(["Employment Regulations\nCommon Enabling Act\nWorkers receive salaries benefits pensions overtime payroll contracts insurance compensation workplace hours unions."], title="Employment Regulations")
    assert compare_documents(upload, reference, URL)["document_identity"] != "match"


def test_common_legal_boilerplate_and_parent_act_are_not_shared_document_titles():
    body = "The application requires a written report and annual public notice. The commissioner may request records and issue a permit after review."
    upload = document(["Wildlife Regulations\nCommon Enabling Act\n" + body], title="Wildlife Regulations")
    reference = document(["Employment Regulations\nCommon Enabling Act\n" + body.replace("annual", "monthly")], title="Employment Regulations")
    assert compare_documents(upload, reference, URL)["document_identity"] != "match"


def test_unconfirmed_identity_returns_the_detected_visible_titles():
    result = compare_documents(document(["First Document\nShort text has changed."]),
                               document(["Second Document\nShort text is different."]), URL)
    assert result["document_identity"] == "needs_review"
    assert result["identity_pdf_title"] == "First Document" and result["identity_source_title"] == "Second Document"
