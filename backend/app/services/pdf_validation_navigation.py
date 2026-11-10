"""Discover document views and chapter links with explicit identity boundaries."""
import re
import json
from urllib.parse import parse_qs, urljoin, urlsplit
import unicodedata

from app.services.pdf_validation_scraping import scrape_page
from app.services.pdf_validation_html_patterns import document_body
from reflink.url.targets import valid_url_target


TOC = '#toc a[href], .toc a[href], [role="doc-toc"] a[href], [data-document-toc] a[href], .table-of-contents a[href], nav[aria-label*="ontent"] a[href]'
COMPLETE = re.compile(r"^(?:full|complete|whole|entire)\s+(?:document|text|regulations?|act)|^print(?:able)?\s+(?:version|view|document)|^(?:texte int[ée]gral|document complet|version imprimable|volltext|gesamter text|druckansicht|texto (?:completo|integral)|versi[óo]n para imprimir|testo (?:completo|integrale)|volledige tekst|全文|全条文|전문\s*보기|전체\s*(?:본문|내용)|النص الكامل)", re.I)
SECTION_NAMES = {
    "section": "section|article|abschnitt|artikel|secci[óo]n|art[íi]culo|se[cç][aã]o|artigo|sezione|articolo|paragraaf|المادة|अनुच्छेद",
    "chapter": "chapter|chapitre|kapitel|cap[íi]tulo|capitolo|hoofdstuk",
    "part": "part|partie|teil|parte|deel", "annex": "annex|annexe|anhang|anexo|bijlage|allegato|ملحق",
    "appendix": "appendix|anlage|ap[ée]ndice", "schedule": "schedule",
}
PREFIXES = "|".join(SECTION_NAMES.values())
CHAPTER = re.compile(rf"^(?:{PREFIXES})[\s_-]+[\w.-]+|^\d+[.\s:-]|^(?:第|제)\s*[\d一二三四五六七八九十百千]+\s*[条條조章장節节절部편]", re.I)
CONTENTS_LABEL = re.compile(r"contents|sommaire|inhalt|[íi]ndice|sommario|inhoud|目次|목차|目[录錄]|المحتويات|תוכן|содержание", re.I)
NEXT_LABELS = {"next page", "page suivante", "suivant", "nächste seite", "weiter", "página siguiente", "siguiente", "próxima página", "pagina successiva", "volgende pagina", "次のページ", "下一页", "下一頁", "다음 페이지", "следующая страница", "الصفحة التالية"}


def continuation_label(value):
    return unicodedata.normalize("NFKC", value).casefold().strip(" \t\r\n><‹›«»←→") in NEXT_LABELS


def page_identity(page):
    def meta(name):
        nodes = page.css(f'meta[name="{name}"], meta[property="{name}"]')
        return nodes[0].attrib.get("content", "").strip() if nodes else ""
    roots = page.css("html")
    return {"document_id": meta("document-id") or meta("dcterms.identifier"),
            "edition": meta("document-version") or meta("version"),
            "language": (roots[0].attrib.get("lang", "") if roots else "").split("-")[0].lower()}


def navigation(snapshot):
    page = scrape_page(snapshot.data, snapshot.url, snapshot.content_type)
    marked = [node for node in page.css("body, main, article, section, div") if document_body(node.attrib)]
    roots = [node for node in marked if not any(document_body(parent.attrib) for parent in node.xpath("ancestor::*"))]
    roots = roots or page.css("article") or page.css("main")
    content_selector = None
    if len(roots) == 1:
        root = roots[0]
        attribute = next((key for key in ("id", "class", "data-document-content", "data-document-body") if key in root.attrib), None)
        content_selector = root.tag + (f'[{attribute}={json.dumps(root.attrib[attribute])}]' if attribute else "")
    interactive = any(root.css('details:not([open]), [role="tab"], [data-document-expand], #app:empty, #root:empty') for root in roots or [page])
    complete, links = [], []
    base = snapshot.url
    bases = page.css("base[href]")
    if bases:
        base = urljoin(base, bases[0].attrib["href"])
    def link(node, kind):
        target = urljoin(base, node.attrib.get("href", ""))
        label = node.get_all_text(separator=" ", strip=True) or node.attrib.get("aria-label", "")
        return {"url": target, "label": label[:200] or "Document section", "kind": kind,
                "language": node.attrib.get("hreflang", "").split("-")[0].lower()}
    for node in page.css(TOC):
        item = link(node, "section")
        if valid_url_target(item["url"]):
            links.append(item)
    for nav in page.css('nav[aria-label]'):
        if CONTENTS_LABEL.search(nav.attrib["aria-label"]):
            links.extend(link(node, "section") for node in nav.css("a[href]"))
    for node in page.css('main a[href], article a[href], [data-document-link][href], link[rel="next"][href]'):
        item = link(node, "section")
        rel = node.attrib.get("rel", "").split()
        if COMPLETE.search(item["label"]):
            complete.append({**item, "kind": "complete"})
        elif "next" in rel or continuation_label(item["label"]):
            links.append({**item, "kind": "continuation"})
        elif "data-document-link" in node.attrib:
            links.append(item)
    for node in page.css('a[rel="next"][href]'):
        links.append(link(node, "continuation"))
    return {"identity": page_identity(page), "complete": list({item["url"]: item for item in complete}.values()),
            "links": list({item["url"]: item for item in links}.values()),
            "interactive": interactive, "content_selector": content_selector, "ambiguous_content": len(roots) > 1}


def eligible_link(item, root_url, identity, hosts):
    parsed, root = urlsplit(item["url"]), urlsplit(root_url)
    host = (parsed.hostname or "").lower()
    if not valid_url_target(item["url"]) or not any(host == value or host.endswith("." + value) for value in hosts):
        return False
    if item.get("language") and identity.get("language") and item["language"] != identity["language"]:
        return False
    parent = root.path.rsplit("/", 1)[0] + "/"
    if host != (root.hostname or "").lower() or not parsed.path.startswith(parent):
        return False
    for key in ("version", "edition", "date", "pointInTime", "validFrom", "lang", "language"):
        before, after = parse_qs(root.query).get(key), parse_qs(parsed.query).get(key)
        if before and after and before != after:
            return False
    for key in ("lang", "language"):
        language = parse_qs(parsed.query).get(key, [""])[0].lower().split("-")[0]
        if language and identity.get("language") and language != identity["language"]:
            return False
    return True


def compatible(root, child):
    return all(not root.get(key) or not child.get(key) or root[key] == child[key]
               for key in ("document_id", "edition", "language"))


def section_key(heading):
    text = unicodedata.normalize("NFKC", heading or "").strip()
    for family, names in SECTION_NAMES.items():
        match = re.match(rf"(?:{names})[\s_-]+(\d+(?:\.\d+)*[A-Za-z]?|[IVXLCDM]+)\b", text, re.I)
        if match:
            number = str(int(match[1])) if match[1].isdecimal() else match[1].casefold()
            return family + ":" + number
    match = re.match(r"(?:第|제)\s*(\d+)\s*([条條조章장節节절部편])", text)
    if match:
        family = "section" if match[2] in "条條조節节절" else "chapter" if match[2] in "章장" else "part"
        return family + ":" + str(int(match[1]))
    return None
