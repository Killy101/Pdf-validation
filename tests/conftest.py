"""Fixtures shared by the PDF validation tests."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.config import settings
from app.routers.pdf_validation import router
from app.services import pdf_validation as service


@pytest.fixture
def source(monkeypatch):
    documents, calls = {}, []
    def retrieve(url, hosts, max_bytes, timeout):
        calls.append(url)
        value = documents[url]
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(service, "fetch_source", retrieve)
    monkeypatch.setattr(settings, "PDF_VALIDATION_ALLOWED_HOSTS", [])
    return documents, calls


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role="user")
    with TestClient(app) as client:
        yield client


@pytest.fixture
def batch_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PDF_VALIDATION_BATCH_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setattr(settings, "PDF_VALIDATION_ALLOWED_HOSTS", [])
    return tmp_path / "snapshots"
