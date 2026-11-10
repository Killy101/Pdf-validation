"""Resolve historical reference periods without falling back to current content."""
from datetime import date, timedelta
import json
import re
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from app.config import settings
from app.pdf_validation_models import PdfHistoricalReference, PdfSourceDiscovery
from app.services.pdf_validation_jurisdictions import PublisherPage, checked_source, resolve_jurisdiction, retrieve_document, source_text
from app.services.pdf_validation_source import reference_allowed
from reflink.url.targets import valid_url_target


def _reference(url, label, start, end, hosts):
    if not valid_url_target(url):
        raise ValueError("A historical version link is not a valid HTTP or HTTPS document URL.")
    return PdfHistoricalReference(url=url, label=label[:200], valid_from=start, valid_to=end,
                                  available=reference_allowed(url, hosts))


def _australian_versions(snapshot, hosts):
    page = PublisherPage(source_text(snapshot))
    versions, complete, listed = {}, True, False
    for text in page.states:
        state = json.loads(text)
        if not isinstance(state, dict):
            raise ValueError("The publisher's version history could not be read.")
        for key, response in state.items():
            if not isinstance(response, dict):
                continue
            if isinstance(response.get("value"), list):
                entries = [item for item in response["value"] if isinstance(item, dict) and item.get("titleId") and item.get("start")]
                if "versions" in key.lower():
                    listed = True
                    complete = complete and response.get("@odata.count") == len(entries)
            else:
                entries = [response] if response.get("titleId") and response.get("start") else []
            if not entries:
                continue
            for entry in entries:
                start = date.fromisoformat(entry["start"][:10])
                end = date.fromisoformat(entry["end"][:10]) - timedelta(days=1) if entry.get("end") else None
                if end and end < start:
                    raise ValueError("The publisher's version history contains an invalid date period.")
                edition = "asmade" if str(entry.get("compilationNumber")) == "0" else start.isoformat()
                url = urljoin(snapshot.url, f"/{entry['titleId']}/{edition}/text")
                versions[url] = _reference(url, entry.get("registerId") or start.isoformat(), start, end, hosts)
    return list(versions.values()), complete and listed


def _dated_links(snapshot, hosts):
    versions = []
    for attrs, label in PublisherPage(source_text(snapshot)).links:
        dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", label)
        start, end = attrs.get("data-valid-from"), attrs.get("data-valid-to")
        if not start and len(dates) == 2 and re.search(r"\b(?:from|to|au)\b|[–—]", label, re.I):
            start, end = dates
        if start and attrs.get("href"):
            start, end = date.fromisoformat(start), date.fromisoformat(end) if end else None
            if end and end < start:
                raise ValueError("The publisher's version history contains an invalid date period.")
            versions.append(_reference(urljoin(snapshot.url, attrs["href"]), label or start.isoformat(), start, end, hosts))
    return versions


def _korean_versions(snapshot, hosts, fetch):
    body = retrieve_document(snapshot.url, hosts, fetch, snapshot, include_body=False)
    sequence = PublisherPage(source_text(body)).inputs.get("admRulSeq", "")
    if not sequence.isdigit():
        return [], False
    url = urljoin(body.url, "/LSW/admRulHstListR.do") + "?" + urlencode({"admRulSeq": sequence})
    history = checked_source(url, hosts, fetch)
    versions, complete = [], True
    for attrs, label in PublisherPage(source_text(history)).links:
        edition = re.search(r"admRulViewHst\('([YN])','(\d+)'\)", attrs.get("onclick", ""))
        effective = re.search(r"\[시행\s+(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.", label)
        if edition and not effective:
            complete = False
        if edition and effective:
            start = date(*map(int, effective.groups()))
            path = "/LSW/admRulLsInfoP.do" if edition[1] == "Y" else "/LSW/admRulInfoP.do"
            reference = urljoin(body.url, path) + "?" + urlencode({"admRulSeq": edition[2], "chrClsCd": "010201"})
            versions.append(_reference(reference, label, start, None, hosts))
    starts = sorted({item.valid_from for item in versions})
    for version in versions:
        following = next((start for start in starts if start > version.valid_from), None)
        version.valid_to = following - timedelta(days=1) if following else date.today()
    return versions, complete and bool(versions)


def _coverage(versions, start, end):
    cursor = start
    for version in sorted(versions, key=lambda item: item.valid_from):
        if version.valid_from > cursor:
            return False
        if version.valid_to is None or version.valid_to >= end:
            return True
        cursor = max(cursor, version.valid_to + timedelta(days=1))
    return False


def discover_history(url, hosts, options, fetch):
    jurisdiction = resolve_jurisdiction(url, options.jurisdiction)
    publisher = resolve_jurisdiction(url)
    result = PdfSourceDiscovery(source_url=url, source_type="unknown", jurisdiction=jurisdiction,
        workflow="date_range", date_start=options.date_start, date_end=options.date_end,
        summary="Historical versions are unavailable for this URL. Enter the publisher's version history page or a dated edition URL using Current version.")
    if options.history_url:
        if not reference_allowed(options.history_url, hosts):
            raise ValueError("The version history URL must use an approved source host.")
        snapshot = checked_source(options.history_url, hosts, fetch)
        versions, complete = _dated_links(snapshot, hosts), False
        result.limitations.append("A supplied history page may omit editions; complete historical coverage is not certified.")
    elif publisher == "au":
        identifier = re.search(r"(?:^|/)([CF]\d{4}[A-Z]\d+)(?:/|$)", urlsplit(url).path)
        if not identifier:
            return result
        snapshot = checked_source(urljoin(url, f"/Series/{identifier[1]}"), hosts, fetch)
        versions, complete = _australian_versions(snapshot, hosts)
    elif publisher == "ca":
        path = re.match(r"(/(?:eng|fra)/(?:acts|regulations|lois|reglements)/[^/]+)(?:/|$)", urlsplit(url).path)
        if not path:
            return result
        parsed = urlsplit(url)
        snapshot = checked_source(urlunsplit((parsed.scheme, parsed.netloc, path[1] + "/PITIndex.html", "", "")), hosts, fetch)
        versions, complete = _dated_links(snapshot, hosts), True
    elif publisher == "kr":
        snapshot = checked_source(url, hosts, fetch)
        versions, complete = _korean_versions(snapshot, hosts, fetch)
    else:
        snapshot = checked_source(url, hosts, fetch)
        if snapshot.kind != "html":
            return result
        versions, complete = _dated_links(snapshot, hosts), False
        result.limitations.append("This publisher has no verified history adapter; listed versions are checked individually.")
    result.source_url, result.source_type = snapshot.url, snapshot.kind
    versions = list({(item.url, item.valid_from, item.valid_to): item for item in versions}.values())
    result.versions = sorted((item for item in versions if item.valid_from <= options.date_end
        and (item.valid_to is None or item.valid_to >= options.date_start)), key=lambda item: (item.valid_from, item.url))
    if not result.versions:
        return result
    if len(result.versions) > settings.PDF_VALIDATION_MAX_VERSIONS:
        raise ValueError(f"The range includes more than {settings.PDF_VALIDATION_MAX_VERSIONS} versions. Choose a shorter date range.")
    result.history_complete = complete and _coverage(result.versions, options.date_start, options.date_end)
    if not result.history_complete:
        result.limitations.append("The available version history does not establish complete coverage for the selected date range.")
    if any(not item.available for item in result.versions):
        result.history_complete = False
        result.limitations.append("Some historical reference hosts are unavailable under the source host policy.")
    result.summary = f"Found {len(result.versions)} version(s) applicable from {options.date_start} to {options.date_end}."
    return result
