"""Historical date boundaries and publisher workflows using isolated sources."""
from datetime import date, timedelta
import json

import pytest

from test_pdf_validation import pdf, TEXT, URL
from app.config import settings
from app.pdf_validation_models import PdfValidationOptions
from app.services import pdf_validation as service
from app.services.pdf_validation_source import SourceSnapshot
from app.services.pdf_validation_jurisdictions import resolve_jurisdiction


def html(url, text):
    return SourceSnapshot(text.encode(), url, "html", "text/html; charset=utf-8")


@pytest.mark.parametrize("url,expected", [
    ("https://www.legislation.gov.au/F2020L00001", "au"),
    ("https://laws-lois.justice.gc.ca/eng/acts/A-1/", "ca"),
    ("https://www.law.go.kr/행정규칙/규정", "kr"),
    ("https://www.legislation.gov.uk/ukpga/2020/1", "uk"),
    ("https://legislation.govt.nz/act/", "nz"),
    ("https://ecfr.gov/current/", "us"),
    ("https://eur-lex.europa.eu/legal-content/", "eu"),
    ("https://publisher.example/regulation.pdf", "other"),
    ("https://law.go.kr.untrusted.example/regulation", "other"),
])
def test_jurisdiction_detection_uses_host_boundaries(url, expected):
    assert resolve_jurisdiction(url) == expected


def australian_history(source, count=2):
    url = "https://www.legislation.gov.au/F2020L00001/latest/text"
    series = "https://www.legislation.gov.au/Series/F2020L00001"
    records = [
        {"titleId": "F2020L00001", "registerId": "Old edition", "start": "2025-08-01T00:00:00", "end": "2025-09-15T00:00:00"},
        {"titleId": "F2020L00001", "registerId": "New edition", "start": "2025-09-15T00:00:00", "end": None},
    ]
    source[0][series] = html(series, '<script id="ng-state" type="application/json">' + json.dumps({"versions": {"@odata.count": count, "value": records}}) + '</script>')
    for record in records:
        reference = f"https://www.legislation.gov.au/F2020L00001/{record['start'][:10]}/text"
        content = pdf(TEXT if record["registerId"] == "Old edition" else TEXT.replace("all regulated", "some regulated"))
        source[0][reference] = SourceSnapshot(content, reference, "pdf")
    return url


def range_options(start="2025-09-01", end="2025-09-30", **kwargs):
    return PdfValidationOptions(workflow="date_range", date_start=start, date_end=end, **kwargs)


def test_date_range_includes_version_starting_before_the_range_and_each_change(source):
    url = australian_history(source)
    result = service.validate_pdf(pdf(TEXT), "synthetic.pdf", url, options=range_options())
    assert len(result.versions) == 2 and result.history_complete
    assert result.versions[0].reference.valid_from == date(2025, 8, 1)
    assert result.versions[0].reference.valid_to == date(2025, 9, 14)
    assert [item.result.status for item in result.versions] == ["match", "mismatch"]
    assert result.status == "mismatch" and result.coverage_complete
    assert result.workflow == "date_range" and result.jurisdiction == "au"


@pytest.mark.parametrize("start,end,label", [
    ("2025-09-14", "2025-09-14", "Old edition"),
    ("2025-09-15", "2025-09-15", "New edition"),
])
def test_same_day_range_and_exclusive_publisher_end_dates(source, start, end, label):
    history = service.discover_pdf_source(australian_history(source), range_options(start, end))
    assert len(history.versions) == 1 and history.versions[0].label == label
    assert history.history_complete


def test_incomplete_publisher_list_cannot_produce_a_whole_range_match(source):
    url = australian_history(source, count=3)
    result = service.validate_pdf(pdf(TEXT), "synthetic.pdf", url, options=range_options(end="2025-09-14"))
    assert result.versions[0].result.status == "match"
    assert result.status == "needs_review" and not result.history_complete and not result.coverage_complete


