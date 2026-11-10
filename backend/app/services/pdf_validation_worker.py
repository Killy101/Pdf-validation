"""Isolated PDF extraction and content comparison with page evidence."""
import base64
from io import BytesIO
import json
import logging
import re
import sys

from pypdf import PdfReader, mult
from app.services.pdf_validation_identity import check_identity
from app.services.pdf_validation_text import TOKEN, document_changes, excerpt, normalize_wraps, page_range, search_phrase, tokens
from app.services.pdf_validation_layout import comparison_scope, document_layout, page_columns, repair_definition_labels
from app.services.pdf_validation_dates import pdf_dates
from app.services.pdf_validation_sections import section_pairs


class ExtractionIncomplete(ValueError):
    pass


def extract_pdf(data: bytes, max_pages: int, max_characters: int, exact: bool = False):
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionIncomplete("The PDF is password protected. Upload an unlocked copy.")
        count = len(reader.pages)
        if not count:
            raise ValueError("The PDF has no readable pages.")
        title = str((reader.metadata or {}).get("/Title") or "").strip()[:200] or None
        if exact:
            return {"units": [], "pages": count, "title": title, "complete": True, "dates": pdf_dates(reader, "")}
        if count > max_pages:
            raise ExtractionIncomplete("The PDF exceeds the configured page limit for content comparison.")
        units, length, blank, graphics = [], 0, [], []
        for index, page in enumerate(reader.pages, 1):
            resources = page.get("/Resources")
            objects = resources.get_object().get("/XObject") if resources else None
            if objects and any(item.get_object().get("/Subtype") in {"/Image", "/Form"} for item in objects.get_object().values()):
                graphics.append(index)
            runs = []
            def visit(text, cm, tm, font, size, runs=runs):
                if text.strip():
                    position = mult(tm, cm)
                    runs.append((position[4], position[5], text, size))
            text = page.extract_text(visitor_text=visit) or ""
            text, _ = repair_definition_labels(text, runs)
            length += len(text)
            if length > max_characters:
                raise ExtractionIncomplete("The PDF exceeds the configured text limit for content comparison.")
            if len(re.findall(r"\w+", text)) < 3 and not (sum(char.isalpha() for char in text) >= 12 and len(TOKEN.findall(text)) >= 3):
                blank.append(index)
            units.append({"text": text, "page": index, **page_columns(runs, float(page.mediabox.width), float(page.mediabox.height))})
        title = title or next((line.strip()[:200] for unit in units for line in unit["text"].splitlines() if line.strip()), None)
        return {"units": units, "pages": count, "title": title, "complete": not blank, "blank_pages": blank,
                "requires_visual_review": bool(graphics), "layout": document_layout(units),
                "dates": pdf_dates(reader, "\n".join(unit["text"] for unit in units[:3]))}
    except ExtractionIncomplete:
        raise
    except MemoryError:
        raise
    except Exception as exc:
        raise ValueError("The PDF could not be read. Upload a valid, undamaged PDF.") from exc


