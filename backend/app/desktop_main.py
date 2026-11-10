"""FastAPI application served on localhost by the desktop sidecar."""
from contextlib import asynccontextmanager
import logging
import os
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api_responses import install_error_handlers, success_response
from app.config import settings
from app.logging_setup import APP, log_event, request_id
from app.routers.client_events import router as client_events_router
from app.routers.pdf_validation import router as pdf_validation_router

HTTP = logging.getLogger("pdfv.backend.http")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event(APP, logging.INFO, "backend.ready", pid=os.getpid())
    yield
    log_event(APP, logging.INFO, "backend.stopping", pid=os.getpid())


app = FastAPI(title="PDF Validation Desktop", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
install_error_handlers(app)


@app.middleware("http")
async def access_log(request: Request, call_next):
    """Tag each request with an id and record its method, path, status and duration."""
    rid = uuid.uuid4().hex[:8]
    marker = request_id.set(rid)
    started = time.perf_counter()
    quiet = request.url.path == "/api/health"
    try:
        response = await call_next(request)
    except Exception as exc:
        log_event(HTTP, logging.ERROR, "http.failed", exc_info=exc, method=request.method, path=request.url.path)
        raise
    else:
        status = response.status_code
        level = logging.DEBUG if quiet and status < 400 else logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
        log_event(HTTP, level, "http.request", method=request.method, path=request.url.path, status=status,
                  elapsed_ms=int((time.perf_counter() - started) * 1000))
        response.headers["X-Request-Id"] = rid
        return response
    finally:
        request_id.reset(marker)


app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["Authorization", "Content-Type"],
                   expose_headers=["Content-Disposition", "Retry-After", "X-Request-Id"])
app.include_router(pdf_validation_router, prefix="/api")
app.include_router(client_events_router, prefix="/api")


@app.get("/api/health")
def health():
    return success_response({"status": "ok"})