def test_australian_as_made_edition_covers_dates_before_the_first_compilation(source):
    url = australian_history(source)
    series = "https://www.legislation.gov.au/Series/F2020L00001"
    state = json.loads(source[0][series].data.decode().split('>', 1)[1].split('</script>', 1)[0])
    state["original"] = {"titleId": "F2020L00001", "registerId": "Original edition", "compilationNumber": "0",
        "start": "2025-05-01T00:00:00", "end": "2025-08-01T00:00:00"}
    source[0][series] = html(series, '<script id="ng-state">' + json.dumps(state) + '</script>')
    history = service.discover_pdf_source(url, range_options("2025-06-01", "2025-06-30"))
    assert len(history.versions) == 1 and history.history_complete
    assert history.versions[0].url.endswith("/asmade/text")
    assert history.versions[0].valid_to == date(2025, 7, 31)


def test_canadian_intervals_are_not_extended_beyond_the_stated_current_date(source):
    url = "https://laws-lois.justice.gc.ca/eng/acts/A-1/index.html"
    history_url = "https://laws-lois.justice.gc.ca/eng/acts/A-1/PITIndex.html"
    source[0][history_url] = html(history_url, '<a href="20250614/P1TT3xt3.html">From 2025-06-14 to 2025-09-21</a>')
    history = service.discover_pdf_source(url, range_options())
    assert len(history.versions) == 1 and not history.history_complete
    assert history.versions[0].valid_to == date(2025, 9, 21)
    assert history.versions[0].url.endswith("/20250614/P1TT3xt3.html")


def korean_sources(source):
    url = "https://www.law.go.kr/행정규칙/규정"
    viewer = "https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2"
    source[0][url] = html(url, f'<iframe id="lawService" src="{viewer}"></iframe>')
    source[0][viewer] = html(viewer, '<input id="admRulSeq" value="2"><div id="bodyContent"></div>')
    for sequence, text in [(1, TEXT), (2, TEXT.replace("all regulated", "some regulated"))]:
        viewer_url = f"https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq={sequence}&chrClsCd=010201"
        body_url = f"https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq={sequence}&chrClsCd=010201"
        source[0][viewer_url] = html(viewer_url, f'<input id="admRulSeq" value="{sequence}">')
        parts = text.splitlines()
        source[0][body_url] = html(body_url, f'<input id="admRulSeq" value="{sequence}"><div id="contentBody"><h1>{parts[0]}</h1><p>{parts[1]}</p><p>{parts[2]}</p></div>')
    history_url = "https://www.law.go.kr/LSW/admRulHstListR.do?admRulSeq=2"
    source[0][history_url] = html(history_url, '''<a onclick="admRulViewHst('Y','2')">[시행 2025. 10. 2.] [2025. 9. 29.]</a>
        <a onclick="admRulViewHst('Y','1')">[시행 2025. 4. 2.] [2025. 4. 2.]</a>''')
    return url


def test_korean_viewer_reads_document_body_instead_of_controls(source):
    result = service.validate_pdf(pdf(TEXT.replace("all regulated", "some regulated")), "synthetic.pdf", korean_sources(source))
    assert result.status == "match" and result.jurisdiction == "kr"
    assert result.source_url.endswith("admRulLsInfoR.do?admRulSeq=2&chrClsCd=010201")


def test_korean_range_uses_effective_date_and_excludes_october_changes(source):
    result = service.validate_pdf(pdf(TEXT), "synthetic.pdf", korean_sources(source), options=range_options())
    assert len(result.versions) == 1 and result.versions[0].result.status == "match"
    assert result.status == "match" and result.history_complete
    assert result.versions[0].reference.valid_from == date(2025, 4, 2)
    assert result.versions[0].reference.valid_to == date(2025, 10, 1)


def test_korean_history_discovery_does_not_download_the_document_body(source):
    history = service.discover_pdf_source(korean_sources(source), range_options())
    assert len(history.versions) == 1
    assert not any("admRulLsInfoR.do" in url for url in source[1])


def test_hidden_korean_annexes_require_review(source):
    url = korean_sources(source)
    body_url = "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2&chrClsCd=010201"
    source[0][body_url].data += b'<a onclick="bylInfoDiv(1)">Annex</a>'
    result = service.validate_pdf(pdf(TEXT), "synthetic.pdf", url)
    assert result.status == "needs_review" and not result.coverage_complete


