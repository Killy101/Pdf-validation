"""Bounded source retries using a deterministic clock and synthetic failures."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.client import IncompleteRead
from io import BytesIO
import socket
import ssl
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from test_pdf_validation import URL
from app.config import settings
from app.services import pdf_validation_retry as retry
from app.services.pdf_validation_access import SourceAccessError
from app.services.pdf_validation_source import SourceSnapshot


@pytest.fixture
def clock(monkeypatch):
    elapsed, waits = [0], []
    monkeypatch.setattr(retry.time, "monotonic", lambda: elapsed[0])
    def sleep(delay):
        waits.append(delay)
        elapsed[0] += delay
    monkeypatch.setattr(retry.time, "sleep", sleep)
    monkeypatch.setattr(settings, "PDF_VALIDATION_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "PDF_VALIDATION_RETRY_DELAY_SECONDS", 1)
    monkeypatch.setattr(settings, "PDF_VALIDATION_MAX_RETRY_WAIT_SECONDS", 10)
    return elapsed, waits


def attempt(values):
    calls = []
    def fetch(timeout):
        calls.append(timeout)
        value = values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value
    return fetch, calls


@pytest.mark.parametrize("failure", [TimeoutError(), ConnectionResetError(), IncompleteRead(b"partial"), URLError(socket.gaierror(socket.EAI_AGAIN, "Temporary lookup")), URLError(ssl.SSLEOFError())])
def test_transient_failure_retries_with_backoff_under_one_deadline(clock, failure):
    fetch, calls = attempt([failure, failure, SourceSnapshot(b"%PDF-synthetic", URL, "pdf")])
    result = retry.retry_source(fetch, 30)
    assert result.retrieval_attempts == 3
    assert clock[1] == [1, 2] and calls == [30, 29, 27]


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_retryable_http_status_honors_retry_after(clock, code):
    error = HTTPError(URL, code, "Temporary failure", {"Retry-After": "4"}, BytesIO(b""))
    fetch, calls = attempt([error, SourceSnapshot(b"%PDF-synthetic", URL, "pdf")])
    result = retry.retry_source(fetch, 30)
    assert result.retrieval_attempts == 2 and calls == [30, 26] and clock[1] == [4]
    assert error.fp.closed


def test_http_date_retry_after_is_supported():
    later = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=6), usegmt=True)
    assert 4 <= retry._retry_after({"Retry-After": later}) <= 6
    assert retry._retry_after({"Retry-After": "bad value"}) is None


@pytest.mark.parametrize("wait,budget", [("60", 30), ("4", 3)])
def test_retry_after_outside_budget_is_not_shortened(clock, wait, budget):
    fetch, calls = attempt([HTTPError(URL, 429, "Limited", {"Retry-After": wait}, BytesIO(b""))])
    with pytest.raises(SourceAccessError) as error:
        retry.retry_source(fetch, budget)
    assert error.value.issue == "rate_limited" and calls == [budget] and clock[1] == []


@pytest.mark.parametrize("failure", [
    HTTPError(URL, 403, "Forbidden", {}, BytesIO(b"")),
    HTTPError(URL, 404, "Missing", {}, BytesIO(b"")),
    URLError(ssl.SSLCertVerificationError("Certificate invalid")),
    URLError(socket.gaierror(socket.EAI_NONAME, "Unknown host")),
    ValueError("The source is outside the approved hosts"),
    ValueError("The source document exceeds the configured size limit"),
    SourceAccessError("captcha", "Browser verification required"),
])
def test_permanent_failures_are_not_retried(clock, failure):
    fetch, calls = attempt([failure])
    with pytest.raises(type(failure)):
        retry.retry_source(fetch, 30)
    assert len(calls) == 1 and not clock[1]


def test_captcha_on_a_server_failure_cannot_trigger_retries(clock):
    error = HTTPError(URL, 503, "Challenge", {}, BytesIO(b"<title>Just a moment...</title>"))
    fetch, calls = attempt([error])
    with pytest.raises(SourceAccessError) as captured:
        retry.retry_source(fetch, 30)
    assert captured.value.issue == "captcha" and len(calls) == 1 and not clock[1]


def test_sign_in_on_a_server_failure_cannot_trigger_retries(clock):
    fetch, calls = attempt([HTTPError(URL, 503, "Sign in", {}, BytesIO(b"<h1>Sign in</h1>"))])
    with pytest.raises(SourceAccessError) as captured:
        retry.retry_source(fetch, 30)
    assert captured.value.issue == "access_denied" and len(calls) == 1 and not clock[1]


def test_persistently_truncated_response_returns_a_network_failure(clock):
    fetch, calls = attempt([IncompleteRead(b"partial")] * 3)
    with pytest.raises(URLError):
        retry.retry_source(fetch, 30)
    assert len(calls) == 3


def test_retries_stop_after_configured_attempts_or_elapsed_deadline(clock):
    fetch, calls = attempt([TimeoutError()] * 3)
    with pytest.raises(TimeoutError):
        retry.retry_source(fetch, 30)
    assert len(calls) == 3 and clock[1] == [1, 2]
    clock[0][0] = 0
    clock[1].clear()
    def exhausted(timeout):
        clock[0][0] += timeout
        raise TimeoutError()
    with pytest.raises(TimeoutError):
        retry.retry_source(exhausted, 3)
    assert not clock[1]


def test_source_socket_timeout_shrinks_with_the_remaining_deadline(clock, monkeypatch):
    from app.services import pdf_validation_source as retrieval
    waits, opens, parts = [], [], [b"%PDF-synthetic", b""]
    monkeypatch.setattr(retrieval, "validate_source_uri", lambda *args: None)
    class Response:
        headers = {"Content-Type": "application/pdf"}
        fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=waits.append)))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def geturl(self):
            return URL
        def read(self, size):
            pytest.fail("Bounded retrieval should prefer one transport read at a time")
        def read1(self, size):
            clock[0][0] += 2
            return parts.pop(0)
    def open_source(request, timeout):
        opens.append(timeout)
        return Response()
    monkeypatch.setattr(retrieval, "build_opener", lambda *args: SimpleNamespace(open=open_source))
    snapshot = retrieval.fetch_source(URL, ("publisher.example",), 100, 5)
    assert opens == [5] and waits == [5, 3]
    assert snapshot.retrieval_attempts == 1 and snapshot.kind == "pdf"


def test_completed_response_does_not_update_a_detached_socket(clock, monkeypatch):
    from app.services import pdf_validation_source as retrieval
    monkeypatch.setattr(retrieval, "validate_source_uri", lambda *args: None)
    data = b"<html><body>" + b"x" * 70000 + b"</body></html>"
    timeouts = []
    class Socket:
        closed = False
        def settimeout(self, value):
            if self.closed:
                raise OSError(10038, "An operation was attempted on something that is not a socket")
            timeouts.append(value)
    sock = Socket()
    class Response(BytesIO):
        headers = {"Content-Type": "text/html", "Content-Length": str(len(data))}
        fp = SimpleNamespace(raw=SimpleNamespace(_sock=sock))
        def geturl(self):
            return URL
        def read1(self, size):
            part = super().read(size)
            if self.tell() == len(data):
                self.fp = None
                sock.closed = True
            return part
    monkeypatch.setattr(retrieval, "build_opener", lambda *args: SimpleNamespace(open=lambda *args, **kwargs: Response(data)))
    snapshot = retrieval.fetch_source(URL, ("publisher.example",), len(data), 5)
    assert snapshot.data == data and snapshot.kind == "html" and snapshot.retrieval_attempts == 1
    assert sock.closed and timeouts == [5, 5]
