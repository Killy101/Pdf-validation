"""Document identity and immutable batch references using synthetic public sources."""
import json
import time
from types import SimpleNamespace

import pytest

from test_pdf_validation import pdf, TEXT, URL
from test_pdf_validation_history import australian_history, range_options
from app.auth import get_current_user
from app.config import settings
from app.pdf_validation_models import PdfValidationOptions
from app.services import pdf_validation as service
from app.services.pdf_validation_access import SourceAccessError
from app.services.pdf_validation_batch import batch_fetch, close_batch, create_batch
from app.services.pdf_validation_source import SourceSnapshot
from app.services.pdf_validation_worker import compare_documents, extract_pdf


EMPLOYMENT = "Employment Rights Act\nWorkers must receive annual leave benefits. Employers provide written contracts describing working hours and overtime compensation. Workplace inspectors investigate violations and enforce occupational safety protections."
WILDLIFE = "Wildlife Conservation Rules\nProtected habitats include forests wetlands and grasslands. Rangers monitor endangered species migration patterns. Hunting permits require ecological surveys detailing breeding populations and restoration strategies."


def start(options=None):
    return create_batch(1, URL, None, options or PdfValidationOptions())["batch_id"]


def retrieve(batch_id, fetch, options=None, owner=1, url=URL, reference=None):
    return batch_fetch(batch_id, owner, url, reference, options or PdfValidationOptions(), fetch)


def test_unrelated_pdf_is_reported_even_when_metadata_claims_the_source_title(source):
    source[0][URL] = SourceSnapshot(pdf(EMPLOYMENT, title="Employment Rights Act"), URL, "pdf")
    result = service.validate_pdf(pdf(WILDLIFE, title="Employment Rights Act"), "synthetic.pdf", URL)
    assert result.status == "mismatch" and result.document_identity == "mismatch"
    assert result.findings[0].kind == "document_mismatch"
    assert result.findings[0].actual == "Wildlife Conservation Rules"
    assert result.findings[0].expected == "Employment Rights Act"
    assert "correct PDF" in result.findings[0].action


def test_unrelated_html_is_reported_with_a_document_identity_finding(source):
    url = "https://publisher.example/employment"
    title, body = EMPLOYMENT.split("\n")
    source[0][url] = SourceSnapshot(f"<main><h1>{title}</h1><p>{body}</p></main>".encode(), url, "html")
    result = service.validate_pdf(pdf(WILDLIFE), "synthetic.pdf", url)
    assert result.document_identity == "mismatch" and result.status == "mismatch"
    assert result.findings[0].source_url == url


def test_different_editions_remain_content_differences_for_the_same_document(source):
    source[0][URL] = SourceSnapshot(pdf(EMPLOYMENT.replace("Act", "Act 2026")), URL, "pdf")
    result = service.validate_pdf(pdf(EMPLOYMENT.replace("Act", "Act 2025").replace("annual", "monthly")), "synthetic.pdf", URL)
    assert result.document_identity == "match" and result.status == "mismatch"
    assert all(item.kind != "document_mismatch" for item in result.findings)


def test_missing_titles_and_incomplete_extraction_do_not_claim_unrelated_documents():
    upload = extract_pdf(pdf(WILDLIFE, ""), 100, 10000)
    reference = extract_pdf(pdf(EMPLOYMENT), 100, 10000)
    result = compare_documents(upload, reference, URL)
    assert result["document_identity"] == "needs_review" and result["status"] == "needs_review"
    upload = {"units": [{"text": ""}], "complete": False}
    result = compare_documents(upload, reference, URL)
    assert result["document_identity"] == "needs_review"


def test_non_latin_visible_titles_identify_edition_changes():
    title = "\uae08\uc735\uc18c\ube44\uc790 \ubcf4\ud638\uc5d0 \uad00\ud55c \uac10\ub3c5\uaddc\uc815"
    def document(year):
        return {"units": [{"text": f"{title} {year}\n\uc81c1\uc870 \uc801\uc6a9 \ubc94\uc704 \uae30\uc900 \uc870\ud56d", "page": 1}], "title": title + " " + year, "complete": True}
    result = compare_documents(document("2025"), document("2026"), URL)
    assert result["document_identity"] == "match" and result["status"] == "mismatch"


def test_batch_keeps_first_source_when_publisher_changes_between_files(batch_store, source):
    first = pdf(TEXT)
    source[0][URL] = SourceSnapshot(first, URL, "pdf")
    batch_id = start()
    with retrieve(batch_id, service.fetch_source) as fetch:
        report = service.validate_pdf(first, "first.pdf", URL, fetch=fetch)
    source[0][URL] = SourceSnapshot(pdf(TEXT.replace("all regulated", "some regulated")), URL, "pdf")
    with retrieve(batch_id, service.fetch_source) as fetch:
        second = service.validate_pdf(first, "second.pdf", URL, fetch=fetch)
    assert report.status == second.status == "match"
    assert report.source_sha256 == second.source_sha256
    assert report.source_retrieved_at == second.source_retrieved_at
    assert source[1] == [URL]
    close_batch(batch_id, 1)
    assert not (batch_store / ("batch-" + batch_id)).exists()


