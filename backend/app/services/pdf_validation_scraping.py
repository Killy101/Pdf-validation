"""Repair source HTML and discover statically declared PDF downloads with Scrapling."""
import json

from scrapling.parser import Selector

from reflink.url.evidence import _detect_html_encoding


def scrape_page(data: bytes, url: str, content_type: str) -> Selector:
    content = data.decode(_detect_html_encoding(data, content_type), errors="replace")
    return Selector(content.encode("utf-8"), url=url, adaptive=False, huge_tree=True)


def pdf_metadata(page: Selector):
    for node in page.css("[data-pdf-url], [data-zip-url], [data-download-url], [data-href], iframe[data-src], embed[data-src]"):
        attrs = node.attrib
        label = attrs.get("aria-label") or attrs.get("title") or node.get_all_text(separator=" ", strip=True) or "Download"
        mime = attrs.get("type", "").split(";", 1)[0].strip().casefold()
        declared = "zip" if mime in {"application/zip", "application/x-zip-compressed"} else mime == "application/pdf"
        for key in ("data-pdf-url", "data-zip-url", "data-download-url", "data-href", "data-src"):
            if attrs.get(key):
                yield attrs[key], label, "zip" if key == "data-zip-url" else declared or key == "data-pdf-url", node.tag in {"iframe", "embed"}
    for node in page.css("script[type]"):
        if node.attrib["type"].split(";", 1)[0].strip().casefold() != "application/ld+json":
            continue
        try:
            pending = [json.loads(node.text)]
        except (ValueError, RecursionError):
            continue
        while pending:
            item = pending.pop()
            if isinstance(item, list):
                pending.extend(reversed(item))
            elif isinstance(item, dict):
                value = item.get("contentUrl")
                mime = item.get("encodingFormat") or item.get("fileFormat")
                normalized = mime.split(";", 1)[0].strip().casefold() if isinstance(mime, str) else ""
                declared = "zip" if normalized in {"application/zip", "application/x-zip-compressed", "zip"} else normalized in {"application/pdf", "pdf"}
                if isinstance(value, str) and (not mime or declared):
                    label = item.get("name")
                    yield value, label if isinstance(label, str) else "Publication download", declared, False
                pending.extend(reversed(list(item.values())))
