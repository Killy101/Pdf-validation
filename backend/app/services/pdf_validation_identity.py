"""Conservative document identity checks using visible titles and text evidence."""
import re
import unicodedata


GENERIC_TITLE_WORDS = {"act", "regulation", "regulations", "rules", "the", "of", "and", "for", "a", "an", "document", "contents", "code", "order", "law"}


def _normalize(value):
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"\b(?:19|20)\d{2}\b|\b(?:edition|version|revised|updated)\s*\d*\b", " ", value)
    return " ".join(re.findall(r"\w+", value))


def _visible_titles(document):
    lines = [line.strip() for unit in document["units"][:3] for line in unit["text"].splitlines() if line.strip()][:80]
    boilerplate = r"^(?:current to\b|\u00e0 jour au\b|published by\b|publi\u00e9 par\b|https?\b|page\s*\d|\d+[\s./-]*$|section\s+\d|chapter\s+\d|article\s+\d|registration\b|enregistrement\b|SOR[/\s-]|DORS[/\s-])"
    lines = [line for line in lines if 6 <= len(line) <= 200
             and not re.match(boilerplate, line, re.I)
             and line.casefold() not in {"canada", "consolidation", "codification", "official status", "table of contents", "table of provisions"}]
    title = document.get("title")
    visible = lines + [left + " " + right for left, right in zip(lines, lines[1:]) if len(left + right) < 199]
    verified = title if title and any(_normalize(title) == _normalize(line) for line in visible) else None
    candidates = [line for line in lines if len(line.split()) <= 16 and not line.endswith((".", ":", ";"))
                  and re.search(r"\b(?:act|regulations?|rules?|code|order|law|ordinance|r\u00e8glement|loi)\b", line, re.I)]
    fallback = next((line for line in lines if len(line.split()) <= 16 and not line.endswith((".", ":", ";"))), None)
    primary = verified or (candidates[0] if candidates else fallback)
    return primary, [item for item in [primary, *candidates] if item]


def check_identity(upload, reference, actual, expected):
    pdf_title, pdf_titles = _visible_titles(upload)
    source_title, _ = _visible_titles(reference)
    if actual == expected and actual:
        return {"document_identity": "match", "identity_pdf_title": pdf_title, "identity_source_title": source_title,
                "identity_summary": "The extracted document text identifies the same content."}
    actual_words = {word for word in actual if len(word) >= 4 and word.isalpha()}
    expected_words = {word for word in expected if len(word) >= 4 and word.isalpha()}
    shared = len(actual_words & expected_words)
    if pdf_title and source_title:
        left, right = _normalize(pdf_title), _normalize(source_title)
        if left == right and set(left.split()) - GENERIC_TITLE_WORDS:
            return {"document_identity": "match", "identity_pdf_title": pdf_title, "identity_source_title": source_title,
                    "identity_summary": "The visible titles identify the same document; edition changes are reported separately."}
        source_title_visible = right in {_normalize(title) for title in pdf_titles} and bool(set(right.split()) - GENERIC_TITLE_WORDS)
        if (source_title_visible and min(len(actual_words), len(expected_words)) >= 8
                and shared / min(len(actual_words), len(expected_words)) >= 0.35):
            return {"document_identity": "match",
                    "identity_pdf_title": next(title for title in pdf_titles if _normalize(title) == right),
                    "identity_source_title": source_title,
                    "identity_summary": "A shared visible document title and overlapping content identify the same document; edition changes are reported separately."}
        left_words, right_words = set(left.split()), set(right.split())
        titles_differ = bool(left_words - GENERIC_TITLE_WORDS and right_words - GENERIC_TITLE_WORDS) and not (left_words - GENERIC_TITLE_WORDS) & (right_words - GENERIC_TITLE_WORDS)
        enough_text = min(len(actual), len(expected)) >= 20 and min(len(actual_words), len(expected_words)) >= 8
        little_shared = shared / max(1, min(len(actual_words), len(expected_words))) <= 0.12
        if (upload["complete"] and reference["complete"] and titles_differ and enough_text and little_shared):
            return {"document_identity": "mismatch", "identity_summary": "The PDF and selected URL appear to refer to different documents.",
                    "identity_pdf_title": pdf_title, "identity_source_title": source_title}
    return {"document_identity": "needs_review",
            "identity_pdf_title": pdf_title, "identity_source_title": source_title,
            "identity_summary": "The visible document titles could not be matched reliably. Confirm the document name and edition; the content findings remain available below."}
