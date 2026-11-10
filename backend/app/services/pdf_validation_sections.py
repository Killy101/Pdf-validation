"""Align declared source sections while retaining physical PDF page evidence."""
import re

from app.services.pdf_validation_navigation import section_key


def section_pairs(upload, reference):
    coverage = reference.get("source_coverage")
    if not coverage:
        return None
    keys = [unit.get("section_id") or section_key(unit.get("heading")) for unit in reference["units"]]
    families = [key.split(":")[0] for key in keys if key]
    if not families:
        return None
    family = "section" if "section" in families else families[0]
    groups, source_intro, current = {}, [], None
    for unit, key in zip(reference["units"], keys):
        if key and key.startswith(family + ":"):
            current = key
        if current:
            groups.setdefault(current, []).append(unit)
        else:
            source_intro.append(unit)
    pdf_groups, pdf_intro, current, ambiguous = {}, [], None, set()
    for unit in upload["units"]:
        for line in unit["text"].splitlines(keepends=True):
            key = section_key(line)
            if not key and family == "section":
                match = re.match(r"^\s*(\d+(?:\.\d+)*[A-Za-z]?)(?=\s|\()", line)
                key = "section:" + match[1].lower() if match else None
            if key and key.startswith(family + ":"):
                if key != current and key in pdf_groups:
                    ambiguous.add(key)
                current = key
            if current:
                segment = {**unit, "text": line}
                pdf_groups.setdefault(current, []).append(segment)
            elif line.strip():
                pdf_intro.append({**unit, "text": line})
    shared = (groups.keys() & pdf_groups.keys()) - ambiguous
    if not shared:
        return {"pairs": [], "complete": False, "notes": ["Source sections could not be aligned with numbered PDF sections; those sections were not checked."]} if not coverage["complete"] else None
    pairs = [({**upload, "units": pdf_intro}, {**reference, "units": source_intro})] if pdf_intro and source_intro else []
    for key, source_units in groups.items():
        if key not in shared:
            continue
        pairs.append(({**upload, "units": pdf_groups[key]}, {**reference, "units": source_units}))
    missing, extra = groups.keys() - shared, pdf_groups.keys() - shared
    notes = []
    intro_complete = bool(pdf_intro) == bool(source_intro)
    if coverage["complete"] and reference["complete"] and (missing or extra or not intro_complete):
        return None
    if not intro_complete:
        notes.append("Introductory text could not be mapped to both documents and was not checked.")
    if missing:
        notes.append("Source sections without a reliable PDF section mapping were not checked: " + ", ".join(sorted(missing)[:20]))
    if extra:
        notes.append("Uploaded sections without collected reference text were not checked: " + ", ".join(sorted(extra)[:20]))
    return {"pairs": pairs, "complete": not missing and not extra and intro_complete, "notes": notes,
        "numbered_count": len(shared)}
