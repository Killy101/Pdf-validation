"""Reference URL discovery: finding the uploaded document several navigation levels inside a website."""
from urllib.error import HTTPError

import pytest

from test_pdf_validation import pdf
from app.auth import get_current_user
from app.services import pdf_validation as service
from app.services.pdf_validation_discovery import discover_reference, link_score, document_hints, page_links
from app.services.pdf_validation_source import SourceSnapshot

SITE = "https://statutes.example"
LANDING = SITE + "/statutes/"
BODIES = {
    "1": ("GENERAL PROVISIONS", "Definitions of words used throughout the revised statutes, construction rules, seals, holidays, and the official state symbols adopted by the legislature."),
    "4": ("JUDICIARY", "The Supreme Judicial Court consists of a Chief Justice and six associate justices. The Chief Justice is the head of the judicial branch and prepares the budget for the courts, appoints clerks, and supervises the probate, district and superior courts."),
    "5": ("ADMINISTRATIVE PROCEDURES AND SERVICES", "State agencies adopt rules after public notice and comment. The commissioner of administrative and financial services manages personnel, purchasing, buildings, and the state retirement system."),
    "14": ("COURT PROCEDURE -- CIVIL", "Civil actions are commenced by filing a complaint. Limitations of actions, attachment, trustee process, executions, and the forms of civil pleading are prescribed."),
}


def title_pdf(number, change=None):
    heading, text = BODIES[number]
    body = text if not change else text.replace(*change)
    return pdf(f"MRS Title {number}. {heading}\nTITLE {number}\n{heading}\nCHAPTER 1\n{body}", f"Chapter 2\n{body} Continued provisions of Title {number}.")


def html(body, url):
    return SourceSnapshot(f"<html><head><title>Statutes</title></head><body>{body}</body></html>".encode(), url, "html", "text/html")


def title_page(number):
    return html(f'<h1>Title {number}: {BODIES[number][0]}</h1><a href="./title{number}.pdf">Title {number} PDF</a>'
                f'<a href="./title{number}.docx">Title {number} MS-Word</a><a href="./ch1.html">Chapter 1</a>', f"{SITE}/statutes/{number}/index.html")


def site(source, landing_body, titles=("1", "4", "5", "14")):
    source[0][LANDING] = html(landing_body, LANDING)
    for number in titles:
        source[0][f"{SITE}/statutes/{number}/index.html"] = title_page(number)
        source[0][f"{SITE}/statutes/{number}/title{number}.pdf"] = SourceSnapshot(title_pdf(number), f"{SITE}/statutes/{number}/title{number}.pdf", "pdf")
    return source


TITLE_LIST = "".join(f'<li><a href="{n}/index.html">TITLE {n}: {BODIES[n][0]}</a></li>' for n in ("1", "4", "5", "14"))


def run(source, upload=None):
    return discover_reference(upload or title_pdf("4"), "title4.pdf", source[0][LANDING], ("statutes.example",), service.fetch_source)


def test_ordinary_links_lead_to_the_requested_title_and_record_the_path(source):
    site(source, f"<main><ul>{TITLE_LIST}</ul></main>")
    trail, document = run(source)
    assert trail["status"] == "found" and document.url.endswith("/statutes/4/title4.pdf")
    assert [step["label"] for step in trail["path"]] == ["Reference URL", "TITLE 4: JUDICIARY", "Title 4 PDF"]
    fetched = source[1]
    assert f"{SITE}/statutes/5/index.html" not in fetched and f"{SITE}/statutes/14/index.html" not in fetched
    assert not any(url.endswith(("title5.pdf", "title14.pdf", "title1.pdf")) for url in fetched)
    statuses = {item["label"]: item["status"] for item in trail["items"]}
    assert statuses["TITLE 5: ADMINISTRATIVE PROCEDURES AND SERVICES"] == "not_relevant"
    assert statuses["Title 4 MS-Word"] == "not_relevant"


def test_designations_distinguish_similar_titles():
    hints = {"primary": ("title", "4"), "designations": [("title", "4")], "keywords": ["judiciary"]}
    assert link_score("TITLE 4: JUDICIARY", f"{SITE}/statutes/4/", hints, False) > 0
    assert link_score("TITLE 14: COURT PROCEDURE", f"{SITE}/statutes/14/", hints, False) < 0
    assert link_score("TITLE 4-A: COURTS", f"{SITE}/statutes/4-A/", hints, False) < 0


