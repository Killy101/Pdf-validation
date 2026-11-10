"""Owner-scoped temporary source snapshots shared by a validation batch."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from uuid import uuid4

from app.config import settings
from app.services.pdf_validation_access import SourceAccessError, ensure_source_access
from app.services.pdf_validation_source import SourceSnapshot
from reflink.url.targets import valid_url_target


class BatchUnavailable(ValueError):
    pass


def _root():
    root = Path(settings.PDF_VALIDATION_BATCH_DIR or Path(tempfile.gettempdir()) / "reflink-pdf-snapshots").resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def _path(batch_id):
    if not re.fullmatch(r"[0-9a-f]{32}", batch_id):
        raise BatchUnavailable("The PDF validation batch is invalid or unavailable. Start a new validation.")
    root = _root()
    path = root / ("batch-" + batch_id)
    if path.is_symlink() or path.resolve().parent != root or not path.is_dir():
        raise BatchUnavailable("The PDF validation batch is invalid or unavailable. Start a new validation.")
    return path


@contextmanager
def _lock(path):
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BlockingIOError("This PDF validation batch is busy. Try again shortly.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read(path):
    try:
        metadata = json.loads((path / "batch.json").read_text(encoding="utf-8"))
        if (not isinstance(metadata, dict) or not isinstance(metadata.get("owner"), int)
                or not isinstance(metadata.get("expires"), (int, float))
                or not re.fullmatch(r"[0-9a-f]{64}", metadata.get("binding", ""))):
            raise ValueError("Invalid batch metadata")
        return metadata
    except (OSError, TypeError, ValueError) as exc:
        raise BatchUnavailable("The PDF validation batch is unavailable. Start a new validation.") from exc


def _remove(path):
    if not path.is_symlink() and path.resolve().parent == _root() and re.fullmatch(r"batch-[0-9a-f]{32}", path.name):
        shutil.rmtree(path, ignore_errors=True)


def _binding(url, reference, options):
    value = {"url": url.strip(), "reference": reference or None,
             "options": options.model_dump(mode="json", include={"jurisdiction", "workflow", "date_start", "date_end", "history_url", "archive_member", "source_mode"}),
             "hosts": list(settings.PDF_VALIDATION_ALLOWED_HOSTS)}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _check(path, owner, binding=None):
    metadata = _read(path)
    if (metadata["owner"] != owner or metadata["expires"] <= time.time() or (path / "closing").exists()
            or binding is not None and metadata["binding"] != binding):
        raise BatchUnavailable("The PDF validation batch is expired or does not match this request. Start a new validation.")
    return metadata


def create_batch(owner, url, reference, options):
    if not valid_url_target(url.strip()):
        raise ValueError("Enter a valid HTTP or HTTPS document URL without embedded credentials.")
    if reference and (options.workflow == "date_range" or not valid_url_target(reference)):
        raise ValueError("Use a valid reference PDF URL for the current workflow only.")
    root = _root()
    with _lock(root / "index.lock"):
        active = 0
        for path in root.glob("batch-*"):
            if path.is_symlink() or path.resolve().parent != root or not re.fullmatch(r"batch-[0-9a-f]{32}", path.name):
                continue
            try:
                expired = _read(path)["expires"] <= time.time() or (path / "closing").exists()
                if expired:
                    with _lock(path / "batch.lock"):
                        expired = _read(path)["expires"] <= time.time() or (path / "closing").exists()
                    if expired:
                        _remove(path)
                    else:
                        active += 1
                else:
                    active += 1
            except BlockingIOError:
                active += 1
            except ValueError:
                active += 1
        if active >= settings.PDF_VALIDATION_MAX_BATCHES:
            raise BlockingIOError("PDF validation batches are busy. Try again shortly.")
        batch_id = uuid4().hex
        path = root / ("batch-" + batch_id)
        path.mkdir(mode=0o700)
        expires = time.time() + settings.PDF_VALIDATION_BATCH_TTL_SECONDS
        (path / "batch.json").write_text(json.dumps({"owner": owner, "expires": expires,
            "binding": _binding(url, reference, options)}), encoding="utf-8")
    return {"batch_id": batch_id, "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat()}


def close_batch(batch_id, owner):
    path = _path(batch_id)
    if _read(path)["owner"] != owner:
        raise ValueError("The PDF validation batch is unavailable.")
    try:
        with _lock(path / "batch.lock"):
            (path / "closing").touch()
        _remove(path)
    except BlockingIOError:
        (path / "closing").touch()


@contextmanager
def batch_fetch(batch_id, owner, url, reference, options, fetch):
    path = _path(batch_id)
    binding = _binding(url, reference, options)
    _check(path, owner, binding)
    acquired = False
    try:
        with _lock(path / "batch.lock"):
            acquired = True
            metadata = _check(path, owner, binding)
            metadata["expires"] = time.time() + settings.PDF_VALIDATION_BATCH_TTL_SECONDS
            (path / "batch.json").write_text(json.dumps(metadata), encoding="utf-8")

            def retrieve(target, hosts, max_bytes, timeout):
                key = hashlib.sha256(json.dumps([target, list(hosts)]).encode()).hexdigest()
                data_path, info_path = path / (key + ".bin"), path / (key + ".json")
                if info_path.exists() or data_path.exists():
                    try:
                        info = json.loads(info_path.read_text(encoding="utf-8"))
                        if not isinstance(info, dict):
                            raise ValueError("Invalid snapshot metadata")
                        if data_path.stat().st_size > max_bytes:
                            raise ValueError("The cached source exceeds the configured size limit.")
                        data = data_path.read_bytes()
                        digest = info.pop("sha256")
                        if hashlib.sha256(data).hexdigest() != digest:
                            raise ValueError("The cached source snapshot is damaged. Start a new validation.")
                        return SourceSnapshot(data=data, **info)
                    except (OSError, TypeError, KeyError, ValueError) as exc:
                        raise SourceAccessError("unavailable", "The source snapshot is unavailable. Start a new validation.") from exc
                snapshot = fetch(target, hosts, max_bytes, timeout)
                ensure_source_access(snapshot)
                size = sum(item.stat().st_size for item in path.glob("*.bin"))
                if len(snapshot.data) > max_bytes or size + len(snapshot.data) > settings.PDF_VALIDATION_BATCH_MAX_BYTES:
                    raise SourceAccessError("unavailable", "This batch exceeds the source snapshot limit. Use fewer historical versions or smaller sources.")
                snapshot.retrieved_at = snapshot.retrieved_at or datetime.now(timezone.utc).isoformat()
                info = {"url": snapshot.url, "kind": snapshot.kind, "content_type": snapshot.content_type,
                        "retrieved_at": snapshot.retrieved_at, "retrieval_attempts": snapshot.retrieval_attempts,
                        "sha256": hashlib.sha256(snapshot.data).hexdigest()}
                data_path.write_bytes(snapshot.data)
                info_path.write_text(json.dumps(info), encoding="utf-8")
                return snapshot

            try:
                yield retrieve
            finally:
                metadata["expires"] = time.time() + settings.PDF_VALIDATION_BATCH_TTL_SECONDS
                (path / "batch.json").write_text(json.dumps(metadata), encoding="utf-8")
    finally:
        if acquired and (path / "closing").exists():
            _remove(path)
