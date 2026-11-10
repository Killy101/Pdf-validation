"""Lets the UI record user actions and frontend errors in the same session logs."""
import logging
import re
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api_responses import ApiRoute
from app.auth import User, get_current_user
from app.logging_setup import APP, SENSITIVE_KEY, VALIDATION, clean, log_event

router = APIRouter(route_class=ApiRoute, prefix="/client-events", tags=["Logging"])
LEVELS = {"info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}


class ClientEvent(BaseModel):
    event: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,63}$")
    level: Literal["info", "warning", "error"] = "info"
    channel: Literal["app", "validation"] = "validation"
    detail: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=12)


@router.post("", status_code=204)
def record_client_event(payload: ClientEvent, current_user: User = Depends(get_current_user)):
    fields = {re.sub(r"[^a-z0-9_]", "_", key.lower())[:32]:
              "***" if SENSITIVE_KEY.search(key) else clean(value, 200) if isinstance(value, str) else value
              for key, value in payload.detail.items()}
    log_event(APP if payload.channel == "app" else VALIDATION, LEVELS[payload.level], f"ui.{payload.event}", **fields)
