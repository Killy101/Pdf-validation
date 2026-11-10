"""Publisher detection and bounded retrieval of supported document viewers."""
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from app.config import settings
from app.services.pdf_validation_access import ensure_source_access
from reflink.url.evidence import _detect_html_encoding


PUBLISHERS = {
    "au": ("legislation.gov.au",),
    "ca": ("justice.gc.ca",),
    "kr": ("law.go.kr",),
    "uk": ("legislation.gov.uk",),
    "us": ("uscode.house.gov", "ecfr.gov", "legislature.maine.gov"),
    "nz": ("legislation.govt.nz",),
    "jp": ("laws.e-gov.go.jp", "shugiin.go.jp", "sangiin.go.jp"),
    "sg": ("sso.agc.gov.sg",),
    "eu": ("eur-lex.europa.eu",),
}


def resolve_jurisdiction(url, selected="auto"):
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    detected = next((code for code, hosts in PUBLISHERS.items()
                     if any(host == item or host.endswith("." + item) for item in hosts)), "other")
    if selected not in {"auto", "other", detected} and detected != "other":
        raise ValueError("The selected jurisdiction does not match this publisher. Choose Auto detect or the publisher's jurisdiction.")
    return detected if selected == "auto" else selected


def source_text(snapshot):
    return snapshot.data.decode(_detect_html_encoding(snapshot.data, snapshot.content_type), errors="replace")


class PublisherPage(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.frames, self.inputs, self.links, self.states = [], {}, [], []
        self.anchor = self.state = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "iframe" and attrs.get("id") == "lawService":
            self.frames.append(attrs.get("src", ""))
        if tag == "input" and attrs.get("id"):
            self.inputs[attrs["id"]] = attrs.get("value", "")
        if tag == "a":
            self.anchor = {"attrs": attrs, "parts": []}
        if tag == "script" and attrs.get("id") == "ng-state":
            self.state = []

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor["parts"].append(data)
        if self.state is not None:
            self.state.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            self.links.append((self.anchor["attrs"], " ".join(" ".join(self.anchor["parts"]).split())))
            self.anchor = None
        if tag == "script" and self.state is not None:
            self.states.append("".join(self.state))
            self.state = None


def checked_source(url, hosts, fetch):
    snapshot = fetch(url, hosts, settings.PDF_VALIDATION_MAX_BYTES, settings.PDF_VALIDATION_TIMEOUT_SECONDS)
    ensure_source_access(snapshot)
    if snapshot.kind == "html" and len(snapshot.data) > settings.PDF_VALIDATION_MAX_HTML_BYTES:
        raise ValueError("The webpage is too large for static retrieval. Enter a direct document URL.")
    return snapshot


def retrieve_document(url, hosts, fetch, snapshot=None, include_body=True):
    snapshot = snapshot or fetch(url, hosts, settings.PDF_VALIDATION_MAX_BYTES, settings.PDF_VALIDATION_TIMEOUT_SECONDS)
    ensure_source_access(snapshot)
    if snapshot.kind != "html" or resolve_jurisdiction(snapshot.url) != "kr":
        return snapshot
    if len(snapshot.data) > settings.PDF_VALIDATION_MAX_HTML_BYTES:
        raise ValueError("The webpage is too large for static retrieval. Enter a direct document URL.")
    page = PublisherPage(source_text(snapshot))
    if page.frames:
        frame = urljoin(snapshot.url, page.frames[0])
        if resolve_jurisdiction(frame) != "kr" or not urlsplit(frame).path.endswith(("/admRulInfoP.do", "/admRulLsInfoP.do")):
            return snapshot
        snapshot = checked_source(frame, hosts, fetch)
    if not include_body:
        return snapshot
    parsed = urlsplit(snapshot.url)
    if snapshot.kind == "html" and parsed.path.endswith(("/admRulInfoP.do", "/admRulLsInfoP.do")):
        query = parse_qs(parsed.query)
        sequence = query.get("admRulSeq", [""])[0]
        if sequence.isdigit():
            params = {"admRulSeq": sequence, "chrClsCd": query.get("chrClsCd", ["010201"])[0]}
            body = urljoin(snapshot.url, "/LSW/admRulLsInfoR.do") + "?" + urlencode(params)
            snapshot = checked_source(body, hosts, fetch)
    return snapshot
