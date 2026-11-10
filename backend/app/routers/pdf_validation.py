"""Authenticated endpoints for independent PDF source validation."""
from datetime import date
import hashlib
import logging
from pathlib import Path
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile

from app.api_responses import ApiRoute
from app.auth import User, get_current_user
from app.config import settings
from app.logging_setup import VALIDATION, clean, log_event, mark_logged, safe_url
from app.pdf_validation_models import PdfBatchRequest, PdfBatchResponse, PdfSourceDiscovery, PdfSourceRequest, PdfTextSearchResult, PdfValidationConfiguration, PdfValidationOptions, PdfValidationResult
from app.services.pdf_validation import discover_pdf_source, discover_reference_source, validate_pdf
from app.services.pdf_validation_search import search_pdf
from app.services import pdf_validation as validation_service
from app.services.pdf_validation_batch import BatchUnavailable, batch_fetch, close_batch, create_batch
from app.services.pdf_validation_downloads import SourceChanged, official_pdf, updated_pdf
from app.validation_log import log_result, logged_fetch


router = APIRouter(route_class=ApiRoute, prefix="/pdf-validations", tags=["PDF Validation"])


def _ms(started):
    return int((time.perf_counter() - started) * 1000)


def _name(filename):
    return clean(Path((filename or "").replace("\\", "/")).name, 120) or "unnamed"


def _rejected(event, status, exc, started, **context):
    """Record a refused or failed request before the route turns it into an HTTP error."""
    log_event(VALIDATION, logging.WARNING, event, status=status, reason=clean(exc.detail if isinstance(exc, HTTPException) else exc),
              elapsed_ms=_ms(started), **context)


def _crashed(event, exc, started, **context):
    log_event(VALIDATION, logging.ERROR, event, exc_info=exc, error=type(exc).__name__, elapsed_ms=_ms(started), **context)
    mark_logged(exc)


@router.get("/source-pdf")
def download_source_pdf(
    source_url: str = Query(min_length=1, max_length=2048),
    source_sha256: str = Query(pattern=r"^[0-9a-f]{64}$"),
    archive_member: str | None = Query(None, min_length=1, max_length=2048),
    archive_sha256: str | None = Query(None, pattern=r"^[0-9a-f]{64}$"),
    current_user: User = Depends(get_current_user),
):
    started, context = time.perf_counter(), {"source": safe_url(source_url), "archive_member": archive_member}
    log_event(VALIDATION, logging.INFO, "download.official.started", **context)
    try:
        data, filename = official_pdf(source_url, source_sha256, logged_fetch(validation_service, **context), archive_member, archive_sha256)
        log_event(VALIDATION, logging.INFO, "download.official.completed", **context, filename=filename, bytes=len(data), elapsed_ms=_ms(started))
        return Response(data, media_type="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    except SourceChanged as exc:
        _rejected("download.official.rejected", 409, exc, started, **context)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BlockingIOError as exc:
        _rejected("download.official.rejected", 503, exc, started, **context)
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "5"}) from exc
    except ValueError as exc:
        _rejected("download.official.rejected", 400, exc, started, **context)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _crashed("download.official.failed", exc, started, **context)
        raise


@router.post("/updated-pdf")
def download_updated_pdf(
    document: UploadFile = File(...),
    source_url: str = Form(min_length=1, max_length=2048),
    source_sha256: str = Form(pattern=r"^[0-9a-f]{64}$"),
    archive_member: str | None = Form(None, min_length=1, max_length=2048),
    archive_sha256: str | None = Form(None, pattern=r"^[0-9a-f]{64}$"),
    current_user: User = Depends(get_current_user),
):
    started = time.perf_counter()
    context = {"file": _name(document.filename), "source": safe_url(source_url), "archive_member": archive_member}
    log_event(VALIDATION, logging.INFO, "download.updated.started", **context)
    try:
        data = document.file.read(settings.PDF_VALIDATION_MAX_BYTES + 1)
        if len(data) > settings.PDF_VALIDATION_MAX_BYTES:
            raise HTTPException(status_code=413, detail="The uploaded PDF exceeds the configured size limit.")
        data, filename = updated_pdf(data, document.filename or "", source_url, source_sha256, logged_fetch(validation_service, **context), archive_member, archive_sha256)
        log_event(VALIDATION, logging.INFO, "download.updated.completed", **context, filename=filename, bytes=len(data), elapsed_ms=_ms(started))
        return Response(data, media_type="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    except HTTPException as exc:
        _rejected("download.updated.rejected", exc.status_code, exc, started, **context)
        raise
    except SourceChanged as exc:
        _rejected("download.updated.rejected", 409, exc, started, **context)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BlockingIOError as exc:
        _rejected("download.updated.rejected", 503, exc, started, **context)
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "5"}) from exc
    except ValueError as exc:
        _rejected("download.updated.rejected", 400, exc, started, **context)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _crashed("download.updated.failed", exc, started, **context)
        raise
    finally:
        document.file.close()


