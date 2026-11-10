"""Sequential historical comparisons with an explicit range summary."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from urllib.error import HTTPError, URLError

from app.pdf_validation_models import PdfValidationOptions, PdfValidationResult, PdfVersionComparison
from app.services.pdf_validation_access import SourceAccessError, http_access_error


def validate_range(upload, filename, url, options, discover, validate):
    result = PdfValidationResult(status="unable", summary="Historical versions could not be retrieved.",
        filename=Path(filename.replace("\\", "/")).name[:255], submitted_url=url, source_url=url,
        checked_at=datetime.now(timezone.utc).isoformat(), upload_sha256=hashlib.sha256(upload).hexdigest(),
        jurisdiction=options.jurisdiction, workflow="date_range", date_start=options.date_start, date_end=options.date_end)
    try:
        history = discover(url, options)
        result.jurisdiction = history.jurisdiction
        result.source_url, result.source_type = history.source_url, history.source_type
        result.history_complete, result.limitations = history.history_complete, list(history.limitations)
        if not history.versions:
            result.status, result.summary = "needs_review", history.summary
            return result
        for reference in history.versions:
            if reference.available:
                report = validate(upload, filename, reference.url, options=PdfValidationOptions(jurisdiction=history.jurisdiction))
            else:
                report = result.model_copy(update={"source_url": reference.url,
                    "summary": "This historical reference host is not approved for retrieval.", "versions": []})
            result.versions.append(PdfVersionComparison(reference=reference, result=report))
        reports = [item.result for item in result.versions]
        matches = sum(item.status == "match" for item in reports)
        mismatches = sum(item.status == "mismatch" for item in reports)
        reviewed = sum(item.comparison != "not_checked" for item in reports)
        result.coverage_complete = result.history_complete and all(item.coverage_complete for item in reports)
        result.pdf_pages, result.pdf_title = reports[0].pdf_pages, reports[0].pdf_title
        result.checked_pdf_pages = max(item.checked_pdf_pages for item in reports)
        result.comparison = "content" if reviewed else "not_checked"
        result.source_access_issue = next((item.source_access_issue for item in reports if item.source_access_issue), None)
        identities = {item.document_identity for item in reports}
        result.document_identity = next(iter(identities)) if len(identities) == 1 else "needs_review"
        result.identity_summary = reports[0].identity_summary if len(identities) == 1 else "Review document identity for each historical version."
        result.status = ("mismatch" if mismatches else "match" if matches == len(reports) and result.coverage_complete
                         else "unable" if all(item.status == "unable" for item in reports) else "needs_review")
        result.summary = f"Compared {reviewed} of {len(reports)} historical versions: {matches} match, {mismatches} differ, {len(reports) - matches - mismatches} need review or are unavailable."
        if not result.coverage_complete:
            result.limitations.append("A complete match across the selected date range has not been established.")
        return result
    except SourceAccessError as exc:
        result.source_access_issue, result.summary = exc.issue, str(exc)
    except HTTPError as exc:
        issue = http_access_error(exc)
        result.source_access_issue, result.summary = issue.issue, str(issue)
    except (URLError, TimeoutError, OSError):
        result.source_access_issue, result.summary = "unavailable", "The historical source could not be reached. Try again or use an accessible version history page."
    except ValueError as exc:
        result.summary = str(exc)
    return result
