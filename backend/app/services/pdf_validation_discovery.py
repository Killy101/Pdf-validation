"""Find the uploaded document inside a website, starting from its Reference URL.

A Reference URL is a landing page; the published PDF can sit several navigation levels below it. Discovery reads
the uploaded PDF's title area, ranks every link it finds against it, follows the most relevant pages first (plain
HTTP, or a browser only when the page builds its menus with JavaScript), and accepts a PDF only after its first
pages are confirmed to be the same document.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import heapq
import logging
import re
import time
from urllib.error import HTTPError
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

from app.config import settings
from app.logging_setup import VALIDATION, clean, log_event, safe_url
from app.services.pdf_validation_access import SourceAccessError, ensure_source_access, http_access_error
from app.services.pdf_validation_scraping import pdf_metadata, scrape_page
from app.services.pdf_validation_search import extract_text, flatten
from reflink.url.targets import valid_url_target

FAMILIES = ("title|subtitle|chapter|subchapter|part|article|section|act|regulation|rule|book|volume|schedule"
            "|division|appendix|annex|code")
DESIGNATION = re.compile(rf"(?<![a-z])({FAMILIES})[\s_:.#-]*(\d+(?:-?[a-z](?![a-z]))?(?:\.\d+)*)(?![a-z0-9])", re.I)
WORD = re.compile(r"[^\W\d_]{3,}", re.U)
STOP = set("""the and for with from that this these those are was were been has have had not but all any each
other such into onto upon under over than then also its their there here which who whom whose what when where
generated page pages revised statutes statute laws law code current version edition updated print printed copy
pdf html doc docx word file download view home contents table index list section chapter title part article
subtitle subchapter act regulation regulations rule rules book volume schedule division appendix annex""".split())
NAVIGATION_ONLY = re.compile(r"^(?:home|contact(?: us)?|privacy(?: policy)?|accessibility|log ?in|sign ?in|sign ?up|"
                             r"register|search|help|faq|about(?: us)?|site ?map|feedback|careers|jobs|news|events|"
                             r"terms(?: of use)?|disclaimer|cookies?|skip to (?:main )?content|back to top|menu|"
                             r"facebook|twitter|x|linkedin|youtube|instagram|rss|subscribe|print|share|email)$", re.I)
OTHER_FORMATS = re.compile(r"\.(?:docx?|rtf|odt|xlsx?|csv|pptx?|txt|xml|json|rss|atom|jpe?g|png|gif|svg|webp|mp[34]|"
                           r"avi|mov|wav|ico|css|js|epub|mobi)$", re.I)
JS_PAGE = 'script[src], #app, #root, [ng-app], [data-reactroot], noscript'
STRONG = 20
VERIFIED = 0.5
POSSIBLE = 0.4


@dataclass(order=True)
class _Visit:
    priority: float
    order: int
    url: str = field(compare=False)
    label: str = field(compare=False)
    depth: int = field(compare=False)
    path: list = field(compare=False)
    score: float = field(compare=False)


def _designations(text: str) -> list[tuple[str, str]]:
    return [(family.casefold(), number.casefold()) for family, number in DESIGNATION.findall(text or "")]


def _words(text: str) -> set[str]:
    return {word.casefold() for word in WORD.findall(text or "")} - STOP


def document_hints(upload: bytes, filename: str = "") -> dict:
    """What the uploaded PDF calls itself: its leading designation (e.g. Title 4) and title words."""
    extracted = extract_text(upload, first_pages=3)
    pages = extracted["pages"]
    lines = [line.strip() for line in (pages[0] if pages else "").splitlines() if line.strip()][:12]
    # The visible heading names the document; metadata titles are often stale or tool-generated.
    found = _designations("\n".join(lines)) + _designations(extracted.get("title") or "")
    primary = found[0] if found else None
    capitals = {word.casefold() for line in lines for word in WORD.findall(line) if word.isupper()} - STOP
    keywords = capitals or _words("\n".join([extracted.get("title") or "", *lines[:3]]))
    body = flatten(" ".join(pages))
    return {"primary": primary, "designations": sorted(set(found)), "keywords": sorted(keywords)[:25],
            "title": (extracted.get("title") or " ".join(lines[:2]))[:200], "filename": filename[:200],
            "tokens": _token_profile(body), "page_count": extracted.get("page_count")}


def _token_profile(text: str, limit: int = 600) -> list[str]:
    tokens, seen = [], set()
    for word in WORD.findall(text.casefold()):
        if word not in seen and word not in STOP:
            seen.add(word)
            tokens.append(word)
            if len(tokens) >= limit:
                break
    return tokens


def link_score(label: str, url: str, hints: dict, document: bool) -> float:
    """Relevance of a link to the uploaded document; negative means it names a different document."""
    path = unquote(urlsplit(url).path)
    text = f"{label} {path}"
    score = 0.0
    found = set(_designations(label)) | set(_designations(path.replace("/", " ")))
    primary = hints.get("primary")
    if primary:
        if primary in found:
            score += STRONG
        elif any(family == primary[0] and number != primary[1] for family, number in found):
            score -= STRONG
    secondary = set(map(tuple, hints.get("designations", []))) - ({primary} if primary else set())
    if found & secondary:
        score += 4
    score += 4 * min(3, len(_words(text) & set(hints.get("keywords", []))))
    if document:
        score += 3
    if re.search(r"\bpdf\b", label, re.I):
        score += 1
    return score


def _kind(url: str, label: str, mime: str = "") -> str:
    path = unquote(urlsplit(url).path)
    if mime == "application/pdf" or re.search(r"\.pdf$", path, re.I) or path.rstrip("/").casefold().endswith("/pdf"):
        return "pdf"
    if mime in {"application/zip", "application/x-zip-compressed"} or re.search(r"\.zip$", path, re.I):
        return "zip"
    if OTHER_FORMATS.search(path):
        return "other"
    if re.search(r"\bpdf\b", label, re.I) and not re.search(r"\b(?:word|docx?|rtf|html)\b", label, re.I):
        return "pdf"
    return "html"


def page_links(snapshot) -> tuple[list[dict], object]:
    """Every navigable target on a page: plain links, menus hidden until hover, dropdown selects, buttons, frames."""
    page = scrape_page(snapshot.data, snapshot.url, snapshot.content_type)
    base = snapshot.url
    bases = page.css("base[href]")
    if bases:
        base = urljoin(base, bases[0].attrib["href"])
    found = []

    def add(value, label, source, mime=""):
        value = (value or "").strip()
        if not value or value.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            return
        target = urldefrag(urljoin(base, value))[0]
        if valid_url_target(target):
            label = " ".join((label or "").split())[:200]
            found.append({"url": target, "label": label or unquote(urlsplit(target).path.rsplit("/", 1)[-1]) or target,
                          "source": source, "kind": _kind(target, label, mime.split(";", 1)[0].strip().casefold())})

    for node in page.css("a[href], area[href]"):
        label = (node.get_all_text(separator=" ", strip=True) or node.attrib.get("aria-label") or node.attrib.get("title")
                 or " ".join(image.attrib.get("alt", "") for image in node.css("img[alt]")))
        hidden = bool(node.xpath('ancestor-or-self::*[@hidden or @aria-hidden="true" or contains(@style, "display:none") or contains(@style, "display: none")]'))
        menu = bool(node.xpath('ancestor::*[self::nav or @role="menu" or @role="menubar" or contains(@class, "menu") or contains(@class, "dropdown") or contains(@class, "nav")]'))
        add(node.attrib.get("href"), label, "hidden_menu" if hidden and menu else "menu" if menu else "link", node.attrib.get("type", ""))
    for node in page.css("select option[value]"):
        value = node.attrib["value"]
        if "/" in value or re.search(r"\.(?:s?html?|php|aspx?|pdf)\b", value, re.I):
            add(value, node.get_all_text(separator=" ", strip=True), "dropdown")
    for node in page.css("[data-href], [data-url], [data-link], [data-target-url]"):
        for key in ("data-href", "data-url", "data-link", "data-target-url"):
            if node.attrib.get(key) and not node.attrib[key].startswith("#"):
                add(node.attrib[key], node.get_all_text(separator=" ", strip=True) or node.attrib.get("aria-label", ""), "button")
    for node in page.css("[onclick]"):
        match = re.search(r"""(?:location(?:\.href)?\s*=|window\.open\(|location\.assign\()\s*['"]([^'"]+)['"]""", node.attrib["onclick"])
        if match:
            add(match[1], node.get_all_text(separator=" ", strip=True) or node.attrib.get("aria-label", ""), "button")
    for node in page.css("iframe[src], embed[src], object[data]"):
        add(node.attrib.get("src") or node.attrib.get("data"), node.attrib.get("title") or "Embedded document", "frame", node.attrib.get("type", ""))
    for node in page.css('link[rel="next"][href], a[rel="next"][href]'):
        add(node.attrib["href"], "Next page", "pagination")
    for value, label, declared, _viewer in pdf_metadata(page):
        add(value, label, "metadata", "application/zip" if declared == "zip" else "application/pdf" if declared is True else "")
    unique = {}
    for item in found:
        previous = unique.get(item["url"])
        if previous is None or (len(item["label"]) > len(previous["label"]) and previous["source"] != "link"):
            unique[item["url"]] = item
    return list(unique.values()), page


def needs_rendering(page, links: list[dict], root_host: str) -> bool:
    """True when the navigation is built by JavaScript, so plain HTTP cannot see the menus."""
    internal = [item for item in links if (urlsplit(item["url"]).hostname or "").lower() == root_host]
    if len(internal) < 3:
        return bool(page.css(JS_PAGE))
    for node in page.css('[aria-controls][aria-expanded="false"], [aria-haspopup][aria-controls]'):
        target = node.attrib.get("aria-controls", "")
        if target and not page.css('[id="' + target.replace('"', "") + '"]'):
            return True
    return False


def looks_like_landing_page(snapshot) -> bool:
    """A page listing several numbered documents (titles, chapters, acts) rather than being one."""
    try:
        links, _ = page_links(snapshot)
    except Exception:
        return False
    return len({_designations(item["label"])[0] for item in links if _designations(item["label"])}) >= 5


def similarity(hints: dict, profile: list[str], designations: list[tuple[str, str]]) -> float:
    """Share of the shorter document's opening vocabulary found in the other; 0 when they name different documents."""
    primary = hints.get("primary")
    leading = designations[0] if designations else None
    if primary and leading and leading[0] == primary[0] and leading[1] != primary[1]:
        return 0.0
    ours, theirs = set(hints.get("tokens", [])), set(profile)
    if not ours or not theirs:
        return 0.0
    return len(ours & theirs) / min(len(ours), len(theirs))


def _status_for(exc) -> tuple[str, str]:
    if isinstance(exc, HTTPError):
        issue = http_access_error(exc)
        return ("unavailable" if issue.issue == "unavailable" else "inaccessible"), str(issue)
    if isinstance(exc, SourceAccessError):
        return ("unavailable" if exc.issue == "unavailable" else "inaccessible"), str(exc)
    if isinstance(exc, TimeoutError):
        return "inaccessible", "The page did not respond within the retrieval limit."
    if isinstance(exc, OSError):
        return "inaccessible", "The website could not be reached."
    return "unavailable", clean(exc, 300)


def discover_reference(upload: bytes, filename: str, snapshot, hosts: tuple[str, ...], fetch, render=None, hints=None):
    """Bounded best-first search from a landing page for the PDF that is the uploaded document."""
    started = time.monotonic()
    deadline = started + settings.PDF_VALIDATION_TIMEOUT_SECONDS
    hints = hints or document_hints(upload, filename)
    root_host = (urlsplit(snapshot.url).hostname or "").lower()
    allowed = {host.lower() for host in hosts} | {root_host}
    upload_sha = sha256(upload).hexdigest()
    log_event(VALIDATION, logging.INFO, "discovery.reference.started", start=safe_url(snapshot.url),
              identity=hints.get("primary") and " ".join(hints["primary"]), keywords=",".join(hints.get("keywords", [])[:8]))
    items, notes, queue, order = {}, [], [], 0
    pages_visited = browser_pages = bytes_read = 0
    candidates, queued = {}, {}

    def remaining():
        return max(0.001, deadline - time.monotonic())

    def on_site(url):
        host = (urlsplit(url).hostname or "").lower()
        return any(host == value or host.endswith("." + value) for value in allowed)

    def record(url, label, kind, status, reason=None, score=None, depth=None, path=None):
        entry = items.get(url)
        rank = ["visited", "not_relevant", "needs_verification", "unavailable", "inaccessible", "rejected", "verified", "selected"]
        if entry and rank.index(entry["status"]) > rank.index(status) and status not in {"unavailable", "inaccessible"}:
            return entry
        entry = {"url": url, "label": label[:200], "kind": kind, "status": status, "reason": reason,
                 "score": None if score is None else round(score, 1), "depth": depth,
                 "path": path if path is not None else (entry or {}).get("path", [])}
        items[url] = entry
        return entry

    def schedule(link, depth, path, parent_score):
        nonlocal order
        url, label, kind = link["url"], link["label"], link["kind"]
        if url in items or url in candidates or url in queued:
            return
        if not on_site(url):
            record(url, label, kind, "not_relevant", "Outside the reference website.", depth=depth)
            return
        if kind == "other":
            record(url, label, kind, "not_relevant", "Not a PDF or web page (another file format).", depth=depth)
            return
        score = link_score(label, url, hints, kind in {"pdf", "zip"})
        step = path + [{"url": url, "label": label[:200]}]
        if kind in {"pdf", "zip"}:
            candidates[url] = {"url": url, "label": label, "kind": kind, "score": score, "depth": depth, "path": step}
            log_event(VALIDATION, logging.INFO, "discovery.candidate", url=safe_url(url), label=clean(label, 120),
                      kind=kind, score=score, depth=depth)
            return
        if score < 0:
            record(url, label, kind, "not_relevant", "Names a different document than the uploaded PDF.", score, depth, step)
            return
        if NAVIGATION_ONLY.match(label.strip()) and score <= 0:
            record(url, label, kind, "not_relevant", "Site navigation, not a document link.", score, depth, step)
            return
        if depth > settings.PDF_VALIDATION_DISCOVERY_MAX_DEPTH:
            record(url, label, kind, "needs_verification", "Deeper than the navigation depth limit.", score, depth, step)
            return
        # Pagination keeps its parent's priority so long lists are read in order.
        priority = parent_score if link["source"] == "pagination" else score
        order += 1
        queued[url] = _Visit(-priority, order, url, label, depth, step, score)
        heapq.heappush(queue, queued[url])

    def visit(page_snapshot, depth, path, score):
        nonlocal pages_visited, browser_pages, bytes_read
        pages_visited += 1
        links, page = page_links(page_snapshot)
        method = "http"
        if (settings.PDF_VALIDATION_BROWSER_ENABLED and browser_pages < settings.PDF_VALIDATION_BROWSER_MAX_PAGES
                and needs_rendering(page, links, root_host)):
            try:
                browser_pages += 1
                rendered = (render or _render)(page_snapshot.url, tuple(sorted(allowed)), remaining())
                bytes_read += len(rendered.data)
                rendered_links, _ = page_links(rendered)
                known = {item["url"] for item in links}
                links += [item for item in rendered_links if item["url"] not in known]
                method = "browser"
            except Exception as exc:  # the static links are still usable
                notes.append("A page's interactive menus could not be opened in the browser; only its static links were checked.")
                log_event(VALIDATION, logging.WARNING, "discovery.browser_failed", url=safe_url(page_snapshot.url), error=type(exc).__name__)
        log_event(VALIDATION, logging.INFO, "discovery.page", url=safe_url(page_snapshot.url), depth=depth, method=method,
                  links=len(links), hidden_menu_links=sum(item["source"] == "hidden_menu" for item in links),
                  dropdown_links=sum(item["source"] == "dropdown" for item in links))
        for link in links:
            schedule(link, depth + 1, path, score)

    def verify(candidate):
        """Download a candidate and compare its first pages with the upload; returns the snapshot when it matches."""
        nonlocal bytes_read
        url = candidate["url"]
        try:
            if bytes_read >= settings.PDF_VALIDATION_CRAWL_MAX_BYTES * 4:
                raise ValueError("The discovery download limit was reached.")
            document = fetch(url, tuple(sorted(allowed)), settings.PDF_VALIDATION_MAX_BYTES, remaining())
            bytes_read += len(document.data)
            ensure_source_access(document)
        except Exception as exc:
            status, reason = _status_for(exc)
            record(url, candidate["label"], candidate["kind"], status, reason, candidate["score"], candidate["depth"], candidate["path"])
            log_event(VALIDATION, logging.WARNING, "discovery.verify", url=safe_url(url), status=status, reason=clean(reason, 200))
            return None
        if document.kind != "pdf":
            reason = "The link returned a ZIP archive; enter it as a Content URI to choose a member." if document.kind == "zip" else "The link did not return a PDF."
            record(url, candidate["label"], document.kind if document.kind in {"zip", "html"} else "pdf", "needs_verification" if document.kind == "zip" else "not_relevant",
                   reason, candidate["score"], candidate["depth"], candidate["path"])
            return None
        if sha256(document.data).hexdigest() == upload_sha:
            value = 1.0
        else:
            try:
                opening = extract_text(document.data, first_pages=3)
            except ValueError as exc:
                record(url, candidate["label"], "pdf", "needs_verification", f"Its text could not be read: {exc}",
                       candidate["score"], candidate["depth"], candidate["path"])
                return None
            first = "\n".join([opening.get("title") or "", *[line for line in (opening["pages"][0] if opening["pages"] else "").splitlines()[:12]]])
            value = similarity(hints, _token_profile(flatten(" ".join(opening["pages"]))), _designations(first))
        candidate["similarity"] = round(value, 2)
        log_event(VALIDATION, logging.INFO, "discovery.verify", url=safe_url(url), similarity=round(value, 2),
                  score=candidate["score"], bytes=len(document.data))
        if value >= VERIFIED:
            record(url, candidate["label"], "pdf", "verified", f"Opening pages match the uploaded PDF ({round(value * 100)}% shared wording).",
                   candidate["score"], candidate["depth"], candidate["path"])
            return document
        status = "needs_verification" if value >= POSSIBLE else "rejected"
        record(url, candidate["label"], "pdf", status,
               f"Opening pages share {round(value * 100)}% of their wording with the uploaded PDF." + (" Review it manually." if status == "needs_verification" else " This is a different document."),
               candidate["score"], candidate["depth"], candidate["path"])
        return None

    start_path = [{"url": snapshot.url, "label": "Reference URL"}]
    items[snapshot.url] = {"url": snapshot.url, "label": "Reference URL", "kind": "html", "status": "visited",
                           "reason": None, "score": None, "depth": 0, "path": start_path}
    visit(snapshot, 0, start_path, 0)
    tried, selected, document = set(), None, None
    while time.monotonic() < deadline:
        # Verify the best untried candidates once nothing queued looks more promising than them.
        best = sorted((item for item in candidates.values() if item["url"] not in tried and item["score"] >= 0),
                      key=lambda item: (-item["score"], item["depth"]))
        frontier = -queue[0].priority if queue else None
        budget = settings.PDF_VALIDATION_DISCOVERY_VERIFY - len(tried)
        if best and budget > 0 and (frontier is None or best[0]["score"] >= frontier or best[0]["score"] >= STRONG):
            for candidate in best[:min(3, budget)]:
                tried.add(candidate["url"])
                document = verify(candidate)
                if document:
                    selected = candidate
                    break
            if selected:
                break
            continue
        if budget <= 0:
            notes.append(f"Stopped after checking {len(tried)} candidate PDFs (verification limit).")
            break
        if not queue:
            break
        if pages_visited >= settings.PDF_VALIDATION_DISCOVERY_MAX_PAGES:
            notes.append(f"Stopped after opening {pages_visited} pages (discovery page limit).")
            break
        current = heapq.heappop(queue)
        del queued[current.url]
        try:
            page_snapshot = fetch(current.url, tuple(sorted(allowed)), settings.PDF_VALIDATION_MAX_HTML_BYTES, remaining())
            bytes_read += len(page_snapshot.data)
            ensure_source_access(page_snapshot)
        except Exception as exc:
            status, reason = _status_for(exc)
            record(current.url, current.label, "html", status, reason, current.score, current.depth, current.path)
            log_event(VALIDATION, logging.WARNING, "discovery.page_failed", url=safe_url(current.url), status=status, reason=clean(reason, 200))
            continue
        if page_snapshot.url != current.url and page_snapshot.url in items:
            record(current.url, current.label, "html", "not_relevant", "Redirects to a page that was already checked.",
                   current.score, current.depth, current.path)
            continue
        if page_snapshot.kind in {"pdf", "zip"}:
            candidates[current.url] = {"url": current.url, "label": current.label, "kind": page_snapshot.kind,
                                       "score": current.score + 3, "depth": current.depth, "path": current.path}
            continue
        if page_snapshot.kind != "html":
            record(current.url, current.label, "html", "not_relevant", "The link did not return a web page or PDF.",
                   current.score, current.depth, current.path)
            continue
        record(current.url, current.label, "html", "visited", None, current.score, current.depth, current.path)
        visit(page_snapshot, current.depth, current.path, current.score)
    else:
        notes.append("Discovery reached its time limit.")

    for url, candidate in candidates.items():
        if url not in items:
            status = "not_relevant" if candidate["score"] < 0 else "needs_verification"
            reason = ("Names a different document than the uploaded PDF." if status == "not_relevant"
                      else "Found but not downloaded; a more relevant document was checked first." if selected
                      else "Found but not downloaded within the discovery limits.")
            record(url, candidate["label"], candidate["kind"], status, reason, candidate["score"], candidate["depth"], candidate["path"])
    for visit_ in queued.values():
        record(visit_.url, visit_.label, "html", "needs_verification",
               "Not opened; the document was found first." if selected else "Not opened within the discovery limits.",
               visit_.score, visit_.depth, visit_.path)
    if selected:
        record(selected["url"], selected["label"], "pdf", "selected", items[selected["url"]]["reason"],
               selected["score"], selected["depth"], selected["path"])
        summary = f"Found “{selected['label']}” {len(selected['path']) - 1} navigation step(s) from the Reference URL and confirmed it is the uploaded document."
        status = "found"
    else:
        possible = [item for item in items.values() if item["status"] == "needs_verification" and item["kind"] == "pdf" and item.get("score", 0) >= 0]
        checked = sum(1 for item in items.values() if item["kind"] == "pdf")
        identity = " ".join(hints["primary"]).title() if hints.get("primary") else "the uploaded document"
        summary = (f"No PDF matching {identity} was found from this Reference URL. Opened {pages_visited} page(s) and checked {checked} PDF link(s)."
                   + (" Some PDFs could not be confirmed automatically; review them below or enter the document's Content URI." if possible
                      else " Enter the document's direct Content URI, or a Reference URL closer to the document."))
        status = "needs_review" if possible else "not_found"
    trail = {"start_url": snapshot.url, "status": status, "summary": summary,
             "selected_url": selected["url"] if selected else None, "selected_label": selected["label"] if selected else None,
             "path": selected["path"] if selected else [], "pages_visited": pages_visited, "browser_pages": browser_pages,
             "document_identity": " ".join(hints["primary"]).title() if hints.get("primary") else (hints.get("title") or None),
             "items": sorted(items.values(), key=lambda item: (["selected", "verified", "needs_verification", "rejected", "inaccessible",
                             "unavailable", "visited", "not_relevant"].index(item["status"]), -(item["score"] or 0)))[:200],
             "notes": list(dict.fromkeys(notes))}
    log_event(VALIDATION, logging.INFO if selected else logging.WARNING, "discovery.reference.completed", status=status,
              selected=safe_url(selected["url"]) if selected else None,
              path=" > ".join(clean(step["label"], 60) for step in trail["path"][1:]) or None,
              pages=pages_visited, browser_pages=browser_pages, candidates=len(candidates),
              elapsed_ms=int((time.monotonic() - started) * 1000))
    if document is not None:
        document.retrieved_at = document.retrieved_at or datetime.now(timezone.utc).isoformat()
    return trail, document


def _render(url, hosts, timeout):
    from app.services.pdf_validation_browser import render_navigation
    return render_navigation(url, hosts, timeout)
