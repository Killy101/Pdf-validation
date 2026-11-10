"""Generate a readable source-text PDF within the validation worker limits."""
import base64
from datetime import datetime, timezone
from html import escape
from io import BytesIO
import json
import logging
from pathlib import Path
import sys
import textwrap

from app.services.pdf_validation_identity import check_identity
from app.services.pdf_validation_text import normalize_wraps, tokens
from app.services.pdf_validation_layout import comparison_scope
from app.services.pdf_validation_worker import extract_pdf


def render_pdf(reference, title, payload):
    import reportlab
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    font_path = payload.get("font_path") or Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
    try:
        font = TTFont("ValidationExport", str(font_path))
        # Reuse the hyphen glyph while preserving Unicode hyphens in extracted text.
        for code in (0x2010, 0x2011):
            if code not in font.face.charToGlyph and 0x2D in font.face.charToGlyph:
                font.face.charToGlyph[code] = font.face.charToGlyph[0x2D]
                font.face.charWidths[code] = font.face.charWidths[0x2D]
        pdfmetrics.registerFont(font)
    except Exception as exc:
        raise ValueError("The PDF export font could not be loaded. Ask an administrator to check the export font configuration.") from exc
    text = "\n".join(unit["text"] for unit in reference["units"])
    evidence = [title, payload["filename"], payload["source_url"]]
    if any(ord(char) not in font.face.charToGlyph for char in text + "".join(evidence) if not char.isspace()):
        raise ValueError("The export font does not support every source character. Download the official PDF or ask an administrator to configure a font for this language.")
    output = BytesIO()
    body = ParagraphStyle("Body", fontName=font.fontName, fontSize=10.5, leading=16, spaceAfter=4)
    heading = ParagraphStyle("Heading", parent=body, fontSize=18, leading=24, spaceAfter=16)
    label = ParagraphStyle("Label", parent=body, fontSize=9, leading=14, textColor=colors.HexColor("#475569"))
    story = [Paragraph("Updated PDF - source text copy", heading), Paragraph(escape(title), heading)]
    details = ["Rebuilt with the complete extracted text of the selected source in a new layout.",
        "Images, signatures, and original table formatting are not reproduced.",
        "Original upload: " + payload["filename"], "Source: " + payload["source_url"],
        "Source SHA-256: " + payload["source_sha256"],
        "Generated: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")]
    details.extend(payload.get("scope_notes", []))
    if payload.get("archive_member"):
        details.extend(["Archive member: " + payload["archive_member"], "Archive SHA-256: " + payload["archive_sha256"]])
    if payload.get("source_current_to"):
        details.append("Source current to: " + payload["source_current_to"])
    story.extend(Paragraph(escape(line), label) for line in details)
    story.append(PageBreak())
    for index, unit in enumerate(reference["units"], 1):
        if unit.get("page"):
            if index > 1:
                story.append(PageBreak())
            story.append(Paragraph(f"Source PDF page {unit['page']}", label))
            story.append(Spacer(1, 10))
        for line in unit["text"].splitlines():
            for part in textwrap.wrap(line, width=2000, break_long_words=False, break_on_hyphens=False):
                story.append(Paragraph(escape(part), body))
    def footer(canvas, document):
        if document.page > payload["max_pages"] + 1:
            raise ValueError("The rebuilt PDF exceeds the configured page limit. Download the official PDF instead.")
        canvas.setFont(font.fontName, 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(48, 30, "Generated source text copy")
        canvas.drawRightString(A4[0] - 48, 30, f"Page {document.page}")
    SimpleDocTemplate(output, pagesize=A4, leftMargin=48, rightMargin=48, topMargin=48, bottomMargin=48,
        title=title + " - updated source text copy", author="Reflink Automation Hub").build(
            story, onFirstPage=footer, onLaterPages=footer)
    data = output.getvalue()
    if len(data) > payload["max_bytes"]:
        raise ValueError("The rebuilt PDF exceeds the download size limit.")
    return data


def generate(payload):
    upload = extract_pdf(base64.b64decode(payload["upload"], validate=True), payload["max_pages"], payload["max_characters"])
    reference = (extract_pdf(base64.b64decode(payload["reference"], validate=True), payload["max_pages"], payload["max_characters"])
                 if payload.get("reference") else payload["html"])
    original_upload, original_reference = upload, reference
    upload, reference, evidence = comparison_scope(upload, reference, payload["source_url"])
    if evidence["language_alignment"] == "needs_review":
        raise ValueError("Confirm the source language corresponding to the uploaded PDF before generating an updated PDF.")
    payload = {**payload, "scope_notes": evidence["scope_notes"],
               "source_current_to": original_reference.get("dates", {}).get("current_to")}
    upload, reference = normalize_wraps(upload, reference), normalize_wraps(reference, upload)
    if not upload["complete"] or not reference["complete"]:
        raise ValueError("Complete readable text is required to rebuild this document. Review the extraction coverage or download the official PDF.")
    actual, _, _ = tokens(upload)
    expected, _, _ = tokens(reference)
    if not actual or not expected:
        raise ValueError("The source has insufficient readable text to generate an updated PDF.")
    identity_reference = reference if evidence["language_alignment"] == "selected" else original_reference
    identity = check_identity(original_upload, identity_reference, actual, expected)
    if identity["document_identity"] != "match":
        raise ValueError("Confirm that the uploaded PDF and selected source are the same document before generating an updated PDF.")
    title = identity.get("identity_source_title") or reference.get("title") or "Updated document"
    data = render_pdf(reference, title, payload)
    return {"data": base64.b64encode(data).decode("ascii")}


def main():
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        from app.services.pdf_validation_limits import limit_memory
        payload = json.load(sys.stdin)
        limit_memory(payload["memory_mb"])
        result = generate(payload)
    except ValueError as exc:
        result = {"error": str(exc)}
    except Exception:
        result = {"error": "The updated PDF could not be generated within its resource limits. Download the official PDF instead."}
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