@router.post("/search-text", response_model=PdfTextSearchResult)
def search_document_text(
    document: UploadFile = File(...),
    query: str = Form(..., min_length=1, max_length=400),
    current_user: User = Depends(get_current_user),
):
    started, context = time.perf_counter(), {"file": _name(document.filename)}
    try:
        data = document.file.read(settings.PDF_VALIDATION_MAX_BYTES + 1)
        if len(data) > settings.PDF_VALIDATION_MAX_BYTES:
            raise HTTPException(status_code=413, detail="The uploaded PDF exceeds the configured size limit.")
        result = search_pdf(data, query)
        log_event(VALIDATION, logging.INFO, "search.completed", **context, query=clean(query.strip(), 120),
                  matches=result["total_matches"], pages_matched=result["pages_matched"],
                  first_pages=",".join(str(item["page"]) for item in result["matches"][:10]) or None, elapsed_ms=_ms(started))
        return result
    except HTTPException as exc:
        _rejected("search.rejected", exc.status_code, exc, started, **context)
        raise
    except BlockingIOError as exc:
        _rejected("search.rejected", 503, exc, started, **context)
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "5"}) from exc
    except ValueError as exc:
        _rejected("search.rejected", 400, exc, started, **context)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _crashed("search.failed", exc, started, **context)
        raise
    finally:
        document.file.close()


@router.get("/configuration", response_model=PdfValidationConfiguration)
def configuration(current_user: User = Depends(get_current_user)):
    return PdfValidationConfiguration(max_upload_bytes=settings.PDF_VALIDATION_MAX_BYTES,
                                      max_files=settings.PDF_VALIDATION_MAX_FILES,
                                      max_pages=settings.PDF_VALIDATION_MAX_PAGES,
                                      timeout_seconds=settings.PDF_VALIDATION_TIMEOUT_SECONDS,
                                      max_versions=settings.PDF_VALIDATION_MAX_VERSIONS)


@router.post("", response_model=PdfValidationResult)
def validate_document(
    document: UploadFile = File(...),
    content_uri: str = Form(..., min_length=1, max_length=2048),
    reference_url: str | None = Form(None, max_length=2048),
    archive_member: str | None = Form(None, min_length=1, max_length=2048),
    jurisdiction: str = Form("auto", max_length=20),
    workflow: str = Form("current", max_length=20),
    date_start: date | None = Form(None),
    date_end: date | None = Form(None),
    history_url: str | None = Form(None, max_length=2048),
    batch_id: str | None = Form(None, max_length=32),
    source_mode: str = Form("content", max_length=20),
    current_user: User = Depends(get_current_user),
):
    started = time.perf_counter()
    context = {"file": _name(document.filename), "batch": batch_id}
    try:
        data = document.file.read(settings.PDF_VALIDATION_MAX_BYTES + 1)
        if len(data) > settings.PDF_VALIDATION_MAX_BYTES:
            raise HTTPException(status_code=413, detail="The uploaded PDF exceeds the configured size limit.")
        log_event(VALIDATION, logging.INFO, "validation.started", **context, size_bytes=len(data),
                  upload_sha256=hashlib.sha256(data).hexdigest()[:16], source_mode=source_mode,
                  source=safe_url(content_uri), reference=safe_url(reference_url) if reference_url else None,
                  archive_member=archive_member, workflow=workflow, jurisdiction=jurisdiction,
                  date_start=date_start, date_end=date_end)
        options = PdfValidationOptions(jurisdiction=jurisdiction, workflow=workflow, source_mode=source_mode,
            date_start=date_start, date_end=date_end, history_url=history_url, archive_member=archive_member)
        fetch = logged_fetch(validation_service, **context)
        if batch_id:
            with batch_fetch(batch_id, current_user.id, content_uri, reference_url, options, fetch) as cached:
                result = validate_pdf(data, document.filename or "", content_uri, reference_url, options, fetch=cached)
        else:
            result = validate_pdf(data, document.filename or "", content_uri, reference_url, options, fetch=fetch)
        log_result(result, _ms(started), **context)
        return result
    except HTTPException as exc:
        _rejected("validation.rejected", exc.status_code, exc, started, **context)
        raise
    except BatchUnavailable as exc:
        _rejected("validation.rejected", 409, exc, started, **context)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BlockingIOError as exc:
        _rejected("validation.rejected", 503, exc, started, **context)
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "5"}) from exc
    except ValueError as exc:
        _rejected("validation.rejected", 400, exc, started, **context)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _crashed("validation.failed", exc, started, **context)
        raise
    finally:
        document.file.close()


