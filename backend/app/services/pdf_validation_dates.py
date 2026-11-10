"""Extract dated document evidence without inferring when a file was downloaded."""
from datetime import date, datetime
import re

from app.services.pdf_validation_scraping import scrape_page


MONTHS = {name.casefold(): index for index, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}


def current_to(text):
    match = re.search(r"(?:current to)\s+(\d{4}-\d{2}-\d{2})", text, re.I)
    try:
        if match:
            return date.fromisoformat(match[1]).isoformat()
        match = re.search(r"current to\s+([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", text, re.I)
        if match:
            return date(int(match[3]), MONTHS[match[1].casefold()], int(match[2])).isoformat()
    except (ValueError, KeyError):
        pass
    return None


def pdf_dates(reader, text):
    result = {"current_to": current_to(text)}
    for field in ("creation_date", "modification_date"):
        try:
            value = getattr(reader.metadata, field, None)
            result[field] = value.isoformat() if isinstance(value, datetime) else None
        except (ValueError, TypeError):
            result[field] = None
    return result


def website_dates(snapshot):
    page = scrape_page(snapshot.data, snapshot.url, snapshot.content_type)
    for selector in ('#wb-dtmd time', 'time[property="dateModified"]', 'meta[name="dcterms.modified"], meta[property="dcterms.modified"]'):
        for node in page.css(selector):
            for value in (node.get_all_text(separator=" ", strip=True), node.attrib.get("datetime"), node.attrib.get("content")):
                if not value:
                    continue
                try:
                    return date.fromisoformat(value.strip("\ufeff \t\r\n")[:10]).isoformat()
                except (ValueError, TypeError):
                    pass
    return None
