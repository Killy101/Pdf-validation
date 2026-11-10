"""Bounded public-source retrieval and static document extraction."""
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import IncompleteRead
import re
import time
from urllib.parse import parse_qs, quote, unquote, urldefrag, urljoin, urlsplit
from urllib.request import Request, build_opener

from app.config import settings
from reflink.url.evidence import _ValidatingRedirectHandler, validate_source_uri
from reflink.url.targets import valid_url_target
from app.services.pdf_validation_access import CAPTCHA_MESSAGE, SourceAccessError
from app.services.pdf_validation_html_patterns import document_body, document_frame, legislation_viewer_pdf, website_control
from app.services.pdf_validation_retry import retry_source
from app.services.pdf_validation_scraping import pdf_metadata, scrape_page
from app.services.pdf_validation_navigation import continuation_label


@dataclass
class SourceSnapshot:
    data: bytes
    url: str
    kind: str
    content_type: str = ""
    retrieved_at: str | None = None
    retrieval_attempts: int = 1


def fetch_source(url: str, allowed_hosts: tuple[str, ...], max_bytes: int, timeout: float) -> SourceSnapshot:
    return retry_source(lambda remaining: _fetch_source_once(url, allowed_hosts, max_bytes, remaining), timeout)


def _fetch_source_once(url: str, allowed_hosts: tuple[str, ...], max_bytes: int, timeout: float) -> SourceSnapshot:
    deadline = time.monotonic() + timeout
    url = urldefrag(url)[0]
    validate_source_uri(url, allowed_hosts)
    parsed = urlsplit(url)
    request_url = parsed._replace(path=quote(parsed.path, safe="/%:@!$&'()*+,;="),
                                  query=quote(parsed.query, safe="/?%:@!$&'()*+,;=")).geturl()
    request = Request(request_url, headers={"User-Agent": "Reflink-PDF-Validator/1.0",
                                           "Accept": "application/pdf,text/html,application/xhtml+xml,application/zip"})
    opener = build_opener(_ValidatingRedirectHandler(allowed_hosts))
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Source retrieval timed out.")
    with opener.open(request, timeout=min(remaining, settings.PDF_VALIDATION_FETCH_SOCKET_TIMEOUT_SECONDS)) as response:
        final_url = urldefrag(response.geturl())[0]
        validate_source_uri(final_url, allowed_hosts)
        if response.headers.get("cf-mitigated") == "challenge":
            raise SourceAccessError("captcha", CAPTCHA_MESSAGE)
        length = response.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            raise ValueError("The source document exceeds the configured size limit.")
        parts, size = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Source retrieval timed out.")
            sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
            if sock:
                sock.settimeout(min(remaining, settings.PDF_VALIDATION_FETCH_SOCKET_TIMEOUT_SECONDS))
            part = getattr(response, "read1", response.read)(min(65536, max_bytes + 1 - size))
            if not part:
                break
            parts.append(part)
            size += len(part)
            if size > max_bytes:
                raise ValueError("The source document exceeds the configured size limit.")
        data = b"".join(parts)
        if length and size < int(length) and "chunked" not in response.headers.get("Transfer-Encoding", "").lower():
            raise IncompleteRead(data, int(length) - size)
        content_type = response.headers.get("Content-Type", "").lower()
    kind = "pdf" if data.startswith(b"%PDF-") else "zip" if data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")) else "html" if (
        "text/html" in content_type or "application/xhtml+xml" in content_type
        or re.search(rb"<(?:!doctype\s+html|html|body|main|article)\b", data[:4096], re.I)
    ) else "unknown"
    return SourceSnapshot(data, final_url, kind, content_type, datetime.now(timezone.utc).isoformat())


