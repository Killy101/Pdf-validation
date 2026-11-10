"""Isolated page text extraction for searching an uploaded PDF or identifying a document by its first pages."""
import base64
from io import BytesIO
import json
import logging
import sys

from pypdf import PdfReader


def extract_pages(data: bytes, max_pages: int, max_characters: int, first_pages: int | None = None):
    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("The PDF is password protected. Upload an unlocked copy to search it.")
    count = len(reader.pages)
    if not count:
        raise ValueError("The PDF has no readable pages.")
    if not first_pages and count > max_pages:
        raise ValueError("The PDF exceeds the configured page limit for searching.")
    pages, length = [], 0
    for page in reader.pages[:first_pages] if first_pages else reader.pages:
        text = page.extract_text() or ""
        length += len(text)
        if length > max_characters:
            raise ValueError("The PDF exceeds the configured text limit for searching.")
        pages.append(text)
    title = str((reader.metadata or {}).get("/Title") or "").strip()[:300] or None
    return {"pages": pages, "page_count": count, "title": title}


def main():
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        from app.services.pdf_validation_limits import limit_memory
        payload = json.load(sys.stdin)
        limit_memory(payload["memory_mb"])
        result = extract_pages(base64.b64decode(payload["upload"], validate=True), payload["max_pages"],
                               payload["max_characters"], payload.get("first_pages"))
    except ValueError as exc:
        result = {"error": str(exc)}
    except (MemoryError, OSError):
        result = {"error": "The PDF reached a resource limit while reading its text."}
    except Exception:
        result = {"error": "The PDF text could not be read for searching. Upload a valid, undamaged PDF."}
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
