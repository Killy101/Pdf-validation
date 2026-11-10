"""Command lines for the isolated analysis workers, from source or from the packaged executable."""
import importlib
import sys

from app.config import FROZEN

WORKERS = {
    "app.services.pdf_validation_worker",
    "app.services.pdf_validation_archive_worker",
    "app.services.pdf_validation_export_worker",
    "app.services.pdf_validation_search_worker",
}


def frozen() -> bool:
    return FROZEN


def worker_command(module: str) -> list[str]:
    if module not in WORKERS:
        raise ValueError(f"Unknown worker module: {module}")
    # A packaged executable has no "-m"; it runs the worker itself when given --worker.
    return [sys.executable, "--worker", module] if frozen() else [sys.executable, "-m", module]


def run_worker(module: str) -> None:
    if module not in WORKERS:
        raise SystemExit(f"Unknown worker module: {module}")
    importlib.import_module(module).main()
