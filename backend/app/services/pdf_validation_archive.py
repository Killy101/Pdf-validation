"""Resolve transient ZIP documents through a bounded, isolated archive worker."""
import base64
from hashlib import sha256
import json
import subprocess
import sys
from threading import BoundedSemaphore

from app.config import BACKEND_DIR, settings
from app.services.pdf_validation_source import SourceSnapshot
from app.services.worker_process import worker_command


_slots = BoundedSemaphore(settings.PDF_VALIDATION_MAX_CONCURRENT)


def resolve_archive(snapshot, member=None, discover=False):
    if len(snapshot.data) > settings.PDF_VALIDATION_MAX_BYTES:
        raise ValueError("The ZIP download exceeds the configured size limit.")
    payload = {"data": base64.b64encode(snapshot.data).decode("ascii"), "url": snapshot.url,
        "member": member, "discover": discover, "memory_mb": settings.PDF_VALIDATION_MEMORY_MB,
        "max_files": settings.PDF_VALIDATION_ZIP_MAX_FILES,
        "max_expanded_bytes": settings.PDF_VALIDATION_ZIP_MAX_EXPANDED_BYTES,
        "max_bytes": settings.PDF_VALIDATION_MAX_BYTES, "max_html_bytes": settings.PDF_VALIDATION_MAX_HTML_BYTES,
        "timeout": settings.PDF_VALIDATION_TIMEOUT_SECONDS}
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    if not _slots.acquire(blocking=False):
        raise ValueError("ZIP inspection is busy. Try again shortly.")
    try:
        process = subprocess.run(worker_command("app.services.pdf_validation_archive_worker"),
            cwd=BACKEND_DIR, input=json.dumps(payload), encoding="utf-8", capture_output=True,
            timeout=settings.PDF_VALIDATION_TIMEOUT_SECONDS, **options)
        if process.returncode:
            raise ValueError("ZIP inspection reached a resource limit. Select a smaller archive or a direct document URL.")
        result = json.loads(process.stdout)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("ZIP inspection reached its time limit. Select a smaller archive or a direct document URL.") from exc
    finally:
        _slots.release()
    if result.get("error"):
        raise ValueError(result["error"])
    result["references"] = [{"url": snapshot.url, "label": item["name"], "archive_member": item["name"],
        "kind": item["kind"]} for item in result["entries"]]
    if result.get("member"):
        data = base64.b64decode(result.pop("data"), validate=True)
        result["snapshot"] = SourceSnapshot(data, snapshot.url, result["kind"],
            "application/pdf" if result["kind"] == "pdf" else "text/html", snapshot.retrieved_at, snapshot.retrieval_attempts)
        result["archive_source"] = {"url": snapshot.url, "sha256": sha256(snapshot.data).hexdigest(),
            "member": result["member"], "member_sha256": sha256(data).hexdigest(),
            "unsupported_members": result["unsupported"]}
    return result