def compare_documents(upload, reference, source_url: str, align=True):
    original_upload, original_reference = upload, reference
    upload, reference, evidence = comparison_scope(upload, reference, source_url)
    if evidence["language_alignment"] == "needs_review":
        return {**evidence, "status": "needs_review", "summary": "Language selection needs review. Select the source text corresponding to the uploaded PDF before checking wording.",
            "coverage_complete": False, "checked_pdf_pages": 0, "findings": [], "document_identity": "needs_review",
            "identity_summary": "The same document and published language must be confirmed before content differences can be established."}
    upload, reference = normalize_wraps(upload, reference), normalize_wraps(reference, upload)
    actual, actual_locations, actual_blocks = tokens(upload)
    expected, expected_locations, expected_blocks = tokens(reference)
    complete = upload["complete"] and reference["complete"]
    if not actual or not expected:
        return {**evidence, "status": "needs_review", "summary": "There is insufficient extractable text to compare this document.",
                "coverage_complete": False, "findings": [], "document_identity": "needs_review",
                "identity_summary": "There is insufficient text to confirm that the PDF and source refer to the same document."}
    identity_reference = reference if evidence["language_alignment"] == "selected" else original_reference
    identity = check_identity(original_upload, identity_reference, actual, expected)
    if identity["document_identity"] == "mismatch":
        pdf_title, source_title = identity["identity_pdf_title"], identity["identity_source_title"]
        return {**evidence, **identity, "status": "mismatch", "summary": identity["identity_summary"],
                "coverage_complete": complete, "findings": [{"kind": "document_mismatch", "severity": "error",
                "message": "The visible titles and extracted content indicate an unrelated PDF and source.",
                "pdf_page": 1, "source_url": source_url, "expected": source_title, "actual": pdf_title,
                "action": "Upload the correct PDF or enter the URL for this document, then validate again."}]}
    plan = section_pairs(upload, reference) if align else None
    if align and plan is None and reference.get("source_coverage") and not reference["complete"]:
        return {**evidence, **identity, "status": "needs_review", "coverage_complete": False, "checked_pdf_pages": 0,
            "summary": "The collected source is incomplete and could not be aligned reliably. No content differences were asserted.",
            "findings": []}
    if plan is not None:
        findings = []
        for pdf_section, source_section in plan["pairs"]:
            findings.extend(compare_documents(pdf_section, source_section, source_url, align=False)["findings"])
        complete = complete and plan["complete"]
        evidence["scope_notes"].extend(plan["notes"])
        evidence["scope_notes"].append(f"Compared {plan.get('numbered_count', len(plan['pairs']))} corresponding numbered sections using their source locations.")
        return {**evidence, **identity, "status": "needs_review" if not complete else "mismatch" if findings else "match",
            "summary": "Some source or PDF sections were not checked. Review source coverage and section mappings." if not complete else
                "Corresponding document sections differ." if findings else "Corresponding extracted sections match the collected source.",
            "coverage_complete": complete, "findings": findings[:100], "findings_truncated": len(findings) > 100,
            "checked_pdf_pages": len({unit["page"] for pdf_section, _ in plan["pairs"] for unit in pdf_section["units"] if unit.get("page")})}
    operations = document_changes(expected, actual, expected_blocks, actual_blocks)
    findings, truncated = [], False
    for tag, start, end, a_start, a_end in operations:
        if len(findings) == 100:
            truncated = True
            break
        source = expected_locations[min(start, len(expected_locations) - 1)]
        pdf_page, pdf_page_end = page_range(actual_locations, a_start, a_end)
        source_page, source_page_end = page_range(expected_locations, start, end)
        url = source.get("url") or source_url + (f"#page={source_page}" if source_page else "")
        kind = {"delete": "missing_content", "insert": "extra_content", "replace": "changed_content"}[tag]
        message = {"delete": "Content present in the source is missing from the uploaded PDF.",
                   "insert": "The uploaded PDF contains text absent from the selected source.",
                   "replace": "The uploaded PDF and source contain different text."}[tag]
        expected_text, expected_change = excerpt(expected_locations, start, end, evidence=True) if tag != "insert" else ("", [0, 0])
        actual_text, actual_change = excerpt(actual_locations, a_start, a_end, evidence=True) if tag != "delete" else ("", [0, 0])
        findings.append({"kind": kind, "severity": "error" if complete else "warning", "message": message,
                         "pdf_page": pdf_page, "pdf_page_end": pdf_page_end, "approximate_location": tag == "delete",
                         "source_page": source_page, "source_page_end": source_page_end,
                         "source_heading": source.get("heading"), "source_url": url,
                         "source_archive_member": source.get("archive_member"),
                         "expected": expected_text, "actual": actual_text,
                         "expected_change": expected_change, "actual_change": actual_change,
                         "pdf_search_text": search_phrase(actual_locations, a_start),
                         "excerpt_truncated": max(end - start, a_end - a_start) > 120,
                         "action": "Review the indicated section and confirm the intended document and edition."})
    if not complete:
        status, summary = "needs_review", "Extraction or source coverage is incomplete. Review the findings before accepting this PDF."
    elif findings:
        status, summary = "mismatch", "The extracted content differs from the selected source. Review the reported locations."
    else:
        status, summary = "match", "The extracted text matches the selected source within the checked scope."
    return {**evidence, **identity, "status": status, "summary": summary, "coverage_complete": complete,
            "findings": findings[:100], "findings_truncated": truncated}


