"""Independent, transient PDF validation against a selected public source."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from threading import BoundedSemaphore
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urlsplit

from app.config import BACKEND_DIR, settings
from app.pdf_validation_models import PdfArchiveSource, PdfDiscoveryTrail, PdfReference, PdfSourceCoverage, PdfSourceDiscovery, PdfValidationOptions, PdfValidationResult
from app.services.pdf_validation_discovery import discover_reference, looks_like_landing_page
from app.services.pdf_validation_source import extract_html, fetch_source, reference_allowed
from app.services.pdf_validation_access import SourceAccessError, ensure_source_access, http_access_error
from app.services.pdf_validation_history import discover_history
from app.services.pdf_validation_jurisdictions import resolve_jurisdiction, retrieve_document
from app.services.pdf_validation_dates import website_dates
from app.services.pdf_validation_collection import collect_document
from app.services.pdf_validation_archive import resolve_archive
from app.services.pdf_validation_navigation import navigation
from app.services.pdf_validation_range import validate_range
from app.services.worker_process import worker_command
from reflink.url.targets import valid_url_target


_slots = BoundedSemaphore(settings.PDF_VALIDATION_MAX_CONCURRENT)


def discover_pdf_source(url: str, options: PdfValidationOptions | None = None, fetch=None):
    url = url.strip()
    options = options or PdfValidationOptions()
    fetch = fetch or fetch_source
    if not valid_url_target(url):
        raise ValueError("Enter a valid HTTP or HTTPS document URL without embedded credentials.")
    jurisdiction = resolve_jurisdiction(url, options.jurisdiction)
    if not _slots.acquire(blocking=False):
        raise BlockingIOError("PDF validation is busy. Try again shortly.")
    hosts = tuple(settings.PDF_VALIDATION_ALLOWED_HOSTS) or (urlsplit(url).hostname,)
    try:
        if options.workflow == "date_range":
            return discover_history(url, hosts, options, fetch)
        snapshot = retrieve_document(url, hosts, fetch)
        ensure_source_access(snapshot)
        if snapshot.kind == "zip":
            archive = resolve_archive(snapshot, discover=True)
            return PdfSourceDiscovery(source_url=snapshot.url, source_type="zip", jurisdiction=jurisdiction,
                references=[PdfReference(**ref) for ref in archive["references"]],
                summary=f"Found {len(archive['references'])} PDF or HTML documents in this ZIP. Select the intended document."
                    if archive["references"] else "This ZIP contains no supported PDF or HTML documents.",
                limitations=["Unsupported archive entries: " + ", ".join(archive["unsupported"])] if archive["unsupported"] else [])
        if snapshot.kind == "pdf":
            return PdfSourceDiscovery(source_url=snapshot.url, source_type="pdf",
                                      jurisdiction=jurisdiction,
                                      summary="This URL returns a PDF. Choose your file and validate it against this document.")
        if snapshot.kind != "html":
            raise ValueError("The URL did not return a supported PDF or HTML document.")
        if len(snapshot.data) > settings.PDF_VALIDATION_MAX_HTML_BYTES:
            raise ValueError("The webpage is too large to search. Enter a direct PDF URL.")
        html, references = extract_html(snapshot)
        if not references:
            nav = navigation(snapshot)
            if nav["links"] or nav["complete"] or nav["interactive"]:
                html = collect_document(snapshot, hosts, fetch)
                references = html.get("references", [])
        if len(references) == 1 and references[0].get("kind") == "zip" and reference_allowed(references[0]["url"], hosts):
            archive_snapshot = fetch(references[0]["url"], hosts, settings.PDF_VALIDATION_MAX_BYTES, settings.PDF_VALIDATION_TIMEOUT_SECONDS)
            ensure_source_access(archive_snapshot)
            if archive_snapshot.kind == "zip":
                archive = resolve_archive(archive_snapshot, discover=True)
                if archive["references"]:
                    references = [{**ref, "url": references[0]["url"]} for ref in archive["references"]]
        return PdfSourceDiscovery(source_url=snapshot.url, source_type="html", source_title=html["title"],
                                  jurisdiction=jurisdiction,
                                  references=[PdfReference(**ref, available=reference_allowed(ref["url"], hosts)) for ref in references],
                                  summary=f"Found {len(references)} document links. Select the intended document to validate."
                                  if references else "No PDF or ZIP links were found. You can validate against this page's text or enter a direct document URL.")
    except HTTPError as exc:
        raise http_access_error(exc) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ValueError("The website could not be reached. Try again or enter a direct PDF URL.") from exc
    finally:
        _slots.release()


def discover_reference_source(upload: bytes, filename: str, url: str, options: PdfValidationOptions | None = None, fetch=None):
    """Locate the uploaded document from a Reference URL without comparing it yet."""
    url = url.strip()
    options = (options or PdfValidationOptions()).model_copy(update={"source_mode": "reference"})
    fetch = fetch or fetch_source
    if not valid_url_target(url):
        raise ValueError("Enter a valid HTTP or HTTPS document URL without embedded credentials.")
    if not filename.lower().endswith(".pdf") or not upload.startswith(b"%PDF-"):
        raise ValueError("Choose the PDF to find; a Reference URL is searched for the uploaded document.")
    jurisdiction = resolve_jurisdiction(url, options.jurisdiction)
    if not _slots.acquire(blocking=False):
        raise BlockingIOError("PDF validation is busy. Try again shortly.")
    hosts = tuple(settings.PDF_VALIDATION_ALLOWED_HOSTS) or (urlsplit(url).hostname,)
    try:
        snapshot = retrieve_document(url, hosts, fetch)
        ensure_source_access(snapshot)
        if snapshot.kind in {"pdf", "zip"}:
            return PdfSourceDiscovery(source_url=snapshot.url, source_type=snapshot.kind, jurisdiction=jurisdiction, source_mode="reference",
                summary="This Reference URL is itself a document, so it will be compared directly.")
        if snapshot.kind != "html":
            raise ValueError("The URL did not return a supported PDF or HTML page.")
        if len(snapshot.data) > settings.PDF_VALIDATION_MAX_HTML_BYTES:
            raise ValueError("The Reference URL page is too large to search. Enter a page closer to the document.")
        trail, found = discover_reference(upload, filename, snapshot, hosts, fetch)
        references = [PdfReference(url=found.url, label=trail["selected_label"] or "Discovered document")] if found else []
        return PdfSourceDiscovery(source_url=snapshot.url, source_type="html", jurisdiction=jurisdiction, source_mode="reference",
                                  summary=trail["summary"], references=references, discovery=PdfDiscoveryTrail.model_validate(trail))
    except HTTPError as exc:
        raise http_access_error(exc) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ValueError("The website could not be reached. Try again or enter a direct PDF URL.") from exc
    finally:
        _slots.release()


def run_analysis(upload: bytes, snapshot, html, exact: bool):
    payload = {"upload": base64.b64encode(upload).decode("ascii"), "exact": exact, "html": html,
               "source_url": snapshot.url, "max_pages": settings.PDF_VALIDATION_MAX_PAGES,
               "memory_mb": settings.PDF_VALIDATION_MEMORY_MB,
               "max_characters": settings.PDF_VALIDATION_MAX_CHARACTERS,
               "reference": base64.b64encode(snapshot.data).decode("ascii") if snapshot.kind == "pdf" and not exact else None}
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    try:
        process = subprocess.run(worker_command("app.services.pdf_validation_worker"), cwd=BACKEND_DIR,
                                 input=json.dumps(payload), encoding="utf-8", capture_output=True,
                                 timeout=settings.PDF_VALIDATION_TIMEOUT_SECONDS, **options)
        if process.returncode:
            return {"status": "needs_review", "summary": "PDF analysis could not finish within its resource limits. Review this document manually.",
                    "coverage_complete": False, "findings": []}
        return json.loads(process.stdout)
    except subprocess.TimeoutExpired:
        return {"status": "needs_review", "summary": "PDF analysis reached its time limit. Review the document manually.",
                "coverage_complete": False, "findings": []}


def validate_pdf(upload: bytes, filename: str, url: str, reference_url: str | None = None,
                 options: PdfValidationOptions | None = None, fetch=None):
    url = url.strip()
    options = options or PdfValidationOptions()
    fetch = fetch or fetch_source
    if not valid_url_target(url):
        raise ValueError("Enter a valid HTTP or HTTPS document URL without embedded credentials.")
    if not filename.lower().endswith(".pdf") or not upload.startswith(b"%PDF-"):
        raise ValueError("Upload a PDF file with a .pdf filename.")
    if len(upload) > settings.PDF_VALIDATION_MAX_BYTES:
        raise ValueError("The uploaded PDF exceeds the configured size limit.")
    jurisdiction = resolve_jurisdiction(url, options.jurisdiction)
    if options.workflow == "date_range":
        if reference_url:
            raise ValueError("Date range comparison checks each historical version; clear the single reference selection.")
        return validate_range(upload, filename, url, options.model_copy(update={"jurisdiction": jurisdiction}),
                              lambda target, scope: discover_pdf_source(target, scope, fetch),
                              lambda *args, **kwargs: validate_pdf(*args, **kwargs, fetch=fetch))
    if not _slots.acquire(blocking=False):
        raise BlockingIOError("PDF validation is busy. Try again shortly.")
    result = PdfValidationResult(status="unable", summary="The source could not be retrieved.",
                                 filename=Path(filename.replace("\\", "/")).name[:255], submitted_url=url, source_url=url,
                                 jurisdiction=jurisdiction,
                                 checked_at=datetime.now(timezone.utc).isoformat(), upload_sha256=hashlib.sha256(upload).hexdigest())
    hosts = tuple(settings.PDF_VALIDATION_ALLOWED_HOSTS) or (urlsplit(url).hostname,)
    result.source_mode = options.source_mode
    landing = None
    try:
        snapshot = retrieve_document(url, hosts, fetch)
        result.source_url, result.source_type = snapshot.url, snapshot.kind
        ensure_source_access(snapshot)
        html = None
        if options.source_mode == "reference":
            if reference_url:
                raise ValueError("A Reference URL finds the document itself; clear the reference document selection.")
            if snapshot.kind == "html":
                if len(snapshot.data) > settings.PDF_VALIDATION_MAX_HTML_BYTES:
                    raise ValueError("The Reference URL page is too large to search. Enter a page closer to the document.")
                result.website_modified_on = website_dates(snapshot)
                trail, found = discover_reference(upload, filename, snapshot, hosts, fetch)
                result.discovery = PdfDiscoveryTrail.model_validate(trail)
                if found is None:
                    result.status = "needs_review" if trail["status"] == "needs_review" else "unable"
                    result.summary = trail["summary"]
                    return result
                snapshot = found
                result.source_url, result.source_type = snapshot.url, snapshot.kind
            else:
                landing = "direct"
        elif snapshot.kind == "html":
            landing = snapshot
        if snapshot.kind == "html":
            if len(snapshot.data) > settings.PDF_VALIDATION_MAX_HTML_BYTES:
                result.status, result.summary = "needs_review", "The webpage is too large for static comparison. Enter a direct PDF URL."
                return result
            html, references = extract_html(snapshot)
            result.website_modified_on = website_dates(snapshot)
            if not references:
                html = collect_document(snapshot, hosts, fetch)
                result.source_coverage = PdfSourceCoverage.model_validate(html["source_coverage"])
                references = html.get("references", [])
            result.source_title = html["title"]
            result.references = [PdfReference(**ref, available=reference_allowed(ref["url"], hosts)) for ref in references]
            if reference_url:
                selected = next((ref for ref in result.references if urldefrag(reference_url)[0] == ref.url), None)
                if not selected or not selected.available:
                    raise ValueError("Select an available document linked from this source page.")
            elif len(references) == 1 and result.references[0].available:
                reference_url = references[0]["url"]
            elif references:
                result.status, result.summary = "needs_review", "Select the intended reference document and validate again."
                return result
            if reference_url:
                snapshot = fetch(urldefrag(reference_url)[0], hosts, settings.PDF_VALIDATION_MAX_BYTES, settings.PDF_VALIDATION_TIMEOUT_SECONDS)
                result.source_url, result.source_type = snapshot.url, snapshot.kind
                ensure_source_access(snapshot)
                if snapshot.kind not in {"pdf", "zip"}:
                    result.summary = "The selected link did not return a PDF or ZIP. Enter the direct document URL."
                    return result
                result.source_coverage = None
            elif sum(len(unit["text"]) for unit in html["units"]) > settings.PDF_VALIDATION_MAX_CHARACTERS:
                result.status, result.summary = "needs_review", "The webpage exceeds the text limit. Select a smaller document or direct PDF URL."
                return result
            else:
                if not html["units"]:
                    result.status, result.summary = "needs_review", "The website's document text could not be retrieved. Review the source collection coverage or use a direct PDF URL."
                    return result
        elif reference_url and not (snapshot.kind == "zip" and urldefrag(reference_url)[0] in {url, snapshot.url}):
            raise ValueError("A reference selection must identify a linked website document or a member of the supplied ZIP.")
        if snapshot.kind == "zip":
            archive = resolve_archive(snapshot, options.archive_member)
            selection_url = urldefrag(reference_url or url)[0]
            result.references = [PdfReference(**{**ref, "url": selection_url}, available=reference_allowed(selection_url, hosts))
                for ref in archive["references"]]
            if not archive.get("member"):
                result.status = "needs_review"
                result.summary = "Select the intended document inside the ZIP and validate again." if result.references else "This ZIP contains no supported PDF or HTML documents."
                if archive["unsupported"]:
                    result.limitations.append("Unsupported archive entries: " + ", ".join(archive["unsupported"]))
                return result
            result.archive_source = PdfArchiveSource.model_validate(archive["archive_source"])
            snapshot, html = archive["snapshot"], archive.get("html")
            result.source_type = snapshot.kind
            result.source_coverage = (PdfSourceCoverage.model_validate(html["source_coverage"]) if html else
                PdfSourceCoverage(method="zip_pdf", expected_sections=1, retrieved_sections=1, pages_retrieved=1, complete=True,
                    sections=[{"url": snapshot.url, "label": archive["member"], "status": "retrieved"}]))
        elif options.archive_member:
            raise ValueError("An archive member can only be selected for a ZIP source.")
        if snapshot.kind == "unknown":
            result.summary = "The URL did not return a supported PDF or HTML document."
            return result
        result.source_sha256 = html.get("source_sha256", hashlib.sha256(snapshot.data).hexdigest()) if snapshot.kind == "html" else hashlib.sha256(snapshot.data).hexdigest()
        result.source_retrieved_at = snapshot.retrieved_at
        result.retrieval_attempts = snapshot.retrieval_attempts
        exact = snapshot.kind == "pdf" and result.upload_sha256 == result.source_sha256
        analysis = run_analysis(upload, snapshot, html, exact)
        if result.archive_source:
            limitations = analysis.setdefault("limitations", [])
            limitations.append("Compared archive member: " + result.archive_source.member)
            if result.archive_source.unsupported_members:
                limitations.append("Other unsupported archive entries were not compared: " + ", ".join(result.archive_source.unsupported_members))
            for finding in analysis.get("findings", []):
                if not finding.get("source_archive_member"):
                    finding["source_archive_member"] = result.archive_source.member
        if landing == "direct":
            analysis.setdefault("limitations", []).append("The Reference URL is itself a document, so it was compared directly.")
        elif landing is not None and analysis.get("status") != "match" and looks_like_landing_page(landing):
            analysis["summary"] = (analysis.get("summary") or "") + (" This URL looks like a website landing page or index."
                " Choose Reference URL to find the document inside the website.")
        if result.discovery:
            analysis.setdefault("scope_notes", []).append("Source found from the Reference URL: "
                + " > ".join(step.label for step in result.discovery.path[1:]))
        return PdfValidationResult.model_validate({**result.model_dump(), **analysis})
    except SourceAccessError as exc:
        result.source_access_issue, result.summary = exc.issue, str(exc)
        return result
    except HTTPError as exc:
        issue = http_access_error(exc)
        result.source_access_issue, result.summary = issue.issue, str(issue)
        return result
    except (URLError, TimeoutError, OSError):
        result.source_access_issue = "unavailable"
        result.summary = "The website could not be reached within the retrieval limit. Try again or enter a direct PDF URL."
        return result
    except ValueError as exc:
        result.summary = str(exc)
        return result
    finally:
        _slots.release()