@router.post("/batches", response_model=PdfBatchResponse)
def start_batch(payload: PdfBatchRequest, current_user: User = Depends(get_current_user)):
    started, context = time.perf_counter(), {"source": safe_url(payload.content_uri), "workflow": payload.workflow}
    try:
        batch = create_batch(current_user.id, payload.content_uri, payload.reference_url, payload)
        log_event(VALIDATION, logging.INFO, "validation.batch.created", batch=batch.get("batch_id") if isinstance(batch, dict) else getattr(batch, "batch_id", None),
                  reference=safe_url(payload.reference_url) if payload.reference_url else None,
                  date_start=payload.date_start, date_end=payload.date_end, **context)
        return batch
    except BlockingIOError as exc:
        _rejected("validation.batch.rejected", 503, exc, started, **context)
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "5"}) from exc
    except ValueError as exc:
        _rejected("validation.batch.rejected", 400, exc, started, **context)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _crashed("validation.batch.failed", exc, started, **context)
        raise


@router.delete("/batches/{batch_id}", status_code=204)
def release_batch(batch_id: str, current_user: User = Depends(get_current_user)):
    started = time.perf_counter()
    try:
        close_batch(batch_id, current_user.id)
        log_event(VALIDATION, logging.INFO, "validation.batch.released", batch=batch_id)
    except ValueError as exc:
        _rejected("validation.batch.release_rejected", 400, exc, started, batch=batch_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sources", response_model=PdfSourceDiscovery)
def discover_source(payload: PdfSourceRequest, current_user: User = Depends(get_current_user)):
    started, context = time.perf_counter(), {"source": safe_url(payload.content_uri), "workflow": payload.workflow}
    log_event(VALIDATION, logging.INFO, "discovery.started", **context, date_start=payload.date_start, date_end=payload.date_end)
    try:
        discovery = discover_pdf_source(payload.content_uri, payload, logged_fetch(validation_service, **context))
        log_event(VALIDATION, logging.INFO, "discovery.completed", **context, source_type=discovery.source_type,
                  references=len(discovery.references), versions=len(discovery.versions),
                  history_complete=discovery.history_complete if payload.workflow == "date_range" else None,
                  elapsed_ms=_ms(started), summary=clean(discovery.summary))
        return discovery
    except Exception as exc:
        _discovery_failed(exc, started, context)


def _discovery_failed(exc: Exception, started: float, context: dict):
    """Log a failed source discovery and raise the matching HTTP error."""
    if isinstance(exc, HTTPException):
        _rejected("discovery.rejected", exc.status_code, exc, started, **context)
        raise exc
    if isinstance(exc, BlockingIOError):
        _rejected("discovery.rejected", 503, exc, started, **context)
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "5"}) from exc
    if isinstance(exc, ValueError):
        _rejected("discovery.rejected", 400, exc, started, **context)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _crashed("discovery.failed", exc, started, **context)
    raise exc


@router.post("/reference-discovery", response_model=PdfSourceDiscovery)
def discover_reference_document(
    document: UploadFile = File(...),
    content_uri: str = Form(..., min_length=1, max_length=2048),
    jurisdiction: str = Form("auto", max_length=20),
    current_user: User = Depends(get_current_user),
):
    started = time.perf_counter()
    context = {"file": _name(document.filename), "source": safe_url(content_uri), "source_mode": "reference"}
    log_event(VALIDATION, logging.INFO, "discovery.started", **context)
    try:
        data = document.file.read(settings.PDF_VALIDATION_MAX_BYTES + 1)
        if len(data) > settings.PDF_VALIDATION_MAX_BYTES:
            raise HTTPException(status_code=413, detail="The uploaded PDF exceeds the configured size limit.")
        options = PdfValidationOptions(jurisdiction=jurisdiction, source_mode="reference")
        discovery = discover_reference_source(data, document.filename or "", content_uri, options,
                                              logged_fetch(validation_service, **context))
        log_event(VALIDATION, logging.INFO, "discovery.completed", **context, source_type=discovery.source_type,
                  references=len(discovery.references), status=discovery.discovery.status if discovery.discovery else None,
                  elapsed_ms=_ms(started), summary=clean(discovery.summary))
        return discovery
    except Exception as exc:
        _discovery_failed(exc, started, context)
    finally:
        document.file.close()