def analyze(payload):
    upload = extract_pdf(base64.b64decode(payload["upload"], validate=True), payload["max_pages"],
                         payload["max_characters"], payload["exact"])
    metadata = {"pdf_pages": upload["pages"], "pdf_title": upload["title"],
                "checked_pdf_pages": upload["pages"], "comparison": "content",
                "pdf_dates": upload.get("dates", {})}
    if payload["exact"]:
        return {**metadata, "source_pages": upload["pages"], "source_title": upload["title"],
                "source_dates": upload.get("dates", {}),
                "comparison": "exact_file", "coverage_complete": True, "status": "match", "findings": [],
                "document_identity": "match", "identity_summary": "The PDF is the same file as the selected source.",
                "summary": "The uploaded PDF is an exact file match for the selected website PDF.", "limitations": []}
    if payload.get("reference"):
        try:
            reference = extract_pdf(base64.b64decode(payload["reference"], validate=True), payload["max_pages"], payload["max_characters"])
        except ValueError as exc:
            raise ExtractionIncomplete("The reference PDF could not be fully extracted. Confirm the reference file manually.") from exc
        metadata.update(source_pages=reference["pages"], source_title=reference["title"])
    else:
        reference = payload["html"]
        metadata["source_title"] = reference["title"]
    metadata["source_dates"] = reference.get("dates", {})
    result = compare_documents(upload, reference, payload["source_url"])
    for field in ("pdf_title", "source_title"):
        if result.get("identity_" + field):
            metadata[field] = result["identity_" + field]
    limitations = ["Content comparison checks extracted text; images, layout, signatures, and table structure are not verified.",
                   "The selected source is checked as retrieved now. Historical editions must be selected explicitly."]
    if not upload["complete"]:
        limitations.append("PDF pages with little or no extracted text require visual review or OCR: " + ", ".join(map(str, upload["blank_pages"])))
    if not reference["complete"]:
        limitations.append("The source has incomplete text or navigation coverage; a complete document match cannot be established.")
    if not payload.get("reference"):
        limitations.append("Website headers, navigation, and viewer controls are excluded from the document text comparison.")
        coverage = reference.get("source_coverage")
        if coverage:
            limitations.append(f"Collected {coverage['retrieved_sections']} of {coverage['expected_sections'] if coverage['expected_sections'] is not None else 'an unknown number of'} declared source sections across {coverage['pages_retrieved']} pages.")
        else:
            limitations.append("Only the submitted source page was checked.")
    if upload.get("requires_visual_review") or reference.get("requires_visual_review"):
        limitations.append("Image, graphic, or structured source content requires visual review unless the PDF files match exactly.")
        if result["status"] == "match":
            result.update(status="needs_review", summary="The extracted text matches, but visual or structured content requires manual review.")
    if metadata.get("source_pages") and metadata["pdf_pages"] != metadata["source_pages"]:
        scoped_language = result.get("language_alignment") == "selected"
        result["findings"].append({"kind": "page_count", "severity": "info" if scoped_language else "warning", "source_url": payload["source_url"],
                                   "message": "PDF page counts differ; pagination alone does not establish missing content.",
                                   "expected": str(metadata["source_pages"]), "actual": str(metadata["pdf_pages"]),
                                   "action": "Check whether the files use different pagination or contain additional material."})
        if result["status"] == "match" and not scoped_language:
            result.update(status="needs_review", summary="The extracted text matches, but the PDF page counts differ.")
    return {**metadata, **result, "limitations": limitations}


def main():
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        from app.services.pdf_validation_limits import limit_memory
        payload = json.load(sys.stdin)
        limit_memory(payload["memory_mb"])
        result = analyze(payload)
    except ExtractionIncomplete as exc:
        result = {"status": "needs_review", "summary": str(exc), "coverage_complete": False, "findings": []}
    except ValueError as exc:
        result = {"status": "unable", "summary": str(exc), "coverage_complete": False, "findings": []}
    except (MemoryError, OSError):
        result = {"status": "needs_review", "summary": "PDF analysis reached a resource limit. Review the document manually.",
                  "coverage_complete": False, "findings": []}
    except Exception:
        result = {"status": "unable", "summary": "The document could not be compared safely. Review it manually.",
                  "coverage_complete": False, "findings": []}
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
