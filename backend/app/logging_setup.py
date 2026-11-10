"""Structured, dated log files shared by the sidecar, the desktop shell and the launcher.

Layout: logs/<YYYY-MM-DD>/{application,backend,validation}.log
Line:   <time> | <LEVEL> | <channel> | session=<id> req=<id> | event=<name> key=value ...
"""
import contextvars
from datetime import datetime, timedelta
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
from urllib.parse import parse_qsl, urlencode, urlsplit

from app.config import BACKEND_DIR, FROZEN, settings, user_data_dir

ROOT = "pdfv"
APP = logging.getLogger("pdfv.app")
BACKEND = logging.getLogger("pdfv.backend")
VALIDATION = logging.getLogger("pdfv.validation")
logging.getLogger(ROOT).addHandler(logging.NullHandler())

request_id = contextvars.ContextVar("request_id", default="-")
_session = settings.PDF_VALIDATION_SESSION_ID or f"{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}"
_handlers: list[tuple[logging.Logger, logging.Handler]] = []
_reported = False
log_root: Path | None = None

FORMAT = "%(asctime)s | %(levelname)-8s | %(channel)s | session=%(session)s req=%(request)s | %(message)s"
_PLAIN = re.compile(r"[\w./:@%+\-]+\Z")
SENSITIVE_KEY = re.compile(r"token|key|secret|passw|pwd|auth|sig|session|credential|jwt|bearer", re.I)
_SECRET_TEXT = re.compile(r"(?i)\b(bearer\s+)[\w.~+/=-]+|((?:token|key|secret|passw\w*|pwd|auth\w*|sig\w*|credential)s?=)[^\s&\"']+")


def session_id() -> str:
    return _session


def clean(value, limit: int = 300) -> str:
    """Single-line, secret-free text safe to place in a log field."""
    text = _SECRET_TEXT.sub(lambda m: (m.group(1) or m.group(2)) + "***", " ".join(str(value).split()))
    token = settings.PDF_VALIDATION_DESKTOP_TOKEN
    if token:
        text = text.replace(token, "***")
    return text if len(text) <= limit else text[:limit - 3] + "..."


def safe_url(url) -> str:
    """URL without credentials or fragment, with sensitive query values masked."""
    try:
        parts = urlsplit(str(url))
        host = parts.hostname or ""
        netloc = host + (f":{parts.port}" if parts.port else "")
        query = urlencode([(k, "REDACTED" if SENSITIVE_KEY.search(k) else v)
                           for k, v in parse_qsl(parts.query, keep_blank_values=True)])
        return clean(parts._replace(netloc=netloc, query=query, fragment="").geturl(), 400)
    except ValueError:
        return "invalid-url"


