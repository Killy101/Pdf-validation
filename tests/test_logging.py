"""Session log files: layout, format, redaction, rotation and the events written by the API."""
from datetime import datetime
import logging
import re
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app import logging_setup
from app.auth import get_current_user
from app.config import settings
from app.desktop_main import app
from app.logging_setup import APP, BACKEND, VALIDATION, DailyFileHandler, clean, log_event, prune_logs, safe_url, setup_logging
from app.services.pdf_validation_source import SourceSnapshot

from test_pdf_validation import TEXT, pdf

URL = "https://publisher.example/regulation.pdf"
LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} \| (INFO|WARNING|ERROR|DEBUG|CRITICAL) +\| [\w.]+ \| session=\S+ req=\S+ \| event=\S+")


@pytest.fixture
def logs(tmp_path):
    folder = setup_logging(tmp_path / "logs", force=True)
    yield folder
    logging_setup.shutdown_logging()


def text(root, name):
    files = list(root.glob(f"*/{name}.log"))
    return "\n".join(item.read_text(encoding="utf-8") for item in files)


@pytest.fixture
def client(logs):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="user")
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def upload(client, data, **fields):
    return client.post("/api/pdf-validations", data={"content_uri": URL, **fields},
                       files={"document": ("upload.pdf", data, "application/pdf")})


def test_entries_are_written_to_dated_files_in_one_format(logs):
    log_event(APP, logging.INFO, "app.example", detail="hello world")
    log_event(BACKEND, logging.INFO, "backend.example")
    log_event(VALIDATION, logging.INFO, "validation.example", file="a.pdf")
    day = datetime.now().strftime("%Y-%m-%d")
    assert {item.name for item in (logs / day).iterdir()} == {"application.log", "backend.log", "validation.log"}
    for name in ("application", "backend", "validation"):
        assert all(LINE.match(line) for line in text(logs, name).splitlines() if line)
    assert 'detail="hello world"' in text(logs, "application")
    assert "validation.example" in text(logs, "validation") and "validation.example" not in text(logs, "application")


def test_errors_from_any_channel_reach_the_application_log(logs):
    log_event(VALIDATION, logging.ERROR, "validation.broken")
    log_event(VALIDATION, logging.WARNING, "validation.minor")
    assert "validation.broken" in text(logs, "application") and "validation.minor" not in text(logs, "application")


def test_full_traceback_is_recorded(logs):
    try:
        raise RuntimeError("exploded")
    except RuntimeError as exc:
        log_event(APP, logging.ERROR, "app.failed", exc_info=exc)
    assert "Traceback (most recent call last)" in text(logs, "application") and "RuntimeError: exploded" in text(logs, "application")


def test_secrets_never_reach_the_log(logs, monkeypatch):
    monkeypatch.setattr(settings, "PDF_VALIDATION_DESKTOP_TOKEN", "desktop-token-value-123")
    url = safe_url("https://user:hunter2@publisher.example/a.pdf?token=abc123&page=2#frag")
    assert "hunter2" not in url and "abc123" not in url and "frag" not in url and "page=2" in url
    log_event(APP, logging.INFO, "app.example", message=clean("Authorization: Bearer abc.def.ghi password=hunter2 desktop-token-value-123"))
    log_event(APP, logging.INFO, "app.url", url=url)
    content = text(logs, "application")
    for secret in ("abc.def.ghi", "hunter2", "desktop-token-value-123", "abc123"):
        assert secret not in content


def test_values_cannot_forge_extra_log_lines(logs):
    log_event(APP, logging.INFO, "app.example", note="x\n2026-01-01 00:00:00.000 | ERROR | app | fake")
    assert len([line for line in text(logs, "application").splitlines() if "note=" in line]) == 1
    assert not any(line.startswith("2026-01-01") for line in text(logs, "application").splitlines())


def test_logging_failures_never_reach_the_caller(logs, monkeypatch):
    handler = next(item for _, item in logging_setup._handlers if isinstance(item, DailyFileHandler))
    handler.day = "1999-01-01"
    monkeypatch.setattr(handler, "_path", lambda: (_ for _ in ()).throw(PermissionError("denied")))
    monkeypatch.setattr(logging_setup, "_reported", False)
    handler.emit(logging.makeLogRecord({"msg": "lost entry", "levelno": logging.INFO}))
    log_event(APP, logging.INFO, "app.after_failure")


def test_a_new_folder_starts_at_midnight(tmp_path, monkeypatch):
    class Clock(datetime):
        current = datetime(2026, 11, 10, 23, 59, 59)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(logging_setup, "datetime", Clock)
    handler = DailyFileHandler(tmp_path, "application", 1024 * 1024, 3)
    record = logging.makeLogRecord({"msg": "one", "levelno": logging.INFO})
    handler.emit(record)
    Clock.current = datetime(2026, 11, 11, 0, 0, 1)
    handler.emit(logging.makeLogRecord({"msg": "two", "levelno": logging.INFO}))
    handler.close()
    assert "one" in (tmp_path / "2026-11-10" / "application.log").read_text()
    assert (tmp_path / "2026-11-11" / "application.log").read_text().strip() == "two"