def test_the_first_pdf_on_the_landing_page_is_not_assumed_to_be_the_document(source):
    site(source, f'<a href="annual-report.pdf">Annual report (PDF)</a><a href="5/title5.pdf">Title 5 PDF</a><ul>{TITLE_LIST}</ul>')
    source[0][LANDING.rstrip("/") + "/annual-report.pdf"] = SourceSnapshot(pdf("Annual report of the statute revision office\nBudget figures and staffing levels for the year."), "", "pdf")
    trail, document = run(source)
    assert trail["status"] == "found" and document.url.endswith("/statutes/4/title4.pdf")
    assert not any(url.endswith("5/title5.pdf") for url in source[1])


def test_hover_menus_hidden_in_the_page_and_dropdown_selects_are_followed(source):
    landing = ('<nav class="menu"><ul><li><a href="#">Laws</a><ul class="dropdown" style="display:none">'
               '<li><a href="browse/">Browse the statutes</a></li></ul></li></ul></nav><p>Welcome</p>')
    site(source, landing)
    source[0][LANDING + "browse/"] = html('<form><select name="go"><option value="">Choose a title</option>'
        + "".join(f'<option value="/statutes/{n}/index.html">Title {n} - {BODIES[n][0]}</option>' for n in ("1", "4", "5"))
        + "</select></form>", LANDING + "browse/")
    links, _ = page_links(source[0][LANDING])
    assert any(item["source"] == "hidden_menu" and item["url"] == LANDING + "browse/" for item in links)
    trail, document = run(source)
    assert trail["status"] == "found"
    assert [step["label"] for step in trail["path"]] == ["Reference URL", "Browse the statutes", "Title 4 - JUDICIARY", "Title 4 PDF"]


def test_javascript_menus_are_rendered_only_when_static_html_has_no_navigation(source, monkeypatch):
    site(source, '<div id="app"></div><script src="/app.js"></script>')
    rendered = []
    def render(url, hosts, timeout):
        rendered.append(url)
        return html(f"<nav><ul>{TITLE_LIST}</ul></nav>", url)
    trail, document = discover_reference(title_pdf("4"), "t.pdf", source[0][LANDING], ("statutes.example",), service.fetch_source, render=render)
    assert rendered == [LANDING] and trail["browser_pages"] == 1
    assert trail["status"] == "found" and document.url.endswith("title4.pdf")
    rendered.clear()
    site(source, f"<ul>{TITLE_LIST}</ul>")
    discover_reference(title_pdf("4"), "t.pdf", source[0][LANDING], ("statutes.example",), service.fetch_source, render=render)
    assert rendered == []


def test_paginated_lists_and_deeper_levels_are_explored(source):
    site(source, '<ul><li><a href="1/index.html">TITLE 1: GENERAL PROVISIONS</a></li></ul><a rel="next" href="?page=2">Next page</a>')
    source[0][LANDING + "?page=2"] = html('<ul><li><a href="part-b/">Part B titles</a></li></ul>', LANDING + "?page=2")
    source[0][LANDING + "part-b/"] = html('<a href="../4/index.html">TITLE 4: JUDICIARY</a><a href="../5/index.html">TITLE 5: ADMINISTRATIVE</a>', LANDING + "part-b/")
    trail, document = run(source)
    assert trail["status"] == "found" and document.url.endswith("title4.pdf")
    assert len(trail["path"]) == 5


def test_duplicate_links_to_one_document_are_checked_once(source):
    site(source, f'<ul>{TITLE_LIST}</ul><a href="4/index.html">Judiciary</a><a href="4/index.html#top">Title 4</a>')
    trail, _ = run(source)
    assert source[1].count(f"{SITE}/statutes/4/index.html") == 1
    assert sum(item["url"] == f"{SITE}/statutes/4/index.html" for item in trail["items"]) == 1


@pytest.mark.parametrize("code, status", [(404, "unavailable"), (403, "inaccessible")])
def test_missing_or_blocked_documents_are_explained(source, code, status):
    site(source, f"<ul>{TITLE_LIST}</ul>")
    url = f"{SITE}/statutes/4/title4.pdf"
    source[0][url] = HTTPError(url, code, "Error", {}, None)
    trail, document = run(source)
    assert document is None and trail["status"] == "not_found"
    item = next(item for item in trail["items"] if item["url"] == url)
    assert item["status"] == status and str(code) in item["reason"]
    assert "No PDF matching Title 4" in trail["summary"] and "checked" in trail["summary"]


