"""Collect one selected document under shared page, depth, byte, and time limits."""
from collections import deque
from hashlib import sha256
import json
import time
from urllib.parse import urldefrag, urlsplit

from app.config import settings
from app.services.pdf_validation_access import ensure_source_access
from app.services.pdf_validation_navigation import CHAPTER, compatible, eligible_link, navigation, section_key
from app.services.pdf_validation_source import extract_html


def collection_hash(documents):
    return sha256(json.dumps(documents, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def collect_document(snapshot, hosts, fetch, render=None):
    from app.services.pdf_validation_browser import render_document
    render = render or render_document
    deadline = time.monotonic() + settings.PDF_VALIDATION_TIMEOUT_SECONDS
    root_url = snapshot.url
    initial, references = extract_html(snapshot, collection=True)
    root_nav = navigation(snapshot)
    identity, title = root_nav["identity"], initial["title"]
    pages, documents, items, units, seen_units = {}, [], {}, [], set()
    queue = deque([({"url": root_url, "label": title or "Submitted document", "kind": "root"}, 0)])
    scheduled = {root_url}
    size = browser_pages = 0
    declared = bool(root_nav["links"] or root_nav["complete"])
    notes, visual, root_required, truncated, browser_incomplete = [], False, False, False, False

    def append_units(content):
        for unit in content:
            if unit["text"] == title and any(previous["text"] == title for previous in units):
                continue
            key = (unit.get("url"), unit["text"], unit.get("heading"))
            if key not in seen_units:
                seen_units.add(key)
                units.append({**unit, "section_id": section_key(unit.get("heading")) or section_key(urldefrag(unit.get("url", ""))[1])})

    def browser_fetch(url, allowed, max_bytes, timeout):
        nonlocal size
        available = settings.PDF_VALIDATION_CRAWL_MAX_BYTES - size
        if available <= 0:
            raise ValueError("Combined browser and source byte limit reached.")
        resource = fetch(url, allowed, min(max_bytes, available), min(timeout, max(0.001, deadline - time.monotonic())))
        size += len(resource.data)
        if size > settings.PDF_VALIDATION_CRAWL_MAX_BYTES:
            raise ValueError("Combined browser and source byte limit reached.")
        return resource

    while queue:
        item, depth = queue.popleft()
        target, fragment = urldefrag(item["url"])
        if item["url"] in items:
            continue
        entry = {"url": item["url"], "label": item["label"], "status": "not_checked", "reason": None}
        items[item["url"]] = entry
        if time.monotonic() >= deadline or depth > settings.PDF_VALIDATION_CRAWL_MAX_DEPTH:
            entry["reason"] = "Collection time or depth limit reached."
            continue
        if target not in pages and len(pages) >= settings.PDF_VALIDATION_CRAWL_MAX_PAGES:
            entry["reason"] = "Source page limit reached."
            continue
        try:
            if target in pages:
                body, nav = pages[target]
            else:
                current = snapshot if target == root_url else fetch(target, hosts, settings.PDF_VALIDATION_MAX_HTML_BYTES,
                    max(0.001, deadline - time.monotonic()))
                ensure_source_access(current)
                if current.kind != "html":
                    raise ValueError("This chapter did not return an HTML document. Select its official PDF directly.")
                size += len(current.data)
                if size > settings.PDF_VALIDATION_CRAWL_MAX_BYTES:
                    raise ValueError("Combined source byte limit reached.")
                body, page_references = extract_html(current, collection=True)
                nav = navigation(current)
                if not compatible(identity, nav["identity"]):
                    raise ValueError("Document identity, language, or edition differs from the selected source.")
                if depth and title and body["title"] and title.casefold() != body["title"].casefold():
                    if not CHAPTER.match(body["title"]) and not CHAPTER.match(item["label"]):
                        raise ValueError("The linked page has a different document title; select its direct URL to compare it separately.")
                references = list({ref["url"]: ref for ref in references + page_references}.values())[:20]
                rendered = None
                browser_rules = settings.PDF_VALIDATION_BROWSER_RULES.get(urlsplit(current.url).hostname or "", {})
                needs_browser = nav["interactive"] or bool(browser_rules and not body["complete"]) or (
                    not body["units"] and not (nav["complete"] or nav["links"]))
                if needs_browser and settings.PDF_VALIDATION_BROWSER_ENABLED:
                    if browser_pages >= settings.PDF_VALIDATION_BROWSER_MAX_PAGES:
                        raise ValueError("Browser page limit reached.")
                    browser_pages += 1
                    rendered, browser_complete, browser_notes = render(current, hosts, browser_fetch,
                        max(0.001, deadline - time.monotonic()))
                    size += len(rendered.data)
                    if size > settings.PDF_VALIDATION_CRAWL_MAX_BYTES:
                        raise ValueError("Combined rendered source byte limit reached.")
                    ensure_source_access(rendered)
                    body, rendered_references = extract_html(rendered, collection=True)
                    references = list({ref["url"]: ref for ref in references + rendered_references}.values())[:20]
                    if target == root_url and not initial["units"] and body["title"]:
                        title = body["title"]
                    body["complete"] = body["complete"] and browser_complete
                    browser_incomplete = browser_incomplete or not browser_complete
                    nav = navigation(rendered)
                    notes.extend(browser_notes)
                pages[target] = (body, nav)
                documents.append({"url": target, "sha256": sha256(current.data).hexdigest(),
                    "content_sha256": sha256(json.dumps(body["units"], sort_keys=True).encode()).hexdigest()})
            if fragment:
                selected = [unit for unit in body["units"] if urldefrag(unit.get("url", ""))[1] == fragment]
                if not selected:
                    raise ValueError("The declared source section was not present in the retrieved page.")
                append_units(selected)
            else:
                if not nav["complete"]:
                    append_units(body["units"])
                    if target == root_url:
                        root_required = sum(len(unit["text"]) for unit in body["units"]
                            if unit["text"] != title and not urldefrag(unit.get("url", ""))[1]) >= 80
            entry["status"] = "retrieved" if body["units"] else "unavailable"
            if not body["complete"]:
                entry["reason"] = "Interactive or incomplete document content requires review."
            visual = visual or body.get("requires_visual_review", False)
            outgoing = nav["complete"] or nav["links"]
            if outgoing:
                declared = True
                for child in outgoing:
                    if child["url"] in scheduled:
                        continue
                    if len(scheduled) > settings.PDF_VALIDATION_CRAWL_MAX_SECTIONS:
                        notes.append("Declared section limit reached; additional sections were not checked.")
                        truncated = True
                        break
                    scheduled.add(child["url"])
                    if eligible_link(child, root_url, identity, hosts):
                        queue.append((child, depth + (child["kind"] != "continuation" and urldefrag(child["url"])[0] != target)))
                    elif child.get("language") not in (None, "", identity.get("language")):
                        notes.append("Links to another published language were excluded.")
                    else:
                        items.setdefault(child["url"], {"url": child["url"], "label": child["label"],
                            "status": "not_checked", "reason": "Link is outside the selected document or approved source boundary."})
        except (ValueError, OSError, TimeoutError) as exc:
            entry.update(status="unavailable", reason=str(exc)[:300])
    meaningful = [entry for entry in items.values() if entry["url"] != root_url or not declared or root_required]
    if not meaningful:
        meaningful = list(items.values())
    complete = bool(units) and not truncated and not browser_incomplete and all(
        entry["status"] == "retrieved" and not entry["reason"] for entry in meaningful)
    coverage = {"method": "browser" if browser_pages else "linked_sections" if declared else "submitted_page",
        "expected_sections": None if truncated else len(meaningful), "retrieved_sections": sum(entry["status"] == "retrieved" for entry in meaningful),
        "pages_retrieved": len(pages), "complete": complete, "sections": meaningful,
        "notes": list(dict.fromkeys(notes))}
    document = {"title": title or next((body["title"] for body, _ in pages.values() if body["title"]), None),
        "units": units, "complete": complete, "requires_visual_review": visual,
        "source_coverage": coverage, "source_documents": documents, "references": references}
    document["source_sha256"] = (sha256(snapshot.data).hexdigest() if not declared and not browser_pages
                                 else collection_hash(documents))
    if units and document["title"] and not any(unit["text"] == document["title"] for unit in units):
        document["units"].insert(0, {"text": document["title"], "heading": document["title"], "url": root_url})
    if sum(len(unit["text"]) for unit in document["units"]) > settings.PDF_VALIDATION_MAX_CHARACTERS:
        raise ValueError("Collected document text exceeds the configured comparison limit.")
    return document