def _value(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    return text if _PLAIN.match(text) else json.dumps(text, ensure_ascii=False)


def log_event(logger: logging.Logger, level: int, event: str, /, *, exc_info=None, **fields) -> None:
    """Write one structured entry; logging problems never reach the caller."""
    try:
        parts = [f"event={event}"] + [f"{key}={_value(value)}" for key, value in fields.items() if value is not None]
        logger.log(level, " ".join(parts), exc_info=exc_info)
    except Exception:
        pass


def mark_logged(exc: BaseException) -> BaseException:
    exc._pdfv_logged = True
    return exc


def already_logged(exc: BaseException) -> bool:
    return getattr(exc, "_pdfv_logged", False)


class _Context(logging.Filter):
    def filter(self, record):
        record.session = _session
        record.request = request_id.get()
        record.channel = record.name[len(ROOT) + 1:] if record.name.startswith(ROOT + ".") else record.name
        return True


class _ApplicationOnly(logging.Filter):
    """The application log keeps shell/app events and every error from any channel."""

    def filter(self, record):
        return record.name.startswith("pdfv.app") or record.levelno >= logging.ERROR


class _Formatter(logging.Formatter):
    def formatTime(self, record, _datefmt=None):
        moment = datetime.fromtimestamp(record.created)
        return moment.strftime("%Y-%m-%d %H:%M:%S.") + f"{moment.microsecond // 1000:03d}"


class DailyFileHandler(RotatingFileHandler):
    """Writes logs/<date>/<name>.log, moves to a new folder at midnight and rotates by size."""

    def __init__(self, root: Path, basename: str, max_bytes: int, backups: int):
        self.root, self.basename, self.day = root, basename, ""
        super().__init__(self._path(), maxBytes=max_bytes, backupCount=backups, encoding="utf-8", delay=True)

    def _path(self) -> str:
        self.day = datetime.now().strftime("%Y-%m-%d")
        folder = self.root / self.day
        folder.mkdir(parents=True, exist_ok=True)
        return str(folder / f"{self.basename}.log")

    def emit(self, record):
        try:
            if datetime.now().strftime("%Y-%m-%d") != self.day:
                self.acquire()
                try:
                    if self.stream:
                        self.stream.close()
                        self.stream = None
                    self.baseFilename = os.path.abspath(self._path())
                finally:
                    self.release()
            super().emit(record)
        except Exception:
            self.handleError(record)

    def handleError(self, record):
        global _reported
        if not _reported:
            _reported = True
            sys.stderr.write("PDF Validation: a log entry could not be written.\n")


def prune_logs(root: Path, days: int) -> int:
    """Remove dated folders older than the retention period; returns how many were removed."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    removed = 0
    for folder in root.iterdir() if root.exists() else []:
        if folder.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", folder.name) and folder.name < cutoff:
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    return removed


def _resolve_root(requested: Path | None) -> Path:
    candidates = [requested] if requested else [
        Path(settings.PDF_VALIDATION_LOG_DIR) if settings.PDF_VALIDATION_LOG_DIR
        else user_data_dir() / "logs" if FROZEN else BACKEND_DIR.parent / "logs",
        Path(tempfile.gettempdir()) / "pdf-validation-logs"]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-test"
            probe.write_text("ok")
            probe.unlink()
            return candidate
        except OSError:
            sys.stderr.write(f"PDF Validation: log folder {candidate} is not writable.\n")
    raise OSError("No writable log folder is available.")


def _attach(logger: logging.Logger, handler: logging.Handler):
    logger.addHandler(handler)
    _handlers.append((logger, handler))


def shutdown_logging() -> None:
    for logger, handler in _handlers:
        logger.removeHandler(handler)
        handler.close()
    _handlers.clear()
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "py.warnings", ROOT):
        logging.getLogger(name).propagate = True
    logging.captureWarnings(False)
    if sys.excepthook is _excepthook:
        sys.excepthook = sys.__excepthook__
    if threading.excepthook is _thread_excepthook:
        threading.excepthook = threading.__excepthook__
    global log_root
    log_root = None


def _excepthook(kind, value, trace):
    log_event(APP, logging.CRITICAL, "process.unhandled_exception", exc_info=(kind, value, trace), error=kind.__name__)


def _thread_excepthook(args):
    log_event(APP, logging.CRITICAL, "thread.unhandled_exception", thread=getattr(args.thread, "name", None),
              exc_info=(args.exc_type, args.exc_value, args.exc_traceback), error=args.exc_type.__name__)


def setup_logging(root: Path | None = None, force: bool = False) -> Path | None:
    """Attach the three log files; returns the log folder, or None if logging is unavailable."""
    global log_root
    if log_root and not force:
        return log_root
    shutdown_logging()
    try:
        folder = _resolve_root(root)
        level = getattr(logging, settings.PDF_VALIDATION_LOG_LEVEL.upper(), logging.INFO)
        formatter, context = _Formatter(FORMAT), _Context()

        def handler(name, only_app=False):
            item = DailyFileHandler(folder, name, settings.PDF_VALIDATION_LOG_MAX_BYTES, settings.PDF_VALIDATION_LOG_BACKUPS)
            item.setLevel(level)
            item.setFormatter(formatter)
            item.addFilter(context)
            if only_app:
                item.addFilter(_ApplicationOnly())
            return item

        root_logger = logging.getLogger(ROOT)
        root_logger.setLevel(level)
        root_logger.propagate = False
        application, backend, validation = handler("application", True), handler("backend"), handler("validation")
        _attach(root_logger, application)
        _attach(BACKEND, backend)
        _attach(VALIDATION, validation)
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "py.warnings"):
            logger = logging.getLogger(name)
            logger.propagate = False
            logger.setLevel(level)
            _attach(logger, backend)
        _attach(logging.getLogger("uvicorn.error"), application)
        logging.captureWarnings(True)
        sys.excepthook = _excepthook
        threading.excepthook = _thread_excepthook
        log_root = folder
        removed = prune_logs(folder, settings.PDF_VALIDATION_LOG_RETENTION_DAYS)
        log_event(APP, logging.INFO, "logging.ready", folder=str(folder), level=logging.getLevelName(level), pruned_days=removed)
        return folder
    except Exception as exc:
        sys.stderr.write(f"PDF Validation: logging is unavailable ({type(exc).__name__}).\n")
        return None
