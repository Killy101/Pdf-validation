"""Shared JSON envelope for API routes and errors (hub contract without the database errors)."""
from functools import wraps
from http import HTTPStatus
from inspect import iscoroutinefunction, signature
import logging
from typing import Any, Generic, Literal, TypeVar

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, JSONResponse

from app.logging_setup import BACKEND, VALIDATION, already_logged, log_event

T = TypeVar("T")


class ApiSuccess(BaseModel, Generic[T]):
    success: Literal[True] = True
    message: str
    data: T


class ApiError(BaseModel):
    code: str
    details: Any = None


class ApiFailure(BaseModel):
    success: Literal[False] = False
    message: str
    data: None = None
    error: ApiError


def success_response(data: Any, message: str = "Request completed successfully") -> dict | Response:
    if isinstance(data, Response):
        return data
    if isinstance(data, dict) and isinstance(data.get("message"), str):
        message = data["message"]
        if set(data) == {"message"}:
            data = None
    return {"success": True, "message": message, "data": data}


def error_response(status: int, message: str, details: Any, headers=None) -> JSONResponse:
    code = "VALIDATION_ERROR" if status == 422 else HTTPStatus(status).name
    body = ApiFailure(message=message, error=ApiError(code=code, details=details))
    return JSONResponse(body.model_dump(mode="json"), status_code=status, headers=headers)


async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    if exc.status_code >= 500:
        message = HTTPStatus(exc.status_code).phrase
    return error_response(exc.status_code, message, message if exc.status_code >= 500 else exc.detail, exc.headers)


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [{"type": item["type"], "loc": list(item["loc"]), "msg": item["msg"]} for item in exc.errors()]
    fields = ",".join(".".join(str(part) for part in item["loc"]) for item in details)
    log_event(BACKEND, logging.WARNING, "request.invalid", method=request.method, path=request.url.path, fields=fields)
    if request.url.path.startswith("/api/pdf-validations"):
        missing = [item["loc"][-1] for item in details if item["type"] == "missing"]
        log_event(VALIDATION, logging.WARNING, "validation.request_invalid", path=request.url.path, fields=fields,
                  missing=",".join(map(str, missing)) or None)
    return error_response(422, "Request validation failed", details)


async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    if not already_logged(exc):
        log_event(BACKEND, logging.ERROR, "request.unhandled_error", exc_info=exc, error=type(exc).__name__,
                  method=request.method, path=request.url.path)
    return error_response(500, "Internal server error", "The request could not be completed")


def install_error_handlers(app: FastAPI) -> None:
    for exception, handler in (
        (HTTPException, http_error), (RequestValidationError, validation_error), (Exception, unexpected_error),
    ):
        app.add_exception_handler(exception, handler)


class ApiRoute(APIRoute):
    def __init__(self, path, endpoint, *, response_model=None, **kwargs):
        if not getattr(endpoint, "_api_enveloped", False) and kwargs.get("status_code") != 204:
            original = endpoint
            default_status = kwargs.get("status_code") or 200

            def respond(result, values):
                status = getattr(values.get("response"), "status_code", None) or default_status
                message = "Resource created successfully" if status == 201 else "Request completed successfully"
                return success_response(result, message)

            if iscoroutinefunction(original):
                @wraps(original)
                async def endpoint(*args, **values):
                    return respond(await original(*args, **values), values)
            else:
                @wraps(original)
                def endpoint(*args, **values):
                    return respond(original(*args, **values), values)
            endpoint.__signature__ = signature(original, eval_str=True)
            endpoint._api_enveloped = True
            if getattr(kwargs.get("response_class"), "value", kwargs.get("response_class")) is FileResponse:
                response_model = None
            else:
                response_model = ApiSuccess[getattr(response_model, "value", response_model) or Any]
        responses = {code: {"model": ApiFailure} for code in (400, 401, 403, 404, 409, 422, 500, 503)}
        responses.update(kwargs.pop("responses", None) or {})
        super().__init__(path, endpoint, response_model=response_model, responses=responses, **kwargs)

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            try:
                return await handler(request)
            except HTTPException as exc:
                return await http_error(request, exc)
            except RequestValidationError as exc:
                return await validation_error(request, exc)
            except Exception as exc:
                return await unexpected_error(request, exc)

        return handle