def test_historical_batch_reuses_history_and_each_edition(batch_store, source):
    url, options = australian_history(source), range_options()
    batch_id = create_batch(1, url, None, options)["batch_id"]
    with retrieve(batch_id, service.fetch_source, options, url=url) as fetch:
        first = service.validate_pdf(pdf(TEXT), "first.pdf", url, options=options, fetch=fetch)
    calls = list(source[1])
    for target in source[0]:
        source[0][target] = SourceSnapshot(b"changed publisher response", target, "unknown")
    with retrieve(batch_id, service.fetch_source, options, url=url) as fetch:
        second = service.validate_pdf(pdf(TEXT), "second.pdf", url, options=options, fetch=fetch)
    assert source[1] == calls and len(calls) == 3
    assert [item.result.source_sha256 for item in first.versions] == [item.result.source_sha256 for item in second.versions]
    assert [item.result.status for item in second.versions] == ["match", "mismatch"]


@pytest.mark.parametrize("change", ["owner", "url", "reference", "dates", "hosts"])
def test_batch_cannot_be_reused_for_another_user_or_scope(batch_store, monkeypatch, change):
    batch_id, calls = start(), []
    kwargs = {"owner": 2} if change == "owner" else {"url": URL + "?different=1"} if change == "url" else (
        {"reference": "https://publisher.example/other.pdf"} if change == "reference" else {"options": range_options()} if change == "dates" else {})
    if change == "hosts":
        monkeypatch.setattr(settings, "PDF_VALIDATION_ALLOWED_HOSTS", ["another.example"])
    with pytest.raises(ValueError):
        with retrieve(batch_id, lambda *args: calls.append(args), **kwargs):
            pass
    assert not calls


def test_expired_batch_is_rejected_without_fetching_and_pruned_on_creation(batch_store):
    batch_id = start()
    path = batch_store / ("batch-" + batch_id)
    metadata = json.loads((path / "batch.json").read_text())
    metadata["expires"] = time.time() - 1
    (path / "batch.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="expired"):
        with retrieve(batch_id, lambda *args: pytest.fail("Expired batch must not retrieve a new source")):
            pass
    start()
    assert not path.exists()


def test_concurrent_batch_reuse_is_blocked_and_active_cancellation_waits_for_cleanup(batch_store):
    batch_id = start()
    path = batch_store / ("batch-" + batch_id)
    with retrieve(batch_id, lambda *args: SourceSnapshot(b"%PDF-synthetic", URL, "pdf")) as fetch:
        with pytest.raises(BlockingIOError):
            with retrieve(batch_id, fetch):
                pass
        close_batch(batch_id, 1)
        assert path.exists() and (path / "closing").exists()
        with pytest.raises(ValueError):
            with retrieve(batch_id, fetch):
                pass
        assert path.exists()
    assert not path.exists()


def test_batch_source_storage_is_bounded_and_corrupt_snapshots_are_not_replaced(batch_store, monkeypatch):
    batch_id = start()
    calls = []
    def fetch(*args):
        calls.append(args)
        return SourceSnapshot(b"%PDF-synthetic", URL, "pdf")
    with retrieve(batch_id, fetch) as cached:
        cached(URL, ("publisher.example",), 100, 1)
    path = batch_store / ("batch-" + batch_id)
    next(path.glob("*.bin")).write_bytes(b"damaged reference")
    with retrieve(batch_id, fetch) as cached:
        with pytest.raises(SourceAccessError, match="snapshot"):
            cached(URL, ("publisher.example",), 100, 1)
    assert len(calls) == 1
    next(item for item in path.glob("*.json") if item.name != "batch.json").unlink()
    with retrieve(batch_id, fetch) as cached:
        with pytest.raises(SourceAccessError, match="snapshot"):
            cached(URL, ("publisher.example",), 100, 1)
    assert len(calls) == 1
    batch_id = start()
    monkeypatch.setattr(settings, "PDF_VALIDATION_BATCH_MAX_BYTES", 4)
    with retrieve(batch_id, fetch) as cached:
        with pytest.raises(SourceAccessError, match="snapshot limit"):
            cached(URL, ("publisher.example",), 100, 1)


def test_batch_capacity_and_invalid_identifiers_cannot_escape_cache_directory(batch_store, monkeypatch, tmp_path):
    outside = tmp_path / "keep.txt"
    outside.write_text("Synthetic unrelated file")
    monkeypatch.setattr(settings, "PDF_VALIDATION_MAX_BATCHES", 1)
    batch_id = start()
    with pytest.raises(BlockingIOError):
        start()
    for invalid in ["../keep.txt", "", "x" * 32]:
        with pytest.raises(ValueError):
            close_batch(invalid, 1)
    with pytest.raises(ValueError):
        close_batch(batch_id, 2)
    assert outside.read_text() == "Synthetic unrelated file"
    close_batch(batch_id, 1)
    assert start()


def test_api_batch_scope_and_owner_are_enforced_and_sources_are_reused(client, source, batch_store):
    source[0][URL] = SourceSnapshot(pdf(TEXT), URL, "pdf")
    created = client.post("/api/pdf-validations/batches", json={"content_uri": URL})
    assert created.status_code == 200
    batch_id = created.json()["data"]["batch_id"]
    for filename in ["first.pdf", "second.pdf"]:
        response = client.post("/api/pdf-validations", data={"content_uri": URL, "batch_id": batch_id},
            files={"document": (filename, pdf(TEXT), "application/pdf")})
        assert response.status_code == 200 and response.json()["data"]["document_identity"] == "match"
    assert source[1] == [URL]
    changed = client.post("/api/pdf-validations", data={"content_uri": URL + "?different=1", "batch_id": batch_id},
        files={"document": ("changed.pdf", pdf(TEXT), "application/pdf")})
    assert changed.status_code == 409 and source[1] == [URL]
    client.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=2, role="user")
    assert client.delete("/api/pdf-validations/batches/" + batch_id).status_code == 400
    client.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="user")
    assert client.delete("/api/pdf-validations/batches/" + batch_id).status_code == 204
