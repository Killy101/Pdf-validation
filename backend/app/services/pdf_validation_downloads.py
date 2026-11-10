"""Bounded downloads of the source used by a PDF validation result."""
import base64
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
from threading import BoundedSemaphore
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit

from app.config import BACKEND_DIR, settings
from app.services.pdf_validation_access import ensure_source_access
from app.services.pdf_validation_collection import collect_document
from app.services.pdf_validation_archive import resolve_archive
from app.services.worker_process import worker_command
from reflink.url.targets import valid_url_target


_slots = BoundedSemaphore(settings.PDF_VALIDATION_MAX_CONCURRENT)


class SourceChanged(ValueError):
    pass


def checked_download(source_url, source_sha256, fetch, collection=False):
    if not valid_url_target(source_url):
        raise ValueError("Enter a valid public source URL.")
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ValueError("Validate the document before downloading its source.")
    if not _slots.acquire(blocking=False):
        raise BlockingIOError("PDF downloads are busy. Try again shortly.")
    try:
        hosts = tuple(settings.PDF_VALIDATION_ALLOWED_HOSTS) or (urlsplit(source_url).hostname,)
        snapshot = fetch(source_url, hosts, settings.PDF_VALIDATION_MAX_BYTES, settings.PDF_VALIDATION_TIMEOUT_SECONDS)
        ensure_source_access(snapshot)
        if sha256(snapshot.data).hexdigest() != source_sha256 and not (collection and snapshot.kind == "html"):
            raise SourceChanged("The source has changed since validation. Validate again before downloading.")
        return snapshot
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ValueError("The source could not be downloaded. Try again or validate the document again.") from exc
    finally:
        _slots.release()


def source_filename(source_url):
    name = unquote(urlsplit(source_url).path.rsplit("/", 1)[-1])
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip(".-")[:120] or "source-document"
    return name if name.lower().endswith(".pdf") else name + ".pdf"


def archive_download(source_url, source_sha256, member, archive_sha256, fetch):
    if not member or not archive_sha256 or not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ValueError("Validate the archive document before downloading its source.")
    snapshot = checked_download(source_url, archive_sha256, fetch)
    if snapshot.kind != "zip":
        raise ValueError("The selected source does not provide a ZIP archive.")
    archive = resolve_archive(snapshot, member)
    digest = archive["html"]["source_sha256"] if archive.get("html") else archive["archive_source"]["member_sha256"]
    if digest != source_sha256:
        raise SourceChanged("The archive document has changed since validation. Validate again before downloading.")
    return archive


def official_pdf(source_url, source_sha256, fetch, archive_member=None, archive_sha256=None):
    archive = archive_download(source_url, source_sha256, archive_member, archive_sha256, fetch) if archive_member or archive_sha256 else None
    snapshot = archive["snapshot"] if archive else checked_download(source_url, source_sha256, fetch)
    if snapshot.kind != "pdf" or not snapshot.data.startswith(b"%PDF-"):
        raise ValueError("The selected source does not provide a downloadable PDF.")
    return snapshot.data, source_filename(archive_member if archive else snapshot.url)


def updated_pdf(upload, filename, source_url, source_sha256, fetch, archive_member=None, archive_sha256=None):
    if not filename.lower().endswith(".pdf") or not upload.startswith(b"%PDF-"):
        raise ValueError("Upload the PDF used for this validation.")
    if len(upload) > settings.PDF_VALIDATION_MAX_BYTES:
        raise ValueError("The uploaded PDF exceeds the configured size limit.")
    archive = archive_download(source_url, source_sha256, archive_member, archive_sha256, fetch) if archive_member or archive_sha256 else None
    snapshot = archive["snapshot"] if archive else checked_download(source_url, source_sha256, fetch, collection=True)
    if snapshot.kind not in {"pdf", "html"}:
        raise ValueError("The selected source has no readable document content.")
    filename = Path(filename.replace("\\", "/")).name[:255]
    html = archive.get("html") if archive else None
    if snapshot.kind == "html" and not archive:
        hosts = tuple(settings.PDF_VALIDATION_ALLOWED_HOSTS) or (urlsplit(source_url).hostname,)
        html = collect_document(snapshot, hosts, fetch)
        if html["source_sha256"] != source_sha256:
            raise SourceChanged("The source document or one of its chapters has changed. Validate again before downloading.")
    payload = {"upload": base64.b64encode(upload).decode("ascii"), "filename": filename,
        "archive_member": archive_member, "archive_sha256": archive_sha256,
        "source_url": snapshot.url, "source_sha256": source_sha256,
        "reference": base64.b64encode(snapshot.data).decode("ascii") if snapshot.kind == "pdf" else None,
        "html": html,
        "max_pages": settings.PDF_VALIDATION_MAX_PAGES, "max_bytes": settings.PDF_VALIDATION_MAX_BYTES,
        "max_characters": settings.PDF_VALIDATION_MAX_CHARACTERS, "memory_mb": settings.PDF_VALIDATION_MEMORY_MB,
        "font_path": settings.PDF_VALIDATION_EXPORT_FONT_PATH}
    if not _slots.acquire(blocking=False):
        raise BlockingIOError("PDF downloads are busy. Try again shortly.")
    try:
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        process = subprocess.run(worker_command("app.services.pdf_validation_export_worker"), cwd=BACKEND_DIR,
            input=json.dumps(payload), encoding="utf-8", capture_output=True,
            timeout=settings.PDF_VALIDATION_TIMEOUT_SECONDS, **options)
        if process.returncode:
            raise ValueError("The updated PDF could not be generated. Download the official PDF instead.")
        result = json.loads(process.stdout)
        if result.get("error"):
            raise ValueError(result["error"])
        return base64.b64decode(result["data"], validate=True), source_filename(filename)[:-4] + "-updated.pdf"
    except subprocess.TimeoutExpired as exc:
        raise ValueError("PDF generation reached its time limit. Download the official PDF instead.") from exc
    finally:
        _slots.release()