class DocumentParser:
    ignored = {"head", "nav", "header", "footer", "aside", "script", "style", "noscript",
               "template", "form", "button", "svg", "canvas", "iframe", "select"}
    blocks = {"p", "div", "section", "article", "main", "li", "tr", "td", "th", "caption", "br", "h1", "h2", "h3", "h4", "h5", "h6"}
    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, url: str, collection=False):
        self.url = url
        self.collection = collection
        self.base_url = url
        self.stack = []
        self.parts, self.pending, self.links = [], [], []
        self.heading, self.fragment, self.anchor = None, None, None
        self.main_count = self.article_count = 0
        self.document_count = 0
        self.document_viewer = False
        self.interactive_content = []
        self.visual_content = []

    def feed(self, node):
        if node.tag == "#text":
            self.handle_data(node.text)
            return
        attrs = dict(node.attrib)
        justice = (urlsplit(self.url).hostname or "").endswith("justice.gc.ca")
        if justice and "wb-invisible" in attrs.get("class", "").split():
            attrs["hidden"] = ""
        if justice and node.tag == "dt":
            following = node.xpath("following-sibling::dd[1]")
            term = node.css("dfn")
            repeated = following[0].css("p.Definition > .DefinedTerm dfn") if following else []
            if term and repeated and term[0].text.strip() == repeated[0].text.strip():
                attrs["hidden"] = ""
        if self.collection and node.tag == "a" and (
                {"next", "prev"} & set(attrs.get("rel", "").split())
                or continuation_label(node.get_all_text(separator=" ", strip=True))
                or re.fullmatch(r"previous\s+page\s*(?:[<\u2190])?", node.get_all_text(separator=" ", strip=True), re.I)):
            attrs["hidden"] = ""
        self.handle_starttag(node.tag, attrs.items())
        for child in node.xpath("./node()"):
            self.feed(child)
        if node.tag not in self.void:
            self.handle_endtag(node.tag)

    def add_pdf(self, value, label="Reference PDF", declared=False, viewer=False):
        if not value:
            return
        url = urljoin(self.base_url, value)
        if not valid_url_target(url):
            return
        pdf_url = re.search(r"\.pdf(?:$|[?#&])", unquote(url), re.I)
        if (declared == "zip" or re.search(r"\.zip(?:$|[?#&])", unquote(url), re.I)
                or not declared and not pdf_url and re.search(r"\bzip\b", label, re.I)):
            self.links.append({"url": urldefrag(url)[0], "label": label[:200] or "ZIP download", "kind": "zip"})
            return
        if viewer:
            query = parse_qs(urlsplit(url).query)
            for key in ("file", "url", "src", "pdf", "document"):
                for target in query.get(key, []):
                    if unquote(urlsplit(target).path).lower().endswith(".pdf"):
                        self.add_pdf(urljoin(url, target), label)
                        return
        if (declared or pdf_url
                or urlsplit(url).path.rstrip("/").casefold().endswith("/pdf") or re.search(r"\bpdf\b", label, re.I)):
            self.links.append({"url": urldefrag(url)[0], "label": label[:200] or "Reference PDF"})

    def hidden(self):
        return any(frame[2] for frame in self.stack)

    def scope(self, tag="", content=False):
        tags = [frame[0] for frame in self.stack]
        return {"main": "main" in tags or tag == "main", "article": "article" in tags or tag == "article",
                "document": content or any(frame[3] for frame in self.stack)}

    def flush(self):
        text = " ".join("".join(self.pending).split())
        self.pending = []
        if not text:
            return
        tags = [frame[0] for frame in self.stack]
        if any(tag in {"h1", "h2", "h3", "h4", "h5", "h6"} for tag in tags):
            self.heading = text
            self.fragment = next((frame[1].get("id") for frame in reversed(self.stack) if frame[1].get("id")), None)
        language = next((frame[1].get("lang") or frame[1].get("xml:lang") for frame in reversed(self.stack)
                         if frame[1].get("lang") or frame[1].get("xml:lang")), None)
        self.parts.append({"text": text, "heading": self.heading, "fragment": self.fragment, "language": language,
                           **self.scope()})

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "base" and attrs.get("href"):
            candidate = urljoin(self.url, attrs["href"])
            if valid_url_target(candidate):
                self.base_url = candidate
        if tag in {"iframe", "embed", "object"}:
            if tag == "iframe" and document_frame(attrs):
                self.document_viewer = True
            viewer_pdf = legislation_viewer_pdf(urljoin(self.base_url, attrs.get("src", "")), attrs) if tag == "iframe" else None
            if viewer_pdf:
                self.add_pdf(viewer_pdf, "Legislation PDF (displayed edition)", declared=True)
            self.add_pdf(attrs.get("data") if tag == "object" else attrs.get("src"),
                         attrs.get("title") or "Embedded document", attrs.get("type", "").lower() == "application/pdf", viewer=True)
        if tag == "link" and attrs.get("type", "").lower() in {"application/pdf", "application/zip", "application/x-zip-compressed"}:
            self.add_pdf(attrs.get("href"), attrs.get("title") or "Publication download",
                         declared=True if attrs["type"].lower() == "application/pdf" else "zip")
        if tag == "meta" and (attrs.get("name") or attrs.get("property") or "").lower() in {"citation_pdf_url", "og:pdf"}:
            self.add_pdf(attrs.get("content"), "Publication PDF", declared=True)
        if len(self.stack) >= 256:
            raise ValueError("The webpage structure is too complex for static comparison. Use a direct PDF URL.")
        content = tag in {"body", "main", "article", "section", "div"} and document_body(attrs)
        scope = self.scope(tag, content)
        control = website_control(attrs, scope["document"])
        if self.collection and (attrs.get("id") == "toc" or "toc" in attrs.get("class", "").split()
                or attrs.get("role") == "doc-toc" or "data-document-toc" in attrs):
            control = True
        if (urlsplit(self.url).hostname or "").endswith("justice.gc.ca") and attrs.get("class") == "info":
            control = True
        invisible = "hidden" in attrs or attrs.get("aria-hidden") == "true" or bool(
            re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", attrs.get("style") or "", re.I))
        excluded_tag = tag in self.ignored and not (scope["document"] and tag in {"header", "footer"})
        hidden = self.hidden() or excluded_tag or control or invisible
        if not self.hidden() and not control and not invisible:
            if tag in {"button", "iframe", "canvas"} or tag == "details" and "open" not in attrs or attrs.get("aria-expanded") == "false":
                self.interactive_content.append(scope)
            if tag in {"img", "svg", "table", "math", "canvas"}:
                self.visual_content.append(scope)
        if not self.hidden() and (tag in self.blocks or hidden or content):
            self.flush()
        if not hidden:
            self.main_count += tag == "main"
            self.article_count += tag == "article"
            self.document_count += content and not self.scope()["document"]
        if tag == "a":
            mime = attrs.get("type", "").split(";", 1)[0].strip().lower()
            download = (attrs.get("download") or "").lower()
            declared = "zip" if mime in {"application/zip", "application/x-zip-compressed"} or download.endswith(".zip") else (
                mime == "application/pdf" or download.endswith(".pdf"))
            self.anchor = {"url": attrs.get("href", ""), "parts": [], "label": attrs.get("aria-label") or attrs.get("title") or "",
                           "pdf": declared}
        if tag not in self.void:
            self.stack.append((tag, attrs, hidden, content))

    def handle_endtag(self, tag):
        if tag == "span" and self.stack and re.fullmatch(r"HLabel\d+", self.stack[-1][1].get("class", "")):
            self.pending.append(" ")
        if tag == "a" and self.anchor and self.anchor["url"].startswith("#fn_"):
            self.pending.append(" ")
        if tag in self.blocks and not self.hidden():
            self.flush()
        if tag == "a" and self.anchor:
            label = " ".join("".join(self.anchor["parts"]).split()) or self.anchor["label"]
            self.add_pdf(self.anchor["url"], label, self.anchor["pdf"])
            if not self.hidden() and (re.search(r"load\s+more|show\s+more", label, re.I)
                    or not self.collection and re.search(r"next\s+page", label, re.I)):
                self.interactive_content.append(self.scope())
            self.anchor = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.anchor:
            self.anchor["parts"].append(data)
        if not self.hidden():
            self.pending.append(data)

    def result(self):
        self.flush()
        parts = self.parts
        visual = self.visual_content
        title = next((part["heading"] for part in parts if part["heading"]), None)
        scope = "document" if self.document_count else "article" if self.article_count else "main" if self.main_count else None
        if self.document_viewer and not self.document_count and not self.article_count:
            parts, visual = [], []
        elif scope:
            parts = [part for part in parts if part[scope]]
            visual = [item for item in visual if item[scope]]
        interactive = any(item[scope] if scope else True for item in self.interactive_content)
        count = self.document_count if scope == "document" else self.article_count if scope == "article" else self.main_count
        complete = bool(parts) and count <= 1 and not interactive
        units = [{"text": part["text"], "heading": part["heading"],
                  "url": self.url + ("#" + part["fragment"] if part["fragment"] else ""),
                  **({"language": part["language"]} if part.get("language") else {})} for part in parts]
        title = next((unit["heading"] for unit in units if unit["heading"]), None) or title
        complete = complete and bool(title) and sum(len(unit["text"]) for unit in units) >= 100
        references = list({link["url"]: link for link in self.links}.values())[:20]
        return {"units": units, "title": title, "complete": complete, "requires_visual_review": bool(visual)}, references


def extract_html(snapshot: SourceSnapshot, collection=False):
    if len(snapshot.data) > settings.PDF_VALIDATION_MAX_HTML_BYTES:
        raise ValueError("The webpage is too large for static comparison. Enter a direct PDF URL.")
    page = scrape_page(snapshot.data, snapshot.url, snapshot.content_type)
    parser = DocumentParser(snapshot.url, collection)
    parser.feed(page)
    for link in pdf_metadata(page):
        parser.add_pdf(*link)
    html, references = parser.result()
    if (urlsplit(snapshot.url).hostname or "").endswith("law.go.kr") and b"bylInfoDiv(" in snapshot.data:
        html["complete"] = False
    return html, references


def reference_allowed(url: str, hosts: tuple[str, ...]) -> bool:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return valid_url_target(url) and any(host == item.lower().rstrip(".") or host.endswith("." + item.lower().rstrip(".")) for item in hosts)