def test_a_different_document_is_rejected_after_verification(source):
    site(source, f"<ul>{TITLE_LIST}</ul>")
    source[0][f"{SITE}/statutes/4/title4.pdf"] = SourceSnapshot(title_pdf("5"), f"{SITE}/statutes/4/title4.pdf", "pdf")
    trail, document = run(source)
    assert document is None
    assert next(item for item in trail["items"] if item["url"].endswith("4/title4.pdf"))["status"] == "rejected"


def test_off_site_links_are_not_followed(source):
    site(source, f'<ul>{TITLE_LIST}</ul><a href="https://courts.example/judicial">Judicial branch TITLE 4</a>')
    trail, _ = run(source)
    assert not any("courts.example" in url for url in source[1])
    assert next(item for item in trail["items"] if "courts.example" in item["url"])["reason"] == "Outside the reference website."


def test_reference_mode_validates_the_discovered_pdf(source):
    site(source, f"<ul>{TITLE_LIST}</ul>")
    options = service.PdfValidationOptions(source_mode="reference")
    result = service.validate_pdf(title_pdf("4"), "title4.pdf", LANDING, options=options)
    assert result.status == "match" and result.source_url.endswith("/statutes/4/title4.pdf")
    assert result.submitted_url == LANDING and result.source_mode == "reference"
    assert result.discovery.status == "found" and result.discovery.path[-1].label == "Title 4 PDF"
    assert any("TITLE 4: JUDICIARY > Title 4 PDF" in note for note in result.scope_notes)
    changed = service.validate_pdf(title_pdf("4", ("six associate justices", "seven associate justices")), "title4.pdf", LANDING, options=options)
    assert changed.status == "mismatch" and changed.source_url.endswith("title4.pdf")
    assert any("seven" in finding.actual for finding in changed.findings)


def test_reference_mode_reports_what_was_checked_when_nothing_matches(source):
    site(source, f"<ul>{TITLE_LIST}</ul>", titles=("1", "5", "14"))
    result = service.validate_pdf(title_pdf("4"), "title4.pdf", LANDING, options=service.PdfValidationOptions(source_mode="reference"))
    assert result.status == "unable" and result.comparison == "not_checked"
    assert result.discovery.status == "not_found" and "Opened" in result.summary
    assert result.source_coverage is None


def test_content_mode_on_a_landing_page_suggests_reference_mode(source):
    many = "".join(f'<li><a href="{n}/index.html">TITLE {n}: Subject {n}</a></li>' for n in range(1, 9))
    site(source, f"<main><h1>Revised statutes</h1><ul>{many}</ul></main>")
    result = service.validate_pdf(title_pdf("4"), "title4.pdf", LANDING)
    assert result.status != "match" and "Choose Reference URL" in result.summary
    assert result.discovery is None


def test_reference_mode_rejects_options_that_need_a_content_uri():
    with pytest.raises(ValueError):
        service.PdfValidationOptions(source_mode="reference", archive_member="a.pdf")


def test_reference_discovery_and_validation_endpoints(client, source):
    site(source, f"<ul>{TITLE_LIST}</ul>")
    files = {"document": ("title4.pdf", title_pdf("4"), "application/pdf")}
    found = client.post("/api/pdf-validations/reference-discovery", data={"content_uri": LANDING}, files=files)
    assert found.status_code == 200, found.text
    data = found.json()["data"]
    assert data["source_mode"] == "reference" and data["references"][0]["url"].endswith("title4.pdf")
    assert data["discovery"]["path"][1]["label"] == "TITLE 4: JUDICIARY"
    result = client.post("/api/pdf-validations", data={"content_uri": LANDING, "source_mode": "reference"}, files=files).json()["data"]
    assert result["status"] == "match" and result["discovery"]["selected_url"].endswith("title4.pdf")
    bad = client.post("/api/pdf-validations", data={"content_uri": LANDING, "source_mode": "anything"}, files=files)
    assert bad.status_code in {400, 422}
    client.app.dependency_overrides.pop(get_current_user)
    assert client.post("/api/pdf-validations/reference-discovery", data={"content_uri": LANDING}, files=files).status_code in {401, 403}


def test_uploaded_document_identity_is_read_from_its_first_page():
    hints = document_hints(title_pdf("4"))
    assert hints["primary"] == ("title", "4") and "judiciary" in hints["keywords"]
