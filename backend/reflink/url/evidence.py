"""Source URI safety and HTML encoding helpers used by PDF validation (verbatim from reflink.url.evidence)."""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler

from reflink.url.targets import valid_url_target


def _valid_http_url(value: str) -> bool:
    return valid_url_target(value)


def _host_allowed(hostname: str, allowed_hosts: tuple[str, ...]) -> bool:
    host = hostname.rstrip(".").casefold()
    return any(
        host == allowed.rstrip(".").casefold()
        or host.endswith("." + allowed.rstrip(".").casefold())
        for allowed in allowed_hosts
        if allowed
    )


def validate_source_uri(uri: str, allowed_hosts: tuple[str, ...]) -> None:
    """Reject non-authoritative and non-public fetch targets before I/O."""
    if not _valid_http_url(uri):
        raise ValueError("Content URI is not a valid HTTP(S) URL")
    parsed = urlsplit(uri)
    hostname = parsed.hostname or ""
    if not allowed_hosts or not _host_allowed(hostname, allowed_hosts):
        raise ValueError("Content URI host is not approved by the source profile")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme.casefold() == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except OSError as exc:
        raise ValueError("Content URI host could not be resolved") from exc
    if not addresses:
        raise ValueError("Content URI host has no resolved address")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Content URI resolved to a non-public address")



class _ValidatingRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_hosts: tuple[str, ...]):
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_source_uri(newurl, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)



def _detect_html_encoding(data: bytes, content_type: str) -> str:
    header_match = re.search(r"charset\s*=\s*['\"]?([\w.-]+)", content_type, re.IGNORECASE)
    if header_match:
        return header_match.group(1)
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    head = data[:4096]
    for pattern in (
        rb"<meta\b[^>]*\bcharset\s*=\s*['\"]?\s*([A-Za-z0-9._-]+)",
        rb"<meta\b[^>]*\bcontent\s*=\s*['\"][^'\"]*charset\s*=\s*([A-Za-z0-9._-]+)",
    ):
        meta_match = re.search(pattern, head, re.IGNORECASE)
        if meta_match:
            return meta_match.group(1).decode("ascii")
    return "utf-8"
