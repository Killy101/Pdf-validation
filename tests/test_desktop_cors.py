"""The desktop shell serves the interface from app://local, and the dev server from localhost:3000."""
from fastapi.testclient import TestClient
import pytest

from app.desktop_main import app


@pytest.mark.parametrize("origin", ["app://local", "http://localhost:3000"])
def test_interface_origins_may_call_the_backend(origin):
    with TestClient(app) as client:
        preflight = client.options("/api/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET",
                                                           "Access-Control-Request-Headers": "authorization"})
        assert preflight.status_code == 200 and preflight.headers["access-control-allow-origin"] == origin


def test_other_origins_are_refused():
    with TestClient(app) as client:
        preflight = client.options("/api/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" not in preflight.headers
