"""Desktop settings: the PDF validation limits from the hub plus the local sidecar options."""
import os
import sys
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

FROZEN = bool(getattr(sys, "frozen", False))
# Packaged: the folder holding pdf-validation-backend.exe (read-only under Program Files). From source: backend/.
BACKEND_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    """Writable per-user folder for logs and temporary data when the shell does not choose one."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "PDF Validation"


def env_file() -> Path:
    if os.environ.get("PDF_VALIDATION_ENV_FILE"):
        return Path(os.environ["PDF_VALIDATION_ENV_FILE"])
    return user_data_dir() / "backend.env" if FROZEN else BACKEND_DIR / ".env"


class Settings(BaseSettings):
    # Shared secret the desktop shell passes to the sidecar; empty rejects every request.
    PDF_VALIDATION_DESKTOP_TOKEN: str = Field(default="", repr=False)
    # Logging: the launcher and shell pass the folder and session; limits keep logs from growing without bound.
    PDF_VALIDATION_LOG_DIR: str | None = None
    PDF_VALIDATION_SESSION_ID: str | None = None
    PDF_VALIDATION_LOG_LEVEL: str = "INFO"
    PDF_VALIDATION_LOG_MAX_BYTES: int = Field(default=5 * 1024 * 1024, ge=64 * 1024)
    PDF_VALIDATION_LOG_BACKUPS: int = Field(default=5, ge=1, le=50)
    PDF_VALIDATION_LOG_RETENTION_DAYS: int = Field(default=30, ge=1, le=3650)
    CORS_ORIGINS: list[str] = [
        "app://local", "http://localhost:3000", "http://127.0.0.1:3000",
    ]
    PDF_VALIDATION_MAX_BYTES: int = Field(default=100 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    PDF_VALIDATION_MAX_FILES: int = Field(default=10, ge=1, le=10)
    PDF_VALIDATION_MAX_VERSIONS: int = Field(default=10, ge=1, le=20)
    PDF_VALIDATION_MAX_HTML_BYTES: int = Field(default=8 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    PDF_VALIDATION_ZIP_MAX_FILES: int = Field(default=1000, ge=1, le=10000)
    PDF_VALIDATION_ZIP_MAX_EXPANDED_BYTES: int = Field(default=128 * 1024 * 1024, ge=1024, le=256 * 1024 * 1024)
    PDF_VALIDATION_MAX_PAGES: int = Field(default=2000, ge=1, le=2000)
    PDF_VALIDATION_MAX_CHARACTERS: int = Field(default=12000000, ge=1000, le=24000000)
    PDF_VALIDATION_TIMEOUT_SECONDS: float = Field(default=180, ge=1, le=600)
    PDF_VALIDATION_MAX_CONCURRENT: int = Field(default=2, ge=1, le=8)
    PDF_VALIDATION_MEMORY_MB: int = Field(default=1024, ge=128, le=2048)
    PDF_VALIDATION_EXPORT_FONT_PATH: str | None = None
    PDF_VALIDATION_ALLOWED_HOSTS: list[str] = []
    PDF_VALIDATION_CRAWL_MAX_PAGES: int = Field(default=50, ge=1, le=200)
    PDF_VALIDATION_CRAWL_MAX_SECTIONS: int = Field(default=1000, ge=1, le=5000)
    PDF_VALIDATION_CRAWL_MAX_DEPTH: int = Field(default=3, ge=0, le=6)
    PDF_VALIDATION_CRAWL_MAX_BYTES: int = Field(default=32 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    PDF_VALIDATION_DISCOVERY_MAX_PAGES: int = Field(default=30, ge=1, le=200)
    PDF_VALIDATION_DISCOVERY_MAX_DEPTH: int = Field(default=4, ge=1, le=8)
    PDF_VALIDATION_DISCOVERY_VERIFY: int = Field(default=5, ge=1, le=20)
    PDF_VALIDATION_BROWSER_ENABLED: bool = True
    PDF_VALIDATION_BROWSER_MAX_PAGES: int = Field(default=5, ge=0, le=20)
    PDF_VALIDATION_BROWSER_MAX_REQUESTS: int = Field(default=80, ge=1, le=300)
    PDF_VALIDATION_BROWSER_CHANNEL: str | None = None
    PDF_VALIDATION_BROWSER_RULES: dict[str, dict] = {}
    PDF_VALIDATION_RETRY_ATTEMPTS: int = Field(default=3, ge=1, le=5)
    PDF_VALIDATION_RETRY_DELAY_SECONDS: float = Field(default=1, ge=0, le=10)
    PDF_VALIDATION_MAX_RETRY_WAIT_SECONDS: float = Field(default=10, ge=0, le=60)
    PDF_VALIDATION_FETCH_SOCKET_TIMEOUT_SECONDS: float = Field(default=30, ge=1, le=600)
    PDF_VALIDATION_BATCH_DIR: str | None = None
    PDF_VALIDATION_BATCH_TTL_SECONDS: int = Field(default=900, ge=60, le=3600)
    PDF_VALIDATION_MAX_BATCHES: int = Field(default=8, ge=1, le=64)
    PDF_VALIDATION_BATCH_MAX_BYTES: int = Field(default=256 * 1024 * 1024, ge=1024, le=1024 * 1024 * 1024)
    model_config = SettingsConfigDict(env_file=env_file(), extra="ignore", hide_input_in_errors=True)


settings = Settings()