def test_unavailable_history_does_not_compare_against_the_current_pdf(source):
    source[0][URL] = SourceSnapshot(pdf(TEXT), URL, "pdf")
    result = service.validate_pdf(pdf(TEXT), "synthetic.pdf", URL, options=range_options())
    assert result.status == "needs_review" and result.comparison == "not_checked"
    assert not result.versions and not result.history_complete


def test_custom_history_uses_explicit_periods_and_reports_uncertified_coverage(source):
    history_url = "https://publisher.example/versions"
    source[0][history_url] = html(history_url, f'<a href="{URL}" data-valid-from="2025-01-01" data-valid-to="2025-12-31">Edition one</a>')
    source[0][URL] = SourceSnapshot(pdf(TEXT), URL, "pdf")
    result = service.validate_pdf(pdf(TEXT), "synthetic.pdf", URL, options=range_options(jurisdiction="sg", history_url=history_url))
    assert result.versions[0].result.status == "match" and result.jurisdiction == "sg"
    assert result.status == "needs_review" and not result.history_complete


def test_history_and_version_links_keep_source_host_restrictions(source):
    options = range_options(history_url="https://unapproved.example/versions")
    with pytest.raises(ValueError, match="approved source host"):
        service.discover_pdf_source(URL, options)
    history_url = "https://publisher.example/versions"
    source[0][history_url] = html(history_url, '<a href="https://unapproved.example/edition.pdf" data-valid-from="2025-01-01" data-valid-to="2025-12-31">Edition</a>')
    result = service.validate_pdf(pdf(TEXT), "synthetic.pdf", URL, options=range_options(history_url=history_url))
    assert result.status == "unable" and not result.versions[0].reference.available
    assert not result.coverage_complete and source[1] == [history_url]


def test_invalid_history_links_are_not_exposed_as_clickable_references(source):
    history_url = "https://publisher.example/versions"
    source[0][history_url] = html(history_url, '<a href="javascript:alert(1)" data-valid-from="2025-01-01" data-valid-to="2025-12-31">Edition</a>')
    result = service.validate_pdf(pdf(TEXT), "synthetic.pdf", URL, options=range_options(history_url=history_url))
    assert result.status == "unable" and "valid HTTP or HTTPS" in result.summary
    assert not result.versions


def test_range_version_limit_and_jurisdiction_mismatch_are_clear(source, monkeypatch):
    url = australian_history(source)
    monkeypatch.setattr(settings, "PDF_VALIDATION_MAX_VERSIONS", 1)
    with pytest.raises(ValueError, match="shorter date range"):
        service.discover_pdf_source(url, range_options())
    with pytest.raises(ValueError, match="jurisdiction does not match"):
        service.discover_pdf_source(url, PdfValidationOptions(jurisdiction="kr"))


@pytest.mark.parametrize("fields", [
    {"workflow": "date_range"},
    {"workflow": "date_range", "date_start": "2025-09-30", "date_end": "2025-09-01"},
    {"workflow": "date_range", "date_start": "2025-02-30", "date_end": "2025-09-01"},
    {"workflow": "date_range", "date_start": "2025-09-01", "date_end": (date.today() + timedelta(days=1)).isoformat()},
    {"jurisdiction": "invalid"},
])
def test_api_rejects_invalid_scope_before_network_access(client, source, fields):
    response = client.post("/api/pdf-validations", files={"document": ("synthetic.pdf", pdf(TEXT), "application/pdf")},
        data={"content_uri": URL, **fields})
    assert response.status_code in {400, 422} and not source[1]


def test_range_api_preserves_nested_reports_and_discovery_metadata(client, source):
    url = australian_history(source)
    fields = {"jurisdiction": "au", "workflow": "date_range", "date_start": "2025-09-01", "date_end": "2025-09-30"}
    discovery = client.post("/api/pdf-validations/sources", json={"content_uri": url, **fields}).json()["data"]
    assert len(discovery["versions"]) == 2 and discovery["history_complete"]
    response = client.post("/api/pdf-validations", files={"document": ("synthetic.pdf", pdf(TEXT), "application/pdf")}, data={"content_uri": url, **fields})
    result = response.json()["data"]
    assert response.status_code == 200 and len(result["versions"]) == 2
    assert result["date_start"] == "2025-09-01" and result["date_end"] == "2025-09-30"
    assert result["versions"][1]["result"]["findings"]
