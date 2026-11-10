"""Retry temporary source failures within one bounded retrieval deadline."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
import errno
import socket
import ssl
import time
from urllib.error import HTTPError, URLError

from app.config import settings
from app.services.pdf_validation_access import http_access_error


def _temporary(error):
    reason = error.reason if isinstance(error, URLError) else error.__cause__ if isinstance(error, ValueError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return False
    if isinstance(reason, socket.gaierror):
        return reason.errno == socket.EAI_AGAIN
    return isinstance(reason, (TimeoutError, ConnectionError, ssl.SSLEOFError, IncompleteRead)) or (
        isinstance(reason, OSError) and reason.errno in {errno.ECONNRESET, errno.ECONNABORTED,
            errno.ETIMEDOUT, errno.ECONNREFUSED, errno.EHOSTUNREACH, errno.ENETUNREACH})


def _retry_after(headers):
    value = (headers or {}).get("Retry-After")
    if not value:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return max(0, (stamp - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def retry_source(retrieve, timeout):
    deadline = time.monotonic() + timeout
    for attempt in range(settings.PDF_VALIDATION_RETRY_ATTEMPTS):
        try:
            snapshot = retrieve(max(0.001, deadline - time.monotonic()))
            snapshot.retrieval_attempts = attempt + 1
            return snapshot
        except HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504}:
                raise
            delay = _retry_after(error.headers)
            failure = http_access_error(error)
            if failure.issue in {"captcha", "access_denied"}:
                raise failure from error
        except (URLError, OSError, IncompleteRead, ValueError) as error:
            if not _temporary(error):
                raise
            failure, delay = error, None
        delay = delay if delay is not None else settings.PDF_VALIDATION_RETRY_DELAY_SECONDS * 2 ** attempt
        if (attempt + 1 == settings.PDF_VALIDATION_RETRY_ATTEMPTS
                or delay > settings.PDF_VALIDATION_MAX_RETRY_WAIT_SECONDS
                or delay >= deadline - time.monotonic()):
            if isinstance(failure, IncompleteRead):
                raise URLError(failure) from failure
            raise failure
        if delay:
            time.sleep(delay)
    raise TimeoutError("Source retrieval timed out.")
