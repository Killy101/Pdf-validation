"""Detect document columns and select an evidenced original-language scope."""
from collections import Counter
import re
from urllib.parse import urlsplit

from app.services.pdf_validation_language import language, select_html_language
from app.services.pdf_validation_text import tokens


def repair_definition_labels(text, runs):
    prefix = re.match(r"(?:[A-Z]\s*\n){2,8}", text)
    if not prefix:
        return text, False
    labels = prefix[0].split()
    if len(set(labels)) != len(labels):
        return text, False
    replacements = []
    for label in labels:
        positions = [(x, y) for x, y, value, size in runs if value.strip() == label]
        if len(positions) != 1:
            return text, False
        x, y = positions[0]
        definitions = [value.strip() for other_x, other_y, value, size in runs
            if 4 < other_x - x < 80 and abs(other_y - y) < 2
            and re.match(r"(?:is|means|represents|denotes)\b", value.strip())]
        if len(definitions) != 1 or text.count(definitions[0]) != 1:
            return text, False
        replacements.append((definitions[0], label + " " + definitions[0]))
    fixed = text[prefix.end():]
    for before, after in replacements:
        fixed = fixed.replace(before, after, 1)
    return fixed, True


def _column_text(runs, left, middle):
    parts, previous_y = [], None
    for x, y, text in runs:
        if (x < middle) != left:
            continue
        if previous_y is not None and abs(y - previous_y) > 8 and parts and not parts[-1].endswith("\n"):
            parts.append("\n")
        parts.append(text)
        previous_y = y
    return "".join(parts).strip()


def page_columns(runs, width, height):
    middle = width / 2
    body = [(x, y, text) for x, y, text, size in runs if 40 < y < height - 40 and text.strip()]
    content = [(x, y, text) for x, y, text, size in runs if 40 < y < height - 40 and text.strip()
               and not (y > height * 0.85 and size <= 7)]
    starts = Counter(round(x / 4) * 4 for x, _, text in body if middle + 4 < x < middle + width * 0.15)
    right_start, count = starts.most_common(1)[0] if starts else (0, 0)
    right_rows = {round(y / 3) for x, y, _ in body if abs(x - right_start) <= 5}
    left_rows = {round(y / 3) for x, y, _ in body if x < width * 0.25}
    parallel = count >= 6 and len(right_rows) >= 6 and len(left_rows & right_rows) >= 4
    return {"columns": 2 if parallel else 1 if len(left_rows) >= 6 else None,
            "left": _column_text(body, True, middle) if parallel else "",
            "right": _column_text(body, False, middle) if parallel else "",
            "left_body": _column_text(content, True, middle) if parallel else "",
            "right_body": _column_text(content, False, middle) if parallel else ""}


def document_layout(units):
    counts = Counter(unit.get("columns") for unit in units if unit.get("columns"))
    columns = counts.most_common(1)[0][0] if counts else None
    left = "\n".join(unit.get("left", "") for unit in units)
    right = "\n".join(unit.get("right", "") for unit in units)
    column_languages = [language(left), language(right)]
    parallel = counts[2] >= 1 and "unknown" not in column_languages and len(set(column_languages)) == 2
    languages = column_languages if parallel else [language("\n".join(unit["text"] for unit in units))]
    return {"columns": 2 if parallel else columns, "languages": languages, "parallel_bilingual": parallel,
            "column_languages": column_languages if counts[2] else []}


