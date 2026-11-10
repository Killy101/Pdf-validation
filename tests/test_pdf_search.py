"""Searching the text of an uploaded PDF."""
from app.auth import get_current_user
from app.services import pdf_validation_search as search

from test_pdf_validation import pdf, TEXT


PAGES = (TEXT, "Section 2 Fees\nThe annual fee is payable on 10.05.2025 to the Court.", "Section 3\nThe Court may waive the fee.\nFee waiver requests close in May.")


def find(client, query, data=None, name="synthetic.pdf"):
    return client.post("/api/pdf-validations/search-text", data={"query": query},
                       files={"document": (name, data or pdf(*PAGES), "application/pdf")})


def test_search_reports_each_page_with_a_highlighted_snippet(client):
    response = find(client, "fee")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["pages_searched"] == 3 and data["pages_matched"] == 2 and data["total_matches"] == 4
    assert [m["page"] for m in data["matches"]] == [2, 3]
    first = data["matches"][0]
    assert (first["before"], first["match"], first["after"][:1], first["count"]) == ("Section 2 ", "Fee", "s", 2)


def test_search_ignores_case_and_line_breaks(client):
    assert find(client, "THE COURT MAY WAIVE THE FEE.").json()["data"]["matches"][0]["page"] == 3
    assert find(client, "waive the fee. Fee waiver").json()["data"]["matches"][0]["page"] == 3


def test_search_without_a_match_is_not_an_error(client):
    data = find(client, "nonexistent wording").json()["data"]
    assert data["total_matches"] == 0 and data["matches"] == []


def test_search_rejects_short_queries_and_non_pdfs(client):
    assert find(client, "a").status_code == 400
    assert find(client, "word", data=b"not a pdf").status_code == 400
    assert find(client, "word", data=pdf(*PAGES, encrypted=True)).status_code == 400


def test_search_requires_authentication(client):
    client.app.dependency_overrides.pop(get_current_user)
    assert find(client, "fee").status_code in {401, 403}


def test_extracted_text_is_cached_per_file(client, monkeypatch):
    calls = []
    original = search._extract
    monkeypatch.setattr(search, "_extract", lambda data: calls.append(1) or original(data))
    data = pdf(*PAGES, title="Cache check")
    search._pages.clear()
    assert find(client, "fee", data).status_code == 200
    assert find(client, "court", data).status_code == 200
    assert len(calls) == 1
