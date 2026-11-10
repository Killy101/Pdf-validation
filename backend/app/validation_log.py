"""Validation activity logging: source retrieval, comparison outcomes and mismatch reasons."""
from collections import Counter
import logging
import time

from app.logging_setup import clean, log_event, safe_url

FETCH = logging.getLogger("pdfv.validation.fetch")
RESULT = logging.getLogger("pdfv.validation.result")
MAX_FINDINGS_LOGGED = 20


def logged_fetch(service, **context):
    """Wrap the source fetch used by the hub services so every retrieval is recorded.

    The service module is looked up at call time, so the real fetch (or a test double) is always used.
    """
    def fetch(url, *args, **kwargs):
        started = time.perf_counter()
        log_event(FETCH, logging.INFO, "source.fetch.started", url=safe_url(url), **context)
        try:
            snapshot = service.fetch_source(url, *args, **kwargs)
        except Exception as exc:
            log_event(FETCH, logging.WARNING, "source.fetch.failed", url=safe_url(url), error=type(exc).__name__,
                      http_status=getattr(exc, "code", None), reason=clean(exc),
                      elapsed_ms=int((time.perf_counter() - started) * 1000), **context)
            raise
        log_event(FETCH, logging.INFO, "source.fetch.completed", url=safe_url(snapshot.url), kind=snapshot.kind,
                  bytes=len(snapshot.data), attempts=snapshot.retrieval_attempts,
                  elapsed_ms=int((time.perf_counter() - started) * 1000), **context)
        return snapshot
    return fetch


def _log_one(result, context):
    findings = result.findings or []
    kinds = dict(Counter(item.kind for item in findings))
    level = logging.INFO if result.status in {"match", "mismatch"} else logging.WARNING
    log_event(RESULT, level, f"validation.result.{result.status}", **context, comparison=result.comparison,
              source=safe_url(result.source_url), source_type=result.source_type,
              identity=result.document_identity, pdf_pages=result.pdf_pages, source_pages=result.source_pages,
              coverage_complete=result.coverage_complete, findings=len(findings), finding_kinds=",".join(sorted(kinds)) or None,
              access_issue=result.source_access_issue, attempts=result.retrieval_attempts,
              upload_sha256=result.upload_sha256[:16], source_sha256=(result.source_sha256 or "")[:16] or None,
              source_mode=result.source_mode, submitted=safe_url(result.submitted_url),
              discovery=result.discovery.status if result.discovery else None,
              discovery_path=" > ".join(clean(step.label, 60) for step in result.discovery.path[1:]) or None if result.discovery else None,
              reason=clean(result.summary))
    context = {key: value for key, value in context.items() if key != "elapsed_ms"}
    if result.discovery:
        for item in result.discovery.items:
            if item.status in {"unavailable", "inaccessible", "rejected", "needs_verification"} and item.kind == "pdf":
                log_event(RESULT, logging.INFO, "validation.discovery_item", **context, status=item.status,
                          url=safe_url(item.url), label=clean(item.label, 120), reason=clean(item.reason or ""))
    for item in findings[:MAX_FINDINGS_LOGGED]:
        log_event(RESULT, logging.INFO, "validation.finding", **context, kind=item.kind, severity=item.severity,
                  pdf_page=item.pdf_page, source_page=item.source_page, heading=clean(item.source_heading or "", 120) or None,
                  reason=clean(item.message))
    if len(findings) > MAX_FINDINGS_LOGGED:
        log_event(RESULT, logging.INFO, "validation.findings_omitted", **context, omitted=len(findings) - MAX_FINDINGS_LOGGED)
    for note in result.limitations[:5]:
        log_event(RESULT, logging.DEBUG, "validation.limitation", **context, note=clean(note))


def log_result(result, elapsed_ms: int, **context):
    """Record the outcome (and, for date ranges, each version) of one PDF validation."""
    try:
        _log_one(result, {**context, "elapsed_ms": elapsed_ms})
        for version in result.versions or []:
            _log_one(version.result, {**context, "version": clean(version.reference.label, 80),
                                      "valid_from": str(version.reference.valid_from)})
    except Exception as exc:
        log_event(RESULT, logging.ERROR, "validation.result_log_failed", exc_info=exc, **context)
