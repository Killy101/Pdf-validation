"""Shared target validation and explicit literal-URL serialization policy."""
from __future__ import annotations

import re
from urllib.parse import urlsplit


def canonical_url_target(value: str) -> str:
    return "https://" + value if value.casefold().startswith("www.") else value


def valid_url_target(value: str) -> bool:
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return False
        parsed.hostname.encode("idna")
    except (ValueError, UnicodeError):
        return False
    return True


def literal_url_target(value: str, policy: str = "canonical") -> str:
    if policy not in {"canonical", "preserve"}:
        raise ValueError("Literal URL policy must be canonical or preserve")
    canonical = canonical_url_target(value)
    if not valid_url_target(canonical):
        raise ValueError("Literal URL is not a valid address")
    return value if policy == "preserve" else canonical
