"""Find wording inside an uploaded PDF, page by page.

Text is extracted once per file in the same isolated, memory-limited worker style used for validation.
Searches then run on the cached page text, so repeated searches of the same PDF are immediate.
"""
import base64
from collections import OrderedDict
import hashlib
import json
import re
import subprocess
import sys
from threading import BoundedSemaphore, Lock

from app.config import BACKEND_DIR, settings
from app.services.worker_process import worker_command

MAX_QUERY = 200
MAX_RESULTS = 200
SNIPPET_CONTEXT = 60
CACHED_FILES = 4

_slots = BoundedSemaphore(2)
_lock = Lock()
_pages: "OrderedDict[str, list[str]]" = OrderedDict()


def flatten(text: str) -> str:
    """Collapse line breaks and repeated spaces so a phrase matches across wrapped lines."""
    return re.sub(r"\s+", " ", text.replace("\u00ad", "").replace("\u00a0", " ")).strip()


def extract_text(data: bytes, first_pages: int | None = None) -> dict:
    """Page texts of a PDF read in the isolated worker: {"pages": [...], "page_count": n, "title": str | None}."""
    payload = {"upload": base64.b64encode(data).decode("ascii"), "max_pages": settings.PDF_VALIDATION_MAX_PAGES,
               "max_characters": settings.PDF_VALIDATION_MAX_CHARACTERS, "memory_mb": settings.PDF_VALIDATION_MEMORY_MB,
               "first_pages": first_pages}
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    try:
        process = subprocess.run(worker_command("app.services.pdf_validation_search_worker"), cwd=BACKEND_DIR,
                                 input=json.dumps(payload), encoding="utf-8", capture_output=True,
                                 timeout=settings.PDF_VALIDATION_TIMEOUT_SECONDS, **options)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Reading the PDF text took too long. Use the PDF viewer's own search instead.") from exc
    try:
        result = json.loads(process.stdout)
    except ValueError as exc:
        raise ValueError("The PDF text could not be read.") from exc
    if process.returncode or "error" in result:
        raise ValueError(result.get("error") or "The PDF text could not be read.")
    return result


def _extract(data: bytes) -> list[str]:
    return extract_text(data)["pages"]


def page_texts(data: bytes) -> list[str]:
    key = hashlib.sha256(data).hexdigest()
    with _lock:
        if key in _pages:
            _pages.move_to_end(key)
            return _pages[key]
    pages = [flatten(text) for text in _extract(data)]
    with _lock:
        _pages[key] = pages
        while len(_pages) > CACHED_FILES:
            _pages.popitem(last=False)
    return pages


def search_pdf(data: bytes, query: str):
    needle = flatten(query).casefold()
    if len(needle) < 2:
        raise ValueError("Enter at least two characters to search.")
    if len(needle) > MAX_QUERY:
        raise ValueError(f"Search text is limited to {MAX_QUERY} characters.")
    if not data.startswith(b"%PDF-"):
        raise ValueError("Upload a PDF file to search.")
    if not _slots.acquire(blocking=False):
        raise BlockingIOError("PDF search is busy. Try again shortly.")
    try:
        pages = page_texts(data)
    finally:
        _slots.release()
    matches, total, truncated, searchable, pages_matched = [], 0, False, 0, 0
    for number, text in enumerate(pages, 1):
        if text:
            searchable += 1
        folded = text.casefold()
        # casefold can change string length for a few scripts; fall back to the unfolded text then.
        haystack = folded if len(folded) == len(text) else text.lower()
        first, count, start = haystack.find(needle), 0, 0
        while (at := haystack.find(needle, start)) != -1:
            count += 1
            start = at + len(needle)
        if not count:
            continue
        total += count
        pages_matched += 1
        if len(matches) >= MAX_RESULTS:
            truncated = True
            continue
        begin, end = max(0, first - SNIPPET_CONTEXT), min(len(text), first + len(needle) + SNIPPET_CONTEXT)
        matches.append({"page": number, "count": count,
                        "before": ("…" if begin else "") + text[begin:first],
                        "match": text[first:first + len(needle)],
                        "after": text[first + len(needle):end] + ("…" if end < len(text) else "")})
    return {"query": query.strip(), "pages_searched": len(pages), "pages_with_text": searchable,
            "total_matches": total, "pages_matched": pages_matched,
            "truncated": truncated, "matches": matches}