def test_large_files_rotate_and_keep_a_limited_history(tmp_path):
    handler = DailyFileHandler(tmp_path, "validation", 400, 2)
    for index in range(60):
        handler.emit(logging.makeLogRecord({"msg": f"entry {index} " + "x" * 40, "levelno": logging.INFO}))
    handler.close()
    names = sorted(item.name for item in next(tmp_path.iterdir()).iterdir())
    assert names == ["validation.log", "validation.log.1", "validation.log.2"]


def test_old_folders_are_pruned_and_others_kept(tmp_path):
    for name in ("2020-01-01", datetime.now().strftime("%Y-%m-%d"), "notes"):
        (tmp_path / name).mkdir()
    assert prune_logs(tmp_path, 30) == 1
    assert sorted(item.name for item in tmp_path.iterdir()) == sorted(["notes", datetime.now().strftime("%Y-%m-%d")])


def test_startup_and_requests_are_logged_with_a_request_id(client):
    response = client.get("/api/health")
    assert re.fullmatch(r"[0-9a-f]{8}", response.headers["x-request-id"])
    assert "event=backend.ready" in text(client_root(), "application")
    assert client.get("/api/missing").status_code == 404
    assert re.search(r"WARNING .*event=http.request method=GET path=/api/missing status=404", text(client_root(), "backend"))


def client_root():
    return logging_setup.log_root


def test_exact_match_is_logged_with_source_and_result(client, source):
    data = pdf(TEXT)
    source[0][URL] = SourceSnapshot(data, URL, "pdf")
    response = upload(client, data)
    assert response.json()["data"]["status"] == "match"
    log = text(client_root(), "validation")
    for expected in ("event=validation.started", "file=upload.pdf", "event=source.fetch.started", "event=source.fetch.completed",
                     "kind=pdf", "event=validation.result.match", "comparison=exact_file", f"source={URL}"):
        assert expected in log
    assert "status=200" in text(client_root(), "backend")


def test_mismatch_records_the_reasons(client, source):
    source[0][URL] = SourceSnapshot(pdf(TEXT.replace("all regulated", "some regulated")), URL, "pdf")
    response = upload(client, pdf(TEXT))
    status = response.json()["data"]["status"]
    assert status == "mismatch"
    log = text(client_root(), "validation")
    assert "event=validation.result.mismatch" in log and "event=validation.finding" in log and "reason=" in log


def test_unreachable_source_is_logged_as_a_warning(client, source):
    source[0][URL] = OSError("connection refused")
    response = upload(client, pdf(TEXT))
    status = response.json()["data"]["status"]
    log = text(client_root(), "validation")
    assert re.search(r"WARNING .*event=source.fetch.failed .*error=OSError", log)
    assert status in {"unable", "needs_review"} and re.search(rf"WARNING .*event=validation.result.{status}", log)


def test_missing_pdf_is_logged(client):
    response = client.post("/api/pdf-validations", data={"content_uri": URL})
    assert response.status_code == 422
    assert "event=validation.request_invalid" in text(client_root(), "validation") and "missing=document" in text(client_root(), "validation")


def test_rejected_input_is_logged_with_its_reason(client):
    response = client.post("/api/pdf-validations", data={"content_uri": URL},
                           files={"document": ("notes.txt", b"plain text", "text/plain")})
    assert response.status_code == 400
    assert re.search(r"WARNING .*event=validation.rejected status=400", text(client_root(), "validation"))


def test_unexpected_errors_are_logged_once_with_a_traceback(client, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr("app.routers.pdf_validation.validate_pdf", explode)
    response = upload(client, pdf(TEXT))
    assert response.status_code == 500 and "boom" not in response.text
    content = text(client_root(), "application")
    assert content.count("Traceback (most recent call last)") == 1 and "RuntimeError: boom" in content
    assert "event=validation.failed" in content and "file=upload.pdf" in content


def test_user_actions_from_the_interface_are_recorded_without_secrets(client):
    response = client.post("/api/client-events", json={"event": "validate_clicked", "detail": {"files": 3, "api_key": "sk-secret", "note": "ok\nline"}})
    assert response.status_code == 204
    log = text(client_root(), "validation")
    assert "event=ui.validate_clicked" in log and "files=3" in log and "sk-secret" not in log
    assert client.post("/api/client-events", json={"event": "Bad Name!"}).status_code == 422
    client.post("/api/client-events", json={"event": "engine_failed", "level": "error", "channel": "app"})
    assert "event=ui.engine_failed" in text(client_root(), "application")
