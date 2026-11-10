"""Local-only authentication: the desktop shell shares one random token with the sidecar."""
from dataclasses import dataclass
import hmac

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class User:
    id: int = 1
    role: str = "user"


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    expected = settings.PDF_VALIDATION_DESKTOP_TOKEN
    if not expected or not credentials or not hmac.compare_digest(credentials.credentials.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    return User()
