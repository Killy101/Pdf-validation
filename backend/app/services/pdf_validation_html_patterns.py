"""Recognize document bodies and website controls without filtering document words."""
import re
from urllib.parse import urlsplit, urlunsplit


DOCUMENT_MARKERS = re.compile(
    r"(?:^|[\s_-])(?:document|legislation|legislative|law|act|regulation|pdf)[_-](?:content|body|text)(?:$|[\s_-])"
)
CHROME_MARKERS = re.compile(
    r"(?:^|[\s_-])(?:breadcrumbs?|pagination|pager|toolbar|toolbars|toc-(?:header|toolbar|body|link)|"
    r"no-print|noprint|d-print-none)(?:$|[\s_-])"
)
OUTSIDE_DOCUMENT_MARKERS = re.compile(
    r"(?:^|[\s_-])(?:(?:site|page|global)-(?:header|footer|navigation)|"
    r"(?:version|download|metadata|title)-(?:panel|banner|controls)|view-document|table-of-contents)(?:$|[\s_-])"
)
CHROME_ROLES = {"navigation", "banner", "contentinfo", "complementary", "toolbar", "tablist", "tab", "search"}


def identity(attrs):
    value = " ".join((attrs.get("id", ""), attrs.get("class", "")))
    return re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value).casefold().replace("_", "-")


def document_body(attrs):
    marker = identity(attrs)
    return bool(DOCUMENT_MARKERS.search(marker) or re.search(r"(?:^|\s)(?:content-body|doc-contents)(?:$|\s)", marker)
                or "data-document-content" in attrs or "data-document-body" in attrs)


def website_control(attrs, in_document=False):
    marker = identity(attrs)
    return (attrs.get("role", "").casefold() in CHROME_ROLES or bool(CHROME_MARKERS.search(marker))
            or not in_document and bool(OUTSIDE_DOCUMENT_MARKERS.search(marker)))


def document_frame(attrs):
    return bool(re.search(r"(?:^|\s)(?:epub-frame|document-frame|document-viewer)(?:$|\s)", identity(attrs))) or attrs.get("title", "").casefold().startswith("document:")


def legislation_viewer_pdf(url, attrs):
    parsed = urlsplit(url)
    if (attrs.get("id", "").casefold() != "epubframe"
            or parsed.hostname not in {"www.legislation.gov.au", "legislation.gov.au"}):
        return None
    match = re.fullmatch(r"(.+/text/original)/epub/.+\.html", parsed.path, re.I)
    if match:
        return urlunsplit((parsed.scheme, parsed.netloc, match[1] + "/pdf", "", ""))
    return None
