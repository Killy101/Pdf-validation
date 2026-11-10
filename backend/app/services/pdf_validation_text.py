"""Bounded text alignment and readable excerpts with original page evidence."""
from difflib import SequenceMatcher
import re
import unicodedata


CJK = r"\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f"
TOKEN = re.compile(rf"[{CJK}]|[^\W{CJK}]+(?:'[^\W{CJK}]+)*|[^\w\s]")


def normalize_wraps(document, counterpart):
    words = {word.casefold() for unit in counterpart["units"] for word in re.findall(r"[^\W\d_]+", unit["text"])}
    def join(match):
        word = match[1] + match[2]
        return word if word.casefold() in words else match[0]
    return {**document, "units": [{**unit, "text": re.sub(r"([^\W\d_]+)[-\u2010]\s*\n\s*([^\W\d_]+)", join, unit["text"])}
                                    for unit in document["units"]]}


def tokens(document):
    values, locations, blocks = [], [], []
    for unit in document["units"]:
        text = unicodedata.normalize("NFKC", unit["text"]).replace("\u00ad", "")
        for before, after in (("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"')):
            text = text.replace(before, after)
        found = [match.group().casefold() for match in TOKEN.finditer(text)]
        if found:
            blocks.append((len(values), len(values) + len(found)))
        location = {**unit, "display_text": text, "token_start": len(values)}
        values.extend(found)
        locations.extend([location] * len(found))
    return values, locations, blocks


def _segments(values, start, end):
    bounds = [start]
    for index in range(start, end):
        if values[index] in {".", ";", "!", "?", "。"} or index + 1 - bounds[-1] >= 160:
            bounds.append(index + 1)
    if bounds[-1] != end:
        bounds.append(end)
    return bounds, [tuple(values[left:right]) for left, right in zip(bounds, bounds[1:])]


def detailed_changes(expected, actual, start, end, a_start, a_end, refine=True):
    while start < end and a_start < a_end and expected[start] == actual[a_start]:
        start, a_start = start + 1, a_start + 1
    while start < end and a_start < a_end and expected[end - 1] == actual[a_end - 1]:
        end, a_end = end - 1, a_end - 1
    if start == end and a_start == a_end:
        return
    if max(end - start, a_end - a_start) > 4000:
        if refine and start < end and a_start < a_end:
            source_bounds, source_keys = _segments(expected, start, end)
            upload_bounds, upload_keys = _segments(actual, a_start, a_end)
            matcher = SequenceMatcher(None, source_keys, upload_keys, autojunk=True)
            for tag, left, right, a_left, a_right in matcher.get_opcodes():
                if tag != "equal":
                    yield from detailed_changes(expected, actual, source_bounds[left], source_bounds[right],
                                                upload_bounds[a_left], upload_bounds[a_right], refine=False)
            return
        tag = "insert" if start == end else "delete" if a_start == a_end else "replace"
        yield tag, start, end, a_start, a_end
        return
    matcher = SequenceMatcher(None, expected[start:end], actual[a_start:a_end], autojunk=False)
    for tag, left, right, a_left, a_right in matcher.get_opcodes():
        if tag != "equal":
            yield tag, start + left, start + right, a_start + a_left, a_start + a_right


def document_changes(expected, actual, expected_blocks, actual_blocks):
    if expected == actual:
        return
    if max(len(expected), len(actual)) <= 4000:
        yield from detailed_changes(expected, actual, 0, len(expected), 0, len(actual))
        return
    source_keys = [tuple(expected[start:end]) for start, end in expected_blocks]
    upload_keys = [tuple(actual[start:end]) for start, end in actual_blocks]
    matcher = SequenceMatcher(None, source_keys, upload_keys, autojunk=True)
    source_bounds = [start for start, _ in expected_blocks] + [len(expected)]
    upload_bounds = [start for start, _ in actual_blocks] + [len(actual)]
    for tag, start, end, a_start, a_end in matcher.get_opcodes():
        if tag != "equal":
            yield from detailed_changes(expected, actual, source_bounds[start], source_bounds[end],
                                        upload_bounds[a_start], upload_bounds[a_end])


def excerpt(locations, start, end, context=8, limit=900, token_limit=120, evidence=False):
    start = min(start, len(locations) - 1)
    left, right = max(0, start - context), min(len(locations), max(end, start + 1) + context, start + token_limit)
    parts, ranges, offset = [], [], 0
    while left < right:
        unit = locations[left]
        stop = left + 1
        while stop < right and locations[stop] is unit:
            stop += 1
        first, last = left - unit["token_start"], stop - unit["token_start"] - 1
        begin = finish = 0
        selected = []
        for index, match in enumerate(TOKEN.finditer(unit["display_text"])):
            if index == first:
                begin = match.start()
            if first <= index <= last and start <= unit["token_start"] + index < end:
                selected.append((match.start(), match.end()))
            if index == last:
                finish = match.end()
                break
        piece = unit["display_text"][begin:finish]
        if selected:
            ranges.append((offset + selected[0][0] - begin, offset + selected[-1][1] - begin))
        parts.append(piece)
        offset += len(piece) + 2
        left = stop
    text = "\n\n".join(parts)
    clipped = right < end or len(text) > limit
    displayed = text[:limit - 3].rstrip() + "..." if clipped else text
    if evidence:
        return displayed, [min(ranges[0][0], len(displayed)), min(ranges[-1][1], len(displayed))] if ranges else [0, 0]
    return displayed


def page_range(locations, start, end):
    first = locations[min(start, len(locations) - 1)].get("page")
    last = locations[min(max(start, end - 1), len(locations) - 1)].get("page")
    return first, last


def search_phrase(locations, start):
    start = min(start, len(locations) - 1)
    unit = locations[start]
    left, right = max(unit["token_start"], start - 4), min(len(locations), start + 8)
    while right > start + 1 and locations[right - 1] is not unit:
        right -= 1
    text = excerpt(locations, left, right, context=0, limit=160, token_limit=16)
    return " ".join(text.removesuffix("...").split())