def comparison_scope(upload, reference, source_url):
    pdf_layout = upload.get("layout", {"columns": None, "languages": ["unknown"]})
    source_layout = reference.get("layout", {"columns": None, "languages": ["unknown"]})
    evidence = {"pdf_layout": pdf_layout, "source_layout": source_layout, "comparison_language": "all",
                "language_alignment": "all_text", "scope_notes": []}
    def review(note):
        actual = tokens(upload)[0]
        if actual and actual == tokens(reference)[0]:
            evidence["scope_notes"] = ["All extracted text matches without excluding a language column."]
        else:
            evidence.update(language_alignment="needs_review", scope_notes=[note])
        return upload, reference, evidence
    html_scope = select_html_language(upload, reference) if not reference.get("pages") else None
    if html_scope and html_scope["review"]:
        return review("The uploaded PDF could not be aligned reliably with the source's published language. Select the corresponding language URL or reference PDF.")
    if html_scope and html_scope["language"]:
        selected_language = html_scope["language"]
        evidence.update(comparison_language=selected_language, language_alignment="selected",
            scope_notes=[f"Compared original source text marked {selected_language} with the uploaded PDF. Other explicitly marked languages are outside this comparison; no translation is performed."])
        return upload, {**reference, "units": html_scope["units"]}, evidence
    target = pdf_layout["languages"][0] if len(pdf_layout["languages"]) == 1 else None
    if not source_layout.get("parallel_bilingual"):
        if target and pdf_layout.get("columns") != 2 and "unknown" in source_layout.get("column_languages", []):
            return review("The source has multiple columns with unconfirmed language alignment. Review the original source before comparing wording; no column was silently excluded.")
        source_language = source_layout["languages"][0] if len(source_layout["languages"]) == 1 else None
        if target and source_language and "unknown" not in (target, source_language) and target != source_language:
            return review("The PDF and source have different detected languages or scripts. Select the same published language before comparing wording.")
        return upload, reference, evidence
    if target is None and pdf_layout.get("parallel_bilingual") and pdf_layout["languages"] == source_layout["languages"]:
        return upload, reference, evidence
    if target not in source_layout["languages"]:
        return review("The source contains parallel language columns, but the PDF's matching language column could not be confirmed. No column was silently excluded.")
    side = "left" if source_layout["languages"].index(target) == 0 else "right"
    units = reference["units"]
    start = 0
    host = urlsplit(source_url).hostname or ""
    canadian = host == "justice.gc.ca" or host.endswith(".justice.gc.ca")
    canada_body = canadian and target in {"en", "fr"}
    if canada_body:
        start = next((index for index, unit in enumerate(units) if re.search(r"^(?:Registration|Enregistrement)\b",
            unit.get("left", "") + "\n" + unit.get("right", ""), re.M)), 0)
    selected = [{**unit, "text": unit.get(side + "_body", unit[side]) if canada_body else unit[side]}
                for unit in units[start:] if unit.get("columns") == 2]
    omitted = [unit for unit in units[start:] if unit.get("columns") != 2 and len(unit["text"].split()) >= 3]
    if not selected:
        evidence["scope_notes"].append("Parallel languages were detected, but reliable matching-column extraction was unavailable.")
        evidence["language_alignment"] = "needs_review"
        return upload, {**reference, "complete": False}, evidence
    other = source_layout["languages"][1 - source_layout["languages"].index(target)]
    names = {"en": "English", "fr": "French"}
    notes = [f"{names.get(target, target)} upload compared with the source's {names.get(target, target)} column. The parallel {names.get(other, other)} column is outside this comparison."]
    if start:
        notes.append(f"Source cover and contents pages 1-{start} are outside the regulation-body comparison.")
        notes.append("Small running source headers and current-to labels are excluded; dates are displayed separately.")
    if omitted:
        notes.append("Some source pages could not be assigned to the matching language column; coverage is incomplete.")
    def clean(document, selected_units):
        cleaned = []
        for unit in selected_units:
            lines = [line for line in unit["text"].splitlines() if not re.match(
                r"^(?:Current to\b|Regulations are current to\b|Table of Contents$|À jour au\b|Table des matières$)", line.strip(), re.I)]
            cleaned.append({**unit, "text": "\n".join(lines)})
        return {**document, "units": cleaned}
    reference = clean(reference, selected) if canada_body else {**reference, "units": selected}
    reference["complete"] = reference["complete"] and not omitted
    evidence.update(comparison_language=target, language_alignment="selected", scope_notes=notes)
    return clean(upload, upload["units"]) if canada_body else upload, reference, evidence
